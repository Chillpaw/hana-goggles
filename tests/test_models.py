import pytest
from pydantic import ValidationError

from app.ir.models import (
    Column, ColumnKind, ColumnMapItem, DataCategory, Edge, Expression, ExpressionLang,
    ExprNode, Node, NodeType, ParseResult, ParseStatus, View, ViewType, make_id,
)


def test_make_id_joins_parts_with_slash():
    assert make_id("V", "N", "C") == "V/N/C"


def test_parse_result_round_trips_through_json():
    view = View(id="V", name="V", view_type=ViewType.GRAPHICAL, data_category=DataCategory.CUBE,
                schema_version="2.3", file_hash="abc", parse_status=ParseStatus.OK, coverage_pct=100.0)
    expr = Expression(
        text='"A" * 2', lang=ExpressionLang.COLUMN_ENGINE,
        ast=ExprNode(kind="binary", value="*",
                     args=[ExprNode(kind="column", value="A"), ExprNode(kind="number", value="2")]),
    )
    node = Node(id="V/P", view_id="V", node_type=NodeType.PROJECTION, name="P", raw="<x/>",
                columns=[Column(id="V/P/C", name="C", kind=ColumnKind.ATTRIBUTE, expression=expr)])
    edge = Edge(from_node="V/T", to_node="V/P",
                column_map=[ColumnMapItem(target="C", source="A"), ColumnMapItem(target="K", constant="X")])
    result = ParseResult(view=view, nodes=[node], edges=[edge])

    assert ParseResult.model_validate_json(result.model_dump_json()) == result


def test_ir_models_reject_unknown_fields():
    with pytest.raises(ValidationError):
        Column(id="a", name="a", bogus=1)


def test_enums_serialise_as_lowercase_values():
    node = Node(id="V/P", view_id="V", node_type=NodeType.OPAQUE, name="P", raw="")
    assert '"node_type":"opaque"' in node.model_dump_json()
