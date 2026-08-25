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


def _strip_inline_comment(text: str) -> str:
    quote: str | None = None
    index = 0
    while index < len(text):
        character = text[index]
        if quote is None:
            if character in {"'", '"'}:
                quote = character
            elif character == "#" and index > 0 and text[index - 1].isspace():
                return text[:index].rstrip()
        elif character == quote:
            if quote == "'" and index + 1 < len(text) and text[index + 1] == "'":
                index += 1
            elif quote == '"' and index > 0 and text[index - 1] == "\\":
                pass
            else:
                quote = None
        index += 1
    return text


def _scalar(value: str, line_number: int) -> str:
    if not value or value.startswith(("[", "{", "&", "*", "|", ">")):
        raise PubspecError(f"line {line_number}: unsupported YAML value")
    if "\t" in value:
        raise PubspecError(f"line {line_number}: unsupported YAML syntax")
    if value[0:1] in {"'", '"'}:
        if len(value) < 2 or value[-1] != value[0]:
            raise PubspecError(f"line {line_number}: unterminated quoted scalar")
        return value[1:-1]
    return value


def parse_pubspec(contents: str) -> dict[str, YamlValue]:
    """Extract only the pubspec metadata used for project classification.

    Pubspecs permit arbitrary package and Flutter configuration.  This scanner
    validates the small set of structural paths the detector consumes while
    deliberately skipping unrelated subtrees.
    """
    root: dict[str, YamlValue] = {}
    active_mapping: tuple[str, int] | None = None
    workspace_indent: int | None = None

    for line_number, raw_line in enumerate(contents.splitlines(), start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith("\t") or "\t" in raw_line[: len(raw_line) - len(raw_line.lstrip(" "))]:
            raise PubspecError(f"line {line_number}: tabs are unsupported")
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        text = raw_line[indent:]

        if workspace_indent is not None and indent > workspace_indent and text.startswith("- "):
            workspace = root["workspace"]
            if not isinstance(workspace, list):
                raise PubspecError(f"line {line_number}: workspace must be a list")
            workspace.append(_scalar(_strip_inline_comment(text[2:]).strip(), line_number))
            continue
        if indent == 0:
            active_mapping = None
            workspace_indent = None
            if ":" not in text:
                continue
            key, value = text.split(":", maxsplit=1)
            key = key.strip()
            value = _strip_inline_comment(value).strip()
            if key not in {"name", "environment", "dependencies", "flutter", "workspace"}:
                if value:
                    try:
                        root[key] = _scalar(value, line_number)
                    except PubspecError:
                        pass
                continue
            if key in root:
                raise PubspecError(f"line {line_number}: duplicate key {key!r}")
            if key == "flutter":
                if value:
                    _scalar(value, line_number)
                root[key] = {}
            elif key == "workspace":
                if value:
                    raise PubspecError(f"line {line_number}: workspace must be a list")
                root[key] = []
                workspace_indent = indent
            elif key in {"environment", "dependencies"}:
                if value:
                    raise PubspecError(f"line {line_number}: {key} must be a mapping")
                root[key] = {}
                active_mapping = (key, indent)
            else:
                root[key] = _scalar(value, line_number)
            continue

        if active_mapping is None or indent <= active_mapping[1] or ":" not in text:
            continue
        parent, parent_indent = active_mapping
        if indent <= parent_indent:
            continue
        key, value = text.split(":", maxsplit=1)
        key = key.strip()
        value = _strip_inline_comment(value).strip()
        mapping = (
            _mapping(_mapping(root["dependencies"]).get("flutter"))
            if parent == "flutter_dependency"
            else _mapping(root[parent])
        )
        if mapping is None:
            raise PubspecError(f"line {line_number}: {parent} must be a mapping")
        if parent == "environment" and key == "sdk":
            if key in mapping:
                raise PubspecError(f"line {line_number}: duplicate key {key!r}")
            mapping[key] = _scalar(value, line_number)
        elif parent == "dependencies" and key == "flutter":
            if key in mapping or value:
                raise PubspecError(f"line {line_number}: flutter dependency must be a mapping")
            mapping[key] = {}
            active_mapping = ("flutter_dependency", indent)
        elif parent == "flutter_dependency" and key == "sdk":
            if key in mapping:
                raise PubspecError(f"line {line_number}: duplicate key {key!r}")
            mapping[key] = _scalar(value, line_number)

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
