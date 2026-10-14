"""FastAPI app. Binds to loopback only; there is deliberately no way to change the host."""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

HOST = "127.0.0.1"
WEB_DIR = Path(__file__).parent / "web"


def create_app() -> FastAPI:
    app = FastAPI(title="CalcView Migrator", docs_url=None, redoc_url=None, openapi_url=None)
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
