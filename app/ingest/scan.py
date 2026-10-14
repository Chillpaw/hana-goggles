"""Folder scan: find view files under a root, derive package paths, parse each (never raises)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.ir.models import ParseResult
from app.parsers.dispatch import parse_file

VIEW_SUFFIXES = (".calculationview", ".hdbcalculationview")   # matched case-insensitively


@dataclass(frozen=True)
class ScannedView:
    path: Path              # absolute
    rel_path: str           # posix path relative to the scan root
    package_path: str | None  # parent dir relative to root, posix, None at root
    result: ParseResult


def find_view_files(root: Path) -> list[Path]:
    root = _check_root(root)
    found: list[tuple[str, Path]] = []
    # followlinks=False stops os.walk descending into symlinked directories (avoids loops);
    # pruning dirnames in place skips hidden directories such as .git.
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.lower().endswith(VIEW_SUFFIXES):
                path = Path(dirpath) / name
                found.append((path.relative_to(root).as_posix(), path))
    found.sort(key=lambda item: item[0])
    return [path for _, path in found]


def scan_folder(root: Path) -> list[ScannedView]:
    root = _check_root(root)
    scanned = []
    for path in find_view_files(root):
        rel = path.relative_to(root)
        package_path = rel.parent.as_posix() if rel.parent != Path(".") else None
        result = parse_file(path, package_path=package_path)
        scanned.append(ScannedView(path=path, rel_path=rel.as_posix(),
                                   package_path=package_path, result=result))
    return scanned


def _check_root(root: Path) -> Path:
    # A bad root is a usage error, not an input file, so it is allowed to raise.
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")
    return root
