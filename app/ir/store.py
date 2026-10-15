"""SQLite persistence: one project per database file.

`view.result_json` holds the full ParseResult, the source of truth for pages; the `view`
and `node` columns are query summaries. Node rows are keyed per view: node ids are
`<view id>/<node name>` and both parts may contain `/`, so two views can produce the same
node id. `project.last_import_json` keeps the last import report (without the estate, which
is rebuilt per request) so the web app can show what an import skipped or warned about. Annotations have no foreign key on purpose: they
must outlive the view or node they describe (they are marked stale instead).

One connection per Store: open a Store per unit of work (e.g. one per request), close it
(ideally with `with`) and never use one Store from two threads at once. The connection is
made with check_same_thread=False only because FastAPI may run a yield dependency's setup
and teardown on different threads; that is sequential use, not sharing.
"""
from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from app.ir.models import Annotation, Node, ParseResult, Project, TargetKind, ViewSummary

if TYPE_CHECKING:  # the IR layer does not import ingest at runtime
    from app.ingest.scan import ScannedView

# 2: annotation keyed by (target_kind, target_id)
# 3: node keyed by (view_id, id); project.last_import_json
SCHEMA_VERSION = 3
BUSY_TIMEOUT_MS = 5000
_SAVEPOINT = "store_nested"

_SCHEMA = """
CREATE TABLE project (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT, source_folder TEXT, imported_at TEXT,
    last_import_json TEXT
);
CREATE TABLE view (
    id TEXT PRIMARY KEY, rel_path TEXT, package_path TEXT, file_hash TEXT, view_type TEXT,
    data_category TEXT, parse_status TEXT, coverage_pct REAL, node_count INTEGER,
    warning_count INTEGER, result_json TEXT NOT NULL
);
CREATE TABLE node (
    id TEXT NOT NULL, view_id TEXT NOT NULL REFERENCES view(id) ON DELETE CASCADE,
    name TEXT, node_type TEXT, understood INTEGER, raw_hash TEXT,
    PRIMARY KEY (view_id, id)
);
CREATE TABLE annotation (
    target_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('view', 'node')),
    purpose_text TEXT, owner TEXT,
    signoff_status TEXT CHECK (signoff_status IN ('draft', 'reviewed', 'approved')),
    notes TEXT, stale INTEGER NOT NULL DEFAULT 0, stale_reason TEXT, updated_at TEXT,
    PRIMARY KEY (target_kind, target_id)
);
"""

_SUMMARY_COLUMNS = ("id, rel_path, package_path, file_hash, view_type, data_category, "
                    "parse_status, coverage_pct, node_count, warning_count")
_ANNOTATION_COLUMNS = ("target_id, target_kind, purpose_text, owner, signoff_status, notes, "
                       "stale, stale_reason, updated_at")


class StoreVersionError(Exception):
    """The database was written by a different (unknown) schema version."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def raw_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def node_raw_hashes(nodes: Iterable[Node]) -> dict[str, str]:
    """node id -> sha256 of its `raw`. A malformed file can repeat a node id; then every
    raw sharing the id is hashed together (joined with NUL), in order, so any change to
    any of them is seen."""
    raws: dict[str, list[str]] = {}
    for node in nodes:
        raws.setdefault(node.id, []).append(node.raw)
    return {node_id: raw_hash("\0".join(parts)) for node_id, parts in raws.items()}


class Store:
    def __init__(self, path: Path) -> None:
        # isolation_level=None: no implicit transactions; `transaction()` issues BEGIN itself.
        self.conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        try:
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT_MS)}")
            self._ensure_schema(Path(path))
        except BaseException:
            self.conn.close()
            raise

    # -- lifecycle -------------------------------------------------------------------

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Commit on success, roll back on any exception (including a failed COMMIT).

        The outer block takes the write lock up front (BEGIN IMMEDIATE). A nested block is
        a savepoint, so it is atomic on its own and its failure rolls back only itself."""
        if self.conn.in_transaction:
            self.conn.execute(f"SAVEPOINT {_SAVEPOINT}")
            try:
                yield
            except BaseException:
                if self.conn.in_transaction:
                    self.conn.execute(f"ROLLBACK TO {_SAVEPOINT}")
                    self.conn.execute(f"RELEASE {_SAVEPOINT}")
                raise
            self.conn.execute(f"RELEASE {_SAVEPOINT}")
            return
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.conn.execute("COMMIT")
        except BaseException:
            if self.conn.in_transaction:  # a failed COMMIT leaves the transaction open
                self.conn.execute("ROLLBACK")
            raise

    def _ensure_schema(self, path: Path) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            return
        if version != 0:
            raise StoreVersionError(
                f"{path} has schema version {version}; this build understands only "
                f"version {SCHEMA_VERSION}")
        has_tables = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1").fetchone()
        if has_tables:
            raise StoreVersionError(
                f"{path} is a SQLite database but not a CalcView project (no schema version)")
        with self.transaction():
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    self.conn.execute(statement)
            # PRAGMA takes no bound parameters; SCHEMA_VERSION is a module constant int.
            self.conn.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")

    # -- project ---------------------------------------------------------------------

    def get_project(self) -> Project | None:
        row = self.conn.execute(
            "SELECT name, source_folder, imported_at FROM project WHERE id = 1").fetchone()
        return Project(**dict(row)) if row else None

    def set_project(self, name: str, source_folder: str) -> None:
        self.conn.execute(
            "INSERT INTO project (id, name, source_folder, imported_at) VALUES (1, ?, ?, ?) "
            "ON CONFLICT (id) DO UPDATE SET name = excluded.name, "
            "source_folder = excluded.source_folder, imported_at = excluded.imported_at",
            (name, source_folder, now_iso()))

    def get_last_import(self) -> str | None:
        """The last import report as JSON text, not validated (it may predate a model
        change); None before the first import."""
        row = self.conn.execute("SELECT last_import_json FROM project WHERE id = 1").fetchone()
        return row["last_import_json"] if row else None

    def set_last_import(self, report_json: str) -> None:
        """Requires the project row (`set_project` first)."""
        self.conn.execute("UPDATE project SET last_import_json = ? WHERE id = 1", (report_json,))

    # -- views -----------------------------------------------------------------------

    def upsert_view(self, scanned: ScannedView) -> None:
        result = scanned.result
        view = result.view
        with self.transaction():
            self.conn.execute("DELETE FROM view WHERE id = ?", (view.id,))  # cascades to node
            self.conn.execute(
                f"INSERT INTO view ({_SUMMARY_COLUMNS}, result_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (view.id, scanned.rel_path, scanned.package_path, view.file_hash,
                 str(view.view_type), str(view.data_category), str(view.parse_status),
                 view.coverage_pct, len(result.nodes), len(result.warnings),
                 result.model_dump_json()))
            # One row per node id: a repeated id keeps its first node's name and type, and
            # its hash covers every raw sharing the id (the full result keeps every node).
            hashes = node_raw_hashes(result.nodes)
            first: dict[str, Node] = {}
            for n in result.nodes:
                first.setdefault(n.id, n)
            self.conn.executemany(
                "INSERT INTO node (id, view_id, name, node_type, understood, raw_hash) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(n.id, view.id, n.name, str(n.node_type), int(n.understood), hashes[n.id])
                 for n in first.values()])

    def delete_view(self, view_id: str) -> None:
        self.conn.execute("DELETE FROM view WHERE id = ?", (view_id,))

    def view_hashes(self) -> dict[str, str]:
        return {r["id"]: r["file_hash"] for r in self.conn.execute("SELECT id, file_hash FROM view")}

    def view_locations(self) -> dict[str, str]:
        """id -> rel_path."""
        return {r["id"]: r["rel_path"] for r in self.conn.execute("SELECT id, rel_path FROM view")}

    def raw_result_json(self, view_id: str) -> str | None:
        """The stored ParseResult JSON as text, not validated (old rows may predate a
        model change)."""
        row = self.conn.execute("SELECT result_json FROM view WHERE id = ?", (view_id,)).fetchone()
        return row["result_json"] if row else None

    # Rows are fetched in full before validation: a validation error raised mid-iteration
    # would leave the statement unfinalized, and its read lock would outlive close().

    def list_views(self) -> list[ViewSummary]:
        rows = self.conn.execute(f"SELECT {_SUMMARY_COLUMNS} FROM view ORDER BY id").fetchall()
        return [ViewSummary(**dict(r)) for r in rows]

    def load_result(self, view_id: str) -> ParseResult | None:
        row = self.conn.execute("SELECT result_json FROM view WHERE id = ?", (view_id,)).fetchone()
        return ParseResult.model_validate_json(row["result_json"]) if row else None

    def load_all_results(self) -> list[ParseResult]:
        rows = self.conn.execute("SELECT result_json FROM view ORDER BY id").fetchall()
        return [ParseResult.model_validate_json(r["result_json"]) for r in rows]

    def node_hashes(self, view_id: str) -> dict[str, str]:
        rows = self.conn.execute("SELECT id, raw_hash FROM node WHERE view_id = ?", (view_id,))
        return {r["id"]: r["raw_hash"] for r in rows}

    # -- annotations -----------------------------------------------------------------

    def get_annotation(self, target_id: str, kind: TargetKind) -> Annotation | None:
        """A view and a node may share an id; each kind has its own annotation."""
        row = self.conn.execute(
            f"SELECT {_ANNOTATION_COLUMNS} FROM annotation "
            "WHERE target_kind = ? AND target_id = ?", (str(kind), target_id)).fetchone()
        return _annotation(row) if row else None

    def save_annotation(self, annotation: Annotation) -> Annotation:
        """Insert or replace; saving is a human review, so it clears any stale mark."""
        saved = annotation.model_copy(update={"stale": False, "stale_reason": None,
                                              "updated_at": now_iso()})
        self.conn.execute(
            f"INSERT OR REPLACE INTO annotation ({_ANNOTATION_COLUMNS}) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (saved.target_id, str(saved.target_kind), saved.purpose_text, saved.owner,
             str(saved.signoff_status), saved.notes, 0, None, saved.updated_at))
        return saved

    def mark_stale(self, target_ids: Iterable[str], reason: str, kind: TargetKind) -> int:
        """Mark existing annotations stale with `reason` (an already-stale one gets the new
        reason); ids without an annotation are ignored. Returns how many annotations were
        newly marked (not stale before)."""
        marked = 0
        with self.transaction():
            for target_id in target_ids:
                cursor = self.conn.execute(
                    "UPDATE annotation SET stale = 1, stale_reason = ? "
                    "WHERE target_kind = ? AND target_id = ? AND stale = 0",
                    (reason, str(kind), target_id))
                marked += cursor.rowcount
                self.conn.execute(
                    "UPDATE annotation SET stale_reason = ? "
                    "WHERE target_kind = ? AND target_id = ? AND stale = 1",
                    (reason, str(kind), target_id))
        return marked

    def list_annotations(self) -> list[Annotation]:
        rows = self.conn.execute(f"SELECT {_ANNOTATION_COLUMNS} FROM annotation "
                                 "ORDER BY target_id, target_kind")
        return [_annotation(r) for r in rows]


def _annotation(row: sqlite3.Row) -> Annotation:
    data = dict(row)
    data["stale"] = bool(data["stale"])
    return Annotation(**data)
