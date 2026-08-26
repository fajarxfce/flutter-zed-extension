from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.configuration import ConfigurationError, load_configuration

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "configuration.py"


class ConfigurationValidationTests(unittest.TestCase):
    def write_configuration(self, directory: Path, configuration: dict[str, object]) -> Path:
        path = directory / "configuration.json"
        path.write_text(json.dumps(configuration), encoding="utf-8")
        return path

    def test_valid_fvm_configuration_preserves_explicit_values(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            directory = Path(temporary_directory)
            (directory / "app").mkdir()
            (directory / "app" / "pubspec.yaml").write_text("name: app\nflutter:\n  uses-material-design: true\ndependencies:\n  flutter:\n    sdk: flutter\n", encoding="utf-8")
            configuration_path = self.write_configuration(
                directory,
                {
                    "project_root": "app",
                    "sdk_mode": "fvm",
                    "target": "lib/main_staging.dart",
                    "device": "emulator-5554",
                    "flavor": "staging",
                    "mode": "profile",
                    "args": ["--dart-define=API_ENV=staging"],
                    "dap": {"adapter": "Dart", "request": "launch", "flutterMode": "profile"},
                    "tmux": {"session": "flutter", "window": "app", "pane": "%3"},
                },
            )
            configuration = load_configuration(configuration_path)
        self.assertEqual(configuration.project_root, directory / "app")
        self.assertEqual(configuration.worktree_root, directory / "app")
        self.assertEqual(configuration.sdk_mode, "fvm")
        self.assertEqual(configuration.target, directory / "app" / "lib" / "main_staging.dart")
        self.assertEqual(configuration.device, "emulator-5554")
        self.assertEqual(configuration.flavor, "staging")
        self.assertEqual(configuration.mode, "profile")
        self.assertEqual(configuration.args, ("--dart-define=API_ENV=staging",))
        self.assertEqual(configuration.tmux.pane if configuration.tmux else None, "%3")

    def test_nested_worktree_resolves_relative_to_configuration(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            directory = Path(temporary_directory)
            app = directory / "app"
            app.mkdir()
            (app / "pubspec.yaml").write_text("name: app\nflutter:\n  uses-material-design: true\ndependencies:\n  flutter:\n    sdk: flutter\n", encoding="utf-8")
            configuration = load_configuration(self.write_configuration(directory, {"project_root": "app", "worktree_root": "."}))
        self.assertEqual(configuration.project_root, app)
        self.assertEqual(configuration.worktree_root, directory)

    def test_non_containing_or_escaping_worktree_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            directory = Path(temporary_directory)
            app = directory / "app"
            app.mkdir()
            (app / "pubspec.yaml").write_text("name: app\nflutter:\n  uses-material-design: true\ndependencies:\n  flutter:\n    sdk: flutter\n", encoding="utf-8")
            (directory / "other").mkdir()
            for document, message in (({"project_root": "app", "worktree_root": "other"}, "worktree_root: must contain project_root"), ({"project_root": "app", "worktree_root": "../outside"}, "worktree_root: must not escape project_root")):
                with self.subTest(document=document):
                    with self.assertRaisesRegex(ConfigurationError, message):
                        load_configuration(self.write_configuration(directory, document))

    def test_ambiguous_tmux_target_fails_without_invoking_tmux(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            directory = Path(temporary_directory)
            (directory / "app").mkdir()
            (directory / "app" / "pubspec.yaml").write_text("name: app\nflutter:\n  uses-material-design: true\ndependencies:\n  flutter:\n    sdk: flutter\n", encoding="utf-8")
            configuration_path = self.write_configuration(
                directory,
                {"project_root": "app", "tmux": {"session": "flutter", "window": "app"}},
            )
            result = subprocess.run(
                ["python3", str(VALIDATOR), str(configuration_path)],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tmux: requires explicit session, window, and pane", result.stderr)

    def test_invalid_path_mode_and_selector_report_their_fields(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            directory = Path(temporary_directory)
            (directory / "app").mkdir()
            (directory / "app" / "pubspec.yaml").write_text("name: app\nflutter:\n  uses-material-design: true\ndependencies:\n  flutter:\n    sdk: flutter\n", encoding="utf-8")
            cases = (
                ({"project_root": "../outside"}, "project_root: must not escape project_root"),
                ({"project_root": "app", "mode": "benchmark"}, "mode: must be one of"),
                ({"project_root": "app", "device": "--machine"}, "device: must not start with '-'"),
            )
            for configuration, message in cases:
                with self.subTest(configuration=configuration):
                    configuration_path = self.write_configuration(directory, configuration)
                    with self.assertRaisesRegex(ConfigurationError, message):
                        load_configuration(configuration_path)


if __name__ == "__main__":
    unittest.main()
