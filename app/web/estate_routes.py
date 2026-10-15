"""Estate map (M9a): the /estate page and the Mermaid downloads.

- `GET /estate`: every view and leaf source with their dependency edges (Cytoscape canvas
  drawn by `static/app/estate.js`), the deploy order, cycles and estate warnings.
- `GET /estate.mmd` (`?leaves=0` for views only) and `GET /view.mmd?view=<view id>`:
  Mermaid text as a `text/plain` attachment. The view id travels as a query parameter
  because ids may contain `/` (see the T7 ruling).

Like the other pages: `get_existing_store` (never creates a db), no project redirects to
the import form (a download answers 404), stored-data errors become the shared 409 page.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.generators.lineage import VIEW_KIND, estate_elements, estate_mermaid, view_mermaid
from app.ir.models import Annotation
from app.ir.store import Store
from app.web.deps import get_existing_store
from app.web.loading import Loaded, OutdatedDataError, load_project
from app.web.routes import templates, view_mmd_url, view_url

router = APIRouter()

# Estate warnings listed under the map (cycles have their own callouts at the top).
CYCLE_CODE = "CYCLE"
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
MAX_FILENAME = 100


@router.get("/estate", response_class=HTMLResponse)
def estate_page(request: Request, store: Store | None = Depends(get_existing_store)):
    loaded = _loaded(store)
    if loaded is None:
        return RedirectResponse("/", status_code=303)
    assert store is not None
    estate = loaded.estate
    elements = estate_elements(estate, loaded.summaries, _annotations(store, loaded))
    for element in elements:
        data = element["data"]
        if data.get("kind") == VIEW_KIND and "source" not in data:
            data["url"] = view_url(data["id"])
            data["mmd_url"] = view_mmd_url(data["id"])
    cycle_members = {m for members in estate.cycles for m in members}
    return templates.TemplateResponse(request, "estate.html", {
        "project": loaded.project, "estate": estate, "elements": elements,
        "cycle_members": cycle_members,
        "warnings": [w for w in estate.warnings if w.code != CYCLE_CODE],
        "internal_count": sum(1 for e in elements if e["data"].get("internal")),
        "edge_count": sum(1 for e in elements if "source" in e["data"]),
    })


@router.get("/estate.mmd")
def estate_mmd(leaves: bool = True, store: Store | None = Depends(get_existing_store)):
    loaded = _loaded(store)
    if loaded is None:
        return _no_project()
    name = safe_filename(loaded.project.name, "estate") + ("-estate" if leaves else "-estate-views")
    return mermaid_attachment(estate_mermaid(loaded.estate, include_leaves=leaves), name)


@router.get("/view.mmd")
def view_mmd(view: str, store: Store | None = Depends(get_existing_store)):
    loaded = _loaded(store)
    if loaded is None:
        return _no_project()
    result = loaded.results.get(view)
    if result is None:
        return PlainTextResponse(f"There is no view {view} in this project.", status_code=404)
    return mermaid_attachment(view_mermaid(result), safe_filename(view, "view"))


# ---------------------------------------------------------------- helpers

def _loaded(store: Store | None) -> Loaded | None:
    project = store.get_project() if store is not None else None
    if store is None or project is None:
        return None
    return load_project(store, project)


def _annotations(store: Store, loaded: Loaded) -> list[Annotation]:
    """All annotations; `estate_elements` keeps the view notes (a step note never counts
    as a view's sign-off)."""
    try:
        return store.list_annotations()
    except ValidationError as exc:
        raise OutdatedDataError(loaded.project) from exc


def _no_project() -> Response:
    return PlainTextResponse("No project has been imported.", status_code=404)


def safe_filename(text: str, fallback: str) -> str:
    """An ASCII file stem: runs of anything but letters, digits, `.`, `_`, `-` become `_`;
    no leading dots; at most MAX_FILENAME characters; `fallback` if nothing is left."""
    stem = _UNSAFE_FILENAME.sub("_", text).lstrip(".")[:MAX_FILENAME].strip("_")
    return stem or fallback


def mermaid_attachment(text: str, stem: str) -> Response:
    return PlainTextResponse(text, media_type="text/plain; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{stem}.mmd"'})
