import pytest

from app.ir.models import ExprNode
from app.parsers.expressions import ExprParseError, parse_expression


def col(name): return ExprNode(kind="column", value=name)
def num(v): return ExprNode(kind="number", value=v)
def s(v): return ExprNode(kind="string", value=v)
def param(name): return ExprNode(kind="param", value=name)
def bin_(op, a, b): return ExprNode(kind="binary", value=op, args=[a, b])
def call(name, *args): return ExprNode(kind="call", value=name, args=list(args))


def test_if_call_with_comparison():
    assert parse_expression("if(\"COL_2\" = 'X', \"AMT_1\", 0)") == call(
        "if", bin_("=", col("COL_2"), s("X")), col("AMT_1"), num("0"))


def test_bare_parameter_placeholder():
    assert parse_expression('"AMT_1" * $$IP_RATE$$') == bin_("*", col("AMT_1"), param("IP_RATE"))


def test_quoted_parameter_placeholder_is_a_param():
    assert parse_expression("(\"COL_3\" = '$$IP_FISCAL_YEAR$$')") == bin_(
        "=", col("COL_3"), param("IP_FISCAL_YEAR"))


def test_arithmetic_precedence():
    assert parse_expression("1 + 2 * 3") == bin_("+", num("1"), bin_("*", num("2"), num("3")))


def test_boolean_precedence_and_not():
    expected = bin_(
        "or",
        bin_("and", bin_("=", col("A"), s("x")),
             ExprNode(kind="unary", value="not", args=[bin_("=", col("B"), s("y"))])),
        bin_(">", col("C"), num("1")),
    )
    assert parse_expression("\"A\" = 'x' and not \"B\" = 'y' OR \"C\" > 1") == expected


def test_escaped_quote_in_string():
    assert parse_expression("'it''s'") == s("it's")


def test_function_names_are_lowercased_and_zero_arg_calls_work():
    assert parse_expression('LEFTSTR("COL_1", 2)') == call("leftstr", col("COL_1"), num("2"))
    assert parse_expression("now()") == call("now")


def test_unary_minus_and_decimal():
    assert parse_expression("-1.5") == ExprNode(kind="unary", value="-", args=[num("1.5")])


@pytest.mark.parametrize("text", [
    "if(\"COL_1\" = 'X', 1",   # missing close paren
    '"COL_1" = ',              # dangling operator
    "COL_1 = 1",               # bare identifier
    "'unterminated",           # unterminated string
    "",                        # empty
    "   ",                     # whitespace only
    "1 2",                     # trailing token
    '"A" # 1',                 # unknown character
])
def test_invalid_expressions_raise_expr_parse_error(text):
    with pytest.raises(ExprParseError):
        parse_expression(text)


def test_deep_nesting_raises_expr_parse_error_not_recursion_error():
    with pytest.raises(ExprParseError):
        parse_expression("(" * 5000 + "1" + ")" * 5000)


def test_same_operator_chains_flatten():
    assert parse_expression("1 + 2 + 3") == ExprNode(
        kind="binary", value="+", args=[num("1"), num("2"), num("3")])
    assert parse_expression("1 - 2 - 3") == ExprNode(
        kind="binary", value="-", args=[num("1"), num("2"), num("3")])
    assert parse_expression('"a" and "b" and "c"') == ExprNode(
        kind="binary", value="and", args=[col("a"), col("b"), col("c")])


def test_mixed_operators_nest_left():
    assert parse_expression("1 + 2 - 3") == bin_(
        "-", bin_("+", num("1"), num("2")), num("3"))


def test_parenthesised_group_is_preserved():
    assert parse_expression("(1 + 2) + 3") == bin_(
        "+", bin_("+", num("1"), num("2")), num("3"))


def test_long_sum_parses_and_round_trips_json():
    node = parse_expression(" + ".join(['"C"'] * 500))
    assert len(node.args) == 500
    assert ExprNode.model_validate_json(node.model_dump_json()) == node


@pytest.mark.parametrize("text", ["-" * 300 + "1", "not " * 300 + "1"])
def test_excessive_tree_depth_raises_expr_parse_error(text):
    with pytest.raises(ExprParseError):
        parse_expression(text)


def test_unary_chain_under_limit_round_trips_json():
    node = parse_expression("-" * 60 + "1")
    assert ExprNode.model_validate_json(node.model_dump_json()) == node
