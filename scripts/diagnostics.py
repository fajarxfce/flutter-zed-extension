"""Stable diagnostics for Flutter workflow boundaries.

This module models failures only. It neither starts processes nor invokes Flutter,
DAP, tmux, or a shell. Consumers can attach its typed diagnostic to their existing
exception types without changing their public exception messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, TypeAlias

DiagnosticCode: TypeAlias = Literal[
    "sdk.missing",
    "project.invalid",
    "configuration.invalid",
    "process.failed",
    "process.unexpected_failure",
    "device.unavailable",
    "dap.failed",
    "tmux.failed",
]


@dataclass(frozen=True)
class Diagnostic:
    """A stable, actionable failure record with faithful external process output."""

    code: DiagnosticCode
    message: str
    context: Mapping[str, str]
    command: tuple[str, ...] | None = None
    stdout: str | None = None
    stderr: str | None = None
    exit_status: int | None = None


class DiagnosticError(RuntimeError):
    """An exception adapter that retains a typed diagnostic for downstream users."""

    def __init__(self, diagnostic: Diagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


def _context(**values: str | int | bool | None) -> dict[str, str]:
    return {key: str(value) for key, value in values.items() if value is not None}


def missing_sdk(message: str, *, source: str | None = None) -> Diagnostic:
    return Diagnostic("sdk.missing", message, _context(source=source))


def invalid_project(message: str, *, project_root: str) -> Diagnostic:
    return Diagnostic("project.invalid", message, _context(project_root=project_root))


def invalid_configuration(message: str, *, configuration_path: str | None = None) -> Diagnostic:
    return Diagnostic("configuration.invalid", message, _context(configuration_path=configuration_path))


def process_failure(
    command: tuple[str, ...],
    *,
    exit_status: int,
    stdout: str,
    stderr: str,
    message: str = "External process failed.",
) -> Diagnostic:
    return Diagnostic(
        "process.failed",
        message,
        _context(executable=command[0] if command else None),
        command=command,
        stdout=stdout,
        stderr=stderr,
        exit_status=exit_status,
    )


def unexpected_process_failure(
    command: tuple[str, ...],
    error: BaseException,
    *,
    cleanup_completed: bool,
) -> Diagnostic:
    return Diagnostic(
        "process.unexpected_failure",
        "External process ended unexpectedly.",
        _context(
            executable=command[0] if command else None,
            error_type=type(error).__name__,
            cleanup_completed=cleanup_completed,
        ),
        command=command,
    )


def unavailable_device(
    command: tuple[str, ...], *, exit_status: int, stdout: str, stderr: str
) -> Diagnostic:
    return Diagnostic(
        "device.unavailable",
        "No requested Flutter device is available.",
        _context(executable=command[0] if command else None),
        command=command,
        stdout=stdout,
        stderr=stderr,
        exit_status=exit_status,
    )


def dap_failure(message: str, *, adapter: str, stderr: str | None = None) -> Diagnostic:
    return Diagnostic("dap.failed", message, _context(adapter=adapter), stderr=stderr)


def tmux_failure(message: str, *, target: str, stderr: str | None = None) -> Diagnostic:
    return Diagnostic("tmux.failed", message, _context(target=target), stderr=stderr)
