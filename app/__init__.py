import logging
import os
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, redirect, request, url_for
from flask_babel import Babel
from flask_session import Session

from app.config import Config
from app.models import db
from app.paths import LOG_DIR
from app.routes.metadata import metadata_bp
from app.routes.scan import scan_bp
from app.routes.settings import settings_bp
from app.services.database import ensure_database_columns, ensure_ai_usage_log_table, ensure_app_settings_table

SUPPORTED_LANGUAGES = ("en", "sv")

babel = Babel()


def get_locale():
    lang = request.cookies.get("colophon_lang")
    if lang in SUPPORTED_LANGUAGES:
        return lang
    return request.accept_languages.best_match(SUPPORTED_LANGUAGES, default="en")


def _configure_logging(app):
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_level_name = os.environ.get("COLOPHON_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        LOG_DIR / "colophon.log",
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
    os.makedirs(app.config["LIBRARY_DIR"], exist_ok=True)
    os.makedirs(app.config["SESSION_FILE_DIR"], exist_ok=True)

    app.config.setdefault("BABEL_DEFAULT_LOCALE", "en")
    app.config.setdefault("BABEL_TRANSLATION_DIRECTORIES", "translations")

    Session(app)
    babel.init_app(app, locale_selector=get_locale)

    @app.context_processor
    def inject_locale():
        return {"get_locale": get_locale}

    @app.route("/set-language/<lang>")
    def set_language(lang):
        if lang not in SUPPORTED_LANGUAGES:
            lang = "en"
        target = request.referrer or url_for("metadata.bulk_metadata")
        response = redirect(target)
        response.set_cookie("colophon_lang", lang, max_age=365 * 24 * 60 * 60)
        return response

    _configure_logging(app)

    db.init_app(app)

    with app.app_context():
        db.create_all()
        ensure_database_columns()
        ensure_app_settings_table()
        ensure_ai_usage_log_table()

    app.register_blueprint(metadata_bp)
    app.register_blueprint(scan_bp)
    app.register_blueprint(settings_bp)

    @app.after_request
    def no_cache_html(response):
        if response.content_type and "text/html" in response.content_type:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response

    return app
