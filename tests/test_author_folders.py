# Colophon – tests for author-folder moves + upstream orphan cleanup
"""DESIGN-author-folders.md: folder-name safety, sister-folder reuse,
atomic group moves that preserve the row id and suppress the Kobo
content stamp, and the surgical push-time orphan cleanup."""
import os

import pytest
from flask import Flask

from app.models import db, Author, LibraryItem
from app.services.author_folders import (
    author_folder_key,
    describe_move,
    move_item_to_author_folder,
    resolve_author_folder,
    sanitize_folder_name,
)


@pytest.fixture
def app(tmp_path):
    lib = tmp_path / "library"
    lib.mkdir()
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + str(tmp_path / "t.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["LIBRARY_DIR"] = str(lib)
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def session(app):
    return db.session


def _lib(app):
    return app.config["LIBRARY_DIR"]


_counter = iter(range(1, 10_000))


def _add_book(session, app, author="Maggie Haberman", name=None,
              group_key=None, in_folder=None, **fields):
    n = next(_counter)
    name = name or f"book-{n}.epub"
    directory = _lib(app) if not in_folder else os.path.join(_lib(app), in_folder)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, name)
    with open(path, "wb") as fh:
        fh.write(b"epub-bytes")
    entry = None
    if author:
        entry = Author(canonical_name=author, source="user_confirmed")
        session.add(entry)
        session.flush()
    item = LibraryItem(
        title=f"Book {n}",
        author=author,
        author_id=entry.id if entry else None,
        author_status="linked" if entry else None,
        file_path=path,
        file_name=name,
        extension=os.path.splitext(name)[1],
        group_key=group_key,
        **fields,
    )
    session.add(item)
    session.commit()
    return item


# --------------------------------------------------------------------------
# Naming safety + consolidation
# --------------------------------------------------------------------------

def test_folder_key_consolidates_cosmetic_variants():
    assert author_folder_key("arthur_c_clarke") == author_folder_key("Arthur C. Clarke")
    assert author_folder_key("ARTHUR  C  CLARKE") == author_folder_key("Arthur C. Clarke")
    # Semantic variation is NOT consolidated.
    assert author_folder_key("A. C. Clarke") != author_folder_key("Arthur C. Clarke")


def test_sanitize_folder_name_hostile_input():
    assert sanitize_folder_name("../../etc") == "etc"
    assert sanitize_folder_name("a/b\\c") == "c"
    assert sanitize_folder_name("CON") is None
    assert sanitize_folder_name("///") is None
    assert sanitize_folder_name(" . ") is None
    assert len(sanitize_folder_name("x" * 500)) <= 120
    assert sanitize_folder_name("O'Brien, Flann") == "O'Brien, Flann"


def test_resolve_reuses_sister_folder(app):
    os.makedirs(os.path.join(_lib(app), "Arthur C. Clarke"))
    assert resolve_author_folder(_lib(app), "arthur_c_clarke") == "Arthur C. Clarke"
    assert resolve_author_folder(_lib(app), "Ursula K. Le Guin") == "Ursula K. Le Guin"


# --------------------------------------------------------------------------
# Eligibility + the move itself
# --------------------------------------------------------------------------

def test_describe_move_gates(app, session):
    foldered = _add_book(session, app, in_folder="Nora Roberts")
    assert describe_move(session, foldered)["reason"] == "not_in_root"

    no_author = _add_book(session, app, author=None)
    info = describe_move(session, no_author)
    assert info["in_root"] and info["reason"] == "no_author"

    ok = _add_book(session, app)
    info = describe_move(session, ok)
    assert info["eligible"] and info["folder"] == "Maggie Haberman"


def test_move_whole_group_preserves_id_and_content_stamp(app, session):
    item = _add_book(session, app, name="regime.epub", group_key="g1")
    sibling = _add_book(session, app, author=None, name="regime.mobi", group_key="g1")
    old_id = item.id
    old_stamp = item.content_updated_at

    info = move_item_to_author_folder(session, item)
    session.commit()

    assert info["eligible"] and info["moved"] == 2
    target = os.path.join(_lib(app), "Maggie Haberman")
    assert os.path.isfile(os.path.join(target, "regime.epub"))
    assert os.path.isfile(os.path.join(target, "regime.mobi"))
    assert item.id == old_id
    assert item.file_path == os.path.join(target, "regime.epub")
    assert sibling.file_path == os.path.join(target, "regime.mobi")
    # Move is not a content change — Kobo must not re-download.
    assert item.content_updated_at == old_stamp
    # But the new path enters the push queue.
    assert item.file_modified_by_colophon is not None
    assert sibling.file_modified_by_colophon is not None


def test_move_records_pending_cleanup_only_when_pushed(app, session):
    from datetime import datetime

    pushed = _add_book(session, app, name="pushed.epub",
                       upstream_synced_at=datetime(2026, 1, 1))
    never_pushed = _add_book(session, app, author="Ken Grimwood",
                             name="fresh.epub")

    move_item_to_author_folder(session, pushed)
    move_item_to_author_folder(session, never_pushed)
    session.commit()

    assert pushed.pending_upstream_cleanup == "pushed.epub"
    assert never_pushed.pending_upstream_cleanup is None


def test_move_refuses_when_target_exists(app, session):
    item = _add_book(session, app, name="dupe.epub")
    os.makedirs(os.path.join(_lib(app), "Maggie Haberman"), exist_ok=True)
    with open(os.path.join(_lib(app), "Maggie Haberman", "dupe.epub"), "wb") as fh:
        fh.write(b"other")

    info = move_item_to_author_folder(session, item)
    assert not info["eligible"] and info["reason"] == "target_exists"
    # Nothing moved, nothing marked.
    assert os.path.isfile(item.file_path)
    assert item.pending_upstream_cleanup is None


# --------------------------------------------------------------------------
# Push-time orphan cleanup
# --------------------------------------------------------------------------

def _run_push(app, monkeypatch, upstream, enabled):
    import app.services.app_settings as app_settings
    monkeypatch.setattr(app_settings, "get_upstream_dir", lambda: str(upstream))
    monkeypatch.setattr(
        app_settings, "upstream_cleanup_enabled", lambda: enabled
    )
    from app.services.upstream_sync import push_to_upstream
    return list(push_to_upstream())


def _moved_pushed_book(app, session, tmp_path):
    """A book that was pushed flat, then moved locally: upstream still
    holds the old flat copy."""
    from datetime import datetime

    upstream = tmp_path / "upstream"
    (upstream / "keep").mkdir(parents=True)
    with open(upstream / "keep" / "anchor.txt", "wb") as fh:
        fh.write(b"x")  # upstream must not look unmounted/empty

    item = _add_book(session, app, name="moved.epub",
                     upstream_synced_at=datetime(2026, 1, 1))
    with open(upstream / "moved.epub", "wb") as fh:
        fh.write(b"old-copy")
    move_item_to_author_folder(session, item)
    session.commit()
    return upstream, item


def test_push_cleans_orphan_when_enabled(app, session, tmp_path, monkeypatch):
    upstream, item = _moved_pushed_book(app, session, tmp_path)

    events = _run_push(app, monkeypatch, upstream, enabled=True)

    done = [e for e in events if e["type"] == "done"][0]
    assert done["synced"] == 1 and done["cleaned"] == 1
    # New path exists upstream, old flat copy removed, marker cleared.
    assert (upstream / "Maggie Haberman" / "moved.epub").is_file()
    assert not (upstream / "moved.epub").exists()
    assert item.pending_upstream_cleanup is None
    assert item.upstream_rel_path == os.path.join("Maggie Haberman", "moved.epub")


def test_push_keeps_orphan_when_disabled(app, session, tmp_path, monkeypatch):
    upstream, item = _moved_pushed_book(app, session, tmp_path)

    events = _run_push(app, monkeypatch, upstream, enabled=False)

    done = [e for e in events if e["type"] == "done"][0]
    assert done["synced"] == 1 and done["cleaned"] == 0
    # Duplicate stays, but the pending marker survives for later.
    assert (upstream / "moved.epub").is_file()
    assert item.pending_upstream_cleanup == "moved.epub"

    # Enabling later cleans retroactively on the next push.
    item.file_modified_by_colophon = None
    session.commit()
    move_again_marker = item.pending_upstream_cleanup
    assert move_again_marker == "moved.epub"
    from datetime import datetime
    item.file_modified_by_colophon = datetime.utcnow()
    session.commit()
    events = _run_push(app, monkeypatch, upstream, enabled=True)
    assert [e for e in events if e["type"] == "done"][0]["cleaned"] == 1
    assert not (upstream / "moved.epub").exists()
    assert item.pending_upstream_cleanup is None


def test_orphan_removal_stays_inside_upstream(tmp_path):
    from app.services.upstream_sync import _remove_upstream_orphan

    upstream = tmp_path / "up"
    upstream.mkdir()
    outside = tmp_path / "secret.txt"
    with open(outside, "wb") as fh:
        fh.write(b"x")

    assert _remove_upstream_orphan(str(upstream), "../secret.txt") is False
    assert outside.exists()


def test_orphan_removal_prunes_empty_folder(tmp_path):
    from app.services.upstream_sync import _remove_upstream_orphan

    upstream = tmp_path / "up"
    old_dir = upstream / "Old Author"
    old_dir.mkdir(parents=True)
    with open(old_dir / "b.epub", "wb") as fh:
        fh.write(b"x")
    with open(old_dir / "b.jpg", "wb") as fh:
        fh.write(b"cover")

    assert _remove_upstream_orphan(str(upstream), "Old Author/b.epub") is True
    assert not old_dir.exists()  # book + cover gone → folder pruned
