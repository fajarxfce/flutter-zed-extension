from __future__ import annotations

import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.configuration import FlutterConfiguration
from scripts.project_detection import ProjectDetection
from scripts.sdk_resolution import SdkResolutionError, resolve_sdk

ROOT = Path(__file__).resolve().parents[1]
FAKE_EXECUTABLE = ROOT / "tests" / "fake_sdk_executable.py"


class SdkResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.directory = Path(self.temporary_directory.name)
        self.project_root = self.directory / "project"
        self.project_root.mkdir()
        self.configuration = FlutterConfiguration(
            project_root=self.project_root.resolve(),
            worktree_root=self.project_root.resolve(),
            sdk_mode="fvm",
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
            has_fvm_metadata=True,
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

    def test_fvm_wins_over_explicit_and_path_with_space_in_path(self) -> None:
        fvm = self.make_sdk(self.project_root / ".fvm" / "flutter_sdk")
        explicit = self.make_sdk(self.directory / "explicit sdk")
        system = self.make_sdk(self.directory / "system sdk")
        environment = self.environment | {"PATH": os.pathsep.join((str(system / "bin"), self.environment["PATH"]))}
        resolved = resolve_sdk(self.configuration, self.project, explicit_sdk=explicit, environment=environment)
        self.assertEqual(resolved.source, "fvm")
        self.assertEqual(resolved.root, fvm.resolve())
        self.assertEqual(resolved.flutter.stdout, "flutter fake-1.2.3\n")
        self.assertEqual(resolved.dart.stdout, "dart fake-1.2.3\n")

    def test_explicit_sdk_wins_when_fvm_is_not_selected(self) -> None:
        explicit = self.make_sdk(self.directory / "explicit sdk")
        configuration = FlutterConfiguration(**{**self.configuration.__dict__, "sdk_mode": "flutter"})
        resolved = resolve_sdk(configuration, self.project, explicit_sdk=explicit, environment=self.environment)
        self.assertEqual(resolved.source, "explicit")
        self.assertEqual(resolved.root, explicit.resolve())

    def test_path_fallback_resolves_matching_sdk_pair(self) -> None:
        system = self.make_sdk(self.directory / "system sdk")
        configuration = FlutterConfiguration(**{**self.configuration.__dict__, "sdk_mode": "flutter"})
        resolved = resolve_sdk(
            configuration,
            self.project,
            environment=self.environment | {"PATH": os.pathsep.join((str(system / "bin"), self.environment["PATH"]))},
        )
        self.assertEqual(resolved.source, "path")
        self.assertEqual(resolved.root, system.resolve())

    def test_missing_sdk_has_stable_actionable_error(self) -> None:
        with self.assertRaisesRegex(
            SdkResolutionError,
            r"No usable Flutter SDK\..*PATH: SDK not found: flutter, dart missing from PATH\. Install Flutter",
        ):
            resolve_sdk(self.configuration, self.project, environment={"PATH": ""})

    def test_invalid_fvm_falls_back_to_explicit_sdk(self) -> None:
        (self.project_root / ".fvm" / "flutter_sdk" / "bin").mkdir(parents=True)
        explicit = self.make_sdk(self.directory / "explicit sdk")
        resolved = resolve_sdk(self.configuration, self.project, explicit_sdk=explicit, environment=self.environment)
        self.assertEqual(resolved.source, "explicit")

    def test_version_failure_includes_captured_stderr(self) -> None:
        explicit = self.make_sdk(self.directory / "explicit sdk")
        environment = self.environment | {"FAKE_SDK_FAIL": "flutter"}
        with self.assertRaisesRegex(SdkResolutionError, r"configured version failure"):
            resolve_sdk(self.configuration, self.project, explicit_sdk=explicit, environment=environment)


if __name__ == "__main__":
    unittest.main()
