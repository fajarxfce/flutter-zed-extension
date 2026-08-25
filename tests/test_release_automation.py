from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReleaseAutomationTests(unittest.TestCase):
    def copied_root(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary_directory = tempfile.TemporaryDirectory()
        root = Path(temporary_directory.name) / "package-root"
        shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "dist", "__pycache__", ".pytest_cache", ".venv", ".sisyphus"))
        return temporary_directory, root

    def test_package_is_reproducible_and_excludes_development_content(self) -> None:
        temporary_directory, root = self.copied_root()
        self.addCleanup(temporary_directory.cleanup)
        first = root / "dist" / "first.tar.gz"
        second = root / "dist" / "second.tar.gz"
        for output in (first, second):
            result = subprocess.run(
                (sys.executable, "scripts/package_release.py", "--root", ".", "--output", str(output.relative_to(root))),
                cwd=root,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        listing = subprocess.run(("tar", "-tzf", str(first)), capture_output=True, text=True, check=True).stdout
        self.assertNotIn("tests/", listing)
        self.assertNotIn(".sisyphus", listing)
        self.assertNotIn("__pycache__", listing)

    def test_version_mismatch_names_each_source(self) -> None:
        temporary_directory, root = self.copied_root()
        self.addCleanup(temporary_directory.cleanup)
        changelog = root / "CHANGELOG.md"
        changelog.write_text(changelog.read_text(encoding="utf-8").replace("## [0.1.0]", "## [9.9.9]"), encoding="utf-8")
        result = subprocess.run(
            (sys.executable, "scripts/release_check.py", "versions", "."),
            cwd=root,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("extension.toml=0.1.0", result.stderr)
        self.assertIn("CHANGELOG.md=9.9.9", result.stderr)


if __name__ == "__main__":
    unittest.main()
