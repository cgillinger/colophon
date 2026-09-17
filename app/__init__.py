# Colophon – e-book metadata manager
import contextlib
import logging
import os
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, Response, jsonify, redirect, render_template, request, url_for
from flask_babel import Babel
from flask_session import Session

from app.config import Config
from app.models import db
from app.paths import LOG_DIR
from app.routes.authors import authors_bp
from app.routes.kobo import kobo_bp
from app.routes.metadata import metadata_bp
from app.routes.reader import reader_bp
from app.routes.scan import scan_bp
from app.routes.settings import settings_bp
from app.services.database import (
    ensure_ai_usage_log_table,
    ensure_app_settings_table,
    ensure_author_tables,
    ensure_database_columns,
    ensure_device_transfers_table,
    ensure_kobo_book_states_table,
    ensure_kobo_devices_table,
    ensure_multi_author_tables,
)

SUPPORTED_LANGUAGES = ("en", "sv")

babel = Babel()


@contextlib.contextmanager
def _schema_lock(data_dir):
    """Serialise schema setup across processes.

    Gunicorn boots its workers simultaneously and every one of them runs the
    migration block in create_app() against the same SQLite file. Each step in
    that block is check-then-act — create_all()'s checkfirst, ensure_*'s
    "does this column exist" — so on a database that is still empty two
    workers can both decide a table is missing, and the loser dies with
    "table library_items already exists". That is a failed boot, not a
    warning: gunicorn gives up after enough of them.

    An exclusive lock on a file beside the database makes the block
    one-at-a-time, so whoever comes second finds the schema already there and
    skips it. Only the first boot of a fresh database actually contends;
    afterwards every worker takes the lock, finds nothing to do and releases
    it. If the lock can't be taken at all (no fcntl, a filesystem that won't
    flock), we proceed unlocked rather than refuse to start — that is the
    behaviour this project had before, races included.
    """
    try:
        import fcntl
    except ImportError:  # not POSIX
        yield
        return

    lock_path = os.path.join(data_dir, ".schema.lock")
    try:
        os.makedirs(data_dir, exist_ok=True)
        handle = open(lock_path, "w")
    except OSError:
        yield
        return

    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError:
            yield
            return
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def get_locale():
    try:
        from flask import has_request_context
        if not has_request_context():
            return "en"
        lang = request.cookies.get("colophon_lang")
        if lang in SUPPORTED_LANGUAGES:
            return lang
        return request.accept_languages.best_match(SUPPORTED_LANGUAGES, default="en")
    except Exception:
        return "en"


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

    @app.context_processor
    def inject_version():
        from app.version import __version__
        return {"app_version": __version__}

    @app.context_processor
    def inject_reader_shell_assets():
        """The static assets the reader shell needs to run offline, version-stamped.
        Shared by reader.html (its own save-for-offline) and bulk_metadata.html
        (save-for-offline from the book modal) so the two lists can never drift.

        Includes foliate-js's whole module graph *except* the pdf.js vendor
        subtree. foliate loads format parsers with runtime dynamic imports
        (``view.js`` does ``import('./epub.js')``, ``import('./vendor/zip.js')``
        for EPUB, ``import('./vendor/fflate.js')`` for MOBI, plus ``ui/*``), so
        the graph is not knowable from static imports and a top-level-only list
        would miss ``vendor/zip.js`` — the EPUB unzip — and hang the offline
        reader on "Loading book". These files carry no ``?v=`` (their relative
        imports must resolve, and they match the SW's FOLIATE_PREFIX rule), and
        they are cached at *save* time here rather than relying on
        stale-while-revalidate having run the reader online first. The pdf.js
        subtree (``vendor/pdfjs/``, ~6 MB) is deliberately excluded: PDF offline
        reading still needs the book opened online once. EPUB/MOBI do not.
        """
        import glob
        import os
        from app.version import __version__
        v = __version__
        assets = [
            url_for("static", filename="js/reader.js") + "?v=" + v,
            # reader.js imports reader-dict.js WITHOUT a ?v= (a bare ES-module
            # specifier), so the request the browser makes carries no query and
            # Cache Storage's exact-query match misses the ?v= copy. Cache the
            # unversioned URL too — the one the import actually asks for — or the
            # whole reader.js graph fails to load offline and the reader hangs
            # on "Loading book…". (cacheFirst also matches ignoreSearch as a
            # backstop; this makes the exact URL present regardless.)
            url_for("static", filename="js/reader-dict.js") + "?v=" + v,
            url_for("static", filename="js/reader-dict.js"),
            url_for("static", filename="css/bulk_metadata.css") + "?v=" + v,
            url_for("static", filename="vendor/tabler-icons/tabler-icons.min.css"),
            url_for("static", filename="vendor/tabler-icons/fonts/tabler-icons.woff2"),
            url_for("static", filename="fonts/opendyslexic-400.woff2"),
            url_for("static", filename="fonts/opendyslexic-700.woff2"),
        ]
        foliate_dir = os.path.join(app.static_folder, "vendor", "foliate-js")
        pdfjs_dir = os.path.join(foliate_dir, "vendor", "pdfjs") + os.sep
        for path in sorted(glob.glob(os.path.join(foliate_dir, "**", "*.js"), recursive=True)):
            if path.startswith(pdfjs_dir):
                continue  # PDF-only, ~6 MB
            rel = os.path.relpath(path, app.static_folder).replace(os.sep, "/")
            assets.append(url_for("static", filename=rel))
        return {"reader_shell_assets": assets}

    @app.context_processor
    def inject_completeness_helpers():
        """The traffic light's tooltip must list exactly the fields the
        score counted, so the template asks the scorer rather than
        re-deriving it with its own `if not item.x` tests."""
        from app.services.metadata_pipeline import missing_fields
        return {"completeness_missing_fields": missing_fields}

    @app.context_processor
    def inject_library_owner():
        """The per-instance library owner label shown under the wordmark
        (COLOPHON_LIBRARY_OWNER). Empty string = render nothing."""
        return {"library_owner": app.config.get("LIBRARY_OWNER", "")}

    @app.context_processor
    def inject_sidebar_counts():
        """Library counts shown in the sidebar across every page.
        Cheap queries — three COUNT(*) statements on a single-user SQLite
        DB. Cached per request via Flask's context_processor mechanism.
        Also pulls the unsynced count when upstream sync is configured —
        small badge on the Kobo-synk sidebar item."""
        from app.models import LibraryItem
        try:
            total = LibraryItem.query.count()
            reading = LibraryItem.query.filter(LibraryItem.read_status == "Reading").count()
            finished = LibraryItem.query.filter(LibraryItem.read_status == "Finished").count()
            unread = total - reading - finished
        except Exception:
            total = reading = finished = unread = 0
        try:
            from app.services.upstream_sync import (
                upstream_configured,
                get_unsynced_count,
                get_pending_cleanup_count,
            )
            # Pending upstream cleanups count as "something to sync" too —
            # a cleanup-only push must be reachable even when no book has
            # changed (the button is the only way to trigger a push).
            unsynced = (
                get_unsynced_count() + get_pending_cleanup_count()
            ) if upstream_configured() else 0
        except Exception:
            unsynced = 0
        return {
            "sidebar_total": total,
            "sidebar_unread": unread,
            "sidebar_reading": reading,
            "sidebar_finished": finished,
            "sidebar_unsynced": unsynced,
        }

    @app.route("/set-language/<lang>")
    def set_language(lang):
        if lang not in SUPPORTED_LANGUAGES:
            lang = "en"
        target = request.referrer or url_for("metadata.bulk_metadata")
        response = redirect(target)
        response.set_cookie("colophon_lang", lang, max_age=365 * 24 * 60 * 60)
        return response

    # --- PWA: manifest + service worker -------------------------------
    # Both are served from the origin root (not /static) so the service
    # worker's scope covers the whole app. Paths inside are root-relative
    # so the same files work whether the app is reached via LAN IP or a
    # Tailscale Serve HTTPS hostname.
    @app.route("/manifest.json")
    def manifest():
        from app.version import __version__
        data = {
            "name": "Colophon",
            "short_name": "Colophon",
            "description": "Self-hosted e-book metadata manager",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "orientation": "any",
            "background_color": "#ffffff",
            "theme_color": "#ffffff",
            "lang": "en",
            "version": __version__,
            "icons": [
                {
                    "src": url_for("static", filename="icons/icon-192.png"),
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": url_for("static", filename="icons/icon-512.png"),
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any",
                },
            ],
        }
        resp = jsonify(data)
        resp.headers["Content-Type"] = "application/manifest+json"
        return resp

    @app.route("/offline")
    def offline_page():
        # Standalone landing page for the "no connection at all" case — see
        # app/templates/offline.html. Precached by sw.js on install so it is
        # always available regardless of network state.
        return render_template("offline.html")

    @app.route("/sw.js")
    def service_worker():
        # Rendered (not static) so the version is baked into the body, and
        # served no-cache so the controlling file is always revalidated —
        # the two things that make updates propagate reliably.
        body = render_template("sw.js")
        resp = Response(body, mimetype="application/javascript")
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Service-Worker-Allowed"] = "/"
        return resp

    _configure_logging(app)

    db.init_app(app)

    with app.app_context(), _schema_lock(app.config["DATA_DIR"]):
        # Order matters. ensure_author_tables() must precede ensure_database_columns()
        # because the author_id ALTER references authors(id). Both must precede
        # db.create_all(), because create_all() emits CREATE INDEX for the
        # ix_library_items_author_id index and that fails if the author_id column
        # doesn't exist on library_items yet.
        ensure_author_tables()
        ensure_database_columns()
        db.create_all()
        ensure_app_settings_table()
        ensure_ai_usage_log_table()
        ensure_kobo_devices_table()
        ensure_kobo_book_states_table()
        ensure_device_transfers_table()
        # After create_all + ensure_database_columns: needs both
        # library_items.author_id (for the backfill) and the authors table.
        ensure_multi_author_tables()

    app.register_blueprint(metadata_bp)
    app.register_blueprint(authors_bp)
    app.register_blueprint(scan_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(kobo_bp)
    app.register_blueprint(reader_bp)

    @app.after_request
    def no_cache_html(response):
        if response.content_type and "text/html" in response.content_type:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return response

    return app
