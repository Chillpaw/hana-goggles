"""FastAPI app. Binds to loopback only; there is deliberately no way to change the host."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.web.estate_routes import router as estate_router
from app.web.notes import router as notes_router
from app.web.routes import register_error_handlers, router
from app.web.security import add_security_middleware

HOST = "127.0.0.1"
WEB_DIR = Path(__file__).parent / "web"
DEFAULT_DB = Path("calcview.db")
DB_ENV = "CALCVIEW_DB"


def default_db_path() -> Path:
    """`CALCVIEW_DB` if set, else `./calcview.db`."""
    return Path(os.environ.get(DB_ENV) or DEFAULT_DB)


def create_app(db_path: Path | None = None) -> FastAPI:
    """Build the app. The database is not opened here: routes open one Store per request
    (see `app.web.deps`), so creating the app never creates the db file."""
    app = FastAPI(title="CalcView Migrator", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.db_path = Path(db_path if db_path is not None else default_db_path()).resolve()
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    register_error_handlers(app)
    add_security_middleware(app)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.include_router(router)
    app.include_router(estate_router)
    app.include_router(notes_router)

    return app


# Freezes cwd and $CALCVIEW_DB at import time; never opens the db (routes do, per request).
app = create_app()
