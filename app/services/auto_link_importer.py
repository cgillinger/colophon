import logging
import re
from urllib.parse import urlparse

from app.services.link_metadata import (
    clean_text,
    import_metadata_from_pasted_content,
    import_metadata_from_url,
)

logger = logging.getLogger(__name__)


BLOCKED_MARKERS = [
    "vercel security checkpoint",
    "security checkpoint",
    "access denied",
    "captcha",
    "robot check",
    "just a moment",
    "enable javascript and cookies",
    "cloudflare",
]


def looks_blocked(html):
    html = (html or "").lower()

    for marker in BLOCKED_MARKERS:
        if marker in html:
            return True

    return False


def is_valid_url(url):
    url = clean_text(url)

    if not url.startswith(("http://", "https://")):
        return False

    try:
        parsed = urlparse(url)
    except Exception:
        return False

    return bool(parsed.hostname)


def fetch_rendered_html_with_browser(url):
    """
    Hämtar renderad HTML med Chromium/Playwright.
    Detta försöker inte kringgå captcha eller säkerhetsspärrar.
    """
    url = clean_text(url)

    if not is_valid_url(url):
        return {
            "ok": False,
            "html": "",
            "final_url": url,
            "error": "Ogiltig länk.",
        }

    try:
        from playwright.sync_api import sync_playwright
    except Exception as error:
        return {
            "ok": False,
            "html": "",
            "final_url": url,
            "error": f"Playwright är inte installerat korrekt: {error}",
        }

    browser = None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )

            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="sv-SE",
            )

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=25000,
            )

            try:
                page.wait_for_load_state("networkidle", timeout=7000)
            except Exception:
                logger.debug("Tystat fel ignorerat", exc_info=True)

            try:
                page.wait_for_timeout(1500)
            except Exception:
                logger.debug("Tystat fel ignorerat", exc_info=True)

            html = page.content()
            final_url = page.url

            browser.close()
            browser = None

            if not html:
                return {
                    "ok": False,
                    "html": "",
                    "final_url": final_url,
                    "error": "Webbläsaren fick tom HTML.",
                }

            if looks_blocked(html):
                return {
                    "ok": False,
                    "html": "",
                    "final_url": final_url,
                    "error": "Sidan visar fortfarande säkerhetsspärr/captcha. Bookstation kringgår inte sådant skydd.",
                }

            return {
                "ok": True,
                "html": html,
                "final_url": final_url,
                "error": "",
            }

    except Exception as error:
        try:
            if browser:
                browser.close()
        except Exception:
            logger.debug("Tystat fel ignorerat", exc_info=True)

        return {
            "ok": False,
            "html": "",
            "final_url": url,
            "error": f"Kunde inte hämta renderad HTML: {error}",
        }


def auto_import_metadata_from_link(source_url):
    """
    Försöker:
    1. Vanlig import från länk.
    2. Automatisk renderad HTML via Playwright.
    3. Parser från renderad HTML.
    """
    source_url = clean_text(source_url)

    if not source_url:
        return {
            "ok": False,
            "error": "Du måste ange en länk.",
            "result": None,
            "method": "none",
        }

    direct = import_metadata_from_url(source_url)

    if direct.get("ok"):
        direct["method"] = "direct"
        return direct

    rendered = fetch_rendered_html_with_browser(source_url)

    if not rendered.get("ok"):
        return {
            "ok": False,
            "error": (
                direct.get("error")
                or rendered.get("error")
                or "Kunde inte hämta metadata från länken."
            ),
            "result": None,
            "method": "failed",
        }

    parsed = import_metadata_from_pasted_content(
        source_url=rendered.get("final_url") or source_url,
        pasted_content=rendered.get("html", ""),
    )

    if parsed.get("ok") and parsed.get("result"):
        result = parsed["result"]
        result["source"] = result.get("source", "Import från länk") + " / automatisk HTML"

        return {
            "ok": True,
            "error": "",
            "result": result,
            "method": "rendered_html",
        }

    return {
        "ok": False,
        "error": parsed.get("error") or "Renderad HTML hämtades, men metadata kunde inte hittas.",
        "result": None,
        "method": "rendered_html_failed",
    }
