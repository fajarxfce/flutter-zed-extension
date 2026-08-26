#!/usr/bin/env python3
"""Generate declarative Zed Flutter task templates and execute one argv-only task.

This module does not contribute a Zed extension task API.  It produces the JSON
that a future project-setup consumer may write to ``.zed/tasks.json``.  The
execution helper exists solely for deterministic local tests and preserves a
child process's exit code and captured output without a shell.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from scripts.configuration import FlutterConfiguration
from scripts.runtime import safe_environment
from scripts.sdk_resolution import ResolvedSdk

ZED_WORKTREE_ROOT = "$ZED_WORKTREE_ROOT"


def zed_cwd(configuration: FlutterConfiguration) -> str:
    relative_app = configuration.project_root.resolve().relative_to(configuration.worktree_root.resolve())
    return ZED_WORKTREE_ROOT if relative_app == Path(".") else f"{ZED_WORKTREE_ROOT}/{relative_app.as_posix()}"


@dataclass(frozen=True)
class TaskTemplate:
    label: str
    intent: str
    command: str
    args: tuple[str, ...]
    cwd: Path
    executable: Path
    zed_cwd: str = ZED_WORKTREE_ROOT

    def as_json(self) -> dict[str, object]:
        return {
            "label": self.label,
            "command": self.command,
            "args": list(self.args),
            "cwd": self.zed_cwd,
        }


@dataclass(frozen=True)
class TaskTemplates:
    """The generated content for a future project's ``.zed/tasks.json`` file."""

    tasks: tuple[TaskTemplate, ...]

    def as_json(self) -> list[dict[str, object]]:
        """Return the array-root document required by Zed's ``.zed/tasks.json``."""
        return [task.as_json() for task in self.tasks]

    def to_json(self) -> str:
        return json.dumps(self.as_json(), indent=2) + "\n"


def _mode_args(configuration: FlutterConfiguration) -> tuple[str, ...]:
    return (f"--{configuration.mode}",)


def _relative_to_project(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError(f"Target must be inside project root: {path}") from error


def _target_args(configuration: FlutterConfiguration, project_root: Path) -> tuple[str, ...]:
    if configuration.target is None:
        return ()
    return ("--target", _relative_to_project(configuration.target, project_root))


def _flavor_args(configuration: FlutterConfiguration) -> tuple[str, ...]:
    if configuration.flavor is None:
        return ()
    return ("--flavor", configuration.flavor)


def _device_args(configuration: FlutterConfiguration) -> tuple[str, ...]:
    if configuration.device is None:
        return ()
    return ("-d", configuration.device)


def generate_task_templates(configuration: FlutterConfiguration, sdk: ResolvedSdk) -> TaskTemplates:
    """Build stable Flutter task templates from validated configuration and SDK paths.

    ``args`` are copied as individual argv entries only to commands that accept
    arbitrary Flutter options.  Device selection is meaningful only for ``run``;
    flavors are emitted for APK builds and run; mode is emitted for builds and
    run.  The selected target is emitted where Flutter accepts ``--target``.
    """
    root = configuration.project_root.resolve()
    serialized_cwd = zed_cwd(configuration)
    flutter = sdk.flutter.path.resolve()
    target = _target_args(configuration, root)
    format_target = _relative_to_project(configuration.target, root) if configuration.target is not None else "."
    flavor = _flavor_args(configuration)
    mode = _mode_args(configuration)
    user_args = configuration.args
    command = "fvm" if configuration.sdk_mode == "fvm" else "flutter"
    flutter_prefix = ("flutter",) if configuration.sdk_mode == "fvm" else ()
    dart_command = "fvm" if configuration.sdk_mode == "fvm" else "dart"
    dart_prefix = ("dart",) if configuration.sdk_mode == "fvm" else ()
    templates = (
        TaskTemplate("Flutter: Pub get", "Resolve pub dependencies", command, (*flutter_prefix, "pub", "get"), root, flutter),
        TaskTemplate("Flutter: Analyze", "Analyze the project", command, (*flutter_prefix, "analyze", *user_args), root, flutter),
        TaskTemplate(
            "Flutter: Format (check)",
            "Check Dart formatting without modifying files",
            dart_command,
            (*dart_prefix, "format", "--set-exit-if-changed", format_target),
            root,
            sdk.dart.path.resolve(),
        ),
        TaskTemplate("Flutter: Test", "Run Flutter tests", command, (*flutter_prefix, "test", *user_args), root, flutter),
        TaskTemplate(
            "Flutter: Build APK",
            "Build an Android APK",
            command,
            (*flutter_prefix, "build", "apk", *target, *flavor, *mode, *user_args),
            root,
            flutter,
        ),
        TaskTemplate(
            "Flutter: Build web",
            "Build a web release",
            command,
            (*flutter_prefix, "build", "web", *target, *mode, *user_args),
            root,
            flutter,
        ),
        TaskTemplate(
            "Flutter: Run",
            "Run the Flutter application",
            command,
            (*flutter_prefix, "run", *target, *flavor, *mode, *_device_args(configuration), *user_args),
            root,
            flutter,
        ),
        TaskTemplate("Flutter: Devices", "List available Flutter devices", command, (*flutter_prefix, "devices"), root, flutter),
        TaskTemplate("Flutter: Clean", "Remove Flutter build artifacts", command, (*flutter_prefix, "clean"), root, flutter),
    )
    return TaskTemplates(tuple(
        TaskTemplate(task.label, task.intent, task.command, task.args, task.cwd, task.executable, serialized_cwd)
        for task in templates
    ))


def execute_task_template(
    task: TaskTemplate,
    *,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an already-generated template without a shell or output translation."""
    arguments = task.args[1:] if task.command == "fvm" else task.args
    return subprocess.run(
        (str(task.executable), *arguments),
        check=False,
        capture_output=True,
        cwd=task.cwd,
        env=safe_environment(environment),
        text=True,
    )
