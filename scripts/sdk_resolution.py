#!/usr/bin/env python3
"""Resolve Flutter and Dart SDK executables without a shell or PATH mutation.

Resolution is intentionally separate from project metadata detection. Callers pass
validated configuration and detected metadata; this module considers filesystem
paths and executes only a selected executable with an argv array for ``--version``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

from scripts.configuration import FlutterConfiguration
from scripts.diagnostics import Diagnostic, missing_sdk, process_failure
from scripts.project_detection import ProjectDetection
from scripts.runtime import safe_environment

SdkSource = Literal["fvm", "explicit", "path"]


@dataclass(frozen=True)
class ExecutableVersion:
    """A resolved executable and its captured version command output."""

    path: Path
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ResolvedSdk:
    """The selected Flutter SDK and the Dart executable it supplies."""

    source: SdkSource
    root: Path
    flutter: ExecutableVersion
    dart: ExecutableVersion


class SdkResolutionError(RuntimeError):
    """Raised when no usable Flutter/Dart SDK pair can be resolved."""

    def __init__(self, message: str, diagnostic: Diagnostic | None = None) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic


def _executable_name(name: str) -> str:
    return f"{name}.bat" if os.name == "nt" else name


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _probe(path: Path, environment: Mapping[str, str]) -> ExecutableVersion:
    command = (str(path), "--version")
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            env=safe_environment(environment),
            text=True,
        )
    except OSError as error:
        raise SdkResolutionError(f"SDK executable cannot run: {path}: {error.strerror or error}") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit status {result.returncode}"
        diagnostic = process_failure(
            command,
            exit_status=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            message="SDK executable version check failed.",
        )
        raise SdkResolutionError(f"SDK executable version check failed: {path}: {detail}", diagnostic)
    return ExecutableVersion(path=path.resolve(), stdout=result.stdout, stderr=result.stderr)


def _sdk_pair(root: Path, environment: Mapping[str, str]) -> tuple[ExecutableVersion, ExecutableVersion]:
    flutter = root / "bin" / _executable_name("flutter")
    dart = root / "bin" / _executable_name("dart")
    invalid = [str(path) for path in (flutter, dart) if not _is_executable(path)]
    if invalid:
        raise SdkResolutionError(f"SDK is missing executable or it is not executable: {', '.join(invalid)}")
    return _probe(flutter, environment), _probe(dart, environment)


def _path_sdk(environment: Mapping[str, str]) -> Path:
    path_value = environment.get("PATH", "")
    flutter = shutil.which(_executable_name("flutter"), path=path_value)
    dart = shutil.which(_executable_name("dart"), path=path_value)
    if not flutter or not dart:
        missing = ", ".join(name for name, value in (("flutter", flutter), ("dart", dart)) if not value)
        raise SdkResolutionError(
            f"SDK not found: {missing} missing from PATH. Install Flutter or configure an SDK directory."
        )
    flutter_path = Path(flutter).resolve()
    dart_path = Path(dart).resolve()
    if flutter_path.parent != dart_path.parent:
        raise SdkResolutionError(
            "SDK PATH fallback is inconsistent: flutter and dart must come from the same bin directory."
        )
    return flutter_path.parent.parent


def resolve_sdk(
    configuration: FlutterConfiguration,
    project: ProjectDetection,
    *,
    explicit_sdk: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> ResolvedSdk:
    """Resolve a usable SDK using FVM, explicit, then PATH precedence.

    A project-local ``.fvm/flutter_sdk`` wins only when ``sdk_mode`` is ``fvm``
    and its Flutter and Dart binaries are executable and pass ``--version``.
    ``explicit_sdk`` is a caller-supplied SDK root; it is not a configuration
    field. The final fallback requires matching ``flutter`` and ``dart`` entries
    in PATH. Failed candidates are recorded in the final actionable error.
    """

    if configuration.project_root != project.project_root:
        raise SdkResolutionError("SDK resolution requires matching configuration and project roots.")
    active_environment = dict(os.environ if environment is None else environment)
    candidates: list[tuple[SdkSource, Path]] = []
    if configuration.sdk_mode == "fvm":
        candidates.append(("fvm", project.project_root / ".fvm" / "flutter_sdk"))
    if explicit_sdk is not None:
        candidates.append(("explicit", explicit_sdk))
    failures: list[str] = []
    process_diagnostic: Diagnostic | None = None
    for source, root in candidates:
        try:
            flutter, dart = _sdk_pair(root, active_environment)
        except SdkResolutionError as error:
            failures.append(f"{source} ({root}): {error}")
            if error.diagnostic is not None and error.diagnostic.code == "process.failed":
                process_diagnostic = error.diagnostic
        else:
            return ResolvedSdk(source=source, root=root.resolve(), flutter=flutter, dart=dart)
    try:
        root = _path_sdk(active_environment)
        flutter, dart = _sdk_pair(root, active_environment)
    except SdkResolutionError as error:
        failures.append(f"PATH: {error}")
    else:
        return ResolvedSdk(source="path", root=root, flutter=flutter, dart=dart)
    message = "No usable Flutter SDK. " + " | ".join(failures)
    raise SdkResolutionError(message, process_diagnostic or missing_sdk(message))
