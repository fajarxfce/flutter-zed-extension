from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_manifest.py"
MANIFEST = ROOT / "extension.toml"


class ManifestValidationTests(unittest.TestCase):
    def run_validator(self, manifest: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(VALIDATOR), str(manifest)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_canonical_manifest_is_valid_without_tmux_or_fvm(self) -> None:
        result = self.run_validator(MANIFEST)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Flutter snippet metadata", result.stdout)
        self.assertIn("official Dart extension", result.stdout)
        self.assertNotIn("tmux", result.stdout.lower())

    def test_missing_required_field_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            invalid_manifest = Path(temporary_directory) / "extension.toml"
            contents = MANIFEST.read_text(encoding="utf-8").replace('id = "flutter"\n', "", 1)
            invalid_manifest.write_text(contents, encoding="utf-8")
            result = self.run_validator(invalid_manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing or invalid required field: id", result.stderr)

    def test_manifest_does_not_require_optional_tools(self) -> None:
        self.assertIsNone(shutil.which("fvm"))
        result = self.run_validator(MANIFEST)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_language_server_registration_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            invalid_manifest = Path(temporary_directory) / "extension.toml"
            invalid_manifest.write_text(
                MANIFEST.read_text(encoding="utf-8")
                + "\n[language_servers.dart]\nlanguage = \"Dart\"\nlanguages = [\"Dart\"]\n",
                encoding="utf-8",
            )
            result = self.run_validator(invalid_manifest)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported manifest declarations: language_servers", result.stderr)

    def test_manifest_registers_only_flutter_snippet_metadata(self) -> None:
        manifest = MANIFEST.read_text(encoding="utf-8")
        self.assertIn('snippets = ["./snippets/flutter.json"]', manifest)
        self.assertNotIn("language_servers", manifest)
        self.assertNotIn("debug_adapters", manifest)
        self.assertNotIn("languages = [\"Flutter\"]", manifest)


if __name__ == "__main__":
    unittest.main()
