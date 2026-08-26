from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.configuration import DapSettings, FlutterConfiguration
from scripts.dap_templates import DapAdapterError, execute_adapter_validation, generate_debug_configurations
from scripts.sdk_resolution import ExecutableVersion, ResolvedSdk

ROOT = Path(__file__).resolve().parents[1]
FAKE_ADAPTER = ROOT / "tests" / "fake_dap_adapter.py"


class DebugConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.directory = Path(self.temporary_directory.name)
        self.root = self.directory / "example app"
        (self.root / "lib").mkdir(parents=True)
        self.target = self.root / "lib" / "main_staging.dart"
        self.target.touch()
        self.fake_adapter = self.directory / "fake adapter"
        self.fake_adapter.write_text(
            f"#!{sys.executable}\nfrom runpy import run_path\nrun_path({str(FAKE_ADAPTER)!r}, run_name='__main__')\n",
            encoding="utf-8",
        )
        self.fake_adapter.chmod(self.fake_adapter.stat().st_mode | stat.S_IXUSR)
        self.configuration = FlutterConfiguration(
            project_root=self.root,
            worktree_root=self.root,
            sdk_mode="fvm",
            target=self.target,
            device="emulator-5554",
            flavor="staging",
            mode="profile",
            args=("--dart-define=API_ENV=staging", "--trace-startup"),
            dap=DapSettings("Dart", "launch", {"vmServiceUri": "http://127.0.0.1:8181/abc/"}),
            tmux=None,
        )
        executable = ExecutableVersion(self.fake_adapter, "", "")
        self.sdk = ResolvedSdk("fvm", self.directory / "sdk", executable, executable)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_generation_maps_launch_and_attach_to_dart_adapter_schema(self) -> None:
        launch = generate_debug_configurations(self.configuration, self.sdk).configurations[0]
        attach_configuration = FlutterConfiguration(
            project_root=self.root,
            worktree_root=self.root,
            sdk_mode="fvm",
            target=self.target,
            device="emulator-5554",
            flavor="staging",
            mode="profile",
            args=("--dart-define=API_ENV=staging", "--trace-startup"),
            dap=DapSettings("Dart", "attach", {"vmServiceUri": "http://127.0.0.1:8181/abc/"}),
            tmux=None,
        )
        attach = generate_debug_configurations(attach_configuration, self.sdk).configurations[0]
        self.assertEqual(launch.adapter, "Dart")
        self.assertEqual(launch.request, "launch")
        self.assertEqual(launch.type, "flutter")
        self.assertEqual(launch.flutter_mode, "profile")
        self.assertEqual(launch.device_id, "emulator-5554")
        self.assertEqual(
            launch.tool_args,
            ("--flavor", "staging", "--dart-define=API_ENV=staging", "--trace-startup"),
        )
        self.assertTrue(launch.use_fvm)
        self.assertEqual(attach.request, "attach")
        self.assertIsNone(attach.flutter_mode)
        self.assertIsNone(attach.device_id)
        self.assertEqual(attach.vm_service_uri, "http://127.0.0.1:8181/abc/")
        generated = json.loads(generate_debug_configurations(self.configuration, self.sdk).to_json())[0]
        self.assertEqual(generated["program"], "lib/main_staging.dart")
        self.assertEqual(generated["cwd"], "$ZED_WORKTREE_ROOT")
        self.assertNotIn(str(self.root), json.dumps(generated))

    def test_fake_adapter_receives_exact_launch_json_without_tmux(self) -> None:
        launch = generate_debug_configurations(self.configuration, self.sdk).configurations[0]
        log_path = self.directory / "adapter.json"
        result = execute_adapter_validation(self.fake_adapter, launch, environment=os.environ | {"FAKE_DAP_LOG": str(log_path)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "launch accepted\n")
        self.assertEqual(
            json.loads(log_path.read_text(encoding="utf-8")),
            {
                "adapter": "Dart",
                "cwd": "$ZED_WORKTREE_ROOT",
                "deviceId": "emulator-5554",
                "flutterMode": "profile",
                "label": "Flutter: Launch",
                "program": "lib/main_staging.dart",
                "request": "launch",
                "toolArgs": ["--flavor", "staging", "--dart-define=API_ENV=staging", "--trace-startup"],
                "type": "flutter",
                "useFvm": True,
            },
        )

    def test_missing_adapter_is_actionable_and_never_falls_back_to_tmux(self) -> None:
        launch = generate_debug_configurations(self.configuration, self.sdk).configurations[0]
        missing = self.directory / "missing adapter"
        with self.assertRaises(DapAdapterError) as raised:
            execute_adapter_validation(missing, launch)
        diagnostic = raised.exception.diagnostic
        self.assertEqual(diagnostic.code, "dap.failed")
        self.assertIn("unavailable", diagnostic.message)
        self.assertIn("Dart Zed extension", diagnostic.message)
        self.assertNotIn("tmux", diagnostic.message.lower())
        self.assertIsNone(diagnostic.command)

    def test_attach_requires_uri_from_dap_settings(self) -> None:
        configuration = FlutterConfiguration(
            project_root=self.root,
            worktree_root=self.root,
            sdk_mode="flutter",
            target=None,
            device=None,
            flavor=None,
            mode="debug",
            args=(),
            dap=DapSettings("Dart", "attach", {}),
            tmux=None,
        )
        with self.assertRaises(ValueError):
            generate_debug_configurations(configuration, self.sdk)


if __name__ == "__main__":
    unittest.main()
