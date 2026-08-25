from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "extension.toml"
SNIPPETS = ROOT / "snippets" / "flutter.json"
VALIDATOR = ROOT / "scripts" / "validate_snippets.py"


class FlutterSnippetTests(unittest.TestCase):
    def test_widget_snippets_have_expected_triggers_and_placeholders(self) -> None:
        snippets = json.loads(SNIPPETS.read_text(encoding="utf-8"))
        stateful = snippets["Flutter StatefulWidget"]
        stateless = snippets["Flutter StatelessWidget"]

        self.assertEqual(stateful["prefix"], "stful")
        self.assertEqual(stateless["prefix"], "stless")
        self.assertIn("class ${1:WidgetName} extends StatefulWidget {", stateful["body"])
        self.assertIn("  State<${1:WidgetName}> createState() => _${1:WidgetName}State();", stateful["body"])
        self.assertIn("class ${1:WidgetName} extends StatelessWidget {", stateless["body"])
        self.assertIn("    return ${2:const Placeholder()};", stateless["body"])
        self.assertEqual(stateful["body"][-1], "$0")
        self.assertEqual(stateless["body"][-1], "$0")

    def test_snippet_metadata_is_scoped_to_flutter_and_unknown_files_are_unaffected(self) -> None:
        result = subprocess.run(
            ["python3", str(VALIDATOR), str(MANIFEST)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Flutter buffers only", result.stdout)
        self.assertIn("Dart and unknown files are unaffected", result.stdout)


if __name__ == "__main__":
    unittest.main()
