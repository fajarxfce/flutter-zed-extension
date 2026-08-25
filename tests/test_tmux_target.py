from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from scripts.configuration import TmuxTarget
from scripts.diagnostics import DiagnosticError
from scripts.tmux_target import inspect_tmux_target

ROOT = Path(__file__).resolve().parents[1]


class TmuxTargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.socket = f"flutter-zed-task12-{uuid.uuid4().hex}"
        self.server_options = ("-L", self.socket)
        self.tmux = shutil.which("tmux")

    def tearDown(self) -> None:
        if self.tmux is not None:
            subprocess.run(
                (self.tmux, *self.server_options, "kill-server"),
                check=False,
                capture_output=True,
                text=True,
            )
        self.temporary_directory.cleanup()

    def start_isolated_server(self) -> None:
        assert self.tmux is not None
        subprocess.run(
            (self.tmux, *self.server_options, "new-session", "-d", "-s", "known", "sleep", "60"),
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            (self.tmux, *self.server_options, "rename-window", "-t", "known:0", "app"),
            check=True,
            capture_output=True,
            text=True,
        )

    @unittest.skipIf(shutil.which("tmux") is None, "tmux is optional and unavailable")
    def test_exact_explicit_target_is_accepted_without_mutation(self) -> None:
        self.start_isolated_server()
        target = TmuxTarget(session="known", window="app", pane="%0")

        inspected = inspect_tmux_target(target, server_options=self.server_options)

        self.assertIsNotNone(inspected)
        assert inspected is not None
        self.assertEqual((inspected.session, inspected.window, inspected.pane), ("known", "app", "%0"))
        sessions = subprocess.run(
            (self.tmux, *self.server_options, "list-sessions", "-F", "#{session_name}"),
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(sessions.stdout, "known\n")

    @unittest.skipIf(shutil.which("tmux") is None, "tmux is optional and unavailable")
    def test_missing_pane_is_refused_without_mutation(self) -> None:
        self.start_isolated_server()
        target = TmuxTarget(session="known", window="app", pane="%99")

        with self.assertRaises(DiagnosticError) as raised:
            inspect_tmux_target(target, server_options=self.server_options)

        self.assertEqual(raised.exception.diagnostic.code, "tmux.failed")
        self.assertIn("did not match", raised.exception.diagnostic.message)
        sessions = subprocess.run(
            (self.tmux, *self.server_options, "list-sessions", "-F", "#{session_name}"),
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(sessions.stdout, "known\n")

    def test_tmux_absence_is_optional_and_deterministic(self) -> None:
        target = TmuxTarget(session="known", window="app", pane="%0")
        with patch("scripts.tmux_target.shutil.which", return_value=None):
            with self.assertRaises(DiagnosticError) as raised:
                inspect_tmux_target(target, environment={"PATH": os.environ.get("PATH", "")})
        self.assertEqual(raised.exception.diagnostic.code, "tmux.failed")
        self.assertEqual(raised.exception.diagnostic.message, "tmux executable is unavailable.")

    def test_disabled_tmux_never_inspects_an_executable(self) -> None:
        with patch("scripts.tmux_target.shutil.which") as which:
            self.assertIsNone(inspect_tmux_target(None))
        which.assert_not_called()
