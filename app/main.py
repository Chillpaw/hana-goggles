"""FastAPI app. Binds to loopback only; there is deliberately no way to change the host."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

HOST = "127.0.0.1"
WEB_DIR = Path(__file__).parent / "web"
DEFAULT_DB = Path("calcview.db")
DB_ENV = "CALCVIEW_DB"


def default_db_path() -> Path:
    """`CALCVIEW_DB` if set, else `./calcview.db`."""
    return Path(os.environ.get(DB_ENV) or DEFAULT_DB)


def create_app(db_path: Path | None = None) -> FastAPI:
    """Build the app. The database is not opened here: routes open a Store per request
    (see `app.web.deps.get_store`), so creating the app never creates the db file."""
    app = FastAPI(title="CalcView Migrator", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.db_path = Path(db_path if db_path is not None else default_db_path()).resolve()
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=WEB_DIR / "templates")

    @app.get("/")
    def index(request: Request):
        return templates.TemplateResponse(request, "index.html", {})

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
