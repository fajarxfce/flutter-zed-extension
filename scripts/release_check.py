#!/usr/bin/env python3
"""Validate release metadata and inspect deterministic extension archives."""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
import tomllib
from pathlib import Path
VERSION_PATTERN = re.compile(r"^## \[(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)\]")
EXCLUDED_PARTS = {".git", ".sisyphus", "tests", "__pycache__", ".pytest_cache", ".venv", "dist"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EVIDENCE_NAME_PATTERN = re.compile(r"^task-\d+-.*\.txt$")
SECRET_NAME_PATTERN = re.compile(r"(?:^|[._-])(secret|token|credential|password|private|id_rsa)(?:[._-]|$)", re.IGNORECASE)


def fail(message: str) -> None:
    print(f"release validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_toml(path: Path) -> dict[str, object]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, tomllib.TOMLDecodeError) as error:
        fail(f"cannot read {path}: {error}")


def changelog_version(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            match = VERSION_PATTERN.match(line)
            if match:
                return match.group(1)
    except FileNotFoundError:
        pass
    fail(f"no release heading found in {path}")


def versions(root: Path) -> dict[str, str]:
    manifest = load_toml(root / "extension.toml")
    project = load_toml(root / "pyproject.toml").get("project")
    if not isinstance(project, dict):
        fail("pyproject.toml has no [project] table")
    values = {
        "extension.toml": manifest.get("version"),
        "pyproject.toml": project.get("version"),
        "CHANGELOG.md": changelog_version(root / "CHANGELOG.md"),
    }
    if not all(isinstance(version, str) and version for version in values.values()):
        fail("all release versions must be non-empty strings")
    return {name: str(version) for name, version in values.items()}


def validate_versions(root: Path) -> None:
    values = versions(root)
    if len(set(values.values())) != 1:
        fail("version mismatch: " + ", ".join(f"{name}={version}" for name, version in values.items()))
    print(f"release versions consistent: {next(iter(values.values()))}")


def archive_members(archive: Path) -> Iterable[tarfile.TarInfo]:
    try:
        with tarfile.open(archive, "r:gz") as package:
            yield from package.getmembers()
    except (FileNotFoundError, tarfile.TarError) as error:
        fail(f"cannot inspect {archive}: {error}")


def validate_archive(archive: Path) -> None:
    names: list[str] = []
    with tarfile.open(archive, "r:gz") as package:
        for member in package.getmembers():
            name = member.name
            path = Path(name)
            if path.is_absolute() or ".." in path.parts:
                fail(f"unsafe archive member: {name}")
            if any(part in EXCLUDED_PARTS for part in path.parts):
                fail(f"excluded archive member: {name}")
            if path.suffix in EXCLUDED_SUFFIXES or EVIDENCE_NAME_PATTERN.fullmatch(path.name) or SECRET_NAME_PATTERN.search(path.name):
                fail(f"forbidden archive member: {name}")
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                fail(f"unsupported archive member type: {name}")
            if member.isfile():
                source = package.extractfile(member)
                if source is not None and (b"/" + b"home/") in source.read():
                    fail(f"absolute local path in archive member: {name}")
            names.append(name)
    if names != sorted(names):
        fail("archive members are not sorted")
    print(f"clean archive: {archive} ({len(names)} members)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("versions", "archive"))
    parser.add_argument("path", nargs="?", type=Path)
    args = parser.parse_args()
    if args.command == "versions":
        validate_versions(args.path or Path.cwd())
    else:
        if args.path is None:
            parser.error("archive path is required")
        validate_archive(args.path)


if __name__ == "__main__":
    main()
