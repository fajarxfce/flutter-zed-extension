#!/usr/bin/env python3
"""Offline structural validation for the supported Zed extension manifest subset."""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = {
    "id": str,
    "name": str,
    "description": str,
    "version": str,
    "schema_version": int,
    "authors": list,
    "repository": str,
}


def fail(message: str) -> None:
    print(f"manifest validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def validate(manifest_path: Path) -> None:
    try:
        manifest: dict[str, Any] = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"manifest not found: {manifest_path}")
    except tomllib.TOMLDecodeError as error:
        fail(f"invalid TOML: {error}")

    for field, expected_type in REQUIRED_FIELDS.items():
        value = manifest.get(field)
        if not isinstance(value, expected_type) or (isinstance(value, str) and not value.strip()):
            fail(f"missing or invalid required field: {field}")

    if manifest["schema_version"] != 1:
        fail("schema_version must be 1")
    if not manifest["authors"] or not all(isinstance(author, str) and author.strip() for author in manifest["authors"]):
        fail("authors must be a non-empty list of non-empty strings")

    snippets = manifest.get("snippets", [])
    if not isinstance(snippets, list) or not all(isinstance(path, str) and path.strip() for path in snippets):
        fail("snippets must be a list of non-empty relative paths")
    for snippet_path in snippets:
        path = Path(snippet_path)
        if path.is_absolute() or ".." in path.parts or path.suffix != ".json":
            fail(f"invalid snippet path: {snippet_path}")

    forbidden = {"commands", "debug_adapters", "language_servers", "lib", "panels", "terminal", "tmux", "fvm"}
    present = forbidden.intersection(manifest)
    if present:
        fail(f"unsupported manifest declarations: {', '.join(sorted(present))}")

    print(f"manifest valid: {manifest_path}")
    print("capabilities: Flutter snippet metadata")
    print("Dart language navigation and debugging require Zed's official Dart extension")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", nargs="?", type=Path, default=Path("extension.toml"))
    args = parser.parse_args()
    validate(args.manifest)


if __name__ == "__main__":
    main()
