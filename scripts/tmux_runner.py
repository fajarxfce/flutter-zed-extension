"""Owned Flutter-runner lifecycle for one explicitly configured tmux pane.

The runner is started only by a narrowly scoped ``tmux send-keys`` invocation:
tmux accepts the command line as pane input, so the command is constructed with
``shlex.join`` from caller-provided argv. All Python subprocess calls themselves
use argv arrays and ``shell=False``. The persisted state token is placed only in
the runner environment and verified through ``/proc`` before a signal is sent.
"""

from __future__ import annotations

import json
import os
import secrets
import shlex
import signal
import stat
import subprocess
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Literal, Mapping, Sequence

from scripts.configuration import TmuxTarget
from scripts.diagnostics import DiagnosticError, tmux_failure
from scripts.runtime import safe_environment
from scripts.tmux_target import InspectedTmuxTarget, inspect_tmux_target

RunnerState = Literal["running-owned", "stopped-owned", "stale-mismatched", "foreign-no-owned-runner"]


@dataclass(frozen=True)
class RunnerStatus:
    """The ownership decision plus stable runner identity and log location."""

    state: RunnerState
    target: str
    pid: int | None
    process_start_time: str | None
    log_path: Path | None
    command: tuple[str, ...] | None
    detail: str


class HotOperation(str, Enum):
    """The only terminal inputs permitted for an owned Flutter runner."""

    RELOAD = "reload"
    RESTART = "restart"


@dataclass(frozen=True)
class HotOperationResult:
    """A completed fixed hot operation without persisting runner secrets."""

    operation: HotOperation
    target: str
    sent_at: float
    timeout: float
    status: RunnerStatus


@dataclass(frozen=True)
class _OwnedRunner:
    token: str
    target: str
    pid: int
    process_start_time: str
    log_path: str
    command: tuple[str, ...]


def _target_text(target: TmuxTarget) -> str:
    return f"{target.session}:{target.window}.{target.pane}"


def _error(target: TmuxTarget, message: str, *, stderr: str | None = None) -> DiagnosticError:
    return DiagnosticError(tmux_failure(message, target=_target_text(target), stderr=stderr))


def _validate_path(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symbolic link")
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError(f"{label} parent must be an existing non-symlink directory")
    return path


def _validate_command(command: Sequence[str]) -> tuple[str, ...]:
    values = tuple(command)
    if not values or any(not value or "\x00" in value or "\n" in value or "\r" in value for value in values):
        raise ValueError("runner command must be non-empty argv entries without NUL or line breaks")
    return values


def _read_start_time(pid: int) -> str | None:
    try:
        # Field 22 is process start time. comm can contain spaces, so split after ') '.
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(") ", 1)[1].split()[19]
    except (FileNotFoundError, IndexError, PermissionError):
        return None


def _has_token(pid: int, token: str) -> bool:
    try:
        entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except (FileNotFoundError, PermissionError):
        return False
    return f"FLUTTER_ZED_RUNNER_TOKEN={token}".encode() in entries


def _write_state(path: Path, state: _OwnedRunner) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(asdict(state), handle, sort_keys=True)
            handle.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _load_state(path: Path) -> _OwnedRunner | None:
    if not path.exists():
        return None
    _validate_path(path, "state path")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        command = tuple(payload["command"])
        state = _OwnedRunner(
            token=payload["token"], target=payload["target"], pid=payload["pid"],
            process_start_time=payload["process_start_time"], log_path=payload["log_path"], command=command,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(state.pid, int) or not isinstance(state.token, str) or not state.token:
        return None
    return state


def _owned_status(target: TmuxTarget, state_path: Path) -> RunnerStatus:
    owned = _load_state(state_path)
    if owned is None:
        return RunnerStatus("foreign-no-owned-runner", _target_text(target), None, None, None, None, "No owned runner state exists.")
    if owned.target != _target_text(target):
        return RunnerStatus("stale-mismatched", _target_text(target), owned.pid, owned.process_start_time, Path(owned.log_path), owned.command, "Owned state targets a different pane.")
    current_start = _read_start_time(owned.pid)
    if current_start is None:
        return RunnerStatus("stopped-owned", owned.target, owned.pid, owned.process_start_time, Path(owned.log_path), owned.command, "Owned runner has stopped; its log is preserved.")
    if current_start != owned.process_start_time or not _has_token(owned.pid, owned.token):
        return RunnerStatus("stale-mismatched", owned.target, owned.pid, owned.process_start_time, Path(owned.log_path), owned.command, "PID identity or ownership token does not match state.")
    return RunnerStatus("running-owned", owned.target, owned.pid, owned.process_start_time, Path(owned.log_path), owned.command, "Owned runner is running.")


def _pane_command(inspected: InspectedTmuxTarget, *, executable: str, server_options: Sequence[str], environment: Mapping[str, str] | None) -> str | None:
    command = (executable, *server_options, "display-message", "-p", "-t", f"{inspected.session}:{inspected.window}.{inspected.pane}", "#{pane_current_command}")
    try:
        completed = subprocess.run(command, check=False, shell=False, capture_output=True, text=True, env=safe_environment(environment))
    except OSError as error:
        target = TmuxTarget(inspected.session, inspected.window, inspected.pane)
        raise _error(target, "Configured pane command could not be inspected.", stderr=str(error)) from error
    return completed.stdout.strip() if completed.returncode == 0 else None


def _is_idle_shell(command: str | None) -> bool:
    return command is not None and Path(command).name in {"ash", "bash", "dash", "fish", "ksh", "sh", "tmux", "zsh"}


def status_runner(target: TmuxTarget | None, state_path: Path, *, executable: str = "tmux", server_options: Sequence[str] = (), environment: Mapping[str, str] | None = None) -> RunnerStatus:
    """Validate the exact pane then report owned, stopped, stale, or foreign state."""
    if target is None:
        raise ValueError("an explicit tmux target is required")
    inspect_tmux_target(target, executable=executable, server_options=server_options, environment=environment)
    return _owned_status(target, _validate_path(state_path, "state path"))


def start_runner(target: TmuxTarget | None, command: Sequence[str], state_path: Path, log_path: Path, *, executable: str = "tmux", server_options: Sequence[str] = (), environment: Mapping[str, str] | None = None, timeout: float = 3.0) -> RunnerStatus:
    """Start an owned command only in an already-existing idle shell pane."""
    if target is None:
        raise ValueError("an explicit tmux target is required")
    inspected = inspect_tmux_target(target, executable=executable, server_options=server_options, environment=environment)
    assert inspected is not None
    if not _is_idle_shell(_pane_command(inspected, executable=executable, server_options=server_options, environment=environment)):
        raise _error(target, "Refusing runner start: configured pane is not an idle shell.")
    state_path, log_path = _validate_path(state_path, "state path"), _validate_path(log_path, "log path")
    if state_path.exists():
        raise _error(target, "Runner state already exists; inspect status before starting another runner.")
    if log_path.exists():
        raise ValueError("log path already exists; logs are never overwritten")
    runner_command = _validate_command(command)
    token = secrets.token_urlsafe(32)
    pid_path = state_path.with_name(f".{state_path.name}.pid")
    _validate_path(pid_path, "PID marker path")
    if pid_path.exists():
        raise ValueError("PID marker path already exists")
    pane_command = (
        f"env FLUTTER_ZED_RUNNER_TOKEN={shlex.quote(token)} {shlex.join(runner_command)} "
        f"> {shlex.quote(str(log_path))} 2>&1 & runner_pid=$!; "
        f"printf '%s\\n' \"$runner_pid\" > {shlex.quote(str(pid_path))}; wait \"$runner_pid\""
    )
    tmux_command = (executable, *server_options, "send-keys", "-t", _target_text(target), "--", pane_command, "Enter")
    completed = subprocess.run(tmux_command, check=False, shell=False, capture_output=True, text=True, env=safe_environment(environment))
    if completed.returncode != 0:
        raise _error(target, "Runner start could not send the controlled command to the configured pane.", stderr=completed.stderr)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, ValueError):
            time.sleep(0.02)
            continue
        start_time = _read_start_time(pid)
        if pid > 0 and start_time is not None and _has_token(pid, token):
            _write_state(state_path, _OwnedRunner(token, _target_text(target), pid, start_time, str(log_path), runner_command))
            pid_path.unlink(missing_ok=True)
            return _owned_status(target, state_path)
        time.sleep(0.02)
    pid_path.unlink(missing_ok=True)
    raise _error(target, "Runner did not establish a verifiable owned process identity.")


def perform_hot_operation(target: TmuxTarget | None, operation: HotOperation, state_path: Path, *, executable: str = "tmux", server_options: Sequence[str] = (), environment: Mapping[str, str] | None = None, timeout: float = 3.0) -> HotOperationResult:
    """Send only fixed Flutter hot-reload or hot-restart input to a verified runner."""
    if target is None:
        raise ValueError("an explicit tmux target is required")
    if not isinstance(operation, HotOperation):
        raise ValueError("hot operation must be a fixed HotOperation value")
    if timeout <= 0:
        raise ValueError("hot operation timeout must be positive")
    status = status_runner(target, state_path, executable=executable, server_options=server_options, environment=environment)
    if status.state != "running-owned":
        raise _error(target, f"Refusing {operation.value}: runner is {status.state}.")
    inspected = inspect_tmux_target(target, executable=executable, server_options=server_options, environment=environment)
    assert inspected is not None
    key = "r" if operation is HotOperation.RELOAD else "R"
    command = (executable, *server_options, "send-keys", "-t", f"{inspected.session}:{inspected.window}.{inspected.pane}", "--", key)
    try:
        completed = subprocess.run(command, check=False, shell=False, capture_output=True, text=True, env=safe_environment(environment), timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise _error(target, f"{operation.value.capitalize()} could not send fixed input to the configured pane.", stderr=str(error)) from error
    if completed.returncode != 0:
        raise _error(target, f"{operation.value.capitalize()} could not send fixed input to the configured pane.", stderr=completed.stderr)
    return HotOperationResult(operation, _target_text(target), time.time(), timeout, status)


def interrupt_runner(target: TmuxTarget | None, state_path: Path, *, executable: str = "tmux", server_options: Sequence[str] = (), environment: Mapping[str, str] | None = None) -> RunnerStatus:
    """Deliver SIGINT only after the same ownership verification as stop_runner."""
    if target is None:
        raise ValueError("an explicit tmux target is required")
    inspect_tmux_target(target, executable=executable, server_options=server_options, environment=environment)
    status = _owned_status(target, _validate_path(state_path, "state path"))
    if status.state != "running-owned":
        raise _error(target, f"Refusing interrupt: runner is {status.state}.")
    assert status.pid is not None
    os.kill(status.pid, signal.SIGINT)
    return RunnerStatus(
        "stopped-owned", status.target, status.pid, status.process_start_time,
        status.log_path, status.command, "Owned runner received SIGINT; its log is preserved.",
    )


def stop_runner(target: TmuxTarget | None, state_path: Path, *, executable: str = "tmux", server_options: Sequence[str] = (), environment: Mapping[str, str] | None = None) -> RunnerStatus:
    """Gracefully terminate only a verified owned runner with SIGTERM; preserve its state and log."""
    if target is None:
        raise ValueError("an explicit tmux target is required")
    inspect_tmux_target(target, executable=executable, server_options=server_options, environment=environment)
    status = _owned_status(target, _validate_path(state_path, "state path"))
    if status.state != "running-owned":
        raise _error(target, f"Refusing stop: runner is {status.state}.")
    assert status.pid is not None
    os.kill(status.pid, signal.SIGTERM)
    return RunnerStatus(
        "stopped-owned", status.target, status.pid, status.process_start_time,
        status.log_path, status.command, "Owned runner received SIGTERM; its log is preserved.",
    )
