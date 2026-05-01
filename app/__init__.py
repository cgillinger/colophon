import logging
import os
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv

load_dotenv()

from flask import Flask
from flask_session import Session

from app.config import Config
from app.models import db
from app.paths import LOG_DIR
from app.routes.library import library_bp
from app.routes.reader import reader_bp
from app.routes.metadata import metadata_bp
from app.routes.bookstores import bookstores_bp
from app.routes.drm import drm_bp
from app.routes.settings import settings_bp
from app.services.database import ensure_database_columns, ensure_ai_usage_log_table


def _configure_logging(app):
    """Konfigurerar roterande fillogg för Flask-applikationen."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_level_name = os.environ.get("BOOKSTATION_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        LOG_DIR / "bookstation.log",
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)

    app.logger.addHandler(file_handler)
    app.logger.setLevel(log_level)

    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def create_app():
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static"
    )

    app.config.from_object(Config)

    os.makedirs(app.config["DATA_DIR"], exist_ok=True)
    os.makedirs(app.config["COVER_DIR"], exist_ok=True)
    os.makedirs(app.config["EPUB_CACHE_DIR"], exist_ok=True)
    os.makedirs(app.config["LIBRARY_DIR"], exist_ok=True)
    os.makedirs(app.config["SESSION_FILE_DIR"], exist_ok=True)

    Session(app)

    _configure_logging(app)

    db.init_app(app)

    with app.app_context():
        db.create_all()
        ensure_database_columns()
        ensure_ai_usage_log_table()

    app.register_blueprint(library_bp)
    app.register_blueprint(reader_bp)
    app.register_blueprint(metadata_bp)
    app.register_blueprint(bookstores_bp)
    app.register_blueprint(drm_bp)
    app.register_blueprint(settings_bp)

    return app
