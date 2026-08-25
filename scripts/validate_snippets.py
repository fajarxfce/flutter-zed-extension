#!/usr/bin/env python3
"""Offline validation for Zed extension snippet metadata."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any


def fail(message: str) -> None:
    print(f"snippet validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def validate(manifest_path: Path) -> None:
    try:
        manifest: dict[str, Any] = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"manifest not found: {manifest_path}")
    except tomllib.TOMLDecodeError as error:
        fail(f"invalid TOML: {error}")

    snippets = manifest.get("snippets", [])
    if not isinstance(snippets, list) or not snippets:
        fail("manifest must declare at least one snippet file")

    for configured_path in snippets:
        if not isinstance(configured_path, str):
            fail("snippet paths must be strings")
        path = Path(configured_path)
        if path.is_absolute() or ".." in path.parts or path.suffix != ".json":
            fail(f"invalid snippet path: {configured_path}")
        if path.stem != "flutter":
            fail(f"snippet filename must target Flutter buffers: {configured_path}")

        snippet_file = manifest_path.parent / path
        try:
            snippets_by_name: dict[str, Any] = json.loads(snippet_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            fail(f"snippet file not found: {configured_path}")
        except json.JSONDecodeError as error:
            fail(f"invalid JSON in {configured_path}: {error}")
        if not isinstance(snippets_by_name, dict) or not snippets_by_name:
            fail(f"snippet file must contain a non-empty object: {configured_path}")

        for name, snippet in snippets_by_name.items():
            if not isinstance(name, str) or not name.strip() or not isinstance(snippet, dict):
                fail(f"invalid snippet declaration in {configured_path}")
            prefix = snippet.get("prefix")
            body = snippet.get("body")
            description = snippet.get("description")
            if not isinstance(prefix, str) or not prefix.strip():
                fail(f"snippet {name!r} must have a non-empty prefix")
            if not isinstance(body, list) or not body or not all(isinstance(line, str) for line in body):
                fail(f"snippet {name!r} must have a non-empty string body")
            if not isinstance(description, str) or not description.strip():
                fail(f"snippet {name!r} must have a non-empty description")

    print(f"snippet metadata valid: {manifest_path}")
    print("association: Flutter buffers only; Dart and unknown files are unaffected")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", nargs="?", type=Path, default=Path("extension.toml"))
    args = parser.parse_args()
    validate(args.manifest)


if __name__ == "__main__":
    main()
