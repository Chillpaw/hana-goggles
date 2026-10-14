"""Cross-view dependency resolution: match each DataSource to a view in the estate or a leaf.

Matching rule (a ruling to confirm with the M4 audit): only calc-view sources resolve
internally, keyed by the last `resource_uri` segment (else the source name) against
`View.id`; several candidates are narrowed by package (the URI's first segment against
`package_path` with "/" read as "."). The package tie-break only decides internal vs
leaf; the estate keeps one definition per bare view id. The result is independent of
input order.
"""
from __future__ import annotations

from collections import defaultdict

from app.ir.graph import order_and_cycles
from app.ir.models import (
    DataSource, DataSourceKind, Estate, IRWarning, LeafKind, LeafSource, ParseResult, ParseStatus,
    Severity, ViewDependency,
)

ROOT_PACKAGE = "(root)"


def resolve_dependencies(results: list[ParseResult]) -> Estate:
    """Build the Estate and set `DataSource.resolved_view_id` on internal matches.
    Earlier resolutions on the passed results are cleared first, so re-runs leave nothing stale."""
    for result in results:
        for ds in result.data_sources:
            ds.resolved_view_id = None
    ordered = sorted(results, key=_sort_key)
    by_id: dict[str, list[ParseResult]] = defaultdict(list)
    for result in ordered:
        by_id[result.view.id].append(result)

    warnings: list[IRWarning] = []
    for view_id, same in by_id.items():
        if len(same) > 1:
            packages = ", ".join(_package_label(r.view.package_path) for r in same)
            warnings.append(IRWarning(
                view_id=view_id, code="DUPLICATE_VIEW_ID", severity=Severity.ERROR,
                message=(f"view id {view_id!r} is defined {len(same)} times (packages: {packages}); "
                         f"dependencies taken from the copy in {_package_label(same[0].view.package_path)}")))

    dependencies: list[ViewDependency] = []
    leaves: dict[str, LeafSource] = {}
    for view_id, same in by_id.items():
        result = same[0]  # the first in sorted order supplies a duplicate id's dependencies
        if not result.nodes:  # failed view: listed, but no dependencies
            continue
        for ds in result.data_sources:
            producer, internal = _resolve(view_id, ds, by_id, leaves, warnings)
            dependencies.append(ViewDependency(consumer=view_id, producer=producer,
                                               data_source_id=ds.id, internal=internal))

    for leaf in leaves.values():
        leaf.used_by = sorted(set(leaf.used_by))
    estate = Estate(
        views=sorted(by_id),
        dependencies=sorted(dependencies, key=lambda d: (d.consumer, d.data_source_id)),
        leaf_sources=sorted(leaves.values(), key=lambda leaf: leaf.id),
        warnings=warnings,
    )
    estate.deploy_order, estate.cycles = order_and_cycles(estate)
    for members in estate.cycles:
        estate.warnings.append(IRWarning(
            code="CYCLE", severity=Severity.ERROR,
            message=f"views depend on each other in a cycle: {', '.join(members)}"))
    estate.warnings.sort(key=lambda w: (w.view_id or "", w.code, w.message))
    return estate


def _resolve(view_id: str, ds: DataSource, by_id: dict[str, list[ParseResult]],
             leaves: dict[str, LeafSource], warnings: list[IRWarning]) -> tuple[str, bool]:
    """Return (producer, internal) for one data source, recording leaves and warnings."""
    if ds.kind is DataSourceKind.CALC_VIEW:
        key = _key(ds)
        candidates = by_id.get(key, [])
        if len(candidates) > 1:
            package = _uri_package(ds.resource_uri)
            candidates = [r for r in candidates if package is not None
                          and (r.view.package_path or "").replace("/", ".") == package]
            if len(candidates) != 1:
                warnings.append(IRWarning(
                    view_id=view_id, node_id=ds.id, code="AMBIGUOUS_DEPENDENCY",
                    message=(f"view {view_id!r} reads {key!r}, which matches several views "
                             f"and no single one by package; treated as unresolved")))
                return _leaf(leaves, f"view:{key}", LeafKind.EXTERNAL_VIEW, None, key, view_id), False
        if candidates:
            ds.resolved_view_id = key
            return key, True
        warnings.append(IRWarning(
            view_id=view_id, node_id=ds.id, code="UNRESOLVED_VIEW_DEPENDENCY",
            message=f"view {view_id!r} reads {key!r}, which is not in this folder"))
        return _leaf(leaves, f"view:{key}", LeafKind.EXTERNAL_VIEW, None, key, view_id), False
    if ds.kind is DataSourceKind.TABLE:
        return _leaf(leaves, f"table:{_qualified(ds)}", LeafKind.TABLE, ds.schema_name, ds.name, view_id), False
    if ds.kind is DataSourceKind.TABLE_FUNCTION:
        return _leaf(leaves, f"table_function:{_qualified(ds)}", LeafKind.TABLE_FUNCTION,
                     ds.schema_name, ds.name, view_id), False
    # unknown (and CDS, which no parser produces yet): one leaf per consuming data source
    return _leaf(leaves, f"unknown:{ds.id}", LeafKind.UNKNOWN, ds.schema_name, ds.name, view_id), False


def _leaf(leaves: dict[str, LeafSource], leaf_id: str, kind: LeafKind, schema_name: str | None,
          name: str, used_by: str) -> str:
    leaf = leaves.setdefault(leaf_id, LeafSource(id=leaf_id, kind=kind, schema_name=schema_name, name=name))
    leaf.used_by.append(used_by)
    return leaf_id


def _key(ds: DataSource) -> str:
    # Last resourceUri segment, else the source name, else the DataSource's own XML id.
    segment = (ds.resource_uri or "").strip().rpartition("/")[2]
    return segment or ds.name or ds.id.rpartition("/")[2]


def _uri_package(uri: str | None) -> str | None:
    """The package segment of "/pkg/calculationviews/NAME", or None if the URI has none."""
    parts = [p for p in (uri or "").strip().split("/") if p]
    return parts[0] if len(parts) >= 3 else None


def _qualified(ds: DataSource) -> str:
    return f"{ds.schema_name}.{ds.name}" if ds.schema_name else ds.name


def _package_label(package_path: str | None) -> str:
    return package_path or ROOT_PACKAGE


def _sort_key(result: ParseResult) -> tuple[str, bool, str, str]:
    # A failed view never beats a parsed one for a duplicate id.
    v = result.view
    return (v.id, v.parse_status is ParseStatus.FAILED, v.package_path or "", v.file_hash)
