# Colophon – e-book metadata manager
"""Language detection using langdetect on extracted book text."""
import logging

from langdetect import DetectorFactory, LangDetectException, detect, detect_langs

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


def _spine_documents(book):
    """Content documents in spine (reading) order.

    ebooklib's get_items_of_type() returns manifest order, which is not
    necessarily the order the book is read in. Fall back to it when the
    spine is unusable.
    """
    import ebooklib

    docs = []
    for idref, _linear in getattr(book, "spine", []) or []:
        item = book.get_item_with_id(idref)
        if item is not None and item.get_type() == ebooklib.ITEM_DOCUMENT:
            docs.append(item)
    if docs:
        return docs
    return list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))


def _text_at(docs, start, min_length, max_chars):
    """Plain text from docs[start:], walking forward until min_length is met."""
    from bs4 import BeautifulSoup

    parts = []
    total = 0
    for item in docs[start:]:
        try:
            text = BeautifulSoup(item.get_content(), "html.parser").get_text(
                separator=" ", strip=True
            )
        except Exception:
            continue
        if not text:
            continue
        parts.append(text)
        total += len(text)
        if total >= max(min_length, max_chars):
            break
    return " ".join(parts)[:max_chars]


def detect_language_confident(
    file_path, positions=(0.3, 0.6), min_length=200, max_chars=2000
):
    """Detect an EPUB's language from two samples taken from *inside* the book.

    The first pages are the worst place to ask: copyright boilerplate,
    publisher blurbs and forewords are routinely in a different language
    than the book itself. So sample at `positions` through the spine.

    Returns {"code": str, "prob": float, "agree": bool} — `agree` says
    whether both samples landed on the same language, which is the signal
    worth surfacing to the user — or None when the book yields too little
    text to judge.
    """
    try:
        import ebooklib  # noqa: F401  (imported for its side effect in helpers)
        from ebooklib import epub

        book = epub.read_epub(file_path, options={"ignore_ncx": True})
        docs = _spine_documents(book)
        if not docs:
            return None

        results = []
        for pos in positions:
            start = min(int(len(docs) * pos), max(len(docs) - 1, 0))
            text = _text_at(docs, start, min_length, max_chars)
            if len(text.strip()) < min_length:
                continue
            try:
                best = detect_langs(text)[0]
            except (LangDetectException, IndexError):
                continue
            results.append((_LANG_MAP.get(best.lang, best.lang), float(best.prob)))

        if not results:
            return None

        # Report the more confident of the two, but let `agree` carry the
        # doubt: a book whose two halves disagree is exactly the case a
        # human should look at rather than have silently overwritten.
        results.sort(key=lambda r: r[1], reverse=True)
        code, prob = results[0]
        agree = len(results) > 1 and all(r[0] == code for r in results)
        return {"code": code, "prob": prob, "agree": agree}
    except Exception as exc:
        logger.debug("Language detection failed for %s: %s", file_path, exc)
        return None
