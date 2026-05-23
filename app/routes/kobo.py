# Colophon – e-book metadata manager
"""Kobo sync endpoints.

A Kobo e-reader whose ``api_endpoint`` config has been pointed at
``http://<colophon-host>/kobo/<token>/`` calls these routes as if
Colophon were the Kobo store. Phase 1 returns every EPUB in the
library as a "new entitlement" on every sync (no delta yet); the
Kobo dedupes by RevisionId.

Protocol shape borrowed from gotson/komga (MIT-licensed) — see
THIRD_PARTY_LICENSES.md. No code copied; DTOs rebuilt in Python.
"""
import logging
import os
import uuid
from datetime import datetime, timezone
from functools import wraps

import requests
from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    jsonify,
    request,
    send_file,
    stream_with_context,
    url_for,
)
from sqlalchemy import or_

from app.models import LibraryItem
from app.services.kobo_auth import find_device_by_token, touch_device
from app.services.kobo_kepub import convert_epub_to_kepub
from app.services.kobo_sync import (
    SyncToken,
    compute_delta,
    forget_items,
    record_sync,
)

logger = logging.getLogger(__name__)

kobo_bp = Blueprint("kobo", __name__, url_prefix="/kobo")

KOBO_STORE_BASE = "https://storeapi.kobo.com"
EPUB_EXTENSIONS = (".epub", ".kepub", ".kepub.epub")

# Deterministic namespace for translating Colophon LibraryItem IDs into
# the UUIDs the Kobo protocol expects. Keep stable forever — changing
# it would cause every Kobo to re-download every book.
_KOBO_UUID_NAMESPACE = uuid.UUID("4c0fb9b1-2b3b-4a1f-9a8d-0c8b6c1a2b3a")


def _book_uuid(item_id: int) -> str:
    return str(uuid.uuid5(_KOBO_UUID_NAMESPACE, f"book-{item_id}"))


def _iso(dt: datetime | None) -> str:
    if dt is None:
        dt = datetime.utcnow()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def require_device(f):
    """Decorator: resolve <token> path param to a KoboDevice or 401."""
    @wraps(f)
    def wrapper(token, *args, **kwargs):
        device = find_device_by_token(token)
        if device is None:
            logger.info("Kobo auth failed for token prefix %s...", token[:8])
            return jsonify({"error": "unauthorized"}), 401
        touch_device(device)
        return f(device, *args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Basic device handshake
# ---------------------------------------------------------------------------

@kobo_bp.route("/<token>/ping")
def ping(token):
    """First request a Kobo makes — must respond quickly so the device
    treats the endpoint as reachable."""
    device = find_device_by_token(token)
    if device is None:
        return ("unauthorized", 401)
    touch_device(device)
    return "pong"


@kobo_bp.route("/<token>/v1/initialization")
@require_device
def initialization(device):
    """Returns a map of named resource URLs. The Kobo uses this to
    decide which endpoint to call for each operation. Anything we
    don't override falls back to the real Kobo store via the
    catch-all proxy."""
    base = request.host_url.rstrip("/")
    token = _token_from_path()
    if not token:
        return jsonify({"error": "bad_request"}), 400
    prefix = f"{base}/kobo/{token}"

    resources = {
        "account_page": f"{KOBO_STORE_BASE}/account",
        "account_page_rakuten": f"{KOBO_STORE_BASE}/account",
        "add_entitlement": f"{prefix}/v1/library/{{RevisionIds}}",
        "affiliaterequest": f"{KOBO_STORE_BASE}/v1/affiliate",
        "audiobook_subscription_orange_deal_inclusion_url": f"{KOBO_STORE_BASE}/v1/audiobook_subscription_orange_deal_inclusion_url",
        "authorproduct_recommendations": f"{KOBO_STORE_BASE}/v1/products/books/authors/recommendations",
        "autocomplete": f"{KOBO_STORE_BASE}/v1/products/autocomplete",
        "blackstone_header": {"key": "x-amz-request-payer", "value": "requester"},
        "book": f"{KOBO_STORE_BASE}/v1/products/books/{{ProductId}}",
        "book_detail_page": f"{KOBO_STORE_BASE}/en/ebook/{{slug}}",
        "book_landing_page": f"{KOBO_STORE_BASE}/ebooks",
        "book_subscription": f"{KOBO_STORE_BASE}/v1/products/books/subscriptions",
        "categories_page": f"{KOBO_STORE_BASE}/ebooks/categories",
        "checkout_borrowed_book": f"{KOBO_STORE_BASE}/v1/library/borrow",
        "configuration_data": f"{KOBO_STORE_BASE}/v1/configuration",
        "content_access_book": f"{prefix}/v1/products/books/{{ProductId}}/access",
        "customer_care_live_chat": f"{KOBO_STORE_BASE}/livechat",
        "daily_deal": f"{KOBO_STORE_BASE}/v1/products/dailydeal",
        "deals": f"{KOBO_STORE_BASE}/v1/deals",
        "delete_tag": f"{prefix}/v1/library/tags/{{TagId}}",
        "delete_tag_items": f"{prefix}/v1/library/tags/{{TagId}}/items/delete",
        "device_auth": f"{prefix}/v1/auth/device",
        "device_refresh": f"{prefix}/v1/auth/refresh",
        "dictionary_host": f"{KOBO_STORE_BASE}",
        "discovery_host": f"{KOBO_STORE_BASE}",
        "eula_page": f"{KOBO_STORE_BASE}/termsofuse",
        "exchange_auth": f"{prefix}/v1/auth/exchange",
        "external_book": f"{KOBO_STORE_BASE}/v1/products/books/external/{{Ids}}",
        "facebook_sso_page": f"{KOBO_STORE_BASE}/v1/auth/fb",
        "featured_list": f"{KOBO_STORE_BASE}/v1/products/featured/{{FeaturedListId}}",
        "featured_lists": f"{KOBO_STORE_BASE}/v1/products/featured",
        "free_books_page": {
            "EN": f"{KOBO_STORE_BASE}/p/free-ebooks",
            "FR": f"{KOBO_STORE_BASE}/fr/p/livres-gratuits",
            "IT": f"{KOBO_STORE_BASE}/it/p/libri-gratis",
            "NL": f"{KOBO_STORE_BASE}/nl/p/gratis-ebooks",
            "PT": f"{KOBO_STORE_BASE}/pt/p/livros-gratis",
            "default": f"{KOBO_STORE_BASE}/p/free-ebooks",
        },
        "fte_feedback": f"{KOBO_STORE_BASE}/v1/products/ftefeedback",
        "get_tests_request": f"{KOBO_STORE_BASE}/v1/analytics/gettests",
        "giftcard_epd_redeem_url": f"{KOBO_STORE_BASE}/giftcard/redeem",
        "giftcard_redeem_url": f"{KOBO_STORE_BASE}/giftcard/redeem",
        "image_host": base,
        "image_url_quality_template": f"{base}/kobo/{token}/v1/books/{{ImageId}}/thumbnail/{{Width}}/{{Height}}/{{Quality}}/{{IsGreyscale}}/image.jpg",
        "image_url_template": f"{base}/kobo/{token}/v1/books/{{ImageId}}/thumbnail/{{Width}}/{{Height}}/{{IsGreyscale}}/image.jpg",
        "kobo_audiobooks_enabled": "False",
        "kobo_audiobooks_orange_deal_enabled": "False",
        "kobo_audiobooks_subscriptions_enabled": "False",
        "kobo_nativeborrow_enabled": "True",
        "kobo_onestorelibrary_enabled": "False",
        "kobo_redeem_enabled": "True",
        "kobo_shelfie_enabled": "False",
        "kobo_subscriptions_enabled": "False",
        "kobo_superpoints_enabled": "False",
        "kobo_wishlist_enabled": "True",
        "library_book": f"{prefix}/v1/library/{{LibraryItemId}}",
        "library_items": f"{prefix}/v1/library",
        "library_metadata": f"{prefix}/v1/library/{{Ids}}/metadata",
        "library_prices": f"{prefix}/v1/user/library/previews/prices",
        "library_stats": f"{prefix}/v1/library/stats",
        "library_sync": f"{prefix}/v1/library/sync",
        "love_dashboard_page": f"{KOBO_STORE_BASE}/kobosuperpoints",
        "love_points_redemption_page": f"{KOBO_STORE_BASE}/kobosuperpoints/redeem",
        "magazine_landing_page": f"{KOBO_STORE_BASE}/emagazines",
        "notifications_registration_issue": f"{KOBO_STORE_BASE}/v1/notifications/registration",
        "oauth_host": f"{KOBO_STORE_BASE}",
        "overdrive_account": f"{KOBO_STORE_BASE}/v1/overdrive/account",
        "overdrive_library": f"{KOBO_STORE_BASE}/v1/overdrive/library",
        "overdrive_library_finder": f"{KOBO_STORE_BASE}/v1/overdrive/library/finder",
        "overdrive_thirdparty": f"{KOBO_STORE_BASE}/v1/overdrive/thirdparty",
        "password_retrieval_page": f"{KOBO_STORE_BASE}/passwordretrieval.html",
        "personalizedrecommendations": f"{KOBO_STORE_BASE}/v1/products/personalizedrecommendations",
        "pluscatalog_page": f"{KOBO_STORE_BASE}/pluscatalog",
        "post_analytics_event": f"{KOBO_STORE_BASE}/v1/analytics/event",
        "privacy_page": f"{KOBO_STORE_BASE}/privacypolicy",
        "product_nextread": f"{KOBO_STORE_BASE}/v1/products/{{ProductIds}}/nextread",
        "product_prices": f"{KOBO_STORE_BASE}/v1/products/{{ProductIds}}/prices",
        "product_recommendations": f"{KOBO_STORE_BASE}/v1/products/{{ProductId}}/recommendations",
        "product_reviews": f"{KOBO_STORE_BASE}/v1/products/{{ProductIds}}/reviews",
        "products": f"{KOBO_STORE_BASE}/v1/products",
        "provider_external_sign_in_page": f"{KOBO_STORE_BASE}/v1/auth/{{providerName}}",
        "purchase_buy": f"{KOBO_STORE_BASE}/v1/store/purchase/buy",
        "purchase_buy_templated": f"{KOBO_STORE_BASE}/v1/store/purchase/{{CountryName}}/{{CurrencyCode}}/{{PaymentProvider}}/{{ShouldAddBookToLibrary}}",
        "rating": f"{KOBO_STORE_BASE}/v1/products/{{ProductId}}/rating/{{Rating}}",
        "reading_state": f"{prefix}/v1/library/{{EntitlementIds}}/state",
        "redeem_interstitial_page": f"{KOBO_STORE_BASE}/redeeminterstitial",
        "register_book": f"{KOBO_STORE_BASE}/v1/user/loyalty/benefits",
        "related_items": f"{KOBO_STORE_BASE}/v1/products/{{Id}}/related",
        "remaining_book_series": f"{KOBO_STORE_BASE}/v1/products/books/series/{{SeriesId}}",
        "rename_tag": f"{prefix}/v1/library/tags/{{TagId}}",
        "review": f"{KOBO_STORE_BASE}/v1/products/reviews/{{ReviewId}}",
        "review_sentiment": f"{KOBO_STORE_BASE}/v1/products/reviews/{{ReviewId}}/sentiment/{{Sentiment}}",
        "shelfie_recommendations": f"{KOBO_STORE_BASE}/v1/user/recommendations/shelfie",
        "sign_in_page": f"{KOBO_STORE_BASE}/auth/signin",
        "social_authorization_host": f"{KOBO_STORE_BASE}:443",
        "social_host": f"{KOBO_STORE_BASE}",
        "stacks_host_productId": f"{KOBO_STORE_BASE}/v1/products/{{ProductId}}/stacks",
        "store_home": f"{KOBO_STORE_BASE}/",
        "store_top_banner": f"{KOBO_STORE_BASE}/store/v1/assets/topbanner",
        "subs_landing_page": f"{KOBO_STORE_BASE}/ebooks/series",
        "tag_items": f"{prefix}/v1/library/tags/{{TagId}}/items",
        "tags": f"{prefix}/v1/library/tags",
        "taste_profile": f"{KOBO_STORE_BASE}/v1/products/tasteprofile",
        "update_accessibility_to_preview": f"{prefix}/v1/library/{{EntitlementIds}}/preview",
        "use_one_store": "False",
        "user_loyalty_benefits": f"{KOBO_STORE_BASE}/v1/user/loyalty/benefits",
        "user_platform": f"{KOBO_STORE_BASE}/v1/user/platform",
        "user_profile": f"{KOBO_STORE_BASE}/v1/user/profile",
        "user_ratings": f"{KOBO_STORE_BASE}/v1/user/ratings",
        "user_recommendations": f"{KOBO_STORE_BASE}/v1/user/recommendations",
        "user_reviews": f"{KOBO_STORE_BASE}/v1/user/reviews",
        "user_wishlist": f"{KOBO_STORE_BASE}/v1/user/wishlist",
        "userproduct_reviews": f"{KOBO_STORE_BASE}/v1/products/{{ProductIds}}/reviews/user",
        "wishlist_page": f"{KOBO_STORE_BASE}/account/wishlist",
    }

    return jsonify({"Resources": resources})


def _token_from_path() -> str | None:
    """Extract the token from /kobo/<token>/... — used from inside
    routes after auth has already passed."""
    parts = request.path.split("/", 3)
    return parts[2] if len(parts) >= 3 else None


@kobo_bp.route("/<token>/v1/affiliate")
@require_device
def affiliate(device):
    """Stub for the Kobo affiliate/referral endpoint. The real Kobo
    store returns affiliate tracking data here; if we let the catch-all
    proxy forward to storeapi.kobo.com without proper signing it
    answers 400, and the device then loops on affiliate forever and
    never moves on to /v1/auth/device or /v1/library/sync. Returning a
    minimal 200 lets it proceed."""
    return jsonify({"Name": "Kobo"})


@kobo_bp.route("/<token>/v1/auth/device", methods=["POST"])
@require_device
def auth_device(device):
    """Token refresh handshake. The Kobo sends its DeviceId etc;
    we just return synthetic tokens. Real auth is by URL-path-key."""
    return jsonify({
        "AccessToken": "colophon-stub-access-token",
        "RefreshToken": "colophon-stub-refresh-token",
        "TokenType": "Bearer",
        "TrackingId": str(uuid.uuid4()),
        "UserKey": f"device-{device.id}",
    })


@kobo_bp.route("/<token>/v1/auth/refresh", methods=["POST"])
@require_device
def auth_refresh(device):
    return jsonify({
        "AccessToken": "colophon-stub-access-token",
        "RefreshToken": "colophon-stub-refresh-token",
        "TokenType": "Bearer",
        "TrackingId": str(uuid.uuid4()),
        "UserKey": f"device-{device.id}",
    })


# ---------------------------------------------------------------------------
# Library sync — the heart of Phase 1
# ---------------------------------------------------------------------------

def _epub_items_query():
    """All LibraryItems whose file extension is an EPUB variant.
    Extensions are stored lowercased and with leading dot by the scanner."""
    patterns = list(EPUB_EXTENSIONS) + [ext.lstrip(".") for ext in EPUB_EXTENSIONS]
    return LibraryItem.query.filter(
        or_(*[LibraryItem.extension == ext for ext in patterns])
    )


def _entitlement_dtos(item: LibraryItem, base_url: str, token: str) -> dict:
    """Build a NewEntitlement wrapper for one LibraryItem."""
    book_uuid = _book_uuid(item.id)
    last_modified = _iso(item.updated_at)
    created = _iso(item.created_at)
    download_url = f"{base_url}/kobo/{token}/v1/books/{item.id}/file/epub"

    contributors = []
    contributor_roles = []
    if item.author:
        for name in [a.strip() for a in item.author.split(",") if a.strip()]:
            contributors.append(name)
            contributor_roles.append({"Name": name, "Role": "Author"})

    series_obj = None
    if item.series:
        series_obj = {
            "Name": item.series,
            "Number": _series_number_float(item.series_index),
            "NumberFloat": _series_number_float(item.series_index),
            "Id": str(uuid.uuid5(_KOBO_UUID_NAMESPACE, f"series-{item.series}")),
        }

    book_entitlement = {
        "Accessibility": "Full",
        "ActivePeriod": {"From": created},
        "Created": created,
        "CrossRevisionId": book_uuid,
        "Id": book_uuid,
        "IsHiddenFromArchive": False,
        "IsLocked": False,
        "IsRemoved": False,
        "LastModified": last_modified,
        "OriginCategory": "Imported",
        "RevisionId": book_uuid,
        "Status": "Active",
    }

    book_metadata = {
        "Categories": ["00000000-0000-0000-0000-000000000001"],
        "Contributors": contributors,
        "ContributorRoles": contributor_roles,
        "CoverImageId": book_uuid,
        "CrossRevisionId": book_uuid,
        "CurrentDisplayPrice": {"CurrencyCode": "USD", "TotalAmount": 0},
        "CurrentLoveDisplayPrice": {"TotalAmount": 0},
        "Description": item.description or "",
        "DownloadUrls": [
            {
                "Format": "KEPUB",
                "Url": download_url,
                "Size": item.size_bytes or 0,
                "Platform": "Android",
                "DrmType": "None",
            }
        ],
        "EntitlementId": book_uuid,
        "ExternalIds": [],
        "Genre": "00000000-0000-0000-0000-000000000001",
        "IsEligibleForKoboLove": False,
        "IsInternetArchived": False,
        "IsPreOrder": False,
        "IsSocialEnabled": True,
        "Language": item.language or "en",
        "PhoneticPronunciations": {},
        "PublicationDate": item.published_date or created[:10],
        "Publisher": {"Imprint": "", "Name": item.publisher or "Colophon"},
        "RevisionId": book_uuid,
        "Title": item.title or item.file_name or "Untitled",
        "WorkId": book_uuid,
    }
    if series_obj:
        book_metadata["Series"] = series_obj

    reading_state = {
        "Created": created,
        "CurrentBookmark": {
            "Location": None,
            "ProgressPercent": None,
            "ContentSourceProgressPercent": None,
        },
        "EntitlementId": book_uuid,
        "LastModified": last_modified,
        "PriorityTimestamp": last_modified,
        "StatusInfo": {
            "LastModified": last_modified,
            "Status": "ReadyToRead",
        },
        "Statistics": {
            "LastModified": last_modified,
            "SpentReadingMinutes": None,
            "RemainingTimeMinutes": None,
        },
    }

    full = {
        "BookEntitlement": book_entitlement,
        "BookMetadata": book_metadata,
        "ReadingState": reading_state,
    }
    return full


def _new_entitlement_wrapper(item: LibraryItem, base_url: str, token: str) -> dict:
    return {"NewEntitlement": {"NewEntitlement": _entitlement_dtos(item, base_url, token)}}


def _changed_entitlement_wrapper(item: LibraryItem, base_url: str, token: str) -> dict:
    return {
        "ChangedEntitlement": {"ChangedEntitlement": _entitlement_dtos(item, base_url, token)}
    }


def _deleted_entitlement_wrapper(library_item_id: int) -> dict:
    """The Kobo expects a minimal BookEntitlement for deletions."""
    book_uuid = _book_uuid(library_item_id)
    now = _iso(None)
    return {
        "DeletedEntitlement": {
            "DeletedEntitlement": {
                "Accessibility": "Full",
                "ActivePeriod": {"From": now},
                "Created": now,
                "CrossRevisionId": book_uuid,
                "Id": book_uuid,
                "IsHiddenFromArchive": True,
                "IsLocked": False,
                "IsRemoved": True,
                "LastModified": now,
                "OriginCategory": "Imported",
                "RevisionId": book_uuid,
                "Status": "Active",
            }
        }
    }


def _series_number_float(value):
    if not value:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@kobo_bp.route("/<token>/v1/library/sync")
@require_device
def library_sync(device):
    """Phase 2: delta sync.

    The Kobo sends back the ``x-kobo-synctoken`` we issued on the
    previous response. We return only items whose ``updated_at`` is
    newer, paginated at SYNC_PAGE_SIZE per request. Books that
    disappeared from the library since the device last saw them are
    sent as DeletedEntitlement on the first page of the run.
    """
    touch_device(device, mark_sync=True)

    base_url = request.host_url.rstrip("/")
    token = _token_from_path()

    incoming = SyncToken.parse(request.headers.get("x-kobo-synctoken"))
    # Read SYNC_PAGE_SIZE at request time (not at function-def time) so
    # tests can monkeypatch it via the module attribute.
    from app.services import kobo_sync as _kobo_sync
    delta = compute_delta(
        device.id, incoming, _epub_items_query, page_size=_kobo_sync.SYNC_PAGE_SIZE
    )

    payload = (
        [_new_entitlement_wrapper(item, base_url, token) for item in delta.new_items]
        + [_changed_entitlement_wrapper(item, base_url, token) for item in delta.changed_items]
        + [_deleted_entitlement_wrapper(item_id) for item_id in delta.deleted_item_ids]
    )

    # Persist what we just sent so the next sync knows
    record_sync(device.id, delta.new_items + delta.changed_items, _book_uuid)
    forget_items(device.id, delta.deleted_item_ids)

    logger.info(
        "Kobo sync: device=%s new=%d changed=%d deleted=%d more=%s",
        device.name,
        len(delta.new_items),
        len(delta.changed_items),
        len(delta.deleted_item_ids),
        delta.has_more,
    )

    response = jsonify(payload)
    response.headers["x-kobo-sync"] = "continue" if delta.has_more else "done"
    response.headers["x-kobo-synctoken"] = delta.next_token.encode()
    response.headers["x-kobo-apitoken"] = "e30="  # base64("{}") — placeholder
    return response


@kobo_bp.route("/<token>/v1/library/<book_id>/metadata")
@require_device
def library_metadata(device, book_id):
    """Returns fresh download URL for a single book (called by the
    device just before download)."""
    item = LibraryItem.query.get(book_id)
    if item is None:
        return jsonify({"error": "not_found"}), 404
    base_url = request.host_url.rstrip("/")
    token = _token_from_path()
    full = _entitlement_dtos(item, base_url, token)
    return jsonify([full["BookMetadata"]])


# ---------------------------------------------------------------------------
# Book file streaming
# ---------------------------------------------------------------------------

@kobo_bp.route("/<token>/v1/books/<int:book_id>/file/epub")
@require_device
def book_file(device, book_id):
    """Stream the book to the Kobo, converted to KEPUB if kepubify
    is available (better reading-position tracking on-device).
    Falls back to raw EPUB if conversion is unavailable or fails."""
    item = LibraryItem.query.get(book_id)
    if item is None or not item.file_path:
        abort(404)
    if not os.path.exists(item.file_path):
        logger.warning("Kobo download: file missing on disk: %s", item.file_path)
        abort(404)

    # Already a .kepub.epub? Serve as-is.
    ext = (item.extension or "").lower()
    if ext in (".kepub", ".kepub.epub"):
        return send_file(
            item.file_path,
            mimetype="application/epub+zip",
            as_attachment=True,
            download_name=os.path.basename(item.file_path),
        )

    kepub_path = convert_epub_to_kepub(item.id, item.file_path)
    if kepub_path and os.path.exists(kepub_path):
        download_name = os.path.basename(item.file_path).rsplit(".", 1)[0] + ".kepub.epub"
        return send_file(
            kepub_path,
            mimetype="application/epub+zip",
            as_attachment=True,
            download_name=download_name,
        )

    # Fallback: raw EPUB. The Kobo accepts it (position tracking degraded).
    logger.info("Kobo download: kepubify unavailable, serving raw EPUB for book %d", item.id)
    return send_file(
        item.file_path,
        mimetype="application/epub+zip",
        as_attachment=True,
        download_name=os.path.basename(item.file_path),
    )


# ---------------------------------------------------------------------------
# Cover thumbnails
# ---------------------------------------------------------------------------

@kobo_bp.route("/<token>/v1/books/<book_id>/thumbnail/<int:width>/<int:height>/<is_grey>/image.jpg")
@kobo_bp.route("/<token>/v1/books/<book_id>/thumbnail/<int:width>/<int:height>/<int:quality>/<is_grey>/image.jpg")
@require_device
def book_thumbnail(device, book_id, width, height, is_grey, quality=85):
    """Serve the existing cover image. We ignore the requested
    width/height/quality and let the Kobo scale — keeps Phase 1
    free of image-processing dependencies."""
    item = _find_item_by_uuid(book_id)
    if item is None or not item.cover_path or not os.path.exists(item.cover_path):
        abort(404)
    return send_file(item.cover_path, mimetype="image/jpeg")


def _find_item_by_uuid(image_id: str) -> LibraryItem | None:
    """Image IDs in the protocol are the UUIDs we minted in _book_uuid.
    Reverse the lookup by scanning candidates. Cheap for small libraries
    (hundreds of books); Phase 2 can add a uuid→id cache table if needed."""
    # Try integer first (some Kobo paths still use raw IDs)
    if image_id.isdigit():
        item = LibraryItem.query.get(int(image_id))
        if item:
            return item
    # Otherwise reverse-lookup by computing UUIDs of all EPUBs and
    # comparing. With <10k books this is microseconds; not worth caching.
    for item in _epub_items_query().all():
        if _book_uuid(item.id) == image_id:
            return item
    return None


# ---------------------------------------------------------------------------
# Catch-all proxy to the real Kobo store
# ---------------------------------------------------------------------------

# Headers we don't forward back from the upstream response
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-encoding",
    "content-length",
}


@kobo_bp.route(
    "/<token>/<path:rest>",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
@require_device
def store_proxy(device, rest):
    """Forward anything we don't explicitly handle to the real Kobo
    store. The user's token is stripped before forwarding so it
    never leaks to Kobo."""
    upstream_url = f"{KOBO_STORE_BASE}/{rest}"

    # Forward all headers except Host and our auth token. The token
    # was already consumed by @require_device; we don't pass it on.
    fwd_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in {"host", "content-length"}
    }

    try:
        upstream = requests.request(
            method=request.method,
            url=upstream_url,
            params=request.args,
            headers=fwd_headers,
            data=request.get_data(),
            allow_redirects=False,
            stream=True,
            timeout=30,
        )
    except requests.RequestException as exc:
        logger.warning("Kobo proxy: upstream failure for %s: %s", rest, exc)
        return jsonify({"error": "upstream_unavailable"}), 502

    resp_headers = [
        (k, v) for k, v in upstream.raw.headers.items()
        if k.lower() not in _HOP_BY_HOP
    ]
    return Response(
        stream_with_context(upstream.iter_content(chunk_size=8192)),
        status=upstream.status_code,
        headers=resp_headers,
    )
