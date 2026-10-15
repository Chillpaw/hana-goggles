"""Notes and sign-off: the view Notes tab, the views-list sign-off column and node notes
in the graph's side panel."""
import re
import shutil

import pytest
from conftest import FIXTURES
from helpers import local_client

from app.ingest.importer import import_folder
from app.ir.models import Annotation, SignoffStatus, TargetKind
from app.ir.store import Store
from app.main import create_app
from app.web.routes import node_notes_url, notes_url, orphaned_notes

VIEW = "GENERIC_TAX_REPORTING_CUBE"
PRODUCER = "SOURCE_VIEW_01"
NODE = f"{VIEW}/Projection_1"
CONSUMER_FILE = f"{VIEW}.calculationview"
SAME_ORIGIN = {"sec-fetch-site": "same-origin", "origin": "http://127.0.0.1"}
FULL = {"purpose_text": "Reports COL_1 by period", "owner": "OWNER_A",
        "signoff_status": "reviewed", "notes": "Checked with SME_A"}


@pytest.fixture
def folder(tmp_path):
    return shutil.copytree(FIXTURES / "graphical", tmp_path / "views",
                           ignore=shutil.ignore_patterns("*.ir.json"))


@pytest.fixture
def db(tmp_path, folder):
    path = tmp_path / "p.db"
    with Store(path) as store:
        import_folder(store, folder)
    return path


@pytest.fixture
def client(db):
    return local_client(create_app(db))


def _annotation(db, target_id, kind=None):
    """The view's annotation for VIEW / PRODUCER / other bare ids, else the node's."""
    if kind is None:
        kind = TargetKind.NODE if "/" in target_id else TargetKind.VIEW
    with Store(db) as store:
        return store.get_annotation(target_id, kind)


def _post(client, url, data, **kw):
    return client.post(url, data=data, headers=SAME_ORIGIN, follow_redirects=False, **kw)


def _notes_tab(client, view=VIEW):
    response = client.get(f"/views/{view}?tab=notes")
    assert response.status_code == 200
    return response.text


def _rename_node(folder, old, new):
    path = folder / CONSUMER_FILE
    path.write_text(path.read_text().replace(f'"{old}"', f'"{new}"').replace(f"#{old}", f"#{new}"))


def _reimport(db, folder):
    with Store(db) as store:
        import_folder(store, folder)


def _views_row(html, view):
    row = re.search(rf'<tr>\s*<td><a href="/views/{view}">.*?</tr>', html, re.DOTALL)
    assert row, f"no row for {view}"
    return row.group(0)


# ---------------------------------------------------------------- view notes

def test_notes_tab_shows_empty_form(client):
    html = _notes_tab(client)
    assert 'name="purpose_text"' in html and 'name="owner"' in html and 'name="notes"' in html
    for status in ("draft", "reviewed", "approved"):
        assert f'value="{status}"' in html
    assert f'action="{notes_url(VIEW)}"' in html
    assert "Not saved yet" in html


def test_save_and_reload(client, db):
    response = _post(client, notes_url(VIEW), FULL)
    assert response.status_code == 303
    assert response.headers["location"] == f"/views/{VIEW}?tab=notes"
    saved = _annotation(db, VIEW)
    assert saved.target_kind == TargetKind.VIEW
    assert (saved.purpose_text, saved.owner, saved.signoff_status, saved.notes) == (
        FULL["purpose_text"], "OWNER_A", SignoffStatus.REVIEWED, "Checked with SME_A")
    html = _notes_tab(client)
    assert "Reports COL_1 by period</textarea>" in html
    assert 'value="OWNER_A"' in html
    assert '<option value="reviewed" selected>' in html
    assert "Checked with SME_A</textarea>" in html
    assert saved.updated_at in html


def test_invalid_status_is_400_with_form(client, db):
    response = _post(client, notes_url(VIEW), {**FULL, "signoff_status": "done"})
    assert response.status_code == 400
    assert "not a sign-off status" in response.text
    assert 'name="purpose_text"' in response.text  # the form, re-rendered
    assert "Reports COL_1 by period</textarea>" in response.text  # with what was typed
    assert _annotation(db, VIEW) is None


@pytest.mark.parametrize("field", ["purpose_text", "owner", "notes"])
def test_overlong_field_is_400(client, db, field):
    response = _post(client, notes_url(VIEW), {**FULL, field: "x" * 20_001})
    assert response.status_code == 400 and "20000" in response.text.replace(" ", "")
    assert _annotation(db, VIEW) is None
    assert _post(client, notes_url(VIEW), {**FULL, field: "x" * 20_000}).status_code == 303


def test_notes_for_unknown_view_is_404(client, db):
    assert _post(client, notes_url("NO_SUCH_VIEW"), FULL).status_code == 404
    assert _annotation(db, "NO_SUCH_VIEW") is None


def test_notes_without_project_is_404(tmp_path):
    db = tmp_path / "none.db"
    client = local_client(create_app(db))
    assert _post(client, notes_url(VIEW), FULL).status_code == 404
    assert not db.exists()


def test_emptied_field_clears_saved_value(client, db):
    _post(client, notes_url(VIEW), FULL)
    assert _post(client, notes_url(VIEW), {**FULL, "owner": "", "notes": ""}).status_code == 303
    saved = _annotation(db, VIEW)
    assert (saved.owner, saved.notes, saved.purpose_text) == ("", "", FULL["purpose_text"])
    _post(client, node_notes_url(VIEW, NODE), {"signoff_status": "draft", "notes": "x"})
    _post(client, node_notes_url(VIEW, NODE), {"signoff_status": "draft", "notes": ""})
    assert _annotation(db, NODE).notes == ""


def test_hostile_note_text_is_escaped(client):
    hostile = '<script>alert(1)</script></textarea><img src=x onerror=alert(2)>'
    assert _post(client, notes_url(VIEW), {**FULL, "owner": hostile, "notes": hostile,
                                            "purpose_text": hostile}).status_code == 303
    for html in (_notes_tab(client), client.get("/views").text,
                 client.get(f"/views/{VIEW}").text):
        assert "<script>alert(1)" not in html and "<img src=x" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in _notes_tab(client)


def test_cross_site_notes_posts_are_refused(client, db):
    for url in (notes_url(VIEW), node_notes_url(VIEW, NODE)):
        for headers in ({"sec-fetch-site": "cross-site"}, {"origin": "http://evil.example"}):
            response = client.post(url, data=FULL, headers=headers, follow_redirects=False)
            assert response.status_code == 403
        response = client.post(url, content="notes=x", headers={"content-type": "text/plain"})
        assert response.status_code == 415
    assert _annotation(db, VIEW) is None and _annotation(db, NODE) is None


# ---------------------------------------------------------------- views list

def test_views_list_has_signoff_column(client):
    html = client.get("/views").text
    assert ">Sign-off</a>" in html
    assert "&mdash;" in _views_row(html, VIEW) or "—" in _views_row(html, VIEW)
    _post(client, notes_url(VIEW), {**FULL, "signoff_status": "approved"})
    html = client.get("/views").text
    assert "approved" in _views_row(html, VIEW)
    assert "approved" not in _views_row(html, PRODUCER)


def test_views_list_sorts_by_signoff(client):
    _post(client, notes_url(PRODUCER), {**FULL, "signoff_status": "approved"})
    html = client.get("/views?sort=-signoff").text
    assert html.index(f'href="/views/{PRODUCER}"') < html.index(f'href="/views/{VIEW}"')


# ---------------------------------------------------------------- stale

def test_reimport_of_changed_file_shows_stale_and_saving_clears_it(client, db, folder):
    _post(client, notes_url(VIEW), FULL)
    path = folder / CONSUMER_FILE
    path.write_text(path.read_text().replace("</Calculation:scenario>",
                                             "<!-- changed -->\n</Calculation:scenario>"))
    _reimport(db, folder)
    assert _annotation(db, VIEW).stale

    tab = _notes_tab(client)
    assert "Stale: view file changed" in tab
    assert "Stale: view file changed" in client.get(f"/views/{VIEW}?tab=steps").text
    listing = client.get("/views").text
    assert "Stale: view file changed" in _views_row(listing, VIEW)
    assert "Stale" not in _views_row(listing, PRODUCER)

    assert _post(client, notes_url(VIEW), FULL).status_code == 303
    assert not _annotation(db, VIEW).stale
    assert "Stale:" not in _notes_tab(client)
    assert "Stale:" not in _views_row(client.get("/views").text, VIEW)


# ---------------------------------------------------------------- node notes

def test_node_panel_has_notes_form(client):
    html = client.get(f"/node?view={VIEW}&node={NODE}").text
    assert f'hx-post="{node_notes_url(VIEW, NODE)}"' in html.replace("&amp;", "&")
    assert 'hx-target="#node-panel"' in html
    assert 'name="notes"' in html and 'name="signoff_status"' in html


def test_node_note_round_trip(client, db):
    response = _post(client, node_notes_url(VIEW, NODE),
                     {"owner": "OWNER_B", "signoff_status": "approved", "notes": "Step note 1"})
    assert response.status_code == 200
    assert 'class="node-panel"' in response.text  # the refreshed panel fragment
    assert "Step note 1</textarea>" in response.text and "Saved" in response.text
    saved = _annotation(db, NODE)
    assert saved.target_kind == TargetKind.NODE
    assert (saved.owner, saved.signoff_status, saved.notes) == (
        "OWNER_B", SignoffStatus.APPROVED, "Step note 1")
    html = client.get(f"/node?view={VIEW}&node={NODE}").text
    assert "Step note 1</textarea>" in html and '<option value="approved" selected>' in html
    # the view's Notes tab lists notes on its steps
    tab = _notes_tab(client)
    assert "Projection_1" in tab and "Step note 1" in tab


def test_node_note_keeps_fields_the_form_does_not_send(client, db):
    with Store(db) as store:
        store.save_annotation(Annotation(target_id=NODE, target_kind=TargetKind.NODE,
                                         purpose_text="kept purpose", notes="old"))
    _post(client, node_notes_url(VIEW, NODE), {"signoff_status": "draft", "notes": "new"})
    saved = _annotation(db, NODE)
    assert (saved.purpose_text, saved.notes) == ("kept purpose", "new")


def test_node_note_invalid_is_400_panel(client, db):
    response = _post(client, node_notes_url(VIEW, NODE),
                     {"signoff_status": "nope", "notes": "typed text"})
    assert response.status_code == 400
    assert 'class="node-panel"' in response.text and "not a sign-off status" in response.text
    assert "typed text</textarea>" in response.text
    response = _post(client, node_notes_url(VIEW, NODE),
                     {"signoff_status": "draft", "notes": "y" * 20_001})
    assert response.status_code == 400
    assert _annotation(db, NODE) is None


def test_node_note_unknown_node_is_visible_fragment(client, db):
    response = _post(client, node_notes_url(VIEW, f"{VIEW}/Nope"), {"notes": "x"})
    assert response.status_code == 200 and "There is no step" in response.text
    assert _annotation(db, f"{VIEW}/Nope") is None
    response = _post(client, node_notes_url("NO_SUCH_VIEW", NODE), {"notes": "x"})
    assert response.status_code == 200 and "There is no step" in response.text


def test_node_note_stale_badge_and_orphan(client, db, folder):
    other = f"{VIEW}/Join_1"
    _post(client, node_notes_url(VIEW, NODE), {"signoff_status": "draft", "notes": "Orphan note"})
    _rename_node(folder, "Projection_1", "Projection_9")
    _reimport(db, folder)
    assert _annotation(db, NODE).stale_reason == "node removed"

    tab = _notes_tab(client)
    assert "Notes on steps that no longer exist" in tab
    section = tab[tab.index("Notes on steps that no longer exist"):]
    assert "Projection_1" in section and "Orphan note" in section
    assert "Stale: node removed" in section
    # the other view's tab does not claim it
    assert "Orphan note" not in _notes_tab(client, PRODUCER)
    # an intact node of the view is not an orphan
    assert other not in section


def test_node_panel_shows_stale_badge(client, db, folder):
    with Store(db) as store:
        store.save_annotation(Annotation(target_id=NODE, target_kind=TargetKind.NODE, notes="n"))
        store.mark_stale([NODE], "node changed", TargetKind.NODE)
    html = client.get(f"/node?view={VIEW}&node={NODE}").text
    assert "Stale: node changed" in html
    response = _post(client, node_notes_url(VIEW, NODE), {"signoff_status": "draft", "notes": "n"})
    assert "Stale:" not in response.text and not _annotation(db, NODE).stale


def test_hostile_node_note_is_escaped(client):
    hostile = '</textarea><script>alert(1)</script>'
    response = _post(client, node_notes_url(VIEW, NODE),
                     {"signoff_status": "draft", "notes": hostile, "owner": hostile})
    assert "<script>alert(1)" not in response.text
    assert "<script>alert(1)" not in _notes_tab(client)


def _slashed_folder(tmp_path, ids):
    """One copy of the producer fixture per view id (ids may contain '/')."""
    xml = (FIXTURES / "graphical" / f"{PRODUCER}.calculationview").read_text(encoding="utf-8")
    folder = tmp_path / "slashed"
    folder.mkdir()
    for i, view_id in enumerate(ids):
        (folder / f"V{i}.calculationview").write_text(
            xml.replace(f'id="{PRODUCER}"', f'id="{view_id}"', 1), encoding="utf-8")
    return folder


def test_step_notes_of_a_removed_view_show_on_the_views_list(client, db, folder):
    _post(client, node_notes_url(PRODUCER, f"{PRODUCER}/Projection_1"),
          {"signoff_status": "draft", "notes": "note on a gone view step"})
    (folder / f"{PRODUCER}.calculationview").unlink()
    _reimport(db, folder)
    html = client.get("/views").text
    section = html[html.index("Notes on views that no longer exist"):]
    assert f"{PRODUCER}/Projection_1" in section and "note on a gone view step" in section
    assert "Stale: view removed" in section
    assert "note on a gone view step" not in _notes_tab(client, VIEW)


def test_removed_view_with_slash_does_not_lend_its_step_notes_to_a_shorter_view(tmp_path):
    folder = _slashed_folder(tmp_path, ["A", "A/B"])
    db = tmp_path / "s.db"
    _reimport(db, folder)
    client = local_client(create_app(db))
    _post(client, node_notes_url("A/B", "A/B/Projection_1"),
          {"signoff_status": "draft", "notes": "step of A/B"})
    (folder / "V1.calculationview").unlink()  # view A/B is gone; A remains
    _reimport(db, folder)
    assert _annotation(db, "A/B/Projection_1").stale_reason == "view removed"
    assert "step of A/B" not in _notes_tab(client, "A")
    html = client.get("/views").text
    assert "step of A/B" in html[html.index("Notes on views that no longer exist"):]


def test_view_and_node_with_the_same_id_keep_separate_notes(tmp_path):
    # view "A/Projection_1" and step "Projection_1" of view "A" share the id A/Projection_1
    folder = _slashed_folder(tmp_path, ["A", "A/Projection_1"])
    db = tmp_path / "s.db"
    _reimport(db, folder)
    client = local_client(create_app(db))
    same = "A/Projection_1"
    assert _post(client, notes_url(same), {**FULL, "notes": "view note"}).status_code == 303
    assert _post(client, node_notes_url("A", same),
                 {"signoff_status": "approved", "notes": "step note"}).status_code == 200
    assert _annotation(db, same, TargetKind.VIEW).notes == "view note"
    assert _annotation(db, same, TargetKind.NODE).notes == "step note"
    assert "view note</textarea>" in _notes_tab(client, same)
    assert "step note</textarea>" in client.get("/node", params={"view": "A", "node": same}).text
    with Store(db) as store:
        assert store.mark_stale([same], "node changed", TargetKind.NODE) == 1
    assert _annotation(db, same, TargetKind.NODE).stale
    assert not _annotation(db, same, TargetKind.VIEW).stale
    assert "Stale:" not in _notes_tab(client, same).split("Notes on steps")[0]


def test_orphaned_notes_classification():
    def note(target_id, kind=TargetKind.NODE, reason=None):
        return Annotation(target_id=target_id, target_kind=kind, stale=reason is not None,
                          stale_reason=reason)
    notes = [note("A/STEP_1"), note("A/GONE", reason="node removed"),
             note("A/B/GONE", reason="node removed"), note("AB/GONE"),
             note("A/C/X", reason="view removed"), note("Z/X", reason="view removed"),
             note("Z", TargetKind.VIEW, "view removed"), note("A", TargetKind.VIEW)]
    by_view, removed = orphaned_notes(notes, {"A", "A/B", "AB"}, {"A/STEP_1"})
    assert {k: [n.target_id for n in v] for k, v in by_view.items()} == {
        "A": ["A/GONE"], "A/B": ["A/B/GONE"], "AB": ["AB/GONE"]}
    assert [(n.target_kind, n.target_id) for n in removed] == [
        ("node", "A/C/X"), ("node", "Z/X"), ("view", "Z")]
