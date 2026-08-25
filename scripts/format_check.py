#!/usr/bin/env python3
"""Dependency-free formatting policy for repository text files."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ROOT / "extension.toml",
    ROOT / "pyproject.toml",
    ROOT / "Makefile",
    ROOT / "README.md",
    ROOT / "CONFIGURATION.md",
    ROOT / ".gitignore",
    *(ROOT / "scripts").glob("*.py"),
    *(ROOT / "snippets").glob("*.json"),
    *(ROOT / "tests").glob("*.py"),
]


def main() -> None:
    invalid = []
    for path in FILES:
        contents = path.read_text(encoding="utf-8")
        if not contents.endswith("\n") or any(line.rstrip(" \t") != line for line in contents.splitlines()):
            invalid.append(path.relative_to(ROOT))
    if invalid:
        raise SystemExit(f"format check failed: {', '.join(map(str, invalid))}")
    print("format check passed")


if __name__ == "__main__":
    main()
