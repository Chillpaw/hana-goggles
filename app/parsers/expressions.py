"""Column-engine expression parser: tokenizer plus recursive descent into ExprNode.

Scope for M1: literals, double-quoted columns, $$PARAM$$ placeholders, function calls,
arithmetic, comparison and boolean operators. Anything else raises ExprParseError; the
caller turns that into a warning so the rest of the view still parses.
"""
from __future__ import annotations

import re

from app.ir.models import ExprNode


class ExprParseError(ValueError):
    pass


_TOKEN_RE = re.compile(
    r"""
     (?P<ws>\s+)
    |(?P<param>\$\$\w+\$\$)
    |(?P<number>\d+(?:\.\d+)?)
    |(?P<string>'(?:[^']|'')*')
    |(?P<column>"(?:[^"]|"")*")
    |(?P<op><=|>=|<>|!=|=|<|>|\+|-|\*|/)
    |(?P<lparen>\()
    |(?P<rparen>\))
    |(?P<comma>,)
    |(?P<ident>[A-Za-z_][A-Za-z0-9_]*)
    """,
    re.VERBOSE,
)
_PARAM_RE = re.compile(r"\$\$(\w+)\$\$")
_CMP_OPS = {"=", "!=", "<>", "<", ">", "<=", ">="}

Token = tuple[str, str]


def parse_expression(text: str) -> ExprNode:
    tokens = _tokenize(text)
    if not tokens:
        raise ExprParseError("empty expression")
    parser = _Parser(tokens)
    try:
        node = parser.parse_or()
    except RecursionError:
        raise ExprParseError("expression nested too deeply") from None
    if parser.peek() is not None:
        raise ExprParseError(f"unexpected token {parser.peek()[1]!r}")
    return node


def _tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if match is None:
            raise ExprParseError(f"unexpected character {text[pos]!r} at position {pos}")
        if match.lastgroup != "ws":
            tokens.append((match.lastgroup, match.group()))
        pos = match.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.i = 0

    def peek(self) -> Token | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self) -> Token:
        tok = self.peek()
        if tok is None:
            raise ExprParseError("unexpected end of expression")
        self.i += 1
        return tok

    def expect(self, kind: str) -> Token:
        tok = self.take()
        if tok[0] != kind:
            raise ExprParseError(f"expected {kind}, got {tok[1]!r}")
        return tok

    def accept_keyword(self, word: str) -> bool:
        tok = self.peek()
        if tok is not None and tok[0] == "ident" and tok[1].lower() == word:
            self.i += 1
            return True
        return False

    def accept_op(self, ops: set[str]) -> str | None:
        tok = self.peek()
        if tok is not None and tok[0] == "op" and tok[1] in ops:
            self.i += 1
            return tok[1]
        return None

    def parse_or(self) -> ExprNode:
        left = self.parse_and()
        while self.accept_keyword("or"):
            left = ExprNode(kind="binary", value="or", args=[left, self.parse_and()])
        return left

    def parse_and(self) -> ExprNode:
        left = self.parse_not()
        while self.accept_keyword("and"):
            left = ExprNode(kind="binary", value="and", args=[left, self.parse_not()])
        return left

    def parse_not(self) -> ExprNode:
        if self.accept_keyword("not"):
            return ExprNode(kind="unary", value="not", args=[self.parse_not()])
        return self.parse_comparison()

    def parse_comparison(self) -> ExprNode:
        left = self.parse_additive()
        op = self.accept_op(_CMP_OPS)
        if op is None:
            return left
        return ExprNode(kind="binary", value=op, args=[left, self.parse_additive()])

    def parse_additive(self) -> ExprNode:
        left = self.parse_multiplicative()
        while (op := self.accept_op({"+", "-"})) is not None:
            left = ExprNode(kind="binary", value=op, args=[left, self.parse_multiplicative()])
        return left

    def parse_multiplicative(self) -> ExprNode:
        left = self.parse_unary()
        while (op := self.accept_op({"*", "/"})) is not None:
            left = ExprNode(kind="binary", value=op, args=[left, self.parse_unary()])
        return left

    def parse_unary(self) -> ExprNode:
        if self.accept_op({"-"}):
            return ExprNode(kind="unary", value="-", args=[self.parse_unary()])
        return self.parse_primary()

    def parse_primary(self) -> ExprNode:
        kind, text = self.take()
        if kind == "number":
            return ExprNode(kind="number", value=text)
        if kind == "string":
            inner = text[1:-1].replace("''", "'")
            placeholder = _PARAM_RE.fullmatch(inner)
            if placeholder:
                return ExprNode(kind="param", value=placeholder.group(1))
            return ExprNode(kind="string", value=inner)
        if kind == "param":
            return ExprNode(kind="param", value=text[2:-2])
        if kind == "column":
            return ExprNode(kind="column", value=text[1:-1].replace('""', '"'))
        if kind == "lparen":
            inner_node = self.parse_or()
            self.expect("rparen")
            return inner_node
        if kind == "ident":
            if self.peek() is not None and self.peek()[0] == "lparen":
                self.i += 1
                return ExprNode(kind="call", value=text.lower(), args=self.parse_args())
            raise ExprParseError(f"bare identifier {text!r}; column references must be double-quoted")
        raise ExprParseError(f"unexpected token {text!r}")

    def parse_args(self) -> list[ExprNode]:
        args: list[ExprNode] = []
        if self.peek() is not None and self.peek()[0] == "rparen":
            self.i += 1
            return args
        args.append(self.parse_or())
        while self.peek() is not None and self.peek()[0] == "comma":
            self.i += 1
            args.append(self.parse_or())
        self.expect("rparen")
        return args
