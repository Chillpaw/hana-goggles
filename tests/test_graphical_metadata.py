import hashlib

from conftest import FIXTURES, MAIN

from app.ir.models import (
    DataCategory, DataSourceKind, NodeType, ParameterKind, ParameterMapping, ViewType,
)

V = "GENERIC_TAX_REPORTING_CUBE"


def test_view_metadata_comes_from_root(parse_fixture):
    view = parse_fixture(MAIN).view
    assert view.id == V and view.name == V
    assert view.view_type is ViewType.GRAPHICAL
    assert view.data_category is DataCategory.CUBE
    assert view.schema_version == "2.3"
    assert view.file_hash == hashlib.sha256((FIXTURES / MAIN).read_bytes()).hexdigest()


def test_data_sources_are_parsed_and_become_nodes(parse_fixture):
    result = parse_fixture(MAIN)
    by_id = {d.id: d for d in result.data_sources}
    assert set(by_id) == {f"{V}/SOURCE_VIEW_01", f"{V}/TABLE_A", f"{V}/TABLE_B"}

    table_a = by_id[f"{V}/TABLE_A"]
    assert (table_a.kind, table_a.schema_name, table_a.name) == (DataSourceKind.TABLE, "SCHEMA_1", "TABLE_A")

    upstream = by_id[f"{V}/SOURCE_VIEW_01"]
    assert upstream.kind is DataSourceKind.CALC_VIEW
    assert upstream.name == "SOURCE_VIEW_01"
    assert upstream.resource_uri == "/pkg.synthetic/calculationviews/SOURCE_VIEW_01"

    ds_nodes = {n.id for n in result.nodes if n.node_type is NodeType.DATASOURCE}
    assert ds_nodes == set(by_id)


def test_parameters_and_variables(parse_fixture):
    params = {p.name: p for p in parse_fixture(MAIN).parameters}
    assert set(params) == {"IP_FISCAL_YEAR", "IP_RATE", "V_COMPANY"}

    year = params["IP_FISCAL_YEAR"]
    assert year.id == f"{V}/@param/IP_FISCAL_YEAR"
    assert (year.kind, year.datatype, year.length, year.mandatory) == (
        ParameterKind.INPUT_PARAMETER, "NVARCHAR", 4, True)

    rate = params["IP_RATE"]
    assert (rate.datatype, rate.length, rate.scale, rate.default, rate.mandatory) == (
        "DECIMAL", 5, 2, "1", False)

    assert params["V_COMPANY"].kind is ParameterKind.VARIABLE


def test_variable_mapping_links_local_parameter_to_upstream_view(parse_fixture):
    assert parse_fixture(MAIN).parameter_mappings == [
        ParameterMapping(view_id=V, data_source_id=f"{V}/SOURCE_VIEW_01",
                         target_parameter="IP_YEAR", local_parameter="IP_FISCAL_YEAR")
    ]
