from conftest import MAIN
from helpers import codes, column, node

from app.ir.models import (
    ColumnKind, ColumnMapItem, ExpressionLang, JoinCondition, NodeType, ParamUsage,
)

V = "GENERIC_TAX_REPORTING_CUBE"


def test_calculation_views_become_typed_nodes(parse_fixture):
    result = parse_fixture(MAIN)
    types = {n.name: n.node_type for n in result.nodes if n.node_type is not NodeType.DATASOURCE}
    expected = {
        "Projection_1": NodeType.PROJECTION,
        "Join_1": NodeType.JOIN,
        "Union_1": NodeType.UNION,
        "Aggregation_1": NodeType.AGGREGATION,
    }
    assert expected.items() <= types.items()  # Task 8 tightens this to an exact match


def test_inputs_become_edges(parse_fixture):
    pairs = {(e.from_node.split("/")[1], e.to_node.split("/")[1]) for e in parse_fixture(MAIN).edges}
    assert {
        ("SOURCE_VIEW_01", "Projection_1"),
        ("Projection_1", "Join_1"),
        ("TABLE_A", "Join_1"),
        ("Join_1", "Union_1"),
        ("TABLE_B", "Union_1"),
        ("Union_1", "Aggregation_1"),
    } <= pairs


def test_edge_carries_column_mappings_and_union_constants(parse_fixture):
    edges = {(e.from_node, e.to_node): e for e in parse_fixture(MAIN).edges}
    from_b = edges[(f"{V}/TABLE_B", f"{V}/Union_1")].column_map
    assert ColumnMapItem(target="COL_1", source="COL_1") in from_b
    assert ColumnMapItem(target="COL_5", constant="SRC_B") in from_b
    assert ColumnMapItem(target="CC_1", null=True) in from_b


def test_join_spec(parse_fixture):
    join = node(parse_fixture(MAIN), "Join_1").join
    assert join.join_type == "leftOuter"
    assert join.cardinality == "CN_1"
    assert join.left_node == f"{V}/Projection_1"
    assert join.right_node == f"{V}/TABLE_A"
    assert join.conditions == [JoinCondition(column="COL_1")]
    assert join.special is False


def test_view_attributes_and_aggregation(parse_fixture):
    agg = node(parse_fixture(MAIN), "Aggregation_1")
    assert column(agg, "AMT_1").kind is ColumnKind.MEASURE
    assert column(agg, "AMT_1").aggregation == "sum"
    assert column(agg, "COL_1").kind is ColumnKind.ATTRIBUTE
    assert column(agg, "COL_1").id == f"{V}/Aggregation_1/COL_1"


def test_calculated_column_keeps_text_and_ast(parse_fixture):
    cc = column(node(parse_fixture(MAIN), "Projection_1"), "CC_1")
    assert (cc.datatype, cc.length, cc.scale) == ("DECIMAL", 15, 2)
    assert cc.expression.text == "if(\"COL_2\" = 'X', \"AMT_1\", 0)"
    assert cc.expression.lang is ExpressionLang.COLUMN_ENGINE
    assert cc.expression.ast.kind == "call" and cc.expression.ast.value == "if"


def test_filter_is_parsed(parse_fixture):
    filters = node(parse_fixture(MAIN), "Projection_1").filters
    assert len(filters) == 1
    assert filters[0].expression.ast.args[1].kind == "param"


def test_parameter_usage_distinguishes_filter_from_calculation(parse_fixture):
    params = {p.name: p for p in parse_fixture(MAIN).parameters}
    assert [(u.node_id, u.usage) for u in params["IP_FISCAL_YEAR"].used_in] == [
        (f"{V}/Projection_1", ParamUsage.FILTER)]
    assert [(u.node_id, u.usage) for u in params["IP_RATE"].used_in] == [
        (f"{V}/Aggregation_1", ParamUsage.CALCULATION)]
    assert params["V_COMPANY"].used_in == []


def test_unknown_node_type_is_opaque_but_stays_connected(parse_fixture):
    result = parse_fixture("malformed/unknown_type.calculationview")
    fancy = node(result, "Fancy_1")
    assert fancy.node_type is NodeType.OPAQUE
    assert fancy.understood is False
    assert "FancyNewView" in fancy.raw
    assert codes(result) == ["UNKNOWN_NODE_TYPE"]
    assert any(e.from_node.endswith("/Projection_1") and e.to_node.endswith("/Fancy_1") for e in result.edges)


def test_unparseable_expression_is_kept_and_flagged(parse_fixture):
    result = parse_fixture("malformed/bad_expression.calculationview")
    projection = node(result, "Projection_1")
    cc = column(projection, "CC_1")
    assert cc.expression.text == "if(\"COL_1\" = 'X', 1"
    assert cc.expression.ast is None
    assert projection.understood is False
    assert codes(result) == ["EXPR_PARSE_FAILED"]


def test_sql_filter_language_comes_from_the_calculation_view():
    from app.parsers.dispatch import parse_bytes

    text = """<?xml version="1.0" encoding="UTF-8"?>
<Calculation:scenario xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:Calculation="http://www.sap.com/ndb/BiModelCalculation.ecore" schemaVersion="2.3" id="INLINE_VIEW" dataCategory="DEFAULT">
  <origin/>
  <dataSources>
    <DataSource id="TABLE_A" type="DATA_BASE_TABLE">
      <columnObject schemaName="SCHEMA_1" columnObjectName="TABLE_A"/>
    </DataSource>
  </dataSources>
  <calculationViews>
    <calculationView xsi:type="Calculation:ProjectionView" id="Projection_1" filterExpressionLanguage="SQL">
      <viewAttributes><viewAttribute id="COL_1"/></viewAttributes>
      <input node="#TABLE_A"><mapping xsi:type="Calculation:AttributeMapping" target="COL_1" source="COL_1"/></input>
      <filter>"COL_1" = 'X'</filter>
    </calculationView>
  </calculationViews>
</Calculation:scenario>"""
    result = parse_bytes(text.encode(), file_name="inline.calculationview")
    expression = node(result, "Projection_1").filters[0].expression
    assert expression.lang is ExpressionLang.SQL
    assert expression.ast is None
    assert "SQL_EXPR_DEFERRED" in codes(result)
