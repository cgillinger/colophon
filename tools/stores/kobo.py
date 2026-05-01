"""Kobo — automatiserad nedladdning av e-böcker."""
import logging

logger = logging.getLogger(__name__)

import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from tools.stores.common import (
    clean_text,
    element_text,
    find_store_menu_buttons,
    load_js,
    prepare_page,
    save_download,
)


def kobo_find_visible_exact_download_choices(page):
    """
    Hittar synliga Kobo-val som är exakt 'Ladda ner' / 'Download'.
    Undviker stora container-rader.
    """
    selectors = [
        "[role='menuitem']:has-text('Ladda ner')",
        "button:has-text('Ladda ner')",
        "a:has-text('Ladda ner')",
        "span:has-text('Ladda ner')",
        "div:has-text('Ladda ner')",
        "[role='menuitem']:has-text('Download')",
        "button:has-text('Download')",
        "a:has-text('Download')",
        "span:has-text('Download')",
        "div:has-text('Download')",
    ]

    results = []

    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()
        except Exception:
            continue

        for i in range(min(count, 20)):
            try:
                item = locator.nth(i)

                if not item.is_visible(timeout=700):
                    continue

                text_value = ""

                try:
                    text_value = clean_text(item.inner_text(timeout=700))
                except Exception:
                    logger.debug("Tystat fel ignorerat", exc_info=True)

                lower = text_value.lower()

                if not lower:
                    continue

                # Exakt knapp är bäst.
                if lower in ["ladda ner", "download"]:
                    score = 100
                elif "ladda ner" in lower or "download" in lower:
                    score = 20
                else:
                    continue

                # Undvik jättelånga container-rader.
                if len(text_value) > 80 and score < 100:
                    continue

                results.append(
                    {
                        "selector": selector,
                        "index": i,
                        "text": text_value,
                        "score": score,
                    }
                )

            except Exception:
                continue

    results.sort(key=lambda row: row["score"], reverse=True)

    unique = []
    seen = set()

    for row in results:
        key = (row["selector"], row["index"], row["text"])

        if key in seen:
            continue

        seen.add(key)
        unique.append(row)

    return unique


def kobo_click_download_choice(page, choice, download_dir):
    """
    Klickar första Kobo-steget: 'Ladda ner'.
    Om nedladdning startar direkt sparas den.
    Annars väntar vi på bekräftelse-popup.
    """
    selector = choice["selector"]
    index = choice["index"]
    text_value = choice["text"]

    logger.info(f"[KOBO] Klickar exakt menyval: {text_value} ({selector} #{index})")

    locator = page.locator(selector).nth(index)

    # Vissa Kobo-versioner kan starta nedladdning direkt.
    try:
        with page.expect_download(timeout=3000) as download_info:
            locator.click(timeout=10000, force=True)

        download = download_info.value
        save_download(download, download_dir)
        logger.info("[KOBO] Nedladdning startade direkt efter första klicket.")
        return "downloaded"

    except PlaywrightTimeoutError:
        logger.info("[KOBO] Första klicket gav ingen direkt nedladdning. Letar efter bekräftelse-popup.")
        return "needs_confirm"

    except Exception as error:
        logger.info(f"[KOBO] Första klicket misslyckades: {error}")
        return "failed"


def kobo_debug_visible_after_click(page):
    try:
        rows = page.evaluate(load_js("kobo_debug_visible.js"))

        logger.info("[KOBO] Synliga texter efter första klicket:")

        for i, row in enumerate(rows, start=1):
            logger.info(f"  {i}. {row}")

    except Exception as error:
        logger.info(f"[KOBO] Kunde inte debugga synliga texter: {error}")


def kobo_click_confirm_download(page, download_dir):
    """Klickar popup-knappen 'Ladda ner fil' efter första Kobo-klicket."""
    try:
        page.wait_for_timeout(2200)
    except Exception:
        logger.debug("Tystat fel ignorerat", exc_info=True)

    selectors = [
        "button:has-text('Ladda ner fil')",
        "a:has-text('Ladda ner fil')",
        "[role='button']:has-text('Ladda ner fil')",
        "[role='menuitem']:has-text('Ladda ner fil')",
        "button:has-text('Download file')",
        "a:has-text('Download file')",
        "[role='button']:has-text('Download file')",
        "[role='menuitem']:has-text('Download file')",
        "button:has-text('Ladda ner')",
        "a:has-text('Ladda ner')",
        "[role='button']:has-text('Ladda ner')",
        "[role='menuitem']:has-text('Ladda ner')",
        "button:has-text('Download')",
        "a:has-text('Download')",
        "[role='button']:has-text('Download')",
        "[role='menuitem']:has-text('Download')",
    ]

    logger.info("[KOBO] Letar efter popup-knappen 'Ladda ner fil'...")

    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()
        except Exception:
            continue

        for i in range(min(count, 10)):
            try:
                item = locator.nth(i)

                if not item.is_visible(timeout=1000):
                    continue

                text_value = ""

                try:
                    text_value = clean_text(item.inner_text(timeout=1000))
                except Exception:
                    logger.debug("Tystat fel ignorerat", exc_info=True)

                lower = text_value.lower()

                if "avbryt" in lower or "cancel" in lower or "stäng" in lower or "close" in lower:
                    continue

                logger.info(f"[KOBO] Klickar popup-knapp: {text_value} ({selector} #{i})")

                with page.expect_download(timeout=35000) as download_info:
                    item.click(timeout=10000, force=True)

                download = download_info.value
                save_download(download, download_dir)
                return True

            except PlaywrightTimeoutError:
                logger.info("[KOBO] Popup-knappen klickades, men ingen nedladdning startade.")
                continue

            except Exception as error:
                logger.info(f"[KOBO] Popup-klick misslyckades: {error}")
                continue

    kobo_debug_visible_after_click(page)
    return False


def kobo_download(page, max_downloads, dry_run, download_dir):
    prepare_page(page)

    menu_buttons = find_store_menu_buttons(page, "kobo")

    logger.info(f"[KOBO] Hittade {len(menu_buttons)} möjliga bokmenyer.")

    downloaded = 0
    checked = 0

    for menu_button in menu_buttons:
        if checked >= max_downloads:
            break

        checked += 1
        label = element_text(menu_button) or f"Meny {checked}"

        logger.info(f"[KOBO] Öppnar meny {checked}: {label[:120]}")

        try:
            menu_button.click(timeout=8000, force=True)
            page.wait_for_timeout(1200)
        except Exception as error:
            logger.info(f"[KOBO] Kunde inte öppna meny: {error}")
            continue

        choices = kobo_find_visible_exact_download_choices(page)

        logger.info(f"[KOBO] Hittade {len(choices)} exakta Ladda ner-val.")

        for index, choice in enumerate(choices[:5], start=1):
            logger.info(f"  {index}. score={choice.get('score')} {choice.get('text')} | {choice.get('selector')}")

        if dry_run:
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(400)
            except Exception:
                logger.debug("Tystat fel ignorerat", exc_info=True)
            continue

        if not choices:
            kobo_debug_visible_after_click(page)

            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(400)
            except Exception:
                logger.debug("Tystat fel ignorerat", exc_info=True)

            continue

        result = kobo_click_download_choice(page, choices[0], download_dir)

        if result == "downloaded":
            downloaded += 1
            time.sleep(1)

        elif result == "needs_confirm":
            if kobo_click_confirm_download(page, download_dir):
                downloaded += 1
                time.sleep(1)

        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        except Exception:
            logger.debug("Tystat fel ignorerat", exc_info=True)

    if dry_run:
        logger.info("[DRY RUN] Kobo: laddar inte ner något.")

    return downloaded
