import sqlite3

import pytest
from fastapi import Depends, FastAPI
from helpers import local_client

import app.cli as cli
from app.ir.store import Store
from app.main import HOST, create_app
from app.web.deps import get_existing_store, get_store


def test_health_endpoint():
    client = local_client(create_app())
    assert client.get("/health").json() == {"status": "ok"}


def test_index_renders():
    response = local_client(create_app()).get("/")
    assert response.status_code == 200
    assert "CalcView Migrator" in response.text


def test_host_is_loopback():
    assert HOST == "127.0.0.1"


def test_serve_binds_loopback_only(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: calls.update(app=app, **kw))
    db = tmp_path / "p.db"
    assert cli.main(["serve", "--port", "9001", "--db", str(db)]) == 0
    app = calls.pop("app")
    assert isinstance(app, FastAPI)
    assert app.state.db_path == db.resolve()
    assert calls == {"host": "127.0.0.1", "port": 9001}
    assert not db.exists()  # serving opens the store lazily, per request


def test_serve_default_db_is_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CALCVIEW_DB", raising=False)
    calls = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: calls.update(app=app, **kw))
    assert cli.main(["serve"]) == 0
    assert calls["app"].state.db_path == (tmp_path / "calcview.db").resolve()
    assert calls["port"] == 8765


def test_serve_without_db_uses_env(monkeypatch, tmp_path):
    db = tmp_path / "env.db"
    monkeypatch.setenv("CALCVIEW_DB", str(db))
    calls = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: calls.update(app=app, **kw))
    assert cli.main(["serve"]) == 0
    assert calls["app"].state.db_path == db.resolve()


def test_serve_has_no_host_option():
    with pytest.raises(SystemExit):
        cli.main(["serve", "--host", "0.0.0.0"])


def test_create_app_with_db_serves_health_without_creating_db(tmp_path):
    db = tmp_path / "p.db"
    app = create_app(db)
    assert app.state.db_path == db.resolve()
    assert local_client(app).get("/health").json() == {"status": "ok"}
    assert local_client(app).get("/").status_code == 200
    assert not db.exists()


def test_create_app_default_reads_env(monkeypatch, tmp_path):
    db = tmp_path / "env.db"
    monkeypatch.setenv("CALCVIEW_DB", str(db))
    assert create_app().state.db_path == db.resolve()
    monkeypatch.delenv("CALCVIEW_DB")
    monkeypatch.chdir(tmp_path)
    assert create_app().state.db_path == (tmp_path / "calcview.db").resolve()
    assert not (tmp_path / "calcview.db").exists()


def test_get_store_opens_per_request_and_closes(tmp_path):
    db = tmp_path / "p.db"
    app = create_app(db)
    opened: list[Store] = []

    @app.get("/probe")
    def probe(store: Store = Depends(get_store)):
        opened.append(store)
        return {"project": store.get_project()}

    client = local_client(app)
    assert client.get("/probe").json() == {"project": None}
    assert client.get("/probe").status_code == 200
    assert len(opened) == 2 and opened[0] is not opened[1]
    assert db.exists()
    for store in opened:  # closed after the response
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            store.conn.execute("SELECT 1")


def test_get_existing_store_yields_none_and_never_creates_db(tmp_path):
    db = tmp_path / "p.db"
    app = create_app(db)

    @app.get("/probe")
    def probe(store: Store | None = Depends(get_existing_store)):
        return {"store": store is not None, "project": store.get_project() if store else None}

    client = local_client(app)
    assert client.get("/probe").json() == {"store": False, "project": None}
    assert not db.exists()
    Store(db).close()
    assert client.get("/probe").json() == {"store": True, "project": None}


def test_serve_fails_fast_on_unusable_db(monkeypatch, tmp_path, capsys):
    db = tmp_path / "other.db"
    db.write_bytes(b"this is not sqlite at all, just text" * 10)
    called = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: called.append(app))
    assert cli.main(["serve", "--db", str(db)]) == 2
    err = capsys.readouterr().err
    assert called == [] and err.count("\n") == 1 and "cannot use database" in err


def test_serve_accepts_existing_project_db(monkeypatch, tmp_path):
    db = tmp_path / "p.db"
    Store(db).close()
    called = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: called.append(app))
    assert cli.main(["serve", "--db", str(db)]) == 0 and len(called) == 1
