from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from scripts.configuration import TmuxTarget
from scripts.diagnostics import DiagnosticError
from scripts.tmux_runner import HotOperation, perform_hot_operation, start_runner, status_runner, stop_runner

ROOT = Path(__file__).resolve().parents[1]


class TmuxRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.directory = Path(self.temporary_directory.name)
        self.socket = f"flutter-zed-task13-{uuid.uuid4().hex}"
        self.server_options = ("-L", self.socket)
        self.tmux = shutil.which("tmux")
        self.target = TmuxTarget(session="known", window="app", pane="%0")
        self.state_path = self.directory / "runner-state.json"
        self.log_path = self.directory / "runner.log"

    def tearDown(self) -> None:
        if self.tmux is not None:
            subprocess.run((self.tmux, *self.server_options, "kill-server"), check=False, capture_output=True, text=True)
        self.temporary_directory.cleanup()

    def start_isolated_server(self) -> None:
        assert self.tmux is not None
        subprocess.run((self.tmux, *self.server_options, "new-session", "-d", "-s", "known"), check=True, capture_output=True, text=True)
        subprocess.run((self.tmux, *self.server_options, "rename-window", "-t", "known:0", "app"), check=True, capture_output=True, text=True)

    @unittest.skipIf(shutil.which("tmux") is None, "tmux is optional and unavailable")
    def test_start_status_log_identity_and_stop_owned_runner(self) -> None:
        self.start_isolated_server()
        command = (sys.executable, "-c", "import time; print('fake Flutter runner', flush=True); time.sleep(60)")
        started = start_runner(self.target, command, self.state_path, self.log_path, server_options=self.server_options)
        self.assertEqual(started.state, "running-owned")
        self.assertIsNotNone(started.pid)
        self.assertEqual(started.command, command)
        self.assertEqual(started.log_path, self.log_path)
        for _ in range(100):
            if "fake Flutter runner" in self.log_path.read_text(encoding="utf-8"):
                break
            time.sleep(0.02)
        self.assertIn("fake Flutter runner", self.log_path.read_text(encoding="utf-8"))
        self.assertEqual(status_runner(self.target, self.state_path, server_options=self.server_options).state, "running-owned")
        stopped = stop_runner(self.target, self.state_path, server_options=self.server_options)
        self.assertEqual(stopped.state, "stopped-owned")
        self.assertTrue(self.log_path.exists())

    @unittest.skipIf(shutil.which("tmux") is None, "tmux is optional and unavailable")
    def test_hot_operations_send_only_fixed_literals_to_owned_runner(self) -> None:
        self.start_isolated_server()
        command = (sys.executable, "-c", "import time; time.sleep(60)")
        start_runner(self.target, command, self.state_path, self.log_path, server_options=self.server_options)
        pane_target = "known:app.%0"
        reloaded = perform_hot_operation(self.target, HotOperation.RELOAD, self.state_path, server_options=self.server_options)
        reload_input = subprocess.run((self.tmux, *self.server_options, "capture-pane", "-p", "-t", pane_target), check=True, capture_output=True, text=True)
        restarted = perform_hot_operation(self.target, HotOperation.RESTART, self.state_path, server_options=self.server_options)
        restart_input = subprocess.run((self.tmux, *self.server_options, "capture-pane", "-p", "-t", pane_target), check=True, capture_output=True, text=True)
        self.assertEqual((reloaded.operation, reloaded.status.state), (HotOperation.RELOAD, "running-owned"))
        self.assertEqual((restarted.operation, restarted.status.state), (HotOperation.RESTART, "running-owned"))
        self.assertIn("rR", restart_input.stdout)
        self.assertNotIn("rR", reload_input.stdout)

    @unittest.skipIf(shutil.which("tmux") is None, "tmux is optional and unavailable")
    def test_hot_restart_refuses_stale_state_without_sending_input(self) -> None:
        self.start_isolated_server()
        command = (sys.executable, "-c", "import time; time.sleep(60)")
        started = start_runner(self.target, command, self.state_path, self.log_path, server_options=self.server_options)
        assert started.process_start_time is not None
        before = subprocess.run((self.tmux, *self.server_options, "capture-pane", "-p", "-t", "known:app.%0"), check=True, capture_output=True, text=True)
        state = self.state_path.read_text(encoding="utf-8")
        self.state_path.write_text(state.replace(started.process_start_time, "0", 1), encoding="utf-8")
        with self.assertRaises(DiagnosticError) as raised:
            perform_hot_operation(self.target, HotOperation.RESTART, self.state_path, server_options=self.server_options)
        after = subprocess.run((self.tmux, *self.server_options, "capture-pane", "-p", "-t", "known:app.%0"), check=True, capture_output=True, text=True)
        self.assertEqual(raised.exception.diagnostic.code, "tmux.failed")
        self.assertIn("stale-mismatched", raised.exception.diagnostic.message)
        self.assertEqual(after.stdout, before.stdout)

    @unittest.skipIf(shutil.which("tmux") is None, "tmux is optional and unavailable")
    def test_start_refuses_foreign_process_without_changing_it(self) -> None:
        self.start_isolated_server()
        pane_target = "known:app.%0"
        subprocess.run((self.tmux, *self.server_options, "send-keys", "-t", pane_target, "sleep 60", "Enter"), check=True, capture_output=True, text=True)
        for _ in range(100):
            foreign_command = subprocess.run((self.tmux, *self.server_options, "display-message", "-p", "-t", pane_target, "#{pane_current_command}"), check=True, capture_output=True, text=True)
            if foreign_command.stdout.strip() == "sleep":
                break
            time.sleep(0.02)
        self.assertEqual(foreign_command.stdout.strip(), "sleep")
        before = subprocess.run((self.tmux, *self.server_options, "capture-pane", "-p", "-t", pane_target), check=True, capture_output=True, text=True)
        with self.assertRaises(DiagnosticError) as raised:
            start_runner(self.target, (sys.executable, "-c", "import time; time.sleep(60)"), self.state_path, self.log_path, server_options=self.server_options)
        after = subprocess.run((self.tmux, *self.server_options, "capture-pane", "-p", "-t", pane_target), check=True, capture_output=True, text=True)
        self.assertEqual(raised.exception.diagnostic.code, "tmux.failed")
        self.assertIn("not an idle shell", raised.exception.diagnostic.message)
        self.assertEqual(after.stdout, before.stdout)
        self.assertFalse(self.state_path.exists())
        self.assertFalse(self.log_path.exists())

    @unittest.skipIf(shutil.which("tmux") is None, "tmux is optional and unavailable")
    def test_stop_refuses_foreign_process_without_changing_it(self) -> None:
        self.start_isolated_server()
        foreign = subprocess.run((self.tmux, *self.server_options, "display-message", "-p", "-t", "known:app.%0", "#{pane_pid}"), check=True, capture_output=True, text=True)
        pane_pid = int(foreign.stdout.strip())
        with self.assertRaises(DiagnosticError) as raised:
            stop_runner(self.target, self.state_path, server_options=self.server_options)
        self.assertEqual(raised.exception.diagnostic.code, "tmux.failed")
        self.assertEqual(status_runner(self.target, self.state_path, server_options=self.server_options).state, "foreign-no-owned-runner")
        os.kill(pane_pid, 0)
        self.assertFalse(self.state_path.exists())
