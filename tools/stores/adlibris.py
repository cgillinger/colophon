"""Adlibris — automatiserad nedladdning av e-böcker via direktlänkar."""
import logging

logger = logging.getLogger(__name__)

import re
import time
from urllib.parse import urljoin

from tools.stores.common import (
    clean_text,
    download_url_by_anchor,
    get_download_dir,
    launch_context,
    open_page,
    prepare_page,
    STORE_URLS,
)


def extract_adlibris_download_links(page):
    links_by_variant = {}

    anchors = page.query_selector_all("a[href]")

    for anchor in anchors:
        try:
            href = clean_text(anchor.get_attribute("href") or "")
        except Exception:
            continue

        if not href:
            continue

        if "/produkt/download" not in href:
            continue

        full_url = urljoin(page.url, href)

        variant_match = re.search(r"variantId=([^&]+)", href)
        version_match = re.search(r"selectedVersion=([^&]+)", href)

        variant_id = variant_match.group(1) if variant_match else href
        version = version_match.group(1) if version_match else ""

        priority_map = {
            "EpubWatermark": 1,
            "Epub": 2,
            "PDFWatermark": 3,
            "PDF": 4,
        }

        priority = priority_map.get(version, 99)

        candidate = {
            "variant_id": variant_id,
            "version": version,
            "url": full_url,
            "priority": priority,
        }

        current = links_by_variant.get(variant_id)

        if current is None or candidate["priority"] < current["priority"]:
            links_by_variant[variant_id] = candidate

    links = list(links_by_variant.values())
    links.sort(key=lambda row: (row["priority"], row["variant_id"]))

    return links


def download_adlibris(url, max_downloads, dry_run, headless):
    store = "adlibris"
    download_dir = get_download_dir(store)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = launch_context(playwright, store, headless=headless)
        page = open_page(context, url)

        prepare_page(page)

        links = extract_adlibris_download_links(page)

        logger.info(f"[ADLIBRIS] Hittade {len(links)} unika nedladdningslänkar.")

        for index, link in enumerate(links, start=1):
            logger.info(f"{index}. {link['version']} | {link['variant_id']}")

        if dry_run:
            logger.info("[DRY RUN] Laddar inte ner något.")
            context.close()
            return

        downloaded = 0

        for index, link in enumerate(links[:max_downloads], start=1):
            total = min(len(links), max_downloads)
            logger.info(f"[{index}/{total}] Hämtar {link['version']}...")

            if download_url_by_anchor(page, link["url"], download_dir):
                downloaded += 1
                time.sleep(1)

        context.close()

    logger.info(f"[KLART] Sparade {downloaded} nedladdningar.")
    logger.info(f"[MAPP] {download_dir}")
