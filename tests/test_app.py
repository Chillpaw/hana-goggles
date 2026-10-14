import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import app.cli as cli
from app.ir.store import Store
from app.main import HOST, create_app
from app.web.deps import get_store


def test_health_endpoint():
    client = TestClient(create_app())
    assert client.get("/health").json() == {"status": "ok"}


def test_index_renders():
    response = TestClient(create_app()).get("/")
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
    assert TestClient(app).get("/health").json() == {"status": "ok"}
    assert TestClient(app).get("/").status_code == 200
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

    client = TestClient(app)
    assert client.get("/probe").json() == {"project": None}
    assert client.get("/probe").status_code == 200
    assert len(opened) == 2 and opened[0] is not opened[1]
    assert db.exists()
    for store in opened:  # closed after the response
        with pytest.raises(Exception):
            store.conn.execute("SELECT 1")
