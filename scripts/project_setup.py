#!/usr/bin/env python3
"""Safely install this project's generated Zed task and debug entries.

Only entries with the stable labels emitted by ``task_templates`` and
``dap_templates`` are owned.  All other JSON values remain intact.  The caller
provides already validated configuration and a resolved SDK; this module probes
no SDKs and starts no external processes.
"""

from __future__ import annotations

import difflib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.configuration import FlutterConfiguration
from scripts.dap_templates import generate_debug_configurations
from scripts.diagnostics import Diagnostic, invalid_configuration, invalid_project
from scripts.project_detection import detect_project
from scripts.sdk_resolution import ResolvedSdk
from scripts.task_templates import generate_task_templates


class ProjectSetupError(RuntimeError):
    """Raised when setup cannot safely read or write consumer-owned Zed metadata."""

    def __init__(self, message: str, diagnostic: Diagnostic) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic


@dataclass(frozen=True)
class SetupResult:
    """A deterministic summary; ``diff`` is empty when no changes are needed."""

    tasks_path: Path
    debug_path: Path
    diff: str
    changed: bool
    dry_run: bool


def _strip_jsonc_comments(contents: str) -> str:
    output: list[str] = []
    quote = False
    escaped = False
    index = 0
    while index < len(contents):
        character = contents[index]
        following = contents[index + 1] if index + 1 < len(contents) else ""
        if quote:
            output.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quote = False
            index += 1
            continue
        if character == '"':
            quote = True
            output.append(character)
            index += 1
        elif character == "/" and following == "/":
            index += 2
            while index < len(contents) and contents[index] not in "\r\n":
                index += 1
        elif character == "/" and following == "*":
            index += 2
            while index + 1 < len(contents) and contents[index : index + 2] != "*/":
                if contents[index] in "\r\n":
                    output.append(contents[index])
                index += 1
            if index + 1 >= len(contents):
                raise json.JSONDecodeError("Unterminated JSONC block comment", contents, index)
            index += 2
        else:
            output.append(character)
            index += 1
    if quote:
        raise json.JSONDecodeError("Unterminated JSON string", contents, len(contents))
    return "".join(output)


def _read_json(path: Path, expected: type[object] | tuple[type[object], ...], empty: object) -> object:
    if not path.exists():
        return empty
    try:
        value = json.loads(_strip_jsonc_comments(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ProjectSetupError(
            f"Cannot safely update malformed Zed configuration: {path}: {error}",
            invalid_configuration("Existing Zed configuration is malformed; it was not overwritten.", configuration_path=str(path)),
        ) from error
    if not isinstance(value, expected):
        raise ProjectSetupError(
            f"Cannot safely update Zed configuration with unexpected JSON shape: {path}",
            invalid_configuration("Existing Zed configuration has an unsupported top-level JSON shape; it was not overwritten.", configuration_path=str(path)),
        )
    return value


def _merge_labeled_entries(existing: list[Any], generated: list[dict[str, object]]) -> list[Any]:
    labels = {entry["label"] for entry in generated}
    retained = [entry for entry in existing if not (isinstance(entry, dict) and entry.get("label") in labels)]
    return [*retained, *generated]


def _tasks_document(existing: list[Any] | dict[str, Any], generated: list[dict[str, object]]) -> list[Any]:
    if isinstance(existing, list):
        return _merge_labeled_entries(existing, generated)
    tasks = existing.get("tasks")
    generated_labels = {entry["label"] for entry in generated}
    is_legacy_generated = (
        set(existing) == {"tasks"}
        and isinstance(tasks, list)
        and all(isinstance(entry, dict) and entry.get("label") in generated_labels for entry in tasks)
    )
    if is_legacy_generated:
        return _merge_labeled_entries(tasks, generated)
    raise ProjectSetupError(
        "Cannot safely migrate unsupported Zed tasks document.",
        invalid_configuration("Existing .zed/tasks.json is not an array or a recognized legacy generated wrapper; it was not overwritten."),
    )


def _render(document: object) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _diff(path: Path, before: str, after: str) -> str:
    if before == after:
        return ""
    return "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile=str(path), tofile=str(path)))


def _atomic_write(path: Path, contents: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def setup_project(configuration: FlutterConfiguration, sdk: ResolvedSdk, *, dry_run: bool = False) -> SetupResult:
    """Merge generated Flutter entries into the opened worktree's `.zed` files.

    Both existing files are parsed before either write, so malformed metadata
    cannot cause a partial overwrite.  A dry run only returns a stable unified
    diff; repeated non-dry executions are idempotent.
    """
    detection = detect_project(configuration.project_root)
    if not detection.has_run_configuration or detection.project_root.resolve() != configuration.project_root.resolve():
        raise ProjectSetupError(
            f"Refusing to create Zed files outside a detected Flutter application: {configuration.project_root}",
            invalid_project("Project setup requires a detected Flutter application.", project_root=str(configuration.project_root)),
        )
    worktree_root = configuration.worktree_root.resolve()
    tasks_path = worktree_root / ".zed" / "tasks.json"
    debug_path = worktree_root / ".zed" / "debug.json"
    tasks_before = tasks_path.read_text(encoding="utf-8") if tasks_path.exists() else ""
    debug_before = debug_path.read_text(encoding="utf-8") if debug_path.exists() else ""
    existing_tasks = _read_json(tasks_path, (list, dict), [])
    existing_debug = _read_json(debug_path, list, [])
    generated_tasks = generate_task_templates(configuration, sdk).as_json()
    generated_debug = generate_debug_configurations(configuration, sdk).as_json()
    tasks_after = _render(_tasks_document(existing_tasks, generated_tasks))
    debug_after = _render(_merge_labeled_entries(existing_debug, generated_debug))
    diff = _diff(tasks_path, tasks_before, tasks_after) + _diff(debug_path, debug_before, debug_after)
    changed = bool(diff)
    if changed and not dry_run:
        _atomic_write(tasks_path, tasks_after)
        _atomic_write(debug_path, debug_after)
    return SetupResult(tasks_path, debug_path, diff, changed, dry_run)
