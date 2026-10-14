"""Front end A: graphical calculation views (Calculation:scenario XML).

Elements are matched by local name and xsi:type by its local part, so the parser does
not depend on namespace prefixes or URIs. Anything not modelled raises a warning.
"""
from __future__ import annotations

from lxml import etree

from app.ir.models import (
    DataSource, DataSourceKind, Edge, IRWarning, Node, NodeType, Parameter, ParameterKind,
    ParameterMapping, ParseResult, Severity, View, make_id,
)
from app.parsers import xmlutil as x

DATASOURCE_KINDS = {
    "DATA_BASE_TABLE": DataSourceKind.TABLE,
    "CALCULATION_VIEW": DataSourceKind.CALC_VIEW,
    "TABLE_FUNCTION": DataSourceKind.TABLE_FUNCTION,
}


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

    def build(self) -> ParseResult:
        self._parse_parameters()
        self._parse_data_sources()
        self._parse_variable_mappings()
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


def _ref(value: str | None) -> str:
    return (value or "").removeprefix("#")


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None
