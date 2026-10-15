"""Estate graph: networkx view of an Estate, deploy order, cycles, up/downstream views."""
from __future__ import annotations

import networkx as nx

from app.ir.models import Estate

VIEW_KIND = "view"


def estate_digraph(estate: Estate) -> nx.DiGraph:
    """Edges run producer -> consumer. Every node has a `kind`: "view" or a LeafKind value."""
    g = nx.DiGraph()
    for view_id in estate.views:
        g.add_node(view_id, kind=VIEW_KIND)
    for leaf in estate.leaf_sources:
        g.add_node(leaf.id, kind=str(leaf.kind))
    for dep in estate.dependencies:
        g.add_edge(dep.producer, dep.consumer)
    return g


def order_and_cycles(estate: Estate) -> tuple[list[str], list[list[str]]]:
    """Deploy order (views only, producers first) and cycles (each sorted, list sorted).

    A cycle is a strongly connected component with more than one member, or a self-loop.
    The order is a lexicographic topological sort of the condensation, a component keyed
    by its smallest member id, with each component's members expanded in sorted order."""
    g = _view_graph(estate)
    cond = nx.condensation(g)
    members = {c: sorted(cond.nodes[c]["members"]) for c in cond.nodes}
    order: list[str] = []
    for c in nx.lexicographical_topological_sort(cond, key=lambda c: members[c][0]):
        order.extend(members[c])
    cycles = sorted(m for m in members.values() if len(m) > 1 or g.has_edge(m[0], m[0]))
    return order, cycles


def upstream(estate: Estate, view_id: str) -> list[str]:
    """Every internal view `view_id` reads from, directly or transitively."""
    g = _view_graph(estate)
    return sorted(nx.ancestors(g, view_id)) if view_id in g else []


def downstream(estate: Estate, view_id: str) -> list[str]:
    """Every internal view that reads from `view_id`, directly or transitively."""
    g = _view_graph(estate)
    return sorted(nx.descendants(g, view_id)) if view_id in g else []


def _view_graph(estate: Estate) -> nx.DiGraph:
    g = nx.DiGraph()
    g.add_nodes_from(estate.views)
    g.add_edges_from((d.producer, d.consumer) for d in estate.dependencies if d.internal)
    return g
