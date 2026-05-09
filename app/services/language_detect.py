# Colophon – e-book metadata manager
"""Language detection using langdetect on extracted book text."""
import logging

from langdetect import DetectorFactory, LangDetectException, detect

logger = logging.getLogger(__name__)

# Make detection deterministic across runs (langdetect uses random sampling
# internally; without seeding, the same text can yield different results).
DetectorFactory.seed = 0

# Map langdetect codes to ISO 639-1. Most are pass-through; the only real
# mapping is the regional Chinese variants which we collapse to "zh".
_LANG_MAP = {
    "en": "en",
    "sv": "sv",
    "no": "no",
    "da": "da",
    "fi": "fi",
    "de": "de",
    "fr": "fr",
    "es": "es",
    "it": "it",
    "pt": "pt",
    "nl": "nl",
    "pl": "pl",
    "ru": "ru",
    "ja": "ja",
    "zh-cn": "zh",
    "zh-tw": "zh",
    "ko": "ko",
}


def detect_language_from_text(text, min_length=50):
    """Detect language from a text sample.

    Returns ISO 639-1 language code, or None if detection fails or the text
    is too short to be reliable.
    """
    if not text or len(text.strip()) < min_length:
        return None

    try:
        raw = detect(text[:2000])
    except LangDetectException:
        return None

    return _LANG_MAP.get(raw, raw)


def extract_text_sample_from_epub(file_path, max_chars=2000):
    """Extract a plain-text sample from an EPUB suitable for language detection.

    Reads the first content documents in spine order, strips HTML, and
    concatenates until max_chars is reached. Returns "" if anything fails —
    callers should treat that as "no detection possible".
    """
    try:
        import ebooklib
        from bs4 import BeautifulSoup
        from ebooklib import epub

        book = epub.read_epub(file_path, options={"ignore_ncx": True})
        text_parts = []
        total = 0

        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            try:
                soup = BeautifulSoup(item.get_content(), "html.parser")
                text = soup.get_text(separator=" ", strip=True)
            except Exception:
                continue
            if text:
                text_parts.append(text)
                total += len(text)
                if total >= max_chars:
                    break

        return " ".join(text_parts)[:max_chars]
    except Exception as exc:
        logger.debug("Could not extract text from %s: %s", file_path, exc)
        return ""
