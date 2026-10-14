"""`calcview` command line: import and serve. Audit and export arrive in M4.

`import` is a local command and may print view names; the audit command (M4) never does.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import uvicorn

from app.ingest.importer import ImportReport, import_folder
from app.ir.store import Store, StoreVersionError
from app.main import DEFAULT_DB, HOST, create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="calcview")
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import", help="import (or re-import) a folder of views into the db")
    imp.add_argument("folder", type=Path)
    imp.add_argument("--db", type=Path, default=DEFAULT_DB,
                     help="project database file (default: ./calcview.db)")
    imp.add_argument("--name", help="project name (default: kept, else the folder name)")

    serve = sub.add_parser("serve", help="start the web app on 127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--db", type=Path, default=None,
                       help="project database file (default: $CALCVIEW_DB, else ./calcview.db)")
    args = parser.parse_args(argv)

    if args.command == "import":
        return _import(args.folder, args.db, args.name)
    if args.command == "serve":
        uvicorn.run(create_app(args.db), host=HOST, port=args.port)
    return 0


def _import(folder: Path, db: Path, name: str | None) -> int:
    if not folder.is_dir():
        print(f"calcview: {folder} is not a directory", file=sys.stderr)
        return 2
    try:
        with Store(db) as store:
            report = import_folder(store, folder, name)
            project = store.get_project()
    except NotADirectoryError:  # the folder vanished between the check and the scan
        print(f"calcview: {folder} is not a directory", file=sys.stderr)
        return 2
    except (StoreVersionError, sqlite3.DatabaseError) as exc:
        print(f"calcview: cannot use database {db}: {_one_line(str(exc))}", file=sys.stderr)
        return 2
    for line in format_report(report, project.name if project else "", db):
        print(line)
    return 0


def format_report(report: ImportReport, project_name: str, db: Path) -> list[str]:
    """Plain, deterministic lines. Order follows the report and estate, which are sorted."""
    estate = report.estate
    internal = [d for d in estate.dependencies if d.internal]
    external = [d for d in estate.dependencies if not d.internal]
    warnings = [*report.warnings, *estate.warnings]
    return [
        f"Project: {project_name}",
        f"Database: {db}",
        f"Added: {report.added}",
        f"Changed: {report.changed}",
        f"Unchanged: {report.unchanged}",
        f"Removed: {report.removed}",
        f"Failed: {report.failed}",
        f"Stale annotations: {report.stale_annotations}",
        f"Internal dependencies: {len(internal)}",
        *(f"  {d.consumer} -> {d.producer}" for d in internal),
        f"Unresolved dependencies: {len(external)}",
        *(f"  {d.consumer} -> {d.producer}" for d in external),
        f"Cycles: {len(estate.cycles)}",
        *(f"  {', '.join(cycle)}" for cycle in estate.cycles),
        f"Deploy order: {len(estate.deploy_order)}",
        *(f"  {i}. {view_id}" for i, view_id in enumerate(estate.deploy_order, 1)),
        f"Warnings: {len(warnings)}",
        *(f"  {w.severity.value.upper()} {w.code} {_one_line(w.message)}" for w in warnings),
    ]


def _one_line(text: str) -> str:
    return " ".join(text.split())
