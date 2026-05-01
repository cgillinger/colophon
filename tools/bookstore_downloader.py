#!/usr/bin/env python3
"""Bookstation bookstore downloader — manuell och automatisk nedladdning."""
import argparse
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _configure_logging():
    level_name = os.environ.get("BOOKSTATION_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stdout,
        force=True,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from tools.stores.common import (
    attach_context_page_logger_basic,
    clean_text,
    get_download_dir,
    get_store_config,
    launch_context,
    open_page,
    save_download_basic,
    STORE_CONFIG,
)
from tools.stores.adlibris import extract_adlibris_download_links


GOOD_WORDS = [
    "ladda ner",
    "ladda",
    "download",
    "hämta",
    "hamta",
    "exportera",
    "export",
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


def href_looks_like_download(href):
    href = clean_text(href)

    if not href:
        return False

    lower = href.lower()
    suffix = Path(lower.split("?", 1)[0]).suffix.lower()

    if suffix in DOWNLOAD_EXTENSIONS:
        return True

    strong_patterns = [
        "download",
        "ladda",
        "hamta",
        "hämta",
        "export",
        "epub",
        "pdf",
        "acsm",
    ]

    return any(pattern in lower for pattern in strong_patterns)


def element_score(text, href, aria, title):
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
        score += 5

    return score


def find_download_candidates(page):
    candidates = []
    elements = page.query_selector_all("a, button, [role='button']")

    for index, element in enumerate(elements):
        try:
            visible = element.is_visible()
        except Exception:
            visible = False

        if not visible:
            continue

        try:
            text = element.inner_text(timeout=1000)
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

        score = element_score(text=text, href=href, aria=aria, title=title)

        if score <= 0:
            continue

        candidates.append(
            {
                "index": index,
                "element": element,
                "score": score,
                "text": clean_text(text),
                "href": clean_text(href),
                "aria": clean_text(aria),
                "title": clean_text(title),
            }
        )

    candidates.sort(key=lambda row: row["score"], reverse=True)
    return candidates


def print_candidates(candidates):
    if not candidates:
        logger.info("[INFO] Hittade inga tydliga nedladdningsknappar/länkar.")
        return

    print()
    logger.info("[KANDIDATER] Möjliga nedladdningsknappar/länkar:")

    for i, candidate in enumerate(candidates, start=1):
        label = candidate["text"] or candidate["aria"] or candidate["title"] or candidate["href"]
        print(f"{i}. score={candidate['score']} text='{label[:100]}' href='{candidate['href'][:100]}'")


def click_candidate(page, candidate, download_dir):
    element = candidate["element"]
    label = candidate["text"] or candidate["aria"] or candidate["title"] or candidate["href"]

    logger.info(f"[KLICKAR] {label[:120]}")

    try:
        with page.expect_download(timeout=12000) as download_info:
            element.click(timeout=8000, force=True)

        download = download_info.value
        save_download_basic(download, download_dir)
        return True

    except PlaywrightTimeoutError:
        logger.info("[INFO] Klick gav ingen direkt nedladdning.")
        return False

    except Exception as error:
        logger.warning(f"[VARNING] Kunde inte klicka kandidat: {error}")
        return False


def download_url_by_temporary_anchor(page, url, download_dir):
    """Startar nedladdning genom att skapa och klicka på en tillfällig länk i sidan."""
    url = clean_text(url)

    if not url:
        logger.error("[FEL] Tom download-URL.")
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
        save_download_basic(download, download_dir)
        return True

    except PlaywrightTimeoutError:
        logger.warning("[VARNING] Ingen nedladdning startade inom tidsgränsen.")
        return False

    except Exception as error:
        logger.error(f"[FEL] Kunde inte starta nedladdning: {error}")
        return False


def login_mode(args):
    config = get_store_config(args.store)
    url = args.url or config["library_url"] or config["start_url"]

    download_dir = get_download_dir(args.store)

    with sync_playwright() as playwright:
        context = launch_context(playwright, args.store, headless=False)
        attach_context_page_logger_basic(context, download_dir)

        open_page(context, url)

        print()
        print("Logga in manuellt i webbläsaren.")
        print("När du är inloggad, gå gärna till sidan där dina köpta böcker finns.")
        print("Sessionen sparas lokalt i Bookstation.")
        print()
        input("Tryck ENTER här i terminalen när du är klar... ")

        context.close()

    logger.info("[KLART] Inloggningssession sparad.")


def watch_mode(args):
    config = get_store_config(args.store)
    url = args.url or config["library_url"] or config["start_url"]

    download_dir = get_download_dir(args.store)

    with sync_playwright() as playwright:
        context = launch_context(playwright, args.store, headless=False)
        attach_context_page_logger_basic(context, download_dir)

        open_page(context, url)

        print()
        print("Nu övervakar Bookstation nedladdningar.")
        print("Klicka själv på Ladda ner / EPUB / PDF / Exportera i webbläsaren.")
        print(f"Filer sparas här: {download_dir}")
        print()
        print("När du är klar: tryck ENTER i terminalen.")
        print()

        input("Väntar... ")

        context.close()

    logger.info("[KLART] Nedladdningsövervakning avslutad.")


def auto_mode(args):
    config = get_store_config(args.store)
    url = args.url or config["library_url"] or config["start_url"]

    download_dir = get_download_dir(args.store)

    with sync_playwright() as playwright:
        context = launch_context(playwright, args.store, headless=args.headless)
        page = open_page(context, url)

        if args.interactive:
            print()
            print("Logga in/navigera manuellt till sidan med dina köpta böcker.")
            input("Tryck ENTER när sidan är rätt, så söker scriptet efter nedladdningar... ")

        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            logger.debug("Tystat fel ignorerat", exc_info=True)

        candidates = find_download_candidates(page)
        print_candidates(candidates)

        if not candidates:
            context.close()
            return

        if args.dry_run:
            logger.info("[DRY RUN] Klickar inte på något.")
            context.close()
            return

        downloaded_count = 0

        for candidate in candidates[: args.max_clicks]:
            did_download = click_candidate(page, candidate, download_dir)

            if did_download:
                downloaded_count += 1
                time.sleep(1.0)

        context.close()

    logger.info(f"[KLART] Antal sparade nedladdningar: {downloaded_count}")


def adlibris_download_all_mode(args):
    config = get_store_config("adlibris")
    url = args.url or config["library_url"] or config["start_url"]

    download_dir = get_download_dir("adlibris")

    with sync_playwright() as playwright:
        context = launch_context(playwright, "adlibris", headless=args.headless)
        page = open_page(context, url)

        if args.interactive:
            print()
            print("Navigera manuellt till sidan där dina köpta Adlibris-böcker visas.")
            input("Tryck ENTER när sidan är rätt, så hämtar scriptet download-länkar... ")

        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            logger.debug("Tystat fel ignorerat", exc_info=True)

        links = extract_adlibris_download_links(page)

        print()
        logger.info(f"[ADLIBRIS] Hittade {len(links)} unika nedladdningslänkar.")

        for index, link in enumerate(links, start=1):
            print(f"{index}. {link['version']} | {link['variant_id']}")

        if not links:
            context.close()
            return

        if args.dry_run:
            logger.info("[DRY RUN] Laddar inte ner något.")
            context.close()
            return

        downloaded = 0

        for index, link in enumerate(links[: args.max_downloads], start=1):
            print()
            print(f"[{index}/{min(len(links), args.max_downloads)}] Hämtar {link['version']}...")

            did_download = download_url_by_temporary_anchor(
                page=page,
                url=link["url"],
                download_dir=download_dir,
            )

            if did_download:
                downloaded += 1
                time.sleep(1.0)

        context.close()

    print()
    logger.info(f"[KLART] Sparade {downloaded} nedladdningar.")
    logger.info(f"[MAPP] {download_dir}")


def list_mode(args):
    print("Stödda butiker:")

    for key, config in STORE_CONFIG.items():
        print(f"- {key}: {config['name']}")
        print(f"  Start:   {config['start_url']}")
        print(f"  Library: {config['library_url']}")


def main():
    _configure_logging()

    parser = argparse.ArgumentParser(
        description="Bookstation bookstore downloader",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--store",
        default="custom",
        choices=sorted(STORE_CONFIG.keys()),
        help="Butik/profil att använda",
    )
    common.add_argument(
        "--url",
        default="",
        help="Valfri startlänk. Om tom används butikens standardlänk.",
    )

    subparsers.add_parser(
        "list",
        help="Visa stödda butiker",
    )

    subparsers.add_parser(
        "login",
        parents=[common],
        help="Öppna butik och logga in manuellt. Session sparas.",
    )

    subparsers.add_parser(
        "watch",
        parents=[common],
        help="Öppna butik och spara alla nedladdningar du själv startar.",
    )

    auto_parser = subparsers.add_parser(
        "auto",
        parents=[common],
        help="Försök hitta och klicka på nedladdningslänkar automatiskt.",
    )
    auto_parser.add_argument(
        "--interactive",
        action="store_true",
        help="Låt dig navigera manuellt först innan auto-scan.",
    )
    auto_parser.add_argument(
        "--headless",
        action="store_true",
        help="Kör utan synlig browser. Rekommenderas inte första gången.",
    )
    auto_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Visa kandidater men klicka inte.",
    )
    auto_parser.add_argument(
        "--max-clicks",
        type=int,
        default=20,
        help="Max antal kandidater att klicka på.",
    )

    adlibris_parser = subparsers.add_parser(
        "adlibris-downloads",
        help="Hämta riktiga Adlibris download-länkar och ladda ner EPUB/PDF.",
    )
    adlibris_parser.add_argument(
        "--url",
        default="",
        help="Valfri Adlibris-sida. Om tom används standard konto-/bibliotekssida.",
    )
    adlibris_parser.add_argument(
        "--interactive",
        action="store_true",
        help="Låt dig navigera manuellt till rätt sida först.",
    )
    adlibris_parser.add_argument(
        "--headless",
        action="store_true",
        help="Kör utan synlig browser. Rekommenderas inte första gången.",
    )
    adlibris_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Visa hittade nedladdningar men ladda inte ner.",
    )
    adlibris_parser.add_argument(
        "--max-downloads",
        type=int,
        default=999,
        help="Max antal böcker att ladda ner.",
    )

    args = parser.parse_args()

    if args.command == "list":
        list_mode(args)
    elif args.command == "login":
        login_mode(args)
    elif args.command == "watch":
        watch_mode(args)
    elif args.command == "auto":
        auto_mode(args)
    elif args.command == "adlibris-downloads":
        adlibris_download_all_mode(args)
    else:
        raise SystemExit("Okänt kommando.")


if __name__ == "__main__":
    main()
