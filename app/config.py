import os

from app.paths import COVER_DIR as _COVER_DIR
from app.paths import DATA_DIR as _DATA_DIR
from app.paths import LIBRARY_ROOT as _LIBRARY_ROOT
from app.paths import VAR_DIR as _VAR_DIR


class Config:
    SECRET_KEY = os.environ.get("COLOPHON_SECRET_KEY", "colophon-utveckling")

    DATA_DIR = str(_DATA_DIR)
    COVER_DIR = str(_COVER_DIR)
    LIBRARY_DIR = str(_LIBRARY_ROOT)

    SQLALCHEMY_DATABASE_URI = "sqlite:///" + str(_DATA_DIR / "colophon.sqlite3")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_TYPE = "filesystem"
    SESSION_FILE_DIR = str(_VAR_DIR / "sessions")
    SESSION_PERMANENT = False
