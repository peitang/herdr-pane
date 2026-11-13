"""Check same-host protection without connecting to a real SSH profile."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_herdr_pane import app, agent, payload, profile


class LoopbackGuardTests(unittest.TestCase):
    def test_remote_pid_check_uses_its_own_profile(self):
        self.assertTrue(hasattr(app, "has_caller_process"))
        source = app.parse_sources([profile()])[0][0]
        row = app.parse_agents(payload(agent()), source)[0]
        calls = []
        def query(args):
            calls.append(args)
            return {"result": {"process_info": {"shell_pid": 100, "foreground_processes": [{"pid": 123}]}}}
        self.assertTrue(app.has_caller_process(row, query, {123}))
        self.assertEqual(calls, [["--machine", "profile_a", "pane", "process-info", "--pane", "pane_a"]])

    def test_missing_ancestry_information_cannot_be_assumed_safe(self):
        with patch.object(app.subprocess, "check_output", side_effect=OSError("unavailable")), \
             self.assertRaises(app.PaneError):
            app.caller_pids()

    def test_incomplete_or_cyclic_parent_table_is_refused(self):
        for table in ("", "999 1\n", "430 420\n", "430 420\n420 430\n"):
            with self.subTest(table=table), patch.object(os, "getpid", return_value=430), \
                 patch.object(app.subprocess, "check_output", return_value=table), \
                 self.assertRaises(app.PaneError):
                app.caller_pids()

    def test_same_kernel_probe_refuses_attach_and_is_reaped_on_exit(self):
        self.assertTrue(hasattr(app, "loopback_guard"))
        source = app.parse_sources([profile()])[0][0]
        row = app.parse_agents(payload(agent()), source)[0]
        for interrupt in (False, True):
            with self.subTest(interrupt=interrupt):
                try:
                    with app.loopback_guard() as guard:
                        pid, marker, ps = guard
                        process_text = subprocess.check_output([ps, "-ww", "-p", str(pid), "-o", "command="], text=True)
                        self.assertTrue(process_text.rstrip("\n").endswith(marker))
                        command = app.attach_command(row, "/tools/herdr", "/tools/ssh", guard)[-1]
                        for shell in ("/bin/sh", "/bin/csh"):
                            if not Path(shell).exists():
                                continue
                            result = subprocess.run([shell, "-f", "-c", command], capture_output=True, text=True, timeout=5)
                            self.assertEqual(result.returncode, 1)
                            self.assertIn("calling terminal", result.stderr)
                        if interrupt:
                            raise KeyboardInterrupt()
                except KeyboardInterrupt:
                    pass
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)

    def test_probe_errors_refuse_attach_but_foreign_or_absent_pid_does_not(self):
        self.assertTrue(hasattr(app, "loopback_guard"))
        source = app.parse_sources([profile()])[0][0]
        row = app.parse_agents(payload(agent()), source)[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            herdr = root / "herdr"
            herdr.write_text('#!/bin/sh\nif test "$3" = terminal; then printf "ATTACHED\\n"; fi\n')
            herdr.chmod(0o755)
            ps = root / "ps"
            env = dict(os.environ, PATH=directory + os.pathsep + os.environ.get("PATH", ""))
            for body, allowed in (("printf 'foreign process\\n'; exit 0", True),
                                  ("exit 1", True),
                                  ("printf 'ps failed\\n' >&2; exit 1", False),
                                  ("exit 2", False)):
                with self.subTest(body=body):
                    ps.write_text("#!/bin/sh\n" + body + "\n")
                    ps.chmod(0o755)
                    command = app.attach_command(row, "/tools/herdr", "/tools/ssh", (123, "probe-marker", str(ps)))[-1]
                    result = subprocess.run(["/bin/sh", "-c", command], env=env, capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 0 if allowed else 1, result.stderr)
                    self.assertEqual("ATTACHED" in result.stdout, allowed)

    def test_probe_startup_failure_does_not_leave_its_child_running(self):
        self.assertTrue(hasattr(app, "loopback_guard"))
        children = []
        real_popen = subprocess.Popen
        def launch(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            children.append(process)
            return process
        with patch.object(app.subprocess, "Popen", side_effect=launch), \
             patch.object(app.subprocess, "check_output", side_effect=OSError("unavailable")), \
             self.assertRaises(app.PaneError):
            with app.loopback_guard():
                self.fail("Unverified probe must not be yielded")
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())
