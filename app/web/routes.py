"""Page routes: import form, views list, view page (tabs) and the node panel fragment.

Every page reads the stored IR and rebuilds the estate per request
(`resolve_dependencies(store.load_all_results())`, milliseconds for a few hundred views).
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
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from pydantic import ValidationError

from app.enrich.deps import _sort_key as estate_preference
from app.enrich.deps import resolve_dependencies
from app.generators.describe import NodeDescription, describe_node, describe_view, render_expression
from app.generators.lineage import MISSING_TYPE, view_elements
from app.ingest.importer import import_folder
from app.ir.graph import downstream, upstream
from app.ir.models import Estate, Node, ParseResult, Project, ViewSummary
from app.ir.store import Store, StoreVersionError
from app.web.deps import get_existing_store

TEMPLATES_DIR = Path(__file__).parent / "templates"
TABS = {"graph": "Graph", "steps": "Steps", "columns": "Columns", "warnings": "Warnings",
        "raw": "Raw XML"}

router = APIRouter()


# ---------------------------------------------------------------- template helpers

def view_url(view_id: str) -> str:
    return "/views/" + quote(view_id, safe="")


def node_url(view_id: str, node_id: str) -> str:
    return "/node?" + urlencode({"view": view_id, "node": node_id}, quote_via=quote)


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
templates.env.globals.update(view_url=view_url, node_url=node_url, column_type=column_type,
                             render_expression=render_expression, tabs=TABS)


# ---------------------------------------------------------------- loading and errors

class OutdatedDataError(Exception):
    """A stored row does not validate against today's IR models."""

    def __init__(self, project: Project | None):
        super().__init__("stored data is from an older version")
        self.project = project


@dataclass
class Loaded:
    project: Project
    summaries: list[ViewSummary]
    results: dict[str, ParseResult]
    estate: Estate


def _load(store: Store, project: Project) -> Loaded:
    try:
        summaries = store.list_views()
        results = store.load_all_results()
    except ValidationError as exc:
        raise OutdatedDataError(project) from exc
    estate = resolve_dependencies(results)  # sets resolved_view_id on these copies
    # One result per id, the copy the estate uses (the store's primary key makes repeats
    # impossible today; this keeps page and estate agreeing if that ever changes).
    by_id: dict[str, ParseResult] = {}
    for result in sorted(results, key=estate_preference):
        by_id.setdefault(result.view.id, result)
    return Loaded(project, summaries, by_id, estate)


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
}


@router.get("/views", response_class=HTMLResponse)
def views(request: Request, sort: str = "name", q: str = "",
          store: Store | None = Depends(get_existing_store)):
    project = store.get_project() if store is not None else None
    if store is None or project is None:
        return RedirectResponse("/", status_code=303)
    loaded = _load(store, project)
    producers, consumers = _direct_links(loaded.estate)

    rows = [{
        "id": s.id, "package": s.package_path, "view_type": str(s.view_type),
        "data_category": str(s.data_category), "node_count": s.node_count,
        "coverage_pct": s.coverage_pct, "parse_status": str(s.parse_status),
        "warning_count": s.warning_count,
        "depends": len(producers.get(s.id, ())), "usedby": len(consumers.get(s.id, ())),
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
    return templates.TemplateResponse(request, "views.html", {
        "project": project, "rows": rows, "sort_key": key, "descending": descending, "q": q,
        "total": len(loaded.summaries), "estate": estate,
        "internal_count": sum(1 for d in estate.dependencies if d.internal),
        "sort_columns": [("name", "View"), ("package", "Package"), ("type", "Type"),
                         ("category", "Category"), ("nodes", "Nodes"), ("coverage", "Coverage"),
                         ("status", "Parse"), ("warnings", "Warnings"),
                         ("depends", "Reads views"), ("usedby", "Used by")],
    })


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
    project = store.get_project() if store is not None else None
    if store is None or project is None:
        return _not_found(request, f"No project has been imported, so there is no view {view_id}.")
    loaded = _load(store, project)
    result = loaded.results.get(view_id)
    if result is None:
        return _not_found(request, f"There is no view {view_id} in this project.")
    estate = loaded.estate
    tab = tab if tab in TABS else "graph"
    descriptions = describe_view(result, estate)
    producers, consumers = _direct_links(estate)
    nodes_by_id = {n.id: n for n in result.nodes}
    steps = [(nodes_by_id[d.node_id], d) for d in descriptions if d.node_id in nodes_by_id]
    leaf_ids = {d.producer for d in estate.dependencies if d.consumer == view_id and not d.internal}

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
    }
    return templates.TemplateResponse(request, "view.html", context)


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
    project = store.get_project() if store is not None else None
    if store is None or project is None:
        return _not_found(request, "No project has been imported.", fragment=True)
    loaded = _load(store, project)
    result = loaded.results.get(view)
    found: Node | None = None
    for candidate in result.nodes if result else []:
        if candidate.id == node:
            found = candidate  # a repeated id: the last definition wins, as in the parser
    if result is None or found is None:
        return _not_found(request, f"There is no step {node} in view {view}.", fragment=True)
    resolved = next((ds.resolved_view_id for ds in result.data_sources if ds.id == found.id), None)
    return templates.TemplateResponse(request, "_node_panel.html", {
        "view": result.view, "node": found,
        "description": describe_node(result, found, loaded.estate),
        "warnings": [w for w in result.warnings if w.node_id == found.id],
        "resolved_view": resolved,
    })


def _not_found(request: Request, message: str, fragment: bool = False) -> Response:
    if fragment:
        # 200, not 404: htmx swaps only 2xx responses, and the panel must say what went wrong.
        return HTMLResponse(f'<p class="callout bad">{escape(message)}</p>', status_code=200)
    return templates.TemplateResponse(request, "error.html", {
        "title": "Not found", "message": message, "project": None}, status_code=404)
