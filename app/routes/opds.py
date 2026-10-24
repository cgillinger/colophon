# Colophon – e-book metadata manager
"""OPDS 1.2 catalogue for e-readers that browse and download on their own.

Built for CrossPoint on an Xteink (``freeink-sdk/libs/network/Opds``), which
reads Atom feeds: navigation entries are links with an ``application/atom+xml``
type, books are entries with an ``application/epub+zip`` acquisition link, and
it keeps at most 62 entries per page, so pages here hold 50 and carry
``rel="next"``. Search is an inline OpenSearch template.

Only EPUBs are offered — that is what the device reads — and the file served
is the library's own, byte for byte. That matters for reading position: the
device names a book by a hash of its copy (services/kosync_documents.py), and
each download records the hashes of exactly what was sent.
"""
import logging
import os
from datetime import datetime
from functools import wraps
from urllib.parse import quote
from xml.sax.saxutils import escape, quoteattr

from flask import Blueprint, Response, abort, current_app, request, send_file
from flask_babel import force_locale, gettext as _
from sqlalchemy import func, or_

from app.models import LibraryItem, db
from app.services.kosync_documents import index_item
from app.services.reader_devices import find_device_by_token, touch_device

logger = logging.getLogger(__name__)

opds_bp = Blueprint("opds", __name__, url_prefix="/opds")

PAGE_SIZE = 50
_NAV = "application/atom+xml;profile=opds-catalog;kind=navigation"
_ACQ = "application/atom+xml;profile=opds-catalog;kind=acquisition"
_EPUB_EXTENSIONS = (".epub", "epub")


def require_reader(f):
    @wraps(f)
    def wrapper(token, *args, **kwargs):
        device = find_device_by_token(token)
        if device is None:
            logger.info("OPDS auth failed for token prefix %s...", token[:8])
            return Response("Unauthorized", status=401)
        touch_device(device)
        with force_locale(device.language or "en"):
            return f(device, token, *args, **kwargs)
    return wrapper


def _books():
    return LibraryItem.query.filter(LibraryItem.extension.in_(_EPUB_EXTENSIONS))


def _ts(dt: datetime | None) -> str:
    return (dt or datetime.utcnow()).strftime("%Y-%m-%dT%H:%M:%SZ")


def _base(token: str) -> str:
    explicit = os.environ.get("COLOPHON_PUBLIC_URL", "").rstrip("/")
    return f"{explicit or request.host_url.rstrip('/')}/opds/{token}"


def _feed(token, feed_id, title, kind, entries, next_url=None, updated=None) -> Response:
    base = _base(token)
    self_url = request.url
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:opds="http://opds-spec.org/2010/catalog" '
        'xmlns:dc="http://purl.org/dc/terms/">',
        f"<id>urn:colophon:opds:{escape(feed_id)}</id>",
        f"<title>{escape(title)}</title>",
        f"<updated>{_ts(updated)}</updated>",
        "<author><name>Colophon</name></author>",
        f"<link rel=\"self\" type=\"{kind}\" href={quoteattr(self_url)}/>",
        f"<link rel=\"start\" type=\"{_NAV}\" href={quoteattr(base + '/')}/>",
        f"<link rel=\"search\" type=\"{_ACQ}\" "
        f"href={quoteattr(base + '/search?q={searchTerms}')}/>",
    ]
    if next_url:
        parts.append(f"<link rel=\"next\" type=\"{kind}\" href={quoteattr(next_url)}/>")
    parts.extend(entries)
    parts.append("</feed>")
    return Response("\n".join(parts), mimetype=f"{kind};charset=utf-8")


def _nav_entry(entry_id, title, href, summary="", kind=_ACQ) -> str:
    body = f"<content type=\"text\">{escape(summary)}</content>" if summary else ""
    return (
        f"<entry><title>{escape(title)}</title>"
        f"<id>urn:colophon:opds:{escape(entry_id)}</id>"
        f"<updated>{_ts(None)}</updated>{body}"
        f"<link rel=\"subsection\" type=\"{kind}\" href={quoteattr(href)}/></entry>"
    )


def _plain(text: str | None, limit: int = 600) -> str:
    if not text:
        return ""
    from bs4 import BeautifulSoup

    flat = " ".join(BeautifulSoup(text, "html.parser").get_text(" ").split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _book_entry(token, item: LibraryItem) -> str:
    base = _base(token)
    title = item.title or os.path.basename(item.file_path or "")
    parts = [
        "<entry>",
        f"<title>{escape(title)}</title>",
        f"<id>urn:colophon:book:{escape(item.book_uid or str(item.id))}</id>",
        f"<updated>{_ts(item.updated_at)}</updated>",
    ]
    if item.author:
        # One <author>: CrossPoint keeps the last <name> it sees, and the
        # filename it saves under is built from it (kosync_documents).
        parts.append(f"<author><name>{escape(item.author)}</name></author>")
    if item.language:
        parts.append(f"<dc:language>{escape(item.language)}</dc:language>")
    if item.series:
        series = item.series + (f" #{item.series_index}" if item.series_index else "")
        parts.append(f"<category term={quoteattr(series)} label={quoteattr(series)}/>")
    summary = _plain(item.description)
    if summary:
        parts.append(f"<summary>{escape(summary)}</summary>")
    parts.append(
        f"<link rel=\"http://opds-spec.org/acquisition/open-access\" "
        f"type=\"application/epub+zip\" href={quoteattr(f'{base}/book/{item.id}.epub')}/>"
    )
    if item.cover_path:
        cover = quoteattr(f"{base}/cover/{item.id}.jpg")
        parts.append(f"<link rel=\"http://opds-spec.org/image\" type=\"image/jpeg\" href={cover}/>")
        parts.append(
            f"<link rel=\"http://opds-spec.org/image/thumbnail\" type=\"image/jpeg\" href={cover}/>"
        )
    parts.append("</entry>")
    return "".join(parts)


def _page() -> int:
    try:
        return max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        return 1


def _paged_books(token, feed_id, title, query):
    page = _page()
    rows = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE + 1).all()
    next_url = None
    if len(rows) > PAGE_SIZE:
        rows = rows[:PAGE_SIZE]
        args = dict(request.args)
        args["page"] = str(page + 1)
        next_url = request.base_url + "?" + "&".join(
            f"{quote(k)}={quote(v)}" for k, v in args.items()
        )
    return _feed(token, f"{feed_id}:{page}", title, _ACQ,
                 [_book_entry(token, item) for item in rows], next_url)


def _paged_names(token, feed_id, title, names, link_for):
    page = _page()
    chunk = names[(page - 1) * PAGE_SIZE: page * PAGE_SIZE + 1]
    next_url = None
    if len(chunk) > PAGE_SIZE:
        chunk = chunk[:PAGE_SIZE]
        next_url = f"{request.base_url}?page={page + 1}"
    entries = [
        _nav_entry(f"{feed_id}:{name}", name, link_for(name),
                   _("%(n)d books", n=count))
        for name, count in chunk
    ]
    return _feed(token, f"{feed_id}:{page}", title, _NAV, entries, next_url)


# ---------------------------------------------------------------------------
# Feeds
# ---------------------------------------------------------------------------

@opds_bp.route("/<token>/")
@opds_bp.route("/<token>")
@require_reader
def root(device, token):
    base = _base(token)
    entries = [
        _nav_entry("reading", _("Reading now"), f"{base}/reading",
                   _("Books you have started, most recent first")),
        _nav_entry("new", _("Recently added"), f"{base}/new"),
        _nav_entry("all", _("All books"), f"{base}/all", _("By title")),
        _nav_entry("authors", _("Authors"), f"{base}/authors", kind=_NAV),
        _nav_entry("series", _("Book series"), f"{base}/series", kind=_NAV),
    ]
    return _feed(token, "root", "Colophon", _NAV, entries)


@opds_bp.route("/<token>/reading")
@require_reader
def reading(device, token):
    query = _books().filter(LibraryItem.read_status == "Reading").order_by(
        LibraryItem.read_last_modified.desc()
    )
    return _paged_books(token, "reading", _("Reading now"), query)


@opds_bp.route("/<token>/new")
@require_reader
def new(device, token):
    query = _books().order_by(LibraryItem.created_at.desc(), LibraryItem.id.desc())
    return _paged_books(token, "new", _("Recently added"), query)


@opds_bp.route("/<token>/all")
@require_reader
def all_books(device, token):
    query = _books().order_by(func.lower(LibraryItem.title), LibraryItem.id)
    return _paged_books(token, "all", _("All books"), query)


@opds_bp.route("/<token>/search")
@require_reader
def search(device, token):
    q = (request.args.get("q") or "").strip()
    title = _("Search: %(q)s", q=q)
    if not q:
        return _feed(token, "search", title, _ACQ, [])
    like = f"%{q}%"
    query = _books().filter(or_(
        LibraryItem.title.ilike(like),
        LibraryItem.author.ilike(like),
        LibraryItem.series.ilike(like),
    )).order_by(func.lower(LibraryItem.title), LibraryItem.id)
    return _paged_books(token, f"search:{q}", title, query)


def _grouped(column):
    rows = (
        db.session.query(column, func.count(LibraryItem.id))
        .filter(LibraryItem.extension.in_(_EPUB_EXTENSIONS), column.isnot(None), column != "")
        .group_by(column)
        .all()
    )
    return sorted(rows, key=lambda row: row[0].casefold())


@opds_bp.route("/<token>/authors")
@require_reader
def authors(device, token):
    base = _base(token)
    return _paged_names(token, "authors", _("Authors"), _grouped(LibraryItem.author),
                        lambda name: f"{base}/author?name={quote(name)}")


@opds_bp.route("/<token>/author")
@require_reader
def author(device, token):
    name = request.args.get("name") or ""
    query = _books().filter(LibraryItem.author == name).order_by(
        func.lower(LibraryItem.series), LibraryItem.series_index, func.lower(LibraryItem.title)
    )
    return _paged_books(token, f"author:{name}", name, query)


@opds_bp.route("/<token>/series")
@require_reader
def series_list(device, token):
    base = _base(token)
    return _paged_names(token, "series", _("Book series"), _grouped(LibraryItem.series),
                        lambda name: f"{base}/series/books?name={quote(name)}")


@opds_bp.route("/<token>/series/books")
@require_reader
def series_books(device, token):
    name = request.args.get("name") or ""
    rows = _books().filter(LibraryItem.series == name).all()

    def order(item):
        try:
            return (0, float(item.series_index), item.title or "")
        except (TypeError, ValueError):
            return (1, 0.0, item.title or "")

    rows.sort(key=order)
    return _feed(token, f"series:{name}", name, _ACQ, [_book_entry(token, i) for i in rows])


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

@opds_bp.route("/<token>/book/<int:item_id>.epub")
@require_reader
def download(device, token, item_id):
    item = db.session.get(LibraryItem, item_id)
    if item is None or (item.extension or "").lower() not in _EPUB_EXTENSIONS:
        abort(404)
    if not item.file_path or not os.path.exists(item.file_path):
        logger.warning("OPDS download: file missing on disk: %s", item.file_path)
        abort(404)
    # Remember what the device now holds, so its KOSync hash resolves even
    # after the library's copy changes.
    if index_item(item):
        db.session.commit()
    logger.info("OPDS download: book_id=%s by %s", item.id, device.name)
    return send_file(
        item.file_path,
        mimetype="application/epub+zip",
        as_attachment=True,
        download_name=os.path.basename(item.file_path),
    )


@opds_bp.route("/<token>/cover/<int:item_id>.jpg")
@require_reader
def cover(device, token, item_id):
    from app.services.cover_thumbs import get_or_make_thumbnail

    item = db.session.get(LibraryItem, item_id)
    path = getattr(item, "cover_path", None) if item else None
    if path and not os.path.isabs(path):
        path = os.path.join(current_app.config["COVER_DIR"], path)
    if not path or not os.path.exists(path):
        abort(404)
    thumb = get_or_make_thumbnail(path, 320)
    return send_file(thumb or path, mimetype="image/jpeg")
