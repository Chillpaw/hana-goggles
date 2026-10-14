"""Plain-English node descriptions. Wording is pinned exactly: change it on purpose only."""
import pytest
from conftest import FIXTURES, MAIN
from helpers import node

from app.enrich.deps import resolve_dependencies
from app.generators.describe import NodeDescription, describe_node, describe_view, render_expression
from app.ir.models import (
    Column, ColumnKind, ColumnMapItem, DataCategory, DataSource, DataSourceKind, Edge, Estate,
    ExpressionLang, Expression, ExprNode, Filter, JoinCondition, JoinSpec, Node, NodeType, ParseResult,
    ParseStatus, View, ViewDependency, ViewType,
)

NOT_UNDERSTOOD = "Not fully understood by the parser: see warnings and raw XML."
CUBE_DETAIL = "CUBE: totals are computed at query time for whatever columns the consumer asks for."
SPECIAL = "HANA-specific join semantics: review before migrating."


# ---------------------------------------------------------------- expression helpers

def col(name):
    return ExprNode(kind="column", value=name)


def num(v):
    return ExprNode(kind="number", value=v)


def s(v):
    return ExprNode(kind="string", value=v)


def param(name):
    return ExprNode(kind="param", value=name)


def bi(op, *args):
    return ExprNode(kind="binary", value=op, args=list(args))


def un(op, arg):
    return ExprNode(kind="unary", value=op, args=[arg])


def call(name, *args):
    return ExprNode(kind="call", value=name, args=list(args))


def ce(ast, text="ignored"):
    return Expression(text=text, lang=ExpressionLang.COLUMN_ENGINE, ast=ast)


# ---------------------------------------------------------------- IR builders

V = "V"


def nid(name):
    return f"{V}/{name}"


def mk_node(name, node_type, columns=(), filters=(), join=None, understood=True):
    return Node(id=nid(name), view_id=V, node_type=node_type, name=name, raw="<x/>",
                columns=list(columns), filters=list(filters), join=join, understood=understood)


def attr(name, expression=None):
    return Column(id=nid(name), name=name, kind=ColumnKind.ATTRIBUTE, expression=expression)


def measure(name, aggregation="sum", expression=None):
    return Column(id=nid(name), name=name, kind=ColumnKind.MEASURE, aggregation=aggregation,
                  expression=expression)


def mk_result(nodes, edges=(), data_sources=(), category=DataCategory.DEFAULT):
    view = View(id=V, name=V, view_type=ViewType.GRAPHICAL, data_category=category, file_hash="0",
                parse_status=ParseStatus.OK, coverage_pct=100.0)
    return ParseResult(view=view, nodes=list(nodes), edges=list(edges), data_sources=list(data_sources))


def edge(a, b, column_map=()):
    return Edge(from_node=nid(a), to_node=nid(b), column_map=list(column_map))


def describe_one(target, nodes, edges=(), data_sources=(), estate=None, category=DataCategory.DEFAULT):
    result = mk_result(nodes, edges, data_sources, category)
    return describe_node(result, node(result, target), estate)


# ---------------------------------------------------------------- render_expression

def test_render_none_is_empty():
    assert render_expression(None) == ""


@pytest.mark.parametrize("ast, expected", [
    (col("AMT_1"), "AMT_1"),
    (num("0"), "0"),
    (num("1.5"), "1.5"),
    (s("X"), "'X'"),
    (s("it's"), "'it''s'"),
    (param("IP_RATE"), "input parameter IP_RATE"),
    (bi("=", col("COL_2"), s("X")), "COL_2 = 'X'"),
    (bi("<>", col("COL_2"), s("X")), "COL_2 <> 'X'"),
    (bi("!=", col("COL_2"), s("X")), "COL_2 != 'X'"),
    (bi("-", col("A"), col("B"), col("C")), "A - B - C"),
    (bi("and", bi("=", col("A"), num("1")), bi(">", col("B"), num("2")), bi("<", col("C"), num("3"))),
     "A = 1 and B > 2 and C < 3"),
    (bi("or", col("A"), col("B")), "A or B"),
    (un("not", col("A")), "not A"),
    (call("if", bi("=", col("COL_2"), s("X")), col("AMT_1"), num("0")), "if COL_2 = 'X' then AMT_1 else 0"),
    (call("leftstr", col("COL_1"), num("3")), "leftstr(COL_1, 3)"),
    (call("now"), "now()"),
    (call("if", col("A"), col("B")), "if(A, B)"),  # wrong arity: shown as a plain call
])
def test_render_basic(ast, expected):
    assert render_expression(ce(ast)) == expected


@pytest.mark.parametrize("ast, expected", [
    # lower precedence inside higher keeps parentheses
    (bi("*", bi("+", col("A"), col("B")), col("C")), "(A + B) * C"),
    (bi("*", col("C"), bi("+", col("A"), col("B"))), "C * (A + B)"),
    (bi("and", bi("or", col("A"), col("B")), col("C")), "(A or B) and C"),
    (bi("=", bi("+", col("A"), col("B")), col("C")), "A + B = C"),
    (bi("+", bi("*", col("A"), col("B")), col("C")), "A * B + C"),
    # same precedence: left side is a left fold already, right side keeps its grouping
    (bi("+", bi("-", col("A"), col("B")), col("C")), "A - B + C"),
    (bi("-", col("A"), bi("-", col("B"), col("C"))), "A - (B - C)"),
    (bi("/", col("A"), bi("*", col("B"), col("C"))), "A / (B * C)"),
    (bi("and", col("A"), bi("and", col("B"), col("C"))), "A and (B and C)"),
    # comparisons do not chain
    (bi("=", bi("=", col("A"), col("B")), col("C")), "(A = B) = C"),
    # unary minus
    (un("-", col("A")), "-A"),
    (un("-", num("5")), "-5"),
    (un("-", bi("+", col("A"), col("B"))), "-(A + B)"),
    (un("-", bi("*", col("A"), col("B"))), "-(A * B)"),
    (un("-", un("-", col("A"))), "-(-A)"),
    (bi("*", col("A"), un("-", col("B"))), "A * -B"),
    # not
    (un("not", bi("=", col("A"), num("1"))), "not (A = 1)"),
    (un("not", bi("and", col("A"), col("B"))), "not (A and B)"),
    (bi("and", un("not", col("A")), col("B")), "not A and B"),
    (bi("or", col("A"), un("not", bi("or", col("B"), col("C")))), "A or not (B or C)"),
    (un("not", un("not", col("A"))), "not not A"),
    # if as an operand is grouped; nested ifs in condition / then position are grouped
    (bi("+", call("if", col("A"), num("1"), num("2")), num("3")), "(if A then 1 else 2) + 3"),
    (call("if", col("A"), call("if", col("B"), num("1"), num("2")), num("3")),
     "if A then (if B then 1 else 2) else 3"),
    (call("if", col("A"), num("1"), call("if", col("B"), num("2"), num("3"))),
     "if A then 1 else if B then 2 else 3"),
    # call arguments need no grouping
    (call("round", bi("*", bi("+", col("A"), col("B")), num("2")), num("2")), "round((A + B) * 2, 2)"),
])
def test_render_parenthesisation(ast, expected):
    assert render_expression(ce(ast)) == expected


def test_render_unparsed_shows_raw_text():
    expr = Expression(text="if(\"COL_1\" = 'X', 1", lang=ExpressionLang.COLUMN_ENGINE, ast=None)
    assert render_expression(expr) == "`if(\"COL_1\" = 'X', 1` (not parsed)"


def test_render_sql_is_not_parsed_even_with_an_ast():
    expr = Expression(text='"COL_1" || \'X\'', lang=ExpressionLang.SQL, ast=col("COL_1"))
    assert render_expression(expr) == "`\"COL_1\" || 'X'` (not parsed)"


def test_render_unknown_operator_kept_verbatim():
    assert render_expression(ce(bi("||", col("A"), col("B")))) == "A || B"


# ---------------------------------------------------------------- the main fixture

@pytest.fixture
def cube(parse_fixture):
    return parse_fixture(MAIN)


def test_fixture_projection(cube):
    d = describe_node(cube, node(cube, "Projection_1"))
    assert d == NodeDescription(
        node_id="GENERIC_TAX_REPORTING_CUBE/Projection_1",
        headline="Takes 4 columns from SOURCE_VIEW_01.",
        details=["Keeps rows where COL_3 = input parameter IP_FISCAL_YEAR.",
                 "Adds CC_1 = if COL_2 = 'X' then AMT_1 else 0."],
    )


def test_fixture_join(cube):
    d = describe_node(cube, node(cube, "Join_1"))
    assert d.headline == "Left outer join of Projection_1 and TABLE_A on COL_1 (many-to-one)."
    assert d.details == []


def test_fixture_union(cube):
    d = describe_node(cube, node(cube, "Union_1"))
    assert d.headline == "Stacks rows from Join_1, TABLE_B."
    assert d.details == [
        "COL_5 is 'SRC_A' for rows from Join_1.",
        "CC_1 is empty (null) for rows from TABLE_B.",
        "COL_5 is 'SRC_B' for rows from TABLE_B.",
    ]


def test_fixture_aggregation(cube):
    d = describe_node(cube, node(cube, "Aggregation_1"))
    assert d.headline == "Sums AMT_1, CC_1 by COL_1, COL_3, COL_5."
    assert d.details == ["Adds CC_2 = AMT_1 * input parameter IP_RATE."]


def test_fixture_output(cube):
    d = describe_node(cube, node(cube, "Semantics"))
    assert d.headline == "Publishes 3 attributes and 4 measures as the view's output."
    assert d.details == ["Adds CM_1 = AMT_1 - CC_1.", CUBE_DETAIL]


def test_fixture_tables_without_estate(cube):
    assert describe_node(cube, node(cube, "TABLE_A")) == NodeDescription(
        node_id="GENERIC_TAX_REPORTING_CUBE/TABLE_A", headline="Reads table SCHEMA_1.TABLE_A.", details=[])
    d = describe_node(cube, node(cube, "SOURCE_VIEW_01"))
    assert d.headline == "Reads calculation view SOURCE_VIEW_01."
    assert d.details == []  # no estate, nothing resolved: no claim either way


def test_fixture_calc_view_resolved_in_estate(parse_fixture):
    consumer = parse_fixture(MAIN)
    producer = parse_fixture("graphical/SOURCE_VIEW_01.calculationview")
    estate = resolve_dependencies([consumer, producer])
    d = describe_node(consumer, node(consumer, "SOURCE_VIEW_01"), estate)
    assert d.headline == "Reads calculation view SOURCE_VIEW_01."
    assert d.details == ["Defined in this project."]
    # tables never get a project claim
    assert describe_node(consumer, node(consumer, "TABLE_A"), estate).details == []


def test_fixture_calc_view_external_in_estate(parse_fixture):
    consumer = parse_fixture(MAIN)
    estate = resolve_dependencies([consumer])
    d = describe_node(consumer, node(consumer, "SOURCE_VIEW_01"), estate)
    assert d.details == ["Not in this project (external)."]


def test_resolution_read_from_estate_alone():
    """A result loaded without `resolved_view_id` still resolves through the estate's dependency."""
    ds = DataSource(id=nid("SV"), kind=DataSourceKind.CALC_VIEW, name="SV", resource_uri="/p/calculationviews/SV")
    estate = Estate(views=["SV", V], dependencies=[
        ViewDependency(consumer=V, producer="SV", data_source_id=nid("SV"), internal=True)])
    d = describe_one("SV", [mk_node("SV", NodeType.DATASOURCE)], data_sources=[ds], estate=estate)
    assert d.details == ["Defined in this project."]


def test_describe_view_order_and_full_text(cube):
    descriptions = describe_view(cube)
    assert [d.node_id.rpartition("/")[2] for d in descriptions] == [
        "SOURCE_VIEW_01", "TABLE_A", "TABLE_B", "Projection_1", "Join_1", "Union_1", "Aggregation_1", "Semantics"]
    assert all(isinstance(d, NodeDescription) for d in descriptions)


# ---------------------------------------------------------------- malformed fixtures

def test_bad_expression_not_parsed(parse_fixture):
    result = parse_fixture("malformed/bad_expression.calculationview")
    d = describe_node(result, node(result, "Projection_1"))
    assert d.headline == "Takes 1 columns from TABLE_A."
    assert d.details == ["Adds CC_1 = `if(\"COL_1\" = 'X', 1` (not parsed).", NOT_UNDERSTOOD]


def test_unknown_type_opaque(parse_fixture):
    result = parse_fixture("malformed/unknown_type.calculationview")
    d = describe_node(result, node(result, "Fancy_1"))
    assert d.headline == "Does something the parser does not recognise, reading Projection_1."
    assert d.details == [NOT_UNDERSTOOD]


# ---------------------------------------------------------------- datasource variants

@pytest.mark.parametrize("kind, schema, name, headline", [
    (DataSourceKind.TABLE, "SCHEMA_1", "TABLE_A", "Reads table SCHEMA_1.TABLE_A."),
    (DataSourceKind.TABLE, None, "TABLE_A", "Reads table TABLE_A."),
    (DataSourceKind.TABLE_FUNCTION, "SCHEMA_1", "TF_1", "Reads table function SCHEMA_1.TF_1."),
    (DataSourceKind.TABLE_FUNCTION, None, "TF_1", "Reads table function TF_1."),
    (DataSourceKind.CALC_VIEW, None, "VIEW_1", "Reads calculation view VIEW_1."),
    (DataSourceKind.CDS, None, "ENTITY_1", "Reads CDS entity ENTITY_1."),
    (DataSourceKind.UNKNOWN, None, "THING_1", "Reads source THING_1 (unknown kind)."),
])
def test_datasource_variants(kind, schema, name, headline):
    ds = DataSource(id=nid("DS"), kind=kind, schema_name=schema, name=name)
    d = describe_one("DS", [mk_node("DS", NodeType.DATASOURCE)], data_sources=[ds])
    assert d.headline == headline


def test_datasource_unknown_kind_not_understood_marker():
    ds = DataSource(id=nid("DS"), kind=DataSourceKind.UNKNOWN, name="THING_1")
    d = describe_one("DS", [mk_node("DS", NodeType.DATASOURCE, understood=False)], data_sources=[ds])
    assert d.details == [NOT_UNDERSTOOD]


def test_datasource_without_a_data_source_record():
    d = describe_one("DS", [mk_node("DS", NodeType.DATASOURCE)])
    assert d.headline == "Reads source DS (unknown kind)."


def test_calc_view_resolved_flag_without_estate():
    ds = DataSource(id=nid("DS"), kind=DataSourceKind.CALC_VIEW, name="VIEW_1", resolved_view_id="VIEW_1")
    d = describe_one("DS", [mk_node("DS", NodeType.DATASOURCE)], data_sources=[ds])
    assert d.details == ["Defined in this project."]


# ---------------------------------------------------------------- joins

JOIN_INPUTS = [mk_node("L", NodeType.PROJECTION), mk_node("R", NodeType.PROJECTION)]


def join_desc(join_type, cardinality="CN_1", conditions=("COL_1",), special=False):
    spec = JoinSpec(join_type=join_type, cardinality=cardinality, left_node=nid("L"), right_node=nid("R"),
                    conditions=[JoinCondition(column=c) for c in conditions], special=special)
    return describe_one("J", [*JOIN_INPUTS, mk_node("J", NodeType.JOIN, join=spec)],
                        edges=[edge("L", "J"), edge("R", "J")])


@pytest.mark.parametrize("join_type, phrase", [
    ("inner", "Inner join"),
    ("leftOuter", "Left outer join"),
    ("rightOuter", "Right outer join"),
    ("fullOuter", "Full outer join"),
    ("referential", "Referential join"),
    ("textTable", "Text join"),
    ("spatialJoin", "Join (spatialJoin)"),
])
def test_join_phrases(join_type, phrase):
    assert join_desc(join_type).headline == f"{phrase} of L and R on COL_1 (many-to-one)."


@pytest.mark.parametrize("cardinality, suffix", [
    ("CN_1", " (many-to-one)"),
    ("C1_1", " (one-to-one)"),
    ("C1_N", " (one-to-many)"),
    ("CN_N", " (many-to-many)"),
    (None, ""),
    ("C9_9", " (cardinality C9_9)"),
])
def test_join_cardinality(cardinality, suffix):
    assert join_desc("inner", cardinality).headline == f"Inner join of L and R on COL_1{suffix}."


def test_join_several_columns():
    assert join_desc("inner", conditions=("COL_1", "COL_2")).headline == \
        "Inner join of L and R on COL_1, COL_2 (many-to-one)."


def test_join_without_columns_is_flagged():
    d = join_desc("inner", conditions=())
    assert d.headline == "Inner join of L and R (many-to-one)."
    assert d.details == ["No join columns were found."]


@pytest.mark.parametrize("join_type", ["referential", "textTable"])
def test_special_join_detail(join_type):
    assert join_desc(join_type, special=True).details == [SPECIAL]


def test_join_without_spec_falls_back_to_inputs():
    d = describe_one("J", [*JOIN_INPUTS, mk_node("J", NodeType.JOIN)], edges=[edge("L", "J"), edge("R", "J")])
    assert d.headline == "Join (unknown) of L and R."


# ---------------------------------------------------------------- unions

def test_union_constants_and_null():
    nodes = [mk_node("A", NodeType.PROJECTION), mk_node("B", NodeType.PROJECTION), mk_node("U", NodeType.UNION)]
    edges = [
        edge("A", "U", [ColumnMapItem(target="COL_1", source="COL_1"),
                        ColumnMapItem(target="COL_5", constant="SRC_A")]),
        edge("B", "U", [ColumnMapItem(target="CC_1", null=True),
                        ColumnMapItem(target="COL_6", constant="it's")]),
    ]
    d = describe_one("U", nodes, edges)
    assert d.headline == "Stacks rows from A, B."
    assert d.details == [
        "COL_5 is 'SRC_A' for rows from A.",
        "CC_1 is empty (null) for rows from B.",
        "COL_6 is 'it''s' for rows from B.",
    ]


def test_union_three_inputs():
    nodes = [mk_node(n, NodeType.PROJECTION) for n in ("A", "B", "C")] + [mk_node("U", NodeType.UNION)]
    d = describe_one("U", nodes, [edge("A", "U"), edge("B", "U"), edge("C", "U")])
    assert d.headline == "Stacks rows from A, B, C."


# ---------------------------------------------------------------- aggregations

def agg_desc(*columns):
    return describe_one("G", [mk_node("A", NodeType.PROJECTION), mk_node("G", NodeType.AGGREGATION, columns)],
                        [edge("A", "G")])


@pytest.mark.parametrize("kind, verb", [
    ("sum", "Sums"),
    ("min", "Takes the minimum of"),
    ("max", "Takes the maximum of"),
    ("count", "Counts"),
    ("avg", "Averages"),
    ("SUM", "Sums"),
    ("stddev", "Aggregates AMT_1 using stddev"),
])
def test_aggregation_verbs(kind, verb):
    expected = verb if verb.startswith("Aggregates") else f"{verb} AMT_1"
    assert agg_desc(attr("COL_1"), measure("AMT_1", kind)).headline == f"{expected} by COL_1."


def test_aggregation_measure_without_kind():
    assert agg_desc(attr("COL_1"), measure("AMT_1", None)).headline == \
        "Aggregates AMT_1 using an unstated method by COL_1."


def test_aggregation_mixed_kinds_in_first_seen_order():
    d = agg_desc(attr("COL_1"), measure("AMT_1", "max"), measure("AMT_2", "sum"), attr("COL_2"),
                 measure("AMT_3", "max"), measure("CNT_1", "count"))
    assert d.headline == ("Takes the maximum of AMT_1, AMT_3; Sums AMT_2; Counts CNT_1 by COL_1, COL_2.")


def test_aggregation_no_measures():
    assert agg_desc(attr("COL_1"), attr("COL_2")).headline == "Groups by COL_1, COL_2."


def test_aggregation_no_keys():
    assert agg_desc(measure("AMT_1")).headline == "Sums AMT_1."


def test_aggregation_no_columns():
    assert agg_desc().headline == "Aggregates rows (no columns listed)."


def test_aggregation_calculated_columns_are_not_keys_or_measures():
    d = agg_desc(attr("COL_1"), measure("AMT_1"), attr("CC_1", ce(bi("*", col("AMT_1"), num("2")))),
                 measure("CM_1", "sum", ce(col("AMT_1"))))
    assert d.headline == "Sums AMT_1 by COL_1."
    assert d.details == ["Adds CC_1 = AMT_1 * 2.", "Adds CM_1 = AMT_1."]


# ---------------------------------------------------------------- other node types

def test_projection_counts_mapped_not_calculated_columns():
    d = describe_one("P", [mk_node("A", NodeType.DATASOURCE),
                           mk_node("P", NodeType.PROJECTION, [attr("COL_1"), attr("CC_1", ce(num("1")))])],
                     [edge("A", "P")])
    assert d.headline == "Takes 1 columns from A."
    assert d.details == ["Adds CC_1 = 1."]


def test_projection_without_input():
    d = describe_one("P", [mk_node("P", NodeType.PROJECTION, [attr("COL_1")], understood=False)])
    assert d.headline == "Takes 1 columns from (no input)."
    assert d.details == [NOT_UNDERSTOOD]


def test_rank():
    d = describe_one("R", [mk_node("A", NodeType.PROJECTION), mk_node("R", NodeType.RANK)], [edge("A", "R")])
    assert d.headline == "Ranks rows (partition and order logic not yet modelled)."
    assert d.details == []


def test_output_dimension_has_no_cube_detail():
    d = describe_one("Semantics", [mk_node("Semantics", NodeType.OUTPUT, [attr("COL_1"), measure("AMT_1")])],
                     category=DataCategory.DIMENSION)
    assert d.headline == "Publishes 1 attributes and 1 measures as the view's output."
    assert d.details == []


def test_script_statement():
    d = describe_one("S", [mk_node("S", NodeType.SCRIPT_STATEMENT, understood=False)])
    assert d.headline == "Runs a SQL script statement."
    assert d.details == [NOT_UNDERSTOOD]


def test_opaque_without_input():
    d = describe_one("O", [mk_node("O", NodeType.OPAQUE, understood=False)])
    assert d.headline == "Does something the parser does not recognise."
    assert d.details == [NOT_UNDERSTOOD]


def test_opaque_marker_even_if_flag_says_understood():
    d = describe_one("O", [mk_node("O", NodeType.OPAQUE, understood=True)])
    assert d.details == [NOT_UNDERSTOOD]


def test_detail_order_filters_calcs_constants_flags():
    flt = Filter(expression=ce(bi(">", col("AMT_1"), num("0"))))
    sql = Filter(expression=Expression(text='"COL_1" LIKE \'A%\'', lang=ExpressionLang.SQL))
    nodes = [mk_node("A", NodeType.PROJECTION),
             mk_node("U", NodeType.UNION, [attr("CC_1", ce(num("1")))], filters=[flt, sql], understood=False)]
    d = describe_one("U", nodes, [edge("A", "U", [ColumnMapItem(target="COL_5", constant="K")])])
    assert d.details == [
        "Keeps rows where AMT_1 > 0.",
        "Keeps rows where `\"COL_1\" LIKE 'A%'` (not parsed).",
        "Adds CC_1 = 1.",
        "COL_5 is 'K' for rows from A.",
        NOT_UNDERSTOOD,
    ]


# ---------------------------------------------------------------- describe_view ordering

def test_describe_view_ties_follow_node_order_and_output_is_last():
    nodes = [mk_node("Semantics", NodeType.OUTPUT), mk_node("J", NodeType.JOIN),
             mk_node("T2", NodeType.DATASOURCE), mk_node("T1", NodeType.DATASOURCE),
             mk_node("Orphan", NodeType.PROJECTION)]
    edges = [edge("T1", "J"), edge("T2", "J"), edge("J", "Semantics")]
    names = [d.node_id.rpartition("/")[2] for d in describe_view(mk_result(nodes, edges))]
    assert names == ["T2", "T1", "J", "Orphan", "Semantics"]


def test_describe_view_survives_a_cycle_and_dangling_edges():
    nodes = [mk_node("A", NodeType.PROJECTION), mk_node("B", NodeType.PROJECTION),
             mk_node("Semantics", NodeType.OUTPUT)]
    edges = [edge("A", "B"), edge("B", "A"), edge("B", "Semantics"), edge("GHOST", "A")]
    names = [d.node_id.rpartition("/")[2] for d in describe_view(mk_result(nodes, edges))]
    assert names == ["A", "B", "Semantics"]


def test_describe_view_empty_result():
    assert describe_view(mk_result([])) == []


def test_describe_view_every_fixture_never_raises(parse_fixture):
    for path in sorted(FIXTURES.rglob("*.calculationview")):
        result = parse_fixture(str(path.relative_to(FIXTURES)))
        descriptions = describe_view(result)
        assert len(descriptions) == len(result.nodes)
        assert all(d.headline.endswith(".") for d in descriptions)
