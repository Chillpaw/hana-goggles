import pytest
from fastapi.testclient import TestClient

import app.cli as cli
from app.main import HOST, create_app


def test_health_endpoint():
    client = TestClient(create_app())
    assert client.get("/health").json() == {"status": "ok"}


def test_index_renders():
    response = TestClient(create_app()).get("/")
    assert response.status_code == 200
    assert "CalcView Migrator" in response.text


def test_host_is_loopback():
    assert HOST == "127.0.0.1"


def test_serve_binds_loopback_only(monkeypatch):
    calls = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: calls.update(app=app, **kw))
    assert cli.main(["serve", "--port", "9001"]) == 0
    assert calls == {"app": "app.main:app", "host": "127.0.0.1", "port": 9001}


def test_serve_has_no_host_option():
    with pytest.raises(SystemExit):
        cli.main(["serve", "--host", "0.0.0.0"])
