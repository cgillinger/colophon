"""Bokus Digitala bokhyllan — automatiserad nedladdning av e-böcker."""
import logging

logger = logging.getLogger(__name__)

import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from tools.stores.common import (
    clean_text,
    load_js,
    prepare_page,
    save_download,
)


def bokus_find_cover_elements(page):
    """
    Bokus Digitala bokhyllan:
    - Sidan ligger på classic.bokus.com.
    - Man klickar på bokomslaget.
    - Bokus öppnar normalt en popup där nedladdning väljs.
    """
    prepare_page(page)

    try:
        covers = page.evaluate(load_js("bokus_find_covers.js"))
    except Exception as error:
        logger.info(f"[BOKUS] Kunde inte läsa bokomslag: {error}")
        return []

    cleaned = []

    for cover in covers or []:
        label = clean_text(cover.get("label", "")) or f"Bokus-omslag {cover.get('index')}"
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


def bokus_click_cover_by_index(page, cover):
    index = cover.get("index")

    try:
        page.evaluate(
            """
            idx => {
                const img = document.querySelector(`img[data-bookstation-bokus-cover="${idx}"]`);

                if (!img) {
                    throw new Error("Bokus-omslaget finns inte längre i sidan.");
                }

                const clickable =
                    document.querySelector(`[data-bookstation-bokus-cover-link="${idx}"]`) ||
                    document.querySelector(`[data-bookstation-bokus-cover-button="${idx}"]`) ||
                    img.closest("a, button, [role='button']") ||
                    img;

                clickable.scrollIntoView({block: "center", inline: "center"});
                clickable.click();
            }
            """,
            str(index),
        )
        page.wait_for_timeout(1700)
        return True
    except Exception as error:
        logger.info(f"[BOKUS] Kunde inte klicka bokomslag {index}: {error}")
        return False


def bokus_find_download_choices(page):
    """
    Hittar nedladdningsval efter att ett Bokus-omslag har klickats.
    Popupen kan innehålla länkar/knappar för EPUB, PDF eller ACSM.
    """
    try:
        page.wait_for_timeout(800)
    except Exception:
        logger.debug("Tystat fel ignorerat", exc_info=True)

    try:
        return page.evaluate(load_js("bokus_find_download_choices.js")) or []
    except Exception as error:
        logger.info(f"[BOKUS] Kunde inte hitta nedladdningsval: {error}")
        return []


def bokus_debug_visible_after_cover(page):
    try:
        rows = page.evaluate(load_js("bokus_debug_visible.js"))
        logger.info("[BOKUS] Synliga texter efter omslagsklick:")
        for i, row in enumerate(rows, start=1):
            logger.info(f"  {i}. {row}")
    except Exception as error:
        logger.info(f"[BOKUS] Kunde inte debugga synliga texter: {error}")


def bokus_click_download_choice(page, choice, download_dir):
    index = choice.get("index")
    text_value = choice.get("text", "")
    logger.info(f"[BOKUS] Klickar nedladdningsval: {text_value[:180]}")

    try:
        with page.expect_download(timeout=45000) as download_info:
            page.evaluate(
                """
                idx => {
                    const el = document.querySelector(`[data-bookstation-bokus-download-choice="${idx}"]`);
                    if (!el) {
                        throw new Error("Bokus-nedladdningsvalet finns inte längre.");
                    }
                    el.scrollIntoView({block: "center", inline: "center"});
                    el.click();
                }
                """,
                str(index),
            )
        download = download_info.value
        save_download(download, download_dir)
        return "downloaded"
    except PlaywrightTimeoutError:
        logger.info("[BOKUS] Klicket gav ingen direkt nedladdning. Kontrollerar om en extra popup öppnades.")
        try:
            page.wait_for_timeout(1200)
        except Exception:
            logger.debug("Tystat fel ignorerat", exc_info=True)
        return "needs_more"
    except Exception as error:
        logger.info(f"[BOKUS] Kunde inte klicka nedladdningsval: {error}")
        return "failed"


def bokus_close_modal_or_restore(page, original_url):
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
        "button:has-text('Cancel')",
        "a:has-text('Stäng')",
        "a:has-text('Avbryt')",
        ".modal button.close",
        ".modal .close",
        ".popup button.close",
        ".popup .close",
        "[role='dialog'] button:has-text('Stäng')",
        "[role='dialog'] button:has-text('Avbryt')",
    ]

    for selector in close_selectors:
        try:
            locator = page.locator(selector).first()
            if locator.count() > 0 and locator.is_visible(timeout=800):
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


def bokus_download(page, max_downloads, dry_run, download_dir):
    original_url = page.url
    checked_keys = set()
    downloaded = 0
    inspected = 0

    while inspected < max_downloads:
        covers = bokus_find_cover_elements(page)
        logger.info(f"[BOKUS] Hittade {len(covers)} möjliga bokomslag.")

        if not covers:
            break

        cover = None
        for candidate in covers:
            key = candidate.get("href") or candidate.get("src") or candidate.get("label")
            if key not in checked_keys:
                cover = candidate
                checked_keys.add(key)
                break

        if not cover:
            break

        inspected += 1
        logger.info(f"[BOKUS] Klickar bokomslag {inspected}: {cover.get('label', '')[:140]}")

        if not bokus_click_cover_by_index(page, cover):
            bokus_close_modal_or_restore(page, original_url)
            continue

        choices = bokus_find_download_choices(page)
        logger.info(f"[BOKUS] Hittade {len(choices)} nedladdningsval efter omslagsklick.")

        for index, choice in enumerate(choices[:6], start=1):
            logger.info(f"  {index}. score={choice.get('score')} {choice.get('text', '')[:180]}")

        if dry_run:
            bokus_close_modal_or_restore(page, original_url)
            continue

        did_download = False
        for choice in choices[:5]:
            result = bokus_click_download_choice(page, choice, download_dir)
            if result == "downloaded":
                downloaded += 1
                did_download = True
                time.sleep(1)
                break
            if result == "needs_more":
                more_choices = bokus_find_download_choices(page)
                for more_choice in more_choices[:5]:
                    more_result = bokus_click_download_choice(page, more_choice, download_dir)
                    if more_result == "downloaded":
                        downloaded += 1
                        did_download = True
                        time.sleep(1)
                        break
                if did_download:
                    break

        if not did_download:
            bokus_debug_visible_after_cover(page)

        bokus_close_modal_or_restore(page, original_url)

    if dry_run:
        logger.info("[DRY RUN] Bokus: laddar inte ner något.")

    return downloaded
