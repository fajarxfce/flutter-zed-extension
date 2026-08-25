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


@dataclass(frozen=True)
class TaskTemplate:
    """One declarative Zed task with an executable and separate argv entries."""

    label: str
    intent: str
    command: Path
    args: tuple[str, ...]
    cwd: Path

    def as_json(self) -> dict[str, object]:
        """Return the stable Zed task object without shell interpolation."""
        return {
            "label": self.label,
            "command": str(self.command),
            "args": list(self.args),
            "cwd": str(self.cwd),
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


def _target_args(configuration: FlutterConfiguration) -> tuple[str, ...]:
    if configuration.target is None:
        return ()
    return ("--target", str(configuration.target))


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
    flutter = sdk.flutter.path.resolve()
    dart = sdk.dart.path.resolve()
    target = _target_args(configuration)
    flavor = _flavor_args(configuration)
    mode = _mode_args(configuration)
    user_args = configuration.args
    templates = (
        TaskTemplate("Flutter: Pub get", "Resolve pub dependencies", flutter, ("pub", "get"), root),
        TaskTemplate("Flutter: Analyze", "Analyze the project", flutter, ("analyze", *user_args), root),
        TaskTemplate(
            "Flutter: Format (check)",
            "Check Dart formatting without modifying files",
            dart,
            ("format", "--set-exit-if-changed", str(configuration.target or root)),
            root,
        ),
        TaskTemplate("Flutter: Test", "Run Flutter tests", flutter, ("test", *user_args), root),
        TaskTemplate(
            "Flutter: Build APK",
            "Build an Android APK",
            flutter,
            ("build", "apk", *target, *flavor, *mode, *user_args),
            root,
        ),
        TaskTemplate(
            "Flutter: Build web",
            "Build a web release",
            flutter,
            ("build", "web", *target, *mode, *user_args),
            root,
        ),
        TaskTemplate(
            "Flutter: Run",
            "Run the Flutter application",
            flutter,
            ("run", *target, *flavor, *mode, *_device_args(configuration), *user_args),
            root,
        ),
        TaskTemplate("Flutter: Devices", "List available Flutter devices", flutter, ("devices",), root),
        TaskTemplate("Flutter: Clean", "Remove Flutter build artifacts", flutter, ("clean",), root),
    )
    return TaskTemplates(templates)


def execute_task_template(
    task: TaskTemplate,
    *,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an already-generated template without a shell or output translation."""
    return subprocess.run(
        (str(task.command), *task.args),
        check=False,
        capture_output=True,
        cwd=task.cwd,
        env=safe_environment(environment),
        text=True,
    )
