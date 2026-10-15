"""Page routes: import form, views list, view page (tabs) and the node panel fragment.

Every page reads the stored IR and rebuilds the estate per request (`app.web.loading`).
GET pages use `get_existing_store`, so browsing never creates a database file.

URLs: a view page is `/views/{view_id}` with the id percent-encoded (ids may contain `/`,
`.`, `:`; the route takes a `path` parameter so an encoded `/` still matches). The node
panel is `/node?view=<view id>&node=<node id>`: query parameters, so a view id with
slashes can never be confused with a node id.
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from pydantic import ValidationError

from app.generators.describe import NodeDescription, describe_node, describe_view, render_expression
from app.generators.lineage import MISSING_TYPE, view_elements
from app.ingest.importer import VIEW_REMOVED, ImportReport, import_folder, last_import
from app.ir.graph import downstream, upstream
from app.ir.models import (
    Annotation,
    Estate,
    Node,
    ParseResult,
    SignoffStatus,
    TargetKind,
)
from app.ir.store import Store, StoreVersionError
from app.web.deps import get_existing_store
from app.web.loading import Loaded, OutdatedDataError, load_project

TEMPLATES_DIR = Path(__file__).parent / "templates"
TABS = {"graph": "Graph", "steps": "Steps", "columns": "Columns", "warnings": "Warnings",
        "raw": "Raw XML", "notes": "Notes"}
MAX_NOTE_CHARS = 20_000
SIGNOFF_VALUES = [str(s) for s in SignoffStatus]

router = APIRouter()


# ---------------------------------------------------------------- template helpers

def view_url(view_id: str) -> str:
    return "/views/" + quote(view_id, safe="")


def view_mmd_url(view_id: str) -> str:
    return "/view.mmd?" + urlencode({"view": view_id}, quote_via=quote)


def node_url(view_id: str, node_id: str) -> str:
    return "/node?" + urlencode({"view": view_id, "node": node_id}, quote_via=quote)


def notes_url(view_id: str) -> str:
    return "/notes?" + urlencode({"view": view_id}, quote_via=quote)


def node_notes_url(view_id: str, node_id: str) -> str:
    return "/node/notes?" + urlencode({"view": view_id, "node": node_id}, quote_via=quote)


# Greedy: from the first backtick to the LAST "` (not parsed)", so raw text that itself
# contains backticks stays inside one code span (a sentence holds one expression).
_NOT_PARSED = re.compile(r"`(.*)` \(not parsed\)", re.DOTALL)


def prose(text: str) -> Markup:
    """Escape a description sentence, then show each `` `raw` (not parsed) `` span as code.
    The substitution runs on already-escaped text, so it cannot introduce markup."""
    escaped = str(escape(text))
    return Markup(_NOT_PARSED.sub(
        lambda m: f'<code class="raw">{m.group(1)}</code> <span class="not-parsed">(not parsed)</span>',
        escaped))


def column_type(column) -> str:
    if not column.datatype:
        return ""
    size = [str(v) for v in (column.length, column.scale) if v is not None]
    return f"{column.datatype}({','.join(size)})" if size else column.datatype


templates = Jinja2Templates(directory=TEMPLATES_DIR)  # select_autoescape(): on for .html
templates.env.filters["prose"] = prose
templates.env.globals.update(view_url=view_url, view_mmd_url=view_mmd_url, node_url=node_url,
                             notes_url=notes_url, node_notes_url=node_notes_url, column_type=column_type,
                             render_expression=render_expression, tabs=TABS,
                             signoff_values=SIGNOFF_VALUES, max_note_chars=MAX_NOTE_CHARS)


# ---------------------------------------------------------------- errors

def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(OutdatedDataError, _outdated_data)
    app.add_exception_handler(StoreVersionError, _unusable_db)
    app.add_exception_handler(sqlite3.DatabaseError, _unusable_db)


def _outdated_data(request: Request, exc: Exception) -> Response:
    project = exc.project if isinstance(exc, OutdatedDataError) else None
    return templates.TemplateResponse(request, "error.html", {
        "title": "Stored data is from an older version",
        "message": ("This project was imported by an older version of CalcView Migrator, and "
                    "its stored views can no longer be read. Re-import the folder to refresh "
                    "them; notes and sign-offs are kept."),
        "project": project,
    }, status_code=409)


def _unusable_db(request: Request, exc: Exception) -> Response:
    return templates.TemplateResponse(request, "error.html", {
        "title": "Cannot use this database",
        "message": (f"{request.app.state.db_path} cannot be read as a CalcView project ({exc}). "
                    "It may come from a different version, or from another program. "
                    "Re-import the folder into a new database file with --db."),
        "project": None,
    }, status_code=409)


# ---------------------------------------------------------------- import

@router.get("/", response_class=HTMLResponse)
def index(request: Request, store: Store | None = Depends(get_existing_store)):
    if store is not None and store.get_project() is not None:
        return RedirectResponse("/views", status_code=303)
    return templates.TemplateResponse(request, "index.html", {"error": None, "folder": ""})


@router.post("/import", response_class=HTMLResponse)
async def post_import(request: Request):
    # Parsed by hand: python-multipart is not a dependency, and the form is urlencoded.
    form = parse_qs((await request.body()).decode("utf-8", "replace"))
    folder = (form.get("folder") or [""])[0].strip()
    if not folder or not _is_dir(folder):
        return templates.TemplateResponse(
            request, "index.html",
            {"error": f"{folder or '(empty)'} is not a folder on this computer.", "folder": folder},
            status_code=400)
    try:
        await run_in_threadpool(_import, request.app.state.db_path, Path(folder))
    except OSError as exc:  # unreadable folder, db path not writable, disk full, ...
        return templates.TemplateResponse(
            request, "index.html",
            {"error": f"Import failed: {exc}", "folder": folder}, status_code=400)
    return RedirectResponse("/views", status_code=303)


def _is_dir(folder: str) -> bool:
    try:
        return Path(folder).is_dir()
    except (OSError, ValueError):  # e.g. an embedded NUL
        return False


def _import(db_path: Path, folder: Path) -> None:
    # The only route that may create the db file, and only once the folder is known good.
    with Store(db_path) as store:
        import_folder(store, folder)


# ---------------------------------------------------------------- views list

SORTS = {
    "name": lambda r: r["id"],
    "package": lambda r: r["package"] or "",
    "type": lambda r: r["view_type"],
    "category": lambda r: r["data_category"],
    "nodes": lambda r: r["node_count"],
    "coverage": lambda r: r["coverage_pct"],
    "status": lambda r: r["parse_status"],
    "warnings": lambda r: r["warning_count"],
    "depends": lambda r: r["depends"],
    "usedby": lambda r: r["usedby"],
    # no note sorts first ascending, then by how far the review got
    "signoff": lambda r: SIGNOFF_VALUES.index(r["signoff"]) + 1 if r["signoff"] else 0,
}


@router.get("/views", response_class=HTMLResponse)
def views(request: Request, sort: str = "name", q: str = "",
          store: Store | None = Depends(get_existing_store)):
    project = store.get_project() if store is not None else None
    if store is None or project is None:
        return RedirectResponse("/", status_code=303)
    loaded = load_project(store, project)
    producers, consumers = _direct_links(loaded.estate)
    annotations = store.list_annotations()
    view_notes = {a.target_id: a for a in annotations if a.target_kind == TargetKind.VIEW}
    _, removed_notes = orphaned_notes(annotations, set(loaded.results), _all_node_ids(loaded))

    rows = [{
        "id": s.id, "package": s.package_path, "view_type": str(s.view_type),
        "data_category": str(s.data_category), "node_count": s.node_count,
        "coverage_pct": s.coverage_pct, "parse_status": str(s.parse_status),
        "warning_count": s.warning_count,
        "depends": len(producers.get(s.id, ())), "usedby": len(consumers.get(s.id, ())),
        "signoff": str(view_notes[s.id].signoff_status) if s.id in view_notes else None,
        "note": view_notes.get(s.id),
    } for s in loaded.summaries]
    needle = q.strip().lower()
    if needle:
        rows = [r for r in rows if needle in r["id"].lower() or needle in (r["package"] or "").lower()]
    descending = sort.startswith("-")
    key = sort.lstrip("-")
    if key not in SORTS:
        key, descending = "name", False
    rows.sort(key=lambda r: r["id"])
    rows.sort(key=SORTS[key], reverse=descending)

    estate = loaded.estate
    report, report_unreadable = _last_import(store)
    return templates.TemplateResponse(request, "views.html", {
        "project": project, "rows": rows,
        "last_import": report, "last_import_unreadable": report_unreadable,
        "stored_ids": set(loaded.results), "sort_key": key, "descending": descending, "q": q,
        "total": len(loaded.summaries), "estate": estate,
        "removed_notes": removed_notes,
        "internal_count": sum(1 for d in estate.dependencies if d.internal),
        "sort_columns": [("name", "View"), ("package", "Package"), ("type", "Type"),
                         ("category", "Category"), ("nodes", "Nodes"), ("coverage", "Coverage"),
                         ("status", "Parse"), ("warnings", "Warnings"),
                         ("depends", "Reads views"), ("usedby", "Used by"),
                         ("signoff", "Sign-off")],
    })


def _last_import(store: Store) -> tuple[ImportReport | None, bool]:
    """(the last import's report, whether a stored report failed to validate)."""
    try:
        return last_import(store), False
    except ValidationError:
        return None, True


def _direct_links(estate: Estate) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """consumer -> its internal producer views; producer -> its internal consumer views
    (direct only, each sorted and distinct)."""
    pairs = {(d.consumer, d.producer) for d in estate.dependencies if d.internal}
    producers: dict[str, list[str]] = {}
    consumers: dict[str, list[str]] = {}
    for consumer, producer in sorted(pairs):
        producers.setdefault(consumer, []).append(producer)
        consumers.setdefault(producer, []).append(consumer)
    return producers, consumers


# ---------------------------------------------------------------- view page

@router.get("/views/{view_id:path}", response_class=HTMLResponse)
def view_page(request: Request, view_id: str, tab: str = "graph",
              store: Store | None = Depends(get_existing_store)):
    context = view_context(store, view_id, tab)
    if isinstance(context, str):
        return not_found(request, context)
    return templates.TemplateResponse(request, "view.html", context)


def view_context(store: Store | None, view_id: str, tab: str) -> dict | str:
    """Everything view.html needs, or a "not found" message."""
    project = store.get_project() if store is not None else None
    if store is None or project is None:
        return f"No project has been imported, so there is no view {view_id}."
    loaded = load_project(store, project)
    result = loaded.results.get(view_id)
    if result is None:
        return f"There is no view {view_id} in this project."
    estate = loaded.estate
    tab = tab if tab in TABS else "graph"
    descriptions = describe_view(result, estate)
    producers, consumers = _direct_links(estate)
    nodes_by_id = {n.id: n for n in result.nodes}
    steps = [(nodes_by_id[d.node_id], d) for d in descriptions if d.node_id in nodes_by_id]
    leaf_ids = {d.producer for d in estate.dependencies if d.consumer == view_id and not d.internal}
    annotations = store.list_annotations()
    note = next((a for a in annotations
                 if a.target_kind == TargetKind.VIEW and a.target_id == view_id), None)

    context = {
        "project": project, "result": result, "view": result.view, "tab": tab,
        "summary": next((s for s in loaded.summaries if s.id == view_id), None),
        "failed": not result.nodes, "steps": steps,
        "reads_from": producers.get(view_id, []), "read_by": consumers.get(view_id, []),
        "all_upstream": upstream(estate, view_id), "all_downstream": downstream(estate, view_id),
        "leaves": [leaf for leaf in estate.leaf_sources if leaf.id in leaf_ids],
        "cycles": [c for c in estate.cycles if view_id in c],
        "estate_warnings": [w for w in estate.warnings if w.view_id == view_id],
        "node_names": {n.id: n.name for n in result.nodes},
        "warning_counts": Counter(w.node_id for w in result.warnings if w.node_id),
        "elements": _graph_elements(result, descriptions) if tab == "graph" else None,
        "note": note, "form": None, "form_error": None,
    }
    if tab == "notes":
        context["step_notes"] = [(nodes_by_id[a.target_id], a) for a in annotations
                                 if a.target_kind == TargetKind.NODE and a.target_id in nodes_by_id]
        by_view, _ = orphaned_notes(annotations, set(loaded.results), _all_node_ids(loaded))
        context["orphan_notes"] = by_view.get(view_id, [])
    return context


def _all_node_ids(loaded: Loaded) -> set[str]:
    return {n.id for result in loaded.results.values() for n in result.nodes}


def orphaned_notes(annotations: list[Annotation], view_ids: set[str], node_ids: set[str],
                   ) -> tuple[dict[str, list[Annotation]], list[Annotation]]:
    """Notes whose target no longer exists, so a page can show them instead of hiding them.

    Returns (step notes by the existing view they belong to, notes of removed views).
    A node id is `<view id>/<node name>` and view ids may contain `/`, so a step note
    belongs to the longest existing view id that prefixes it, with one exception: a note
    the importer marked "view removed" belongs to a removed view even when a shorter
    existing view id also prefixes it (view `A/B` removed: `A/B/X` is not view A's step).
    A view note belongs to removed views when its view does not exist."""
    by_view: dict[str, list[Annotation]] = {}
    removed: list[Annotation] = []
    for a in annotations:
        if a.target_kind == TargetKind.VIEW:
            if a.target_id not in view_ids:
                removed.append(a)
            continue
        if a.target_id in node_ids:
            continue
        owners = [v for v in view_ids if a.target_id.startswith(v + "/")]
        if not owners or (a.stale and a.stale_reason == VIEW_REMOVED):
            removed.append(a)
        else:
            by_view.setdefault(max(owners, key=len), []).append(a)
    return by_view, removed


def _graph_elements(result: ParseResult, descriptions: list[NodeDescription]) -> list[dict]:
    """The generator's elements plus the URLs the browser needs (kept out of the generator,
    which knows nothing about routes)."""
    elements = view_elements(result, descriptions)
    for element in elements:
        data = element["data"]
        if "source" in data or data["node_type"] == MISSING_TYPE:
            continue
        data["panel_url"] = node_url(result.view.id, data["id"])
        if data["resolved_view"]:
            data["view_url"] = view_url(data["resolved_view"])
    return elements


# ---------------------------------------------------------------- node panel (htmx fragment)

@router.get("/node", response_class=HTMLResponse)
def node_panel(request: Request, view: str, node: str,
               store: Store | None = Depends(get_existing_store)):
    context = node_context(store, view, node)
    if isinstance(context, str):
        return not_found(request, context, fragment=True)
    return templates.TemplateResponse(request, "_node_panel.html", context)


def node_context(store: Store | None, view: str, node: str) -> dict | str:
    project = store.get_project() if store is not None else None
    if store is None or project is None:
        return "No project has been imported."
    loaded = load_project(store, project)
    result = loaded.results.get(view)
    found: Node | None = None
    for candidate in result.nodes if result else []:
        if candidate.id == node:
            found = candidate  # a repeated id: the last definition wins, as in the parser
    if result is None or found is None:
        return f"There is no step {node} in view {view}."
    resolved = next((ds.resolved_view_id for ds in result.data_sources if ds.id == found.id), None)
    return {
        "view": result.view, "node": found,
        "description": describe_node(result, found, loaded.estate),
        "warnings": [w for w in result.warnings if w.node_id == found.id],
        "resolved_view": resolved,
        "note": store.get_annotation(found.id, TargetKind.NODE),
        "form": None, "form_error": None, "saved": False,
    }


def not_found(request: Request, message: str, fragment: bool = False) -> Response:
    if fragment:
        # 200, not 404: htmx swaps only 2xx responses, and the panel must say what went wrong.
        return HTMLResponse(f'<p class="callout bad">{escape(message)}</p>', status_code=200)
    return templates.TemplateResponse(request, "error.html", {
        "title": "Not found", "message": message, "project": None}, status_code=404)
