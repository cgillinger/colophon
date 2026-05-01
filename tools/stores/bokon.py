"""Bokon — automatiserad nedladdning av e-böcker."""
import logging

logger = logging.getLogger(__name__)

import time

from tools.stores.common import (
    clean_text,
    extract_generic_download_candidates,
    load_js,
    looks_like_export_candidate,
    prepare_page,
    try_candidate_download,
)


def bokon_find_cover_elements(page):
    """
    Bokon:
    - Leta bara efter riktiga bokomslag.
    - Ignorera toppmeny, kategorier, presentkort, eböcker/ljudböcker-länkar osv.
    - Märk varje hittat omslag med ett data-attribut så vi kan klicka det senare.
    """
    prepare_page(page)

    try:
        covers = page.evaluate(load_js("bokon_find_covers.js"))
    except Exception as error:
        logger.info(f"[BOKON] Kunde inte läsa bokomslag: {error}")
        return []

    cleaned = []

    for cover in covers:
        label = clean_text(cover.get("label", ""))

        if not label:
            label = f"Bokomslag {cover.get('index')}"

        cleaned.append(
            {
                "index": cover.get("index"),
                "label": label,
                "href": clean_text(cover.get("href", "")),
                "src": clean_text(cover.get("src", "")),
                "width": cover.get("width"),
                "height": cover.get("height"),
            }
        )

    return cleaned


def bokon_click_cover_by_index(page, cover):
    index = cover.get("index")

    try:
        page.evaluate(
            """
            idx => {
                const img = document.querySelector(`img[data-bookstation-bokon-cover="${idx}"]`);

                if (!img) {
                    throw new Error("Bokomslaget finns inte längre i sidan.");
                }

                const clickable =
                    document.querySelector(`[data-bookstation-bokon-cover-link="${idx}"]`) ||
                    document.querySelector(`[data-bookstation-bokon-cover-button="${idx}"]`) ||
                    img.closest("a, button, [role='button']") ||
                    img;

                clickable.scrollIntoView({block: "center", inline: "center"});
                clickable.click();
            }
            """,
            str(index),
        )

        page.wait_for_timeout(1400)
        return True

    except Exception as error:
        logger.info(f"[BOKON] Kunde inte klicka bokomslag {index}: {error}")
        return False


def bokon_close_modal_or_restore(page, original_url):
    """
    Stänger modal om Bokon öppnade en sådan.
    Om klicket navigerade bort från biblioteket går vi tillbaka.
    """
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    except Exception:
        logger.debug("Tystat fel ignorerat", exc_info=True)

    close_selectors = [
        "button[aria-label*='Stäng']",
        "button[aria-label*='Close']",
        "button:has-text('Stäng')",
        "button:has-text('Avbryt')",
        ".modal button.close",
        ".modal .close",
        "[role='dialog'] button",
    ]

    for selector in close_selectors:
        try:
            locator = page.locator(selector).first()

            if locator.count() > 0 and locator.is_visible():
                locator.click(timeout=1500, force=True)
                page.wait_for_timeout(400)
                break
        except Exception:
            logger.debug("Tystat fel ignorerat", exc_info=True)

    try:
        if original_url and page.url != original_url:
            page.goto(original_url, wait_until="domcontentloaded", timeout=20000)
            prepare_page(page)
    except Exception:
        try:
            page.go_back(wait_until="domcontentloaded", timeout=20000)
            prepare_page(page)
        except Exception:
            logger.debug("Tystat fel ignorerat", exc_info=True)


def bokon_download(page, max_downloads, dry_run, download_dir):
    original_url = page.url
    checked_labels = set()
    downloaded = 0
    inspected = 0

    while inspected < max_downloads:
        covers = bokon_find_cover_elements(page)

        logger.info(f"[BOKON] Hittade {len(covers)} möjliga bokomslag.")

        if not covers:
            break

        cover = None

        for candidate in covers:
            key = candidate.get("src") or candidate.get("href") or candidate.get("label")

            if key not in checked_labels:
                cover = candidate
                checked_labels.add(key)
                break

        if not cover:
            break

        inspected += 1

        logger.info(
            f"[BOKON] Klickar bokomslag {inspected}: {cover.get('label', '')[:140]}",
        )

        if not bokon_click_cover_by_index(page, cover):
            bokon_close_modal_or_restore(page, original_url)
            continue

        candidates = extract_generic_download_candidates(page)
        download_candidates = [row for row in candidates if looks_like_export_candidate(row)]

        logger.info(f"[BOKON] Hittade {len(download_candidates)} nedladdningskandidater efter klick.")

        for index, candidate in enumerate(download_candidates[:5], start=1):
            label = candidate["text"] or candidate["aria"] or candidate["title"] or candidate["href"] or candidate["url"]
            logger.info(f"  {index}. {label[:160]}")

        if dry_run:
            bokon_close_modal_or_restore(page, original_url)
            continue

        for candidate in download_candidates[:3]:
            if try_candidate_download(page, candidate, download_dir):
                downloaded += 1
                break

        bokon_close_modal_or_restore(page, original_url)

    if dry_run:
        logger.info("[DRY RUN] Bokon: laddar inte ner något.")

    return downloaded
