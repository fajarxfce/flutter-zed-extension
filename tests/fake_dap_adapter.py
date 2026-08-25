from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    configuration = json.loads(sys.stdin.read())
    Path(os.environ["FAKE_DAP_LOG"]).write_text(json.dumps(configuration, sort_keys=True) + "\n", encoding="utf-8")
    if os.environ.get("FAKE_DAP_OUTCOME") == "failure":
        print("fake adapter failure", file=sys.stderr)
        return 1
    print(f"{configuration['request']} accepted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
