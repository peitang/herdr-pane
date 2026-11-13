"""Exercise the real CLI/PTY with disposable Herdr and SSH executables."""

import errno
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import subprocess
import sys
import tempfile
import termios
import time
import unittest


PROGRAM = Path(__file__).resolve().parents[1] / "herdr_pane.py"
PROFILE_ID = "a" * 32
FAKE_CLI = r'''
import json, os, signal, subprocess, sys, termios, time
from pathlib import Path
state_path = Path(os.environ["HERDR_PANE_TEST_STATE"])
state = json.loads(state_path.read_text())
args = sys.argv[1:]
kind = Path(sys.argv[0]).name
with open(str(state_path) + ".calls", "a") as log:
    log.write(json.dumps([kind, *args]) + "\n")
interactive = kind == "ssh" or args[:2] in (["terminal", "attach"], ["machine", "add"], ["machine", "remove"])
if state.get("interrupt_cleanup") and interactive:
    attributes = termios.tcgetattr(0)
    changed = list(attributes)
    changed[3] &= ~termios.ECHO
    termios.tcsetattr(0, termios.TCSANOW, changed)
    state["interactive_pid"] = os.getpid()
    state_path.write_text(json.dumps(state))
    def finish(signum, frame):
        time.sleep(0.6)
        state["cleanup_completed"] = True
        state_path.write_text(json.dumps(state))
        termios.tcsetattr(0, termios.TCSANOW, attributes)
        sys.exit(130)
    signal.signal(signal.SIGINT, signal.SIG_IGN if state.get("ignore_signals") else finish)
    if state.get("ignore_signals"):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    print("FIXTURE_INTERRUPT_READY", flush=True)
    while True:
        time.sleep(1)
if kind == "ssh":
    if state.get("loopback"):
        sys.exit(subprocess.call(["/bin/sh", "-c", args[-1]]))
    print("FIXTURE_REMOTE_ATTACHED", flush=True)
    sys.exit(state.get("attach_exit", 0))
if args == ["machine", "list", "--json"]:
    if state.get("interrupt_postcheck") and state.get("removed"):
        os.kill(os.getppid(), signal.SIGINT)
        sys.exit(0)
    print(json.dumps(state["profiles"]))
elif args[:2] == ["machine", "remove"] and len(args) == 3:
    state["profiles"] = [p for p in state["profiles"] if p["id"] != args[2]]
    state["removed"] = True
    state_path.write_text(json.dumps(state))
    if state.get("interrupt_remove"):
        os.kill(os.getppid(), signal.SIGINT)
elif args[:2] == ["machine", "add"] and len(args) == 5 and args[3] == "--remote-session":
    answer = input("NATIVE_SETUP_CONFIRM>")
    state["setup_answer"] = answer
    state_path.write_text(json.dumps(state))
    sys.exit(0 if answer == "allow" else 1)
elif args == ["agent", "list"]:
    print(json.dumps({"result": {"agents": state["local_agents"]}}))
elif args[:1] == ["--machine"] and args[2:] == ["agent", "list"]:
    if state.get("remote_offline"):
        print("PRIVATE_ERROR_MUST_NOT_SURFACE", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"result": {"agents": state["remote_agents"]}}))
elif args[:2] == ["pane", "process-info"] or args[:3] == ["--machine", "a" * 32, "pane"]:
    print(json.dumps({"result": {"process_info": {
        "shell_pid": os.getppid() if state.get("loopback") and args[0] == "--machine" else 2000000000,
        "foreground_processes": []
    }}}))
elif args[:2] == ["terminal", "attach"]:
    print("FIXTURE_LOCAL_ATTACHED", flush=True)
    sys.exit(state.get("attach_exit", 0))
else:
    print("UNEXPECTED_FIXTURE_COMMAND", file=sys.stderr)
    sys.exit(2)
'''


def fixture_agent(terminal_id):
    return {
        "agent": "codex", "agent_status": "working", "name": "reviewer",
        "pane_id": "pane_a", "terminal_id": terminal_id,
        "cwd": "~/projects/sample-app", "focused": False, "revision": 1,
    }


class CliIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="herdr-pane-cli-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.state_path = self.root / "state.json"
        for name in ("herdr", "ssh"):
            executable = self.root / name
            executable.write_text("#!" + sys.executable + "\n" + FAKE_CLI)
            executable.chmod(0o755)
        self.env = dict(os.environ)
        self.env["PATH"] = str(self.root) + os.pathsep + self.env.get("PATH", "")
        self.env["HERDR_PANE_TEST_STATE"] = str(self.state_path)
        self.state = {
            "profiles": [{
                "id": PROFILE_ID, "label": "build-box", "target": "developer@build.example.invalid",
                "session": "review", "enabled": True, "selected": False,
            }],
            "local_agents": [fixture_agent("terminal_local")],
            "remote_agents": [fixture_agent("terminal_remote")],
        }

    def calls(self):
        path = Path(str(self.state_path) + ".calls")
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def run_cli(self, args, exchanges=(), interactive=True):
        self.state_path.write_text(json.dumps(self.state))
        if not interactive:
            result = subprocess.run(
                [sys.executable, str(PROGRAM), *args], env=self.env,
                input="", capture_output=True, text=True, timeout=15,
            )
            return result.returncode, result.stdout + result.stderr
        master, slave = pty.openpty()
        process = subprocess.Popen(
            [sys.executable, str(PROGRAM), *args], env=self.env,
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
        )
        os.close(slave)
        output = bytearray()
        deadline = time.monotonic() + 15
        exchange = 0
        try:
            while True:
                if time.monotonic() >= deadline:
                    self.fail("CLI did not reach the next prompt or exit: " + output.decode(errors="replace"))
                if select.select([master], [], [], 0.1)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        chunk = b""
                    if not chunk:
                        break
                    output.extend(chunk)
                if exchange < len(exchanges) and exchanges[exchange][0].encode() in output:
                    response = exchanges[exchange][1]
                    if isinstance(response, signal.Signals):
                        os.killpg(process.pid, response)
                    else:
                        os.write(master, response if isinstance(response, bytes) else response.encode())
                    exchange += 1
            status = process.wait(timeout=3)
            self.tty_echo_after = bool(termios.tcgetattr(master)[3] & termios.ECHO)
            self.assertEqual(exchange, len(exchanges), output.decode(errors="replace"))
            return status, output.decode(errors="replace")
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
            os.close(master)

    def test_list_keeps_local_result_when_remote_query_fails(self):
        self.state["remote_offline"] = True
        code, output = self.run_cli(["--list"], interactive=False)
        self.assertEqual(code, 0)
        self.assertIn("reviewer", output)
        self.assertIn("查詢失敗", output)
        self.assertNotIn("PRIVATE_ERROR_MUST_NOT_SURFACE", output)
        self.assertFalse(any(call[0] == "ssh" for call in self.calls()))

    def test_remote_selection_runs_ssh_with_the_selected_session_and_terminal(self):
        code, output = self.run_cli([], [("輸入編號連線", "2\n")])
        self.assertEqual(code, 0)
        self.assertIn("FIXTURE_REMOTE_ATTACHED", output)
        ssh_calls = [call for call in self.calls() if call[0] == "ssh"]
        self.assertEqual(len(ssh_calls), 1)
        self.assertEqual(ssh_calls[0][:4], ["ssh", "-t", "--", "developer@build.example.invalid"])
        self.assertIn("--session review terminal attach terminal_remote", ssh_calls[0][4])
        self.assertNotIn("--takeover", ssh_calls[0][4])

    def test_local_selection_attaches_to_the_selected_terminal(self):
        code, output = self.run_cli([], [("輸入編號連線", "1\n")])
        self.assertEqual(code, 0)
        self.assertIn("FIXTURE_LOCAL_ATTACHED", output)
        self.assertIn(["herdr", "terminal", "attach", "terminal_local"], self.calls())

    def test_setup_retains_native_interactive_confirmation(self):
        code, _ = self.run_cli(
            ["--add-remote", "build-box", "--remote-session", "review"],
            [("NATIVE_SETUP_CONFIRM>", "deny\n"), ("輸入編號連線", "\n")],
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.state_path.read_text())["setup_answer"], "deny")
        self.assertIn(["herdr", "machine", "add", "build-box", "--remote-session", "review"], self.calls())

    def test_confirmed_disabled_profile_removal_updates_only_the_fixture_catalog(self):
        self.state["profiles"][0]["enabled"] = False
        code, output = self.run_cli(
            ["--remove-remote"], [("選擇要移除", "1\n"), ("確認移除？", "yes\n")],
        )
        self.assertEqual(code, 0)
        self.assertIn("[停用]", output)
        self.assertIn("已移除連線", output)
        self.assertEqual(json.loads(self.state_path.read_text())["profiles"], [])
        self.assertFalse(any(call[0] == "ssh" for call in self.calls()))

    def test_interrupt_after_profile_mutation_is_not_reported_as_cancelled(self):
        for timing in ("interrupt_remove", "interrupt_postcheck"):
            with self.subTest(timing=timing):
                self.state[timing] = True
                code, output = self.run_cli(
                    ["--remove-remote", PROFILE_ID], [("確認移除？", "yes\n")],
                )
                self.assertEqual(code, 130)
                self.assertEqual(json.loads(self.state_path.read_text())["profiles"], [])
                self.assertIn("結果未確認", output)
                self.assertNotIn("已取消", output)
                self.state.pop(timing)

    def test_piped_removal_is_refused_before_reading_profiles(self):
        code, output = self.run_cli(["--remove-remote", PROFILE_ID], interactive=False)
        self.assertEqual(code, 1)
        self.assertIn("互動終端", output)
        self.assertEqual(self.calls(), [])


    def test_interrupt_allows_child_cleanup_and_restores_terminal_echo(self):
        for args, before in (([], [("輸入編號連線", "1\n")]),
                             (["--add-remote", "build-box", "--remote-session", "review"], []),
                             (["--remove-remote", PROFILE_ID], [("確認移除？", "yes\n")])):
            with self.subTest(args=args):
                self.state["interrupt_cleanup"] = True
                code, _ = self.run_cli(args, before + [("FIXTURE_INTERRUPT_READY", signal.SIGINT)])
                self.assertEqual(code, 130)
                self.assertTrue(json.loads(self.state_path.read_text()).get("cleanup_completed"))
                self.assertTrue(self.tty_echo_after)

    def test_unresponsive_interactive_child_cannot_hold_terminal_forever(self):
        self.state.update(interrupt_cleanup=True, ignore_signals=True)
        code, _ = self.run_cli([], [("輸入編號連線", "1\n"), ("FIXTURE_INTERRUPT_READY", signal.SIGINT)])
        self.assertEqual(code, 130)
        self.assertTrue(self.tty_echo_after)
        pid = json.loads(self.state_path.read_text())["interactive_pid"]
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_invalid_utf8_at_number_prompt_is_rejected_without_traceback(self):
        self.env["PYTHONIOENCODING"] = "utf-8:strict"
        code, output = self.run_cli([], [("輸入編號連線", b"\xff\n"), ("請輸入這次清單", "\n")])
        self.assertEqual(code, 0)
        self.assertNotIn("Traceback", output)
        self.assertFalse(any(call[0] == "ssh" for call in self.calls()))

    def test_ascii_output_locale_does_not_crash_list_or_help(self):
        self.env["PYTHONIOENCODING"] = "ascii:strict"
        for args in (["--list"], ["-h"]):
            with self.subTest(args=args):
                code, output = self.run_cli(args, interactive=False)
                self.assertEqual(code, 0)
                self.assertNotIn("Traceback", output)

    def test_explicit_empty_session_is_rejected_before_native_setup(self):
        code, _ = self.run_cli(["--add-remote", "build-box", "--remote-session", ""], interactive=False)
        self.assertEqual(code, 2)
        self.assertEqual(self.calls(), [])


    def test_loopback_to_calling_terminal_is_refused_and_probe_is_cleaned(self):
        self.state["loopback"] = True
        code, output = self.run_cli([], [("輸入編號連線", "2\n"), ("calling terminal", "\n")])
        self.assertEqual(code, 0)
        self.assertIn("cannot attach to the calling terminal", output)
        self.assertNotIn("FIXTURE_REMOTE_ATTACHED", output)
        ssh_calls = [call for call in self.calls() if call[0] == "ssh"]
        self.assertEqual(len(ssh_calls), 1)
        match = re.search(r"ps -ww -p ([0-9]+)", ssh_calls[0][-1])
        self.assertIsNotNone(match)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(match.group(1)), 0)
