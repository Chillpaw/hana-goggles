import re

import pytest
from helpers import local_client

from app.main import WEB_DIR, create_app

VENDOR_DIR = WEB_DIR / "static" / "vendor"
APP_JS_DIR = WEB_DIR / "static" / "app"
VENDORED = ["htmx.min.js", "cytoscape.min.js", "dagre.min.js", "cytoscape-dagre.js"]
REMOTE_REF = re.compile(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//""", re.IGNORECASE)
ANY_URL = re.compile(r"https?://", re.IGNORECASE)


@pytest.mark.parametrize("name", VENDORED)
def test_vendored_file_is_present_and_served_locally(name):
    assert (VENDOR_DIR / name).stat().st_size > 1000
    response = local_client(create_app()).get(f"/static/vendor/{name}")
    assert response.status_code == 200


def test_templates_reference_no_remote_urls():
    for template in (WEB_DIR / "templates").rglob("*.html"):
        assert not REMOTE_REF.search(template.read_text(encoding="utf-8")), template.name


def test_templates_contain_no_http_urls_at_all():
    templates = list((WEB_DIR / "templates").rglob("*.html"))
    assert len(templates) >= 5
    for template in templates:
        assert not ANY_URL.search(template.read_text(encoding="utf-8")), template.name


def test_first_party_js_contains_no_urls():
    scripts = sorted(APP_JS_DIR.glob("*.js"))
    assert "viewgraph.js" in [p.name for p in scripts]
    for script in scripts:
        text = script.read_text(encoding="utf-8")
        assert not ANY_URL.search(text), script.name
        assert not re.search(r"(?:fetch|XMLHttpRequest|import\s*\()", text), script.name


def test_every_script_in_every_template_is_local():
    for template in (WEB_DIR / "templates").rglob("*.html"):
        html = template.read_text(encoding="utf-8")
        for src in re.findall(r'<script[^>]*\ssrc="([^"]+)"', html):
            assert src.startswith("/static/"), (template.name, src)
            assert (WEB_DIR / src.removeprefix("/")).is_file(), (template.name, src)


def test_first_party_js_is_served():
    response = local_client(create_app()).get("/static/app/viewgraph.js")
    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_cdn_backed_api_docs_are_disabled(path):
    assert local_client(create_app()).get(path).status_code == 404
