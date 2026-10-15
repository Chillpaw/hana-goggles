"""Structure-only audit (M4): structure scan, aggregation, formatting and the leak test."""
import json
import re
import shutil
from collections import Counter

import pytest
from conftest import FIXTURES, MAIN
from lxml import etree

from app.audit import (
    KNOWN_FUNCTIONS, FileFacts, aggregate, coverage_bucket, file_facts, format_json, format_text,
    run_audit,
)
from app.ir.models import ParseStatus, ViewType
from app.parsers import audit_scan
from app.parsers.audit_scan import OTHER, scan_structure, unparsed_function_names, uri_shape
from app.parsers.dispatch import parse_bytes
from app.parsers.xmlutil import XSI_NS

LEAK = "audit/LEAKCANARY_VIEW.calculationview"
ALL_FIXTURES = sorted(FIXTURES.rglob("*.calculationview"))

HEAD = ('<?xml version="1.0" encoding="UTF-8"?>'
        '<Calculation:scenario xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:Calculation="http://www.sap.com/ndb/BiModelCalculation.ecore" id="V" {attrs}>')
TAIL = "</Calculation:scenario>"


def scenario(body: str, attrs: str = "") -> bytes:
    return (HEAD.format(attrs=attrs) + body + TAIL).encode("utf-8")


# --- structure scan on the main fixture -------------------------------------------------

@pytest.fixture
def main_structure(fixture_bytes):
    return scan_structure(fixture_bytes(MAIN))


def test_main_fixture_xsi_types(main_structure):
    s = main_structure
    assert s.well_formed and not s.scan_error
    assert s.xsi_types["Calculation:JoinView"] == 1
    assert s.xsi_types["Calculation:ProjectionView"] == 1
    assert s.xsi_types["Calculation:ConstantAttributeMapping"] == 3
    assert s.xsi_types["Variable:VariableMapping"] == 1


def test_main_fixture_enum_values(main_structure):
    e = main_structure.enum_values
    assert e[("DataSource@type", "CALCULATION_VIEW")] == 1
    assert e[("DataSource@type", "DATA_BASE_TABLE")] == 2
    assert e[("scenario@dataCategory", "CUBE")] == 1
    assert e[("scenario@schemaVersion", "2.3")] == 1
    assert e[("calculationView@joinType", "leftOuter")] == 1
    assert e[("calculationView@cardinality", "CN_1")] == 1
    assert e[("input@emptyUnionBehavior", "NO_ROW")] == 2
    assert e[("measure@aggregationType", "sum")] == 4
    assert e[("valueDomain@type", "AttributeValue")] == 1


def test_main_fixture_elements_attributes_namespaces(main_structure):
    s = main_structure
    assert s.elements["calculationView"] == 4
    assert s.children[("calculationViews", "calculationView")] == 4
    assert s.children[("logicalModel", "baseMeasures")] == 1
    assert s.attributes[("scenario", "schemaVersion")] == 1
    assert s.attributes[("mapping", "xsi:type")] == 27
    assert s.namespaces == {
        "http://www.w3.org/2001/XMLSchema-instance": 1,
        "http://www.sap.com/ndb/BiModelCalculation.ecore": 1,
        "http://www.sap.com/ndb/BiModelVariable.ecore": 1,
    }


def test_main_fixture_functions_and_uri_shapes(main_structure):
    s = main_structure
    assert s.functions_parsed == {"if": 1}
    assert s.functions_unparsed == {}
    assert s.expressions == {"column_engine_parsed": 4}   # 2 calculated columns, 1 filter, 1 measure
    assert s.resource_uri_shapes == {
        ("DataSource/resourceUri", "/<package>/calculationviews/<name>"): 1,
        ("targetVariable@resourceUri", "/<package>/calculationviews/<name>"): 1,
    }


# --- structure scan rules ---------------------------------------------------------------

@pytest.mark.parametrize("uri, shape", [
    ("/pkg.synthetic/calculationviews/SOURCE_VIEW_01", "/<package>/calculationviews/<name>"),
    ("/a/b/c/calculationviews/V", "/<package>/<segment>/<segment>/calculationviews/<name>"),
    ("pkg::VIEW", "<namespace>::<name>"),
    ("VIEW", "<name>"),
    ("/tables/T", "/tables/<name>"),
    ("/A/B", "/<segment>/<name>"),
    ("/p/calculationviews/V/", "/<package>/calculationviews/<name>/"),
    ("//p//calculationviews/V", "//<package>//calculationviews/<name>"),
    ("", "<empty>"), ("   ", "<empty>"), (None, "<empty>"),
    ("/P/CalculationViews/X", "/<package>/calculationviews/<name>"),   # case-insensitive
])
def test_uri_shape(uri, shape):
    assert uri_shape(uri) == shape


@pytest.mark.parametrize("text, names", [
    ("if(\"A\" = 'x', 1", ["if"]),
    ("\"COL_FN\"(1) + leftstr('LIT(2)', 3", ["leftstr"]),
    ("'$$P$$'(1) + $$P$$(2) + midstr(", ["midstr"]),
    ("'unterminated ( LIT(", []),
    ("\"un\"\"terminated COL(", []),
    ("IF (\"A\"", ["if"]),
    ("'it''s FN(' + rtrim(", ["rtrim"]),
])
def test_unparsed_function_names_strip_quotes_and_placeholders(text, names):
    assert unparsed_function_names(text) == names


def test_sql_expressions_are_counted_not_mined():
    data = scenario(
        '<calculationViews><calculationView xsi:type="Calculation:ProjectionView" id="P" '
        'filterExpressionLanguage="sql "><calculatedViewAttributes>'
        '<calculatedViewAttribute id="C" expressionLanguage="SQL"><formula>SECRETFN(SECRETCOL)'
        '</formula></calculatedViewAttribute></calculatedViewAttributes>'
        '<filter>OTHERFN(X) = 1</filter></calculationView></calculationViews>')
    s = scan_structure(data)
    assert s.expressions == {"sql": 2}
    assert s.functions_parsed == {} and s.functions_unparsed == {}


def test_enum_values_outside_the_token_pattern_become_other():
    data = scenario('<dataSources><DataSource id="D" type="has spaces"/>'
                    '<DataSource id="E" type="9STARTS_WITH_DIGIT"/></dataSources>',
                    attrs='dataCategory="CUBE" schemaVersion="2.3.1" visibility="x y"')
    e = scan_structure(data).enum_values
    assert e[("DataSource@type", OTHER)] == 2
    assert e[("scenario@schemaVersion", "2.3.1")] == 1
    assert e[("scenario@visibility", OTHER)] == 1


def test_only_allow_listed_attribute_values_are_collected():
    data = scenario('<dataSources><DataSource id="SECRET_ID" type="DATA_BASE_TABLE">'
                    '<columnObject schemaName="SECRET_SCHEMA" columnObjectName="SECRET_T"/>'
                    '</DataSource></dataSources>')
    values = {v for (_k, v) in scan_structure(data).enum_values}
    assert values == {"DATA_BASE_TABLE"}


def test_odd_xsi_type_becomes_other():
    data = scenario('<calculationViews><calculationView xsi:type="has spaces in it" id="P"/>'
                    '</calculationViews>')
    assert scan_structure(data).xsi_types == {OTHER: 1}


@pytest.mark.parametrize("data", [
    b"", b"not xml", b"<a><b></a>", b"\xff\xfe\x00garbage", b"<?xml version='1.0'?>",
    b"<root/>", b"<scenario/>", b"<" + b"a>" * 5000,
    b'<!DOCTYPE a [<!ENTITY e "x">]><a>&e;</a>',
    b"<scenario><calculationViews><calculationView><formula>(((((</formula>"
    b"</calculationView></calculationViews></scenario>",
    b"<scenario><x><formula>" + b"(" * 5000 + b"</formula></x></scenario>",
])
def test_scan_structure_never_raises(data):
    s = scan_structure(data)
    assert isinstance(s.elements, dict)
    assert not s.scan_error


def test_garbage_is_not_well_formed():
    s = scan_structure(b"not xml at all")
    assert not s.well_formed
    assert s.elements == {}


# --- UNKNOWN_ELEMENT by parent and child -------------------------------------------------

@pytest.mark.parametrize("path", ALL_FIXTURES, ids=lambda p: p.stem)
def test_unknown_element_totals_match_the_parser(path):
    data = path.read_bytes()
    unknown: Counter = Counter()
    parsed = parse_bytes(data, file_name=path.name, unknown=unknown)
    expected = sum(1 for w in parsed.warnings if w.code == "UNKNOWN_ELEMENT")
    assert sum(unknown.values()) == expected
    assert parse_bytes(data, file_name=path.name) == parsed   # the collector never alters the IR


UNKNOWN_EVERYWHERE = scenario(
    '<informationModelLayout/>'
    '<localVariables><variable id="V1" parameter="true"><z1/>'
    '<variableProperties datatype="INTEGER"><z2/></variableProperties></variable></localVariables>'
    '<dataSources><DataSource id="T" type="DATA_BASE_TABLE"><z3/>'
    '<columnObject schemaName="S" columnObjectName="T"/></DataSource></dataSources>'
    '<calculationViews>'
    '<calculationView xsi:type="Calculation:ProjectionView" id="P">'
    '<restrictedViewAttributes/>'
    '<viewAttributes><viewAttribute id="C"><filter/></viewAttribute></viewAttributes>'
    '<calculatedViewAttributes><calculatedViewAttribute id="K" expressionLanguage="COLUMN_ENGINE">'
    '<formula>1</formula><z4/></calculatedViewAttribute></calculatedViewAttributes>'
    '<input node="#T"><z5/></input></calculationView>'
    '<calculationView xsi:type="Calculation:FancyView" id="F"><ignored_in_opaque/>'
    '<input node="#P"><z6/></input></calculationView>'
    '</calculationViews>'
    '<logicalModel id="F"><z7/>'
    '<attributes><attribute id="C"><z8/></attribute></attributes>'
    '<calculatedAttributes><calculatedAttribute id="CA"><z9/></calculatedAttribute></calculatedAttributes>'
    '<baseMeasures><measure id="M"><z10/></measure></baseMeasures>'
    '<calculatedMeasures><measure id="CM"><z11/></measure></calculatedMeasures>'
    '</logicalModel>')


def unknown_pairs(data: bytes) -> Counter:
    unknown: Counter = Counter()
    parse_bytes(data, file_name="V.calculationview", unknown=unknown)
    return unknown


def test_unknown_elements_by_parent_and_child():
    assert unknown_pairs(UNKNOWN_EVERYWHERE) == {
        ("scenario", "informationModelLayout"): 1,
        ("variable", "z1"): 1,
        ("variableProperties", "z2"): 1,
        ("DataSource", "z3"): 1,
        ("calculationView", "restrictedViewAttributes"): 1,
        ("viewAttribute", "filter"): 1,
        ("calculatedViewAttribute", "z4"): 1,
        ("input", "z5"): 1,
        ("input", "z6"): 1,
        ("logicalModel", "z7"): 1,
        ("attribute", "z8"): 1,
        ("calculatedAttribute", "z9"): 1,
        ("measure", "z10"): 1,
        ("measure", "z11"): 1,
    }


def test_unknown_elements_everywhere_match_the_parser():
    parsed = parse_bytes(UNKNOWN_EVERYWHERE, file_name="V.calculationview")
    expected = sum(1 for w in parsed.warnings if w.code == "UNKNOWN_ELEMENT")
    assert expected == 14
    assert sum(unknown_pairs(UNKNOWN_EVERYWHERE).values()) == expected


# --- aggregation (pure) -----------------------------------------------------------------

@pytest.mark.parametrize("pct, bucket", [
    (0.0, "0"), (0.5, "1-49"), (49.9, "1-49"), (50.0, "50-89"), (89.9, "50-89"),
    (90.0, "90-99"), (99.9, "90-99"), (100.0, "100"),
])
def test_coverage_bucket(pct, bucket):
    assert coverage_bucket(pct) == bucket


def facts(view_id="V", package=None, status="ok", coverage=100.0, codes=(), structure=True,
          suffix=".calculationview", view_type="graphical", id_from_stem=False):
    return FileFacts(suffix=suffix, parse_status=status, view_type=view_type, coverage_pct=coverage,
                     warning_codes=list(codes), view_id=view_id, package_path=package,
                     structure=scan_structure(b"<scenario/>") if structure else None,
                     id_from_stem=id_from_stem)


def test_aggregate_files_and_coverage():
    report = aggregate([
        facts("A", coverage=100.0), facts("B", status="partial", coverage=71.4, codes=["X", "X"]),
        facts("C", status="failed", coverage=0.0, codes=["READ_ERROR"], structure=False,
              suffix=".HDBCALCULATIONVIEW", view_type="unknown"),
        facts("D", view_type="scripted", coverage=50.0, codes=["SCRIPTED_DEFERRED"]),
    ], ["SCAN_BAD_FILENAME"])
    files = report["files"]
    assert files["total"] == 4
    assert files["by_suffix"] == {".HDBCALCULATIONVIEW": 1, ".calculationview": 3}
    assert files["parse_status"] == {"failed": 1, "ok": 2, "partial": 1}
    assert files["unreadable"] == 1
    assert files["coverage_pct"] == [0.0, 50.0, 71.4, 100.0]
    assert files["coverage_histogram"] == {"0": 1, "1-49": 0, "50-89": 2, "90-99": 0, "100": 1}
    assert report["warning_codes"] == {"READ_ERROR": 1, "SCRIPTED_DEFERRED": 1, "X": 2}
    assert report["folder_scan_warning_codes"] == {"SCAN_BAD_FILENAME": 1}
    assert report["scripted_views"] == 1


def test_aggregate_duplicate_ids_counts_only():
    report = aggregate([facts("A", "p1"), facts("A", "p2"), facts("B", "p1"), facts("B", "p1"),
                        facts("C"), facts("A", status="failed", id_from_stem=True)])
    assert report["duplicate_view_ids"] == {"ids_shared": 2, "files_involved": 4,
                                            "ids_across_packages": 1}
    assert "A" not in format_json(report)


def test_aggregate_empty_folder():
    report = aggregate([])
    assert report["files"]["total"] == 0
    assert "values (sorted): none" in format_text(report)


# --- whole-folder audit -----------------------------------------------------------------

def test_run_audit_on_fixtures_json():
    report = json.loads(run_audit(FIXTURES, "json"))
    files = report["files"]
    assert files["total"] == len(ALL_FIXTURES)
    assert files["parse_status"]["failed"] == 1          # truncated.calculationview
    assert files["not_well_formed"] == 1
    assert report["warning_codes"]["XML_SYNTAX"] == 1
    assert report["xsi_types"]["Calculation:JoinView"] == 1
    assert report["enum_values"]["DataSource@type"]["CALCULATION_VIEW"] >= 1
    assert report["functions"]["known"]["parsed"]["if"] >= 1
    assert report["functions"]["known"]["from_unparsed_text"]["daysbetween"] == 1
    assert report["functions"]["unrecognised"] == {"parsed": {}, "from_unparsed_text": {}}
    assert report["resource_uri_shapes"]["DataSource/resourceUri"][
        "/<package>/calculationviews/<name>"] >= 1
    assert report["unknown_elements"]["scenario"]["informationModelLayout"] == 1
    assert report["unknown_elements"]["viewAttribute"]["filter"] == 1


def test_run_audit_is_deterministic_and_sorted():
    first = run_audit(FIXTURES, "json")
    assert first == run_audit(FIXTURES, "json")
    assert first == json.dumps(json.loads(first), sort_keys=True, indent=2) + "\n"
    assert run_audit(FIXTURES, "text") == run_audit(FIXTURES, "text")


def test_run_audit_text_sections():
    text = run_audit(FIXTURES, "text")
    for heading in ("== Files ==", "== Parse status ==", "== Coverage ==", "== Warning codes ==",
                    "== Namespace URIs", "== Elements ==", "== Element children",
                    "== Attributes", "== xsi:type values ==", "== Enum attribute values",
                    "== resourceUri shapes", "== Expressions ==", "== Known column-engine functions",
                    "== Unrecognised function names",
                    "== UNKNOWN_ELEMENT", "== Duplicate view ids =="):
        assert heading in text
    assert "Calculation:JoinView: 1" in text
    assert "DataSource@type = DATA_BASE_TABLE:" in text


def test_run_audit_counts_garbage_file_as_failed(tmp_path):
    (tmp_path / "G.calculationview").write_bytes(b"\x00\xffnot xml")
    (tmp_path / "ignored.txt").write_text("x")
    report = json.loads(run_audit(tmp_path, "json"))
    assert report["files"]["total"] == 1
    assert report["files"]["parse_status"] == {"failed": 1}
    assert report["warning_codes"] == {"XML_SYNTAX": 1}


def test_run_audit_bad_format_and_folder(tmp_path):
    with pytest.raises(ValueError):
        run_audit(tmp_path, "xml")
    with pytest.raises(NotADirectoryError):
        run_audit(tmp_path / "missing", "text")


# --- leak test --------------------------------------------------------------------------

_RECOVER = etree.XMLParser(recover=True, resolve_entities=False, no_network=True, load_dtd=False)
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Function names the fixtures call; printing these is the point of the functions section.
FIXTURE_FUNCTIONS = {"if", "leftstr", "daysbetween"}


def _root(path):
    return etree.fromstring(path.read_bytes(), _RECOVER)


def _elements(root):
    return [] if root is None else [el for el in root.iter() if isinstance(el.tag, str)]


def harvest_business_strings(paths) -> set[str]:
    """Every attribute value and text node of every fixture, whole and tokenised, plus
    resourceUri segments: a superset of what the audit must never print."""
    found: set[str] = set()

    def add(value: str) -> None:
        value = value.strip()
        found.add(value)
        found.update(_TOKEN_RE.findall(value))
        found.update(re.split(r"/|::", value))

    for path in paths:
        for el in _elements(_root(path)):
            for value in el.attrib.values():
                add(value)
            for prefix, uri in el.nsmap.items():   # namespace declarations
                add(uri)
                if prefix:
                    add(prefix)
            if el.text and el.text.strip():
                add(el.text)
    return found


def allowed_strings(paths) -> set[str]:
    """Structural words the audit is allowed to print."""
    allowed = set(FIXTURE_FUNCTIONS) | set(audit_scan.URI_KEYWORDS)
    for path in paths:
        root = _root(path)
        for el in _elements(root):
            tag = etree.QName(el).localname
            allowed.add(tag)
            for uri in el.nsmap.values():   # SAP and W3C namespace URIs print by design
                if re.match(r"http://www\.sap\.com/ndb/|http://www\.w3\.org/", uri):
                    allowed.add(uri)
                    allowed.update(_TOKEN_RE.findall(uri))
                    allowed.update(re.split(r"/|::", uri))
            for name, value in el.attrib.items():
                attr = etree.QName(name).localname
                allowed.add(attr)
                if etree.QName(name).namespace == XSI_NS:
                    allowed.add(value)
                    allowed.update(value.split(":"))
                elif (el is root and attr in audit_scan.ROOT_ENUM_ATTRIBUTES) or \
                        (tag, attr) in audit_scan.ENUM_ATTRIBUTES:
                    allowed.add(value)
    return allowed


def fixed_vocabulary(empty_dir, fmt) -> set[str]:
    """Words the audit prints whatever the input: its own headings and keys, and the
    values of the IR's status and view-type enums."""
    empty_dir.mkdir(exist_ok=True)
    words = set(re.findall(r"[A-Za-z]+", run_audit(empty_dir, fmt)))
    return words | {s.value for s in ParseStatus} | {t.value for t in ViewType}


@pytest.fixture
def leak_folder(tmp_path):
    """Every fixture, plus the canary in a package dir named leakcanary_pkg, under a root
    whose own name is a canary too (the audit must not echo its folder)."""
    root = tmp_path / "LeakCanary_root"
    for path in ALL_FIXTURES:
        dest = root / path.relative_to(FIXTURES)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(path, dest)
    pkg = root / "leakcanary_pkg" / "LEAKCANARY_sub"
    pkg.mkdir(parents=True)
    shutil.copy(FIXTURES / LEAK, pkg / "LEAKCANARY_VIEW.calculationview")
    (pkg / "LeakCanary_garbage.hdbcalculationview").write_bytes(b"LEAKCANARY not xml")
    return root


@pytest.mark.parametrize("fmt", ["text", "json"])
def test_audit_output_has_no_business_content(leak_folder, fmt):
    output = run_audit(leak_folder, fmt)
    assert "leakcanary" not in output.lower()

    paths = sorted(leak_folder.rglob("*.calculationview"))
    allowed = allowed_strings(paths) | fixed_vocabulary(leak_folder.parent / "empty", fmt)
    path_parts = {part for p in leak_folder.rglob("*") for part in p.relative_to(leak_folder).parts}
    path_parts |= {p.stem for p in paths}
    candidates = (harvest_business_strings(paths) | path_parts) - allowed
    leaks = sorted(s for s in candidates
                   if len(s) >= 3 and not re.fullmatch(r"[\d.]+", s) and s in output)
    assert leaks == [], leaks


def test_leak_fixture_exercises_every_hiding_place(fixture_bytes):
    """Guards the leak test itself: the canary must sit in each place the plan names."""
    data = fixture_bytes(LEAK).decode("utf-8")
    for needle in ('id="LEAKCANARY_VIEW"', 'defaultDescription="LeakCanary', 'id="LEAKCANARY_DS_',
                   'schemaName="LEAKCANARY_', 'columnObjectName="LEAKCANARY_',
                   "<resourceUri>/leakcanary.pkg/", 'viewAttribute id="LEAKCANARY_',
                   "'LEAKCANARY_LITERAL'", "'LEAKCANARY_FILTER_VALUE'",
                   'variable id="LEAKCANARY_IP"', 'defaultValue="LEAKCANARY_DEFAULT"',
                   'expressionLanguage="SQL"', 'xmlns:lc="urn:leakcanary:ns"',
                   'lc:note="LEAKCANARY_NS_VALUE"'):
        assert needle in data
    report = aggregate([FileFacts(suffix=".calculationview", parse_status="partial",
                                  view_type="graphical", coverage_pct=50.0,
                                  structure=scan_structure(data.encode("utf-8")))])
    assert report["expressions"] == {"column_engine_parsed": 3, "column_engine_unparsed": 1,
                                     "sql": 1}
    assert report["functions"] == {
        "known": {"parsed": {"if": 1, "leftstr": 1}, "from_unparsed_text": {"daysbetween": 1}},
        "unrecognised": {"parsed": {}, "from_unparsed_text": {}},
    }
    assert report["namespaces"][OTHER] == 1


# --- fix round: namespaces, function catalogue, duplicate ids -----------------------------

def test_foreign_namespaces_and_their_attributes_are_masked():
    data = (b'<scenario xmlns="urn:acme:secret" xmlns:sap="http://www.sap.com/ndb/X.ecore" '
            b'xmlns:acme="http://acme.example/ns" acme:flag="1" sap:ok="1" '
            b'xmlns:w="http://www.w3.org/2001/XMLSchema-instance" w:type="a:B"/>')
    s = scan_structure(data)
    assert s.namespaces == {OTHER: 1, "http://www.sap.com/ndb/X.ecore": 1,
                            "http://www.w3.org/2001/XMLSchema-instance": 1}
    assert set(s.attributes) == {("scenario", f"{OTHER}:flag"), ("scenario", "sap:ok"),
                                 ("scenario", "w:type")}
    assert "acme" not in format_json(aggregate([FileFacts(
        suffix=".calculationview", parse_status="failed", view_type="unknown", coverage_pct=0.0,
        structure=s)]))


def test_function_names_split_into_known_and_unrecognised():
    data = scenario(
        '<calculationViews><calculationView xsi:type="Calculation:ProjectionView" id="P">'
        '<calculatedViewAttributes>'
        '<calculatedViewAttribute id="A" expressionLanguage="COLUMN_ENGINE">'
        '<formula>if(myfunc("C") = 1, rtrim("D"), 0)</formula></calculatedViewAttribute>'
        '<calculatedViewAttribute id="B" expressionLanguage="COLUMN_ENGINE">'
        '<formula>weird_fn("C", midstr("D", 1, 2)</formula></calculatedViewAttribute>'
        '</calculatedViewAttributes></calculationView></calculationViews>')
    report = aggregate([FileFacts(suffix=".calculationview", parse_status="partial",
                                  view_type="graphical", coverage_pct=50.0,
                                  structure=scan_structure(data))])
    assert report["functions"] == {
        "known": {"parsed": {"if": 1, "rtrim": 1}, "from_unparsed_text": {"midstr": 1}},
        "unrecognised": {"parsed": {"myfunc": 1}, "from_unparsed_text": {"weird_fn": 1}},
    }
    text = format_text(report)
    assert "== Unrecognised function names (parsed expressions; review before sharing) ==\nmyfunc: 1" in text


def test_known_function_catalogue_covers_the_basics():
    assert {"if", "case", "isnull", "leftstr", "midstr", "daysbetween", "coalesce", "match",
            "in", "component", "format"} <= KNOWN_FUNCTIONS
    assert all(re.fullmatch(r"[a-z_][a-z0-9_]*", name) for name in KNOWN_FUNCTIONS)


NO_LOGICAL_MODEL = ('<?xml version="1.0"?><Calculation:scenario '
                    'xmlns:Calculation="http://www.sap.com/ndb/BiModelCalculation.ecore" '
                    'id="SHARED_ID"><dataSources/></Calculation:scenario>')


def test_duplicate_ids_count_failed_views_with_a_real_id(tmp_path):
    for pkg in ("p1", "p2"):
        (tmp_path / pkg).mkdir()
        (tmp_path / pkg / f"FILE_{pkg}.calculationview").write_text(NO_LOGICAL_MODEL)
    (tmp_path / "p1" / "SAME.calculationview").write_bytes(b"not xml")
    (tmp_path / "p2" / "SAME.calculationview").write_text(
        '<Calculation:scenario xmlns:Calculation="urn:x"/>')   # no id: falls back to the stem
    report = json.loads(run_audit(tmp_path, "json"))
    assert report["warning_codes"]["MISSING_LOGICAL_MODEL"] == 3   # incl. the id-less one
    assert report["files"]["parse_status"] == {"failed": 4}
    assert report["duplicate_view_ids"] == {"ids_shared": 1, "files_involved": 2,
                                            "ids_across_packages": 1}


def test_file_facts_id_from_stem(tmp_path):
    cases = {"A.calculationview": NO_LOGICAL_MODEL, "B.calculationview": "garbage",
             "C.calculationview": "<other id='X'/>", "D.calculationview": "<scenario id=''/>"}
    for name, body in cases.items():
        (tmp_path / name).write_text(body)
    got = {name: file_facts(tmp_path / name, tmp_path).id_from_stem for name in cases}
    assert got == {"A.calculationview": False, "B.calculationview": True,
                   "C.calculationview": True, "D.calculationview": True}


# --- final-review fix round: root id shapes ----------------------------------------------

@pytest.mark.parametrize("value, shape", [
    ("CV_SALES_01", "plain"),
    ("pkg.sub::CV_SALES", "<namespace>::<name>"),
    ("a::b::c", "<other>"),
    ("::CV", "<other>"),
    ("pkg/CV", "<other>"),
    ("CV SALES", "<other>"),
    ("CV-1", "<other>"),
    (None, "<missing>"),
    ("", "<missing>"),
])
def test_root_id_shape(value, shape):
    assert audit_scan.root_id_shape(value) == shape


def test_root_id_shapes_are_counted_without_values():
    files = [FileFacts(suffix=".calculationview", parse_status="ok", view_type="graphical",
                       coverage_pct=100.0, structure=scan_structure(data))
             for data in (scenario("", "").replace(b'id="V"', b'id="SECRET_A"'),
                          scenario("").replace(b'id="V"', b'id="secret.pkg::SECRET_B"'),
                          scenario("").replace(b'id="V"', b'id="secret/SECRET_C"'),
                          scenario("").replace(b'id="V" ', b""),
                          scenario("").replace(b'id="V"', b'id="SECRET_D"'))]
    files.append(FileFacts(suffix=".calculationview", parse_status="failed", view_type="unknown",
                           coverage_pct=0.0, structure=scan_structure(b"not xml")))
    report = aggregate(files)
    assert report["root_id_shapes"] == {"<missing>": 1, "<namespace>::<name>": 1, "<other>": 1,
                                        "plain": 2}
    for text in (format_text(report), format_json(report)):
        assert "secret" not in text.lower()
    assert "== Root id shapes ==" in format_text(report)
    assert "plain: 2" in format_text(report)


def test_leak_fixture_root_id_shape(fixture_bytes):
    assert scan_structure(fixture_bytes(LEAK)).root_id_shape == "plain"
