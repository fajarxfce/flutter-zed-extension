from __future__ import annotations

import json
import os
import sys
import stat
import tempfile
import unittest
from pathlib import Path

from scripts.configuration import FlutterConfiguration
from scripts.sdk_resolution import ExecutableVersion, ResolvedSdk
from scripts.task_templates import execute_task_template, generate_task_templates

ROOT = Path(__file__).resolve().parents[1]
FAKE_FLUTTER = ROOT / "tests" / "fake_flutter_sdk.py"


class TaskTemplateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.directory = Path(self.temporary_directory.name)
        self.root = self.directory / "example app"
        self.root.mkdir()
        self.fake_flutter = self.directory / "fake flutter"
        self.fake_flutter.write_text(
            f"#!{sys.executable}\n"
            "from runpy import run_path\n"
            f"run_path({str(FAKE_FLUTTER)!r}, run_name='__main__')\n",
            encoding="utf-8",
        )
        self.fake_flutter.chmod(self.fake_flutter.stat().st_mode | stat.S_IXUSR)
        self.configuration = FlutterConfiguration(
            project_root=self.root,
            sdk_mode="fvm",
            target=self.root / "lib" / "main_staging.dart",
            device="fake-device",
            flavor="staging",
            mode="profile",
            args=("--dart-define=API_ENV=staging",),
            dap=None,
            tmux=None,
        )
        self.sdk = ResolvedSdk(
            source="fvm",
            root=self.directory / "sdk",
            flutter=ExecutableVersion(self.fake_flutter, "", ""),
            dart=ExecutableVersion(self.fake_flutter, "", ""),
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def task(self, label: str):
        return next(task for task in generate_task_templates(self.configuration, self.sdk).tasks if task.label == label)

    def test_templates_emit_zed_json_with_stable_labels_and_argv(self) -> None:
        templates = generate_task_templates(self.configuration, self.sdk)
        document = json.loads(templates.to_json())
        self.assertIsInstance(document, list)
        self.assertEqual(
            [task["label"] for task in document],
            [
                "Flutter: Pub get",
                "Flutter: Analyze",
                "Flutter: Format (check)",
                "Flutter: Test",
                "Flutter: Build APK",
                "Flutter: Build web",
                "Flutter: Run",
                "Flutter: Devices",
                "Flutter: Clean",
            ],
        )
        run = self.task("Flutter: Run")
        self.assertEqual(
            run.args,
            (
                "flutter",
                "run",
                "--target",
                "lib/main_staging.dart",
                "--flavor",
                "staging",
                "--profile",
                "-d",
                "fake-device",
                "--dart-define=API_ENV=staging",
            ),
        )
        self.assertEqual(run.cwd, self.root)
        self.assertEqual(document[6]["command"], "fvm")
        self.assertEqual(document[6]["cwd"], "$ZED_WORKTREE_ROOT")
        self.assertNotIn(str(self.root), json.dumps(document))
        self.assertNotIn(str(self.fake_flutter.resolve()), json.dumps(document))

    def test_system_serialization_uses_path_commands_and_relative_target(self) -> None:
        configuration = FlutterConfiguration(
            project_root=self.root,
            sdk_mode="flutter",
            target=self.root / "lib" / "main_staging.dart",
            device=None,
            flavor=None,
            mode="debug",
            args=(),
            dap=None,
            tmux=None,
        )
        document = generate_task_templates(configuration, self.sdk).as_json()
        build_apk = next(task for task in document if task["label"] == "Flutter: Build APK")
        format_task = next(task for task in document if task["label"] == "Flutter: Format (check)")
        self.assertEqual(build_apk["command"], "flutter")
        self.assertEqual(build_apk["args"], ["build", "apk", "--target", "lib/main_staging.dart", "--debug"])
        self.assertEqual(format_task["command"], "dart")
        self.assertEqual(format_task["args"], ["format", "--set-exit-if-changed", "lib/main_staging.dart"])
        self.assertTrue(all(task["cwd"] == "$ZED_WORKTREE_ROOT" for task in document))
        self.assertNotIn(str(self.root), json.dumps(document))

    def test_optional_selectors_only_emit_relevant_flags(self) -> None:
        configuration = FlutterConfiguration(
            project_root=self.root,
            sdk_mode="flutter",
            target=None,
            device=None,
            flavor=None,
            mode="debug",
            args=(),
            dap=None,
            tmux=None,
        )
        templates = {task.label: task for task in generate_task_templates(configuration, self.sdk).tasks}
        self.assertEqual(templates["Flutter: Build APK"].args, ("build", "apk", "--debug"))
        self.assertEqual(templates["Flutter: Build web"].args, ("build", "web", "--debug"))
        self.assertEqual(templates["Flutter: Run"].args, ("run", "--debug"))
        self.assertEqual(templates["Flutter: Format (check)"].args, ("format", "--set-exit-if-changed", "."))
        document = generate_task_templates(configuration, self.sdk).as_json()
        format_task = next(task for task in document if task["label"] == "Flutter: Format (check)")
        self.assertEqual(format_task["command"], "dart")
        self.assertEqual(format_task["cwd"], "$ZED_WORKTREE_ROOT")

    def test_analyze_execution_uses_exact_argv_and_root(self) -> None:
        task = self.task("Flutter: Analyze")
        log_path = self.directory / "analyze.json"
        environment = os.environ | {
            "FAKE_SDK_EXECUTABLE": str(self.fake_flutter.resolve()),
            "FAKE_SDK_LOG": str(log_path),
            "FAKE_SDK_LOG_CWD": "1",
            "FAKE_SDK_OUTCOME": "success",
        }
        result = execute_task_template(task, environment=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"{self.fake_flutter.resolve()}: analyze --dart-define=API_ENV=staging\n")
        self.assertEqual(
            json.loads(log_path.read_text(encoding="utf-8")),
            {
                "arguments": ["analyze", "--dart-define=API_ENV=staging"],
                "cwd": str(self.root),
                "executable": str(self.fake_flutter.resolve()),
            },
        )

    def test_test_execution_propagates_failure_exit_and_stderr(self) -> None:
        task = self.task("Flutter: Test")
        log_path = self.directory / "test.json"
        environment = os.environ | {
            "FAKE_SDK_EXECUTABLE": str(self.fake_flutter.resolve()),
            "FAKE_SDK_LOG": str(log_path),
            "FAKE_SDK_OUTCOME": "failure",
        }
        result = execute_task_template(task, environment=environment)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, f"{self.fake_flutter.resolve()}: configured failure\n")
        self.assertEqual(json.loads(log_path.read_text(encoding="utf-8"))["arguments"], ["test", "--dart-define=API_ENV=staging"])


if __name__ == "__main__":
    unittest.main()
