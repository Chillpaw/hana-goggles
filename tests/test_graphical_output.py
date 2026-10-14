import pytest
from conftest import MAIN
from helpers import codes, column, node

from app.ir.models import ColumnKind, ColumnMapItem, NodeType, ParamUsage, ParseStatus, ViewType
from app.parsers.dispatch import parse_bytes

V = "GENERIC_TAX_REPORTING_CUBE"
NS = ('xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
      'xmlns:Calculation="http://www.sap.com/ndb/BiModelCalculation.ecore"')
NO_WRAPPER = f"""<?xml version="1.0" encoding="UTF-8"?>
<Calculation:scenario {NS} schemaVersion="2.3" id="NO_WRAPPER" dataCategory="DIMENSION">
  <dataSources>
    <DataSource id="TABLE_A" type="DATA_BASE_TABLE">
      <columnObject schemaName="SCHEMA_1" columnObjectName="TABLE_A"/>
    </DataSource>
  </dataSources>
  <calculationView xsi:type="Calculation:ProjectionView" id="Projection_1">
    <viewAttributes><viewAttribute id="COL_1"/></viewAttributes>
    <input node="#TABLE_A"><mapping xsi:type="Calculation:AttributeMapping" target="COL_1" source="COL_1"/></input>
  </calculationView>
  <logicalModel id="Projection_1">
    <attributes><attribute id="COL_1"><keyMapping columnObjectName="Projection_1" columnName="COL_1"/></attribute></attributes>
  </logicalModel>
  EXTRA
</Calculation:scenario>"""
SCRIPTED_STUB = f"""<?xml version="1.0" encoding="UTF-8"?>
<Calculation:scenario {NS} schemaVersion="2.3" id="SCRIPTED_STUB" dataCategory="CUBE">
  <calculationViews>
    <calculationView xsi:type="Calculation:SqlScriptView" id="Script_View">
      <viewAttributes><viewAttribute id="COL_1"/></viewAttributes>
      <definition>BEGIN var_out = SELECT "COL_1" FROM "SCHEMA_1"."TABLE_A"; END</definition>
    </calculationView>
  </calculationViews>
  <logicalModel id="Script_View">
    <attributes><attribute id="COL_1"><keyMapping columnObjectName="Script_View" columnName="COL_1"/></attribute></attributes>
  </logicalModel>
</Calculation:scenario>"""


def parse_text(text: str):
    return parse_bytes(text.encode(), file_name="inline.calculationview")


def test_logical_model_becomes_semantics_node(parse_fixture):
    semantics = node(parse_fixture(MAIN), "Semantics")
    assert semantics.node_type is NodeType.OUTPUT
    assert semantics.id == f"{V}/Semantics"
    assert [c.name for c in semantics.columns] == ["COL_1", "COL_3", "COL_5", "AMT_1", "CC_1", "CC_2", "CM_1"]
    assert column(semantics, "COL_1").kind is ColumnKind.ATTRIBUTE
    assert column(semantics, "AMT_1").kind is ColumnKind.MEASURE
    assert column(semantics, "AMT_1").aggregation == "sum"


def test_calculated_measure_has_expression(parse_fixture):
    cm = column(node(parse_fixture(MAIN), "Semantics"), "CM_1")
    assert cm.kind is ColumnKind.MEASURE
    assert cm.expression.text == '"AMT_1" - "CC_1"'
    assert cm.expression.ast.value == "-"


def test_semantics_edge_carries_key_and_measure_mappings(parse_fixture):
    edges = [e for e in parse_fixture(MAIN).edges if e.to_node == f"{V}/Semantics"]
    assert len(edges) == 1
    assert edges[0].from_node == f"{V}/Aggregation_1"
    assert [m.target for m in edges[0].column_map] == ["COL_1", "COL_3", "COL_5", "AMT_1", "CC_1", "CC_2"]
    assert ColumnMapItem(target="CC_2", source="CC_2") in edges[0].column_map


def test_main_fixture_is_fully_understood(parse_fixture):
    result = parse_fixture(MAIN)
    assert codes(result) == []
    assert result.view.parse_status is ParseStatus.OK
    assert result.view.coverage_pct == 100.0
    assert len(result.nodes) == 8
    assert len(result.edges) == 7


@pytest.mark.parametrize("rel, status, coverage, expected_codes", [
    ("malformed/truncated.calculationview", ParseStatus.FAILED, 0.0, ["XML_SYNTAX"]),
    ("malformed/unknown_type.calculationview", ParseStatus.PARTIAL, 75.0, ["UNKNOWN_NODE_TYPE"]),
    ("malformed/bad_expression.calculationview", ParseStatus.PARTIAL, 66.7, ["EXPR_PARSE_FAILED"]),
])
def test_malformed_fixtures_degrade_gracefully(parse_fixture, rel, status, coverage, expected_codes):
    result = parse_fixture(rel)
    assert result.view.parse_status is status
    assert result.view.coverage_pct == coverage
    assert codes(result) == expected_codes


def test_calculation_views_without_wrapper_are_parsed():
    result = parse_text(NO_WRAPPER.replace("EXTRA", ""))
    assert codes(result) == []
    assert node(result, "Projection_1").node_type is NodeType.PROJECTION
    assert {(e.from_node, e.to_node) for e in result.edges} == {
        ("NO_WRAPPER/TABLE_A", "NO_WRAPPER/Projection_1"),
        ("NO_WRAPPER/Projection_1", "NO_WRAPPER/Semantics"),
    }


def test_unknown_root_element_is_reported_not_dropped():
    result = parse_text(NO_WRAPPER.replace("EXTRA", "<executionHints/>"))
    assert codes(result) == ["UNKNOWN_ELEMENT"]
    assert "executionHints" in result.warnings[0].message
    assert result.view.parse_status is ParseStatus.PARTIAL


def test_non_empty_private_data_foundation_is_flagged():
    text = NO_WRAPPER.replace("EXTRA", "").replace(
        "</attributes>",
        "</attributes><privateDataFoundation><tableProxies><tableProxy/></tableProxies></privateDataFoundation>",
    )
    result = parse_text(text)
    assert codes(result) == ["PRIVATE_DATA_FOUNDATION_DEFERRED"]
    assert node(result, "Semantics").understood is False


def test_missing_logical_model_is_an_error():
    text = NO_WRAPPER.replace("EXTRA", "")
    text = text[: text.index("<logicalModel")] + text[text.index("</logicalModel>") + len("</logicalModel>"):]
    result = parse_text(text)
    assert codes(result) == ["MISSING_LOGICAL_MODEL"]


def test_scripted_view_is_detected_and_kept_opaque_until_m2():
    result = parse_text(SCRIPTED_STUB)
    assert result.view.view_type is ViewType.SCRIPTED
    assert node(result, "Script_View").node_type is NodeType.OPAQUE
    assert codes(result) == ["SCRIPTED_DEFERRED"]
    assert ("SCRIPTED_STUB/Script_View", "SCRIPTED_STUB/Semantics") in {(e.from_node, e.to_node) for e in result.edges}


def test_calculated_measure_parameter_usage_is_recorded():
    text = NO_WRAPPER.replace("EXTRA", "").replace(
        '<dataSources>',
        '<localVariables><variable id="IP_X" parameter="true"><variableProperties datatype="INTEGER"/></variable></localVariables><dataSources>',
    ).replace(
        "</attributes>",
        '</attributes><calculatedMeasures><measure id="CM_1" aggregationType="sum" datatype="INTEGER">'
        '<formula>$$IP_X$$ * 2</formula></measure></calculatedMeasures>',
    )
    params = parse_text(text).parameters
    assert [(u.node_id, u.usage) for u in params[0].used_in] == [("NO_WRAPPER/Semantics", ParamUsage.CALCULATION)]


def test_unexpected_child_of_output_attribute_is_reported():
    text = NO_WRAPPER.replace("EXTRA", "").replace("</attribute>", "<unknownThing/></attribute>")
    assert codes(parse_text(text)) == ["UNKNOWN_ELEMENT"]


def test_hidden_output_attribute_is_info_only():
    text = NO_WRAPPER.replace("EXTRA", "").replace('<attribute id="COL_1">', '<attribute id="COL_1" hidden="true">')
    result = parse_text(text)
    assert "HIDDEN_COLUMN" in codes(result)
    assert result.view.parse_status is ParseStatus.OK


def test_non_simple_measure_type_is_deferred():
    text = NO_WRAPPER.replace("EXTRA", "").replace(
        "</attributes>",
        '</attributes><baseMeasures><measure id="AMT_1" aggregationType="sum" measureType="amount">'
        '<measureMapping columnObjectName="Projection_1" columnName="COL_1"/></measure></baseMeasures>',
    )
    result = parse_text(text)
    assert codes(result) == ["MEASURE_TYPE_DEFERRED"]
    assert node(result, "Semantics").understood is False


def _probe(old: str, new: str):
    return parse_text(NO_WRAPPER.replace("EXTRA", "").replace(old, new))


def test_unknown_child_of_view_attribute_is_reported_and_node_not_understood():
    result = _probe('<viewAttribute id="COL_1"/>',
                    '<viewAttribute id="COL_1"><filter xsi:type="AccessControl:SingleValueFilter" '
                    'operator="EQ" value="X"/></viewAttribute>')
    assert codes(result) == ["UNKNOWN_ELEMENT"]
    assert node(result, "Projection_1").understood is False
    assert result.view.parse_status is ParseStatus.PARTIAL
    assert result.view.coverage_pct < 100


def test_unknown_child_of_input_is_reported_and_node_not_understood():
    result = _probe("</input>", "<surprise/></input>")
    assert codes(result) == ["UNKNOWN_ELEMENT"]
    assert node(result, "Projection_1").understood is False


@pytest.mark.parametrize("view_type", ["ProjectionView", "AggregationView"])
def test_unknown_node_level_child_marks_node_not_understood(view_type):
    result = parse_text(
        NO_WRAPPER.replace("EXTRA", "").replace("ProjectionView", view_type)
        .replace("</viewAttributes>", "</viewAttributes><restrictedViewAttributes/>"))
    assert codes(result) == ["UNKNOWN_ELEMENT"]
    assert node(result, "Projection_1").understood is False


@pytest.mark.parametrize("old,new", [
    ('<DataSource id="TABLE_A" type="DATA_BASE_TABLE">', '<DataSource id="TABLE_A" type="DATA_BASE_TABLE"><oddity/>'),
    ('<dataSources>', '<localVariables><variable id="V_1"><oddity/></variable></localVariables><dataSources>'),
    ('<dataSources>', '<localVariables><variable id="V_1"><variableProperties><oddity/></variableProperties>'
                      '</variable></localVariables><dataSources>'),
    ('<viewAttributes>', '<calculatedViewAttributes><calculatedViewAttribute id="CC_1" datatype="INTEGER">'
                         '<oddity/><formula>1</formula></calculatedViewAttribute></calculatedViewAttributes><viewAttributes>'),
])
def test_unknown_children_of_other_elements_are_reported(old, new):
    result = _probe(old, new)
    assert codes(result) == ["UNKNOWN_ELEMENT"]
