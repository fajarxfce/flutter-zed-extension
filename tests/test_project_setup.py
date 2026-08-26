from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from scripts.configuration import FlutterConfiguration
from scripts.project_setup import ProjectSetupError, setup_project
from scripts.sdk_resolution import ExecutableVersion, ResolvedSdk

ROOT = Path(__file__).resolve().parents[1]


class ProjectSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(dir=ROOT)
        self.directory = Path(self.temporary_directory.name)
        self.root = self.directory / "app"
        (self.root / "lib").mkdir(parents=True)
        (self.root / "lib" / "main.dart").touch()
        (self.root / "pubspec.yaml").write_text("name: app\nflutter:\n  uses-material-design: true\ndependencies:\n  flutter:\n    sdk: flutter\n", encoding="utf-8")
        executable = self.directory / "flutter"
        executable.touch()
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        version = ExecutableVersion(executable, "", "")
        self.sdk = ResolvedSdk("explicit", self.directory, version, version)
        self.configuration = FlutterConfiguration(self.root, self.root, "flutter", None, None, None, "debug", (), None, None)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_dry_run_merges_owned_entries_and_repeat_is_idempotent(self) -> None:
        zed = self.root / ".zed"
        zed.mkdir()
        tasks = zed / "tasks.json"
        debug = zed / "debug.json"
        tasks.write_text('[{"label": "User task", "command": "true"}, {"label": "Flutter: Test", "old": true}]\n', encoding="utf-8")
        debug.write_text('[{"label": "User debug", "adapter": "Other"}, {"label": "Flutter: Launch", "old": true}]\n', encoding="utf-8")

        dry_result = setup_project(self.configuration, self.sdk, dry_run=True)
        self.assertTrue(dry_result.changed)
        self.assertIn("---", dry_result.diff)
        self.assertIn("Flutter: Test", dry_result.diff)
        self.assertIn('"old": true', tasks.read_text(encoding="utf-8"))

        result = setup_project(self.configuration, self.sdk)
        self.assertTrue(result.changed)
        task_document = json.loads(tasks.read_text(encoding="utf-8"))
        debug_document = json.loads(debug.read_text(encoding="utf-8"))
        self.assertIsInstance(task_document, list)
        self.assertEqual(task_document[0], {"label": "User task", "command": "true"})
        self.assertEqual(debug_document[0], {"label": "User debug", "adapter": "Other"})
        self.assertEqual(sum(task["label"] == "Flutter: Test" for task in task_document), 1)
        self.assertEqual(sum(entry["label"] == "Flutter: Launch" for entry in debug_document), 1)
        self.assertEqual(setup_project(self.configuration, self.sdk).changed, False)
        self.assertEqual(setup_project(self.configuration, self.sdk, dry_run=True).diff, "")
        self.assertEqual(stat.S_IMODE(tasks.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(debug.stat().st_mode), 0o600)

    def test_nested_worktree_writes_root_metadata_and_preserves_user_entries(self) -> None:
        worktree = self.directory / "monorepo"
        worktree.mkdir()
        nested = worktree / "app"
        self.root.rename(nested)
        self.root = nested
        self.configuration = FlutterConfiguration(self.root, worktree, "flutter", self.root / "lib" / "main.dart", None, "prod", "debug", (), None, None)
        zed = worktree / ".zed"
        zed.mkdir()
        tasks = zed / "tasks.json"
        debug = zed / "debug.json"
        tasks.write_text('[{"label": "User task", "command": "true"}]\n', encoding="utf-8")
        debug.write_text('[{"label": "User debug", "adapter": "Other"}]\n', encoding="utf-8")

        result = setup_project(self.configuration, self.sdk)

        task_document = json.loads(tasks.read_text(encoding="utf-8"))
        debug_document = json.loads(debug.read_text(encoding="utf-8"))
        run = next(task for task in task_document if task["label"] == "Flutter: Run")
        self.assertEqual(result.tasks_path, tasks)
        self.assertEqual(result.debug_path, debug)
        self.assertEqual(run["cwd"], "$ZED_WORKTREE_ROOT/app")
        self.assertEqual(run["args"], ["run", "--target", "lib/main.dart", "--flavor", "prod", "--debug"])
        self.assertEqual(debug_document[-1]["cwd"], "$ZED_WORKTREE_ROOT/app")
        self.assertFalse((self.root / ".zed").exists())
        self.assertFalse(any(str(self.directory) in json.dumps(document) for document in (task_document, debug_document)))
        self.assertFalse(setup_project(self.configuration, self.sdk).changed)

    def test_legacy_generated_tasks_wrapper_is_migrated_to_zed_array_root(self) -> None:
        tasks = self.root / ".zed" / "tasks.json"
        tasks.parent.mkdir()
        tasks.write_text('{"tasks": [{"label": "Flutter: Test", "old": true}]}\n', encoding="utf-8")

        result = setup_project(self.configuration, self.sdk)

        self.assertTrue(result.changed)
        document = json.loads(tasks.read_text(encoding="utf-8"))
        self.assertIsInstance(document, list)
        self.assertEqual(sum(task["label"] == "Flutter: Test" for task in document), 1)

    def test_unrecognized_tasks_wrapper_is_never_overwritten(self) -> None:
        tasks = self.root / ".zed" / "tasks.json"
        tasks.parent.mkdir()
        tasks.write_text('{"tasks": [{"label": "User task", "command": "true"}]}\n', encoding="utf-8")
        before = tasks.read_bytes()

        with self.assertRaises(ProjectSetupError) as raised:
            setup_project(self.configuration, self.sdk)

        self.assertEqual(raised.exception.diagnostic.code, "configuration.invalid")
        self.assertEqual(tasks.read_bytes(), before)

    def test_jsonc_debug_config_preserves_user_entries_and_comment_like_strings(self) -> None:
        zed = self.root / ".zed"
        zed.mkdir()
        debug = zed / "debug.json"
        debug.write_text(
            "// Project-local debug tasks\n"
            "[\n"
            "  {\n"
            '    "label": "Flutter: Dev", // retain this user entry\n'
            '    "adapter": "Dart",\n'
            '    "program": "lib/main.dart",\n'
            '    "url": "https://example.test/path//not-a-comment"\n'
            "  },\n"
            "  /* production configuration */\n"
            "  {\n"
            '    "label": "Flutter: Prod",\n'
            '    "adapter": "Dart",\n'
            '    "program": "lib/main_prod.dart"\n'
            "  }\n"
            "]\n",
            encoding="utf-8",
        )

        result = setup_project(self.configuration, self.sdk)

        self.assertTrue(result.changed)
        debug_document = json.loads(debug.read_text(encoding="utf-8"))
        self.assertEqual(debug_document[0]["label"], "Flutter: Dev")
        self.assertEqual(debug_document[0]["url"], "https://example.test/path//not-a-comment")
        self.assertEqual(debug_document[1]["label"], "Flutter: Prod")
        self.assertEqual(sum(entry["label"] == "Flutter: Launch" for entry in debug_document), 1)

    def test_malformed_jsonc_is_never_overwritten_or_partially_written(self) -> None:
        zed = self.root / ".zed"
        zed.mkdir()
        tasks = zed / "tasks.json"
        debug = zed / "debug.json"
        tasks.write_text('{"tasks": []}', encoding="utf-8")
        debug.write_text('[{"label": "User debug"} /* unclosed', encoding="utf-8")
        tasks_before = tasks.read_bytes()
        debug_before = debug.read_bytes()

        with self.assertRaises(ProjectSetupError) as raised:
            setup_project(self.configuration, self.sdk)

        self.assertEqual(raised.exception.diagnostic.code, "configuration.invalid")
        self.assertEqual(tasks.read_bytes(), tasks_before)
        self.assertEqual(debug.read_bytes(), debug_before)

    def test_malformed_config_is_never_overwritten_or_partially_written(self) -> None:
        zed = self.root / ".zed"
        zed.mkdir()
        tasks = zed / "tasks.json"
        debug = zed / "debug.json"
        tasks.write_text('{"tasks": [}', encoding="utf-8")
        debug.write_text('[{"label": "User debug"}]\n', encoding="utf-8")
        tasks_before = tasks.read_bytes()
        debug_before = debug.read_bytes()

        with self.assertRaises(ProjectSetupError) as raised:
            setup_project(self.configuration, self.sdk)

        self.assertEqual(raised.exception.diagnostic.code, "configuration.invalid")
        self.assertEqual(tasks.read_bytes(), tasks_before)
        self.assertEqual(debug.read_bytes(), debug_before)

    def test_non_flutter_project_is_refused_before_creating_zed_files(self) -> None:
        (self.root / "pubspec.yaml").write_text("name: package\nenvironment:\n  sdk: ^3.0.0\n", encoding="utf-8")

        with self.assertRaises(ProjectSetupError) as raised:
            setup_project(self.configuration, self.sdk)

        self.assertEqual(raised.exception.diagnostic.code, "project.invalid")
        self.assertFalse((self.root / ".zed").exists())
