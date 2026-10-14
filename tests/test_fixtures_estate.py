"""Hand-written checks for the M3 dependency fixtures: the producer view the main
fixture reads (SOURCE_VIEW_01) and a two-view cycle (CYCLE_A <-> CYCLE_B)."""
from helpers import column, node

from app.ir.models import (
    ColumnKind, DataCategory, DataSourceKind, NodeType, ParamUsage, ParseStatus, ViewType,
)

PRODUCER = "graphical/SOURCE_VIEW_01.calculationview"
MAIN = "graphical/GENERIC_TAX_REPORTING_CUBE.calculationview"


def _types(result):
    return {n.name: n.node_type for n in result.nodes if n.node_type is not NodeType.DATASOURCE}


def test_producer_parses_cleanly(parse_fixture):
    result = parse_fixture(PRODUCER)
    v = result.view
    assert (v.id, v.name) == ("SOURCE_VIEW_01", "SOURCE_VIEW_01")
    assert v.view_type is ViewType.GRAPHICAL
    assert v.data_category is DataCategory.CUBE
    assert v.parse_status is ParseStatus.OK
    assert v.coverage_pct == 100
    assert result.warnings == []


def test_producer_nodes_and_table_source(parse_fixture):
    result = parse_fixture(PRODUCER)
    assert _types(result) == {"Projection_1": NodeType.PROJECTION, "Semantics": NodeType.OUTPUT}

    (ds,) = result.data_sources
    assert ds.id == "SOURCE_VIEW_01/TABLE_C"
    assert (ds.kind, ds.schema_name, ds.name, ds.resource_uri) == (
        DataSourceKind.TABLE, "SCHEMA_1", "TABLE_C", None)

    pairs = {(e.from_node, e.to_node) for e in result.edges}
    assert ("SOURCE_VIEW_01/TABLE_C", "SOURCE_VIEW_01/Projection_1") in pairs


def test_producer_parameter_matches_consumer_target_variable(parse_fixture):
    producer = parse_fixture(PRODUCER)
    (param,) = producer.parameters
    assert (param.name, param.datatype, param.length, param.mandatory) == ("IP_YEAR", "NVARCHAR", 4, True)
    assert any(u.usage is ParamUsage.FILTER for u in param.used_in)

    consumer = parse_fixture(MAIN)
    assert {m.target_parameter for m in consumer.parameter_mappings} == {param.name}


def test_producer_output_publishes_what_consumer_reads(parse_fixture):
    producer = parse_fixture(PRODUCER)
    out = node(producer, "Semantics")
    assert {c.name for c in out.columns} == {"COL_1", "COL_2", "COL_3", "AMT_1"}
    assert column(out, "AMT_1").kind is ColumnKind.MEASURE
    assert column(out, "AMT_1").aggregation == "sum"
    assert column(out, "COL_1").kind is ColumnKind.ATTRIBUTE

    consumer = parse_fixture(MAIN)
    read = next(e for e in consumer.edges
                if e.from_node == "GENERIC_TAX_REPORTING_CUBE/SOURCE_VIEW_01")
    assert {m.source for m in read.column_map} <= {c.name for c in out.columns}


def test_cycle_views_read_each_other(parse_fixture):
    for me, other in (("CYCLE_A", "CYCLE_B"), ("CYCLE_B", "CYCLE_A")):
        result = parse_fixture(f"estate_cycle/{me}.calculationview")
        assert result.view.id == me
        assert result.view.parse_status is ParseStatus.OK
        assert result.view.coverage_pct == 100
        assert result.warnings == []
        assert _types(result) == {"Projection_1": NodeType.PROJECTION, "Semantics": NodeType.OUTPUT}

        (ds,) = result.data_sources
        assert ds.id == f"{me}/{other}"
        assert ds.kind is DataSourceKind.CALC_VIEW
        assert ds.name == other
        assert ds.resource_uri == f"/pkg.synthetic/calculationviews/{other}"
        assert ds.resolved_view_id is None
