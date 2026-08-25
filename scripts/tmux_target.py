"""Non-mutating inspection for an explicit, user-owned tmux pane.

This module validates one configured ``TmuxTarget`` only.  It never discovers
sessions, windows, or panes and never starts, stops, selects, renames, attaches
to, or sends input to tmux resources.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Mapping, Sequence

from scripts.configuration import TmuxTarget
from scripts.diagnostics import Diagnostic, DiagnosticError, tmux_failure
from scripts.runtime import safe_environment

_IDENTITY_FORMAT = "#{session_name}\t#{window_name}\t#{pane_id}"


@dataclass(frozen=True)
class InspectedTmuxTarget:
    """The exact configured target after tmux has confirmed its identity."""

    session: str
    window: str
    pane: str
    command: tuple[str, ...]


def _configured_target(target: TmuxTarget) -> str:
    """Build the sole tmux target argument from all required configured fields."""
    return f"{target.session}:{target.window}.{target.pane}"


def _failure(
    target: TmuxTarget, message: str, *, stderr: str | None = None
) -> DiagnosticError:
    return DiagnosticError(tmux_failure(message, target=_configured_target(target), stderr=stderr))


def inspect_tmux_target(
    target: TmuxTarget | None,
    *,
    executable: str = "tmux",
    server_options: Sequence[str] = (),
    environment: Mapping[str, str] | None = None,
) -> InspectedTmuxTarget | None:
    """Confirm an explicit pane exists without mutating or discovering tmux state.

    ``None`` means the optional tmux bridge is disabled.  ``server_options`` is
    passed verbatim as separate argv entries before ``display-message``; callers
    may supply (``"-L"``, socket_name) to inspect an isolated test server.  No
    shell is used.  tmux's response must exactly match every configured identity
    component, preventing a global pane ID from silently retargeting a request.
    """
    if target is None:
        return None
    if not executable or executable.startswith("-"):
        raise _failure(target, "tmux executable is unavailable.")
    if any(not option or "\x00" in option for option in server_options):
        raise _failure(target, "tmux server options are invalid.")
    if shutil.which(executable, path=(environment or os.environ).get("PATH")) is None:
        raise _failure(target, "tmux executable is unavailable.")

    command = (
        executable,
        *server_options,
        "display-message",
        "-p",
        "-t",
        _configured_target(target),
        _IDENTITY_FORMAT,
    )
    try:
        completed = subprocess.run(
            command,
            check=False,
            shell=False,
            capture_output=True,
            text=True,
            env=safe_environment(environment),
        )
    except OSError as error:
        raise _failure(target, "tmux inspection could not start.", stderr=str(error)) from error

    if completed.returncode != 0:
        raise _failure(
            target,
            "Configured tmux session/window/pane does not exist or is inaccessible.",
            stderr=completed.stderr,
        )

    identity = completed.stdout.rstrip("\n").split("\t")
    if identity != [target.session, target.window, target.pane]:
        raise _failure(
            target,
            "Configured tmux target identity did not match the inspected pane.",
            stderr=completed.stderr,
        )
    return InspectedTmuxTarget(
        session=target.session,
        window=target.window,
        pane=target.pane,
        command=command,
    )
