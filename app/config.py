import os

from app.paths import VAR_DIR as _VAR_DIR


class Config:
    SECRET_KEY = os.environ.get("COLOPHON_SECRET_KEY", "colophon-utveckling")

    DATA_DIR = os.environ.get("COLOPHON_DATA_DIR", "/data")
    LIBRARY_DIR = os.environ.get("COLOPHON_LIBRARY_DIR", "/books")
    COVER_DIR = os.environ.get("COLOPHON_COVER_DIR", os.path.join(DATA_DIR, "covers"))

    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(DATA_DIR, "colophon.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_TYPE = "filesystem"
    SESSION_FILE_DIR = str(_VAR_DIR / "sessions")
    SESSION_PERMANENT = False
