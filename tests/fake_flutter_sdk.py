from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    configured_executable = os.environ.get("FAKE_SDK_EXECUTABLE")
    if configured_executable is None:
        executable, *arguments = sys.argv[1:]
    else:
        executable = configured_executable
        arguments = sys.argv[1:]
    log_path = Path(os.environ["FAKE_SDK_LOG"])
    invocation = {"arguments": arguments, "executable": executable}
    if os.environ.get("FAKE_SDK_LOG_CWD") == "1":
        invocation["cwd"] = str(Path.cwd())
    log_path.write_text(json.dumps(invocation, sort_keys=True) + "\n", encoding="utf-8")
    if os.environ.get("FAKE_SDK_DEVICE_AVAILABLE") == "0" and "run" in arguments:
        print("No devices found", file=sys.stderr)
        return 1
    if os.environ.get("FAKE_SDK_OUTCOME") == "failure":
        print(f"{executable}: configured failure", file=sys.stderr)
        return 1
    print(f"{executable}: {' '.join(arguments)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
