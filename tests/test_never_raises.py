import pytest
from conftest import FIXTURES, MAIN

import app.parsers.dispatch as dispatch
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
        assert isinstance(dispatch.parse_bytes(data[:cut], file_name="cut.calculationview"), ParseResult)


def test_internal_bug_becomes_a_parser_crash_warning(monkeypatch):
    def boom(root, view):
        raise RuntimeError("simulated bug")

    monkeypatch.setattr(dispatch, "parse_graphical", boom)
    result = dispatch.parse_bytes((FIXTURES / MAIN).read_bytes(), file_name="x.calculationview")
    assert result.view.parse_status is ParseStatus.FAILED
    assert result.warnings[-1].code == "PARSER_CRASH"
    assert "simulated bug" in result.warnings[-1].message


def test_unreadable_file_becomes_a_read_error(tmp_path):
    result = dispatch.parse_file(tmp_path / "missing.calculationview")
    assert result.warnings[0].code == "READ_ERROR"
