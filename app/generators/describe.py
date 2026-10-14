"""Plain-English descriptions of a view's nodes: one headline plus detail sentences per node.

Reads only the IR (and the Estate built from IR). The wording is pinned by tests: change it
on purpose only. Anything the parser could not understand is said out loud, never dropped.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from app.ir.models import (
    ColumnKind, ColumnMapItem, DataSource, DataSourceKind, DataCategory, Estate, ExpressionLang, Expression,
    ExprNode, Node, NodeType, ParseResult,
)

NOT_UNDERSTOOD = "Not fully understood by the parser: see warnings and raw XML."
SPECIAL_JOIN = "HANA-specific join semantics: review before migrating."
CUBE_DETAIL = "CUBE: totals are computed at query time for whatever columns the consumer asks for."
NO_INPUT = "(no input)"
MISSING_INPUT = "(missing input)"

JOIN_PHRASES = {
    "inner": "Inner join",
    "leftOuter": "Left outer join",
    "rightOuter": "Right outer join",
    "fullOuter": "Full outer join",
    "referential": "Referential join",
    "textTable": "Text join",
}
CARDINALITY_PHRASES = {
    "CN_1": "many-to-one",
    "C1_1": "one-to-one",
    "C1_N": "one-to-many",
    "CN_N": "many-to-many",
}
AGGREGATION_VERBS = {
    "sum": "Sums",
    "min": "Takes the minimum of",
    "max": "Takes the maximum of",
    "count": "Counts",
    "avg": "Averages",
}


@dataclass(frozen=True)
class NodeDescription:
    node_id: str
    headline: str  # one sentence
    details: list[str] = field(default_factory=list)  # filters, calculated columns, constants, flags


# ---------------------------------------------------------------- expressions

# Binding strength, loosest first. An `if` rendered as `if … then … else …` binds loosest of all,
# so it is grouped whenever it is an operand.
_IF, _OR, _AND, _NOT, _CMP, _ADD, _MUL, _NEG, _ATOM = range(9)
_BINARY_PRECEDENCE = {
    "or": _OR, "and": _AND,
    "=": _CMP, "!=": _CMP, "<>": _CMP, "<": _CMP, ">": _CMP, "<=": _CMP, ">=": _CMP,
    "+": _ADD, "-": _ADD, "*": _MUL, "/": _MUL,
}


def render_expression(expr: Expression | None) -> str:
    """Readable text for an expression; unparsed (or SQL) text is shown verbatim and flagged."""
    if expr is None:
        return ""
    if expr.ast is None or expr.lang is ExpressionLang.SQL:
        return f"`{expr.text}` (not parsed)"
    return _render(expr.ast)[0]


def _render(node: ExprNode) -> tuple[str, int]:
    """Return (text, precedence of the text's outermost operator)."""
    value = node.value or ""
    if node.kind == "column":
        return value, _ATOM
    if node.kind == "number":
        return value, _ATOM
    if node.kind == "string":
        return "'" + value.replace("'", "''") + "'", _ATOM
    if node.kind == "param":
        return f"input parameter {value}", _ATOM
    if node.kind == "call":
        return _render_call(value, node.args)
    if node.kind == "unary":
        return _render_unary(value, node.args)
    if node.kind == "binary":
        return _render_binary(value, node.args)
    return value, _ATOM


def _render_call(name: str, args: list[ExprNode]) -> tuple[str, int]:
    if name == "if" and len(args) == 3:
        cond, then, other = (_render(a) for a in args)
        # A nested `if` in condition or then position is grouped; `else if …` reads as a chain.
        return (f"if {_group(cond, cond[1] == _IF)} then {_group(then, then[1] == _IF)} else {other[0]}",
                _IF)
    return f"{name}({', '.join(_render(a)[0] for a in args)})", _ATOM


def _render_unary(op: str, args: list[ExprNode]) -> tuple[str, int]:
    if not args:
        return op, _ATOM
    operand = args[0]
    text, prec = _render(operand)
    if op == "not":
        # Any binary operand is grouped for clarity: `not (A = 1)`, not `not A = 1`.
        return f"not {_group((text, prec), operand.kind == 'binary' or prec < _NOT)}", _NOT
    # Unary minus (or an unknown prefix operator): group anything that is not a plain atom.
    needs = operand.kind in ("binary", "unary") or prec < _NEG
    sep = " " if op[-1:].isalpha() else ""
    return f"{op}{sep}{_group((text, prec), needs)}", _NEG


def _render_binary(op: str, args: list[ExprNode]) -> tuple[str, int]:
    prec = _BINARY_PRECEDENCE.get(op, _ADD)
    parts = []
    for i, arg in enumerate(args):
        text, child = _render(arg)
        # Looser operands are grouped. At equal strength only the first operand may stay bare
        # (the AST is a left fold), and comparisons never chain.
        needs = child < prec or (child == prec and (i > 0 or prec == _CMP))
        parts.append(_group((text, child), needs))
    return f" {op} ".join(parts), prec


def _group(rendered: tuple[str, int], needed: bool) -> str:
    return f"({rendered[0]})" if needed else rendered[0]


# ---------------------------------------------------------------- nodes

def describe_view(result: ParseResult, estate: Estate | None = None) -> list[NodeDescription]:
    """Every node in data-flow order: topological over the view's edges, ties by node order,
    the output node last. A cycle or a dangling edge never stops the walk."""
    return [describe_node(result, n, estate) for n in _flow_order(result)]


def describe_node(result: ParseResult, node: Node, estate: Estate | None = None) -> NodeDescription:
    ctx = _Context(result)
    details: list[str] = []
    details.extend(f"Keeps rows where {render_expression(f.expression)}." for f in node.filters)
    details.extend(f"Adds {c.name} = {render_expression(c.expression)}."
                   for c in node.columns if c.expression is not None)

    t = node.node_type
    if t is NodeType.DATASOURCE:
        headline = _datasource(result, node, estate, details)
    elif t is NodeType.PROJECTION:
        headline = f"Takes {len(_plain_columns(node))} columns from {ctx.input_list(node)}."
    elif t is NodeType.JOIN:
        headline = _join(ctx, node, details)
    elif t is NodeType.UNION:
        headline = _union(ctx, node, details)
    elif t is NodeType.AGGREGATION:
        headline = _aggregation(node)
    elif t is NodeType.RANK:
        headline = "Ranks rows (partition and order logic not yet modelled)."
    elif t is NodeType.OUTPUT:
        attributes = sum(1 for c in node.columns if c.kind is ColumnKind.ATTRIBUTE)
        measures = sum(1 for c in node.columns if c.kind is ColumnKind.MEASURE)
        headline = f"Publishes {attributes} attributes and {measures} measures as the view's output."
        if result.view.data_category is DataCategory.CUBE:
            details.append(CUBE_DETAIL)
    elif t is NodeType.SCRIPT_STATEMENT:
        headline = "Runs a SQL script statement."
    else:  # opaque, or a node type added later without a template
        inputs = ctx.inputs(node)
        reading = f", reading {', '.join(inputs)}" if inputs else ""
        headline = f"Does something the parser does not recognise{reading}."

    if not node.understood or t in (NodeType.OPAQUE, NodeType.SCRIPT_STATEMENT):
        details.append(NOT_UNDERSTOOD)
    return NodeDescription(node_id=node.id, headline=headline, details=details)


class _Context:
    """Node names and incoming edges of one view."""

    def __init__(self, result: ParseResult):
        self.result = result
        self.names = {n.id: n.name for n in result.nodes}

    def name(self, node_id: str | None) -> str:
        if node_id is None:
            return MISSING_INPUT
        return self.names.get(node_id) or node_id.rpartition("/")[2]

    def incoming(self, node: Node):
        return [e for e in self.result.edges if e.to_node == node.id]

    def inputs(self, node: Node) -> list[str]:
        return [self.name(e.from_node) for e in self.incoming(node)]

    def input_list(self, node: Node) -> str:
        return ", ".join(self.inputs(node)) or NO_INPUT


def _plain_columns(node: Node):
    return [c for c in node.columns if c.expression is None]


def _datasource(result: ParseResult, node: Node, estate: Estate | None, details: list[str]) -> str:
    ds = next((d for d in result.data_sources if d.id == node.id), None)
    if ds is None:
        return f"Reads source {node.name} (unknown kind)."
    if ds.kind is DataSourceKind.TABLE:
        return f"Reads table {_qualified(ds)}."
    if ds.kind is DataSourceKind.TABLE_FUNCTION:
        return f"Reads table function {_qualified(ds)}."
    if ds.kind is DataSourceKind.CDS:
        return f"Reads CDS entity {_qualified(ds)}."
    if ds.kind is DataSourceKind.CALC_VIEW:
        internal = ds.resolved_view_id is not None or (estate is not None and any(
            d.internal for d in estate.dependencies
            if d.consumer == result.view.id and d.data_source_id == ds.id))
        if internal:
            details.append("Defined in this project.")
        elif estate is not None:
            details.append("Not in this project (external).")
        # No estate and no resolution: say nothing either way rather than guess.
        return f"Reads calculation view {ds.name}."
    return f"Reads source {ds.name} (unknown kind)."


def _qualified(ds: DataSource) -> str:
    return f"{ds.schema_name}.{ds.name}" if ds.schema_name else ds.name


def _join(ctx: _Context, node: Node, details: list[str]) -> str:
    spec = node.join
    inputs = ctx.inputs(node)
    fallback = inputs + [MISSING_INPUT] * (2 - len(inputs))
    if spec is None:
        return f"Join (unknown) of {fallback[0]} and {fallback[1]}."
    phrase = JOIN_PHRASES.get(spec.join_type, f"Join ({spec.join_type})")
    left = ctx.name(spec.left_node) if spec.left_node else fallback[0]
    right = ctx.name(spec.right_node) if spec.right_node else fallback[1]
    columns = [c.column for c in spec.conditions]
    on = f" on {', '.join(columns)}" if columns else ""
    if not columns:
        details.append("No join columns were found.")
    cardinality = ""
    if spec.cardinality:
        label = CARDINALITY_PHRASES.get(spec.cardinality, f"cardinality {spec.cardinality}")
        cardinality = f" ({label})"
    if spec.special:
        details.append(SPECIAL_JOIN)
    return f"{phrase} of {left} and {right}{on}{cardinality}."


def _union(ctx: _Context, node: Node, details: list[str]) -> str:
    for e in ctx.incoming(node):
        source = ctx.name(e.from_node)
        details.extend(_constant(item, source) for item in e.column_map
                       if item.null or item.constant is not None)
    return f"Stacks rows from {ctx.input_list(node)}."


def _constant(item: ColumnMapItem, source: str) -> str:
    if item.null:
        return f"{item.target} is empty (null) for rows from {source}."
    value = (item.constant or "").replace("'", "''")
    return f"{item.target} is '{value}' for rows from {source}."


def _aggregation(node: Node) -> str:
    keys: list[str] = []
    clauses: dict[str, list[str]] = {}  # verb -> columns, in first-seen order
    for c in _plain_columns(node):
        if c.kind is ColumnKind.MEASURE or c.aggregation is not None:
            clauses.setdefault(_verb(c.aggregation), []).append(c.name)
        else:
            keys.append(c.name)
    parts = []
    for verb, names in clauses.items():
        if verb.startswith("using "):
            parts.append(f"Aggregates {', '.join(names)} {verb}")
        else:
            parts.append(f"{verb} {', '.join(names)}")
    by = ", ".join(keys)
    if not parts:
        return f"Groups by {by}." if keys else "Aggregates rows (no columns listed)."
    return "; ".join(parts) + (f" by {by}." if keys else ".")


def _verb(aggregation: str | None) -> str:
    if not aggregation:
        return "using an unstated method"
    return AGGREGATION_VERBS.get(aggregation.lower(), f"using {aggregation}")


def _flow_order(result: ParseResult) -> list[Node]:
    index = {n.id: i for i, n in enumerate(result.nodes)}
    outputs = [n for n in result.nodes if n.node_type is NodeType.OUTPUT]
    output_ids = {n.id for n in outputs}
    indegree = {n.id: 0 for n in result.nodes if n.id not in output_ids}
    children: dict[str, list[str]] = {node_id: [] for node_id in indegree}
    for e in result.edges:
        if e.from_node in indegree and e.to_node in indegree:
            children[e.from_node].append(e.to_node)
            indegree[e.to_node] += 1

    ready = [index[i] for i, d in indegree.items() if d == 0]
    heapq.heapify(ready)
    done: set[str] = set()
    order: list[Node] = []
    while len(order) < len(indegree):
        if not ready:  # a cycle: release its earliest member and carry on
            heapq.heappush(ready, min(index[i] for i in indegree if i not in done))
        node = result.nodes[heapq.heappop(ready)]
        if node.id in done:
            continue
        done.add(node.id)
        order.append(node)
        for child in children[node.id]:
            indegree[child] -= 1
            if indegree[child] == 0 and child not in done:
                heapq.heappush(ready, index[child])
    return order + outputs
