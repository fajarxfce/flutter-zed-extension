from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.project_detection import detect_project, parse_pubspec

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


class ProjectDetectionTests(unittest.TestCase):
    def test_flutter_app_from_nested_directory_records_optional_metadata(self) -> None:
        detected = detect_project(FIXTURES / "fvm_app" / "lib")
        self.assertEqual(detected.project_root, (FIXTURES / "fvm_app").resolve())
        self.assertEqual(detected.kind, "flutter_app")
        self.assertTrue(detected.has_run_configuration)
        self.assertTrue(detected.has_fvm_metadata)
        self.assertFalse(detected.has_zed_metadata)

    def test_zed_metadata_is_recorded_without_being_required(self) -> None:
        detected = detect_project(FIXTURES / "valid_app")
        self.assertEqual(detected.kind, "flutter_app")
        self.assertTrue(detected.has_zed_metadata)
        self.assertFalse(detected.has_fvm_metadata)

    def test_dart_package_has_no_flutter_run_configuration(self) -> None:
        detected = detect_project(FIXTURES / "dart_package" / "lib")
        self.assertEqual(detected.kind, "dart_package")
        self.assertFalse(detected.has_run_configuration)
        self.assertEqual(detected.diagnostics, ())

    def test_malformed_and_non_project_fixtures_are_invalid(self) -> None:
        malformed = detect_project(FIXTURES / "malformed_pubspec")
        missing = detect_project(FIXTURES / "invalid_project")
        self.assertEqual(malformed.kind, "invalid")
        self.assertIn("malformed pubspec.yaml", malformed.diagnostics[0])
        self.assertEqual(missing.kind, "invalid")
        self.assertEqual(missing.diagnostics, ("no pubspec.yaml found from start path",))

    def test_workspace_root_requires_declared_workspace_membership(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / "packages" / "app" / "lib").mkdir(parents=True)
            (workspace / "pubspec.yaml").write_text(
                "name: workspace\nenvironment:\n  sdk: \">=3.0.0 <4.0.0\"\nworkspace:\n  - packages/app\n",
                encoding="utf-8",
            )
            (workspace / "packages" / "app" / "pubspec.yaml").write_text(
                "name: app\nenvironment:\n  sdk: \">=3.0.0 <4.0.0\"\ndependencies:\n  flutter:\n    sdk: flutter\nflutter:\n",
                encoding="utf-8",
            )
            detected = detect_project(workspace / "packages" / "app" / "lib")
        self.assertEqual(detected.kind, "flutter_app")
        self.assertEqual(detected.workspace_root, workspace)

    def test_workspace_list_followed_by_top_level_key_remains_a_list(self) -> None:
        pubspec = "name: workspace\nworkspace:\n  - packages/app\nenvironment:\n  sdk: \">=3.0.0 <4.0.0\"\n"
        self.assertEqual(parse_pubspec(pubspec)["workspace"], ["packages/app"])

    def test_inline_comments_are_removed_without_changing_quoted_hashes(self) -> None:
        pubspec = 'name: app\npublish_to: "none" # hris uses a private package\ndescription: "Preserve # inside quotes"\n'
        parsed = parse_pubspec(pubspec)
        self.assertEqual(parsed["publish_to"], "none")
        self.assertEqual(parsed["description"], "Preserve # inside quotes")

    def test_nested_pubspec_wins_over_ancestor_workspace(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary_directory:
            workspace = Path(temporary_directory)
            (workspace / "nested").mkdir()
            (workspace / "pubspec.yaml").write_text(
                "name: parent\nenvironment:\n  sdk: \">=3.0.0 <4.0.0\"\nworkspace:\n  - other\n",
                encoding="utf-8",
            )
            (workspace / "nested" / "pubspec.yaml").write_text(
                "name: nested\nenvironment:\n  sdk: \">=3.0.0 <4.0.0\"\n",
                encoding="utf-8",
            )
            detected = detect_project(workspace / "nested")
        self.assertEqual(detected.project_root, workspace / "nested")
        self.assertEqual(detected.kind, "dart_package")
        self.assertIsNone(detected.workspace_root)
