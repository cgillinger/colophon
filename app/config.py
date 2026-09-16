# Colophon – e-book metadata manager
import os

from app.paths import VAR_DIR as _VAR_DIR


class Config:
    SECRET_KEY = os.environ.get("COLOPHON_SECRET_KEY", "colophon-utveckling")

    DATA_DIR = os.environ.get("COLOPHON_DATA_DIR", "/data")
    LIBRARY_DIR = os.environ.get("COLOPHON_LIBRARY_DIR", "/books")
    COVER_DIR = os.environ.get("COLOPHON_COVER_DIR", os.path.join(DATA_DIR, "covers"))

    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(DATA_DIR, "colophon.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPSTREAM_DIR = os.environ.get("COLOPHON_UPSTREAM_DIR", "").strip() or None

    # Max size of a single uploaded file (in-app upload feature). Ebooks are
    # small but comics (CBZ/CBR) and image-heavy PDFs can be large, so default
    # generously. Gunicorn rejects oversized bodies before they hit a worker.
    MAX_CONTENT_LENGTH = int(os.environ.get("COLOPHON_MAX_UPLOAD_MB", "1024")) * 1024 * 1024

    # How many days a freshly added book wears the "Nytillagt" badge. Derived
    # from LibraryItem.created_at, so it self-expires — no flag to clear.
    NEW_BADGE_DAYS = int(os.environ.get("COLOPHON_NEW_BADGE_DAYS", "14"))

    # Whose library this instance shows. Rendered verbatim under the wordmark
    # in the sidebar so each per-person instance (see multi-user-via-instances)
    # is self-identifying. Empty = no label. Set to the full text you want,
    # e.g. COLOPHON_LIBRARY_OWNER="Christians bibliotek".
    LIBRARY_OWNER = os.environ.get("COLOPHON_LIBRARY_OWNER", "").strip()

    SESSION_TYPE = "filesystem"
    SESSION_FILE_DIR = str(_VAR_DIR / "sessions")
    SESSION_PERMANENT = False
