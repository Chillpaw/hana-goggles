"""Structure-only audit report (M4): what the parser met in a folder, with no business content.

`collect` walks a folder (scan + parse + structure scan per file), `aggregate` turns the
per-file facts into a report dict (pure), and `format_text` / `format_json` print it.

Never printed: file names, paths, ids, names, column names, descriptions, literals,
expressions, warning messages, parameter defaults. Only counts, fixed codes, XML tag and
attribute names, namespace URIs, `xsi:type` values, allow-listed enum values,
resourceUri shapes and column-engine function names.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.ingest.scan import VIEW_SUFFIXES, find_view_files
from app.ir.models import IRWarning, ViewType
from app.parsers.audit_scan import FileStructure, scan_structure
from app.parsers.dispatch import parse_bytes

AUDIT_FORMAT_VERSION = 1
FORMATS = ("text", "json")
COVERAGE_BUCKETS = ("0", "1-49", "50-89", "90-99", "100")


@dataclass
class FileFacts:
    """One file's audit facts. `view_id` and `package_path` are used only to count
    duplicate ids; they never reach the report."""
    suffix: str
    parse_status: str
    view_type: str
    coverage_pct: float
    warning_codes: list[str] = field(default_factory=list)
    view_id: str = ""
    package_path: str | None = None
    structure: FileStructure | None = None   # None when the file could not be read


def collect(folder: Path) -> tuple[list[FileFacts], list[str]]:
    """Facts for every view file under `folder`, plus folder-scan warning codes.
    Raises NotADirectoryError for a bad folder (usage error); never raises on a file."""
    scan_warnings: list[IRWarning] = []
    root = Path(folder).resolve()
    paths = find_view_files(root, scan_warnings)
    facts = [file_facts(path, root) for path in paths]
    return facts, [w.code for w in scan_warnings]


def file_facts(path: Path, root: Path) -> FileFacts:
    rel = path.relative_to(root)
    package_path = rel.parent.as_posix() if rel.parent != Path(".") else None
    suffix = _suffix(path.name)
    try:
        data = path.read_bytes()
    except OSError:
        return FileFacts(suffix=suffix, parse_status="failed", view_type=ViewType.UNKNOWN.value,
                         coverage_pct=0.0, warning_codes=["READ_ERROR"], package_path=package_path)
    result = parse_bytes(data, file_name=path.name, package_path=package_path)
    return FileFacts(
        suffix=suffix,
        parse_status=result.view.parse_status.value,
        view_type=result.view.view_type.value,
        coverage_pct=result.view.coverage_pct,
        warning_codes=[w.code for w in result.warnings],
        view_id=result.view.id,
        package_path=package_path,
        structure=scan_structure(data),
    )


def _suffix(name: str) -> str:
    for suffix in VIEW_SUFFIXES:
        if name.lower().endswith(suffix):
            return name[-len(suffix):]   # as written, so case variants show up
    return "<other>"


def coverage_bucket(pct: float) -> str:
    if pct <= 0:
        return "0"
    if pct < 50:
        return "1-49"
    if pct < 90:
        return "50-89"
    if pct < 100:
        return "90-99"
    return "100"


def aggregate(facts: list[FileFacts], scan_warning_codes: list[str] | None = None) -> dict:
    """Pure: per-file facts in, a JSON-ready report out (only counts and structural words)."""
    structures = [f.structure for f in facts if f.structure is not None]

    def total(attr: str) -> Counter:
        counter: Counter = Counter()
        for s in structures:
            counter.update(getattr(s, attr))
        return counter

    histogram = Counter(coverage_bucket(f.coverage_pct) for f in facts)
    return {
        "audit_format_version": AUDIT_FORMAT_VERSION,
        "files": {
            "total": len(facts),
            "by_suffix": _plain(Counter(f.suffix for f in facts)),
            "parse_status": _plain(Counter(f.parse_status for f in facts)),
            "view_type": _plain(Counter(f.view_type for f in facts)),
            "unreadable": sum(1 for f in facts if f.structure is None),
            "not_well_formed": sum(1 for s in structures if not s.well_formed),
            "structure_scan_errors": sum(1 for s in structures if s.scan_error),
            "coverage_pct": sorted(f.coverage_pct for f in facts),
            "coverage_histogram": {bucket: histogram.get(bucket, 0) for bucket in COVERAGE_BUCKETS},
        },
        "warning_codes": _plain(Counter(code for f in facts for code in f.warning_codes)),
        "folder_scan_warning_codes": _plain(Counter(scan_warning_codes or [])),
        "duplicate_view_ids": _duplicates(facts),
        "scripted_views": sum(1 for f in facts if f.view_type == ViewType.SCRIPTED.value),
        "namespaces": _plain(total("namespaces")),
        "elements": _plain(total("elements")),
        "element_children": _nested(total("children")),
        "attributes": _nested(total("attributes")),
        "xsi_types": _plain(total("xsi_types")),
        "enum_values": _nested(total("enum_values")),
        "resource_uri_shapes": _nested(total("resource_uri_shapes")),
        "expressions": _plain(total("expressions")),
        "functions": {
            "parsed": _plain(total("functions_parsed")),
            "from_unparsed_text": _plain(total("functions_unparsed")),
        },
        "unknown_elements": _nested(total("unknown_elements")),
    }


def _duplicates(facts: list[FileFacts]) -> dict:
    """Counts only: how many ids are shared by more than one file, and how many of those
    span more than one package (Task 3 assumes ids are unique across the folder)."""
    packages: dict[str, list[str | None]] = {}
    for f in facts:
        if f.structure is not None and f.parse_status != "failed":
            packages.setdefault(f.view_id, []).append(f.package_path)
    groups = [p for p in packages.values() if len(p) > 1]
    return {
        "ids_shared": len(groups),
        "files_involved": sum(len(p) for p in groups),
        "ids_across_packages": sum(1 for p in groups if len(set(p)) > 1),
    }


def _plain(counter: Counter) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def _nested(counter: Counter) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for (outer, inner), count in counter.items():
        out.setdefault(outer, {})[inner] = count
    return {outer: dict(sorted(out[outer].items())) for outer in sorted(out)}


def format_json(report: dict) -> str:
    return json.dumps(report, sort_keys=True, indent=2) + "\n"


_TEXT_INTRO = (
    "CalcView audit: structure only.",
    "Contains counts, XML tag and attribute names, namespace URIs, xsi:type values,",
    "allow-listed enum values, resourceUri shapes and function names. No file names,",
    "paths, ids, names, descriptions, literals, expressions or warning messages.",
)


def format_text(report: dict) -> str:
    files = report["files"]
    dup = report["duplicate_view_ids"]
    lines = [*_TEXT_INTRO, f"Audit format version: {report['audit_format_version']}", ""]
    lines += ["== Files ==", f"total: {files['total']}",
              f"unreadable: {files['unreadable']}",
              f"not well-formed XML: {files['not_well_formed']}",
              f"structure scan errors: {files['structure_scan_errors']}",
              f"scripted views: {report['scripted_views']}"]
    lines += _section("Files by suffix", files["by_suffix"])
    lines += _section("Parse status", files["parse_status"])
    lines += _section("View type", files["view_type"])
    lines += ["", "== Coverage ==",
              "histogram: " + ", ".join(f"{b}: {files['coverage_histogram'][b]}" for b in COVERAGE_BUCKETS),
              "values (sorted): " + (", ".join(_pct(v) for v in files["coverage_pct"]) or "none")]
    lines += _section("Warning codes", report["warning_codes"])
    lines += _section("Folder scan warning codes", report["folder_scan_warning_codes"])
    lines += ["", "== Duplicate view ids ==",
              f"ids shared by more than one file: {dup['ids_shared']}",
              f"files involved: {dup['files_involved']}",
              f"ids shared across packages: {dup['ids_across_packages']}"]
    lines += _section("Namespace URIs (files using each)", report["namespaces"])
    lines += _section("Elements", report["elements"])
    lines += _nested_section("Element children (parent > child)", report["element_children"], " > ")
    lines += _nested_section("Attributes (element@attribute)", report["attributes"], "@")
    lines += _section("xsi:type values", report["xsi_types"])
    lines += _nested_section("Enum attribute values (element@attribute = value)",
                             report["enum_values"], " = ")
    lines += _nested_section("resourceUri shapes (where: shape)", report["resource_uri_shapes"], ": ")
    lines += _section("Expressions", report["expressions"])
    lines += _section("Column-engine functions (parsed expressions)", report["functions"]["parsed"])
    lines += _section("Column-engine functions (unparsed text; review before sharing)",
                      report["functions"]["from_unparsed_text"])
    lines += _nested_section("UNKNOWN_ELEMENT (parent > child)", report["unknown_elements"], " > ")
    return "\n".join(lines) + "\n"


def _section(title: str, counts: dict[str, int]) -> list[str]:
    body = [f"{key}: {count}" for key, count in counts.items()] or ["none"]
    return ["", f"== {title} ==", *body]


def _nested_section(title: str, nested: dict[str, dict[str, int]], sep: str) -> list[str]:
    body = [f"{outer}{sep}{inner}: {count}"
            for outer, inner_counts in nested.items() for inner, count in inner_counts.items()]
    return ["", f"== {title} ==", *(body or ["none"])]


def _pct(value: float) -> str:
    return f"{value:g}"


def run_audit(folder: Path, fmt: str = "text") -> str:
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}; expected one of {', '.join(FORMATS)}")
    facts, scan_codes = collect(folder)
    report = aggregate(facts, scan_codes)
    return format_json(report) if fmt == "json" else format_text(report)
