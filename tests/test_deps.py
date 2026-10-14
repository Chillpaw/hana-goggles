"""Cross-view dependency resolution, the estate model, deploy order and cycles.
The estate golden is a regression guard; regenerate it with
UPDATE_GOLDEN=1 pytest tests/test_deps.py, then review the diff by hand."""
import os
import shutil

import pytest
from conftest import FIXTURES, MAIN

from app.enrich.deps import resolve_dependencies
from app.ingest.scan import scan_folder
from app.ir.graph import downstream, estate_digraph, upstream
from app.ir.models import DataSourceKind, LeafKind, ParseStatus, Severity

GOLDEN = FIXTURES / "estate" / "graphical.estate.json"


def _results(root):
    return [s.result for s in scan_folder(root)]


def _by_id(results, view_id):
    return next(r for r in results if r.view.id == view_id)


def _codes(estate):
    return [w.code for w in estate.warnings]


def _source(ds_id, ds_type, inner):
    return (f'<DataSource id="{ds_id}" type="{ds_type}">'
            f'<viewAttributes allViewAttributes="true"/>{inner}</DataSource>')


def calc_source(ds_id, uri):
    return _source(ds_id, "CALCULATION_VIEW", f"<resourceUri>{uri}</resourceUri>")


def table_source(ds_id, schema="SCHEMA_1"):
    schema_attr = f' schemaName="{schema}"' if schema else ""
    return _source(ds_id, "DATA_BASE_TABLE",
                   f'<columnObject{schema_attr} columnObjectName="{ds_id}"/>')


def view_xml(view_id, *sources):
    """A minimal synthetic graphical view: the given data sources, one projection over the first."""
    first = sources[0].split('id="', 1)[1].split('"', 1)[0]
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Calculation:scenario xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:Calculation="http://www.sap.com/ndb/BiModelCalculation.ecore" schemaVersion="2.3" id="{view_id}" dataCategory="CUBE" outputViewType="Projection">
  <descriptions defaultDescription="{view_id}"/>
  <localVariables/>
  <variableMappings/>
  <dataSources>{''.join(sources)}</dataSources>
  <calculationViews>
    <calculationView xsi:type="Calculation:ProjectionView" id="Projection_1">
      <viewAttributes><viewAttribute id="COL_1"/></viewAttributes>
      <calculatedViewAttributes/>
      <input node="#{first}">
        <mapping xsi:type="Calculation:AttributeMapping" target="COL_1" source="COL_1"/>
      </input>
    </calculationView>
  </calculationViews>
  <logicalModel id="Projection_1">
    <attributes>
      <attribute id="COL_1" order="1">
        <keyMapping columnObjectName="Projection_1" columnName="COL_1"/>
      </attribute>
    </attributes>
    <calculatedAttributes/>
    <baseMeasures/>
    <calculatedMeasures/>
    <restrictedMeasures/>
  </logicalModel>
</Calculation:scenario>
"""


def put(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- the graphical/ fixture folder -------------------------------------------------------

def test_graphical_folder_resolves_producer():
    results = _results(FIXTURES / "graphical")
    estate = resolve_dependencies(results)

    consumer = next(r for r in results if r.view.id == "GENERIC_TAX_REPORTING_CUBE")
    calc = next(d for d in consumer.data_sources if d.kind is DataSourceKind.CALC_VIEW)
    assert calc.resolved_view_id == "SOURCE_VIEW_01"
    assert all(d.resolved_view_id is None for d in consumer.data_sources if d is not calc)

    assert estate.views == ["GENERIC_TAX_REPORTING_CUBE", "SOURCE_VIEW_01"]
    assert estate.deploy_order == ["SOURCE_VIEW_01", "GENERIC_TAX_REPORTING_CUBE"]
    assert estate.cycles == []
    assert estate.warnings == []

    deps = [(d.consumer, d.producer, d.data_source_id, d.internal) for d in estate.dependencies]
    assert deps == [
        ("GENERIC_TAX_REPORTING_CUBE", "SOURCE_VIEW_01", "GENERIC_TAX_REPORTING_CUBE/SOURCE_VIEW_01", True),
        ("GENERIC_TAX_REPORTING_CUBE", "table:SCHEMA_1.TABLE_A", "GENERIC_TAX_REPORTING_CUBE/TABLE_A", False),
        ("GENERIC_TAX_REPORTING_CUBE", "table:SCHEMA_1.TABLE_B", "GENERIC_TAX_REPORTING_CUBE/TABLE_B", False),
        ("SOURCE_VIEW_01", "table:SCHEMA_1.TABLE_C", "SOURCE_VIEW_01/TABLE_C", False),
    ]

    leaves = {leaf.id: leaf for leaf in estate.leaf_sources}
    assert list(leaves) == ["table:SCHEMA_1.TABLE_A", "table:SCHEMA_1.TABLE_B", "table:SCHEMA_1.TABLE_C"]
    a = leaves["table:SCHEMA_1.TABLE_A"]
    assert (a.kind, a.schema_name, a.name, a.used_by) == (
        LeafKind.TABLE, "SCHEMA_1", "TABLE_A", ["GENERIC_TAX_REPORTING_CUBE"])
    assert leaves["table:SCHEMA_1.TABLE_C"].used_by == ["SOURCE_VIEW_01"]


def test_result_is_independent_of_input_order():
    forward = _results(FIXTURES / "graphical")
    backward = list(reversed(_results(FIXTURES / "graphical")))
    assert resolve_dependencies(forward) == resolve_dependencies(backward)


def test_estate_golden():
    actual = resolve_dependencies(_results(FIXTURES / "graphical")).model_dump_json(indent=2) + "\n"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_bytes(actual.encode("utf-8"))
    assert GOLDEN.exists(), f"missing {GOLDEN.name}; run UPDATE_GOLDEN=1 pytest tests/test_deps.py and review it"
    assert actual == GOLDEN.read_text(encoding="utf-8")


def test_graph_and_neighbours():
    estate = resolve_dependencies(_results(FIXTURES / "graphical"))
    g = estate_digraph(estate)
    assert g.nodes["SOURCE_VIEW_01"]["kind"] == "view"
    assert g.nodes["table:SCHEMA_1.TABLE_A"]["kind"] == "table"
    assert g.has_edge("SOURCE_VIEW_01", "GENERIC_TAX_REPORTING_CUBE")
    assert g.has_edge("table:SCHEMA_1.TABLE_C", "SOURCE_VIEW_01")

    assert upstream(estate, "GENERIC_TAX_REPORTING_CUBE") == ["SOURCE_VIEW_01"]
    assert downstream(estate, "SOURCE_VIEW_01") == ["GENERIC_TAX_REPORTING_CUBE"]
    assert upstream(estate, "SOURCE_VIEW_01") == []
    assert downstream(estate, "GENERIC_TAX_REPORTING_CUBE") == []
    assert upstream(estate, "NO_SUCH_VIEW") == []


def test_upstream_is_transitive(tmp_path):
    put(tmp_path, "V_1.calculationview", view_xml("V_1", table_source("TABLE_A")))
    put(tmp_path, "V_2.calculationview", view_xml("V_2", calc_source("V_1", "/pkg/calculationviews/V_1")))
    put(tmp_path, "V_3.calculationview", view_xml("V_3", calc_source("V_2", "/pkg/calculationviews/V_2")))
    estate = resolve_dependencies(_results(tmp_path))
    assert estate.deploy_order == ["V_1", "V_2", "V_3"]
    assert upstream(estate, "V_3") == ["V_1", "V_2"]
    assert downstream(estate, "V_1") == ["V_2", "V_3"]


# --- unresolved, cycles, self-loop --------------------------------------------------------

def test_consumer_alone_is_unresolved(tmp_path):
    shutil.copy(FIXTURES / MAIN, tmp_path)
    results = _results(tmp_path)
    estate = resolve_dependencies(results)

    assert all(d.resolved_view_id is None for d in _by_id(results, "GENERIC_TAX_REPORTING_CUBE").data_sources)
    (w,) = estate.warnings
    assert (w.code, w.severity, w.view_id) == (
        "UNRESOLVED_VIEW_DEPENDENCY", Severity.WARNING, "GENERIC_TAX_REPORTING_CUBE")
    assert "SOURCE_VIEW_01" in w.message

    leaf = next(x for x in estate.leaf_sources if x.id == "view:SOURCE_VIEW_01")
    assert (leaf.kind, leaf.name, leaf.schema_name, leaf.used_by) == (
        LeafKind.EXTERNAL_VIEW, "SOURCE_VIEW_01", None, ["GENERIC_TAX_REPORTING_CUBE"])
    dep = next(d for d in estate.dependencies if d.producer == "view:SOURCE_VIEW_01")
    assert dep.internal is False
    assert estate.deploy_order == ["GENERIC_TAX_REPORTING_CUBE"]


def test_estate_cycle():
    results = _results(FIXTURES / "estate_cycle")
    estate = resolve_dependencies(results)
    assert estate.cycles == [["CYCLE_A", "CYCLE_B"]]
    (w,) = estate.warnings
    assert (w.code, w.severity, w.view_id) == ("CYCLE", Severity.ERROR, None)
    assert "CYCLE_A" in w.message and "CYCLE_B" in w.message
    assert estate.deploy_order == ["CYCLE_A", "CYCLE_B"]
    assert {r.data_sources[0].resolved_view_id for r in results} == {"CYCLE_A", "CYCLE_B"}
    assert upstream(estate, "CYCLE_A") == ["CYCLE_B"]


def test_self_loop_is_a_cycle(tmp_path):
    put(tmp_path, "SELF_1.calculationview",
        view_xml("SELF_1", calc_source("SELF_1", "/pkg/calculationviews/SELF_1")))
    put(tmp_path, "V_2.calculationview", view_xml("V_2", table_source("TABLE_A")))
    estate = resolve_dependencies(_results(tmp_path))
    assert estate.cycles == [["SELF_1"]]
    assert _codes(estate) == ["CYCLE"]
    assert estate.deploy_order == ["SELF_1", "V_2"]
    assert estate.dependencies[0].internal is True


def test_cycle_members_deploy_after_their_producers(tmp_path):
    # Z_1 feeds the cycle; the cycle feeds A_1. Lexicographic order alone would put A_1 first.
    put(tmp_path, "Z_1.calculationview", view_xml("Z_1", table_source("TABLE_A")))
    put(tmp_path, "C_1.calculationview", view_xml(
        "C_1", calc_source("C_2", "/pkg/calculationviews/C_2"), calc_source("Z_1", "/pkg/calculationviews/Z_1")))
    put(tmp_path, "C_2.calculationview", view_xml("C_2", calc_source("C_1", "/pkg/calculationviews/C_1")))
    put(tmp_path, "A_1.calculationview", view_xml("A_1", calc_source("C_2", "/pkg/calculationviews/C_2")))
    estate = resolve_dependencies(_results(tmp_path))
    assert estate.cycles == [["C_1", "C_2"]]
    assert estate.deploy_order == ["Z_1", "C_1", "C_2", "A_1"]


# --- duplicates, ambiguity, failed views, leaf kinds ------------------------------------

def test_duplicate_view_id(tmp_path):
    put(tmp_path, "b/V_1.calculationview", view_xml("V_1", table_source("TABLE_B")))
    put(tmp_path, "a/V_1.calculationview", view_xml("V_1", table_source("TABLE_A")))
    results = _results(tmp_path)
    for order in (results, list(reversed(results))):
        estate = resolve_dependencies(order)
        assert estate.views == ["V_1"]
        assert estate.deploy_order == ["V_1"]
        (w,) = estate.warnings
        assert (w.code, w.severity, w.view_id) == ("DUPLICATE_VIEW_ID", Severity.ERROR, "V_1")
        # the first in sorted order (package a) wins; the loser contributes no dependencies
        assert [d.producer for d in estate.dependencies] == ["table:SCHEMA_1.TABLE_A"]


def test_ambiguous_match_broken_by_package(tmp_path):
    put(tmp_path, "p1/V_1.calculationview", view_xml("V_1", table_source("TABLE_A")))
    put(tmp_path, "p2/V_1.calculationview", view_xml("V_1", table_source("TABLE_B")))
    put(tmp_path, "c/CONSUMER_1.calculationview",
        view_xml("CONSUMER_1", calc_source("V_1", "/p2/calculationviews/V_1")))
    results = _results(tmp_path)
    estate = resolve_dependencies(results)
    consumer = next(r for r in results if r.view.id == "CONSUMER_1")
    assert consumer.data_sources[0].resolved_view_id == "V_1"
    assert _codes(estate) == ["DUPLICATE_VIEW_ID"]
    dep = next(d for d in estate.dependencies if d.consumer == "CONSUMER_1")
    assert (dep.producer, dep.internal) == ("V_1", True)
    assert estate.deploy_order == ["V_1", "CONSUMER_1"]


def test_ambiguous_match_without_package_winner(tmp_path):
    put(tmp_path, "p1/V_1.calculationview", view_xml("V_1", table_source("TABLE_A")))
    put(tmp_path, "p2/V_1.calculationview", view_xml("V_1", table_source("TABLE_B")))
    put(tmp_path, "CONSUMER_1.calculationview",
        view_xml("CONSUMER_1", calc_source("V_1", "/p3/calculationviews/V_1")))
    results = _results(tmp_path)
    estate = resolve_dependencies(results)
    consumer = next(r for r in results if r.view.id == "CONSUMER_1")
    assert consumer.data_sources[0].resolved_view_id is None
    assert sorted(_codes(estate)) == ["AMBIGUOUS_DEPENDENCY", "DUPLICATE_VIEW_ID"]
    amb = next(w for w in estate.warnings if w.code == "AMBIGUOUS_DEPENDENCY")
    assert (amb.severity, amb.view_id) == (Severity.WARNING, "CONSUMER_1")
    dep = next(d for d in estate.dependencies if d.consumer == "CONSUMER_1")
    assert (dep.producer, dep.internal) == ("view:V_1", False)


def test_nested_package_matches_dotted_uri(tmp_path):
    put(tmp_path, "a/b/V_1.calculationview", view_xml("V_1", table_source("TABLE_A")))
    put(tmp_path, "a/c/V_1.calculationview", view_xml("V_1", table_source("TABLE_B")))
    put(tmp_path, "CONSUMER_1.calculationview",
        view_xml("CONSUMER_1", calc_source("V_1", "/a.b/calculationviews/V_1")))
    results = _results(tmp_path)
    resolve_dependencies(results)
    consumer = next(r for r in results if r.view.id == "CONSUMER_1")
    assert consumer.data_sources[0].resolved_view_id == "V_1"


def test_failed_view_is_listed_without_dependencies(tmp_path):
    put(tmp_path, "JUNK_1.calculationview", "not xml at all")
    put(tmp_path, "V_1.calculationview", view_xml("V_1", table_source("TABLE_A")))
    results = _results(tmp_path)
    assert _by_id(results, "JUNK_1").view.parse_status is ParseStatus.FAILED
    estate = resolve_dependencies(results)
    assert estate.views == ["JUNK_1", "V_1"]
    assert estate.deploy_order == ["JUNK_1", "V_1"]
    assert [d.consumer for d in estate.dependencies] == ["V_1"]
    assert estate.warnings == []


def test_leaf_kinds(tmp_path):
    put(tmp_path, "V_1.calculationview", view_xml(
        "V_1",
        table_source("TABLE_A", schema=None),
        _source("TF_1", "TABLE_FUNCTION", '<columnObject schemaName="SCHEMA_1" columnObjectName="TF_1"/>'),
        _source("ODD_1", "SOMETHING_ELSE", ""),
        calc_source("NOWHERE_1", "/pkg/calculationviews/NOWHERE_1"),
    ))
    estate = resolve_dependencies(_results(tmp_path))
    kinds = {leaf.id: leaf.kind for leaf in estate.leaf_sources}
    assert kinds == {
        "table:TABLE_A": LeafKind.TABLE,
        "table_function:SCHEMA_1.TF_1": LeafKind.TABLE_FUNCTION,
        "unknown:V_1/ODD_1": LeafKind.UNKNOWN,
        "view:NOWHERE_1": LeafKind.EXTERNAL_VIEW,
    }
    assert [w.code for w in estate.warnings] == ["UNRESOLVED_VIEW_DEPENDENCY"]


def test_calc_view_without_uri_matches_by_name(tmp_path):
    put(tmp_path, "V_1.calculationview", view_xml("V_1", table_source("TABLE_A")))
    put(tmp_path, "V_2.calculationview",
        view_xml("V_2", _source("V_1", "CALCULATION_VIEW", "")))
    results = _results(tmp_path)
    estate = resolve_dependencies(results)
    assert _by_id(results, "V_2").data_sources[0].resolved_view_id == "V_1"
    assert estate.deploy_order == ["V_1", "V_2"]


def test_warnings_are_deterministic(tmp_path):
    put(tmp_path, "V_1.calculationview", view_xml(
        "V_1", calc_source("MISSING_2", "/pkg/calculationviews/MISSING_2"),
        calc_source("MISSING_1", "/pkg/calculationviews/MISSING_1")))
    results = _results(tmp_path)
    first = resolve_dependencies(results)
    second = resolve_dependencies(list(reversed(results)))
    assert first.warnings == second.warnings
    assert [w.message for w in first.warnings] == sorted(w.message for w in first.warnings)


@pytest.mark.parametrize("missing", ["", "/", "/pkg/calculationviews/"])
def test_odd_resource_uri_falls_back_to_name(tmp_path, missing):
    put(tmp_path, "V_1.calculationview", view_xml("V_1", table_source("TABLE_A")))
    put(tmp_path, "V_2.calculationview", view_xml("V_2", calc_source("V_1", missing)))
    results = _results(tmp_path)
    resolve_dependencies(results)
    assert _by_id(results, "V_2").data_sources[0].resolved_view_id == "V_1"


def test_rerun_clears_stale_resolution():
    results = _results(FIXTURES / "graphical")
    resolve_dependencies(results)
    consumer = _by_id(results, "GENERIC_TAX_REPORTING_CUBE")
    calc = next(d for d in consumer.data_sources if d.kind is DataSourceKind.CALC_VIEW)
    assert calc.resolved_view_id == "SOURCE_VIEW_01"

    estate = resolve_dependencies([consumer])
    assert calc.resolved_view_id is None
    assert _codes(estate) == ["UNRESOLVED_VIEW_DEPENDENCY"]


def test_failed_view_never_wins_duplicate_id(tmp_path):
    # The failed copy sorts first by package ("a" < "b") but must still lose.
    put(tmp_path, "a/V_1.calculationview", "not xml at all")
    put(tmp_path, "b/V_1.calculationview", view_xml("V_1", table_source("TABLE_A")))
    results = _results(tmp_path)
    assert [r.view.parse_status for r in results] == [ParseStatus.FAILED, ParseStatus.OK]
    for order in (results, list(reversed(results))):
        estate = resolve_dependencies(order)
        assert [d.producer for d in estate.dependencies] == ["table:SCHEMA_1.TABLE_A"]
        (w,) = estate.warnings
        assert w.code == "DUPLICATE_VIEW_ID"
        assert w.message.endswith("dependencies taken from the copy in b")
