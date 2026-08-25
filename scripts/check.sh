#!/usr/bin/env sh
set -eu
python3 scripts/validate_manifest.py extension.toml
python3 -m unittest discover -s tests -v
