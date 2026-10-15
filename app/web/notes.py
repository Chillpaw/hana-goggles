"""Notes and sign-off: saving a view's notes (Notes tab) and a step's notes (node panel).

`POST /notes?view=<view id>` redirects back to the view's Notes tab.
`POST /node/notes?view=<view id>&node=<node id>` answers with the refreshed node panel
(an htmx swap). Validation errors are 400 with the form re-rendered, nothing saved;
`viewgraph.js` swaps a 400 into the panel. Bodies are parsed by hand, like /import:
python-multipart is not a dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.ir.models import Annotation, TargetKind
from app.ir.store import Store
from app.web.deps import get_existing_store
from app.web.routes import (
    MAX_NOTE_CHARS,
    SIGNOFF_VALUES,
    node_context,
    not_found,
    view_context,
    templates,
    view_url,
)

NOTE_FIELDS = {"purpose_text": "Purpose", "owner": "Owner", "notes": "Notes"}

router = APIRouter()


@dataclass
class NoteForm:
    """A submitted notes form. A field the form did not send is None (kept as stored);
    a field sent empty is "" (cleared)."""

    values: dict[str, str | None]
    error: str | None


async def _read_note_form(request: Request) -> NoteForm:
    form = parse_qs((await request.body()).decode("utf-8", "replace"), keep_blank_values=True)
    values: dict[str, str | None] = {
        name: (form[name][0] if name in form else None)
        for name in (*NOTE_FIELDS, "signoff_status")}
    errors = []
    status = values["signoff_status"]
    if status is not None and status not in SIGNOFF_VALUES:
        errors.append(f"{status[:40]!r} is not a sign-off status; choose one of "
                      f"{', '.join(SIGNOFF_VALUES)}.")
    for name, label in NOTE_FIELDS.items():
        text = values[name]
        if text is not None and len(text) > MAX_NOTE_CHARS:
            errors.append(f"{label} is {len(text)} characters long; the limit is "
                          f"{MAX_NOTE_CHARS}.")
    return NoteForm(values, " ".join(errors) or None)


def _merged(existing: Annotation | None, target_id: str, kind: TargetKind,
            values: dict[str, str | None]) -> Annotation:
    base = existing or Annotation(target_id=target_id, target_kind=kind)
    update = {k: v for k, v in values.items() if v is not None}
    return Annotation.model_validate({**base.model_dump(), **update})


@router.post("/notes", response_class=HTMLResponse)
async def post_view_notes(request: Request, view: str,
                          store: Store | None = Depends(get_existing_store)):
    form = await _read_note_form(request)
    if store is None or store.get_project() is None or view not in store.view_hashes():
        return not_found(request, f"There is no view {view} in this project.")
    if form.error:
        context = view_context(store, view, "notes")
        if isinstance(context, str):
            return not_found(request, context)
        context.update(form=form.values, form_error=form.error)
        return templates.TemplateResponse(request, "view.html", context, status_code=400)
    existing = store.get_annotation(view, TargetKind.VIEW)
    store.save_annotation(_merged(existing, view, TargetKind.VIEW, form.values))
    return RedirectResponse(view_url(view) + "?tab=notes", status_code=303)


@router.post("/node/notes", response_class=HTMLResponse)
async def post_node_notes(request: Request, view: str, node: str,
                          store: Store | None = Depends(get_existing_store)):
    form = await _read_note_form(request)
    context = node_context(store, view, node)
    if isinstance(context, str) or store is None:
        return not_found(request, str(context), fragment=True)
    if form.error:
        context.update(form=form.values, form_error=form.error)
        return templates.TemplateResponse(request, "_node_panel.html", context, status_code=400)
    saved = store.save_annotation(_merged(context["note"], node, TargetKind.NODE, form.values))
    context.update(note=saved, saved=True)
    return templates.TemplateResponse(request, "_node_panel.html", context)
