"""Structural facts from one view file, for the audit (M4). Never raises on input.

Everything collected here is structure: element and attribute local names, namespace
URIs, `xsi:type` values, values of a fixed allow-list of schema-enum attributes, the
*shape* of resourceUri values, column-engine function names and counts. Names, ids,
descriptions, literals, expressions and parameter defaults are never collected.

UNKNOWN_ELEMENT pairs are computed with the graphical parser's own known-children sets,
walking the same places the parser checks (tests cross-check the totals).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from lxml import etree

from app.parsers import graphical as g
from app.parsers import xmlutil as x
from app.parsers.expressions import ExprParseError, parse_expression

OTHER = "<other>"

_ENUM_VALUE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")
_VERSION_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.]{0,39}$")
_XSI_TYPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}(?::[A-Za-z_][A-Za-z0-9_.-]{0,63})?$")
_FUNCTION_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,39}$")

# Root (scenario) attributes whose values are schema enums.
ROOT_ENUM_ATTRIBUTES = frozenset({
    "dataCategory", "schemaVersion", "calculationScenarioType", "outputViewType",
    "executionSemantic", "applyPrivilegeType", "visibility",
})
# (element local name, attribute local name) pairs whose values are schema enums,
# anywhere in the file. Values are reported only when they look like an enum token.
ENUM_ATTRIBUTES = frozenset({
    ("DataSource", "type"),
    ("calculationView", "joinType"), ("calculationView", "cardinality"),
    ("calculationView", "joinOrder"), ("calculationView", "filterExpressionLanguage"),
    ("viewAttribute", "aggregationType"), ("viewAttribute", "datatype"),
    ("measure", "aggregationType"), ("measure", "engineAggregation"), ("measure", "measureType"),
    ("measure", "expressionLanguage"), ("measure", "datatype"),
    ("calculatedViewAttribute", "expressionLanguage"), ("calculatedViewAttribute", "datatype"),
    ("keyCalculation", "expressionLanguage"), ("keyCalculation", "datatype"),
    ("filter", "expressionLanguage"),
    ("variable", "parameter"),
    ("variableProperties", "datatype"),
    ("valueDomain", "type"),
    ("selection", "type"),
    ("input", "emptyUnionBehavior"),
})
# resourceUri segments printed verbatim (fixed repository folder words); every other
# segment is replaced by its role.
URI_KEYWORDS = frozenset({
    "calculationviews", "analyticviews", "attributeviews", "tables", "views",
    "procedures", "functions", "tablefunctions", "hierarchies",
})

# Strip string literals, double-quoted identifiers and $$...$$ placeholders before
# looking for `name(`. An unterminated quote swallows the rest of the text (safe side).
_STRIP_RE = re.compile(r"""'(?:[^']|'')*'?|"(?:[^"]|"")*"?|\$\$[^$]*\$\$""")
_CALL_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")


@dataclass
class FileStructure:
    well_formed: bool = False
    scan_error: bool = False           # the walk itself failed (a bug, never an input problem)
    namespaces: Counter = field(default_factory=Counter)        # URI -> 1 per file
    elements: Counter = field(default_factory=Counter)          # local tag -> count
    children: Counter = field(default_factory=Counter)          # (parent, child) -> count
    attributes: Counter = field(default_factory=Counter)        # (tag, attr) -> count
    xsi_types: Counter = field(default_factory=Counter)         # as written -> count
    enum_values: Counter = field(default_factory=Counter)       # ("tag@attr", value) -> count
    resource_uri_shapes: Counter = field(default_factory=Counter)  # (where, shape) -> count
    expressions: Counter = field(default_factory=Counter)       # kind -> count
    functions_parsed: Counter = field(default_factory=Counter)
    functions_unparsed: Counter = field(default_factory=Counter)
    unknown_elements: Counter = field(default_factory=Counter)  # (parent, child) -> count


def scan_structure(data: bytes) -> FileStructure:
    result = FileStructure()
    try:
        root, _error, _line = x.load(data)
    except Exception:
        root = None
    if root is None:
        return result
    result.well_formed = True
    try:
        _walk(root, result)
        if x.local(root) == "scenario":
            _unknown_elements(root, result.unknown_elements)
    except Exception:  # never raise on an input file; the report counts this
        fresh = FileStructure(well_formed=True, scan_error=True)
        return fresh
    return result


def _elements(root: etree._Element):
    return (el for el in root.iter() if isinstance(el.tag, str))


def _walk(root: etree._Element, out: FileStructure) -> None:
    uris: set[str] = set()
    for el in _elements(root):
        tag = x.local(el)
        out.elements[tag] += 1
        parent = el.getparent()
        if parent is not None:
            out.children[(x.local(parent), tag)] += 1
        uris.update(uri for uri in el.nsmap.values() if uri)
        ns = etree.QName(el).namespace
        if ns:
            uris.add(ns)
        for name, value in el.attrib.items():
            qname = etree.QName(name)
            if qname.namespace:
                uris.add(qname.namespace)
            out.attributes[(tag, _attr_label(el, qname))] += 1
        xsi = el.get(f"{{{x.XSI_NS}}}type")
        if xsi is not None:
            out.xsi_types[xsi if _XSI_TYPE_RE.match(xsi) else OTHER] += 1
        _enum_values(el, tag, el is root, out.enum_values)
        _resource_uris(el, tag, parent, out.resource_uri_shapes)
        _expression(el, tag, parent, out)
    for uri in uris:
        out.namespaces[uri] += 1


def _attr_label(el: etree._Element, qname: etree.QName) -> str:
    if not qname.namespace:
        return qname.localname
    if qname.namespace == "http://www.w3.org/XML/1998/namespace":
        return f"xml:{qname.localname}"
    prefixes = sorted(p for p, uri in el.nsmap.items() if uri == qname.namespace and p)
    if prefixes:
        return f"{prefixes[0]}:{qname.localname}"
    return f"{{{qname.namespace}}}{qname.localname}"


def _enum_values(el: etree._Element, tag: str, is_root: bool, out: Counter) -> None:
    for name, value in el.attrib.items():
        qname = etree.QName(name)
        if qname.namespace:
            continue
        attr = qname.localname
        if is_root and attr in ROOT_ENUM_ATTRIBUTES:
            pattern = _VERSION_VALUE_RE if attr == "schemaVersion" else _ENUM_VALUE_RE
        elif (tag, attr) in ENUM_ATTRIBUTES:
            pattern = _ENUM_VALUE_RE
        else:
            continue
        out[(f"{tag}@{attr}", value if pattern.match(value) else OTHER)] += 1


def _resource_uris(el: etree._Element, tag: str, parent: etree._Element | None, out: Counter) -> None:
    if tag == "resourceUri":
        where = f"{x.local(parent)}/resourceUri" if parent is not None else "resourceUri"
        out[(where, uri_shape(el.text))] += 1
    for name, value in el.attrib.items():
        if etree.QName(name).localname == "resourceUri":
            out[(f"{tag}@resourceUri", uri_shape(value))] += 1


def uri_shape(uri: str | None) -> str:
    """`/pkg.a/calculationviews/VIEW` -> `/<package>/calculationviews/<name>`. No segment text
    survives except the fixed URI_KEYWORDS; empty segments (leading, trailing, doubled
    slashes) are kept so the shape stays faithful."""
    if uri is None or not uri.strip():
        return "<empty>"
    segments = uri.strip().split("/")
    filled = [i for i, s in enumerate(segments) if s]
    shaped = []
    for i, seg in enumerate(segments):
        if not seg:
            shaped.append("")
        elif i == filled[-1]:
            shaped.append("<namespace>::<name>" if "::" in seg else "<name>")
        elif seg in URI_KEYWORDS:
            shaped.append(seg)
        elif i == filled[0] and len(filled) >= 3:
            shaped.append("<package>")
        else:
            shaped.append("<segment>")
    return "/".join(shaped)


def _expression(el: etree._Element, tag: str, parent: etree._Element | None, out: FileStructure) -> None:
    if tag not in ("formula", "filter"):
        return
    text = (el.text or "").strip()
    if not text:
        return
    if tag == "formula":
        lang = parent.get("expressionLanguage") if parent is not None else None
        if lang is None and parent is not None and parent.getparent() is not None:
            lang = parent.getparent().get("expressionLanguage")
    else:
        lang = el.get("expressionLanguage") or (
            parent.get("filterExpressionLanguage") if parent is not None else None)
    if (lang or "").upper() == "SQL":
        # SQL text may hold unquoted column names followed by "(": count it, never mine it.
        out.expressions["sql"] += 1
        return
    try:
        ast = parse_expression(text)
    except ExprParseError:
        out.expressions["column_engine_unparsed"] += 1
        out.functions_unparsed.update(unparsed_function_names(text))
        return
    out.expressions["column_engine_parsed"] += 1
    stack = [ast]
    while stack:
        node = stack.pop()
        if node.kind == "call" and node.value:
            out.functions_parsed[node.value if _FUNCTION_NAME_RE.match(node.value) else OTHER] += 1
        stack.extend(node.args)


def unparsed_function_names(text: str) -> list[str]:
    stripped = _STRIP_RE.sub(" ", text)
    names = []
    for match in _CALL_RE.finditer(stripped):
        name = match.group(1).lower()
        names.append(name if _FUNCTION_NAME_RE.match(name) else OTHER)
    return names


def _unknown_elements(root: etree._Element, out: Counter) -> None:
    """Mirror of the places graphical.py calls _check_children, using its sets."""
    def check(el: etree._Element | None, known) -> None:
        if el is None:
            return
        for c in x.children(el):
            if x.local(c) not in known:
                out[(x.local(el), x.local(c))] += 1

    check(root, g.ROOT_CHILDREN)
    for var in x.children(x.child(root, "localVariables"), "variable"):
        check(var, g.VARIABLE_CHILDREN)
        check(x.child(var, "variableProperties"), g.VARIABLE_PROPERTIES_CHILDREN)
    for ds in x.children(x.child(root, "dataSources"), "DataSource"):
        check(ds, g.DATASOURCE_CHILDREN)
    wrapper = x.child(root, "calculationViews")
    for cv in x.children(wrapper if wrapper is not None else root, "calculationView"):
        if (x.xsi_type_name(cv) or "") in g.NODE_TYPES:
            check(cv, g.KNOWN_CALCVIEW_CHILDREN)
            for va in x.children(x.child(cv, "viewAttributes"), "viewAttribute"):
                check(va, g.VIEW_ATTRIBUTE_CHILDREN)
            for ca in x.children(x.child(cv, "calculatedViewAttributes"), "calculatedViewAttribute"):
                check(ca, g.CALCULATED_VIEW_ATTRIBUTE_CHILDREN)
        for inp in x.children(cv, "input"):
            check(inp, g.INPUT_CHILDREN)
    lm = x.child(root, "logicalModel")
    if lm is None:
        return
    check(lm, g.KNOWN_LOGICAL_MODEL_CHILDREN)
    for el in x.children(x.child(lm, "attributes"), "attribute"):
        check(el, g.ATTRIBUTE_CHILDREN)
    for el in x.children(x.child(lm, "baseMeasures"), "measure"):
        check(el, g.BASE_MEASURE_CHILDREN)
    for el in x.children(x.child(lm, "calculatedAttributes"), "calculatedAttribute"):
        check(el, g.CALCULATED_ATTRIBUTE_CHILDREN)
    for el in x.children(x.child(lm, "calculatedMeasures"), "measure"):
        check(el, g.CALCULATED_MEASURE_CHILDREN)
