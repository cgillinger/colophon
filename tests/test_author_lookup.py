# Colophon – tests for authority anchoring + the AI adjudicator (step 5)
"""All network calls mocked, per the tests/ convention."""
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from app.models import db, Author
from app.routes.authors import authors_bp
from app.services.author_authority_lookup import lookup_author_authority


def _resp(payload, ok=True, status=200):
    r = MagicMock()
    r.ok = ok
    r.status_code = status
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


_SEARCH = {"search": [{"id": "Q892"}]}

_ENTITIES = {"entities": {"Q892": {
    "labels": {"en": {"value": "J. R. R. Tolkien"}},
    "descriptions": {"en": {"value": "English author (1892–1973)"}},
    "aliases": {"en": [{"value": "John Ronald Reuel Tolkien"}]},
    "claims": {
        "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}],
        "P214": [{"mainsnak": {"datavalue": {"value": "95218067"}}}],
        "P5587": [{"mainsnak": {"datavalue": {"value": "97mqwzhd43lwn0c"}}}],
    },
}}}


# --------------------------------------------------------------------------
# lookup_author_authority
# --------------------------------------------------------------------------

def test_lookup_matches_human_with_matching_name():
    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(_SEARCH), _resp(_ENTITIES)]):
        result = lookup_author_authority("J.R.R. Tolkien")
    assert result["matched"] is True
    assert result["qid"] == "Q892"
    assert result["viaf_id"] == "95218067"
    assert result["libris_id"] == "97mqwzhd43lwn0c"


def test_lookup_rejects_non_human():
    entities = {"entities": {"Q892": {
        **_ENTITIES["entities"]["Q892"],
        "claims": {**_ENTITIES["entities"]["Q892"]["claims"],
                   "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q571"}}}}]},
    }}}
    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(_SEARCH), _resp(entities)]):
        result = lookup_author_authority("J.R.R. Tolkien")
    assert result["matched"] is False


def test_lookup_rejects_name_mismatch():
    # A human, but the label is someone else entirely — no guessing.
    entities = {"entities": {"Q892": {
        **_ENTITIES["entities"]["Q892"],
        "labels": {"en": {"value": "Astrid Lindgren"}},
        "aliases": {},
    }}}
    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(_SEARCH), _resp(entities)]):
        result = lookup_author_authority("J.R.R. Tolkien")
    assert result["matched"] is False


def test_lookup_network_error_is_ok_false():
    import requests as _requests
    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=_requests.ConnectionError("boom")):
        result = lookup_author_authority("J.R.R. Tolkien")
    assert result["ok"] is False
    assert result["matched"] is False


def test_lookup_no_search_hits_is_clean_miss():
    with patch("app.services.author_authority_lookup.requests.get",
               return_value=_resp({"search": []})):
        result = lookup_author_authority("Helt Okänd Person")
    assert result["ok"] is True
    assert result["matched"] is False


# --------------------------------------------------------------------------
# Routes: /verify + /adjudicate
# --------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    app = Flask(__name__, template_folder=None)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + str(tmp_path / "t.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    app.register_blueprint(authors_bp)
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def test_verify_stores_ids_and_promotes(client):
    author = Author(canonical_name="J.R.R. Tolkien", source="tentative")
    db.session.add(author)
    db.session.commit()

    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(_SEARCH), _resp(_ENTITIES)]):
        body = client.post(f"/authors/{author.id}/verify").get_json()

    assert body["ok"] is True and body["matched"] is True
    assert author.wikidata_qid == "Q892"
    assert author.viaf_id == "95218067"
    assert author.source == "authority_linked"
    # The canonical NAME is untouched — anchoring adds ids only.
    assert author.canonical_name == "J.R.R. Tolkien"


def test_verify_miss_changes_nothing(client):
    author = Author(canonical_name="Helt Okänd", source="tentative")
    db.session.add(author)
    db.session.commit()

    with patch("app.services.author_authority_lookup.requests.get",
               return_value=_resp({"search": []})):
        body = client.post(f"/authors/{author.id}/verify").get_json()

    assert body["ok"] is True and body["matched"] is False
    assert author.source == "tentative"
    assert author.wikidata_qid is None


def test_adjudicate_returns_verdict(client):
    a = Author(canonical_name="Michael Connelly", source="user_confirmed")
    b = Author(canonical_name="Michael Connolly", source="user_confirmed")
    db.session.add_all([a, b])
    db.session.commit()

    ai_response = _resp({
        "choices": [{"message": {"content":
            '{"verdict": "different", "reason": "Two distinct crime writers."}'}}],
        "usage": {},
    })
    with patch("app.services.ai_metadata.ai_is_configured", return_value=True), \
         patch("app.services.ai_metadata.requests.post", return_value=ai_response):
        body = client.post("/authors/adjudicate",
                           json={"a_id": a.id, "b_id": b.id}).get_json()

    assert body["ok"] is True
    assert body["verdict"] == "different"
    assert "distinct" in body["reason"]


def test_adjudicate_requires_ai_config(client):
    a = Author(canonical_name="A A", source="user_confirmed")
    b = Author(canonical_name="B B", source="user_confirmed")
    db.session.add_all([a, b])
    db.session.commit()

    with patch("app.services.ai_metadata.ai_is_configured", return_value=False):
        resp = client.post("/authors/adjudicate", json={"a_id": a.id, "b_id": b.id})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "not_configured"
