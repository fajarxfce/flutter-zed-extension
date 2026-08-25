from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FAKE_EXECUTABLE = Path(__file__).resolve().parent / "fake_flutter_sdk.py"


@dataclass(frozen=True)
class FixtureProject:
    name: str
    path: Path
    classification: Literal["flutter_app", "invalid"]


def fixture_project(name: str) -> FixtureProject:
    path = FIXTURES / name
    classifications: dict[str, Literal["flutter_app", "invalid"]] = {
        "valid_app": "flutter_app",
        "fvm_app": "flutter_app",
        "target_flavor_app": "flutter_app",
        "malformed_pubspec": "invalid",
        "invalid_project": "invalid",
    }
    try:
        classification = classifications[name]
    except KeyError as error:
        raise ValueError(f"unknown fixture: {name}") from error
    return FixtureProject(name=name, path=path, classification=classification)


def classify_fixture_project(project: Path) -> Literal["flutter_app", "invalid"]:
    """Classify fixture metadata only; this is not production project detection."""
    pubspec = project / "pubspec.yaml"
    if not pubspec.is_file():
        return "invalid"
    contents = pubspec.read_text(encoding="utf-8")
    required_lines = ("name:", "environment:", "flutter:")
    if any(not any(line.startswith(required) for line in contents.splitlines()) for required in required_lines):
        return "invalid"
    if 'sdk: ">=3.0.0 <4.0.0"' not in contents:
        return "invalid"
    return "flutter_app"


def run_fake_sdk(
    executable: Literal["flutter", "dart"],
    arguments: list[str],
    *,
    outcome: Literal["success", "failure"] = "success",
    device_available: bool = True,
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as temporary_directory:
        directory = Path(temporary_directory)
        log_path = directory / "invocations.jsonl"
        environment = os.environ | {
            "FAKE_SDK_LOG": str(log_path),
            "FAKE_SDK_OUTCOME": outcome,
            "FAKE_SDK_DEVICE_AVAILABLE": "1" if device_available else "0",
        }
        result = subprocess.run(
            [sys.executable, str(FAKE_EXECUTABLE), executable, *arguments],
            check=False,
            capture_output=True,
            cwd=directory,
            env=environment,
            text=True,
        )
        invocation = json.loads(log_path.read_text(encoding="utf-8").strip())
    result.invocation = invocation  # type: ignore[attr-defined]
    return result
