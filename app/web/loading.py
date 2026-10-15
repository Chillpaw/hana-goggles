"""Loading a stored project for a page: summaries, results and the estate rebuilt per
request (`resolve_dependencies(store.load_all_results())`, milliseconds for a few hundred
views). Shared by every route module."""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from app.enrich.deps import _sort_key as estate_preference
from app.enrich.deps import resolve_dependencies
from app.ir.models import Estate, ParseResult, Project, ViewSummary
from app.ir.store import Store


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


def load_project(store: Store, project: Project) -> Loaded:
    """Summaries, results (one per view id) and the estate rebuilt from them.
    Raises OutdatedDataError when a stored row no longer validates."""
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
