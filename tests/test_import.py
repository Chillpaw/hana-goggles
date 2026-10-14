"""Import and re-import into the store, with stale annotations. Tests edit copies only."""
import shutil

import pytest
from conftest import FIXTURES

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
    view_ann = store.get_annotation(VIEW)
    assert view_ann.stale and view_ann.stale_reason == "view file changed"
    proj = store.get_annotation(f"{VIEW}/Projection_1")
    assert proj.stale and proj.stale_reason == "node changed"
    assert not store.get_annotation(f"{VIEW}/Join_1").stale
    assert not store.get_annotation(PRODUCER).stale
    filters = [n for n in store.load_result(VIEW).nodes if n.name == "Projection_1"][0].filters
    assert "2024" in filters[0].expression.text


def test_removed_node(store, folder):
    import_folder(store, folder)
    _annotate(store, f"{VIEW}/Projection_1", TargetKind.NODE)
    # rename the node and its one reference: Projection_1 no longer exists
    _edit(folder / MAIN_FILE, 'id="Projection_1"', 'id="Projection_9"')
    _edit(folder / MAIN_FILE, 'node="#Projection_1"', 'node="#Projection_9"')
    import_folder(store, folder)
    ann = store.get_annotation(f"{VIEW}/Projection_1")
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
    for target in (VIEW, f"{VIEW}/Join_1"):
        ann = store.get_annotation(target)
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


def test_moved_file_refreshes_location_without_staling(store, folder):
    import_folder(store, folder)
    _annotate(store, PRODUCER, TargetKind.VIEW)
    (folder / "pkg").mkdir()
    shutil.move(folder / f"{PRODUCER}.calculationview", folder / "pkg")
    report = import_folder(store, folder)
    assert (report.added, report.changed, report.unchanged, report.removed) == (0, 0, 2, 0)
    summary = {v.id: v for v in store.list_views()}[PRODUCER]
    assert summary.package_path == "pkg"
    assert store.load_result(PRODUCER).view.package_path == "pkg"
    assert not store.get_annotation(PRODUCER).stale


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
    assert not store.get_annotation(VIEW).stale
    assert "2024" not in store.load_result(VIEW).nodes[3].filters[0].expression.text
