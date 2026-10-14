"""`calcview` command line: import, serve and audit. Export arrives later.

`import` is a local command and may print view names; `audit` never does: it prints a
structure-only report (see app/audit.py) meant to be carried out of the work boundary.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import uvicorn

from app.audit import FORMATS, run_audit
from app.ingest.importer import ImportReport, import_folder
from app.ir.models import Estate, LeafKind
from app.ir.store import Store, StoreVersionError
from app.main import HOST, create_app, default_db_path

# Leaf kinds that are expected endpoints of the estate; anything else is unresolved.
_LEAF_KINDS = {LeafKind.TABLE, LeafKind.TABLE_FUNCTION}
_DB_HELP = "project database file (default: $CALCVIEW_DB, else ./calcview.db)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="calcview")
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import", help="import (or re-import) a folder of views into the db")
    imp.add_argument("folder", type=Path)
    imp.add_argument("--db", type=Path, default=None, help=_DB_HELP)
    imp.add_argument("--name",
                     help="project name (default: the existing name, else the folder name)")

    serve = sub.add_parser("serve", help="start the web app on 127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--db", type=Path, default=None, help=_DB_HELP)

    audit = sub.add_parser("audit", help="print a structure-only report of a folder (no names)")
    audit.add_argument("folder", type=Path)
    audit.add_argument("--format", choices=FORMATS, default="text")
    args = parser.parse_args(argv)

    if args.command == "audit":
        return _audit(args.folder, args.format)

    db = args.db if args.db is not None else default_db_path()
    if args.command == "import":
        return _import(args.folder, db, args.name)
    if args.command == "serve":
        return _serve(db, args.port)
    return 0


def _audit(folder: Path, fmt: str) -> int:
    # The folder is the user's own argument, so echoing it in an error is fine; the report
    # itself never contains it.
    try:
        output = run_audit(folder, fmt)
    except NotADirectoryError:
        print(f"calcview: {folder} is not a directory", file=sys.stderr)
        return 2
    sys.stdout.write(output)
    return 0


def _serve(db: Path, port: int) -> int:
    """Fail fast on an unusable existing db; a missing one is created by the first import."""
    if db.exists():
        try:
            Store(db).close()
        except (StoreVersionError, sqlite3.DatabaseError, OSError) as exc:
            _db_error(db, exc)
            return 2
    uvicorn.run(create_app(db), host=HOST, port=port)
    return 0


def _import(folder: Path, db: Path, name: str | None) -> int:
    if not folder.is_dir():
        print(f"calcview: {folder} is not a directory", file=sys.stderr)
        return 2
    existed = db.exists()
    try:
        with Store(db) as store:
            report = import_folder(store, folder, name)
            project = store.get_project()
    except NotADirectoryError:  # the folder vanished between the check and the scan
        _remove_if_new(db, existed)
        print(f"calcview: {folder} is not a directory", file=sys.stderr)
        return 2
    except (StoreVersionError, sqlite3.DatabaseError, OSError) as exc:
        _remove_if_new(db, existed)
        _db_error(db, exc)
        return 2
    for line in format_report(report, project.name if project else "", db):
        print(line)
    return 0


def _remove_if_new(db: Path, existed: bool) -> None:
    """The import is one transaction, so a failed import into a new file left it empty."""
    if not existed:
        db.unlink(missing_ok=True)


def _db_error(db: Path, exc: BaseException) -> None:
    print(f"calcview: cannot use database {db}: {_one_line(str(exc))}", file=sys.stderr)


def format_report(report: ImportReport, project_name: str, db: Path) -> list[str]:
    """Plain, deterministic lines. Order follows the report and estate, which are sorted."""
    estate = report.estate
    internal = [d for d in estate.dependencies if d.internal]
    leaf_ids = _leaf_ids(estate)
    leaves = [d for d in estate.dependencies if not d.internal and d.producer in leaf_ids]
    unresolved = [d for d in estate.dependencies if not d.internal and d.producer not in leaf_ids]
    warnings = [*report.warnings, *estate.warnings]
    return [
        f"Project: {project_name}",
        f"Database: {db}",
        f"Added: {report.added}",
        f"Changed: {report.changed}",
        f"Unchanged: {report.unchanged}",
        f"Reparsed: {report.reparsed}",
        f"Removed: {report.removed}",
        f"Failed: {report.failed}",
        f"Stale annotations: {report.stale_annotations}",
        f"Internal dependencies: {len(internal)}",
        *(f"  {d.consumer} -> {d.producer}" for d in internal),
        f"Leaf sources: {len(leaves)}",
        *(f"  {d.consumer} -> {d.producer}" for d in leaves),
        f"Unresolved: {len(unresolved)}",
        *(f"  {d.consumer} -> {d.producer}" for d in unresolved),
        f"Cycles: {len(estate.cycles)}",
        *(f"  {', '.join(cycle)}" for cycle in estate.cycles),
        f"Deploy order: {len(estate.deploy_order)}",
        *(f"  {i}. {view_id}" for i, view_id in enumerate(estate.deploy_order, 1)),
        f"Warnings: {len(warnings)}",
        *(f"  {w.severity.value.upper()} {w.code} {_one_line(w.message)}" for w in warnings),
    ]


def _leaf_ids(estate: Estate) -> set[str]:
    """Producers that are tables or table functions. External views (including ambiguous
    ones, which resolve to `view:` leaves) and unknown sources count as unresolved."""
    return {leaf.id for leaf in estate.leaf_sources if leaf.kind in _LEAF_KINDS}


def _one_line(text: str) -> str:
    return " ".join(text.split())
