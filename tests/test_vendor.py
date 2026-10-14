import re

import pytest
from fastapi.testclient import TestClient

from app.main import WEB_DIR, create_app

VENDOR_DIR = WEB_DIR / "static" / "vendor"
VENDORED = ["htmx.min.js", "cytoscape.min.js", "dagre.min.js", "cytoscape-dagre.js"]
REMOTE_REF = re.compile(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//""", re.IGNORECASE)


@pytest.mark.parametrize("name", VENDORED)
def test_vendored_file_is_present_and_served_locally(name):
    assert (VENDOR_DIR / name).stat().st_size > 1000
    response = TestClient(create_app()).get(f"/static/vendor/{name}")
    assert response.status_code == 200


def test_templates_reference_no_remote_urls():
    for template in (WEB_DIR / "templates").rglob("*.html"):
        assert not REMOTE_REF.search(template.read_text(encoding="utf-8")), template.name


def test_every_script_in_index_is_vendored():
    html = (WEB_DIR / "templates" / "index.html").read_text(encoding="utf-8")
    for src in re.findall(r'<script src="/static/vendor/([^"]+)"', html):
        assert (VENDOR_DIR / src).is_file(), src
