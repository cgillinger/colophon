# Colophon – tests for authority anchoring + the AI adjudicator (step 5)
"""All network calls mocked, per the tests/ convention."""
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from app.models import db, Author, BookAuthor, LibraryItem
from app.routes.authors import authors_bp
from app.services.author_authority_lookup import (
    lookup_author_authority,
    _search_ids,
    _get_entities,
)


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
        "P106": [{"mainsnak": {"datavalue": {"value": {"id": "Q36180"}}}}],
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


def test_lookup_rejects_human_with_no_occupation_claim():
    # Name matches, human — but no P106 at all. No guessing.
    entities = {"entities": {"Q892": {
        **_ENTITIES["entities"]["Q892"],
        "claims": {k: v for k, v in _ENTITIES["entities"]["Q892"]["claims"].items()
                   if k != "P106"},
    }}}
    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(_SEARCH), _resp(entities)]):
        result = lookup_author_authority("J.R.R. Tolkien")
    assert result["matched"] is False


def test_lookup_rejects_snooker_player_with_matching_name():
    # The real case this guard exists for: "Dennis Taylor" the snooker
    # player (Q13382566) is human and can share a name, but does not write.
    entities = {"entities": {"Q892": {
        **_ENTITIES["entities"]["Q892"],
        "claims": {**_ENTITIES["entities"]["Q892"]["claims"],
                   "P106": [{"mainsnak": {"datavalue": {"value": {"id": "Q13382566"}}}}]},
    }}}
    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(_SEARCH), _resp(entities)]):
        result = lookup_author_authority("J.R.R. Tolkien")
    assert result["matched"] is False


def test_lookup_skips_non_writer_and_returns_the_writer():
    # Search ranks a name-matching non-writer first (notability), a
    # name-matching writer second. The lookup must walk past the first.
    search = {"search": [{"id": "Q1"}, {"id": "Q2"}]}
    entities = {"entities": {
        "Q1": {
            **_ENTITIES["entities"]["Q892"],
            "claims": {**_ENTITIES["entities"]["Q892"]["claims"],
                       "P106": [{"mainsnak": {"datavalue": {"value": {"id": "Q13382566"}}}}]},
        },
        "Q2": _ENTITIES["entities"]["Q892"],
    }}
    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(search), _resp(entities)]):
        result = lookup_author_authority("J.R.R. Tolkien")
    assert result["matched"] is True
    assert result["qid"] == "Q2"


@pytest.mark.parametrize("occupation_qid", ["Q6625963", "Q201788"])  # novelist, historian
def test_lookup_accepts_other_writing_occupations(occupation_qid):
    entities = {"entities": {"Q892": {
        **_ENTITIES["entities"]["Q892"],
        "claims": {**_ENTITIES["entities"]["Q892"]["claims"],
                   "P106": [{"mainsnak": {"datavalue": {"value": {"id": occupation_qid}}}}]},
    }}}
    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(_SEARCH), _resp(entities)]):
        result = lookup_author_authority("J.R.R. Tolkien")
    assert result["matched"] is True
    assert result["qid"] == "Q892"


# --------------------------------------------------------------------------
# lookup_author_authority — title evidence (known_titles cross-check)
# --------------------------------------------------------------------------

_TITLE = "We Are Legion (We Are Bob)"


def _sparql_resp(qid, work_label):
    return _resp({"results": {"bindings": [
        {"person": {"value": f"http://www.wikidata.org/entity/{qid}"},
         "workLabel": {"value": work_label}},
    ]}})


def test_lookup_title_evidence_rescues_candidate_with_no_occupation():
    # Q1 shares the name but is not a writer at all (a namesake). Q2 shares
    # the name, has NO occupation claim whatsoever, but SPARQL credits it
    # with a title this library holds — that must win over Q1 even though
    # Q2 would fail the occupation test outright.
    search = {"search": [{"id": "Q1"}, {"id": "Q2"}]}
    entities = {"entities": {
        "Q1": {
            **_ENTITIES["entities"]["Q892"],
            "claims": {**_ENTITIES["entities"]["Q892"]["claims"],
                       "P106": [{"mainsnak": {"datavalue": {"value": {"id": "Q13382566"}}}}]},
        },
        "Q2": {
            **_ENTITIES["entities"]["Q892"],
            "claims": {k: v for k, v in _ENTITIES["entities"]["Q892"]["claims"].items()
                       if k != "P106"},
        },
    }}
    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(search), _resp(entities), _sparql_resp("Q2", _TITLE)]):
        result = lookup_author_authority("J.R.R. Tolkien", known_titles=[_TITLE])
    assert result["matched"] is True
    assert result["qid"] == "Q2"
    assert result["matched_on"] == "title"


def test_lookup_title_evidence_outranks_ranking_order():
    # Both candidates are writers; SPARQL credits only the second with a
    # held title. Without the cross-check, ranking order alone would pick
    # the first.
    search = {"search": [{"id": "Q1"}, {"id": "Q2"}]}
    entities = {"entities": {"Q1": _ENTITIES["entities"]["Q892"],
                             "Q2": _ENTITIES["entities"]["Q892"]}}
    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(search), _resp(entities), _sparql_resp("Q2", _TITLE)]):
        result = lookup_author_authority("J.R.R. Tolkien", known_titles=[_TITLE])
    assert result["matched"] is True
    assert result["qid"] == "Q2"
    assert result["matched_on"] == "title"


def test_lookup_title_comparison_is_normalized():
    search = {"search": [{"id": "Q1"}, {"id": "Q2"}]}
    entities = {"entities": {"Q1": _ENTITIES["entities"]["Q892"],
                             "Q2": _ENTITIES["entities"]["Q892"]}}
    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(search), _resp(entities),
                            _sparql_resp("Q2", "We Are Legion (We Are Bob)")]):
        result = lookup_author_authority("J.R.R. Tolkien", known_titles=["we are legion"])
    assert result["matched"] is True
    assert result["qid"] == "Q2"
    assert result["matched_on"] == "title"


def test_lookup_sparql_failure_falls_back_to_occupation():
    import requests as _requests
    search = {"search": [{"id": "Q1"}, {"id": "Q2"}]}
    entities = {"entities": {
        "Q1": {
            **_ENTITIES["entities"]["Q892"],
            "claims": {**_ENTITIES["entities"]["Q892"]["claims"],
                       "P106": [{"mainsnak": {"datavalue": {"value": {"id": "Q13382566"}}}}]},
        },
        "Q2": _ENTITIES["entities"]["Q892"],
    }}
    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(search), _resp(entities),
                            _requests.RequestException("boom")]):
        result = lookup_author_authority("J.R.R. Tolkien", known_titles=[_TITLE])
    assert result["ok"] is True
    assert result["matched"] is True
    assert result["qid"] == "Q2"
    assert result["matched_on"] == "occupation"


def test_lookup_no_sparql_call_with_single_candidate():
    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(_SEARCH), _resp(_ENTITIES)]) as mock_get:
        result = lookup_author_authority("J.R.R. Tolkien", known_titles=[_TITLE])
    assert result["matched"] is True
    assert result["matched_on"] == "occupation"
    assert mock_get.call_count == 2


def test_lookup_no_sparql_call_without_known_titles():
    search = {"search": [{"id": "Q1"}, {"id": "Q2"}]}
    entities = {"entities": {
        "Q1": {
            **_ENTITIES["entities"]["Q892"],
            "claims": {**_ENTITIES["entities"]["Q892"]["claims"],
                       "P106": [{"mainsnak": {"datavalue": {"value": {"id": "Q13382566"}}}}]},
        },
        "Q2": _ENTITIES["entities"]["Q892"],
    }}
    for known_titles in (None, []):
        with patch("app.services.author_authority_lookup.requests.get",
                   side_effect=[_resp(search), _resp(entities)]) as mock_get:
            result = lookup_author_authority("J.R.R. Tolkien", known_titles=known_titles)
        assert result["matched"] is True
        assert result["qid"] == "Q2"
        assert mock_get.call_count == 2


def test_lookup_title_evidence_requires_the_title_to_match():
    # SPARQL credits Q2 with a title we do NOT hold — a credit for an
    # unrelated book must not win on "title"; occupation decides instead.
    search = {"search": [{"id": "Q1"}, {"id": "Q2"}]}
    entities = {"entities": {"Q1": _ENTITIES["entities"]["Q892"],
                             "Q2": _ENTITIES["entities"]["Q892"]}}
    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(search), _resp(entities),
                            _sparql_resp("Q2", "Some Unrelated Book")]):
        result = lookup_author_authority("J.R.R. Tolkien", known_titles=[_TITLE])
    assert result["matched"] is True
    assert result["qid"] == "Q1"
    assert result["matched_on"] == "occupation"


# --------------------------------------------------------------------------
# lookup_author_authority — title→author fallback (_author_of_a_book_we_hold)
# --------------------------------------------------------------------------

def test_lookup_title_fallback_finds_the_novelist_wikidata_never_offered():
    # The real case this fallback exists for: searching "Dennis Taylor"
    # only ever surfaces a snooker player, a racing driver and a
    # footballer — the novelist is labelled "Dennis E. Taylor" and is
    # never a candidate at all. Searching a title the library holds
    # finds the book in one step, and the book says who wrote it (P50).
    name_search = {"search": [{"id": "Q1"}]}
    snooker_player = {
        "labels": {"en": {"value": "Dennis Taylor"}},
        "descriptions": {"en": {"value": "British snooker player"}},
        "aliases": {},
        "claims": {
            "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}],
            "P106": [{"mainsnak": {"datavalue": {"value": {"id": "Q13382566"}}}}],
        },
    }
    name_entities = {"entities": {"Q1": snooker_player}}
    title_search = {"search": [{"id": "Q100"}]}
    work_entities = {"entities": {"Q100": {
        "claims": {"P50": [{"mainsnak": {"datavalue": {"value": {"id": "Q41694161"}}}}]},
    }}}
    novelist = {
        "labels": {"en": {"value": "Dennis E. Taylor"}},
        "descriptions": {"en": {"value": "Canadian novelist"}},
        "aliases": {},
        "claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}]},
        # Deliberately no P106 at all.
    }
    person_entities = {"entities": {"Q41694161": novelist}}

    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(name_search), _resp(name_entities),
                            _resp(title_search), _resp(work_entities),
                            _resp(person_entities)]):
        result = lookup_author_authority("Dennis Taylor", known_titles=[_TITLE])

    assert result["matched"] is True
    assert result["qid"] == "Q41694161"
    assert result["matched_on"] == "title"
    assert result["label"] == "Dennis E. Taylor"
    assert result["description"] == "Canadian novelist"


def test_lookup_title_fallback_runs_when_the_name_search_finds_nothing():
    # The strongest case for the fallback, and the one an early
    # `if not people: return` used to make unreachable: Wikidata has
    # never heard of the name as written, but it knows the book.
    empty = {"search": []}
    title_search = {"search": [{"id": "Q100"}]}
    work_entities = {"entities": {"Q100": {
        "claims": {"P50": [{"mainsnak": {"datavalue": {"value": {"id": "Q41694161"}}}}]},
    }}}
    person_entities = {"entities": {"Q41694161": {
        "labels": {"en": {"value": "Dennis E. Taylor"}},
        "descriptions": {"en": {"value": "Canadian novelist"}},
        "aliases": {},
        "claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}]},
    }}}

    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(empty), _resp(empty), _resp(title_search),
                            _resp(work_entities), _resp(person_entities)]):
        result = lookup_author_authority("Dennis Taylor", known_titles=[_TITLE])

    assert result["matched"] is True
    assert result["qid"] == "Q41694161"
    assert result["matched_on"] == "title"


def test_lookup_title_fallback_runs_when_no_candidate_matches_the_name():
    # The search returned someone, but nobody whose name could be ours.
    # That is still "the name search found nobody" and the books should
    # get their turn.
    name_search = {"search": [{"id": "Q1"}]}
    stranger = {
        "labels": {"en": {"value": "Someone Else Entirely"}},
        "descriptions": {"en": {"value": "unrelated person"}},
        "aliases": {},
        "claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}]},
    }
    title_search = {"search": [{"id": "Q100"}]}
    work_entities = {"entities": {"Q100": {
        "claims": {"P50": [{"mainsnak": {"datavalue": {"value": {"id": "Q41694161"}}}}]},
    }}}
    person_entities = {"entities": {"Q41694161": {
        "labels": {"en": {"value": "Dennis E. Taylor"}},
        "descriptions": {"en": {"value": "Canadian novelist"}},
        "aliases": {},
        "claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}]},
    }}}

    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(name_search), _resp({"entities": {"Q1": stranger}}),
                            _resp(title_search), _resp(work_entities),
                            _resp(person_entities)]):
        result = lookup_author_authority("Dennis Taylor", known_titles=[_TITLE])

    assert result["matched"] is True
    assert result["qid"] == "Q41694161"


def test_lookup_title_fallback_rejects_name_mismatch():
    name_search = {"search": [{"id": "Q1"}]}
    name_entities = {"entities": {"Q1": {
        "labels": {"en": {"value": "Dennis Taylor"}},
        "aliases": {},
        "claims": {
            "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}],
            "P106": [{"mainsnak": {"datavalue": {"value": {"id": "Q13382566"}}}}],
        },
    }}}
    title_search = {"search": [{"id": "Q100"}]}
    work_entities = {"entities": {"Q100": {
        "claims": {"P50": [{"mainsnak": {"datavalue": {"value": {"id": "Q999"}}}}]},
    }}}
    mismatched = {
        "labels": {"en": {"value": "Someone Else Entirely"}},
        "aliases": {},
        "claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}]},
    }
    person_entities = {"entities": {"Q999": mismatched}}

    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(name_search), _resp(name_entities),
                            _resp(title_search), _resp(work_entities),
                            _resp(person_entities)]):
        result = lookup_author_authority("Dennis Taylor", known_titles=[_TITLE])

    assert result["matched"] is False
    assert result["ok"] is True


def test_lookup_title_fallback_rejects_non_human_p50():
    name_search = {"search": [{"id": "Q1"}]}
    name_entities = {"entities": {"Q1": {
        "labels": {"en": {"value": "Dennis Taylor"}},
        "aliases": {},
        "claims": {
            "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}],
            "P106": [{"mainsnak": {"datavalue": {"value": {"id": "Q13382566"}}}}],
        },
    }}}
    title_search = {"search": [{"id": "Q100"}]}
    work_entities = {"entities": {"Q100": {
        "claims": {"P50": [{"mainsnak": {"datavalue": {"value": {"id": "Q999"}}}}]},
    }}}
    not_human = {
        "labels": {"en": {"value": "Dennis Taylor"}},
        "aliases": {},
        "claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q571"}}}}]},
    }
    person_entities = {"entities": {"Q999": not_human}}

    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(name_search), _resp(name_entities),
                            _resp(title_search), _resp(work_entities),
                            _resp(person_entities)]):
        result = lookup_author_authority("Dennis Taylor", known_titles=[_TITLE])

    assert result["matched"] is False


def test_lookup_title_fallback_not_reached_when_occupation_matches():
    # The name path already chose a writer — the fallback must not fire
    # (and must cost no extra requests) once someone was accepted.
    name_search = {"search": [{"id": "Q1"}]}
    writer = {
        "labels": {"en": {"value": "Dennis Taylor"}},
        "aliases": {},
        "claims": {
            "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}],
            "P106": [{"mainsnak": {"datavalue": {"value": {"id": "Q36180"}}}}],
        },
    }
    name_entities = {"entities": {"Q1": writer}}

    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(name_search), _resp(name_entities)]) as mock_get:
        result = lookup_author_authority("Dennis Taylor", known_titles=[_TITLE])

    assert result["matched"] is True
    assert result["matched_on"] == "occupation"
    assert mock_get.call_count == 2


def test_lookup_title_fallback_skipped_without_known_titles():
    # Nobody acceptable on the name path, but with no known_titles there
    # is nothing to fall back on — must not spend any extra requests.
    name_search = {"search": [{"id": "Q1"}]}
    snooker_player = {
        "labels": {"en": {"value": "Dennis Taylor"}},
        "aliases": {},
        "claims": {
            "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}],
            "P106": [{"mainsnak": {"datavalue": {"value": {"id": "Q13382566"}}}}],
        },
    }
    name_entities = {"entities": {"Q1": snooker_player}}

    for known_titles in (None, []):
        with patch("app.services.author_authority_lookup.requests.get",
                   side_effect=[_resp(name_search), _resp(name_entities)]) as mock_get:
            result = lookup_author_authority("Dennis Taylor", known_titles=known_titles)
        assert result["matched"] is False
        assert mock_get.call_count == 2


def test_lookup_title_fallback_failure_is_harmless():
    import requests as _requests
    name_search = {"search": [{"id": "Q1"}]}
    snooker_player = {
        "labels": {"en": {"value": "Dennis Taylor"}},
        "aliases": {},
        "claims": {
            "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}],
            "P106": [{"mainsnak": {"datavalue": {"value": {"id": "Q13382566"}}}}],
        },
    }
    name_entities = {"entities": {"Q1": snooker_player}}

    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(name_search), _resp(name_entities),
                            _requests.RequestException("boom")]):
        result = lookup_author_authority("Dennis Taylor", known_titles=[_TITLE])

    assert result["ok"] is True
    assert result["matched"] is False


def test_lookup_title_fallback_stops_at_first_title_with_hits():
    # Up to three known titles are tried; the walk must stop at the
    # first that returns any work ids, so the third is never searched.
    name_search = {"search": [{"id": "Q1"}]}
    snooker_player = {
        "labels": {"en": {"value": "Dennis Taylor"}},
        "aliases": {},
        "claims": {
            "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}],
            "P106": [{"mainsnak": {"datavalue": {"value": {"id": "Q13382566"}}}}],
        },
    }
    name_entities = {"entities": {"Q1": snooker_player}}
    empty_title_search = {"search": []}
    title_search = {"search": [{"id": "Q100"}]}
    work_entities = {"entities": {"Q100": {
        "claims": {"P50": [{"mainsnak": {"datavalue": {"value": {"id": "Q41694161"}}}}]},
    }}}
    novelist = {
        "labels": {"en": {"value": "Dennis E. Taylor"}},
        "aliases": {},
        "claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}]},
    }
    person_entities = {"entities": {"Q41694161": novelist}}

    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=[_resp(name_search), _resp(name_entities),
                            _resp(empty_title_search), _resp(title_search),
                            _resp(work_entities), _resp(person_entities)]) as mock_get:
        result = lookup_author_authority("Dennis Taylor", known_titles=["A", "B", "C"])

    assert result["matched"] is True
    assert result["matched_on"] == "title"
    assert mock_get.call_count == 6


def test_search_ids_returns_empty_on_network_error():
    import requests as _requests
    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=_requests.RequestException("boom")):
        assert _search_ids("some title") == []


def test_search_ids_returns_empty_on_bad_json():
    bad = _resp({})
    bad.json.side_effect = ValueError("bad json")
    with patch("app.services.author_authority_lookup.requests.get", return_value=bad):
        assert _search_ids("some title") == []


def test_get_entities_returns_empty_on_network_error():
    import requests as _requests
    with patch("app.services.author_authority_lookup.requests.get",
               side_effect=_requests.RequestException("boom")):
        assert _get_entities(["Q1"]) == {}


def test_get_entities_returns_empty_on_bad_json():
    bad = _resp({})
    bad.json.side_effect = ValueError("bad json")
    with patch("app.services.author_authority_lookup.requests.get", return_value=bad):
        assert _get_entities(["Q1"]) == {}


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


def test_verify_passes_known_titles_from_linked_books(client):
    # Two books linked to the author via BookAuthor — _author_titles must
    # collect both and hand them to the lookup as known_titles.
    author = Author(canonical_name="J.R.R. Tolkien", source="tentative")
    db.session.add(author)
    db.session.commit()

    item_a = LibraryItem(title="The Hobbit", file_path="/books/hobbit.epub",
                          file_name="hobbit.epub", extension=".epub")
    item_b = LibraryItem(title="The Silmarillion", file_path="/books/silm.epub",
                          file_name="silm.epub", extension=".epub")
    db.session.add_all([item_a, item_b])
    db.session.flush()
    db.session.add_all([
        BookAuthor(item_id=item_a.id, author_id=author.id, position=0),
        BookAuthor(item_id=item_b.id, author_id=author.id, position=0),
    ])
    db.session.commit()

    mock_lookup = MagicMock(return_value={
        "ok": True, "matched": True, "qid": "Q892", "viaf_id": "95218067",
        "libris_id": "97mqwzhd43lwn0c", "label": "J. R. R. Tolkien",
        "description": "English author (1892-1973)", "matched_on": "title",
    })
    # NOTE: verify() imports lookup_author_authority locally, inside the
    # view function ("from app.services.author_authority_lookup import
    # lookup_author_authority"), so app.routes.authors has no such
    # module-level attribute to patch — patching it raises AttributeError.
    # The call the view actually makes is served by the source module.
    with patch("app.services.author_authority_lookup.lookup_author_authority",
               mock_lookup):
        body = client.post(f"/authors/{author.id}/verify").get_json()

    assert body["ok"] is True and body["matched"] is True
    mock_lookup.assert_called_once()
    _, kwargs = mock_lookup.call_args
    assert set(kwargs["known_titles"]) == {"The Hobbit", "The Silmarillion"}


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


# --------------------------------------------------------------------------
# Routes: /unlink
# --------------------------------------------------------------------------

def test_unlink_clears_ids_and_demotes_to_user_confirmed(client):
    author = Author(
        canonical_name="J.R.R. Tolkien",
        source="authority_linked",
        wikidata_qid="Q892",
        viaf_id="95218067",
        libris_id="97mqwzhd43lwn0c",
        authority_label="J. R. R. Tolkien",
        authority_description="English author (1892–1973)",
    )
    db.session.add(author)
    db.session.commit()

    body = client.post(f"/authors/{author.id}/unlink").get_json()

    assert body["ok"] is True
    assert author.wikidata_qid is None
    assert author.viaf_id is None
    assert author.libris_id is None
    assert author.authority_label is None
    assert author.authority_description is None
    assert author.source == "user_confirmed"
    # The canonical NAME is untouched — unlinking drops ids only.
    assert author.canonical_name == "J.R.R. Tolkien"


def test_unlink_response_reflects_cleared_state(client):
    author = Author(
        canonical_name="Astrid Lindgren",
        source="authority_linked",
        wikidata_qid="Q160306",
        viaf_id="12345",
        libris_id="abc123",
        authority_label="Astrid Lindgren",
        authority_description="Swedish writer",
    )
    db.session.add(author)
    db.session.commit()

    body = client.post(f"/authors/{author.id}/unlink").get_json()

    assert body == {"ok": True, "author": {
        "id": author.id,
        "name": "Astrid Lindgren",
        "source": "user_confirmed",
        "wikidata_qid": None,
        "libris_id": None,
        "viaf_id": None,
        "authority_label": None,
        "authority_description": None,
    }}


def test_unlink_unknown_id_is_404(client):
    resp = client.post("/authors/999999/unlink")
    assert resp.status_code == 404


def test_unlink_author_with_no_ids_is_harmless(client):
    author = Author(canonical_name="Ny Författare", source="tentative")
    db.session.add(author)
    db.session.commit()

    resp = client.post(f"/authors/{author.id}/unlink")

    assert resp.status_code == 200
    assert author.source == "user_confirmed"
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
