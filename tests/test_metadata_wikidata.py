# Colophon – e-book metadata manager
"""Tests for the Wikidata metadata source. No network."""
import app.services.metadata_wikidata as wd
from app.services.metadata_wikidata import _aggregate, _best_work, _qid


def _b(**kw):
    """Build a SPARQL binding row from key=value pairs."""
    return {k: {"value": v} for k, v in kw.items()}


# Two QIDs: a film (wrong type) and the novel, both titled the same.
_BINDINGS = [
    _b(work="http://www.wikidata.org/entity/Q111", workLabel="A Fire Upon the Deep",
       type="http://www.wikidata.org/entity/Q11424"),  # film
    _b(work="http://www.wikidata.org/entity/Q222", workLabel="A Fire Upon the Deep",
       type="http://www.wikidata.org/entity/Q7725634",  # literary work
       seriesLabel="Zones of Thought", ordinal="1",
       genreLabel="science fiction", date="1992-01-01T00:00:00Z",
       authorLabel="Vernor Vinge", image="https://commons/FilePath/fire.jpg"),
    _b(work="http://www.wikidata.org/entity/Q222", workLabel="A Fire Upon the Deep",
       type="http://www.wikidata.org/entity/Q7725634", genreLabel="space opera"),
]


def test_qid_extracts_id():
    assert _qid("http://www.wikidata.org/entity/Q42") == "Q42"
    assert _qid("") == ""


def test_aggregate_collapses_rows_per_work():
    works = {w["qid"]: w for w in _aggregate(_BINDINGS)}
    assert set(works) == {"Q111", "Q222"}
    novel = works["Q222"]
    assert novel["series"] == "Zones of Thought"
    assert novel["series_index"] == "1"
    assert novel["genres"] == ["science fiction", "space opera"]  # unioned
    assert novel["date"] == "1992-01-01"
    assert novel["authors"] == ["Vernor Vinge"]
    assert novel["image"].endswith("fire.jpg")


def test_best_work_picks_book_type_not_film():
    work = _best_work(_aggregate(_BINDINGS), "A Fire Upon the Deep", "Vernor Vinge")
    assert work["qid"] == "Q222"  # the literary work, not the film Q111


def test_best_work_none_when_no_book_type():
    films_only = [_b(work="http://www.wikidata.org/entity/Q111", workLabel="X",
                     type="http://www.wikidata.org/entity/Q11424")]
    assert _best_work(_aggregate(films_only), "X", "Y") is None


def test_search_with_status_builds_candidate(monkeypatch):
    monkeypatch.setattr(wd, "_search_entities", lambda title: ["Q111", "Q222"])
    monkeypatch.setattr(wd, "_sparql_for_qids", lambda qids: _BINDINGS)
    sr = wd.wikidata_search_with_status(title="A Fire Upon the Deep", author="Vernor Vinge")
    assert sr["ok"] is True
    assert sr["source"] == "wikidata"
    c = sr["candidates"][0]
    assert c["series"] == "Zones of Thought"
    assert c["series_index"] == "1"
    assert "science fiction" in c["genres"]
    assert "series_index" in c["fields_found"]


def test_search_with_status_no_title():
    sr = wd.wikidata_search_with_status(title="")
    assert sr["ok"] is False
    assert sr["status"] == "no_result"


def test_search_with_status_no_entities(monkeypatch):
    monkeypatch.setattr(wd, "_search_entities", lambda title: [])
    sr = wd.wikidata_search_with_status(title="Nonexistent Book")
    assert sr["status"] == "no_result"
