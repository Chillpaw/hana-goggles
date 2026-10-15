"""Parser entry point. Loads XML safely, routes by view type, never raises on input."""
from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

from app.ir.models import (
    DataCategory, IRWarning, ParseResult, ParseStatus, Severity, View, ViewType,
)
from app.parsers import xmlutil as x
from app.parsers.graphical import parse_graphical


def parse_file(path: Path, *, package_path: str | None = None) -> ParseResult:
    try:
        data = path.read_bytes()
    except OSError as exc:
        return _failed(_stem(path.name), "", package_path, "READ_ERROR", str(exc))
    return parse_bytes(data, file_name=path.name, package_path=package_path)


def parse_bytes(data: bytes, *, file_name: str, package_path: str | None = None,
                unknown: Counter | None = None) -> ParseResult:
    """`unknown`, when given, collects (parent, child) pairs of UNKNOWN_ELEMENT warnings."""
    stem = _stem(file_name)
    file_hash = hashlib.sha256(data).hexdigest()
    try:
        return _parse(data, stem, file_hash, package_path, unknown)
    except Exception as exc:  # the parser must never raise on an input file
        return _failed(stem, file_hash, package_path, "PARSER_CRASH", f"{type(exc).__name__}: {exc}")


def finalize(result: ParseResult) -> ParseResult:
    nodes = result.nodes
    understood = sum(1 for n in nodes if n.understood)
    result.view.coverage_pct = round(100 * understood / len(nodes), 1) if nodes else 0.0
    severities = {w.severity for w in result.warnings}
    if not nodes:
        result.view.parse_status = ParseStatus.FAILED
    elif severities & {Severity.WARNING, Severity.ERROR}:
        result.view.parse_status = ParseStatus.PARTIAL
    else:
        result.view.parse_status = ParseStatus.OK
    return result


def _parse(data: bytes, stem: str, file_hash: str, package_path: str | None,
           unknown: Counter | None = None) -> ParseResult:
    root, _error, _line = x.load(data)
    if root is None:
        # Fixed message: libxml2's wording and line numbers vary between lxml builds,
        # which would make golden files machine-dependent. The detail is still useful
        # interactively, so M5's UI can re-run x.load() to show it.
        return _failed(stem, file_hash, package_path, "XML_SYNTAX", "file is not well-formed XML")
    if x.local(root) != "scenario":
        return _failed(stem, file_hash, package_path, "NOT_A_SCENARIO",
                       f"root element is <{x.local(root)}>, expected <scenario>")

    view_id = root.get("id") or stem
    types = {x.xsi_type_name(cv) for cv in x.descendants(root, "calculationView")}
    view = View(
        id=view_id,
        name=view_id,
        package_path=package_path,
        view_type=ViewType.SCRIPTED if "SqlScriptView" in types else ViewType.GRAPHICAL,
        data_category=_category(root.get("dataCategory")),
        schema_version=root.get("schemaVersion"),
        file_hash=file_hash,
        parse_status=ParseStatus.OK,
        coverage_pct=0.0,
    )
    # M2 routes scripted views to app.parsers.scripted; until then SqlScriptView nodes
    # become opaque inside the graphical front end.
    return finalize(parse_graphical(root, view, unknown=unknown))


def _failed(stem: str, file_hash: str, package_path: str | None, code: str, message: str,
            line: int | None = None) -> ParseResult:
    view = View(id=stem, name=stem, package_path=package_path, view_type=ViewType.UNKNOWN,
                data_category=DataCategory.UNKNOWN, file_hash=file_hash,
                parse_status=ParseStatus.FAILED, coverage_pct=0.0)
    warning = IRWarning(view_id=stem, code=code, message=message, severity=Severity.ERROR, line=line)
    return ParseResult(view=view, warnings=[warning])


def _category(value: str | None) -> DataCategory:
    try:
        return DataCategory(value or "")
    except ValueError:
        return DataCategory.UNKNOWN


def _stem(file_name: str) -> str:
    return Path(file_name).name.split(".")[0]
