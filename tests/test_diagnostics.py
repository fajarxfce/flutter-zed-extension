from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.configuration import FlutterConfiguration
from scripts.diagnostics import (
    dap_failure,
    invalid_configuration,
    invalid_project,
    tmux_failure,
    unavailable_device,
    unexpected_process_failure,
)
from scripts.project_detection import ProjectDetection
from scripts.sdk_resolution import SdkResolutionError, resolve_sdk

ROOT = Path(__file__).resolve().parents[1]
FAKE_EXECUTABLE = ROOT / "tests" / "fake_sdk_executable.py"


class DiagnosticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.directory = Path(self.temporary_directory.name)
        self.project_root = self.directory / "project"
        self.project_root.mkdir()
        self.configuration = FlutterConfiguration(
            project_root=self.project_root.resolve(),
            worktree_root=self.project_root.resolve(),
            sdk_mode="flutter",
            target=None,
            device=None,
            flavor=None,
            mode="debug",
            args=(),
            dap=None,
            tmux=None,
        )
        self.project = ProjectDetection(
            project_root=self.project_root.resolve(),
            kind="flutter_app",
            diagnostics=(),
            workspace_root=None,
            has_fvm_metadata=False,
            has_zed_metadata=False,
        )
        self.environment = {"PATH": str(Path(sys.executable).parent), "FAKE_SDK_VERSION": "fake-1.2.3"}

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def make_sdk(self, root: Path) -> Path:
        bin_directory = root / "bin"
        bin_directory.mkdir(parents=True)
        for name in ("flutter", "dart"):
            executable = bin_directory / name
            shutil.copyfile(FAKE_EXECUTABLE, executable)
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        return root

    def test_sdk_process_failure_preserves_exact_stderr_and_command(self) -> None:
        explicit = self.make_sdk(self.directory / "explicit-sdk")
        environment = self.environment | {"FAKE_SDK_FAIL": "flutter"}
        with self.assertRaises(SdkResolutionError) as raised:
            resolve_sdk(self.configuration, self.project, explicit_sdk=explicit, environment=environment)
        diagnostic = raised.exception.diagnostic
        self.assertIsNotNone(diagnostic)
        assert diagnostic is not None
        self.assertEqual(diagnostic.code, "process.failed")
        self.assertEqual(diagnostic.command, (str(explicit / "bin" / "flutter"), "--version"))
        self.assertEqual(diagnostic.exit_status, 1)
        self.assertEqual(diagnostic.stderr, "flutter: configured version failure\n")
        self.assertEqual(diagnostic.stdout, "")

    def test_missing_sdk_has_stable_diagnostic(self) -> None:
        with self.assertRaises(SdkResolutionError) as raised:
            resolve_sdk(self.configuration, self.project, environment={"PATH": ""})
        diagnostic = raised.exception.diagnostic
        self.assertIsNotNone(diagnostic)
        assert diagnostic is not None
        self.assertEqual(diagnostic.code, "sdk.missing")
        self.assertEqual(diagnostic.message, str(raised.exception))

    def test_modeled_boundary_failures_have_stable_codes(self) -> None:
        command = ("flutter", "run")
        unavailable = unavailable_device(command, exit_status=1, stdout="", stderr="No devices found\n")
        unexpected = unexpected_process_failure(command, RuntimeError("terminated"), cleanup_completed=True)
        self.assertEqual(invalid_project("invalid project", project_root="/project").code, "project.invalid")
        self.assertEqual(invalid_configuration("invalid config", configuration_path="config.json").code, "configuration.invalid")
        self.assertEqual(unavailable.code, "device.unavailable")
        self.assertEqual(unavailable.stderr, "No devices found\n")
        self.assertEqual(dap_failure("DAP request failed.", adapter="Dart").code, "dap.failed")
        self.assertEqual(tmux_failure("tmux target failed.", target="session:window.pane").code, "tmux.failed")
        self.assertEqual(unexpected.code, "process.unexpected_failure")
        self.assertEqual(unexpected.context["cleanup_completed"], "True")


if __name__ == "__main__":
    unittest.main()
