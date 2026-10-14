import pytest
from conftest import FIXTURES, MAIN
from lxml import etree

import app.parsers.dispatch as dispatch
from app.parsers import xmlutil
from app.ir.models import ParseResult, ParseStatus, Severity


@pytest.mark.parametrize("data", [
    b"",
    b"not xml at all",
    b"<a>",
    b"\xff\xfe\x00\x01",
    b"<?xml version='1.0'?><other/>",
    b"<?xml version='1.0'?><!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><x>&e;</x>",
])
def test_garbage_yields_a_failed_result(data):
    result = dispatch.parse_bytes(data, file_name="junk.calculationview")
    assert result.view.parse_status is ParseStatus.FAILED
    assert result.warnings and result.warnings[0].severity is Severity.ERROR


def test_every_truncation_of_the_main_fixture_returns_a_result():
    data = (FIXTURES / MAIN).read_bytes()
    for cut in range(0, len(data), 53):
        r = dispatch.parse_bytes(data[:cut], file_name="cut.calculationview")
        assert isinstance(r, ParseResult)
        assert "PARSER_CRASH" not in [w.code for w in r.warnings]


def test_internal_bug_becomes_a_parser_crash_warning(monkeypatch):
    def boom(root, view, **_kwargs):
        raise RuntimeError("simulated bug")

    monkeypatch.setattr(dispatch, "parse_graphical", boom)
    result = dispatch.parse_bytes((FIXTURES / MAIN).read_bytes(), file_name="x.calculationview")
    assert result.view.parse_status is ParseStatus.FAILED
    assert result.warnings[-1].code == "PARSER_CRASH"
    assert "simulated bug" in result.warnings[-1].message


def test_unreadable_file_becomes_a_read_error(tmp_path):
    result = dispatch.parse_file(tmp_path / "missing.calculationview")
    assert result.warnings[0].code == "READ_ERROR"


def test_external_entities_are_never_resolved(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("SENTINEL_SECRET_42")
    data = (
        f'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "{secret.as_uri()}">]><x>&e;</x>'
    ).encode()
    root, _, _ = xmlutil.load(data)
    assert root is not None
    assert "SENTINEL_SECRET_42" not in etree.tostring(root, encoding="unicode")
