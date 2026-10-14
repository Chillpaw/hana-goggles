"""`calcview import` and the --db options. Imports go into a tmp database only."""
import shutil
import sqlite3

import pytest
from conftest import FIXTURES

import app.cli as cli
from app.ir.store import Store

VIEW = "GENERIC_TAX_REPORTING_CUBE"
PRODUCER = "SOURCE_VIEW_01"


@pytest.fixture
def folder(tmp_path):
    dest = tmp_path / "views"
    shutil.copytree(FIXTURES / "graphical", dest, ignore=shutil.ignore_patterns("*.ir.json"))
    return dest


def _run(capsys, *argv):
    code = cli.main(list(argv))
    out, err = capsys.readouterr()
    return code, out.splitlines(), err


def test_import_prints_report_and_stores_views(tmp_path, folder, capsys):
    db = tmp_path / "p.db"
    code, lines, err = _run(capsys, "import", str(folder), "--db", str(db))
    assert code == 0 and err == ""
    assert lines == [
        "Project: views",
        f"Database: {db}",
        "Added: 2",
        "Changed: 0",
        "Unchanged: 0",
        "Reparsed: 0",
        "Removed: 0",
        "Failed: 0",
        "Stale annotations: 0",
        "Internal dependencies: 1",
        f"  {VIEW} -> {PRODUCER}",
        "Leaf sources: 3",
        f"  {VIEW} -> table:SCHEMA_1.TABLE_A",
        f"  {VIEW} -> table:SCHEMA_1.TABLE_B",
        f"  {PRODUCER} -> table:SCHEMA_1.TABLE_C",
        "Unresolved: 0",
        "Cycles: 0",
        "Deploy order: 2",
        f"  1. {PRODUCER}",
        f"  2. {VIEW}",
        "Warnings: 0",
    ]
    with Store(db) as store:
        assert [v.id for v in store.list_views()] == [VIEW, PRODUCER]


def test_reimport_is_unchanged_and_output_deterministic(tmp_path, folder, capsys):
    db = tmp_path / "p.db"
    _run(capsys, "import", str(folder), "--db", str(db))
    code, first, _ = _run(capsys, "import", str(folder), "--db", str(db))
    _, second, _ = _run(capsys, "import", str(folder), "--db", str(db))
    assert code == 0 and first == second
    assert "Added: 0" in first and "Unchanged: 2" in first


def test_import_name_option(tmp_path, folder, capsys):
    db = tmp_path / "p.db"
    code, lines, _ = _run(capsys, "import", str(folder), "--db", str(db), "--name", "Tax")
    assert code == 0 and lines[0] == "Project: Tax"
    with Store(db) as store:
        assert store.get_project().name == "Tax"


def test_import_prints_warnings_with_severity_and_code(tmp_path, folder, capsys):
    shutil.copy(folder / f"{VIEW}.calculationview", folder / f"COPY_{VIEW}.calculationview")
    code, lines, _ = _run(capsys, "import", str(folder), "--db", str(tmp_path / "p.db"))
    assert code == 0
    assert "Warnings: 1" in lines
    warning = lines[lines.index("Warnings: 1") + 1]
    assert warning.startswith("  ERROR DUPLICATE_VIEW_ID ")


def test_import_prints_cycles(tmp_path, capsys):
    code, lines, _ = _run(capsys, "import", str(FIXTURES / "estate_cycle"),
                          "--db", str(tmp_path / "p.db"))
    assert code == 0
    assert "Cycles: 1" in lines
    assert lines[lines.index("Cycles: 1") + 1] == "  CYCLE_A, CYCLE_B"
    assert any(line.startswith("  ERROR CYCLE ") for line in lines)


def test_import_non_directory_exits_2(tmp_path, capsys):
    db = tmp_path / "p.db"
    missing = tmp_path / "nope"
    code, lines, err = _run(capsys, "import", str(missing), "--db", str(db))
    assert code == 2 and lines == []
    assert err.count("\n") == 1 and "not a directory" in err
    assert not db.exists()


def test_import_file_instead_of_folder_exits_2(tmp_path, folder, capsys):
    code, _, err = _run(capsys, "import", str(folder / f"{VIEW}.calculationview"),
                        "--db", str(tmp_path / "p.db"))
    assert code == 2 and err.count("\n") == 1


def test_import_into_foreign_database_exits_2(tmp_path, folder, capsys):
    db = tmp_path / "other.db"
    db.write_bytes(b"this is not sqlite at all, just text" * 10)
    code, lines, err = _run(capsys, "import", str(folder), "--db", str(db))
    assert code == 2 and lines == [] and err.count("\n") == 1


def test_import_default_db_is_cwd(tmp_path, folder, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CALCVIEW_DB", raising=False)
    code, lines, _ = _run(capsys, "import", str(folder))
    assert code == 0 and lines[1] == "Database: calcview.db"
    assert (tmp_path / "calcview.db").exists()


def test_import_honours_env_db(tmp_path, folder, capsys, monkeypatch):
    db = tmp_path / "env.db"
    monkeypatch.setenv("CALCVIEW_DB", str(db))
    code, lines, _ = _run(capsys, "import", str(folder))
    assert code == 0 and lines[1] == f"Database: {db}" and db.exists()


def test_unresolved_lists_views_outside_the_folder(tmp_path, folder, capsys):
    (folder / f"{PRODUCER}.calculationview").unlink()
    code, lines, _ = _run(capsys, "import", str(folder), "--db", str(tmp_path / "p.db"))
    assert code == 0
    assert "Internal dependencies: 0" in lines and "Leaf sources: 2" in lines
    assert lines[lines.index("Unresolved: 1") + 1] == f"  {VIEW} -> view:{PRODUCER}"


def test_failed_import_removes_db_it_created(tmp_path, folder, capsys, monkeypatch):
    db = tmp_path / "p.db"

    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(cli, "import_folder", boom)
    code, lines, err = _run(capsys, "import", str(folder), "--db", str(db))
    assert code == 2 and lines == [] and err.count("\n") == 1
    assert not db.exists()


def test_failed_import_keeps_existing_db(tmp_path, folder, capsys, monkeypatch):
    db = tmp_path / "p.db"
    Store(db).close()
    monkeypatch.setattr(cli, "import_folder", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    code, _, _ = _run(capsys, "import", str(folder), "--db", str(db))
    assert code == 2 and db.exists()
