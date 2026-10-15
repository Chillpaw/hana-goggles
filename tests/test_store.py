"""SQLite store: schema, versioning, ParseResult round trip, annotations."""
import sqlite3

import pytest
from conftest import FIXTURES, MAIN

from app.ingest.scan import scan_folder
from app.ir.models import Annotation, Node, NodeType, SignoffStatus, TargetKind
from app.ir.store import SCHEMA_VERSION, Store, StoreVersionError, node_raw_hashes, raw_hash

VIEW = "GENERIC_TAX_REPORTING_CUBE"


def _scanned(tmp_path):
    folder = tmp_path / "src"
    folder.mkdir()
    (folder / "GENERIC_TAX_REPORTING_CUBE.calculationview").write_bytes((FIXTURES / MAIN).read_bytes())
    (scanned,) = scan_folder(folder)
    return scanned


def test_creates_schema_and_reopens(tmp_path):
    db = tmp_path / "p.db"
    with Store(db) as store:
        assert store.get_project() is None
        store.set_project("Proj", "/some/folder")
    with Store(db) as store:
        project = store.get_project()
    assert project.name == "Proj"
    assert project.source_folder == "/some/folder"
    assert project.imported_at  # ISO timestamp

    conn = sqlite3.connect(db)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 2
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert {"project", "view", "node", "annotation"} <= tables


def test_foreign_keys_on(tmp_path):
    with Store(tmp_path / "p.db") as store:
        assert store.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_unknown_user_version_refused(tmp_path):
    db = tmp_path / "p.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(StoreVersionError, match="99"):
        Store(db)


def test_version_1_db_refused(tmp_path):
    """Version 1 keyed annotations by id alone; no migration (no real data existed)."""
    db = tmp_path / "p.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE annotation (target_id TEXT PRIMARY KEY)")
    conn.execute("PRAGMA user_version = 1")
    conn.close()
    with pytest.raises(StoreVersionError, match="version 1"):
        Store(db)


def test_view_and_node_annotations_with_one_id_are_separate(tmp_path):
    with Store(tmp_path / "p.db") as store:
        store.save_annotation(Annotation(target_id="A/B", target_kind=TargetKind.VIEW, notes="v"))
        store.save_annotation(Annotation(target_id="A/B", target_kind=TargetKind.NODE, notes="n"))
        assert store.get_annotation("A/B", TargetKind.VIEW).notes == "v"
        assert store.get_annotation("A/B", TargetKind.NODE).notes == "n"
        assert store.mark_stale(["A/B"], "view removed", TargetKind.VIEW) == 1
        assert store.get_annotation("A/B", TargetKind.VIEW).stale
        assert not store.get_annotation("A/B", TargetKind.NODE).stale
        assert [(a.target_kind, a.target_id) for a in store.list_annotations()] == [
            ("node", "A/B"), ("view", "A/B")]


def test_context_manager_closes(tmp_path):
    with Store(tmp_path / "p.db") as store:
        pass
    with pytest.raises(sqlite3.ProgrammingError):
        store.conn.execute("SELECT 1")


def test_view_round_trip_and_summaries(tmp_path):
    scanned = _scanned(tmp_path)
    with Store(tmp_path / "p.db") as store:
        store.upsert_view(scanned)
        assert store.load_result(VIEW) == scanned.result
        assert store.load_all_results() == [scanned.result]
        assert store.load_result("NOPE") is None
        assert store.view_hashes() == {VIEW: scanned.result.view.file_hash}

        (summary,) = store.list_views()
        assert summary.id == VIEW
        assert summary.rel_path == "GENERIC_TAX_REPORTING_CUBE.calculationview"
        assert summary.node_count == len(scanned.result.nodes)
        assert summary.parse_status == scanned.result.view.parse_status
        assert summary.warning_count == len(scanned.result.warnings)

        hashes = store.node_hashes(VIEW)
        assert set(hashes) == {n.id for n in scanned.result.nodes}
        assert all(len(h) == 64 for h in hashes.values())

        store.upsert_view(scanned)  # replacing is idempotent
        assert len(store.node_hashes(VIEW)) == len(scanned.result.nodes)

        store.delete_view(VIEW)
        assert store.list_views() == []
        assert store.node_hashes(VIEW) == {}  # cascade


def test_annotation_save_load_and_stale(tmp_path):
    with Store(tmp_path / "p.db") as store:
        assert store.get_annotation("X", TargetKind.VIEW) is None
        saved = store.save_annotation(Annotation(
            target_id=f"{VIEW}/Join_1", target_kind=TargetKind.NODE, purpose_text="joins",
            owner="me", signoff_status=SignoffStatus.REVIEWED, notes="n"))
        assert saved.updated_at
        loaded = store.get_annotation(f"{VIEW}/Join_1", TargetKind.NODE)
        assert loaded == saved
        assert loaded.stale is False and loaded.stale_reason is None

        assert store.mark_stale([f"{VIEW}/Join_1", "missing"], "node changed", TargetKind.NODE) == 1
        stale = store.get_annotation(f"{VIEW}/Join_1", TargetKind.NODE)
        assert stale.stale is True and stale.stale_reason == "node changed"
        # already stale: not counted again, but the reason is updated
        assert store.mark_stale([f"{VIEW}/Join_1"], "view removed", TargetKind.NODE) == 0
        stale = store.get_annotation(f"{VIEW}/Join_1", TargetKind.NODE)
        assert stale.stale is True and stale.stale_reason == "view removed"

        store.save_annotation(stale)  # saving clears stale
        cleared = store.get_annotation(f"{VIEW}/Join_1", TargetKind.NODE)
        assert cleared.stale is False and cleared.stale_reason is None

        store.save_annotation(Annotation(target_id=VIEW, target_kind=TargetKind.VIEW))
        assert [a.target_id for a in store.list_annotations()] == [VIEW, f"{VIEW}/Join_1"]


def test_annotation_survives_view_delete(tmp_path):
    scanned = _scanned(tmp_path)
    with Store(tmp_path / "p.db") as store:
        store.upsert_view(scanned)
        store.save_annotation(Annotation(target_id=VIEW, target_kind=TargetKind.VIEW))
        store.delete_view(VIEW)
        assert store.get_annotation(VIEW, TargetKind.VIEW) is not None


def test_transaction_rolls_back(tmp_path):
    scanned = _scanned(tmp_path)
    with Store(tmp_path / "p.db") as store:
        with pytest.raises(RuntimeError):
            with store.transaction():
                store.upsert_view(scanned)
                raise RuntimeError("boom")
        assert store.list_views() == []


def test_nested_transaction_is_a_savepoint(tmp_path):
    scanned = _scanned(tmp_path)
    with Store(tmp_path / "p.db") as store:
        with store.transaction():
            store.set_project("Outer", "/f")
            with pytest.raises(RuntimeError):
                with store.transaction():
                    store.upsert_view(scanned)
                    raise RuntimeError("inner fails")
        assert store.list_views() == []  # inner block rolled back alone
        assert store.get_project().name == "Outer"  # outer block committed


def test_failed_commit_rolls_back_and_store_stays_usable(tmp_path):
    db = tmp_path / "p.db"
    scanned = _scanned(tmp_path)
    store = Store(db)
    store.conn.execute("PRAGMA busy_timeout = 50")
    reader = sqlite3.connect(db, isolation_level=None)
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM view").fetchall()  # holds a shared lock
        with pytest.raises(sqlite3.OperationalError):
            with store.transaction():
                store.upsert_view(scanned)
        assert store.conn.in_transaction is False
        reader.execute("ROLLBACK")

        with store.transaction():
            store.upsert_view(scanned)
    finally:
        reader.close()
        store.close()
    with Store(db) as reopened:
        assert [v.id for v in reopened.list_views()] == [VIEW]


def test_busy_timeout_set(tmp_path):
    with Store(tmp_path / "p.db") as store:
        assert store.conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_repeated_node_ids_hash_together(tmp_path):
    def n(raw):
        return Node(id="V/N", view_id="V", node_type=NodeType.OPAQUE, name="N", raw=raw)

    assert node_raw_hashes([n("a")]) == {"V/N": raw_hash("a")}
    assert node_raw_hashes([n("a"), n("b")]) == {"V/N": raw_hash("a\0b")}

    scanned = _scanned(tmp_path)
    scanned.result.nodes.append(n("extra").model_copy(update={"id": scanned.result.nodes[0].id}))
    with Store(tmp_path / "p.db") as store:
        store.upsert_view(scanned)  # no primary-key clash
        first = scanned.result.nodes[0]
        assert store.node_hashes(VIEW)[first.id] == raw_hash(first.raw + "\0extra")
