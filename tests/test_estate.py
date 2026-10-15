"""Estate map (M9a): estate elements, Mermaid exports and the /estate page.

The Mermaid golden is a regression guard; regenerate it with
UPDATE_GOLDEN=1 pytest tests/test_estate.py, then review the diff by hand."""
import json
import os
import re
import shutil
import sqlite3

import pytest
from conftest import FIXTURES
from helpers import local_client
from test_deps import calc_source, put, table_source, view_xml

from app.enrich.deps import resolve_dependencies
from app.generators.lineage import estate_elements, estate_mermaid, mermaid_label, view_mermaid
from app.ingest.importer import import_folder
from app.ingest.scan import scan_folder
from app.ir.models import Annotation, Estate, LeafKind, LeafSource, SignoffStatus, TargetKind, ViewDependency
from app.ir.store import Store
from app.main import create_app

VIEW = "GENERIC_TAX_REPORTING_CUBE"
PRODUCER = "SOURCE_VIEW_01"
GOLDEN = FIXTURES / "estate" / "graphical.estate.mmd"
ESTATE_DATA = re.compile(
    r'<script type="application/json" id="estate-data">(.*?)</script>', re.DOTALL)
HOSTILE = "<script>alert(1)</script>"


def _copy(src, dest):
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns("*.ir.json"), dirs_exist_ok=True)
    return dest


def _import(tmp_path, *fixture_dirs):
    folder = tmp_path / "views"
    folder.mkdir(exist_ok=True)
    for name in fixture_dirs:
        _copy(FIXTURES / name, folder)
    db = tmp_path / "p.db"
    with Store(db) as store:
        import_folder(store, folder)
    return db


@pytest.fixture
def db(tmp_path):
    return _import(tmp_path, "graphical")


@pytest.fixture
def client(db):
    return local_client(create_app(db))


def _scan(root):
    results = [s.result for s in scan_folder(root)]
    return results, resolve_dependencies(results)


def _split(elements):
    nodes = [e["data"] for e in elements if "source" not in e["data"]]
    edges = [e["data"] for e in elements if "source" in e["data"]]
    return nodes, edges


def _page_elements(html):
    match = ESTATE_DATA.search(html)
    assert match, "estate JSON not embedded"
    return _split(json.loads(match.group(1)))


def _store_inputs(db):
    with Store(db) as store:
        results = store.load_all_results()
        return resolve_dependencies(results), store.list_views(), store.list_annotations()


# ---------------------------------------------------------------- estate_elements

def test_estate_elements_for_fixture_folder(db):
    estate, summaries, annotations = _store_inputs(db)
    nodes, edges = _split(estate_elements(estate, summaries, annotations))
    views = [n for n in nodes if n["kind"] == "view"]
    leaves = [n for n in nodes if n["kind"] != "view"]
    assert [v["id"] for v in views] == [VIEW, PRODUCER]
    assert [leaf["kind"] for leaf in leaves] == ["table"] * 3
    assert [leaf["label"] for leaf in leaves] == ["SCHEMA_1.TABLE_A", "SCHEMA_1.TABLE_B", "SCHEMA_1.TABLE_C"]
    assert len(edges) == 4 and sum(e["internal"] for e in edges) == 1
    internal = next(e for e in edges if e["internal"])
    assert (internal["source"], internal["target"]) == (PRODUCER, VIEW)
    cube = views[0]
    assert {k: cube[k] for k in ("label", "view_type", "data_category", "parse_status",
                                 "coverage_pct", "signoff", "in_cycle")} == {
        "label": VIEW, "view_type": "graphical", "data_category": "CUBE", "parse_status": "ok",
        "coverage_pct": 100.0, "signoff": None, "in_cycle": False}
    assert cube["node_count"] > 0 and cube["warning_count"] == 0
    assert all(not e["in_cycle"] and not e["ambiguous"] for e in edges)


def test_estate_elements_are_deterministic(db):
    estate, summaries, annotations = _store_inputs(db)
    first = estate_elements(estate, summaries, annotations)
    again = estate_elements(estate, list(reversed(summaries)), annotations)
    assert json.dumps(first) == json.dumps(again)


def test_estate_elements_carry_view_signoff_only(db):
    estate, summaries, _ = _store_inputs(db)
    annotations = [
        Annotation(target_id=VIEW, target_kind=TargetKind.VIEW, signoff_status=SignoffStatus.APPROVED),
        # a step note with the producer's id must not count as the producer's sign-off
        Annotation(target_id=PRODUCER, target_kind=TargetKind.NODE, signoff_status=SignoffStatus.REVIEWED),
    ]
    nodes, _ = _split(estate_elements(estate, summaries, annotations))
    signoff = {n["id"]: n.get("signoff") for n in nodes if n["kind"] == "view"}
    assert signoff == {VIEW: "approved", PRODUCER: None}


def test_cycle_folder_marks_in_cycle(tmp_path):
    db = _import(tmp_path, "graphical", "estate_cycle")
    estate, summaries, annotations = _store_inputs(db)
    nodes, edges = _split(estate_elements(estate, summaries, annotations))
    cycle = {n["id"]: n["in_cycle"] for n in nodes if n["kind"] == "view"}
    assert cycle == {"CYCLE_A": True, "CYCLE_B": True, VIEW: False, PRODUCER: False}
    assert sorted((e["source"], e["target"]) for e in edges if e["in_cycle"]) == [
        ("CYCLE_A", "CYCLE_B"), ("CYCLE_B", "CYCLE_A")]


def _ambiguous_estate(tmp_path):
    put(tmp_path, "p1/V_1.calculationview", view_xml("V_1", table_source("TABLE_A")))
    put(tmp_path, "p2/V_1.calculationview", view_xml("V_1", table_source("TABLE_B")))
    put(tmp_path, "CONSUMER_1.calculationview",
        view_xml("CONSUMER_1", calc_source("V_1", "/p3/calculationviews/V_1")))
    put(tmp_path, "CONSUMER_2.calculationview",
        view_xml("CONSUMER_2", calc_source("GONE_1", "/p3/calculationviews/GONE_1")))
    return _scan(tmp_path)[1]


def test_ambiguous_leaf_is_marked(tmp_path):
    estate = _ambiguous_estate(tmp_path)
    nodes, edges = _split(estate_elements(estate, [], []))
    leaves = {n["id"]: n for n in nodes if n["kind"] != "view"}
    amb = leaves["view:V_1"]
    assert (amb["kind"], amb["ambiguous"], amb["marker"]) == ("external_view", True, "ambiguous")
    assert leaves["view:GONE_1"]["ambiguous"] is False
    assert leaves["view:GONE_1"]["marker"] == "not in folder"
    amb_edges = [e for e in edges if e["ambiguous"]]
    assert [(e["source"], e["target"]) for e in amb_edges] == [("view:V_1", "CONSUMER_1")]
    text = estate_mermaid(estate)
    assert "V_1 (ambiguous: several views match)" in text
    assert "GONE_1 (not in folder)" in text
    assert re.search(r"n\d+ -\.->\|ambiguous\| n\d+", text)
    assert "class " in text and " ambiguous" in text


def test_view_without_summary_still_drawn(tmp_path):
    estate = _ambiguous_estate(tmp_path)
    nodes, _ = _split(estate_elements(estate, [], []))
    consumer = next(n for n in nodes if n["id"] == "CONSUMER_1")
    assert consumer["parse_status"] is None and consumer["kind"] == "view"


# ---------------------------------------------------------------- Mermaid

def test_estate_mermaid_golden():
    _, estate = _scan(FIXTURES / "graphical")
    actual = estate_mermaid(estate)
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(actual, encoding="utf-8")
    assert GOLDEN.exists(), f"missing {GOLDEN.name}; run UPDATE_GOLDEN=1 pytest tests/test_estate.py and review it"
    assert actual == GOLDEN.read_text(encoding="utf-8")


def test_estate_mermaid_shape():
    _, estate = _scan(FIXTURES / "graphical")
    text = estate_mermaid(estate)
    lines = text.splitlines()
    assert lines[0] == "flowchart LR"
    assert f'n0["{VIEW}"]' in lines and f'n1["{PRODUCER}"]' in lines
    assert 'n2[("SCHEMA_1.TABLE_A")]' in lines
    assert "n1 --> n0" in lines and "n2 --> n0" in lines and "n4 --> n1" in lines
    assert sum(" --> " in line for line in lines) == 4
    assert estate_mermaid(estate) == text  # deterministic


def test_estate_mermaid_without_leaves():
    _, estate = _scan(FIXTURES / "graphical")
    lines = estate_mermaid(estate, include_leaves=False).splitlines()
    assert "n1 --> n0" in lines
    assert sum("-->" in line for line in lines) == 1
    assert not any("TABLE_" in line for line in lines)


def test_estate_mermaid_marks_cycles():
    _, estate = _scan(FIXTURES / "estate_cycle")
    lines = estate_mermaid(estate).splitlines()
    assert "n0 -->|cycle| n1" in lines and "n1 -->|cycle| n0" in lines
    assert "class n0,n1 cycle" in lines
    assert any(line.startswith("classDef cycle ") for line in lines)


def test_mermaid_label_neutralises_special_characters():
    assert mermaid_label('A"B') == "A#quot;B"
    out = mermaid_label('x#y<b>&`%%{init: {}}%%\n')
    for bad in ('"', "<", ">", "`", "%", "\n"):
        assert bad not in out, bad
    assert out.startswith("x#35;y#60;b#62;#38;#96;#37;#37;")
    assert mermaid_label("#quot;") == "#35;quot;"  # a literal entity stays literal


def test_estate_mermaid_escapes_hostile_ids():
    estate = Estate(
        views=['A"]-->X', HOSTILE],
        dependencies=[ViewDependency(consumer=HOSTILE, producer='A"]-->X',
                                     data_source_id="x", internal=True),
                      ViewDependency(consumer=HOSTILE, producer="table:S.T\nclick",
                                     data_source_id="y", internal=False)],
        leaf_sources=[LeafSource(id="table:S.T\nclick", kind=LeafKind.TABLE, schema_name="S",
                                 name="T\nclick")])
    text = estate_mermaid(estate)
    lines = text.splitlines()
    assert 'n1["A#quot;]--#62;X"]' in lines  # views sorted: "<" before "A"
    assert HOSTILE not in text
    assert not any(line.strip().startswith("click") for line in lines)  # newline neutralised
    assert 'n2[("S.T click")]' in lines
    assert len([line for line in lines if line.startswith("n")]) == 5


def test_view_mermaid(db):
    with Store(db) as store:
        result = store.load_result(VIEW)
    text = view_mermaid(result)
    lines = text.splitlines()
    assert lines[0] == "flowchart BT"
    assert any(re.fullmatch(r'n\d+\[\("TABLE_A"\)\]', line) for line in lines)
    assert any(re.fullmatch(r'n\d+\["Projection_1 \(projection\)"\]', line) for line in lines)
    assert sum(" --> " in line for line in lines) == len(result.edges)
    assert view_mermaid(result) == text


def test_view_mermaid_marks_missing_and_not_understood(db):
    from app.ir.models import Edge
    with Store(db) as store:
        result = store.load_result(VIEW)
    result.edges.append(Edge(from_node=f"{VIEW}/GHOST_1", to_node=result.nodes[-1].id))
    result.nodes[1].understood = False
    text = view_mermaid(result)
    assert '"GHOST_1 (missing)"' in text
    assert "(not understood)" in text


# ---------------------------------------------------------------- routes

def test_estate_page_embeds_json(client):
    response = client.get("/estate")
    assert response.status_code == 200
    nodes, edges = _page_elements(response.text)
    assert len([n for n in nodes if n["kind"] == "view"]) == 2
    assert len([n for n in nodes if n["kind"] != "view"]) == 3
    assert len(edges) == 4
    cube = next(n for n in nodes if n["id"] == VIEW)
    assert cube["url"] == f"/views/{VIEW}" and cube["mmd_url"] == f"/view.mmd?view={VIEW}"
    html = response.text
    assert 'href="/estate.mmd"' in html and 'href="/estate.mmd?leaves=0"' in html
    assert "/static/app/estate.js" in html
    assert 'id="colour-by"' in html and 'id="png-export"' in html and 'id="search"' in html
    deploy = html.split('id="deploy-order"', 1)[1].split("</ol>", 1)[0]
    assert deploy.index(PRODUCER) < deploy.index(VIEW)


def test_estate_page_without_project_redirects(tmp_path):
    db = tmp_path / "none.db"
    client = local_client(create_app(db))
    response = client.get("/estate", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/"
    assert client.get("/estate.mmd").status_code == 404
    assert client.get("/view.mmd", params={"view": VIEW}).status_code == 404
    assert not db.exists()


def test_estate_page_shows_cycles_at_top(tmp_path):
    client = local_client(create_app(_import(tmp_path, "graphical", "estate_cycle")))
    html = client.get("/estate").text
    main = html.split("<main>", 1)[1]
    assert "Cycle:" in main
    assert main.index("Cycle:") < main.index('id="estate"')
    nodes, _ = _page_elements(html)
    assert {n["id"] for n in nodes if n.get("in_cycle")} == {"CYCLE_A", "CYCLE_B"}


def test_estate_page_lists_unresolved_warnings(tmp_path):
    folder = tmp_path / "views"
    folder.mkdir()
    shutil.copy(FIXTURES / "graphical" / f"{VIEW}.calculationview", folder)
    db = tmp_path / "p.db"
    with Store(db) as store:
        import_folder(store, folder)
    html = local_client(create_app(db)).get("/estate").text
    assert "UNRESOLVED_VIEW_DEPENDENCY" in html
    nodes, _ = _page_elements(html)
    leaf = next(n for n in nodes if n["id"] == f"view:{PRODUCER}")
    assert leaf["marker"] == "not in folder"


def test_estate_mmd_is_an_attachment(client):
    response = client.get("/estate.mmd")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;") and 'filename="' in disposition
    assert response.text == GOLDEN.read_text(encoding="utf-8")
    views_only = client.get("/estate.mmd", params={"leaves": "0"})
    assert "TABLE_A" not in views_only.text and "n1 --> n0" in views_only.text


def test_view_mmd_is_an_attachment(client):
    response = client.get("/view.mmd", params={"view": VIEW})
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["content-disposition"] == f'attachment; filename="{VIEW}.mmd"'
    assert response.text.startswith("flowchart BT")
    assert client.get("/view.mmd", params={"view": "NO_SUCH_VIEW"}).status_code == 404


def test_hostile_view_id_escaped_in_page_and_mermaid(tmp_path):
    xml = (FIXTURES / "graphical" / f"{PRODUCER}.calculationview").read_text(encoding="utf-8")
    xml = xml.replace(f'id="{PRODUCER}"', 'id="&lt;script&gt;alert(1)&lt;/script&gt;"', 1)
    folder = tmp_path / "views"
    folder.mkdir()
    (folder / "HOSTILE.calculationview").write_text(xml, encoding="utf-8")
    db = tmp_path / "p.db"
    with Store(db) as store:
        import_folder(store, folder)
    client = local_client(create_app(db))

    page = client.get("/estate")
    assert page.status_code == 200 and HOSTILE not in page.text
    nodes, _ = _page_elements(page.text)
    assert any(n["id"] == HOSTILE for n in nodes)

    for response in (client.get("/estate.mmd"), client.get("/view.mmd", params={"view": HOSTILE})):
        assert response.status_code == 200
        assert HOSTILE not in response.text and "#60;script#62;" in response.text
        filename = response.headers["content-disposition"].split("filename=", 1)[1]
        assert re.fullmatch(r'"[A-Za-z0-9._-]+\.mmd"', filename), filename
        assert response.headers["content-disposition"].isascii()


def test_estate_routes_show_outdated_data_message(client, db):
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT result_json FROM view WHERE id = ?", (VIEW,)).fetchone()
    data = json.loads(row[0])
    data["view"]["field_from_another_version"] = 1
    conn.execute("UPDATE view SET result_json = ? WHERE id = ?", (json.dumps(data), VIEW))
    conn.commit()
    conn.close()
    for url in ("/estate", "/estate.mmd", f"/view.mmd?view={PRODUCER}"):
        response = client.get(url)
        assert response.status_code == 409, url
        assert "older version" in response.text


def test_nav_and_pages_link_to_estate(client):
    for url in ("/views", f"/views/{VIEW}", "/estate"):
        html = client.get(url).text
        assert 'href="/estate"' in html, url
