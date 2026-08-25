#!/usr/bin/env python3
"""Validated Flutter workflow configuration contract.

This module parses repository-owned JSON configuration only. It never invokes
Flutter, FVM, tmux, Zed, or a shell. Downstream project detection, SDK, DAP,
task, and tmux modules consume the typed model after validation succeeds.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypeAlias, cast

FlutterMode: TypeAlias = Literal["debug", "profile", "release"]
SdkMode: TypeAlias = Literal["flutter", "fvm"]
SUPPORTED_FLUTTER_MODES = frozenset({"debug", "profile", "release"})
SUPPORTED_SDK_MODES = frozenset({"flutter", "fvm"})


@dataclass(frozen=True)
class TmuxTarget:
    """An explicit, user-owned tmux pane. No target component is inferred."""

    session: str
    window: str
    pane: str


@dataclass(frozen=True)
class DapSettings:
    """Adapter-specific DAP settings retained without executing a DAP request."""

    adapter: str
    request: Literal["launch", "attach"]
    extra: dict[str, str | int | bool | list[str]]


@dataclass(frozen=True)
class FlutterConfiguration:
    """The stable contract for Flutter project, SDK, task, DAP, and tmux consumers."""

    project_root: Path
    sdk_mode: SdkMode
    target: Path | None
    device: str | None
    flavor: str | None
    mode: FlutterMode
    args: tuple[str, ...]
    dap: DapSettings | None
    tmux: TmuxTarget | None


class ConfigurationError(ValueError):
    """Raised when a configuration field is missing, ambiguous, or unsafe."""


def fail(field: str, message: str) -> None:
    raise ConfigurationError(f"{field}: {message}")


def require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(field, "must be an object")
    return value


def require_non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(field, "must be a non-empty string")
    if "\x00" in value or "\n" in value or "\r" in value:
        fail(field, "must not contain NUL or line breaks")
    return value


def require_safe_argument(value: Any, field: str) -> str:
    return require_non_empty_string(value, field)


def require_selector(value: Any, field: str) -> str:
    selector = require_safe_argument(value, field)
    if selector.startswith("-"):
        fail(field, "must not start with '-'")
    return selector


def require_path(value: Any, field: str, project_root: Path | None = None) -> Path:
    path_string = require_non_empty_string(value, field)
    path = Path(path_string)
    if path.is_absolute():
        fail(field, "must be relative to project_root")
    if any(part == ".." for part in path.parts):
        fail(field, "must not escape project_root")
    normalized = path.resolve() if project_root is None else (project_root / path).resolve()
    return normalized


def parse_args(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        fail("args", "must be a list of non-empty strings")
    return tuple(require_safe_argument(item, f"args[{index}]") for index, item in enumerate(value))


def parse_dap(value: Any) -> DapSettings | None:
    if value is None:
        return None
    dap = require_object(value, "dap")
    adapter = require_non_empty_string(dap.get("adapter"), "dap.adapter")
    request = require_non_empty_string(dap.get("request"), "dap.request")
    if request not in {"launch", "attach"}:
        fail("dap.request", "must be 'launch' or 'attach'")
    extra: dict[str, str | int | bool | list[str]] = {}
    for key, item in dap.items():
        if key in {"adapter", "request"}:
            continue
        if not isinstance(key, str) or not key:
            fail("dap", "keys must be non-empty strings")
        if isinstance(item, str):
            extra[key] = require_non_empty_string(item, f"dap.{key}")
        elif isinstance(item, bool | int):
            extra[key] = item
        elif isinstance(item, list) and all(isinstance(argument, str) for argument in item):
            extra[key] = [require_safe_argument(argument, f"dap.{key}[{index}]") for index, argument in enumerate(item)]
        else:
            fail(f"dap.{key}", "must be a string, integer, boolean, or string list")
    return DapSettings(adapter=adapter, request=cast(Literal["launch", "attach"], request), extra=extra)


def parse_tmux(value: Any) -> TmuxTarget | None:
    if value is None:
        return None
    tmux = require_object(value, "tmux")
    required = {"session", "window", "pane"}
    present = required.intersection(tmux)
    if present != required:
        fail("tmux", "requires explicit session, window, and pane")
    unexpected = set(tmux).difference(required)
    if unexpected:
        fail("tmux", f"unsupported fields: {', '.join(sorted(unexpected))}")
    return TmuxTarget(
        session=require_non_empty_string(tmux["session"], "tmux.session"),
        window=require_non_empty_string(tmux["window"], "tmux.window"),
        pane=require_non_empty_string(tmux["pane"], "tmux.pane"),
    )


def parse_configuration(configuration: dict[str, Any], base_directory: Path) -> FlutterConfiguration:
    """Parse one configuration object without probing external dependencies."""
    allowed = {"project_root", "sdk_mode", "target", "device", "flavor", "mode", "args", "dap", "tmux"}
    unexpected = set(configuration).difference(allowed)
    if unexpected:
        fail("configuration", f"unsupported fields: {', '.join(sorted(unexpected))}")

    project_root = require_path(configuration.get("project_root"), "project_root", base_directory)
    if not project_root.is_dir():
        fail("project_root", f"must name an existing directory: {project_root}")
    sdk_mode = require_non_empty_string(configuration.get("sdk_mode", "flutter"), "sdk_mode")
    if sdk_mode not in SUPPORTED_SDK_MODES:
        fail("sdk_mode", "must be 'flutter' or 'fvm'")
    target_value = configuration.get("target")
    target = None if target_value is None else require_path(target_value, "target", project_root)
    device_value = configuration.get("device")
    device = None if device_value is None else require_selector(device_value, "device")
    flavor_value = configuration.get("flavor")
    flavor = None if flavor_value is None else require_selector(flavor_value, "flavor")
    mode = require_non_empty_string(configuration.get("mode", "debug"), "mode")
    if mode not in SUPPORTED_FLUTTER_MODES:
        fail("mode", "must be one of: debug, profile, release")

    return FlutterConfiguration(
        project_root=project_root,
        sdk_mode=cast(SdkMode, sdk_mode),
        target=target,
        device=device,
        flavor=flavor,
        mode=cast(FlutterMode, mode),
        args=parse_args(configuration.get("args")),
        dap=parse_dap(configuration.get("dap")),
        tmux=parse_tmux(configuration.get("tmux")),
    )


def load_configuration(configuration_path: Path) -> FlutterConfiguration:
    try:
        contents = configuration_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        fail("configuration", f"file not found: {configuration_path}")
    try:
        configuration = json.loads(contents)
    except json.JSONDecodeError as error:
        fail("configuration", f"invalid JSON: {error.msg}")
    return parse_configuration(require_object(configuration, "configuration"), configuration_path.parent)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Flutter workflow configuration JSON")
    parser.add_argument("configuration", type=Path)
    arguments = parser.parse_args()
    try:
        configuration = load_configuration(arguments.configuration)
    except ConfigurationError as error:
        print(f"configuration validation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(f"configuration valid: {arguments.configuration}")
    print(f"project root: {configuration.project_root}")
    print(f"sdk mode: {configuration.sdk_mode}; Flutter mode: {configuration.mode}")
    print("tmux target: disabled" if configuration.tmux is None else "tmux target: explicit")


if __name__ == "__main__":
    main()
