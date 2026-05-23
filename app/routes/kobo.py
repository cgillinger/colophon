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

from flask import (
    Blueprint,
    abort,
    jsonify,
    request,
    send_file,
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
    decide which endpoint to call for each operation.

    We require an Authorization: Bearer header here. Without it we
    return 401, which is what Komga does. The 401 forces the device
    to POST /v1/auth/device first to obtain a bearer token, and only
    then retry initialization. Without that ordering, the device
    happily takes our Resources map and starts calling URLs that
    happen to still point at storeapi.kobo.com (autocomplete,
    user_profile, configuration_data, ...) — those calls fail because
    we've hijacked the device's api_endpoint, and the device loops on
    affiliate -> initialization forever.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "unauthorized"}), 401

    # The Kobo Libra Color empirically sends `Host: 192.168.50.8`
    # without the port even when api_endpoint has :5055, so
    # request.host_url comes back without the port and our image
    # URLs in the conf end up pointing at port 80. Prefer an explicit
    # COLOPHON_PUBLIC_URL when configured (e.g. set in
    # docker-compose.yml) so the URLs survive Kobo's Host-header
    # mangling.
    base = os.environ.get("COLOPHON_PUBLIC_URL", "").rstrip("/") or request.host_url.rstrip("/")
    token = _token_from_path()
    if not token:
        return jsonify({"error": "bad_request"}), 400
    prefix = f"{base}/kobo/{token}"

    # Strategy: mirror Komga's initialization response as closely as
    # possible. Empirically the device follows api_endpoint (i.e. our
    # prefix) for /v1/... calls regardless of what Resources says, so
    # most of these URLs are de-facto unused for the sync flow. But
    # the firmware does check for specific keys and feature flags;
    # missing entries or wrong values (e.g. use_one_store=False where
    # Komga has True) make the device bail out silently after init.
    # Override only the image-related keys to point at us; everything
    # else stays at the real Kobo hosts, matching Komga's working
    # response on this exact device.
    img_template = (
        f"{base}/kobo/{token}/v1/books/{{ImageId}}/thumbnail/"
        f"{{Width}}/{{Height}}/false/image.jpg"
    )
    img_quality_template = (
        f"{base}/kobo/{token}/v1/books/{{ImageId}}/thumbnail/"
        f"{{Width}}/{{Height}}/{{Quality}}/{{IsGreyscale}}/image.jpg"
    )

    resources = {
        "account_page": "https://www.kobo.com/account/settings",
        "account_page_rakuten": "https://my.rakuten.co.jp/",
        "add_device": "https://storeapi.kobo.com/v1/user/add-device",
        "add_entitlement": "https://storeapi.kobo.com/v1/library/{RevisionIds}",
        "affiliaterequest": "https://storeapi.kobo.com/v1/affiliate",
        "assets": "https://storeapi.kobo.com/v1/assets",
        "audiobook": "https://storeapi.kobo.com/v1/products/audiobooks/{ProductId}",
        "audiobook_detail_page": "https://www.kobo.com/{region}/{language}/audiobook/{slug}",
        "audiobook_get_credits": "https://www.kobo.com/{region}/{language}/audiobooks/plans",
        "audiobook_landing_page": "https://www.kobo.com/{region}/{language}/audiobooks",
        "audiobook_preview": "https://storeapi.kobo.com/v1/products/audiobooks/{Id}/preview",
        "audiobook_purchase_withcredit": "https://storeapi.kobo.com/v1/store/audiobook/{Id}",
        "audiobook_subscription_management": "https://www.kobo.com/{region}/{language}/account/subscriptions",
        "audiobook_subscription_orange_deal_inclusion_url": "https://authorize.kobo.com/inclusion",
        "audiobook_subscription_purchase": "https://www.kobo.com/{region}/{language}/checkoutoption/21C6D938-934B-4A91-B979-E14D70B2F280",
        "audiobook_subscription_tiers": "https://www.kobo.com/{region}/{language}/checkoutoption/21C6D938-934B-4A91-B979-E14D70B2F280",
        "authorproduct_recommendations": "https://storeapi.kobo.com/v1/products/books/authors/recommendations",
        "autocomplete": "https://storeapi.kobo.com/v1/products/autocomplete",
        "bam": "https://storeapi.kobo.com/v2/activity/bam/success",
        "blackstone_header": {"key": "x-amz-request-payer", "value": "requester"},
        "book": "https://storeapi.kobo.com/v1/products/books/{ProductId}",
        "book_detail_page": "https://www.kobo.com/{region}/{language}/ebook/{slug}",
        "book_detail_page_rakuten": "http://books.rakuten.co.jp/rk/{crossrevisionid}",
        "book_landing_page": "https://www.kobo.com/ebooks",
        "book_subscription": "https://storeapi.kobo.com/v1/products/books/subscriptions",
        "browse_history": "https://storeapi.kobo.com/v1/user/browsehistory",
        "categories": "https://storeapi.kobo.com/v1/categories",
        "categories_page": "https://www.kobo.com/ebooks/categories",
        "categoriesv2": "https://storeapi.kobo.com/api/v2/Categories/Top",
        "category": "https://storeapi.kobo.com/v1/categories/{CategoryId}",
        "category_featured_lists": "https://storeapi.kobo.com/v1/categories/{CategoryId}/featured",
        "category_products": "https://storeapi.kobo.com/v1/categories/{CategoryId}/products",
        "checkout_borrowed_book": "https://storeapi.kobo.com/v1/library/borrow",
        "client_authd_referral": "https://authorize.kobo.com/api/AuthenticatedReferral/client/v1/getLink",
        "configuration_data": "https://storeapi.kobo.com/v1/configuration",
        "content_access_book": "https://storeapi.kobo.com/v1/products/books/{ProductId}/access",
        "contributorsv2": "https://storeapi.kobo.com/v2/contributors/author",
        "customer_care_live_chat": "https://v2.zopim.com/widget/livechat.html?key=Y6gwUmnu4OATxN3Tli4Av9bYN319BTdO",
        "daily_deal": "https://storeapi.kobo.com/v1/products/dailydeal",
        "deals": "https://storeapi.kobo.com/v1/deals",
        "delete_entitlement": "https://storeapi.kobo.com/v1/library/{Ids}",
        "delete_tag": "https://storeapi.kobo.com/v1/library/tags/{TagId}",
        "delete_tag_items": "https://storeapi.kobo.com/v1/library/tags/{TagId}/items/delete",
        "device_auth": "https://storeapi.kobo.com/v1/auth/device",
        "device_refresh": "https://storeapi.kobo.com/v1/auth/refresh",
        "dictionary_host": "https://ereaderfiles.kobo.com",
        "discovery_host": "https://discovery.kobobooks.com",
        "display_accessibility_enabled": "False",
        "display_parental_controls_enabled": "True",
        "dropbox_link_account_poll": "https://authorize.kobo.com/{region}/{language}/LinkDropbox",
        "dropbox_link_account_start": "https://authorize.kobo.com/LinkDropbox/start",
        "ereaderdevices": "https://storeapi.kobo.com/v2/products/EReaderDeviceFeeds",
        "eula_page": "https://www.kobo.com/termsofuse?style=onestore",
        "exchange_auth": "https://storeapi.kobo.com/v1/auth/exchange",
        "external_book": "https://storeapi.kobo.com/v1/products/books/external/{Ids}",
        "facebook_sso_page": "https://authorize.kobo.com/signin/provider/Facebook/login?returnUrl=https://kobo.com/",
        "featured_list": "https://storeapi.kobo.com/v1/products/featured/{FeaturedListId}",
        "featured_lists": "https://storeapi.kobo.com/v1/products/featured",
        "featuredlist2": "https://storeapi.kobo.com/v2/products/list/featured",
        "fixed_layout_page_cache_enabled": "True",
        "free_books_page": {
            "EN": "https://www.kobo.com/{region}/{language}/p/free-ebooks",
            "FR": "https://www.kobo.com/{region}/{language}/p/livres-gratuits",
            "IT": "https://www.kobo.com/{region}/{language}/p/libri-gratuiti",
            "NL": "https://www.kobo.com/{region}/{language}/List/bekijk-het-overzicht-van-gratis-ebooks/QpkkVWnUw8sxmgjSlCbJRg",
            "PT": "https://www.kobo.com/{region}/{language}/p/livros-gratis",
        },
        "fte_feedback": "https://storeapi.kobo.com/v1/products/ftefeedback",
        "funnel_metrics": "https://storeapi.kobo.com/v1/funnelmetrics",
        "geography_data": "https://storeapi.kobo.com/v2/configuration/geography/country",
        "get_download_keys": "https://storeapi.kobo.com/v1/library/downloadkeys",
        "get_download_link": "https://storeapi.kobo.com/v1/library/downloadlink",
        "get_tests_request": "https://storeapi.kobo.com/v1/analytics/gettests",
        "giftcard_epd_redeem_url": "https://www.kobo.com/{storefront}/{language}/redeem-ereader",
        "giftcard_redeem_url": "https://www.kobo.com/{storefront}/{language}/redeem",
        "googledrive_link_account_start": "https://authorize.kobo.com/{region}/{language}/linkcloudstorage/provider/google_drive",
        "gpb_flow_enabled": "False",
        "help_page": "https://www.kobo.com/help",
        "image_host": base,
        "image_url_quality_template": img_quality_template,
        "image_url_template": img_template,
        "instapaper_enabled": "True",
        "instapaper_env_url": "https://www.instapaper.com/api/kobo",
        "instapaper_link_account_start": "https://authorize.kobo.com/{region}/{language}/linkinstapaper",
        "kobo_audiobooks_credit_redemption": "True",
        "kobo_audiobooks_enabled": "True",
        "kobo_audiobooks_orange_deal_enabled": "True",
        "kobo_audiobooks_subscriptions_enabled": "True",
        "kobo_display_price": "True",
        "kobo_dropbox_link_account_enabled": "True",
        "kobo_google_tax": "False",
        "kobo_googledrive_link_account_enabled": "True",
        "kobo_nativeborrow_enabled": "False",
        "kobo_onedrive_link_account_enabled": "False",
        "kobo_onestorelibrary_enabled": "False",
        "kobo_privacyCentre_url": "https://www.kobo.com/privacy",
        "kobo_redeem_enabled": "True",
        "kobo_shelfie_enabled": "False",
        "kobo_subscriptions_enabled": "True",
        "kobo_superpoints_enabled": "False",
        "kobo_wishlist_enabled": "True",
        "library_book": "https://storeapi.kobo.com/v1/user/library/books/{LibraryItemId}",
        "library_items": "https://storeapi.kobo.com/v1/user/library",
        "library_metadata": "https://storeapi.kobo.com/v1/library/{Ids}/metadata",
        "library_prices": "https://storeapi.kobo.com/v1/user/library/previews/prices",
        "library_search": "https://storeapi.kobo.com/v1/library/search",
        "library_sync": "https://storeapi.kobo.com/v1/library/sync",
        "love_dashboard_page": "https://www.kobo.com/{region}/{language}/kobosuperpoints",
        "love_points_redemption_page": "https://www.kobo.com/{region}/{language}/KoboSuperPointsRedemption?productId={ProductId}",
        "magazine_landing_page": "https://www.kobo.com/emagazines",
        "more_sign_in_options": "https://authorize.kobo.com/signin?returnUrl=https://kobo.com/#allProviders",
        "morebyauthor": "https://storeapi.kobo.com/v2/products/recommendations/morebyauthor",
        "notebooks": "https://storeapi.kobo.com/api/internal/notebooks",
        "notifications_registration_issue": "https://storeapi.kobo.com/v1/notifications/registration",
        "oauth_host": "https://oauth.kobo.com",
        "password_retrieval_page": "https://www.kobo.com/passwordretrieval.html",
        "personalizedrecommendations": "https://storeapi.kobo.com/v2/users/personalizedrecommendations",
        "pocket_link_account_start": "https://authorize.kobo.com/{region}/{language}/linkpocket",
        "post_analytics_event": "https://storeapi.kobo.com/v1/analytics/event",
        "ppx_purchasing_url": "https://purchasing.kobo.com",
        "privacy_page": "https://www.kobo.com/privacypolicy?style=onestore",
        "product_nextread": "https://storeapi.kobo.com/v1/products/{ProductIds}/nextread",
        "product_prices": "https://storeapi.kobo.com/v1/products/{ProductIds}/prices",
        "product_recommendations": "https://storeapi.kobo.com/v1/products/{ProductId}/recommendations",
        "product_reviews": "https://storeapi.kobo.com/v1/products/{ProductIds}/reviews",
        "productbyid": "https://storeapi.kobo.com/v2/products/itemDetailById/{ProductType}/{Id}",
        "productbyslug": "https://storeapi.kobo.com/v2/products/itemDetail/{ProductType}/{Slug}",
        "products": "https://storeapi.kobo.com/v1/products",
        "productstatebyid": "https://storeapi.kobo.com/v2/products/itemStateById/{ProductType}/{Id}",
        "productstatebyslug": "https://storeapi.kobo.com/v2/products/itemState/{ProductType}/{Slug}",
        "productsv2": "https://storeapi.kobo.com/v2/products",
        "provider_external_sign_in_page": "https://authorize.kobo.com/ExternalSignIn/{providerName}?returnUrl=https://kobo.com/",
        "purchase_buy": "https://www.kobo.com/checkoutoption/",
        "purchase_buy_templated": "https://www.kobo.com/{region}/{language}/checkoutoption/{ProductId}",
        "quickbuy_checkout": "https://storeapi.kobo.com/v1/store/quickbuy/{PurchaseId}/checkout",
        "quickbuy_create": "https://storeapi.kobo.com/v1/store/quickbuy/purchase",
        "rakuten_token_exchange": "https://storeapi.kobo.com/v1/auth/rakuten_token_exchange",
        "rating": "https://storeapi.kobo.com/v1/products/{ProductId}/rating/{Rating}",
        "reading_services_host": "https://readingservices.kobo.com",
        "reading_state": "https://storeapi.kobo.com/v1/library/{Ids}/state",
        "redeem_interstitial_page": "https://www.kobo.com",
        "reflowable_page_cache_enabled": "True",
        "registration_page": "https://authorize.kobo.com/signup?returnUrl=https://kobo.com/",
        "related": "https://storeapi.kobo.com/v2/products/recommendations/related",
        "related_items": "https://storeapi.kobo.com/v1/products/{Id}/related",
        "remaining_book_series": "https://storeapi.kobo.com/v1/products/books/series/{SeriesId}",
        "rename_tag": "https://storeapi.kobo.com/v1/library/tags/{TagId}",
        "review": "https://storeapi.kobo.com/v1/products/reviews/{ReviewId}",
        "review_sentiment": "https://storeapi.kobo.com/v1/products/reviews/{ReviewId}/sentiment/{Sentiment}",
        "shelfie_recommendations": "https://storeapi.kobo.com/v1/user/recommendations/shelfie",
        "sign_in_page": "https://auth.kobobooks.com/ActivateOnWeb",
        "social_authorization_host": "https://social.kobobooks.com:8443",
        "social_host": "https://social.kobobooks.com",
        "store_home": "[www.kobo.com/{region}/{language}](https://www.kobo.com/{region}/{language})",
        "store_host": "[www.kobo.com](https://www.kobo.com)",
        "store_newreleases": "https://www.kobo.com/{region}/{language}/List/new-releases/961XUjtsU0qxkFItWOutGA",
        "store_search": "https://www.kobo.com/{region}/{language}/Search?Query={query}",
        "store_top50": "https://www.kobo.com/{region}/{language}/ebooks/Top",
        "subs_landing_page": "https://www.kobo.com/{region}/{language}/plus",
        "subs_management_page": "https://www.kobo.com/{region}/{language}/account/subscriptions",
        "subs_purchase_buy_templated": "https://www.kobo.com/{region}/{language}/Checkoutoption/{ProductId}/{TierId}",
        "subscription_publisher_price_page": "https://www.kobo.com/{region}/{language}/subscriptionpublisherprice",
        "tag_items": "https://storeapi.kobo.com/v1/library/tags/{TagId}/Items",
        "tags": "https://storeapi.kobo.com/v1/library/tags",
        "taste_profile": "https://storeapi.kobo.com/v1/products/tasteprofile",
        "terms_of_sale_page": "https://authorize.kobo.com/{region}/{language}/terms/termsofsale",
        "topproducts": "https://storeapi.kobo.com/v2/products/list/topproducts",
        "tracking": "https://storeapi.kobo.com/v2/tracking/searchperformed",
        "update_accessibility_to_preview": "https://storeapi.kobo.com/v1/library/{EntitlementIds}/preview",
        "use_one_store": "True",
        "user_currencyconversion": "https://storeapi.kobo.com/v1/user/currency/convert",
        "user_loyalty_benefits": "https://storeapi.kobo.com/v1/user/loyalty/benefits",
        "user_platform": "https://storeapi.kobo.com/v1/user/platform",
        "user_profile": "https://storeapi.kobo.com/v1/user/profile",
        "user_ratings": "https://storeapi.kobo.com/v1/user/ratings",
        "user_recommendations": "https://storeapi.kobo.com/v1/user/recommendations",
        "user_reviews": "https://storeapi.kobo.com/v1/user/reviews",
        "user_tasteprofile_complete": "https://storeapi.kobo.com/v2/user/tasteprofile/complete",
        "user_tasteprofile_genre": "https://storeapi.kobo.com/v2/user/tasteprofile/genre",
        "user_wishlist": "https://storeapi.kobo.com/v1/user/wishlist",
        "userguide_host": "https://ereaderfiles.kobo.com",
        "wishlist_page": "https://www.kobo.com/{region}/{language}/account/wishlist",
    }
    # Suppress unused-variable warning for prefix; the mirror-Komga
    # strategy makes the device follow api_endpoint directly for all
    # /v1/ paths, so we don't need to splice prefix into Resources.
    del prefix

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
    from app.services.kobo_kepub import resolve_kepubify_path

    book_uuid = _book_uuid(item.id)
    last_modified = _iso(item.updated_at)
    created = _iso(item.created_at)
    download_url = f"{base_url}/kobo/{token}/v1/books/{item.id}/file/epub"

    # Kobo silently skips metadata updates when Description is null or
    # empty (per Komga's KoboDtoDao comment). Force at least a single
    # space so the device commits the row.
    description = (item.description or "").strip() or " "

    # Komga uses "KEPUB" when a kepubify binary is reachable, "EPUB3"
    # otherwise. We do the same — the actual conversion is handled
    # on-demand by book_file().
    download_format = "KEPUB" if resolve_kepubify_path() else "EPUB3"

    # PublicationDate must be a real ISO 8601 datetime with timezone;
    # the embedded item.published_date is often a year-only string or
    # missing entirely, so normalise to created when we can't trust it.
    published = item.published_date
    if not published or len(str(published)) < 10:
        publication_date = created
    else:
        # Pad year-only / date-only values out to a full timestamp.
        s = str(published)
        if len(s) == 4:
            publication_date = f"{s}-01-01T00:00:00.000Z"
        elif len(s) == 10:
            publication_date = f"{s}T00:00:00.000Z"
        else:
            publication_date = s

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
        "Description": description,
        "DownloadUrls": [
            {
                "Format": download_format,
                "Url": download_url,
                "Size": item.size_bytes or 0,
                "Platform": "Generic",
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
        "Language": (item.language or "en")[:2],
        "PhoneticPronunciations": {},
        "PublicationDate": publication_date,
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
            "LastModified": last_modified,
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
            "TimesStartedReading": 0,
        },
        "Statistics": {
            "LastModified": last_modified,
            "SpentReadingMinutes": 0,
            "RemainingTimeMinutes": 0,
        },
    }

    full = {
        "BookEntitlement": book_entitlement,
        "BookMetadata": book_metadata,
        "ReadingState": reading_state,
    }
    return full


def _new_entitlement_wrapper(item: LibraryItem, base_url: str, token: str) -> dict:
    return {"NewEntitlement": _entitlement_dtos(item, base_url, token)}


def _changed_entitlement_wrapper(item: LibraryItem, base_url: str, token: str) -> dict:
    return {"ChangedEntitlement": _entitlement_dtos(item, base_url, token)}


def _deleted_entitlement_wrapper(library_item_id: int) -> dict:
    """The Kobo expects a minimal BookEntitlement for deletions."""
    book_uuid = _book_uuid(library_item_id)
    now = _iso(None)
    return {
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
    device just before download). book_id is the UUID we minted at
    sync time, not the raw DB primary key — use the reverse lookup."""
    item = _find_item_by_uuid(book_id)
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
# Catch-all stub for unhandled Kobo endpoints
# ---------------------------------------------------------------------------

@kobo_bp.route(
    "/<token>/<path:rest>",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
@require_device
def store_proxy(device, rest):
    """Stub for any endpoint we don't explicitly handle.

    We used to forward to storeapi.kobo.com here, but the real store
    rejects unsigned requests with 4xx, which makes some firmwares
    treat the whole sync as broken and loop on affiliate+init forever.
    Returning an empty 200 instead lets the device move on. The user
    loses store browsing (which never worked over our proxy anyway)
    but sync works.

    Every fall-through is logged at WARNING so we can see which
    endpoints the device wants and add proper handlers for them.
    """
    logger.warning(
        "Kobo store_proxy fallthrough: %s %s args=%s",
        request.method, rest, dict(request.args),
    )
    return jsonify({}), 200
