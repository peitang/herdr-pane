import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "herdr_pane.py"


def load_module():
    if not MODULE.exists():
        return None
    spec = importlib.util.spec_from_file_location("herdr_pane", MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


app = load_module()


def profile(**changes):
    data = dict(id="profile_a", label="build-box", target="developer@build.example.invalid",
                session="review", enabled=True, selected=False)
    data.update(changes)
    return data


def agent(**changes):
    data = dict(agent="codex", agent_status="working", name="reviewer",
                pane_id="pane_a", terminal_id="terminal_a", cwd="~/projects/sample-app",
                focused=False, revision=3)
    data.update(changes)
    return data


def payload(*rows):
    return {"result": {"agents": list(rows), "type": "agent_list"}}


class SelectorTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(app, "The selector implementation does not exist yet")

    def test_disabled_profiles_are_not_queried(self):
        sources, errors = app.parse_sources([profile(), profile(id="disabled", enabled=False)])
        self.assertEqual([s.profile_id for s in sources], ["profile_a"])
        self.assertEqual(errors, [])

    def test_malformed_profile_does_not_drop_valid_profiles(self):
        sources, errors = app.parse_sources([profile(), profile(id="broken", target="-oProxyCommand=bad")])
        self.assertEqual([s.profile_id for s in sources], ["profile_a"])
        self.assertEqual(len(errors), 1)

    def test_duplicate_names_and_panes_remain_bound_to_source(self):
        remote = app.parse_sources([profile()])[0][0]
        rows = app.parse_agents(payload(agent()), app.LOCAL)
        rows += app.parse_agents(payload(agent()), remote)
        self.assertEqual([r.source.profile_id for r in rows], [None, "profile_a"])
        self.assertEqual(len(rows), 2)

    def test_shells_are_omitted_and_missing_status_is_unknown(self):
        rows = app.parse_agents(payload(agent(agent=None), agent(agent="shell"), agent(agent_status=None)), app.LOCAL)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "unknown")

    def test_invalid_terminal_identity_is_rejected(self):
        with self.assertRaises(app.PaneError):
            app.parse_agents(payload(agent(terminal_id="$(touch bad)")), app.LOCAL)

    def test_invalid_agent_response_is_not_silently_an_empty_list(self):
        with self.assertRaises(app.PaneError):
            app.parse_agents({"result": {}}, app.LOCAL)

    def test_one_offline_source_does_not_hide_other_agents(self):
        def query(args):
            if args == ["machine", "list", "--json"]:
                return [profile(), profile(id="offline", label="offline-box")]
            if args[:2] == ["--machine", "offline"]:
                raise app.PaneError("timeout")
            return payload(agent())
        rows, errors, count = app.inventory(query)
        self.assertEqual([r.source.profile_id for r in rows], [None, "profile_a"])
        self.assertEqual(count, 2)
        self.assertEqual(len(errors), 1)

    def test_local_failure_still_lists_remote_agents(self):
        def query(args):
            if args == ["machine", "list", "--json"]:
                return [profile()]
            if args == ["agent", "list"]:
                raise app.PaneError("local server unavailable")
            return payload(agent())
        rows, errors, count = app.inventory(query)
        self.assertEqual([r.source.profile_id for r in rows], ["profile_a"])
        self.assertEqual(len(errors), 1)

    def test_changed_profile_aborts_before_remote_query(self):
        source = app.parse_sources([profile()])[0][0]
        row = app.parse_agents(payload(agent()), source)[0]
        calls = []
        def query(args):
            calls.append(args)
            return [profile(session="different")]
        with self.assertRaises(app.PaneError):
            app.revalidate(row, query)
        self.assertEqual(calls, [["machine", "list", "--json"]])

    def test_replaced_terminal_and_missing_agent_are_not_attached(self):
        row = app.parse_agents(payload(agent()), app.LOCAL)[0]
        for value in (payload(), payload(agent(terminal_id="terminal_b"))):
            with self.subTest(value=value), self.assertRaises(app.PaneError):
                app.revalidate(row, lambda args: value)

    def test_revalidation_uses_same_machine_and_checks_terminal(self):
        source = app.parse_sources([profile()])[0][0]
        row = app.parse_agents(payload(agent()), source)[0]
        calls = []
        def query(args):
            calls.append(args)
            return [profile()] if args[0] == "machine" else payload(agent())
        app.revalidate(row, query)
        self.assertEqual(calls, [["machine", "list", "--json"], ["--machine", "profile_a", "agent", "list"]])

    def test_terminal_controls_and_bidi_are_not_rendered(self):
        clean = app.display_text("hello\x1b[31m\nworld\x1b]0;fake\x07\u202eevil")
        self.assertNotIn("\x1b", clean)
        self.assertNotIn("\x07", clean)
        self.assertNotIn("\u202e", clean)
        self.assertNotIn("\n", clean)

    def test_ssh_target_rejects_option_and_command_injection(self):
        for target in ("-oProxyCommand=x", "host;touch x", "$(id)", "host\nnext", "a b", "", "host`id`"):
            with self.subTest(target=target), self.assertRaises(app.PaneError):
                app.validate_target(target)
        for target in ("build-box", "developer@build.example.invalid", "ssh://developer@build.example.invalid:2222", "ssh://developer@[2001:db8::1]"):
            self.assertEqual(app.validate_target(target), target)

    def test_attach_uses_terminal_id_and_never_takeover(self):
        row = app.parse_agents(payload(agent()), app.LOCAL)[0]
        self.assertEqual(app.attach_command(row, "/tools/herdr", "/tools/ssh"), ["/tools/herdr", "terminal", "attach", "terminal_a"])
        remote = app.parse_sources([profile()])[0][0]
        row = app.parse_agents(payload(agent()), remote)[0]
        command = app.attach_command(row, "/tools/herdr", "/tools/ssh")
        self.assertEqual(command[:4], ["/tools/ssh", "-t", "--", "developer@build.example.invalid"])
        self.assertIn("--session review terminal attach terminal_a", command[4])
        self.assertNotIn("--takeover", command[4])

    def test_native_setup_passes_target_and_explicit_session_as_arguments(self):
        calls = []
        def run(args):
            calls.append(args)
            return 0
        app.add_remote("build-box", "review", "/tools/herdr", run)
        self.assertEqual(calls, [["/tools/herdr", "machine", "add", "build-box", "--remote-session", "review"]])

    def test_query_timeout_terminates_child(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "slow"
            script.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n")
            script.chmod(0o755)
            query = app.QueryRunner(str(script), 0.1)
            with self.assertRaises(app.PaneError):
                query(["agent", "list"])
            self.assertFalse(query.active)

    def test_query_invalid_json_is_diagnosed(self):
        query = app.QueryRunner(sys.executable, 2)
        with self.assertRaises(app.PaneError):
            query(["-c", "print('not json')"])

    def test_timeout_does_not_wait_for_detached_descendant_holding_output(self):
        with tempfile.TemporaryDirectory() as directory:
            pid_file = Path(directory) / "child.pid"
            script = Path(directory) / "query"
            script.write_text(
                "#!" + sys.executable + "\nimport subprocess,sys,time\n"
                "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(4)'], start_new_session=True)\n"
                "open(" + repr(str(pid_file)) + ",'w').write(str(child.pid))\n"
                "time.sleep(30)\n"
            )
            script.chmod(0o755)
            started = time.monotonic()
            try:
                with self.assertRaises(app.PaneError) as error:
                    app.QueryRunner(str(script), 0.5)([])
                self.assertTrue(pid_file.exists(), str(error.exception))
                self.assertIn("逾時", str(error.exception))
                self.assertLess(time.monotonic() - started, 2)
            finally:
                if pid_file.exists():
                    try:
                        os.kill(int(pid_file.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_cancel_stops_query_and_rejects_queued_work(self):
        query = app.QueryRunner(sys.executable, 30)
        errors = []
        def run_query():
            try:
                query(["-c", "import time;time.sleep(30)"])
            except app.PaneError as error:
                errors.append(error)
        thread = threading.Thread(target=run_query)
        thread.start()
        deadline = time.monotonic() + 2
        while not query.active and time.monotonic() < deadline:
            time.sleep(0.01)
        query.cancel()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        with self.assertRaises(app.PaneError):
            query(["-c", "pass"])

    def test_known_native_error_code_survives_without_raw_error_text(self):
        query = app.QueryRunner(sys.executable, 2)
        code = "import sys,json;print(json.dumps({'error':{'code':'server_not_running','message':'private-detail'}}),file=sys.stderr);sys.exit(1)"
        with self.assertRaises(app.PaneError) as error:
            query(["-c", code])
        self.assertIn("server_not_running", str(error.exception))
        self.assertNotIn("private-detail", str(error.exception))

    def test_plain_bracket_ipv6_is_rejected_in_favor_of_ssh_uri(self):
        with self.assertRaises(app.PaneError):
            app.validate_target("developer@[2001:db8::1]")
        self.assertEqual(app.validate_target("ssh://developer@[2001:db8::1]"), "ssh://developer@[2001:db8::1]")

    def test_caller_pids_follows_parent_chain_not_other_processes(self):
        with patch.object(os, "getpid", return_value=430), \
             patch.object(subprocess, "check_output", return_value="430 420\n420 410\n410 1\n999 1\n"):
            self.assertEqual(app.caller_pids(), {430, 420, 410})

    def test_selection_rejects_out_of_range_without_choosing_another_row(self):
        for text in ("0", "-1", "3", "1;ls", "reviewer"):
            with self.subTest(text=text), self.assertRaises(app.PaneError):
                app.selection_index(text, 2)
        self.assertEqual(app.selection_index("2", 2), 1)
        self.assertIsNone(app.selection_index("", 2))

    def test_self_detection_uses_process_ancestry_not_focus_or_inherited_id(self):
        row = app.parse_agents(payload(agent(focused=True)), app.LOCAL)[0]
        unrelated = {"result": {"process_info": {"shell_pid": 410, "foreground_processes": []}}}
        own = {"result": {"process_info": {"shell_pid": 420, "foreground_processes": []}}}
        self.assertFalse(app.is_own_terminal(row, lambda args: unrelated, {420, 421}))
        self.assertTrue(app.is_own_terminal(row, lambda args: own, {420, 421}))

    def test_unverifiable_local_process_identity_is_not_assumed_safe(self):
        row = app.parse_agents(payload(agent()), app.LOCAL)[0]
        with self.assertRaises(app.PaneError):
            app.is_own_terminal(row, lambda args: {"result": {}}, {420})

    def test_menu_selection_keeps_snapshot_when_live_order_changes(self):
        first = agent()
        second = agent(pane_id="pane_b", terminal_id="terminal_b")
        agent_queries = 0
        def query(args):
            nonlocal agent_queries
            if args == ["machine", "list", "--json"]:
                return []
            agent_queries += 1
            return payload(first, second) if agent_queries == 1 else payload(second, first)
        commands = []
        with patch.object(app, "find_herdr", return_value="/tools/herdr"), \
             patch.object(app, "QueryRunner", return_value=query), \
             patch.object(app, "caller_pids", return_value=set()), \
             patch.object(sys, "stdin", Tty()), patch.object(sys, "stdout", Tty()), \
             patch("builtins.input", side_effect=["invalid", "1"]), \
             patch.object(app, "interactive_run", side_effect=lambda args: commands.append(args) or 0):
            self.assertEqual(app.main([]), 0)
        self.assertEqual(commands, [["/tools/herdr", "terminal", "attach", "terminal_a"]])

    def test_failed_attach_returns_to_menu_without_automatic_retry(self):
        def query(args):
            return [] if args[0] == "machine" else payload(agent())
        commands = []
        with patch.object(app, "find_herdr", return_value="/tools/herdr"), \
             patch.object(app, "QueryRunner", return_value=query), \
             patch.object(app, "caller_pids", return_value=set()), \
             patch.object(sys, "stdin", Tty()), patch.object(sys, "stdout", Tty()), \
             patch("builtins.input", side_effect=["1", ""]), \
             patch.object(app, "interactive_run", side_effect=lambda args: commands.append(args) or 1):
            self.assertEqual(app.main([]), 0)
        self.assertEqual(len(commands), 1)

    def test_setup_returns_to_refreshed_inventory(self):
        events = []
        def query(args):
            events.append("query")
            return [] if args[0] == "machine" else payload()
        def run(args):
            events.append("setup")
            return 0
        with patch.object(app, "find_herdr", return_value="/tools/herdr"), \
             patch.object(app, "QueryRunner", return_value=query), \
             patch.object(app, "caller_pids", return_value=set()), \
             patch.object(sys, "stdin", Tty()), patch.object(sys, "stdout", Tty()), \
             patch("builtins.input", side_effect=["build-box", "", ""]), \
             patch.object(app, "interactive_run", side_effect=run):
            self.assertEqual(app.main(["--add-remote"]), 0)
        self.assertEqual(events[0], "setup")
        self.assertIn("query", events[1:])

    def test_list_distinguishes_empty_inventory_from_all_sources_failing(self):
        for failed, expected in ((False, 0), (True, 1)):
            def query(args):
                if args[0] == "machine":
                    return []
                if failed:
                    raise app.PaneError("server unavailable")
                return payload()
            output = io.StringIO()
            with self.subTest(failed=failed), \
                 patch.object(app, "find_herdr", return_value="/tools/herdr"), \
                 patch.object(app, "QueryRunner", return_value=query), \
                 patch.object(app, "caller_pids", return_value=set()), \
                 patch.object(sys, "stdout", output):
                self.assertEqual(app.main(["--list"]), expected)
            self.assertIn("--add-remote", output.getvalue())


class RemoteRemovalTests(unittest.TestCase):
    def execute(self, snapshots, answers, args=None, native_exit=0, tty=True):
        snapshots = iter(snapshots)
        calls = []
        output = Tty()
        def query(argv):
            if argv != ["machine", "list", "--json"]:
                raise AssertionError("Removal must not query or connect to an agent")
            result = next(snapshots)
            if isinstance(result, Exception):
                raise result
            return result
        def run(argv):
            calls.append(argv)
            return native_exit
        with patch.object(app, "find_herdr", return_value="/tools/herdr"), \
             patch.object(app, "QueryRunner", return_value=query), \
             patch.object(sys, "stdin", Tty() if tty else io.StringIO()), \
             patch.object(sys, "stdout", output), patch.object(sys, "stderr", output), \
             patch("builtins.input", side_effect=answers), \
             patch.object(app, "interactive_run", side_effect=run):
            try:
                result = app.main(args or ["--remove-remote"])
            except SystemExit as error:
                self.fail("Removal option must reach the workflow, not argparse exit {}".format(error.code))
        return result, calls, output.getvalue()

    def test_confirmed_selection_removes_disabled_broken_target_by_id(self):
        chosen = profile(enabled=False, target="unsupported target", label="build-box\x1b[31m")
        other = profile(id="profile_b", label="other-box")
        code, calls, output = self.execute(
            [[chosen, other], [other, chosen], [other]], ["bad", "999", "1", "yes"],
        )
        self.assertEqual(code, 0)
        self.assertEqual(calls, [["/tools/herdr", "machine", "remove", "profile_a"]])
        self.assertIn("停用", output)
        self.assertNotIn("\x1b", output)

    def test_explicit_id_does_not_need_a_number_selection(self):
        code, calls, _ = self.execute(
            [[profile()], [profile()], []], ["yes"], ["--remove-remote", "profile_a"],
        )
        self.assertEqual(code, 0)
        self.assertEqual(calls, [["/tools/herdr", "machine", "remove", "profile_a"]])

    def test_cancelling_number_or_confirmation_never_mutates(self):
        for answers in ([""], ["1", ""], ["1", "no"]):
            with self.subTest(answers=answers):
                code, calls, _ = self.execute([[profile()]], answers)
                self.assertEqual(code, 0)
                self.assertEqual(calls, [])

    def test_empty_saved_list_exits_without_mutation(self):
        code, calls, _ = self.execute([[]], [])
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])

    def test_missing_id_or_label_cannot_remove_another_profile(self):
        for requested in ("missing", "build-box", "--bad", "profile_a;echo"):
            with self.subTest(requested=requested):
                code, calls, _ = self.execute(
                    [[profile()]], [], ["--remove-remote=" + requested],
                )
                self.assertEqual(code, 1)
                self.assertEqual(calls, [])

    def test_changed_or_missing_profile_after_confirmation_is_not_removed(self):
        for current in ([], [profile(session="changed")], [profile(enabled=False)],
                        [profile(target="other-box")], [profile(label="renamed")]):
            with self.subTest(current=current):
                code, calls, _ = self.execute([[profile()], current], ["1", "yes"])
                self.assertEqual(code, 1)
                self.assertEqual(calls, [])

    def test_native_failure_is_not_reported_as_success(self):
        code, calls, output = self.execute([[profile()], [profile()]], ["1", "yes"], native_exit=3)
        self.assertNotEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("已移除", output)

    def test_unverified_removal_is_not_reported_as_success(self):
        for after in ([profile()], app.PaneError("query unavailable")):
            with self.subTest(after=after):
                code, calls, output = self.execute([[profile()], [profile()], after], ["1", "yes"])
                self.assertEqual(code, 1)
                self.assertEqual(len(calls), 1)
                self.assertNotIn("已移除", output)

    def test_malformed_or_duplicate_saved_ids_never_mutate(self):
        for snapshot in ({}, [None], [profile(id="-option")], [profile(), profile()]):
            with self.subTest(snapshot=snapshot):
                code, calls, _ = self.execute([snapshot], [])
                self.assertEqual(code, 1)
                self.assertEqual(calls, [])

    def test_noninteractive_removal_is_refused(self):
        code, calls, _ = self.execute([], [], tty=False)
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])

    def test_remove_conflicts_with_other_modes_before_running_herdr(self):
        for flags in (["--list"], ["--add-remote"], ["--remote-session", "review"], ["--remote-session", ""]):
            with self.subTest(flags=flags), patch.object(sys, "stderr", io.StringIO()), \
                 self.assertRaises(SystemExit) as raised:
                app.main(["--remove-remote", *flags])
            self.assertEqual(raised.exception.code, 2)


class Tty(io.StringIO):
    def isatty(self):
        return True


if __name__ == "__main__":
    unittest.main()
