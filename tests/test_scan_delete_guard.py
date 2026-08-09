# Colophon – e-book metadata manager
"""The scanner's delete phase must not read 'unreadable' as 'deleted'.

`scan_directory` removes every catalogue row whose file it cannot find, which
is correct when the user deleted a book and catastrophic when the library
volume merely came up empty or stopped responding — a NAS that isn't exported
yet, a re-created Docker volume, a stale network handle. The whole catalogue
(and every reading position on it) goes, and the next scan puts the books back
as *new* rows with new ids, which the Kobo then treats as different books.

The upstream puller has guarded against exactly this since it was written
(`upstream_sync.py`); these tests hold the scanner to the same standard.
"""
import os
from unittest.mock import patch

import pytest

from app.services.scanner import _file_state


# ---------------------------------------------------------------------------
# _file_state — the "is it really gone?" question, answered honestly
# ---------------------------------------------------------------------------

def test_existing_file_is_present(tmp_path):
    book = tmp_path / "book.epub"
    book.write_bytes(b"x")
    assert _file_state(str(book)) == "present"


def test_deleted_file_is_missing(tmp_path):
    assert _file_state(str(tmp_path / "gone.epub")) == "missing"


def test_empty_path_is_missing():
    assert _file_state("") == "missing"
    assert _file_state(None) == "missing"


def test_path_through_a_non_directory_is_missing(tmp_path):
    """A path component that isn't a directory can't contain the file."""
    notdir = tmp_path / "notdir"
    notdir.write_bytes(b"x")
    assert _file_state(str(notdir / "book.epub")) == "missing"


@pytest.mark.parametrize(
    "errno_name", ["EIO", "EACCES", "ESTALE", "ENOTCONN", "EHOSTDOWN"]
)
def test_io_errors_are_unreadable_not_missing(tmp_path, errno_name):
    """The distinction the whole guard rests on.

    A stale NFS handle, a disconnected share and a permission error all make
    Path.exists() answer False, exactly like a deleted file. Deleting a row on
    that answer is how a library disappears.
    """
    import errno as errno_mod

    code = getattr(errno_mod, errno_name, None)
    if code is None:
        pytest.skip(f"{errno_name} not available on this platform")

    with patch("app.services.scanner.os.stat", side_effect=OSError(code, "boom")):
        assert _file_state(str(tmp_path / "book.epub")) == "unreadable"


# ---------------------------------------------------------------------------
# scan_directory — the guard itself
# ---------------------------------------------------------------------------

@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("COLOPHON_SECRET_KEY", "test-secret")
    from app import create_app
    from app.models import db
    from sqlalchemy import text

    flask_app = create_app()
    flask_app.config["TESTING"] = True

    def _wipe():
        with flask_app.app_context():
            db.session.execute(text("DELETE FROM kobo_book_states"))
            db.session.execute(text("DELETE FROM library_items"))
            db.session.commit()

    _wipe()
    yield flask_app
    _wipe()


def _add_book(title, path):
    from app.models import LibraryItem, db

    item = LibraryItem(
        title=title,
        file_path=str(path),
        file_name=os.path.basename(str(path)),
        extension=".epub",
        read_status="Reading",
        read_progress=60.0,
    )
    db.session.add(item)
    db.session.commit()
    return item.id


def test_empty_library_directory_deletes_nothing(app, tmp_path):
    """The disaster case: the volume mounts empty.

    root.exists() is True, discovery finds nothing, and the old code read that
    as "the user deleted all 380 books".
    """
    from app.models import LibraryItem, db
    from app.services.scanner import scan_directory

    library = tmp_path / "books"
    library.mkdir()

    with app.app_context():
        _add_book("Kept Book", library / "kept.epub")
        _add_book("Other Book", library / "other.epub")

        result = scan_directory(str(library), db_session=db.session)

        assert result["removed"] == 0
        assert LibraryItem.query.count() == 2
        # And the reading position survived with them.
        assert {i.read_progress for i in LibraryItem.query.all()} == {60.0}


def test_genuinely_deleted_book_is_still_removed(app, tmp_path):
    """The guard must not turn the delete phase off — only qualify it."""
    from app.models import LibraryItem, db
    from app.services.scanner import scan_directory

    library = tmp_path / "books"
    library.mkdir()
    present = library / "present.epub"
    present.write_bytes(b"not really an epub")

    with app.app_context():
        _add_book("Present Book", present)
        _add_book("Vanished Book", library / "vanished.epub")

        scan_directory(str(library), db_session=db.session)

        # Assert on paths, not titles: re-scanning a file rewrites its title
        # from the file's own (here absent) metadata.
        paths = {i.file_path for i in LibraryItem.query.all()}
        assert str(library / "vanished.epub") not in paths
        assert str(present) in paths


def test_unreadable_files_are_kept_not_deleted(app, tmp_path):
    """A library that is present but throwing I/O errors keeps its rows."""
    from app.models import LibraryItem, db
    from app.services.scanner import scan_directory

    library = tmp_path / "books"
    library.mkdir()
    real = library / "real.epub"
    real.write_bytes(b"not really an epub")

    with app.app_context():
        _add_book("Unreadable Book", library / "unreadable.epub")

        real_stat = os.stat

        def flaky_stat(path, *args, **kwargs):
            if str(path).endswith("unreadable.epub"):
                raise OSError(5, "Input/output error")
            return real_stat(path, *args, **kwargs)

        with patch("app.services.scanner.os.stat", side_effect=flaky_stat):
            result = scan_directory(str(library), db_session=db.session)

        assert result["removed"] == 0
        # The row whose file we couldn't read is still there. (real.epub is
        # also picked up as a new row — that's the scan doing its normal job.)
        paths = {i.file_path for i in LibraryItem.query.all()}
        assert str(library / "unreadable.epub") in paths
