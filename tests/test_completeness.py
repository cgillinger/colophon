# Colophon - completeness score: weights, refresh, backfill, route counts
"""completeness_score is a 0..10 traffic-light score (0 = complete). It must
be recomputed on every write path, not just metadata_writer's apply flow, so
it stays accurate for the UI traffic light."""
from unittest.mock import patch

import pytest
from flask import Flask
from flask_babel import Babel

from app.models import db, LibraryItem
from app.routes.metadata import metadata_bp
from app.services.metadata_pipeline import completeness_score


@pytest.fixture
def app(tmp_path):
    app = Flask(__name__, template_folder=None)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + str(tmp_path / "t.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    cover_dir = tmp_path / "covers"
    cover_dir.mkdir()
    app.config["COVER_DIR"] = str(cover_dir)
    db.init_app(app)
    Babel(app)
    app.register_blueprint(metadata_bp)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _full_item(**overrides):
    """A LibraryItem with every completeness-weighted field filled in (cover
    excluded — no test builds a real cover file, so it always reads as
    missing; that's fine since it's equal across items in a given test)."""
    fields = dict(
        title="A Book",
        author="An Author",
        description="A" * 60,
        genres="Fantasy",
        published_date="2020-01-01",
        publisher="Acme Press",
        series="A Series",
        file_path="/books/a-book.epub",
        file_name="a-book.epub",
        extension=".epub",
    )
    fields.update(overrides)
    return LibraryItem(**fields)


def test_completeness_score_counts_series():
    complete = _full_item()
    missing_series = _full_item(series=None)

    assert completeness_score(missing_series) == completeness_score(complete) + 1


def test_refresh_completeness_sets_score():
    from app.services.metadata_pipeline import refresh_completeness

    item = _full_item(series=None)
    assert item.completeness_score is None

    refresh_completeness(item)

    assert item.completeness_score == completeness_score(item)


@pytest.mark.parametrize("score,bucket", [
    (0, "green"), (1, "green"),
    (2, "yellow"), (5, "yellow"),
    (6, "red"), (10, "red"),
])
def test_bucket_thresholds(score, bucket):
    from app.routes.metadata import _completeness_bucket

    assert _completeness_bucket(score) == bucket


def test_backfill_sets_null_scores(app):
    from app.services.database import backfill_completeness_scores

    item = _full_item(series=None)
    db.session.add(item)
    db.session.commit()
    assert item.completeness_score is None

    backfill_completeness_scores()

    db.session.refresh(item)
    assert item.completeness_score == completeness_score(item)


def test_save_json_recomputes_completeness(client, app):
    item = _full_item()
    db.session.add(item)
    db.session.commit()
    item_id = item.id
    before = completeness_score(item)

    payload = {
        "title": "A Book",
        "author": "An Author",
        "series": "A Series",
        "genres": "Fantasy",
        "published_date": "2020-01-01",
        "publisher": "Acme Press",
        "description": "",  # wipe a previously-adequate synopsis
    }
    with patch("app.routes.metadata.write_metadata_to_file", return_value={"ok": True}):
        resp = client.post(f"/metadata/{item_id}/save-json", json=payload)
    assert resp.get_json()["ok"] is True

    fresh = db.session.get(LibraryItem, item_id)
    assert fresh.completeness_score is not None
    assert fresh.completeness_score > before
