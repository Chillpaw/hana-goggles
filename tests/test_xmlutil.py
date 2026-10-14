from conftest import MAIN

from app.parsers import xmlutil as x

TWO_PREFIXES = b"""<?xml version="1.0"?>
<calc:scenario xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xmlns:calc="http://www.sap.com/ndb/BiModelCalculation.ecore">
  <!-- a comment -->
  <calculationViews>
    <calculationView xsi:type="calc:ProjectionView" id="P"/>
    <calculationView xsi:type="JoinView" id="J"/>
  </calculationViews>
</calc:scenario>"""


def test_load_returns_root_for_well_formed_xml(fixture_bytes):
    root, error, line = x.load(fixture_bytes(MAIN))
    assert error is None and line is None
    assert x.local(root) == "scenario"


def test_load_reports_syntax_error_with_line(fixture_bytes):
    root, error, line = x.load(fixture_bytes("malformed/truncated.calculationview"))
    assert root is None
    assert error
    assert isinstance(line, int)


def test_load_rejects_empty_and_binary_input():
    assert x.load(b"")[0] is None
    assert x.load(b"\xff\xfe\x00\x01")[0] is None


def test_children_skip_comments_and_match_local_names():
    root, _, _ = x.load(TWO_PREFIXES)
    assert [x.local(c) for c in x.children(root)] == ["calculationViews"]
    views = x.children(x.child(root, "calculationViews"), "calculationView")
    assert [v.get("id") for v in views] == ["P", "J"]


def test_xsi_type_name_ignores_prefix():
    root, _, _ = x.load(TWO_PREFIXES)
    views = x.descendants(root, "calculationView")
    assert [x.xsi_type_name(v) for v in views] == ["ProjectionView", "JoinView"]


def test_helpers_are_none_safe():
    assert x.children(None, "a") == []
    assert x.child(None, "a") is None
    assert x.text(None) is None
    assert x.first_descendant(None, "a") is None


def test_text_strips_whitespace():
    root, _, _ = x.load(b"<a>  hello  </a>")
    assert x.text(root) == "hello"
