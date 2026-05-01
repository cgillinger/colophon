"""Google Play Böcker — automatiserad nedladdning av ACSM-filer."""
import logging

logger = logging.getLogger(__name__)

import time

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from tools.stores.common import (
    clean_text,
    click_tagged_download_candidate,
    element_text,
    find_store_menu_buttons,
    load_js,
    log_skipped_drm,
    prepare_page,
    save_download,
    tag_exact_menu_texts,
    tag_visible_download_like_elements,
)


def google_debug_visible_after_export(page):
    """Debuggar synliga knappar/texter efter att Google Play-menyn eller popupen öppnats."""
    try:
        rows = page.evaluate(load_js("google_debug_visible.js"))

        logger.info("[GOOGLE PLAY] Synliga texter efter Exportera/popup:")

        for i, row in enumerate(rows, start=1):
            logger.info(f"  {i}. {row}")

    except Exception as error:
        logger.info(f"[GOOGLE PLAY] Kunde inte debugga synliga texter: {error}")


def google_click_export_choice(page, download_dir):
    """Klickar första Google Play-valet: Exportera.

    Detta öppnar normalt popupen med EPUB/PDF-val.
    I ovanliga fall kan det starta nedladdning direkt.
    """
    selectors = [
        "[role='menuitem']:has-text('Exportera')",
        "button:has-text('Exportera')",
        "a:has-text('Exportera')",
        "[role='button']:has-text('Exportera')",
        "div:has-text('Exportera')",
        "span:has-text('Exportera')",
        "[role='menuitem']:has-text('Export')",
        "button:has-text('Export')",
        "a:has-text('Export')",
        "[role='button']:has-text('Export')",
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()
        except Exception:
            continue

        for i in range(min(count, 25)):
            try:
                item = locator.nth(i)

                if not item.is_visible(timeout=800):
                    continue

                text_value = ""

                try:
                    text_value = clean_text(item.inner_text(timeout=800))
                except Exception:
                    logger.debug("Tystat fel ignorerat", exc_info=True)

                lower = text_value.lower()

                if not lower:
                    continue

                if "epub" in lower or "pdf" in lower or "acsm" in lower:
                    continue

                is_exact_export = lower in [
                    "exportera",
                    "export",
                    "exportera fil",
                    "export file",
                ]

                is_short_export = (
                    ("exportera" in lower or "export" in lower)
                    and len(text_value) <= 90
                )

                if not is_exact_export and not is_short_export:
                    continue

                logger.info(f"[GOOGLE PLAY] Klickar Exportera-val: {text_value} ({selector} #{i})")

                try:
                    with page.expect_download(timeout=3000) as download_info:
                        item.click(timeout=10000, force=True)

                    download = download_info.value
                    save_download(download, download_dir)
                    logger.info("[GOOGLE PLAY] Nedladdning startade direkt efter Exportera.")
                    return "downloaded"

                except PlaywrightTimeoutError:
                    page.wait_for_timeout(1500)
                    return "opened"

            except Exception as error:
                logger.info(f"[GOOGLE PLAY] Exportera-klick misslyckades: {error}")
                continue

    # Fallback till gamla exakta metoden om Playwright-locator inte hittar rätt.
    from tools.stores.common import click_exact_menu_candidate

    exact_exports = tag_exact_menu_texts(
        page,
        [
            "Exportera",
            "Exportera fil",
            "Export file",
            "Export",
        ],
    )

    for candidate in exact_exports[:5]:
        try:
            clicked = click_exact_menu_candidate(
                page=page,
                candidate_index=candidate.get("index"),
                download_dir=download_dir,
                expect_download=False,
            )

            if clicked:
                page.wait_for_timeout(1500)
                return "opened"

        except Exception:
            continue

    return "failed"


def google_find_acsm_format_choices(page):
    """Efter första Exportera-klicket öppnar Google Play en popup.

    Exempel från popup:
    - Exportera som ACSM för åtkomst till EPUB
    - Exportera som ACSM för åtkomst till PDF

    Den här funktionen hittar de riktiga popup-knapparna och prioriterar EPUB före PDF.
    """
    try:
        page.wait_for_timeout(1200)
    except Exception:
        logger.debug("Tystat fel ignorerat", exc_info=True)

    try:
        choices = page.evaluate(load_js("google_find_acsm_choices.js"))
        return choices or []

    except Exception as error:
        logger.info(f"[GOOGLE PLAY] Kunde inte hitta ACSM-formatval: {error}")
        return []


def google_click_acsm_format_choice(page, choice, download_dir):
    """Klickar EPUB/PDF-valet i Google Play-popupen och sparar ACSM-filen."""
    index = choice.get("index")
    text_value = choice.get("text", "")
    format_value = choice.get("format", "")

    logger.info(f"[GOOGLE PLAY] Klickar ACSM-formatval: {format_value} | {text_value[:160]}")

    try:
        with page.expect_download(timeout=45000) as download_info:
            page.evaluate(
                """
                idx => {
                    const el = document.querySelector(`[data-bookstation-google-format-choice="${idx}"]`);

                    if (!el) {
                        throw new Error("Google Play-formatvalet finns inte längre.");
                    }

                    el.scrollIntoView({block: "center", inline: "center"});
                    el.click();
                }
                """,
                str(index),
            )

        download = download_info.value
        save_download(download, download_dir)
        return True

    except PlaywrightTimeoutError:
        logger.info("[GOOGLE PLAY] Formatvalet klickades, men ingen nedladdning startade.")
        return False

    except Exception as error:
        logger.info(f"[GOOGLE PLAY] Kunde inte klicka ACSM-formatval: {error}")
        return False


def google_play_download(page, max_downloads, dry_run, download_dir):
    prepare_page(page)

    menu_buttons = find_store_menu_buttons(page, "google")

    logger.info(f"[GOOGLE PLAY] Hittade {len(menu_buttons)} möjliga bokmenyer.")

    downloaded = 0
    checked = 0

    for menu_button in menu_buttons:
        if checked >= max_downloads:
            break

        checked += 1
        label = element_text(menu_button) or f"Meny {checked}"

        logger.info(f"[GOOGLE PLAY] Öppnar meny {checked}: {label[:120]}")

        try:
            menu_button.click(timeout=8000, force=True)
            page.wait_for_timeout(1200)
        except Exception as error:
            logger.info(f"[GOOGLE PLAY] Kunde inte öppna meny: {error}")
            continue

        if dry_run:
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(400)
            except Exception:
                logger.debug("Tystat fel ignorerat", exc_info=True)
            continue

        result = google_click_export_choice(page, download_dir)

        if result == "downloaded":
            downloaded += 1
            time.sleep(1)

            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(400)
            except Exception:
                logger.debug("Tystat fel ignorerat", exc_info=True)

            continue

        if result == "skipped_drm":
            log_skipped_drm(
                store="google",
                title=label,
                reason="Google Play gav DRM/ACSM i direkt export",
                filename="",
                path="",
            )

            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(400)
            except Exception:
                logger.debug("Tystat fel ignorerat", exc_info=True)

            continue

        if result != "opened":
            logger.info("[GOOGLE PLAY] Kunde inte öppna Exportera-popupen.")

            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(400)
            except Exception:
                logger.debug("Tystat fel ignorerat", exc_info=True)

            continue

        format_candidates = google_find_acsm_format_choices(page)

        logger.info(f"[GOOGLE PLAY] ACSM-formatval i popup: {len(format_candidates)}")

        for index, candidate in enumerate(format_candidates[:5], start=1):
            logger.info(
                f"  {index}. score={candidate.get('score')} format={candidate.get('format')} "
                f"{candidate.get('text', '')[:180]}",
            )

        if format_candidates:
            epub_choices = [
                row for row in format_candidates
                if (row.get("format") or "").upper() == "EPUB"
            ]

            chosen = epub_choices[0] if epub_choices else format_candidates[0]

            if google_click_acsm_format_choice(page, chosen, download_dir):
                downloaded += 1
                time.sleep(1)

                try:
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(500)
                except Exception:
                    logger.debug("Tystat fel ignorerat", exc_info=True)

                continue

            logger.info(f"[GOOGLE PLAY] Kunde inte ladda ner ACSM/EPUB-valet: {label[:140]}")

            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
            except Exception:
                logger.debug("Tystat fel ignorerat", exc_info=True)

            continue

        fallback_format_candidates = tag_exact_menu_texts(
            page,
            [
                "Exportera som ACSM för åtkomst till EPUB",
                "Exportera som ACSM för åtkomst till PDF",
                "Export as ACSM for access to EPUB",
                "Export as ACSM for access to PDF",
                "Export as ACSM for EPUB",
                "Export as ACSM for PDF",
            ],
        )

        if fallback_format_candidates:
            logger.info(f"[GOOGLE PLAY] Fallback hittade ACSM-val. Försöker klicka: {label[:140]}")

            if click_tagged_download_candidate(
                page,
                fallback_format_candidates[0].get("index"),
                download_dir,
                label=label,
            ):
                downloaded += 1
                time.sleep(1)
                continue

            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
            except Exception:
                logger.debug("Tystat fel ignorerat", exc_info=True)

            continue

        candidates = tag_visible_download_like_elements(page, "google")

        logger.info(f"[GOOGLE PLAY] Generella fallback-kandidater: {len(candidates)}")

        did_download = False

        for candidate in candidates[:5]:
            if click_tagged_download_candidate(
                page,
                candidate.get("index"),
                download_dir,
                label=label,
            ):
                did_download = True
                downloaded += 1
                time.sleep(1)
                break

        if not did_download:
            google_debug_visible_after_export(page)

        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
        except Exception:
            logger.debug("Tystat fel ignorerat", exc_info=True)

    if dry_run:
        logger.info("[DRY RUN] Google Play: laddar inte ner något.")

    return downloaded
