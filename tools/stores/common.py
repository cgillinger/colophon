"""Gemensamma hjälpfunktioner för butikslogiken (Playwright, sessioner, scoring).

Delas av tools/bookstore_web_worker.py och tools/bookstore_downloader.py samt
butiksspecifika moduler i tools/stores/.
"""
import logging

logger = logging.getLogger(__name__)

import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


PROJECT_ROOT = Path(__file__).resolve().parents[2]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from app.paths import DOWNLOAD_ROOT, LIBRARY_ROOT, MYEBOOKFLOW_INPUT, PROFILE_ROOT
    from app.services.drm_skip_registry import record_skipped_drm
except Exception as _import_error:
    PROFILE_ROOT = PROJECT_ROOT / "browser_profiles"
    DOWNLOAD_ROOT = PROJECT_ROOT / "downloads" / "bookstores"
    MYEBOOKFLOW_INPUT = DOWNLOAD_ROOT / "_myebookflow_input"
    LIBRARY_ROOT = PROJECT_ROOT / "bibliotek"

    def record_skipped_drm(store, title, reason, filename="", path=""):
        logger.warning(f"[DRM] Kunde inte logga överhoppad DRM-bok: {_import_error}")

JS_ROOT = Path(__file__).resolve().parent / "js"


STORE_URLS = {
    "adlibris": {
        "name": "Adlibris",
        "start_url": "https://www.adlibris.com/se",
        "login_url": "https://www.adlibris.com/se/konto",
        "library_url": "https://www.adlibris.com/se/konto/library",
    },
    "bokus": {
        "name": "Bokus",
        "start_url": "https://www.bokus.com/",
        "login_url": "https://classic.bokus.com/cgi-bin/account_bibl_ebookshelf.cgi",
        "library_url": "https://classic.bokus.com/cgi-bin/account_bibl_ebookshelf.cgi",
    },
    "bokon": {
        "name": "Bokon",
        "start_url": "https://bokon.se/",
        "login_url": "https://bokon.se/konto/login/?next=",
        "library_url": "https://bokon.se/bibliotek/",
    },
    "kobo": {
        "name": "Kobo",
        "start_url": "https://www.kobo.com/se/sv",
        "login_url": "https://www.kobo.com/se/sv",
        "library_url": "https://www.kobo.com/se/sv/library/books",
    },
    "google": {
        "name": "Google Play Böcker",
        "start_url": "https://play.google.com/books",
        "login_url": "https://play.google.com/books",
        "library_url": "https://play.google.com/books",
    },
}


STORE_CONFIG = {
    "bokus": {
        "name": "Bokus",
        "start_url": "https://www.bokus.com/",
        "library_url": "https://classic.bokus.com/cgi-bin/account_bibl_ebookshelf.cgi",
    },
    "adlibris": {
        "name": "Adlibris",
        "start_url": "https://www.adlibris.com/se",
        "library_url": "https://www.adlibris.com/se/konto",
    },
    "bokon": {
        "name": "Bokon",
        "start_url": "https://bokon.se/",
        "library_url": "https://bokon.se/mina-sidor/",
    },
    "google": {
        "name": "Google Play Böcker",
        "start_url": "https://play.google.com/books",
        "library_url": "https://play.google.com/books",
    },
    "custom": {
        "name": "Egen länk",
        "start_url": "https://www.google.com/",
        "library_url": "https://www.google.com/",
    },
}


GOOD_WORDS = [
    "ladda ner",
    "ladda ned",
    "ladda",
    "download",
    "hämta",
    "hamta",
    "exportera fil",
    "exportera",
    "export file",
    "export",
    "export as epub",
    "export as pdf",
    "ladda ned fil",
    "ladda ner fil",
    "download file",
    "download epub",
    "download pdf",
    "epub",
    "pdf",
    "acsm",
    "ljudbok",
    "e-bok",
    "ebok",
    "audiobook",
]


BAD_WORDS = [
    "cookie",
    "cookies",
    "logga ut",
    "logout",
    "villkor",
    "terms",
    "privacy",
    "integritet",
    "kundservice",
    "support",
    "köp",
    "kop",
    "buy",
    "cart",
    "kundvagn",
    "delete",
    "ta bort",
    "remove",
    "recension",
    "review",
]


DOWNLOAD_EXTENSIONS = {
    ".epub",
    ".pdf",
    ".acsm",
    ".mobi",
    ".azw",
    ".azw3",
    ".cbz",
    ".cbr",
    ".mp3",
    ".m4a",
    ".m4b",
    ".zip",
}


def load_js(name):
    """Läser in JavaScript-snutt från tools/stores/js/<name>.js."""
    return (JS_ROOT / name).read_text(encoding="utf-8")


def clean_text(value):
    return " ".join(str(value or "").split()).strip()


def safe_filename(name):
    name = clean_text(name) or "download"
    name = re.sub(r"[\\/:*?\"<>|]+", "_", name)
    return name[:180]


def unique_path(path):
    if not path.exists():
        return path

    counter = 2

    while True:
        candidate = path.parent / f"{path.stem} ({counter}){path.suffix}"

        if not candidate.exists():
            return candidate

        counter += 1


def normalize_url(value):
    value = clean_text(value)

    if not value:
        return ""

    if value.startswith("//"):
        return "https:" + value

    return value


def get_profile_dir(store):
    path = PROFILE_ROOT / store
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_download_dir(store):
    path = DOWNLOAD_ROOT / store
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_store_config(store):
    if store not in STORE_CONFIG:
        names = ", ".join(sorted(STORE_CONFIG.keys()))
        raise SystemExit(f"Okänd butik: {store}. Välj en av: {names}")

    return STORE_CONFIG[store]


def cleanup_stale_profile_locks(profile_dir):
    profile_dir = Path(profile_dir)

    for lock_name in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
        lock_path = profile_dir / lock_name

        try:
            if lock_path.exists() or lock_path.is_symlink():
                lock_path.unlink()
        except Exception:
            logger.debug("Tystat fel ignorerat", exc_info=True)


def log_skipped_drm(store, title, reason, filename="", path=""):
    return record_skipped_drm(
        store=store,
        title=title,
        reason=reason,
        filename=filename,
        path=path,
    )


def quarantine_drm_download(path, download_dir, label=""):
    path = Path(path)
    download_dir = Path(download_dir)

    store_name = download_dir.name.strip().lower() or "okand_butik"
    skipped_root = DOWNLOAD_ROOT / "_drm_hoppades_over" / store_name
    skipped_root.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")

    raw_label = clean_text(label) or path.stem or "drm_bok"
    clean_label = safe_filename(raw_label).strip()

    if clean_label.lower().endswith(".acsm"):
        clean_label = clean_label[:-5].strip()

    clean_label = Path(clean_label).stem.strip() or "drm_bok"

    final_target = unique_path(skipped_root / f"{timestamp}_{clean_label}.acsm")

    path.replace(final_target)

    record_skipped_drm(
        store=store_name,
        title=clean_text(label) or clean_text(path.stem),
        reason="DRM/ACSM upptäckt vid massnedladdning",
        filename=final_target.name,
        path=str(final_target),
    )

    logger.warning(f"[DRM] Flyttade ACSM till: {final_target}")
    return final_target


def normalize_book_key(value):
    value = Path(str(value or "")).stem.lower()
    value = re.sub(r"[-_]+epub$", "", value)
    value = re.sub(r"[-_]+pdf$", "", value)
    value = re.sub(r"[^a-z0-9åäö]+", "", value)
    return value


def book_already_exists(filename, download_dir, label=""):
    keys = {
        normalize_book_key(filename),
        normalize_book_key(label),
    }
    keys = {k for k in keys if k and k not in {"download", "urllink", "bok", "book", "drmbok"}}

    search_dirs = [
        Path(download_dir),
        MYEBOOKFLOW_INPUT,
        LIBRARY_ROOT,
    ]

    for folder in search_dirs:
        if not folder.exists():
            continue

        for existing in folder.glob("*"):
            if not existing.is_file():
                continue

            existing_key = normalize_book_key(existing.name)

            if existing_key in keys:
                return existing

    return None


def queue_acsm_for_myebookflow(path, download_dir, label=""):
    path = Path(path)
    download_dir = Path(download_dir)

    MYEBOOKFLOW_INPUT.mkdir(parents=True, exist_ok=True)

    store_name = download_dir.name.strip().lower() or "okand_butik"
    raw_label = clean_text(label) or path.stem or "bok"
    clean_label = safe_filename(raw_label).strip()

    if clean_label.lower().endswith(".acsm"):
        clean_label = clean_label[:-5].strip()

    clean_label = Path(clean_label).stem.strip() or "bok"

    target = unique_path(MYEBOOKFLOW_INPUT / f"{store_name}_{clean_label}.acsm")
    target.write_bytes(path.read_bytes())

    logger.info(f"[MYEBOOKFLOW] Köade ACSM för konvertering: {target}")
    return target


def save_download(download, download_dir, label=""):
    download_dir = Path(download_dir)
    filename = safe_filename(download.suggested_filename or "download")

    suffix = Path(filename).suffix.lower()
    stem = Path(filename).stem.strip()

    store_name = download_dir.name.strip().lower() or "butik"

    if suffix == ".acsm":
        bad_names = {"1", "2", "3", "4", "5", "download", "urllink", "book", "ebok", "e-bok", ""}
        clean_stem = stem

        if clean_stem.lower() in bad_names:
            clean_stem = clean_text(label) or "drm_bok"

        filename = safe_filename(f"{store_name}_{clean_stem}.acsm")

    duplicate = book_already_exists(filename, download_dir, label=label)
    if duplicate:
        logger.info(f"[HOPPAR ÖVER] Redan hämtad: {duplicate}")
        return None

    target = download_dir / filename

    if target.exists():
        logger.info(f"[HOPPAR ÖVER] Filen finns redan: {target}")
        return None

    download.save_as(str(target))

    if target.suffix.lower() == ".acsm":
        queue_acsm_for_myebookflow(target, download_dir, label=label or filename)
        logger.info(f"[SPARAD ACSM] {target}")
        return target

    logger.info(f"[SPARAD] {target}")
    return target


def save_download_basic(download, download_dir):
    """Enklare version utan DRM-/dedupe-logik. Används av bookstore_downloader.py."""
    suggested = safe_filename(download.suggested_filename or "download")
    target = unique_path(Path(download_dir) / suggested)

    download.save_as(str(target))
    logger.info(f"[SPARAD] {target}")
    return target


def launch_context(playwright, store, headless=False):
    profile_dir = get_profile_dir(store)
    download_dir = get_download_dir(store)

    cleanup_stale_profile_locks(profile_dir)

    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=headless,
        accept_downloads=True,
        downloads_path=str(download_dir),
        locale="sv-SE",
        args=[
            "--disable-blink-features=AutomationControlled",
        ],
    )

    return context


def attach_download_logger(page, download_dir):
    def on_download(download):
        try:
            save_download(download, download_dir)
        except Exception as error:
            logger.error(f"[FEL] Kunde inte spara nedladdning: {error}")

    page.on("download", on_download)


def attach_context_download_logger(context, download_dir):
    for page in context.pages:
        attach_download_logger(page, download_dir)

    def on_page(page):
        attach_download_logger(page, download_dir)

    context.on("page", on_page)


def attach_download_logger_basic(page, download_dir):
    def on_download(download):
        try:
            save_download_basic(download, download_dir)
        except Exception as error:
            logger.error(f"[FEL] Kunde inte spara nedladdning: {error}")

    page.on("download", on_download)


def attach_context_page_logger_basic(context, download_dir):
    for page in context.pages:
        attach_download_logger_basic(page, download_dir)

    def on_page(page):
        attach_download_logger_basic(page, download_dir)

    context.on("page", on_page)


def open_page(context, url):
    page = context.pages[0] if context.pages else context.new_page()

    logger.info(f"[ÖPPNAR] {url}")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except PlaywrightTimeoutError:
        logger.info("[INFO] Sidan tog lång tid, men vi fortsätter.")
    except Exception as error:
        logger.warning(f"[VARNING] Kunde inte öppna sidan: {error}")

    return page


def prepare_page(page):
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        logger.debug("Tystat fel ignorerat", exc_info=True)

    try:
        page.wait_for_timeout(2000)
    except Exception:
        logger.debug("Tystat fel ignorerat", exc_info=True)

    try:
        for _ in range(5):
            page.evaluate("window.scrollBy(0, Math.max(700, window.innerHeight * 0.8));")
            page.wait_for_timeout(600)

        page.evaluate("window.scrollTo(0, 0);")
        page.wait_for_timeout(600)
    except Exception:
        logger.debug("Tystat fel ignorerat", exc_info=True)


def wait_until_all_browser_pages_closed(context):
    logger.info("[INFO] Webbläsaren hålls öppen tills du själv stänger alla Chromium-fönster.")

    while True:
        try:
            open_pages = []

            for page in context.pages:
                try:
                    if not page.is_closed():
                        open_pages.append(page)
                except Exception:
                    continue

            if not open_pages:
                break

            time.sleep(1)

        except Exception:
            break


def href_looks_like_download(href):
    href = clean_text(href)

    if not href:
        return False

    lower = href.lower()
    suffix = Path(lower.split("?", 1)[0]).suffix.lower()

    if suffix in DOWNLOAD_EXTENSIONS:
        return True

    patterns = [
        "download",
        "ladda",
        "hamta",
        "hämta",
        "export",
        "epub",
        "pdf",
        "acsm",
        "/produkt/download",
    ]

    return any(pattern in lower for pattern in patterns)


def element_text(element):
    pieces = []

    try:
        pieces.append(element.inner_text(timeout=600))
    except Exception:
        logger.debug("Tystat fel ignorerat", exc_info=True)

    for attr in ["aria-label", "title", "alt", "data-testid", "href"]:
        try:
            value = element.get_attribute(attr) or ""
            pieces.append(value)
        except Exception:
            logger.debug("Tystat fel ignorerat", exc_info=True)

    return clean_text(" ".join(pieces))


def candidate_score(text, href, aria, title):
    combined = " ".join(
        [
            clean_text(text),
            clean_text(href),
            clean_text(aria),
            clean_text(title),
        ]
    ).lower()

    if not combined:
        return 0

    for bad in BAD_WORDS:
        if bad in combined:
            return 0

    score = 0

    for word in GOOD_WORDS:
        if word in combined:
            score += 2

    if href_looks_like_download(href):
        score += 8

    return score


def extract_generic_download_candidates(page):
    candidates = []

    selectors = [
        "a[href]",
        "button",
        "[role='button']",
        "[role='menuitem']",
        "[role='option']",
        "[aria-label]",
        "[title]",
        "[data-testid]",
        "[data-test]",
        "li",
        "span",
        "div",
    ]

    selector_text = ", ".join(selectors)

    elements = page.query_selector_all(selector_text)

    for index, element in enumerate(elements):
        try:
            if not element.is_visible():
                continue
        except Exception:
            continue

        try:
            box = element.bounding_box()
        except Exception:
            box = None

        # Hoppa över jättestora containers, annars fångar vi hela sidan.
        if box:
            width = box.get("width", 0)
            height = box.get("height", 0)

            if width > 1200 and height > 300:
                continue

        try:
            text = element.inner_text(timeout=500)
        except Exception:
            text = ""

        try:
            href = element.get_attribute("href") or ""
        except Exception:
            href = ""

        try:
            aria = element.get_attribute("aria-label") or ""
        except Exception:
            aria = ""

        try:
            title = element.get_attribute("title") or ""
        except Exception:
            title = ""

        try:
            data_testid = element.get_attribute("data-testid") or ""
        except Exception:
            data_testid = ""

        try:
            data_test = element.get_attribute("data-test") or ""
        except Exception:
            data_test = ""

        combined_text = " ".join(
            [
                clean_text(text),
                clean_text(href),
                clean_text(aria),
                clean_text(title),
                clean_text(data_testid),
                clean_text(data_test),
            ]
        )

        score = candidate_score(
            text=combined_text,
            href=href,
            aria=aria,
            title=title,
        )

        if score <= 0:
            continue

        full_url = urljoin(page.url, href) if href else ""

        candidates.append(
            {
                "index": index,
                "element": element,
                "score": score,
                "text": clean_text(text),
                "href": clean_text(href),
                "url": full_url,
                "aria": clean_text(aria),
                "title": clean_text(title),
                "data_testid": clean_text(data_testid),
                "data_test": clean_text(data_test),
            }
        )

    candidates.sort(key=lambda row: row["score"], reverse=True)

    # Ta bort dubbletter
    unique = []
    seen = set()

    for candidate in candidates:
        key = (
            candidate.get("text", ""),
            candidate.get("href", ""),
            candidate.get("aria", ""),
            candidate.get("title", ""),
            candidate.get("data_testid", ""),
            candidate.get("data_test", ""),
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(candidate)

    return unique


def print_candidates(candidates):
    if not candidates:
        logger.info("[INFO] Hittade inga tydliga nedladdningsknappar/länkar.")
        return

    logger.info(f"[INFO] Hittade {len(candidates)} möjliga nedladdningskandidater.")

    for i, candidate in enumerate(candidates, start=1):
        label = candidate["text"] or candidate["aria"] or candidate["title"] or candidate["href"] or candidate["url"]
        logger.info(
            f"{i}. score={candidate['score']} text='{label[:140]}' href='{candidate['href'][:160]}'",
        )


def click_element_for_download(page, element, download_dir):
    try:
        with page.expect_download(timeout=30000) as download_info:
            element.click(timeout=10000, force=True)

        download = download_info.value
        save_download(download, download_dir)
        return True

    except PlaywrightTimeoutError:
        logger.warning("[VARNING] Klick gav ingen nedladdning.")
        return False

    except Exception as error:
        logger.error(f"[FEL] Kunde inte klicka kandidat: {error}")
        return False


def click_element_no_download_required(page, element):
    try:
        element.click(timeout=10000, force=True)
        page.wait_for_timeout(1000)
        return True
    except Exception as error:
        logger.warning(f"[VARNING] Kunde inte klicka: {error}")
        return False


def download_url_by_anchor(page, url, download_dir):
    url = clean_text(url)

    if not url:
        return False

    try:
        with page.expect_download(timeout=30000) as download_info:
            page.evaluate(
                """
                downloadUrl => {
                    const a = document.createElement('a');
                    a.href = downloadUrl;
                    a.style.display = 'none';
                    a.rel = 'noopener';
                    document.body.appendChild(a);
                    a.click();
                    setTimeout(() => a.remove(), 1000);
                }
                """,
                url,
            )

        download = download_info.value
        save_download(download, download_dir)
        return True

    except PlaywrightTimeoutError:
        return False

    except Exception as error:
        logger.error(f"[FEL] Kunde inte starta URL-nedladdning: {error}")
        return False


def looks_like_export_candidate(candidate):
    combined = " ".join(
        [
            candidate.get("text", ""),
            candidate.get("href", ""),
            candidate.get("aria", ""),
            candidate.get("title", ""),
            candidate.get("url", ""),
        ]
    ).lower()

    if any(bad in combined for bad in BAD_WORDS):
        return False

    markers = [
        "exportera fil",
        "exportera",
        "export file",
        "export",
        "ladda ner",
        "ladda ned",
        "download",
        "epub",
        "pdf",
        "acsm",
    ]

    return any(marker in combined for marker in markers)


def try_candidate_download(page, candidate, download_dir):
    label = candidate["text"] or candidate["aria"] or candidate["title"] or candidate["href"] or candidate["url"]

    logger.info(f"[FÖRSÖKER] {label[:140]}")

    if candidate.get("url") and href_looks_like_download(candidate.get("url")):
        if download_url_by_anchor(page, candidate["url"], download_dir):
            return True

    return click_element_for_download(page, candidate["element"], download_dir)


def debug_visible_menu_texts(page, label):
    """Skriver ut synliga menytexter så vi kan se vad butiken faktiskt visar."""
    try:
        rows = page.evaluate(load_js("debug_visible_menu_texts.js"))

        logger.debug(f"[DEBUG] Synliga menytexter för {label}:")

        for i, row in enumerate(rows, start=1):
            logger.info(f"  {i}. {row}")

    except Exception as error:
        logger.debug(f"[DEBUG] Kunde inte läsa menytexter för {label}: {error}")


def click_candidate_safely(page, candidate):
    """Klickar på kandidat eller närmaste klickbara förälder."""
    element = candidate["element"]

    try:
        element.click(timeout=10000, force=True)
        page.wait_for_timeout(900)
        return True
    except Exception:
        logger.debug("Tystat fel ignorerat", exc_info=True)

    try:
        element.evaluate(
            """
            el => {
                const clickable = el.closest('a, button, [role="button"], [role="menuitem"], [role="option"]') || el;
                clickable.scrollIntoView({block: 'center', inline: 'center'});
                clickable.click();
            }
            """
        )
        page.wait_for_timeout(900)
        return True
    except Exception as error:
        logger.warning(f"[VARNING] Kunde inte klicka kandidat säkert: {error}")
        return False


def tag_visible_download_like_elements(page, store):
    """Märker synliga element som faktiskt ser ut som Download/Ladda ner/Exportera.

    Används särskilt för Kobo och Google Play där menyrader kan vara komplexa.
    """
    try:
        return page.evaluate(load_js("tag_visible_download_like.js"), store)
    except Exception as error:
        logger.info(f"[{store.upper()}] Kunde inte märka download-element: {error}")
        return []


def click_tagged_download_candidate(page, candidate_index, download_dir):
    try:
        with page.expect_download(timeout=30000) as download_info:
            page.evaluate(
                """
                idx => {
                    const el = document.querySelector(`[data-bookstation-download-candidate="${idx}"]`);

                    if (!el) {
                        throw new Error("Kandidaten finns inte längre.");
                    }

                    el.scrollIntoView({block: "center", inline: "center"});
                    el.click();
                }
                """,
                str(candidate_index),
            )

        download = download_info.value
        save_download(download, download_dir)
        return True

    except PlaywrightTimeoutError:
        logger.warning("[VARNING] Klick gav ingen nedladdning.")
        return False

    except Exception as error:
        logger.error(f"[FEL] Kunde inte klicka taggad kandidat: {error}")
        return False


def find_store_menu_buttons(page, store):
    """Hittar menyknappar men undviker konto-/topmenyer."""
    buttons = []

    elements = page.query_selector_all("button, [role='button'], [aria-label], div[role='button']")

    for element in elements:
        try:
            if not element.is_visible():
                continue

            box = element.bounding_box()
        except Exception:
            continue

        if not box:
            continue

        label = element_text(element).lower()

        # Undvik toppmeny/konto på Google.
        if store == "google":
            if box.get("y", 0) < 140:
                continue

            if "google-konto" in label or "konto:" in label or "signout" in label:
                continue

        markers = [
            "fler alternativ",
            "fler åtgärder",
            "more options",
            "more actions",
            "alternativ",
            "åtgärder",
            "options",
            "actions",
        ]

        if any(marker in label for marker in markers) or label.strip() in ["⋮", "..."]:
            buttons.append(element)

    return buttons


def tag_exact_menu_texts(page, labels):
    """Märker synliga element som har exakt text, t.ex. Exportera eller Ladda ner.

    Detta är bättre än att klicka stora container-rader.
    """
    try:
        return page.evaluate(load_js("tag_exact_menu.js"), labels)
    except Exception as error:
        logger.info(f"[EXAKT] Kunde inte läsa exakta menyval: {error}")
        return []


def click_exact_menu_candidate(page, candidate_index, download_dir=None, expect_download=False):
    try:
        if expect_download:
            with page.expect_download(timeout=30000) as download_info:
                page.evaluate(
                    """
                    idx => {
                        const el = document.querySelector(`[data-bookstation-exact-menu-candidate="${idx}"]`);

                        if (!el) {
                            throw new Error("Exakt kandidat finns inte längre.");
                        }

                        el.scrollIntoView({block: "center", inline: "center"});
                        el.click();
                    }
                    """,
                    str(candidate_index),
                )

            download = download_info.value
            save_download(download, download_dir)
            return True

        page.evaluate(
            """
            idx => {
                const el = document.querySelector(`[data-bookstation-exact-menu-candidate="${idx}"]`);

                if (!el) {
                    throw new Error("Exakt kandidat finns inte längre.");
                }

                el.scrollIntoView({block: "center", inline: "center"});
                el.click();
            }
            """,
            str(candidate_index),
        )

        page.wait_for_timeout(1200)
        return True

    except PlaywrightTimeoutError:
        logger.warning("[VARNING] Exakt klick gav ingen nedladdning.")
        return False

    except Exception as error:
        logger.error(f"[FEL] Kunde inte klicka exakt kandidat: {error}")
        return False


def click_tagged_candidate_without_download(page, candidate_index):
    """Klickar en taggad kandidat utan att kräva att nedladdningen startar direkt.

    Används t.ex. Kobo: första klicket öppnar bara bekräftelse-popup.
    """
    try:
        page.evaluate(
            """
            idx => {
                const el = document.querySelector(`[data-bookstation-download-candidate="${idx}"]`);

                if (!el) {
                    throw new Error("Kandidaten finns inte längre.");
                }

                el.scrollIntoView({block: "center", inline: "center"});
                el.click();
            }
            """,
            str(candidate_index),
        )

        page.wait_for_timeout(1200)
        return True

    except Exception as error:
        logger.error(f"[FEL] Kunde inte klicka kandidat utan direktnedladdning: {error}")
        return False
