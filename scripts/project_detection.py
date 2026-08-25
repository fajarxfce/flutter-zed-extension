#!/usr/bin/env python3
"""Deterministic, dependency-free Dart and Flutter project detection.

This module only reads project metadata.  It neither resolves an SDK nor executes
Flutter, Dart, FVM, Zed, a shell, or generated run configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

ProjectKind: TypeAlias = Literal["flutter_app", "dart_package", "invalid"]
YamlValue: TypeAlias = str | dict[str, "YamlValue"] | list[str]


@dataclass(frozen=True)
class ProjectDetection:
    """The canonical metadata classification for a discovered project."""

    project_root: Path
    kind: ProjectKind
    diagnostics: tuple[str, ...]
    workspace_root: Path | None
    has_fvm_metadata: bool
    has_zed_metadata: bool

    @property
    def has_run_configuration(self) -> bool:
        """Only a material Flutter application can produce a run configuration."""
        return self.kind == "flutter_app"


class PubspecError(ValueError):
    """Raised for pubspec YAML outside the deliberately supported subset."""


def _scalar(value: str, line_number: int) -> str:
    if not value or value.startswith(("[", "{", "&", "*", "|", ">")):
        raise PubspecError(f"line {line_number}: unsupported YAML value")
    if " #" in value or "\t" in value:
        raise PubspecError(f"line {line_number}: unsupported YAML syntax")
    if value[0:1] in {"'", '"'}:
        if len(value) < 2 or value[-1] != value[0]:
            raise PubspecError(f"line {line_number}: unterminated quoted scalar")
        return value[1:-1]
    return value


def parse_pubspec(contents: str) -> dict[str, YamlValue]:
    """Parse the small indentation-based YAML subset material to pubspec checks."""
    root: dict[str, YamlValue] = {}
    stack: list[tuple[int, dict[str, YamlValue]]] = [(-1, root)]
    pending: tuple[int, dict[str, YamlValue], str] | None = None

    for line_number, raw_line in enumerate(contents.splitlines(), start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith("\t") or "\t" in raw_line[: len(raw_line) - len(raw_line.lstrip(" "))]:
            raise PubspecError(f"line {line_number}: tabs are unsupported")
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        text = raw_line[indent:]
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        if text.startswith("- "):
            if pending is None or indent <= pending[0]:
                raise PubspecError(f"line {line_number}: list has no mapping key")
            parent_indent, parent, key = pending
            if indent <= parent_indent:
                raise PubspecError(f"line {line_number}: invalid list indentation")
            existing = parent.get(key)
            if existing is None or existing == {}:
                existing = []
                parent[key] = existing
            if not isinstance(existing, list):
                raise PubspecError(f"line {line_number}: mixed mapping and list values")
            existing.append(_scalar(text[2:].strip(), line_number))
            stack = [(stack_indent, mapping) for stack_indent, mapping in stack if stack_indent < indent]
            pending = None
            continue
        if ":" not in text:
            raise PubspecError(f"line {line_number}: expected key: value")
        key, value = text.split(":", maxsplit=1)
        key = key.strip()
        if not key or key.startswith(("-", "?", "&", "*")):
            raise PubspecError(f"line {line_number}: unsupported YAML key")
        value = value.strip()
        parent = stack[-1][1]
        if key in parent:
            raise PubspecError(f"line {line_number}: duplicate key {key!r}")
        pending = (indent, parent, key)
        if value:
            parent[key] = _scalar(value, line_number)
            continue
        mapping: dict[str, YamlValue] = {}
        parent[key] = mapping
        stack.append((indent, mapping))

    if not root:
        raise PubspecError("pubspec is empty")
    return root


def _mapping(value: YamlValue | None) -> dict[str, YamlValue] | None:
    return value if isinstance(value, dict) else None


def _is_flutter_app(pubspec: dict[str, YamlValue]) -> bool:
    dependencies = _mapping(pubspec.get("dependencies"))
    flutter_dependency = _mapping(dependencies.get("flutter")) if dependencies else None
    return flutter_dependency is not None and flutter_dependency.get("sdk") == "flutter" and "flutter" in pubspec


def _is_dart_package(pubspec: dict[str, YamlValue]) -> bool:
    environment = _mapping(pubspec.get("environment"))
    return isinstance(pubspec.get("name"), str) and environment is not None and isinstance(environment.get("sdk"), str)


def _workspace_root(project_root: Path) -> Path | None:
    for candidate in (project_root, *project_root.parents):
        pubspec_path = candidate / "pubspec.yaml"
        if not pubspec_path.is_file():
            continue
        try:
            pubspec = parse_pubspec(pubspec_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, PubspecError):
            continue
        workspace = pubspec.get("workspace")
        if isinstance(workspace, list):
            relative = project_root.relative_to(candidate).as_posix()
            if relative in workspace or candidate == project_root:
                return candidate
    return None


def detect_project(start: Path) -> ProjectDetection:
    """Find the nearest pubspec from *start* and classify it without SDK calls."""
    try:
        current = start.resolve(strict=True)
    except OSError as error:
        root = start.resolve(strict=False)
        return ProjectDetection(root, "invalid", (f"cannot resolve start path: {error}",), None, False, False)
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        pubspec_path = candidate / "pubspec.yaml"
        if not pubspec_path.is_file():
            continue
        metadata = (candidate / ".fvm").exists() or (candidate / ".fvmrc").is_file()
        zed_metadata = (candidate / ".zed").is_dir()
        try:
            pubspec = parse_pubspec(pubspec_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, PubspecError) as error:
            return ProjectDetection(candidate, "invalid", (f"malformed pubspec.yaml: {error}",), None, metadata, zed_metadata)
        workspace_root = _workspace_root(candidate)
        if _is_flutter_app(pubspec):
            return ProjectDetection(candidate, "flutter_app", (), workspace_root, metadata, zed_metadata)
        if _is_dart_package(pubspec):
            return ProjectDetection(candidate, "dart_package", (), workspace_root, metadata, zed_metadata)
        return ProjectDetection(candidate, "invalid", ("pubspec.yaml lacks material Dart or Flutter project evidence",), workspace_root, metadata, zed_metadata)

    return ProjectDetection(current, "invalid", ("no pubspec.yaml found from start path",), None, False, False)
