from fastapi.testclient import TestClient

from app.ir.models import Column, Node, ParseResult

LOCAL = "http://127.0.0.1"


def local_client(app) -> TestClient:
    """A TestClient that sends Host: 127.0.0.1 (its default "testserver" is refused)."""
    return TestClient(app, base_url=LOCAL)


def node(result: ParseResult, name: str) -> Node:
    matches = [n for n in result.nodes if n.name == name]
    assert matches, f"no node named {name!r}; have {[n.name for n in result.nodes]}"
    return matches[0]


def column(n: Node, name: str) -> Column:
    matches = [c for c in n.columns if c.name == name]
    assert matches, f"no column {name!r} on {n.name}; have {[c.name for c in n.columns]}"
    return matches[0]


def codes(result: ParseResult) -> list[str]:
    return [w.code for w in result.warnings]
