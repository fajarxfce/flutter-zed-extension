#!/usr/bin/env python3
"""Generate consumer-owned Zed Dart/Flutter debug configurations.

The generator models `.zed/debug.json` entries for the Dart extension's existing
``Dart`` adapter. It neither declares an extension debug adapter nor starts a
real Flutter/DAP process. The argv-only validation helper exists exclusively for
deterministic fake-adapter tests and retains child output and exit status.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from scripts.configuration import FlutterConfiguration
from scripts.diagnostics import Diagnostic, dap_failure
from scripts.runtime import safe_environment
from scripts.sdk_resolution import ResolvedSdk
from scripts.task_templates import ZED_WORKTREE_ROOT

DART_ADAPTER = "Dart"
FLUTTER_TYPE = "flutter"


@dataclass(frozen=True)
class DebugConfiguration:
    """One declarative `.zed/debug.json` entry for the installed Dart adapter."""

    label: str
    adapter: str
    request: str
    type: str
    program: str
    cwd: str
    flutter_mode: str | None = None
    device_id: str | None = None
    tool_args: tuple[str, ...] = ()
    use_fvm: bool = False
    vm_service_uri: str | None = None

    def as_json(self) -> dict[str, object]:
        """Return adapter-schema fields only, retaining the configured argv order."""
        document: dict[str, object] = {
            "label": self.label,
            "adapter": self.adapter,
            "request": self.request,
            "type": self.type,
            "program": self.program,
            "cwd": self.cwd,
        }
        if self.flutter_mode is not None:
            document["flutterMode"] = self.flutter_mode
        if self.device_id is not None:
            document["deviceId"] = self.device_id
        if self.tool_args:
            document["toolArgs"] = list(self.tool_args)
        if self.use_fvm:
            document["useFvm"] = True
        if self.vm_service_uri is not None:
            document["vmServiceUri"] = self.vm_service_uri
        return document


@dataclass(frozen=True)
class DebugConfigurations:
    """The generated contents of a consumer project's `.zed/debug.json`."""

    configurations: tuple[DebugConfiguration, ...]

    def as_json(self) -> list[dict[str, object]]:
        return [configuration.as_json() for configuration in self.configurations]

    def to_json(self) -> str:
        return json.dumps(self.as_json(), indent=2) + "\n"


class DapAdapterError(RuntimeError):
    """Raised when deterministic adapter validation cannot start or fails."""

    def __init__(self, message: str, diagnostic: Diagnostic) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic


def _program(configuration: FlutterConfiguration) -> str:
    root = configuration.project_root.resolve()
    target = (configuration.target or root / "lib" / "main.dart").resolve()
    try:
        return target.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError(f"Target must be inside project root: {target}") from error


def _launch_tool_args(configuration: FlutterConfiguration) -> tuple[str, ...]:
    flavor = ("--flavor", configuration.flavor) if configuration.flavor is not None else ()
    adapter_args: tuple[str, ...] = ()
    if configuration.dap is not None:
        configured = configuration.dap.extra.get("toolArgs")
        if isinstance(configured, list):
            adapter_args = tuple(configured)
    return (*flavor, *configuration.args, *adapter_args)


def _attach_uri(configuration: FlutterConfiguration) -> str | None:
    if configuration.dap is None:
        return None
    value = configuration.dap.extra.get("vmServiceUri")
    return value if isinstance(value, str) else None


def _adapter(configuration: FlutterConfiguration) -> str:
    return configuration.dap.adapter if configuration.dap is not None else DART_ADAPTER


def generate_debug_configurations(configuration: FlutterConfiguration, sdk: ResolvedSdk) -> DebugConfigurations:
    """Build the requested documented Flutter launch or attach entry.

    SDK resolution establishes that FVM selection has already been performed. The
    resulting path is intentionally not serialized: the Dart adapter's documented
    schema selects its toolchain through `useFvm`, while its `toolArgs` stays an
    ordered array and never becomes a shell command.
    """
    del sdk
    program = _program(configuration)
    adapter = _adapter(configuration)
    if adapter != DART_ADAPTER:
        raise ValueError(f"DAP adapter must be {DART_ADAPTER!r}, got {adapter!r}")
    request = configuration.dap.request if configuration.dap is not None else "launch"
    if request == "launch":
        launch = DebugConfiguration(
            label="Flutter: Launch",
            adapter=adapter,
            request="launch",
            type=FLUTTER_TYPE,
            program=program,
            cwd=ZED_WORKTREE_ROOT,
            flutter_mode=configuration.mode,
            device_id=configuration.device,
            tool_args=_launch_tool_args(configuration),
            use_fvm=configuration.sdk_mode == "fvm",
        )
        return DebugConfigurations((launch,))
    attach_uri = _attach_uri(configuration)
    if attach_uri is None:
        raise ValueError("dap.vmServiceUri is required to generate a Flutter attach configuration")
    attach = DebugConfiguration(
        label="Flutter: Attach",
        adapter=adapter,
        request="attach",
        type=FLUTTER_TYPE,
        program=program,
        cwd=ZED_WORKTREE_ROOT,
        vm_service_uri=attach_uri,
    )
    return DebugConfigurations((attach,))


def execute_adapter_validation(
    adapter: Path,
    configuration: DebugConfiguration,
    *,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a fake adapter against JSON stdin using only an argv array.

    This helper is test-only. It has no tmux branch or fallback, and callers must
    never use it to launch Flutter's real `debug_adapter` command.
    """
    command = (str(adapter),)
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            input=json.dumps(configuration.as_json()) + "\n",
            text=True,
            env=safe_environment(environment),
        )
    except OSError as error:
        diagnostic = dap_failure(
            f"Dart debug adapter is unavailable at {adapter}. Install or enable the Dart Zed extension.",
            adapter=configuration.adapter,
            stderr=error.strerror or str(error),
        )
        raise DapAdapterError(diagnostic.message, diagnostic) from error
    if result.returncode != 0:
        diagnostic = dap_failure(
            "Dart debug adapter validation failed.",
            adapter=configuration.adapter,
            stderr=result.stderr,
        )
        raise DapAdapterError(diagnostic.message, diagnostic)
    return result
