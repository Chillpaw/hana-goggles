"""Views list, view page (tabs), node panel and the view-graph elements."""
import json
import re
import shutil
import sqlite3

import pytest
from conftest import FIXTURES
from fastapi.testclient import TestClient

from app.enrich.deps import resolve_dependencies
from app.generators.describe import describe_view
from app.generators.lineage import view_elements
from app.ingest.importer import import_folder
from app.ir.models import Edge, Node, NodeType
from app.ir.store import Store
from app.main import create_app

VIEW = "GENERIC_TAX_REPORTING_CUBE"
PRODUCER = "SOURCE_VIEW_01"
GRAPH_DATA = re.compile(
    r'<script type="application/json" id="graph-data">(.*?)</script>', re.DOTALL)


def _copy(src, dest):
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("*.ir.json"))
    return dest


@pytest.fixture
def folder(tmp_path):
    return _copy(FIXTURES / "graphical", tmp_path / "views")


@pytest.fixture
def db(tmp_path, folder):
    path = tmp_path / "p.db"
    with Store(path) as store:
        import_folder(store, folder)
    return path


@pytest.fixture
def client(db):
    return TestClient(create_app(db))


def _results(db):
    with Store(db) as store:
        results = store.load_all_results()
    return {r.view.id: r for r in results}, resolve_dependencies(results)


def _graph(html):
    match = GRAPH_DATA.search(html)
    assert match, "graph JSON not embedded"
    elements = json.loads(match.group(1))
    nodes = [e["data"] for e in elements if "source" not in e["data"]]
    edges = [e["data"] for e in elements if "source" in e["data"]]
    return nodes, edges


# ---------------------------------------------------------------- lineage.view_elements

def test_view_elements_for_consumer(db):
    results, estate = _results(db)
    result = results[VIEW]
    elements = view_elements(result, describe_view(result, estate))
    nodes = [e["data"] for e in elements if "source" not in e["data"]]
    edges = [e["data"] for e in elements if "source" in e["data"]]
    assert len(nodes) == 8 and len(edges) == 7
    proj = next(n for n in nodes if n["label"] == "Projection_1")
    assert proj == {
        "id": f"{VIEW}/Projection_1", "label": "Projection_1", "node_type": "projection",
        "understood": True, "warning_count": 0,
        "headline": "Takes 4 columns from SOURCE_VIEW_01.", "resolved_view": None,
    }
    src = next(n for n in nodes if n["label"] == PRODUCER)
    assert src["resolved_view"] == PRODUCER
    assert {"id": f"{VIEW}/Projection_1->{VIEW}/Join_1", "source": f"{VIEW}/Projection_1",
            "target": f"{VIEW}/Join_1", "column_count": 5} in edges
    # deterministic
    assert elements == view_elements(result, describe_view(result, estate))


def test_view_elements_mark_dangling_edges_and_duplicate_edges(db):
    results, _ = _results(db)
    result = results[PRODUCER].model_copy(deep=True)
    first = result.edges[0]
    result.edges.append(Edge(from_node=first.from_node, to_node=first.to_node))
    result.edges.append(Edge(from_node=f"{PRODUCER}/GHOST", to_node=first.to_node))
    elements = view_elements(result, [])
    ids = [e["data"]["id"] for e in elements]
    assert len(ids) == len(set(ids))  # cytoscape rejects duplicate ids
    ghost = next(e["data"] for e in elements if e["data"]["id"] == f"{PRODUCER}/GHOST")
    assert ghost["node_type"] == "missing" and ghost["understood"] is False
    assert "(missing)" in ghost["label"]


def test_view_elements_duplicate_node_ids_appear_once(db):
    results, _ = _results(db)
    result = results[PRODUCER].model_copy(deep=True)
    result.nodes.append(Node(id=result.nodes[0].id, view_id=PRODUCER,
                             node_type=NodeType.OPAQUE, name="dup", raw="<x/>"))
    ids = [e["data"]["id"] for e in view_elements(result, [])]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------- index and import

def test_index_shows_import_form_before_import(tmp_path):
    db = tmp_path / "p.db"
    response = TestClient(create_app(db)).get("/")
    assert response.status_code == 200
    assert 'name="folder"' in response.text and 'action="/import"' in response.text
    assert not db.exists()


def test_index_redirects_after_import(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/views"


def test_views_without_project_redirects_to_form(tmp_path):
    client = TestClient(create_app(tmp_path / "p.db"))
    response = client.get("/views", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/"


def test_post_import_creates_project_and_redirects(tmp_path, folder):
    db = tmp_path / "new.db"
    client = TestClient(create_app(db))
    response = client.post("/import", data={"folder": str(folder)}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/views"
    assert VIEW in client.get("/views").text


def test_post_import_bad_folder_rerenders_form(tmp_path):
    db = tmp_path / "new.db"
    client = TestClient(create_app(db))
    response = client.post("/import", data={"folder": str(tmp_path / "nope")})
    assert response.status_code == 400
    assert "not a folder" in response.text and 'name="folder"' in response.text
    response = client.post("/import", data={"folder": ""})
    assert response.status_code == 400


def test_views_page_has_reimport_button(client, folder):
    html = client.get("/views").text
    assert 'action="/import"' in html and f'value="{folder.resolve()}"' in html


# ---------------------------------------------------------------- views list

def _rows(html):
    body = html.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    return [r for r in body.split("<tr") if "</td>" in r]


def test_views_lists_both_with_coverage_and_dependency_counts(client):
    response = client.get("/views")
    assert response.status_code == 200
    rows = _rows(response.text)
    assert len(rows) == 2
    consumer = next(r for r in rows if VIEW in r)
    producer = next(r for r in rows if f">{PRODUCER}<" in r)
    assert "100%" in consumer and "CUBE" in consumer and "graphical" in consumer
    assert re.search(r'depends">1<', consumer) and re.search(r'usedby">0<', consumer)
    assert re.search(r'depends">0<', producer) and re.search(r'usedby">1<', producer)
    assert f'href="/views/{VIEW}"' in consumer


def test_views_sort_and_filter(client):
    by_name = _rows(client.get("/views?sort=name").text)
    assert VIEW in by_name[0]
    by_name_desc = _rows(client.get("/views?sort=-name").text)
    assert PRODUCER in by_name_desc[0]
    by_nodes = _rows(client.get("/views?sort=nodes").text)
    assert PRODUCER in by_nodes[0]  # 3 nodes before 8
    filtered = _rows(client.get("/views?q=source").text)
    assert len(filtered) == 1 and PRODUCER in filtered[0]
    assert client.get("/views?sort=bogus").status_code == 200


# ---------------------------------------------------------------- view page

def test_view_page_embeds_graph_json(client):
    response = client.get(f"/views/{VIEW}")
    assert response.status_code == 200
    nodes, edges = _graph(response.text)
    assert len(nodes) == 8 and len(edges) == 7
    assert '/static/app/viewgraph.js' in response.text
    assert 'id="node-panel"' in response.text


def test_view_page_header_links_upstream_and_downstream(client):
    consumer = client.get(f"/views/{VIEW}").text
    assert f'href="/views/{PRODUCER}"' in consumer
    producer = client.get(f"/views/{PRODUCER}").text
    assert f'href="/views/{VIEW}"' in producer


def test_steps_tab_lists_sentences_in_order(client):
    html = client.get(f"/views/{VIEW}?tab=steps").text
    expected = [
        "Reads calculation view SOURCE_VIEW_01.",
        "Defined in this project.",
        "Reads table SCHEMA_1.TABLE_A.",
        "Takes 4 columns from SOURCE_VIEW_01.",
        "Keeps rows where COL_3 = input parameter IP_FISCAL_YEAR.",
        "Adds CC_1 = if COL_2 = &#39;X&#39; then AMT_1 else 0.",
        "Left outer join of Projection_1 and TABLE_A on COL_1 (many-to-one).",
        "Stacks rows from Join_1 and TABLE_B.",
        "Sums AMT_1, CC_1 by COL_1, COL_3, COL_5.",
        "Publishes 3 attributes and 4 measures as the view&#39;s output.",
    ]
    positions = [html.find(s) for s in expected]
    assert all(p >= 0 for p in positions), [s for s, p in zip(expected, positions) if p < 0]
    assert positions == sorted(positions)
    assert GRAPH_DATA.search(html) is None  # graph only on its tab


@pytest.mark.parametrize("tab,needle", [
    ("columns", "AMT_1"),
    ("warnings", "No warnings"),
    ("raw", "&lt;calculationView"),
])
def test_other_tabs_render(client, tab, needle):
    response = client.get(f"/views/{VIEW}?tab={tab}")
    assert response.status_code == 200 and needle in response.text


def test_unknown_view_is_404(client):
    assert client.get("/views/NO_SUCH_VIEW").status_code == 404
    assert client.get("/node", params={"view": "NO_SUCH_VIEW", "node": "x"}).status_code == 404
    assert client.get("/node", params={"view": VIEW, "node": "nope"}).status_code == 404


def test_node_panel_fragment(client):
    response = client.get("/node", params={"view": VIEW, "node": "Projection_1"})
    assert response.status_code == 200
    html = response.text
    assert "<html" not in html  # a fragment
    assert "Takes 4 columns from SOURCE_VIEW_01." in html
    assert "Keeps rows where COL_3 = input parameter IP_FISCAL_YEAR." in html
    assert "CC_1" in html and "&lt;calculationView" in html


def test_node_panel_links_resolved_datasource(client):
    html = client.get("/node", params={"view": VIEW, "node": PRODUCER}).text
    assert f'href="/views/{PRODUCER}"' in html


def test_graph_nodes_carry_panel_and_view_urls(client):
    nodes, _ = _graph(client.get(f"/views/{VIEW}").text)
    proj = next(n for n in nodes if n["label"] == "Projection_1")
    assert proj["panel_url"] == f"/node?view={VIEW}&node=Projection_1"
    src = next(n for n in nodes if n["label"] == PRODUCER)
    assert src["view_url"] == f"/views/{PRODUCER}"
    assert "view_url" not in proj


# ---------------------------------------------------------------- failed and unparsed views

def test_failed_view_shows_could_not_be_parsed(tmp_path):
    folder = tmp_path / "views"
    folder.mkdir()
    shutil.copy(FIXTURES / "malformed" / "truncated.calculationview", folder)
    db = tmp_path / "p.db"
    with Store(db) as store:
        import_folder(store, folder)
    client = TestClient(create_app(db))
    for tab in ("graph", "steps"):
        html = client.get(f"/views/truncated?tab={tab}").text
        assert "could not be parsed" in html and "XML_SYNTAX" in html


def test_not_parsed_expression_is_code_and_escaped(tmp_path):
    folder = tmp_path / "views"
    folder.mkdir()
    shutil.copy(FIXTURES / "malformed" / "bad_expression.calculationview", folder)
    db = tmp_path / "p.db"
    with Store(db) as store:
        import_folder(store, folder)
    client = TestClient(create_app(db))
    html = client.get("/views/BAD_EXPRESSION_VIEW?tab=steps").text
    assert ('<code class="raw">if(&#34;COL_1&#34; = &#39;X&#39;, 1</code> '
            '<span class="not-parsed">(not parsed)</span>') in html
    assert "`" not in html.split("<main", 1)[1]


# ---------------------------------------------------------------- escaping

HOSTILE = "<script>alert(1)</script>"


def test_hostile_view_id_is_escaped(tmp_path):
    xml = (FIXTURES / "graphical" / f"{PRODUCER}.calculationview").read_text(encoding="utf-8")
    xml = xml.replace(f'id="{PRODUCER}"', 'id="&lt;script&gt;alert(1)&lt;/script&gt;"', 1)
    folder = tmp_path / "views"
    folder.mkdir()
    (folder / "HOSTILE.calculationview").write_text(xml, encoding="utf-8")
    db = tmp_path / "p.db"
    with Store(db) as store:
        import_folder(store, folder)
    client = TestClient(create_app(db))

    listing = client.get("/views").text
    assert HOSTILE not in listing and "&lt;script&gt;alert(1)&lt;/script&gt;" in listing
    assert 'href="/views/%3Cscript%3Ealert%281%29%3C%2Fscript%3E"' in listing

    response = client.get("/views/%3Cscript%3Ealert%281%29%3C%2Fscript%3E")
    assert response.status_code == 200
    assert HOSTILE not in response.text
    nodes, _ = _graph(response.text)  # the JSON round-trips despite the hostile id
    assert any(n["id"].startswith(HOSTILE) for n in nodes)
    panel = client.get("/node", params={"view": HOSTILE, "node": "Projection_1"})
    assert panel.status_code == 200 and HOSTILE not in panel.text


def test_jinja_autoescape_is_on():
    from app.web.routes import templates
    for name in ("base.html", "views.html", "view.html", "_node_panel.html", "index.html"):
        assert templates.env.autoescape(name) is True, name
    assert templates.get_template("base.html") is not None


def test_view_ids_with_slashes_and_dots_route(tmp_path):
    xml = (FIXTURES / "graphical" / f"{PRODUCER}.calculationview").read_text(encoding="utf-8")
    xml = xml.replace(f'id="{PRODUCER}"', 'id="pkg/sub.V:1"', 1)
    folder = tmp_path / "views"
    folder.mkdir()
    (folder / "SLASHED.calculationview").write_text(xml, encoding="utf-8")
    db = tmp_path / "p.db"
    with Store(db) as store:
        import_folder(store, folder)
    client = TestClient(create_app(db))
    assert 'href="/views/pkg%2Fsub.V%3A1"' in client.get("/views").text
    assert client.get("/views/pkg%2Fsub.V%3A1").status_code == 200
    assert client.get("/views/pkg/sub.V:1").status_code == 200
    assert client.get("/node", params={"view": "pkg/sub.V:1", "node": "Projection_1"}).status_code == 200


# ---------------------------------------------------------------- stored data from an older version

def test_old_ir_in_store_shows_reimport_message(client, db):
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT result_json FROM view WHERE id = ?", (VIEW,)).fetchone()
    data = json.loads(row[0])
    data["view"]["field_from_another_version"] = 1
    conn.execute("UPDATE view SET result_json = ? WHERE id = ?", (json.dumps(data), VIEW))
    conn.commit()
    conn.close()
    for url in ("/views", f"/views/{VIEW}", f"/views/{PRODUCER}"):
        response = client.get(url)
        assert response.status_code == 409, url
        assert "older version" in response.text and "re-import" in response.text.lower()


def test_wrong_schema_db_shows_message(tmp_path):
    db = tmp_path / "p.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    response = TestClient(create_app(db)).get("/views")
    assert response.status_code == 409 and "re-import" in response.text.lower()
