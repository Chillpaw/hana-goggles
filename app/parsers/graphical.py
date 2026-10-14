"""Front end A: graphical calculation views (Calculation:scenario XML).

Elements are matched by local name and xsi:type by its local part, so the parser does
not depend on namespace prefixes or URIs. Anything not modelled raises a warning.
"""
from __future__ import annotations

import re

from lxml import etree

from app.ir.models import (
    Column, ColumnKind, ColumnMapItem, DataSource, DataSourceKind, Edge, Expression,
    ExpressionLang, Filter, IRWarning, JoinCondition, JoinSpec, Node, NodeType, Parameter,
    ParameterKind, ParameterMapping, ParameterUse, ParamUsage, ParseResult, Severity, View,
    make_id,
)
from app.parsers import xmlutil as x
from app.parsers.expressions import ExprParseError, parse_expression

DATASOURCE_KINDS = {
    "DATA_BASE_TABLE": DataSourceKind.TABLE,
    "CALCULATION_VIEW": DataSourceKind.CALC_VIEW,
    "TABLE_FUNCTION": DataSourceKind.TABLE_FUNCTION,
}
NODE_TYPES = {
    "ProjectionView": NodeType.PROJECTION,
    "JoinView": NodeType.JOIN,
    "AggregationView": NodeType.AGGREGATION,
    "UnionView": NodeType.UNION,
    "RankView": NodeType.RANK,
}
KNOWN_CALCVIEW_CHILDREN = {
    "descriptions", "viewAttributes", "calculatedViewAttributes", "input", "filter", "joinAttribute",
}
SPECIAL_JOIN_TYPES = {"referential", "textTable"}
PARAM_RE = re.compile(r"\$\$(\w+)\$\$")


def parse_graphical(root: etree._Element, view: View) -> ParseResult:
    return _Builder(root, view).build()


class _Builder:
    def __init__(self, root: etree._Element, view: View):
        self.root = root
        self.view = view
        self.vid = view.id
        self.nodes: dict[str, Node] = {}  # keyed by the id used in "#ref" attributes
        self.edges: list[Edge] = []
        self.params: dict[str, Parameter] = {}
        self.param_maps: list[ParameterMapping] = []
        self.sources: list[DataSource] = []
        self.warnings: list[IRWarning] = []
        self._pending_inputs: list[tuple[Node, etree._Element]] = []

    def build(self) -> ParseResult:
        self._parse_parameters()
        self._parse_data_sources()
        self._parse_calculation_views()
        self._resolve_inputs()
        self._parse_variable_mappings()
        self._record_parameter_usage()
        return self._result()

    def _result(self) -> ParseResult:
        return ParseResult(
            view=self.view,
            nodes=list(self.nodes.values()),
            edges=self.edges,
            parameters=list(self.params.values()),
            parameter_mappings=self.param_maps,
            data_sources=self.sources,
            warnings=self.warnings,
        )

    def warn(self, code: str, message: str, *, el: etree._Element | None = None,
             node_id: str | None = None, severity: Severity = Severity.WARNING) -> None:
        self.warnings.append(IRWarning(
            view_id=self.vid, node_id=node_id, code=code, message=message, severity=severity,
            line=el.sourceline if el is not None else None,
        ))

    def _parse_parameters(self) -> None:
        for var in x.children(x.child(self.root, "localVariables"), "variable"):
            name = var.get("id") or ""
            props = x.child(var, "variableProperties")
            attrs = props.attrib if props is not None else {}
            default = attrs.get("defaultValue")
            if default is None:
                default_range = x.child(props, "defaultRange")
                default = default_range.get("lowValue") if default_range is not None else None
            self.params[name] = Parameter(
                id=make_id(self.vid, "@param", name),
                view_id=self.vid,
                name=name,
                kind=ParameterKind.INPUT_PARAMETER if var.get("parameter") == "true" else ParameterKind.VARIABLE,
                datatype=attrs.get("datatype"),
                length=_int(attrs.get("length")),
                scale=_int(attrs.get("scale")),
                default=default,
                mandatory=attrs.get("mandatory") == "true",
            )

    def _parse_data_sources(self) -> None:
        for ds in x.children(x.child(self.root, "dataSources"), "DataSource"):
            ds_id = ds.get("id") or ""
            node_id = make_id(self.vid, ds_id)
            kind = DATASOURCE_KINDS.get(ds.get("type") or "", DataSourceKind.UNKNOWN)
            if kind is DataSourceKind.UNKNOWN:
                self.warn("UNKNOWN_DATASOURCE_TYPE", f"data source {ds_id!r} has type {ds.get('type')!r}",
                          el=ds, node_id=node_id)
            column_object = x.child(ds, "columnObject")
            uri = x.text(x.child(ds, "resourceUri"))
            if column_object is not None:
                schema_name, name = column_object.get("schemaName"), column_object.get("columnObjectName") or ds_id
            else:
                schema_name, name = None, uri.rpartition("/")[2] if uri else ds_id
            self.sources.append(DataSource(id=node_id, kind=kind, schema_name=schema_name, name=name,
                                           resource_uri=uri))
            self.nodes[ds_id] = Node(id=node_id, view_id=self.vid, node_type=NodeType.DATASOURCE,
                                     name=ds_id, raw=x.raw(ds), understood=kind is not DataSourceKind.UNKNOWN)

    def _parse_variable_mappings(self) -> None:
        for m in x.children(x.child(self.root, "variableMappings"), "mapping"):
            ds_ref = _ref(m.get("dataSource"))
            target = x.child(m, "targetVariable")
            local_ref = x.text(x.child(m, "localVariable"))
            local_name = _ref(local_ref) if local_ref else None
            if ds_ref not in self.nodes:
                self.warn("UNRESOLVED_VARIABLE_MAPPING", f"variable mapping names unknown data source #{ds_ref}", el=m)
            if local_name is not None and local_name not in self.params:
                self.warn("UNKNOWN_PARAMETER_REF", f"variable mapping names unknown parameter #{local_name}", el=m)
            self.param_maps.append(ParameterMapping(
                view_id=self.vid,
                data_source_id=make_id(self.vid, ds_ref),
                target_parameter=(target.get("name") or "") if target is not None else "",
                local_parameter=local_name,
                constant=m.get("value"),
            ))

    def _calculation_view_elements(self) -> list[etree._Element]:
        wrapper = x.child(self.root, "calculationViews")
        return x.children(wrapper if wrapper is not None else self.root, "calculationView")

    def _parse_calculation_views(self) -> None:
        for cv in self._calculation_view_elements():
            name = cv.get("id") or ""
            node_id = make_id(self.vid, name)
            type_name = x.xsi_type_name(cv)
            node_type = NODE_TYPES.get(type_name or "")
            if node_type is None:
                code = "SCRIPTED_DEFERRED" if type_name == "SqlScriptView" else "UNKNOWN_NODE_TYPE"
                self.warn(code, f"calculationView {name!r} has type {type_name!r}; kept as an opaque node",
                          el=cv, node_id=node_id)
                node = Node(id=node_id, view_id=self.vid, node_type=NodeType.OPAQUE, name=name,
                            raw=x.raw(cv), understood=False)
            else:
                node = self._parse_node(cv, node_id, name, node_type)
            self.nodes[name] = node
            self._pending_inputs.extend((node, inp) for inp in x.children(cv, "input"))

    def _parse_node(self, cv: etree._Element, node_id: str, name: str, node_type: NodeType) -> Node:
        node = Node(id=node_id, view_id=self.vid, node_type=node_type, name=name, raw=x.raw(cv))
        self._check_children(cv, KNOWN_CALCVIEW_CHILDREN, node_id)
        node.columns.extend(self._view_attributes(cv, node_id))
        node.columns.extend(self._calculated_columns(
            x.child(cv, "calculatedViewAttributes"), "calculatedViewAttribute", node, ColumnKind.ATTRIBUTE))
        for f in x.children(cv, "filter"):
            text = x.text(f)
            if text:
                node.filters.append(Filter(expression=self._expression(
                    text, f.get("expressionLanguage") or cv.get("filterExpressionLanguage"), node, "filter")))
        if node_type is NodeType.JOIN:
            node.join = self._join_spec(cv, node_id)
        if node_type is NodeType.RANK:
            self.warn("RANK_NODE", f"{name} is a rank node; partition logic needs review in codegen",
                      el=cv, node_id=node_id, severity=Severity.INFO)
        return node

    def _view_attributes(self, cv: etree._Element, node_id: str) -> list[Column]:
        columns = []
        for va in x.children(x.child(cv, "viewAttributes"), "viewAttribute"):
            name = va.get("id") or ""
            aggregation = va.get("aggregationType")
            columns.append(Column(
                id=make_id(node_id, name), name=name, datatype=va.get("datatype"),
                length=_int(va.get("length")), scale=_int(va.get("scale")),
                kind=ColumnKind.MEASURE if aggregation else ColumnKind.ATTRIBUTE, aggregation=aggregation,
            ))
        return columns

    def _calculated_columns(self, container: etree._Element | None, tag: str, node: Node,
                            kind: ColumnKind) -> list[Column]:
        columns = []
        for ca in x.children(container, tag):
            name = ca.get("id") or ""
            formula = x.first_descendant(ca, "formula")
            # Datatype sits on the element itself, or on the formula's parent (e.g. keyCalculation).
            spec = ca if ca.get("datatype") is not None or formula is None else formula.getparent()
            columns.append(Column(
                id=make_id(node.id, name), name=name, datatype=spec.get("datatype"),
                length=_int(spec.get("length")), scale=_int(spec.get("scale")),
                kind=kind, aggregation=ca.get("aggregationType"),
                expression=self._expression(x.text(formula) or "", spec.get("expressionLanguage"),
                                            node, f"column {name}"),
            ))
        return columns

    def _expression(self, text: str, lang_attr: str | None, node: Node, where: str) -> Expression:
        lang = ExpressionLang.SQL if (lang_attr or "").upper() == "SQL" else ExpressionLang.COLUMN_ENGINE
        expr = Expression(text=text, lang=lang)
        if lang is ExpressionLang.SQL:
            self.warn("SQL_EXPR_DEFERRED", f"{node.name} {where}: SQL expression kept as text until M2",
                      node_id=node.id, severity=Severity.INFO)
            return expr
        try:
            expr.ast = parse_expression(text)
        except ExprParseError as exc:
            node.understood = False
            self.warn("EXPR_PARSE_FAILED", f"{node.name} {where}: {exc}", node_id=node.id)
        return expr

    def _join_spec(self, cv: etree._Element, node_id: str) -> JoinSpec:
        refs = [_ref(i.get("node")) for i in x.children(cv, "input")]
        if len(refs) != 2:
            self.warn("JOIN_INPUT_COUNT", f"join has {len(refs)} inputs, expected 2", el=cv, node_id=node_id)
        join_type = cv.get("joinType") or "inner"
        spec = JoinSpec(
            join_type=join_type,
            cardinality=cv.get("cardinality"),
            left_node=make_id(self.vid, refs[0]) if len(refs) > 0 else None,
            right_node=make_id(self.vid, refs[1]) if len(refs) > 1 else None,
            conditions=[JoinCondition(column=j.get("name") or "") for j in x.children(cv, "joinAttribute")],
            special=join_type in SPECIAL_JOIN_TYPES,
        )
        if spec.special:
            self.warn("SPECIAL_JOIN", f"{join_type} join needs special semantics in codegen",
                      el=cv, node_id=node_id, severity=Severity.INFO)
        return spec

    def _resolve_inputs(self) -> None:
        for node, inp in self._pending_inputs:
            ref = _ref(inp.get("node"))
            source = self.nodes.get(ref)
            if source is None:
                node.understood = False
                self.warn("UNRESOLVED_INPUT", f"{node.name} reads #{ref}, which is not in this view",
                          el=inp, node_id=node.id)
                continue
            self.edges.append(Edge(from_node=source.id, to_node=node.id, column_map=self._mappings(inp, node.id)))

    def _mappings(self, inp: etree._Element, node_id: str) -> list[ColumnMapItem]:
        items = []
        for m in x.children(inp, "mapping"):
            target = m.get("target") or ""
            if x.xsi_type_name(m) == "ConstantAttributeMapping":
                is_null = m.get("null") == "true"
                items.append(ColumnMapItem(target=target, constant=None if is_null else m.get("value"), null=is_null))
            elif m.get("source") is not None:
                items.append(ColumnMapItem(target=target, source=m.get("source")))
            else:
                self.warn("UNKNOWN_MAPPING", f"mapping to {target!r} has no source or constant",
                          el=m, node_id=node_id)
        return items

    def _record_parameter_usage(self) -> None:
        for node in self.nodes.values():
            uses = [(f.expression.text, ParamUsage.FILTER) for f in node.filters]
            uses += [(c.expression.text, ParamUsage.CALCULATION) for c in node.columns if c.expression]
            for text, usage in uses:
                for name in PARAM_RE.findall(text):
                    param = self.params.get(name)
                    if param is None:
                        self.warn("UNKNOWN_PARAMETER_REF", f"{node.name} references $${name}$$", node_id=node.id)
                        continue
                    use = ParameterUse(node_id=node.id, usage=usage)
                    if use not in param.used_in:
                        param.used_in.append(use)

    def _check_children(self, el: etree._Element, known: set[str], node_id: str | None) -> None:
        for c in x.children(el):
            if x.local(c) not in known:
                self.warn("UNKNOWN_ELEMENT", f"<{x.local(c)}> inside <{x.local(el)}> is not modelled",
                          el=c, node_id=node_id)


def _ref(value: str | None) -> str:
    return (value or "").removeprefix("#")


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None
