from __future__ import annotations

import os
from typing import Mapping


_HOSTILE_SHELL_ENVIRONMENT = ("BASH_ENV", "CDPATH", "ENV")


def safe_environment(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    values = dict(os.environ if environment is None else environment)
    for name in _HOSTILE_SHELL_ENVIRONMENT:
        values.pop(name, None)
    return values
