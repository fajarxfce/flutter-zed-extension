#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


version = os.environ.get("FAKE_SDK_VERSION", "0.0.0")
name = Path(sys.argv[0]).name
if "--version" not in sys.argv[1:]:
    print(f"unexpected arguments: {sys.argv[1:]}", file=sys.stderr)
    raise SystemExit(2)
if os.environ.get("FAKE_SDK_FAIL") == name:
    print(f"{name}: configured version failure", file=sys.stderr)
    raise SystemExit(1)
print(f"{name} {version}")
