"""Folder scan: which files count as views, their package paths, and ordering."""
import os
import shutil

import pytest
from conftest import FIXTURES

from app.ingest.scan import find_view_files, scan_folder
from app.ir.models import ParseStatus

PRODUCER = FIXTURES / "graphical" / "SOURCE_VIEW_01.calculationview"


def _put(root, rel, data=b"<x/>"):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _rels(root):
    return [p.relative_to(root).as_posix() for p in find_view_files(root)]


def test_finds_both_suffixes_and_upper_case(tmp_path):
    _put(tmp_path, "A.calculationview")
    _put(tmp_path, "B.hdbcalculationview")
    _put(tmp_path, "C.CALCULATIONVIEW")
    _put(tmp_path, "D.HdbCalculationView")
    assert _rels(tmp_path) == [
        "A.calculationview", "B.hdbcalculationview", "C.CALCULATIONVIEW", "D.HdbCalculationView",
    ]


def test_ignores_other_files(tmp_path):
    _put(tmp_path, "A.calculationview")
    _put(tmp_path, "notes.txt")
    _put(tmp_path, "A.calculationview.bak")
    _put(tmp_path, "calculationview")
    _put(tmp_path, "sub/README.md")
    assert _rels(tmp_path) == ["A.calculationview"]


def test_nested_package_path(tmp_path):
    shutil.copy(PRODUCER, tmp_path / "TOP.calculationview")
    _put(tmp_path, "a/b/SOURCE_VIEW_01.calculationview", PRODUCER.read_bytes())
    top, nested = scan_folder(tmp_path)

    assert top.rel_path == "TOP.calculationview"
    assert top.package_path is None
    assert top.result.view.package_path is None

    assert nested.rel_path == "a/b/SOURCE_VIEW_01.calculationview"
    assert nested.package_path == "a/b"
    assert nested.result.view.package_path == "a/b"
    assert nested.result.view.parse_status is ParseStatus.OK
    assert nested.path.is_absolute()
    assert nested.path == (tmp_path / "a" / "b" / "SOURCE_VIEW_01.calculationview").resolve()


def test_deterministic_order(tmp_path):
    for rel in ["z/A.calculationview", "B.calculationview", "a/c/C.calculationview",
                "a/B.calculationview", "A.calculationview"]:
        _put(tmp_path, rel)
    expected = ["A.calculationview", "B.calculationview", "a/B.calculationview",
                "a/c/C.calculationview", "z/A.calculationview"]
    assert _rels(tmp_path) == expected
    assert [s.rel_path for s in scan_folder(tmp_path)] == expected


def test_garbage_file_yields_failed_result(tmp_path):
    _put(tmp_path, "pkg/JUNK.calculationview", b"not xml at all")
    (scanned,) = scan_folder(tmp_path)
    assert scanned.result.view.parse_status is ParseStatus.FAILED
    assert [w.code for w in scanned.result.warnings] == ["XML_SYNTAX"]
    assert scanned.result.view.package_path == "pkg"


def test_hidden_dirs_skipped(tmp_path):
    _put(tmp_path, ".git/A.calculationview")
    _put(tmp_path, "pkg/.hidden/B.calculationview")
    _put(tmp_path, "pkg/C.calculationview")
    assert _rels(tmp_path) == ["pkg/C.calculationview"]


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="needs symlinks")
def test_symlinked_dirs_not_followed(tmp_path):
    _put(tmp_path, "pkg/A.calculationview")
    try:
        (tmp_path / "pkg" / "loop").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("cannot create symlinks here")
    assert _rels(tmp_path) == ["pkg/A.calculationview"]


def test_non_directory_root_raises(tmp_path):
    file_root = _put(tmp_path, "A.calculationview")
    with pytest.raises(NotADirectoryError):
        find_view_files(file_root)
    with pytest.raises(NotADirectoryError):
        scan_folder(tmp_path / "missing")
