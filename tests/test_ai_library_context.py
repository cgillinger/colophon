# Colophon – tests for AI library context (v1.51.0)
"""The AI prompt carries three extracts of what the library already knows:
the same author's other books, the series vocabulary and the subject
vocabulary. A suggested series that matches an existing one is snapped to
the library spelling and promoted to "high" so bulk runs converge.
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from app.models import LibraryItem, db
from app.services import ai_metadata
from app.services.ai_metadata import (
    build_library_context,
    fetch_ai_suggestions,
    format_library_context,
)


@pytest.fixture
def session(tmp_path):
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + str(tmp_path / "test.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield db.session


def _book(session, title, author, author_id=None, series=None, index=None,
          genres=None, group_key=None, ext="epub"):
    item = LibraryItem(
        title=title, author=author, author_id=author_id, series=series,
        series_index=index, genres=genres, group_key=group_key or title.lower(),
        file_path=f"/books/{title}.{ext}", file_name=f"{title}.{ext}",
        extension=ext,
    )
    session.add(item)
    session.commit()
    return item


def test_author_books_exclude_self_and_format_siblings(session):
    target = _book(session, "Caliban's War", "James S. A. Corey", author_id=1)
    _book(session, "Caliban's War", "James S. A. Corey", author_id=1,
          group_key="caliban's war", ext="mobi")  # same book, other format
    _book(session, "Leviathan Wakes", "James S. A. Corey", author_id=1,
          series="The Expanse", index="1", genres="science fiction, space opera")
    _book(session, "Abaddon's Gate", "James S. A. Corey", author_id=1,
          series="The Expanse", index="3")
    _book(session, "Abaddon's Gate", "James S. A. Corey", author_id=1,
          group_key="abaddon's gate", ext="azw3")  # duplicate format group
    _book(session, "Guards! Guards!", "Terry Pratchett", author_id=2,
          series="Discworld", index="8", genres="fantasy, humour")

    ctx = build_library_context(target)

    titles = [b["title"] for b in ctx["author_books"]]
    assert titles == ["Leviathan Wakes", "Abaddon's Gate"]
    assert ctx["author_books"][0]["series"] == "The Expanse"
    assert ctx["author_books"][0]["series_index"] == "1"
    assert ctx["author_books"][0]["subjects"] == "science fiction, space opera"


def test_series_vocabulary_lists_own_author_first(session):
    target = _book(session, "New Book", "Stieg Larsson")
    _book(session, "Colour of Magic", "Terry Pratchett", series="Discworld")
    _book(session, "Mort", "Terry Pratchett", series="Discworld")
    _book(session, "Män som hatar kvinnor", "Stieg Larsson", series="Millennium")
    _book(session, "Dune", "Frank Herbert", series="Dune")

    ctx = build_library_context(target)

    names = [s["name"] for s in ctx["series"]]
    assert names[0] == "Millennium"          # own author first
    assert names[1] == "Discworld"           # then by frequency
    assert set(names) == {"Millennium", "Discworld", "Dune"}
    assert ctx["series"][0]["author"] == "Stieg Larsson"


def test_subjects_are_deduped_and_frequency_ordered(session):
    target = _book(session, "X", "Someone")
    _book(session, "A", "P", genres="Fantasy, humour")
    _book(session, "B", "Q", genres="fantasy , Science Fiction")
    _book(session, "C", "R", genres="fantasy")

    ctx = build_library_context(target)

    assert ctx["subjects"][0] == "Fantasy"                # first-seen spelling
    assert [s.casefold() for s in ctx["subjects"]].count("fantasy") == 1
    assert set(ctx["subjects"]) == {"Fantasy", "humour", "Science Fiction"}


def test_author_fallback_by_name_when_unlinked(session):
    target = _book(session, "X", "Ann Author")
    _book(session, "Y", "ann author", series="S")
    _book(session, "Z", "Other", series="T")

    ctx = build_library_context(target)
    assert [b["title"] for b in ctx["author_books"]] == ["Y"]


def test_context_without_author_or_data_is_empty(session):
    target = _book(session, "Lonely", "")
    ctx = build_library_context(target)
    assert ctx == {"author_books": [], "series": [], "subjects": []}
    assert format_library_context(ctx) == ""


def test_format_renders_all_three_blocks_and_rules():
    text = format_library_context({
        "author_books": [{"title": "T1", "series": "S", "series_index": "2",
                          "subjects": "a, b"}],
        "series": [{"name": "S", "author": "A"}],
        "subjects": ["a", "b"],
    })
    assert "Other books by this author already in the library:" in text
    assert "- T1  (series: S, #2)  [subjects: a, b]" in text
    assert "Series names already used in this library" in text
    assert "- S — A" in text
    assert "Subjects already used in this library:\na, b" in text
    assert "Library alignment rules" in text


def _ai_response(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.ok = True
    resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "usage": {},
    }
    return resp


def test_prompt_carries_context_and_series_snaps_to_library(session):
    target = _book(session, "Caliban's War", "James S. A. Corey", author_id=1)
    _book(session, "Leviathan Wakes", "James S. A. Corey", author_id=1,
          series="The Expanse", index="1")

    answer = {"series": {"value": "the  expanse", "confidence": "medium",
                         "reason": "general knowledge"}}
    with patch.object(ai_metadata, "get_setting", return_value="x"), \
         patch.object(ai_metadata.requests, "post",
                      return_value=_ai_response(answer)) as post:
        result = fetch_ai_suggestions(target)

    prompt = post.call_args.kwargs["json"]["messages"][0]["content"]
    assert "Leviathan Wakes  (series: The Expanse, #1)" in prompt
    assert "- The Expanse — James S. A. Corey" in prompt
    assert "Library alignment rules" in prompt

    assert result["ok"]
    assert result["suggestions"]["series"] == {
        "value": "The Expanse", "confidence": "high", "reason": "general knowledge",
    }


def test_unknown_series_keeps_model_confidence(session):
    target = _book(session, "Solo", "Nobody")
    answer = {"series": {"value": "Brand New", "confidence": "medium", "reason": "r"}}
    with patch.object(ai_metadata, "get_setting", return_value="x"), \
         patch.object(ai_metadata.requests, "post", return_value=_ai_response(answer)):
        result = fetch_ai_suggestions(target)
    assert result["suggestions"]["series"]["confidence"] == "medium"
    assert result["suggestions"]["series"]["value"] == "Brand New"


def test_context_failure_does_not_block_suggestions(session):
    target = _book(session, "Solo", "Nobody")
    answer = {"title": {"value": "Solo", "confidence": "high", "reason": "r"}}
    with patch.object(ai_metadata, "get_setting", return_value="x"), \
         patch.object(ai_metadata, "build_library_context", side_effect=RuntimeError("db")), \
         patch.object(ai_metadata.requests, "post", return_value=_ai_response(answer)) as post:
        result = fetch_ai_suggestions(target)
    assert result["ok"] and result["suggestions"]["title"]["value"] == "Solo"
    assert "Library alignment rules" not in post.call_args.kwargs["json"]["messages"][0]["content"]
