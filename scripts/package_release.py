#!/usr/bin/env python3
"""Create a deterministic source archive without development-only files."""

from __future__ import annotations

import argparse
import gzip
import os
import tarfile
from pathlib import Path

from release_check import EXCLUDED_PARTS, EXCLUDED_SUFFIXES, EVIDENCE_NAME_PATTERN, SECRET_NAME_PATTERN, validate_archive, validate_versions


def include(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    return path.suffix not in EXCLUDED_SUFFIXES and not EVIDENCE_NAME_PATTERN.fullmatch(path.name) and not SECRET_NAME_PATTERN.search(path.name)


def package(root: Path, output: Path) -> None:
    validate_versions(root)
    files = sorted(path for path in root.rglob("*") if path.is_file() and include(path, root))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
                for path in files:
                    info = archive.gettarinfo(str(path), arcname=path.relative_to(root).as_posix())
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    with path.open("rb") as source:
                        archive.addfile(info, source)
    os.utime(output, (0, 0))
    validate_archive(output)
    print(f"wrote deterministic package: {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("dist/flutter-zed-extension.tar.gz"))
    args = parser.parse_args()
    package(args.root.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
