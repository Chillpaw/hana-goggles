"""Graph elements for the browser: one view's node graph as Cytoscape elements.

Reads only the IR and the descriptions built from it. Output order is deterministic:
nodes in IR order, then edges in IR order. Nothing is dropped silently: an edge that
names a node the view does not define gets a visible "missing" placeholder node.
"""
from __future__ import annotations

from collections import Counter

from app.generators.describe import NodeDescription
from app.ir.models import ParseResult

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
