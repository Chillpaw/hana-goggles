"""Import and re-import a folder of views into the store; mark annotations stale.

Views are matched by view id. A file whose hash is unchanged is skipped; a changed one
replaces the stored result and marks annotations stale where their target changed:
the view annotation ("view file changed"), node annotations whose node `raw` hash
changed ("node changed") or whose node disappeared ("node removed"). Views no longer in
the folder are deleted, and their annotations kept but marked stale ("view removed"),
unless the scan could not read part of the folder (SCAN_DIR_UNREADABLE): then nothing is
removed and a REMOVALS_SKIPPED warning says how many views were kept.

An unchanged file is still re-parsed by the scan; if the new result differs from the
stored JSON (a parser fix, an IR model change, or the file moved package) the row is
rewritten and counted as `reparsed`. The file did not change, so annotations stay valid,
except node annotations whose node no longer exists ("node removed").
The whole import is one transaction; each view is stored in a savepoint, so a view the
database refuses (sqlite3.IntegrityError) gets a VIEW_NOT_STORED error and the import
carries on. The report (minus the estate) is stored on the project for the web app.
Dependencies are recomputed after every import and returned, never stored.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from pydantic import BaseModel, Field

from app.enrich.deps import resolve_dependencies
from app.ingest.scan import ScannedView, scan_folder
from app.ir.models import Estate, IRWarning, ParseStatus, Severity, TargetKind
from app.ir.store import Store, node_raw_hashes

VIEW_FILE_CHANGED = "view file changed"
NODE_CHANGED = "node changed"
NODE_REMOVED = "node removed"
VIEW_REMOVED = "view removed"

REMOVALS_SKIPPED = "REMOVALS_SKIPPED"
VIEW_NOT_STORED = "VIEW_NOT_STORED"


class ImportReport(BaseModel):
    added: int = 0
    changed: int = 0
    unchanged: int = 0
    reparsed: int = 0  # same file, different parse result (parser or model changed, or moved)
    removed: int = 0
    stale_annotations: int = 0  # annotations newly marked stale by this import
    failed: int = 0  # stored views from this folder whose parse failed
    not_stored: int = 0  # views the database refused (VIEW_NOT_STORED warning each)
    estate: Estate = Field(default_factory=Estate)
    # scan problems, duplicate ids, views not stored, removals skipped
    warnings: list[IRWarning] = Field(default_factory=list)


def import_folder(store: Store, folder: Path, name: str | None = None) -> ImportReport:
    """Raises NotADirectoryError for a bad folder (a usage error); never for a bad file."""
    report = ImportReport()
    scanned = _unique(scan_folder(folder, report.warnings), report.warnings)
    scan_incomplete = any(w.code == "SCAN_DIR_UNREADABLE" for w in report.warnings)
    folder = Path(folder).resolve()

    with store.transaction():
        stored_hashes = store.view_hashes()
        stored_locations = store.view_locations()
        for item in scanned:
            try:
                with store.transaction():  # a savepoint: a failure undoes this view only
                    outcome, stale = _store_view(store, item, stored_hashes, stored_locations)
            except sqlite3.IntegrityError as exc:
                report.not_stored += 1
                report.warnings.append(_not_stored(item, exc, item.result.view.id in stored_hashes))
                continue
            setattr(report, outcome, getattr(report, outcome) + 1)
            report.stale_annotations += stale
            if item.result.view.parse_status is ParseStatus.FAILED:
                report.failed += 1

        present = {item.result.view.id for item in scanned}
        missing = sorted(set(stored_hashes) - present)
        if missing and scan_incomplete:
            # Part of the folder could not be read: a missing view may only be unreadable
            # right now (permissions, a network drive), so nothing is removed or staled.
            report.warnings.append(IRWarning(
                code=REMOVALS_SKIPPED, severity=Severity.WARNING,
                message=(f"{len(missing)} stored view{'' if len(missing) == 1 else 's'} not "
                         "found in this scan kept, because part of the folder could not be "
                         "read (SCAN_DIR_UNREADABLE); re-import once it is readable to remove "
                         "views that are really gone")))
            missing = []
        for view_id in missing:
            node_ids = sorted(store.node_hashes(view_id))
            store.delete_view(view_id)
            report.stale_annotations += (
                store.mark_stale([view_id], VIEW_REMOVED, TargetKind.VIEW)
                + store.mark_stale(node_ids, VIEW_REMOVED, TargetKind.NODE))
            report.removed += 1

        previous = store.get_project()
        project_name = name or (previous.name if previous else None) or folder.name
        store.set_project(project_name, str(folder))
        store.set_last_import(report.model_dump_json(exclude={"estate"}))

    # Fresh copies from the store: resolve_dependencies sets resolved_view_id on these
    # objects only; the stored JSON is left as parsed.
    report.estate = resolve_dependencies(store.load_all_results())
    return report


def last_import(store: Store) -> ImportReport | None:
    """The stored report of the last import (its estate is empty: pages rebuild it).
    None before the first import; raises pydantic.ValidationError if it no longer
    validates."""
    text = store.get_last_import()
    return ImportReport.model_validate_json(text) if text is not None else None


def _store_view(store: Store, item: ScannedView, stored_hashes: dict[str, str],
                stored_locations: dict[str, str]) -> tuple[str, int]:
    """Store one scanned view. Returns (report counter to bump, annotations newly stale)."""
    view = item.result.view
    old_hash = stored_hashes.get(view.id)
    if old_hash is None:
        store.upsert_view(item)
        return "added", 0
    if old_hash != view.file_hash:
        return "changed", _replace_changed(store, item)
    # Compared as raw text: an old row may not validate against today's models.
    if store.raw_result_json(view.id) != item.result.model_dump_json():
        return "reparsed", _replace_reparsed(store, item)
    if stored_locations.get(view.id) != item.rel_path:
        store.upsert_view(item)  # renamed in place: same result, new rel_path
    return "unchanged", 0


def _not_stored(item: ScannedView, exc: sqlite3.IntegrityError, existed: bool) -> IRWarning:
    view_id = item.result.view.id
    kept = "the previously stored version is kept" if existed else "it is not in the project"
    return IRWarning(
        view_id=view_id, code=VIEW_NOT_STORED, severity=Severity.ERROR,
        message=f"view {view_id!r} from {item.rel_path} could not be stored ({exc}); {kept}")


def _replace_changed(store: Store, item: ScannedView) -> int:
    view_id = item.result.view.id
    old_nodes = store.node_hashes(view_id)
    new_nodes = node_raw_hashes(item.result.nodes)
    store.upsert_view(item)
    changed = [nid for nid, h in old_nodes.items() if nid in new_nodes and new_nodes[nid] != h]
    removed = [nid for nid in old_nodes if nid not in new_nodes]
    return (store.mark_stale([view_id], VIEW_FILE_CHANGED, TargetKind.VIEW)
            + store.mark_stale(sorted(changed), NODE_CHANGED, TargetKind.NODE)
            + store.mark_stale(sorted(removed), NODE_REMOVED, TargetKind.NODE))


def _replace_reparsed(store: Store, item: ScannedView) -> int:
    view_id = item.result.view.id
    old_nodes = store.node_hashes(view_id)
    new_nodes = {node.id for node in item.result.nodes}
    store.upsert_view(item)
    return store.mark_stale(sorted(set(old_nodes) - new_nodes), NODE_REMOVED, TargetKind.NODE)


def _unique(scanned: list[ScannedView], warnings: list[IRWarning]) -> list[ScannedView]:
    """Keep one file per view id, a parsed one before a failed one, then the first by
    rel_path (as the estate does); warn on the rest."""
    kept: dict[str, ScannedView] = {}
    dropped: dict[str, list[str]] = {}
    for item in sorted(scanned, key=_preference):
        view_id = item.result.view.id
        if view_id in kept:
            dropped.setdefault(view_id, []).append(item.rel_path)
        else:
            kept[view_id] = item
    for view_id, rel_paths in dropped.items():
        warnings.append(IRWarning(
            view_id=view_id, code="DUPLICATE_VIEW_ID", severity=Severity.ERROR,
            message=(f"view id {view_id!r} is defined in {len(rel_paths) + 1} files; "
                     f"stored {kept[view_id].rel_path}, skipped {', '.join(rel_paths)}")))
    return list(kept.values())


def _preference(item: ScannedView) -> tuple[bool, str]:
    return (item.result.view.parse_status is ParseStatus.FAILED, item.rel_path)
