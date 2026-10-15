"""Graph elements for the browser (one view's steps, or the whole estate) and Mermaid text.

Reads only the IR, the estate built from it, view summaries and annotations. Output order
is deterministic: for a view, nodes in IR order, then edges in IR order. Nothing is dropped silently: an edge that
names a node the view does not define gets a visible "missing" placeholder node.
"""
from __future__ import annotations

from collections import Counter

from app.generators.describe import NodeDescription
from app.ir.models import (
    Annotation, Estate, LeafSource, Node, NodeType, ParseResult, TargetKind, ViewSummary,
)

MISSING_TYPE = "missing"
MISSING_HEADLINE = "An edge refers to this node, but the view does not define it."


def view_elements(result: ParseResult, descriptions: list[NodeDescription]) -> list[dict]:
    """Cytoscape elements for one view.

    Node data: {id, label, node_type, understood, warning_count, headline, resolved_view}
    (`resolved_view` is the internal view a calc-view datasource reads, else None).
    Edge data: {id: "<from>-><to>", source, target, column_count}; a repeated pair gets
    "#2", "#3", ... appended so ids stay unique. A repeated node id appears once (the last
    definition wins, as in the parser), at the position of its first appearance."""
    headlines = {d.node_id: d.headline for d in descriptions}
    warning_counts = Counter(w.node_id for w in result.warnings if w.node_id)
    resolved = {ds.id: ds.resolved_view_id for ds in result.data_sources}

    nodes: dict[str, dict] = {}
    for node in result.nodes:
        nodes[node.id] = {
            "id": node.id,
            "label": node.name,
            "node_type": str(node.node_type),
            "understood": node.understood,
            "warning_count": warning_counts.get(node.id, 0),
            "headline": headlines.get(node.id, ""),
            "resolved_view": resolved.get(node.id),
        }

    edges: list[dict] = []
    seen: Counter[str] = Counter()
    for edge in result.edges:
        for end in (edge.from_node, edge.to_node):
            if end not in nodes:
                nodes[end] = {
                    "id": end,
                    "label": f"{end.rpartition('/')[2]} (missing)",
                    "node_type": MISSING_TYPE,
                    "understood": False,
                    "warning_count": warning_counts.get(end, 0),
                    "headline": MISSING_HEADLINE,
                    "resolved_view": None,
                }
        edge_id = f"{edge.from_node}->{edge.to_node}"
        seen[edge_id] += 1
        if seen[edge_id] > 1:
            edge_id = f"{edge_id}#{seen[edge_id]}"
        edges.append({"id": edge_id, "source": edge.from_node, "target": edge.to_node,
                      "column_count": len(edge.column_map)})

    return [{"data": n} for n in nodes.values()] + [{"data": e} for e in edges]


# ---------------------------------------------------------------- estate level (M9a)

VIEW_KIND = "view"
AMBIGUOUS_CODE = "AMBIGUOUS_DEPENDENCY"
LEAF_MARKERS = {  # visible text for leaf kinds that are not plain tables
    "external_view": "not in folder",
    "table_function": "table function",
    "unknown": "unknown source",
}
AMBIGUOUS_MARKER = "ambiguous"


def estate_elements(estate: Estate, summaries: list[ViewSummary],
                    annotations: list[Annotation]) -> list[dict]:
    """Cytoscape elements for the estate map: views, leaf sources, producer -> consumer edges.

    View data: {id, label, kind: "view", view_type, data_category, parse_status, coverage_pct,
    signoff, stale, node_count, warning_count, in_cycle} (summary fields are None for a view
    with no stored summary; signoff is None without a view note). Leaf data: {id, label, kind,
    ambiguous, marker} where marker is "" for a table, else visible text such as
    "not in folder" or "ambiguous". Edge data: {id: "e<index>", source, target,
    internal, in_cycle, ambiguous, count} with one edge per pair (`count` data sources); edge
    ids are `e<index>` in edge order, because "<producer>-><consumer>" can collide when
    ids contain "->" (views "A->B" + "C" versus "A" + "B->C").
    Order: views by id, leaves by id, edges in dependency order (consumer, data source)."""
    summary_by_id = {s.id: s for s in summaries}
    notes = {a.target_id: a for a in annotations if a.target_kind == TargetKind.VIEW}
    cycle_of = _cycle_index(estate)
    ambiguous_pairs = _ambiguous_pairs(estate)

    elements: list[dict] = []
    for view_id in sorted(estate.views):
        s = summary_by_id.get(view_id)
        note = notes.get(view_id)
        elements.append({"data": {
            "id": view_id, "label": view_id, "kind": VIEW_KIND,
            "view_type": str(s.view_type) if s else None,
            "data_category": str(s.data_category) if s else None,
            "parse_status": str(s.parse_status) if s else None,
            "coverage_pct": s.coverage_pct if s else None,
            "signoff": str(note.signoff_status) if note else None,
            "stale": bool(note and note.stale),
            "node_count": s.node_count if s else None,
            "warning_count": s.warning_count if s else None,
            "in_cycle": view_id in cycle_of,
        }})
    ambiguous_leaves = {producer for producer, _ in ambiguous_pairs}
    for leaf in sorted(estate.leaf_sources, key=lambda leaf: leaf.id):
        ambiguous = leaf.id in ambiguous_leaves
        elements.append({"data": {
            "id": leaf.id, "label": leaf_label(leaf), "kind": str(leaf.kind),
            "ambiguous": ambiguous,
            "marker": AMBIGUOUS_MARKER if ambiguous else LEAF_MARKERS.get(str(leaf.kind), ""),
        }})
    for index, ((producer, consumer), (internal, count)) in enumerate(_edge_pairs(estate).items()):
        elements.append({"data": {
            "id": f"e{index}", "source": producer, "target": consumer,
            "internal": internal, "count": count,
            "in_cycle": _same_cycle(cycle_of, producer, consumer),
            "ambiguous": (producer, consumer) in ambiguous_pairs,
        }})
    return elements


def leaf_label(leaf: LeafSource) -> str:
    return f"{leaf.schema_name}.{leaf.name}" if leaf.schema_name else leaf.name


def _cycle_index(estate: Estate) -> dict[str, int]:
    return {member: i for i, members in enumerate(estate.cycles) for member in members}


def _same_cycle(cycle_of: dict[str, int], a: str, b: str) -> bool:
    return a in cycle_of and cycle_of.get(b) == cycle_of[a]


def _ambiguous_pairs(estate: Estate) -> set[tuple[str, str]]:
    """(leaf id, consumer) for each dependency that resolution flagged as ambiguous."""
    flagged = {(w.view_id, w.node_id) for w in estate.warnings if w.code == AMBIGUOUS_CODE}
    return {(d.producer, d.consumer) for d in estate.dependencies
            if not d.internal and (d.consumer, d.data_source_id) in flagged}


def _edge_pairs(estate: Estate) -> dict[tuple[str, str], tuple[bool, int]]:
    """(producer, consumer) -> (internal, data source count), in dependency order."""
    pairs: dict[tuple[str, str], tuple[bool, int]] = {}
    for d in estate.dependencies:
        internal, count = pairs.get((d.producer, d.consumer), (d.internal, 0))
        pairs[(d.producer, d.consumer)] = (internal, count + 1)
    return pairs


# ---------------------------------------------------------------- Mermaid text

# Characters Mermaid reads specially inside a quoted label, as entity codes. "#" goes
# first so the codes themselves are not re-escaped; "%" stops "%%{...}%%" directives;
# "`" stops markdown strings; "<", ">", "&" stop HTML.
_MERMAID_CODES = {"#": "#35;", '"': "#quot;", "<": "#60;", ">": "#62;", "&": "#38;",
                  "`": "#96;", "%": "#37;"}

MERMAID_CLASSES = {
    "cycle": "stroke:#b42318,stroke-width:3px,stroke-dasharray:4 2",
    "ambiguous": "stroke:#a15c00,stroke-width:2px,stroke-dasharray:4 2",
    "external": "stroke:#a15c00,stroke-dasharray:2 2",
    "missing": "stroke:#b42318,stroke-dasharray:2 2",
    "notunderstood": "stroke:#b42318,stroke-width:2px",
}


def mermaid_label(text: str) -> str:
    """Escape `text` for use inside a double-quoted Mermaid label."""
    out = []
    for ch in text:
        if ch in _MERMAID_CODES:
            out.append(_MERMAID_CODES[ch])
        elif not ch.isprintable():  # newlines, tabs, control characters
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def estate_mermaid(estate: Estate, include_leaves: bool = True) -> str:
    """`flowchart LR` of the estate: views `["id"]`, leaf sources `[("name")]`, edges
    producer --> consumer. Ids are `n<index>` (views by id, then leaves by id). Cycle edges
    read `-->|cycle|`; an ambiguous dependency reads `-.->|ambiguous|`; marked nodes get a
    class. Deterministic."""
    views = sorted(estate.views)
    leaves = sorted(estate.leaf_sources, key=lambda leaf: leaf.id) if include_leaves else []
    ids = {view_id: f"n{i}" for i, view_id in enumerate(views)}
    ids.update({leaf.id: f"n{len(views) + i}" for i, leaf in enumerate(leaves)})
    cycle_of = _cycle_index(estate)
    ambiguous_pairs = _ambiguous_pairs(estate)
    ambiguous_leaves = {producer for producer, _ in ambiguous_pairs}
    classes: dict[str, list[str]] = {name: [] for name in MERMAID_CLASSES}

    lines = ["flowchart LR"]
    for view_id in views:
        lines.append(f'{ids[view_id]}["{mermaid_label(view_id)}"]')
        if view_id in cycle_of:
            classes["cycle"].append(ids[view_id])
    for leaf in leaves:
        label = leaf_label(leaf)
        if leaf.id in ambiguous_leaves:
            label += " (ambiguous: several views match)"
            classes["ambiguous"].append(ids[leaf.id])
        elif str(leaf.kind) in LEAF_MARKERS:
            label += f" ({LEAF_MARKERS[str(leaf.kind)]})"
            classes["external"].append(ids[leaf.id])
        lines.append(f'{ids[leaf.id]}[("{mermaid_label(label)}")]')
    for (producer, consumer), _ in _edge_pairs(estate).items():
        if producer not in ids or consumer not in ids:
            continue  # a leaf edge with leaves hidden
        if _same_cycle(cycle_of, producer, consumer):
            arrow = "-->|cycle|"
        elif (producer, consumer) in ambiguous_pairs:
            arrow = "-.->|ambiguous|"
        else:
            arrow = "-->"
        lines.append(f"{ids[producer]} {arrow} {ids[consumer]}")
    lines.extend(_mermaid_class_lines(classes))
    return "\n".join(lines) + "\n"


def view_mermaid(result: ParseResult) -> str:
    """`flowchart BT` of one view's steps (sources at the bottom, like the canvas), inside a
    subgraph titled with the view id. Ids are `n<index>` in IR order; data sources are `[("name")]`, other steps
    `["name (type)"]`; an edge to an undefined step gets a "(missing)" placeholder and a
    step the parser did not fully understand says so. Deterministic."""
    nodes: dict[str, Node] = {}
    for node in result.nodes:
        nodes[node.id] = node  # a repeated id: last definition wins, first position kept
    ids = {node_id: f"n{i}" for i, node_id in enumerate(nodes)}
    missing = []
    for edge in result.edges:
        for end in (edge.from_node, edge.to_node):
            if end not in ids:
                ids[end] = f"n{len(ids)}"
                missing.append(end)
    classes: dict[str, list[str]] = {name: [] for name in MERMAID_CLASSES}

    lines = ["flowchart BT", f'subgraph s0["{mermaid_label(result.view.id)}"]']
    for node_id, node in nodes.items():
        label = node.name
        if node.node_type is not NodeType.DATASOURCE:
            label += f" ({str(node.node_type).replace('_', ' ')})"
        if not node.understood:
            label += " (not understood)"
            classes["notunderstood"].append(ids[node_id])
        shape = '[("{}")]' if node.node_type is NodeType.DATASOURCE else '["{}"]'
        lines.append(ids[node_id] + shape.format(mermaid_label(label)))
    for end in missing:
        lines.append(f'{ids[end]}["{mermaid_label(end.rpartition("/")[2] + " (missing)")}"]')
        classes["missing"].append(ids[end])
    lines.append("end")
    for edge in result.edges:
        lines.append(f"{ids[edge.from_node]} --> {ids[edge.to_node]}")
    lines.extend(_mermaid_class_lines(classes))
    return "\n".join(lines) + "\n"


def _mermaid_class_lines(classes: dict[str, list[str]]) -> list[str]:
    lines = []
    for name, members in classes.items():
        if members:
            lines.append(f"classDef {name} {MERMAID_CLASSES[name]}")
            lines.append(f"class {','.join(members)} {name}")
    return lines
