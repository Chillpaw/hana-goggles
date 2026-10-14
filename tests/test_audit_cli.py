"""`calcview audit`: prints the structure-only report, never touches a database."""
import json

import pytest
from conftest import FIXTURES

import app.cli as cli
from app.audit import run_audit


def test_audit_text_matches_run_audit(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["audit", str(FIXTURES)]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert out == run_audit(FIXTURES, "text")
    assert "== xsi:type values ==" in out
    assert list(tmp_path.iterdir()) == []      # no calcview.db or anything else created


def test_audit_json(capsys):
    assert cli.main(["audit", str(FIXTURES), "--format", "json"]) == 0
    out, _ = capsys.readouterr()
    assert json.loads(out)["xsi_types"]["Calculation:JoinView"] == 1
    assert str(FIXTURES) not in out


def test_audit_missing_folder(capsys, tmp_path):
    assert cli.main(["audit", str(tmp_path / "missing")]) == 2
    out, err = capsys.readouterr()
    assert out == "" and "is not a directory" in err


def test_audit_rejects_unknown_format(capsys):
    with pytest.raises(SystemExit):
        cli.main(["audit", str(FIXTURES), "--format", "xml"])
