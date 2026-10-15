"""Folder scan: find view files under a root, derive package paths, parse each (never raises).

Problems with the folder itself (unreadable directories, file names that are not valid
UTF-8) are never dropped silently: they are appended to the caller's `warnings` list.
"""
from __future__ import annotations

import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.ir.models import IRWarning, ParseResult, Severity
from app.parsers.dispatch import parse_file

VIEW_SUFFIXES = (".calculationview", ".hdbcalculationview")   # matched case-insensitively


@dataclass(frozen=True)
class ScannedView:
    path: Path              # absolute
    rel_path: str           # posix path relative to the scan root
    package_path: str | None  # parent dir relative to root, posix, None at root
    result: ParseResult


def find_view_files(root: Path, warnings: list[IRWarning] | None = None) -> list[Path]:
    return _walk(_check_root(root), warnings if warnings is not None else [])


def scan_folder(root: Path, warnings: list[IRWarning] | None = None) -> list[ScannedView]:
    root = _check_root(root)
    scanned = []
    for path in _walk(root, warnings if warnings is not None else []):
        rel = path.relative_to(root)
        package_path = rel.parent.as_posix() if rel.parent != Path(".") else None
        result = parse_file(path, package_path=package_path)
        scanned.append(ScannedView(path=path, rel_path=rel.as_posix(),
                                   package_path=package_path, result=result))
    return scanned


def _walk(root: Path, warnings: list[IRWarning]) -> list[Path]:
    """Recursive scan of an already-resolved root, sorted by rel posix path."""
    found: list[tuple[str, Path]] = []

    def on_error(exc: OSError) -> None:
        where = _rel_text(root, exc.filename)
        warnings.append(IRWarning(code="SCAN_DIR_UNREADABLE", severity=Severity.ERROR,
                                  message=f"cannot read folder {where}: {exc.strerror}"))

    # followlinks=False stops os.walk descending into symlinked directories (avoids loops);
    # pruning dirnames in place skips hidden directories such as .git, and Windows
    # junctions, which os.walk on Python 3.11 does not treat as links.
    for dirpath, dirnames, filenames in os.walk(root, onerror=on_error, followlinks=False):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and not _is_reparse_point(os.path.join(dirpath, d))]
        for name in filenames:
            # Hidden files include macOS resource forks such as ._X.calculationview.
            if name.startswith(".") or not name.lower().endswith(VIEW_SUFFIXES):
                continue
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if not _is_utf8(rel):
                # Undecodable bytes survive as surrogate escapes, which would break
                # later text storage (e.g. SQLite), so the file is skipped visibly.
                warnings.append(IRWarning(code="SCAN_BAD_FILENAME", severity=Severity.WARNING,
                                          message=f"skipped file with a non-UTF-8 name: "
                                                  f"{_escaped(rel)}"))
                continue
            found.append((rel, path))
    found.sort(key=lambda item: item[0])
    return [path for _, path in found]


# Reparse tags that make a directory point elsewhere (and so can loop). Other reparse
# points, such as OneDrive cloud placeholders, are ordinary folders and are walked.
# The stat module defines the tag constants on Windows only; the values are fixed by Windows.
IO_REPARSE_TAG_MOUNT_POINT = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)  # junction
IO_REPARSE_TAG_SYMLINK = getattr(stat, "IO_REPARSE_TAG_SYMLINK", 0xA000000C)
_LINK_TAGS = frozenset({IO_REPARSE_TAG_MOUNT_POINT, IO_REPARSE_TAG_SYMLINK})


def _is_reparse_point(path: str | os.PathLike[str],
                      lstat: Callable[[str | os.PathLike[str]], object] = os.lstat) -> bool:
    """True for a Windows directory junction or symlink (a link-type reparse point).
    Only Windows stat results carry st_file_attributes, so elsewhere this is always False.
    A reparse point without a readable tag counts as a link (the safe side: no loops)."""
    try:
        info = lstat(path)
    except OSError:
        return False
    if not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    tag = getattr(info, "st_reparse_tag", None)
    return tag is None or tag in _LINK_TAGS


def _check_root(root: Path) -> Path:
    # A bad root is a usage error, not an input file, so it is allowed to raise.
    root = Path(root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")
    return root


def _rel_text(root: Path, filename: str | os.PathLike[str] | None) -> str:
    if filename is None:
        return "."
    try:
        rel = Path(filename).relative_to(root).as_posix()
    except ValueError:
        rel = Path(filename).as_posix()
    return _escaped(rel)


def _is_utf8(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _escaped(text: str) -> str:
    return text.encode("utf-8", "backslashreplace").decode("utf-8")
