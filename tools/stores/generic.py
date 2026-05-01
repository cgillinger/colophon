"""Generisk butik — manuell inloggning, nedladdningsövervakning och automatisk nedladdning."""
import logging

logger = logging.getLogger(__name__)

import time

from tools.stores.common import (
    attach_context_download_logger,
    extract_generic_download_candidates,
    get_download_dir,
    launch_context,
    open_page,
    prepare_page,
    print_candidates,
    STORE_URLS,
    try_candidate_download,
    wait_until_all_browser_pages_closed,
)


def login_window(store, url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = launch_context(playwright, store, headless=False)
        open_page(context, url)

        logger.info("")
        logger.info("[INFO] Logga in i webbläsarfönstret.")
        logger.info("[INFO] Om butiken öppnar ny flik/fönster fortsätter Bookstation vänta.")
        logger.info("[INFO] När du är helt klar: stäng alla Chromium-fönster.")
        logger.info("[INFO] Sessionen sparas lokalt i Bookstation.")

        wait_until_all_browser_pages_closed(context)

        try:
            context.close()
        except Exception:
            logger.debug("Tystat fel ignorerat", exc_info=True)

    logger.info("[KLART] Loginfönster stängt. Session sparad.")


def watch_downloads(store, url):
    download_dir = get_download_dir(store)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = launch_context(playwright, store, headless=False)
        attach_context_download_logger(context, download_dir)

        open_page(context, url)

        logger.info("")
        logger.info("[INFO] Manuell övervakning är aktiv.")
        logger.info("[INFO] Klicka själv på Ladda ner / Exportera / EPUB / PDF i webbläsaren.")
        logger.info("[INFO] Bookstation sparar nedladdningar automatiskt.")
        logger.info("[INFO] Om butiken öppnar ny flik/fönster fortsätter Bookstation vänta.")
        logger.info("[INFO] När du är klar: stäng alla Chromium-fönster.")
        logger.info(f"[MAPP] {download_dir}")

        wait_until_all_browser_pages_closed(context)

        try:
            context.close()
        except Exception:
            logger.debug("Tystat fel ignorerat", exc_info=True)

    logger.info("[KLART] Övervakning avslutad.")


def generic_download(store, url, max_downloads, dry_run, headless):
    from playwright.sync_api import sync_playwright

    from tools.stores.bokon import bokon_download
    from tools.stores.bokus import bokus_download
    from tools.stores.google import google_play_download
    from tools.stores.kobo import kobo_download

    download_dir = get_download_dir(store)

    with sync_playwright() as playwright:
        context = launch_context(playwright, store, headless=headless)
        page = open_page(context, url)

        if store == "google":
            downloaded = google_play_download(
                page=page,
                max_downloads=max_downloads,
                dry_run=dry_run,
                download_dir=download_dir,
            )
            context.close()
            logger.info(f"[KLART] Sparade {downloaded} nedladdningar.")
            logger.info(f"[MAPP] {download_dir}")
            return

        if store == "kobo":
            downloaded = kobo_download(
                page=page,
                max_downloads=max_downloads,
                dry_run=dry_run,
                download_dir=download_dir,
            )
            context.close()
            logger.info(f"[KLART] Sparade {downloaded} nedladdningar.")
            logger.info(f"[MAPP] {download_dir}")
            return

        if store == "bokon":
            downloaded = bokon_download(
                page=page,
                max_downloads=max_downloads,
                dry_run=dry_run,
                download_dir=download_dir,
            )
            context.close()
            logger.info(f"[KLART] Sparade {downloaded} nedladdningar.")
            logger.info(f"[MAPP] {download_dir}")
            return

        if store == "bokus":
            downloaded = bokus_download(
                page=page,
                max_downloads=max_downloads,
                dry_run=dry_run,
                download_dir=download_dir,
            )
            context.close()
            logger.info(f"[KLART] Sparade {downloaded} nedladdningar.")
            logger.info(f"[MAPP] {download_dir}")
            return

        prepare_page(page)

        candidates = extract_generic_download_candidates(page)
        print_candidates(candidates)

        if dry_run:
            logger.info("[DRY RUN] Laddar inte ner något.")
            context.close()
            return

        downloaded = 0

        for candidate in candidates[:max_downloads]:
            if try_candidate_download(page, candidate, download_dir):
                downloaded += 1
                time.sleep(1)

        context.close()

    logger.info(f"[KLART] Sparade {downloaded} nedladdningar.")
    logger.info(f"[MAPP] {download_dir}")
