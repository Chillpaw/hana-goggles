"""Intermediate representation. Every output is a view of these models.

Graphical and scripted views share the same entities, so generators never branch on
view type. Ids are deterministic (view/node/column) so annotations survive re-import.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def make_id(*parts: str) -> str:
    return "/".join(parts)


class IRModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ViewType(StrEnum):
    GRAPHICAL = "graphical"
    SCRIPTED = "scripted"
    UNKNOWN = "unknown"


class DataCategory(StrEnum):
    CUBE = "CUBE"
    DIMENSION = "DIMENSION"
    DEFAULT = "DEFAULT"
    UNKNOWN = "UNKNOWN"


class NodeType(StrEnum):
    DATASOURCE = "datasource"
    PROJECTION = "projection"
    JOIN = "join"
    AGGREGATION = "aggregation"
    UNION = "union"
    RANK = "rank"
    SCRIPT_STATEMENT = "script_statement"
    OPAQUE = "opaque"
    OUTPUT = "output"


class ColumnKind(StrEnum):
    ATTRIBUTE = "attribute"
    MEASURE = "measure"


class ExpressionLang(StrEnum):
    COLUMN_ENGINE = "column_engine"
    SQL = "sql"


class ParameterKind(StrEnum):
    INPUT_PARAMETER = "input_parameter"
    VARIABLE = "variable"


class ParamUsage(StrEnum):
    FILTER = "filter"
    CALCULATION = "calculation"


class DataSourceKind(StrEnum):
    TABLE = "table"
    CALC_VIEW = "calc_view"
    TABLE_FUNCTION = "table_function"
    CDS = "cds"
    UNKNOWN = "unknown"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ParseStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"


class ExprNode(IRModel):
    """Expression AST. `value` holds the literal text, column name, parameter name,
    function name (lowercased) or operator, depending on `kind`. A `binary` node may carry
    more than two args, meaning a left fold of the same operator."""

    kind: Literal["string", "number", "column", "param", "call", "binary", "unary"]
    value: str | None = None
    args: list[ExprNode] = Field(default_factory=list)


class Expression(IRModel):
    text: str
    lang: ExpressionLang
    ast: ExprNode | None = None


class Column(IRModel):
    id: str
    name: str
    datatype: str | None = None
    length: int | None = None
    scale: int | None = None
    kind: ColumnKind = ColumnKind.ATTRIBUTE
    aggregation: str | None = None
    expression: Expression | None = None


class ColumnMapItem(IRModel):
    """Maps a source column, or a constant (unions), to a target column."""

    target: str
    source: str | None = None
    constant: str | None = None
    null: bool = False


class Edge(IRModel):
    from_node: str
    to_node: str
    column_map: list[ColumnMapItem] = Field(default_factory=list)


class JoinCondition(IRModel):
    column: str


class JoinSpec(IRModel):
    join_type: str
    cardinality: str | None = None
    left_node: str | None = None
    right_node: str | None = None
    conditions: list[JoinCondition] = Field(default_factory=list)
    special: bool = False  # referential / text joins need special semantics


class Filter(IRModel):
    expression: Expression


class Node(IRModel):
    id: str
    view_id: str
    node_type: NodeType
    name: str
    raw: str
    columns: list[Column] = Field(default_factory=list)
    filters: list[Filter] = Field(default_factory=list)
    join: JoinSpec | None = None
    understood: bool = True  # feeds View.coverage_pct


class ParameterUse(IRModel):
    node_id: str
    usage: ParamUsage


class Parameter(IRModel):
    id: str
    view_id: str
    name: str
    kind: ParameterKind
    datatype: str | None = None
    length: int | None = None
    scale: int | None = None
    default: str | None = None
    mandatory: bool = False
    used_in: list[ParameterUse] = Field(default_factory=list)


class ParameterMapping(IRModel):
    """A local parameter (or constant) passed to a parameter of an upstream view."""

    view_id: str
    data_source_id: str
    target_parameter: str
    local_parameter: str | None = None
    constant: str | None = None


class DataSource(IRModel):
    id: str
    kind: DataSourceKind
    schema_name: str | None = None
    name: str
    resource_uri: str | None = None
    resolved_view_id: str | None = None  # set by dependency resolution (M3)


class IRWarning(IRModel):
    view_id: str | None = None
    node_id: str | None = None
    code: str
    message: str
    severity: Severity = Severity.WARNING
    line: int | None = None


class View(IRModel):
    id: str
    name: str
    package_path: str | None = None
    view_type: ViewType
    data_category: DataCategory
    schema_version: str | None = None
    file_hash: str
    parse_status: ParseStatus
    coverage_pct: float


class ParseResult(IRModel):
    view: View
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    parameters: list[Parameter] = Field(default_factory=list)
    parameter_mappings: list[ParameterMapping] = Field(default_factory=list)
    data_sources: list[DataSource] = Field(default_factory=list)
    warnings: list[IRWarning] = Field(default_factory=list)


class LeafKind(StrEnum):
    TABLE = "table"
    EXTERNAL_VIEW = "external_view"
    TABLE_FUNCTION = "table_function"
    UNKNOWN = "unknown"


class LeafSource(IRModel):
    """Something the estate reads but does not define: a table, or a view outside the folder."""

    id: str  # "table:SCHEMA_1.TABLE_A", "view:SOME_VIEW", "table_function:...", "unknown:<view>/<ds>"
    kind: LeafKind
    schema_name: str | None = None
    name: str
    used_by: list[str] = Field(default_factory=list)  # view ids, sorted


class ViewDependency(IRModel):
    consumer: str  # view id
    producer: str  # view id (internal) or LeafSource id (leaf)
    data_source_id: str  # the consumer's DataSource node id
    internal: bool


class Estate(IRModel):
    """Every view in a folder and how they depend on each other. Built from IR only."""

    views: list[str] = Field(default_factory=list)  # view ids, sorted
    dependencies: list[ViewDependency] = Field(default_factory=list)  # by (consumer, data_source_id)
    leaf_sources: list[LeafSource] = Field(default_factory=list)  # by id
    deploy_order: list[str] = Field(default_factory=list)  # producers before consumers
    cycles: list[list[str]] = Field(default_factory=list)  # each sorted; list sorted
    warnings: list[IRWarning] = Field(default_factory=list)


ExprNode.model_rebuild()
