"""Import and re-import into the store, with stale annotations. Tests edit copies only."""
import shutil

import pytest
from conftest import FIXTURES
from helpers import node

from app.ingest.importer import import_folder
from app.ir.models import Annotation, ParseStatus, Severity, TargetKind
from app.ir.store import Store

VIEW = "GENERIC_TAX_REPORTING_CUBE"
PRODUCER = "SOURCE_VIEW_01"
MAIN_FILE = f"{VIEW}.calculationview"
FILTER = "<filter>(&quot;COL_3&quot; = '$$IP_FISCAL_YEAR$$')</filter>"


@pytest.fixture
def folder(tmp_path):
    dest = tmp_path / "views"
    shutil.copytree(FIXTURES / "graphical", dest,
                    ignore=shutil.ignore_patterns("*.ir.json"))
    return dest


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "p.db") as s:
        yield s


def _edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def _filter_text(store, node_name):
    return node(store.load_result(VIEW), node_name).filters[0].expression.text


def _annotate(store, target_id, kind):
    store.save_annotation(Annotation(target_id=target_id, target_kind=kind, purpose_text="p"))


def test_first_import(store, folder):
    report = import_folder(store, folder)
    assert (report.added, report.changed, report.unchanged, report.removed) == (2, 0, 0, 0)
    assert report.failed == 0 and report.stale_annotations == 0 and report.warnings == []
    assert [v.id for v in store.list_views()] == [VIEW, PRODUCER]
    project = store.get_project()
    assert project.name == "views"
    assert project.source_folder == str(folder.resolve())
    # dependencies come back resolved but are not written back to the store
    assert report.estate.deploy_order == [PRODUCER, VIEW]
    assert any(d.internal for d in report.estate.dependencies)
    stored = store.load_result(VIEW)
    assert all(ds.resolved_view_id is None for ds in stored.data_sources)


def test_name_kept_and_overridable(store, folder):
    import_folder(store, folder, name="Estate 1")
    import_folder(store, folder)
    assert store.get_project().name == "Estate 1"
    import_folder(store, folder, name="Estate 2")
    assert store.get_project().name == "Estate 2"


def test_second_import_all_unchanged(store, folder):
    import_folder(store, folder)
    report = import_folder(store, folder)
    assert (report.added, report.changed, report.unchanged, report.removed) == (0, 0, 2, 0)


def test_changed_filter_marks_annotations_stale(store, folder):
    import_folder(store, folder)
    _annotate(store, VIEW, TargetKind.VIEW)
    _annotate(store, f"{VIEW}/Projection_1", TargetKind.NODE)
    _annotate(store, f"{VIEW}/Join_1", TargetKind.NODE)
    _annotate(store, PRODUCER, TargetKind.VIEW)

    _edit(folder / MAIN_FILE, FILTER, "<filter>(&quot;COL_3&quot; = '2024')</filter>")
    report = import_folder(store, folder)

    assert (report.added, report.changed, report.unchanged, report.removed) == (0, 1, 1, 0)
    assert report.stale_annotations == 2
    view_ann = store.get_annotation(VIEW, TargetKind.VIEW)
    assert view_ann.stale and view_ann.stale_reason == "view file changed"
    proj = store.get_annotation(f"{VIEW}/Projection_1", TargetKind.NODE)
    assert proj.stale and proj.stale_reason == "node changed"
    assert not store.get_annotation(f"{VIEW}/Join_1", TargetKind.NODE).stale
    assert not store.get_annotation(PRODUCER, TargetKind.VIEW).stale
    assert "2024" in _filter_text(store, "Projection_1")


def test_removed_node(store, folder):
    import_folder(store, folder)
    _annotate(store, f"{VIEW}/Projection_1", TargetKind.NODE)
    # rename the node and its one reference: Projection_1 no longer exists
    _edit(folder / MAIN_FILE, 'id="Projection_1"', 'id="Projection_9"')
    _edit(folder / MAIN_FILE, 'node="#Projection_1"', 'node="#Projection_9"')
    import_folder(store, folder)
    ann = store.get_annotation(f"{VIEW}/Projection_1", TargetKind.NODE)
    assert ann.stale and ann.stale_reason == "node removed"


def test_deleted_file(store, folder):
    import_folder(store, folder)
    _annotate(store, VIEW, TargetKind.VIEW)
    _annotate(store, f"{VIEW}/Join_1", TargetKind.NODE)
    (folder / MAIN_FILE).unlink()
    report = import_folder(store, folder)
    assert (report.added, report.changed, report.unchanged, report.removed) == (0, 0, 1, 1)
    assert report.stale_annotations == 2
    assert [v.id for v in store.list_views()] == [PRODUCER]
    assert store.node_hashes(VIEW) == {}
    for target, kind in ((VIEW, TargetKind.VIEW), (f"{VIEW}/Join_1", TargetKind.NODE)):
        ann = store.get_annotation(target, kind)
        assert ann.stale and ann.stale_reason == "view removed"
    assert report.estate.views == [PRODUCER]


def test_garbage_file_is_a_failed_view(store, folder):
    (folder / "BROKEN_1.calculationview").write_bytes(b"\x00 not xml <<<")
    report = import_folder(store, folder)
    assert report.added == 3 and report.failed == 1
    summary = {v.id: v for v in store.list_views()}["BROKEN_1"]
    assert summary.parse_status is ParseStatus.FAILED
    assert summary.node_count == 0
    assert "BROKEN_1" in report.estate.views


def test_duplicate_view_id_first_by_rel_path(store, folder):
    (folder / "b").mkdir()
    (folder / "a").mkdir()
    shutil.copy(folder / f"{PRODUCER}.calculationview", folder / "b")
    shutil.copy(folder / f"{PRODUCER}.calculationview", folder / "a")
    (folder / f"{PRODUCER}.calculationview").unlink()
    report = import_folder(store, folder)
    assert report.added == 2
    dupes = [w for w in report.warnings if w.code == "DUPLICATE_VIEW_ID"]
    assert len(dupes) == 1 and dupes[0].severity is Severity.ERROR
    assert dupes[0].view_id == PRODUCER
    summary = {v.id: v for v in store.list_views()}[PRODUCER]
    assert summary.rel_path == f"a/{PRODUCER}.calculationview"
    assert summary.package_path == "a"


def test_duplicate_view_id_prefers_parsed_over_failed(store, folder):
    (folder / "a").mkdir()
    (folder / "a" / f"{PRODUCER}.calculationview").write_bytes(b"garbage")  # failed, id = stem
    (folder / "b").mkdir()
    shutil.move(folder / f"{PRODUCER}.calculationview", folder / "b")
    report = import_folder(store, folder)
    assert [w.code for w in report.warnings] == ["DUPLICATE_VIEW_ID"]
    summary = {v.id: v for v in store.list_views()}[PRODUCER]
    assert summary.rel_path == f"b/{PRODUCER}.calculationview"
    assert summary.parse_status is not ParseStatus.FAILED
    assert report.failed == 0


def test_renamed_file_refreshes_rel_path(store, folder):
    import_folder(store, folder)
    (folder / f"{PRODUCER}.calculationview").rename(folder / "OTHER_NAME.calculationview")
    report = import_folder(store, folder)  # the view id comes from the XML, not the file name
    assert (report.unchanged, report.reparsed) == (2, 0)
    summary = {v.id: v for v in store.list_views()}[PRODUCER]
    assert summary.rel_path == "OTHER_NAME.calculationview"


def test_unchanged_file_with_different_result_is_reparsed(store, folder, tmp_path):
    import sqlite3

    import_folder(store, folder)
    _annotate(store, VIEW, TargetKind.VIEW)
    _annotate(store, f"{VIEW}/Join_1", TargetKind.NODE)
    _annotate(store, f"{VIEW}/GONE_1", TargetKind.NODE)
    good = store.raw_result_json(VIEW)
    # Simulate an older parser: different (even invalid-for-today) JSON and an extra node row.
    old_json = good.replace('"Join_1"', '"Join_X"').replace('"coverage_pct":100.0', '"legacy":1')
    store.conn.execute("UPDATE view SET result_json = ? WHERE id = ?", (old_json, VIEW))
    store.conn.execute("INSERT INTO node (id, view_id, name, node_type, understood, raw_hash) "
                       "VALUES (?, ?, 'GONE_1', 'projection', 1, 'x')", (f"{VIEW}/GONE_1", VIEW))

    report = import_folder(store, folder)
    assert (report.changed, report.unchanged, report.reparsed) == (0, 1, 1)
    assert store.raw_result_json(VIEW) == good
    assert report.stale_annotations == 1
    gone = store.get_annotation(f"{VIEW}/GONE_1", TargetKind.NODE)
    assert gone.stale and gone.stale_reason == "node removed"
    assert not store.get_annotation(VIEW, TargetKind.VIEW).stale
    assert not store.get_annotation(f"{VIEW}/Join_1", TargetKind.NODE).stale


def test_already_stale_annotation_kept_on_unchanged_view(store, folder):
    import_folder(store, folder)
    _annotate(store, f"{VIEW}/Projection_1", TargetKind.NODE)
    _edit(folder / MAIN_FILE, FILTER, "<filter>(&quot;COL_3&quot; = '2024')</filter>")
    import_folder(store, folder)
    report = import_folder(store, folder)
    assert report.unchanged == 2 and report.stale_annotations == 0
    ann = store.get_annotation(f"{VIEW}/Projection_1", TargetKind.NODE)
    assert ann.stale and ann.stale_reason == "node changed"


def test_stale_count_is_newly_marked_only(store, folder):
    import_folder(store, folder)
    _annotate(store, VIEW, TargetKind.VIEW)
    _edit(folder / MAIN_FILE, FILTER, "<filter>(&quot;COL_3&quot; = '2024')</filter>")
    assert import_folder(store, folder).stale_annotations == 1
    (folder / MAIN_FILE).unlink()
    report = import_folder(store, folder)
    assert report.removed == 1 and report.stale_annotations == 0
    assert store.get_annotation(VIEW, TargetKind.VIEW).stale_reason == "view removed"


def test_moved_file_refreshes_location_without_staling(store, folder):
    import_folder(store, folder)
    _annotate(store, PRODUCER, TargetKind.VIEW)
    (folder / "pkg").mkdir()
    shutil.move(folder / f"{PRODUCER}.calculationview", folder / "pkg")
    report = import_folder(store, folder)
    assert (report.added, report.changed, report.unchanged, report.removed) == (0, 0, 1, 0)
    assert report.reparsed == 1 and report.stale_annotations == 0
    summary = {v.id: v for v in store.list_views()}[PRODUCER]
    assert summary.package_path == "pkg"
    assert store.load_result(PRODUCER).view.package_path == "pkg"
    assert not store.get_annotation(PRODUCER, TargetKind.VIEW).stale


def test_scan_warnings_carried(store, folder):
    bad = folder / b"BAD_\xff.calculationview".decode("utf-8", "surrogateescape")
    try:
        bad.write_bytes(b"<x/>")
    except (OSError, UnicodeEncodeError):
        pytest.skip("file system rejects non-UTF-8 names")
    report = import_folder(store, folder)
    assert "SCAN_BAD_FILENAME" in [w.code for w in report.warnings]


def test_failure_rolls_back_whole_import(store, folder, monkeypatch):
    import_folder(store, folder)
    _annotate(store, VIEW, TargetKind.VIEW)
    _edit(folder / MAIN_FILE, FILTER, "<filter>(&quot;COL_3&quot; = '2024')</filter>")
    (folder / f"{PRODUCER}.calculationview").unlink()

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(store, "delete_view", boom)
    with pytest.raises(RuntimeError):
        import_folder(store, folder)
    assert sorted(store.view_hashes()) == [VIEW, PRODUCER]
    assert not store.get_annotation(VIEW, TargetKind.VIEW).stale
    assert "2024" not in _filter_text(store, "Projection_1")
