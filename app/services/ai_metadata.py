# Colophon – e-book metadata manager
import json
import logging
from datetime import datetime

import requests

from app.models import LibraryItem
from app.services.app_settings import get_setting

logger = logging.getLogger(__name__)

_DEFAULT_API_URL = "https://api.mistral.ai/v1/chat/completions"
# The free plan does not include the mistral-* chat models any more
# (they answer 429 with a ceiling of zero); the ministral-* family does.
_DEFAULT_MODEL = "ministral-14b-latest"

_PROMPT = """\
You help improve book metadata for a personal library application.

Your most important task is to identify book series and series number.

You may use your training knowledge to identify series, authors, and other metadata.
When you do, set confidence to "medium" and explain in the reason field that the suggestion
is based on general knowledge rather than the provided metadata.

If a suggestion is directly supported by the provided metadata, set confidence to "high".
If evidence is weak, return null for that field's value and set confidence to "low".

Do not invent metadata. If you are unsure, return null.
Return only valid JSON. Do not include markdown fences.

Book metadata:
Title: {title}
Authors: {authors}
ISBN: {isbn}
Publisher: {publisher}
Language: {language}
Description: {description}
File name: {file_name}

The file name may contain series information (e.g. "SeriesName03 - Author - Title").
Use this to infer series name and index if not available from other fields.
{library_context}
For publication_date, return the original release year (or "YYYY-MM" / "YYYY-MM-DD" if you are confident).
Do not guess — return null if you don't know.

Return this JSON shape:
{{
  "series": {{ "value": string|null, "confidence": "high"|"medium"|"low", "reason": string }},
  "series_index": {{ "value": number|null, "confidence": "high"|"medium"|"low", "reason": string }},
  "language": {{ "value": string|null, "confidence": "high"|"medium"|"low", "reason": string }},
  "subjects": {{ "value": array|null, "confidence": "high"|"medium"|"low", "reason": string }},
  "description": {{ "value": string|null, "confidence": "high"|"medium"|"low", "reason": string }},
  "title": {{ "value": string|null, "confidence": "high"|"medium"|"low", "reason": string }},
  "authors": {{ "value": array|null, "confidence": "high"|"medium"|"low", "reason": string }},
  "publisher": {{ "value": string|null, "confidence": "high"|"medium"|"low", "reason": string }},
  "publication_date": {{ "value": string|null, "confidence": "high"|"medium"|"low", "reason": string }}
}}"""

# --- Library context (v1.51.0) -------------------------------------------
# The AI used to see one book at a time, so a bulk run produced N independent
# spellings of the same series and three synonyms for every subject. These
# three small extracts let it align with what the library already says.
# They are capped so the block stays a few KB even on a large library, which
# keeps short-context local models workable.
_CTX_MAX_AUTHOR_BOOKS = 20
_CTX_MAX_SERIES = 200
_CTX_MAX_SUBJECTS = 200
_CTX_MAX_STR = 120


def _ctx_clean(value) -> str:
    return " ".join(str(value or "").split())[:_CTX_MAX_STR]


def _norm_key(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def build_library_context(item, author_name=None) -> dict:
    """Collect what the library already knows that is relevant to `item`.

    Returns {"author_books": [...], "series": [...], "subjects": [...]}:
      author_books — other books by the same author (one per format group),
                     excluding the item itself and its own format siblings.
      series       — distinct series names in use, each with one author;
                     the item's own author's series are listed first.
      subjects     — distinct subject/genre terms, most frequent first.

    Pure read; never raises on an item without an author.
    """
    from app.models import db

    author_name = author_name or getattr(item, "author", None) or ""
    author_id = getattr(item, "author_id", None)
    item_id = getattr(item, "id", None)
    group_key = getattr(item, "group_key", None)

    # -- same author's other books ----------------------------------------
    author_books = []
    if author_id is not None or author_name.strip():
        q = LibraryItem.query
        if author_id is not None:
            q = q.filter(LibraryItem.author_id == author_id)
        else:
            q = q.filter(db.func.lower(LibraryItem.author) == author_name.strip().lower())
        if item_id is not None:
            q = q.filter(LibraryItem.id != item_id)
        if group_key:
            q = q.filter(db.or_(LibraryItem.group_key != group_key,
                                LibraryItem.group_key.is_(None)))
        # One row per format group; formats of the same book can carry
        # different metadata, so keep the sibling that says the most.
        best = {}
        for other in q.all():
            gk = other.group_key or f"id:{other.id}"
            score = (bool(other.series), bool(other.genres), bool(other.series_index))
            if gk not in best or score > best[gk][0]:
                best[gk] = (score, other)

        def _index_key(v):
            try:
                return (0, float(str(v or "").replace(",", ".")))
            except ValueError:
                return (1, str(v or ""))

        ordered = sorted(
            (o for _, o in best.values()),
            key=lambda o: (_norm_key(o.series), _index_key(o.series_index),
                           _norm_key(o.title)),
        )
        for other in ordered[:_CTX_MAX_AUTHOR_BOOKS]:
            author_books.append({
                "title": _ctx_clean(other.title),
                "series": _ctx_clean(other.series),
                "series_index": _ctx_clean(other.series_index),
                "subjects": _ctx_clean(other.genres),
            })

    # -- series vocabulary --------------------------------------------------
    rows = (
        db.session.query(LibraryItem.series, LibraryItem.author)
        .filter(LibraryItem.series.isnot(None), LibraryItem.series != "")
        .all()
    )
    own_key = _norm_key(author_name)
    by_series = {}
    for series, author in rows:
        key = _norm_key(series)
        if not key:
            continue
        entry = by_series.setdefault(key, {"name": _ctx_clean(series),
                                            "author": _ctx_clean(author),
                                            "count": 0, "own": False})
        entry["count"] += 1
        if own_key and _norm_key(author) == own_key:
            entry["own"] = True
    series_list = sorted(by_series.values(),
                         key=lambda e: (not e["own"], -e["count"], e["name"].casefold()))
    series_list = [{"name": e["name"], "author": e["author"]}
                   for e in series_list[:_CTX_MAX_SERIES]]

    # -- subject vocabulary -------------------------------------------------
    counts = {}
    display = {}
    for (genres,) in (db.session.query(LibraryItem.genres)
                      .filter(LibraryItem.genres.isnot(None), LibraryItem.genres != "")
                      .all()):
        for term in str(genres).split(","):
            key = _norm_key(term)
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
            display.setdefault(key, _ctx_clean(term))
    subjects = [display[k] for k, _ in
                sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:_CTX_MAX_SUBJECTS]]

    return {"author_books": author_books, "series": series_list, "subjects": subjects}


def format_library_context(ctx: dict) -> str:
    """Render build_library_context() output as a prompt block ('' if empty)."""
    parts = []
    if ctx.get("author_books"):
        lines = []
        for b in ctx["author_books"]:
            line = f"- {b['title']}"
            if b.get("series"):
                idx = f", #{b['series_index']}" if b.get("series_index") else ""
                line += f"  (series: {b['series']}{idx})"
            if b.get("subjects"):
                line += f"  [subjects: {b['subjects']}]"
            lines.append(line)
        parts.append("Other books by this author already in the library:\n" + "\n".join(lines))
    if ctx.get("series"):
        lines = [f"- {s['name']} — {s['author']}" if s.get("author") else f"- {s['name']}"
                 for s in ctx["series"]]
        parts.append("Series names already used in this library (with author):\n" + "\n".join(lines))
    if ctx.get("subjects"):
        parts.append("Subjects already used in this library:\n" + ", ".join(ctx["subjects"]))
    if not parts:
        return ""
    rules = (
        "Library alignment rules: if this book belongs to a series that already "
        "exists in the library, use that exact spelling. Prefer existing subject "
        "terms over new synonyms. A suggestion that matches an existing library "
        "value is \"high\" confidence."
    )
    return "\n" + "\n\n".join(parts) + "\n\n" + rules + "\n"


_KNOWN_FIELDS = {
    "series", "series_index", "language", "subjects",
    "description", "title", "authors", "publisher",
    "publication_date",
}

# Map UI/DB field names to AI prompt field names. Fields mapped to None
# cannot be reliably suggested by the AI and are excluded.
_FIELD_MAP = {
    "title": "title",
    "author": "authors",
    "series": "series",
    "series_index": "series_index",
    "isbn": None,
    "publisher": "publisher",
    "language": "language",
    "description": "description",
    "genres": "subjects",
    "published_date": "publication_date",
}


# A 429 does not say which kind of "too much" it means. The same status
# covers "you are sending requests faster than the tier allows" (wait and
# it works again) and "the account's quota is used up" (waiting does
# nothing). Telling a user to try again later is wrong in the second case,
# so read what the provider actually said: a Retry-After header means the
# first kind, and the body names the second. When neither is present we say
# so rather than guess.
_QUOTA_HINTS = ("quota", "credit", "billing", "insufficient",
                "subscription", "payment", "exceeded your current")


def _rate_limit_error(resp) -> dict:
    """Build the 429 result, carrying what the provider revealed about it.

    Always {"ok": False, "error": "rate_limit", ...} so existing callers
    that only branch on the code keep working; `retry_after` (seconds, or
    None) and `quota` (True when the body points at an exhausted balance)
    let a caller say something more useful than "try again later".
    """
    retry_after = None
    raw = str(resp.headers.get("Retry-After") or "").strip()
    if raw.isdigit():
        retry_after = int(raw)

    try:
        body = (resp.text or "")[:1000].casefold()
    except Exception:
        body = ""
    quota = any(hint in body for hint in _QUOTA_HINTS)

    # A ceiling of zero is not throttling — the provider is saying this
    # account may make no requests at all, which is what a workspace with
    # no active plan looks like. Waiting is useless advice there, and the
    # body says nothing about it: only the header does.
    allowance_zero = False
    for header in ("x-ratelimit-limit-req-minute", "x-ratelimit-limit-requests"):
        raw_limit = str(resp.headers.get(header) or "").strip()
        if raw_limit.isdigit() and int(raw_limit) == 0:
            allowance_zero = True
            break

    return {"ok": False, "error": "rate_limit", "retry_after": retry_after,
            "quota": quota, "allowance_zero": allowance_zero}


def _detect_provider(url: str) -> str:
    url = (url or "").lower()
    if "mistral" in url:
        return "mistral"
    if "openai" in url:
        return "openai"
    if "deepseek" in url:
        return "deepseek"
    if "anthropic" in url:
        return "anthropic"
    if "localhost" in url or "127.0.0.1" in url or "ollama" in url:
        return "local"
    return "custom"


def _build_headers(api_key: str) -> dict:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _log_usage(provider, model, usage, book_id=None, book_title=None):
    try:
        from sqlalchemy import text
        from app.models import db
        db.session.execute(text("""
            INSERT INTO ai_usage_log
                (provider, model, prompt_tokens, completion_tokens, total_tokens, book_id, book_title, created_at)
            VALUES
                (:provider, :model, :prompt_tokens, :completion_tokens, :total_tokens, :book_id, :book_title, :created_at)
        """), {
            "provider": provider,
            "model": model,
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "book_id": book_id,
            "book_title": book_title,
            "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        })
        db.session.commit()
    except Exception as exc:
        logger.warning("Could not save AI usage: %s", exc)


def test_ai_connection() -> dict:
    """Test the configured AI provider via a minimal chat completion call.

    Returns {"ok": True, "model": "..."} or {"ok": False, "error": "..."}.
    Works with any OpenAI-compatible chat completions endpoint.
    """
    api_url = (get_setting("AI_API_URL") or _DEFAULT_API_URL).strip()
    api_key = (get_setting("AI_API_KEY") or "").strip()
    model = (get_setting("AI_MODEL") or _DEFAULT_MODEL).strip()

    headers = _build_headers(api_key)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
        "max_tokens": 5,
    }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=15)
    except requests.Timeout:
        return {"ok": False, "error": "timeout"}
    except requests.RequestException as exc:
        logger.warning("AI test request error: %s", exc)
        return {"ok": False, "error": "request_failed"}

    if resp.status_code in (401, 403):
        return {"ok": False, "error": "auth"}
    if resp.status_code == 429:
        return _rate_limit_error(resp)
    if not resp.ok:
        return {"ok": False, "error": f"http_{resp.status_code}"}

    return {"ok": True, "model": model}


def fetch_ai_suggestions(item: LibraryItem, fields=None, override_values=None) -> dict:
    """Returns {"ok": True, "suggestions": {...}} or {"ok": False, "error": "..."}

    If `fields` is provided (list of UI field names), the prompt is narrowed
    to ask only for those fields and other suggestions are dropped.
    """
    api_url = (get_setting("AI_API_URL") or _DEFAULT_API_URL).strip()
    api_key = (get_setting("AI_API_KEY") or "").strip()
    model = (get_setting("AI_MODEL") or _DEFAULT_MODEL).strip()

    ov = override_values or {}
    description = (ov.get("description") or item.description or "")[:2000]

    if fields:
        ai_fields = [_FIELD_MAP[f] for f in fields if f in _FIELD_MAP and _FIELD_MAP[f]]
        if not ai_fields:
            return {"ok": False, "error": "no_valid_fields"}
        fields_instruction = (
            f"Only suggest values for these fields: {', '.join(ai_fields)}. "
            "Return null for all other fields."
        )
    else:
        ai_fields = None
        fields_instruction = ""

    author_name = ov.get("author") or item.author or ""
    try:
        library_ctx = build_library_context(item, author_name=author_name)
    except Exception as exc:  # context is an aid, never a blocker
        logger.warning("Library context unavailable: %s", exc)
        library_ctx = {}
    known_series = {_norm_key(s["name"]): s["name"] for s in library_ctx.get("series", [])}

    prompt = _PROMPT.format(
        title=ov.get("title") or item.title or "",
        authors=author_name,
        isbn=ov.get("isbn") or item.isbn or "",
        publisher=ov.get("publisher") or item.publisher or "",
        language=ov.get("language") or item.language or "",
        description=description,
        file_name=getattr(item, "file_name", "") or "",
        library_context=format_library_context(library_ctx),
    )
    if fields_instruction:
        prompt = prompt.replace(
            "Book metadata:",
            fields_instruction + "\n\nBook metadata:",
        )

    headers = _build_headers(api_key)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=30)
    except requests.Timeout:
        return {"ok": False, "error": "timeout"}
    except requests.RequestException as exc:
        logger.warning("AI request error: %s", exc)
        return {"ok": False, "error": "request_failed"}

    if resp.status_code in (401, 403):
        return {"ok": False, "error": "auth"}

    if resp.status_code == 429:
        return _rate_limit_error(resp)

    if not resp.ok:
        logger.warning("AI HTTP %s: %s", resp.status_code, resp.text[:300])
        return {"ok": False, "error": "api_error"}

    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, IndexError, json.JSONDecodeError, ValueError):
        return {"ok": False, "error": "invalid_json"}

    usage = body.get("usage", {})
    if usage:
        _log_usage(
            provider=_detect_provider(api_url),
            model=model,
            usage=usage,
            book_id=item.id,
            book_title=(item.title or "")[:500],
        )

    suggestions = {}

    for field in _KNOWN_FIELDS:
        entry = parsed.get(field)
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        confidence = entry.get("confidence")
        reason = entry.get("reason", "")
        if value is None or confidence not in ("high", "medium", "low"):
            continue

        if field == "authors":
            # Map authors array → author string (comma-separated) to match LibraryItem
            if isinstance(value, list):
                value = ", ".join(str(a) for a in value if a)
            else:
                value = str(value)
            suggestions["author"] = {
                "value": value,
                "confidence": confidence,
                "reason": reason,
            }
        elif field == "subjects":
            if isinstance(value, list):
                value = ", ".join(str(s) for s in value if s)
            else:
                value = str(value)
            suggestions["genres"] = {
                "value": value,
                "confidence": confidence,
                "reason": reason,
            }
        elif field == "series_index":
            suggestions["series_index"] = {
                "value": str(value),
                "confidence": confidence,
                "reason": reason,
            }
        elif field == "publication_date":
            suggestions["published_date"] = {
                "value": str(value)[:10],
                "confidence": confidence,
                "reason": reason,
            }
        else:
            if field == "series" and _norm_key(value) in known_series:
                # Snap to the library's spelling and make it apply in bulk.
                value = known_series[_norm_key(value)]
                confidence = "high"
            suggestions[field] = {
                "value": str(value),
                "confidence": confidence,
                "reason": reason,
            }

    return {"ok": True, "suggestions": suggestions}


def ai_is_configured() -> bool:
    """True if there is enough config to attempt an AI call."""
    return bool((get_setting("AI_API_KEY") or "").strip()) or _is_local_endpoint()


def _is_local_endpoint() -> bool:
    url = (get_setting("AI_API_URL") or "").lower()
    return "localhost" in url or "127.0.0.1" in url


_EXPLAIN_PROMPT = """You are a reading companion inside an e-book reader. The reader (a native Swedish speaker reading in English) selected the word "{word}" in this sentence:

"{sentence}"

The book is {book}. Explain, in Swedish, what the word means as used in this exact sentence — including any idiom, archaic usage or irony. 2–3 short sentences, no preamble, no markdown."""


def explain_word_in_context(word, sentence, item=None):
    """AI fallback/companion for the reader's dictionary sheet: explain a
    selected word in its sentence, in Swedish. Same provider, error-code and
    usage-logging conventions as adjudicate_author_names().

    Returns {"ok": True, "explanation": str} or {"ok": False, "error": "..."}.
    """
    api_url = (get_setting("AI_API_URL") or _DEFAULT_API_URL).strip()
    api_key = (get_setting("AI_API_KEY") or "").strip()
    model = (get_setting("AI_MODEL") or _DEFAULT_MODEL).strip()

    book = "unknown"
    if item is not None:
        title = (item.title or "").strip()
        author = (item.author or "").strip()
        if title:
            book = f'"{title}"' + (f" by {author}" if author else "")

    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": _EXPLAIN_PROMPT.format(
                word=(word or "")[:80],
                sentence=(sentence or "")[:500],
                book=book,
            ),
        }],
        "max_tokens": 300,
    }

    try:
        resp = requests.post(api_url, json=payload,
                             headers=_build_headers(api_key), timeout=30)
    except requests.Timeout:
        return {"ok": False, "error": "timeout"}
    except requests.RequestException as exc:
        logger.warning("AI explain request error: %s", exc)
        return {"ok": False, "error": "request_failed"}

    if resp.status_code in (401, 403):
        return {"ok": False, "error": "auth"}
    if resp.status_code == 429:
        return _rate_limit_error(resp)
    if not resp.ok:
        return {"ok": False, "error": "api_error"}

    try:
        body = resp.json()
        explanation = (body["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, ValueError):
        return {"ok": False, "error": "invalid_json"}
    if not explanation:
        return {"ok": False, "error": "empty"}

    usage = body.get("usage", {})
    if usage:
        _log_usage(provider=_detect_provider(api_url), model=model, usage=usage,
                   book_id=getattr(item, "id", None),
                   book_title=getattr(item, "title", None))

    return {"ok": True, "explanation": explanation}


_ADJUDICATE_PROMPT = """Two author name strings from an ebook library may or may not refer to the same real person:

A: "{a}"
B: "{b}"

Decide whether they are the same person. Consider typos, transliteration (e.g. Dostoevsky/Dostoyevsky), diacritics, initials vs full names, and name order — but remember that distinct real authors can have nearly identical names (e.g. Michael Connelly vs Michael Connolly are different writers).

Respond with JSON only:
{{"verdict": "same" | "different" | "unsure", "reason": "<one short sentence>"}}

Use "unsure" whenever you cannot be confident — a wrong "same" would merge two people's books."""


def adjudicate_author_names(name_a: str, name_b: str) -> dict:
    """AI adjudicator for the ambiguous middle (design matching layer 5):
    are two author spellings the same person? Advisory only — the caller
    (the manage view) shows the verdict and the USER decides to merge.
    Never auto-merge on this.

    Returns {"ok": True, "verdict": "same|different|unsure", "reason": str}
    or {"ok": False, "error": "..."} (same error codes as the other calls).
    """
    api_url = (get_setting("AI_API_URL") or _DEFAULT_API_URL).strip()
    api_key = (get_setting("AI_API_KEY") or "").strip()
    model = (get_setting("AI_MODEL") or _DEFAULT_MODEL).strip()

    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": _ADJUDICATE_PROMPT.format(a=name_a, b=name_b),
        }],
        "response_format": {"type": "json_object"},
    }

    try:
        resp = requests.post(api_url, json=payload,
                             headers=_build_headers(api_key), timeout=30)
    except requests.Timeout:
        return {"ok": False, "error": "timeout"}
    except requests.RequestException as exc:
        logger.warning("AI adjudicate request error: %s", exc)
        return {"ok": False, "error": "request_failed"}

    if resp.status_code in (401, 403):
        return {"ok": False, "error": "auth"}
    if resp.status_code == 429:
        return _rate_limit_error(resp)
    if not resp.ok:
        return {"ok": False, "error": "api_error"}

    try:
        body = resp.json()
        parsed = json.loads(body["choices"][0]["message"]["content"])
        verdict = parsed.get("verdict")
        reason = str(parsed.get("reason") or "")
    except (KeyError, IndexError, json.JSONDecodeError, ValueError):
        return {"ok": False, "error": "invalid_json"}

    if verdict not in ("same", "different", "unsure"):
        verdict = "unsure"

    usage = body.get("usage", {})
    if usage:
        _log_usage(provider=_detect_provider(api_url), model=model, usage=usage)

    return {"ok": True, "verdict": verdict, "reason": reason}


_SERIES_ORDER_PROMPT = """These books come from one e-book library and appear to belong to the same series. Put them in reading order.
{hint}
Books — id, title, and what the library currently records:
{book_lines}
{library_series}
Rules:
- Use the series' own volume numbering (the publisher's), not publication date, when the two disagree.
- A book that does not belong to this series goes in "not_in_series" and gets no number. Omnibus editions, companion volumes outside the sequence, and other series' books belong there.
- "confidence": "high" only when you recognise this specific book and its place in the sequence; "medium" when the order follows from the titles or from numbering already recorded; "low" when you are guessing.
- "reason": one short sentence in English saying what the number rests on.
- Do not invent books. Every id you return must be one of the ids above, and each id must appear exactly once — either in "books" or in "not_in_series".

Respond with JSON only:
{{"series_name": "<the series' name>", "books": [{{"id": <id>, "index": "<number as a string, e.g. 1 or 2.5>", "confidence": "high"|"medium"|"low", "reason": "<one sentence>"}}], "not_in_series": [<id>, ...]}}"""

MAX_SERIES_BOOKS = 60


def _series_order_book_line(book) -> str:
    parts = [f"id={book.get('id')}"]
    title = _ctx_clean(book.get("title"))
    if title:
        parts.append(f'"{title}"')
    author = _ctx_clean(book.get("author"))
    if author:
        parts.append(author)
    series = _ctx_clean(book.get("series"))
    series_index = _ctx_clean(book.get("series_index"))
    if series:
        if series_index:
            parts.append(f"recorded: {series} #{series_index}")
        else:
            parts.append(f"recorded: {series}")
    published_date = _ctx_clean(book.get("published_date"))
    if published_date:
        parts.append(f"published: {published_date}")
    file_name = _ctx_clean(book.get("file_name"))
    if file_name:
        parts.append(f"file: {file_name}")
    return "- " + " | ".join(parts)


def propose_series_order(books, series_hint=None, known_series=None) -> dict:
    """Ask the AI to order a set of books believed to be the same series.

    `books` is [{"id", "title", "author", "series", "series_index",
    "published_date", "file_name"}, ...]. `known_series` is a dict of
    normalized name -> library spelling, used to snap the model's series
    name back to what the library already calls it.

    Returns {"ok": True, "series_name": str, "series_name_snapped": bool,
    "books": [{"id", "index", "confidence", "reason"}], "not_in_series":
    [id], "unranked": [id]} or {"ok": False, "error": "..."}.

    Sanitizing the model's answer matters more than the HTTP call: ids the
    model invented are dropped, ids it repeated are kept once, and an id
    the model placed in both lists lands only in "not_in_series" — the
    safest reading, since it never puts a number on a book the model
    itself was unsure belonged to the series.
    """
    if not books:
        return {"ok": False, "error": "no_books"}
    if len(books) > MAX_SERIES_BOOKS:
        return {"ok": False, "error": "too_many"}
    if not ai_is_configured():
        return {"ok": False, "error": "not_configured"}

    known_series = known_series or {}

    hint = f'\nThe library calls this series "{series_hint}".\n' if series_hint else ""
    book_lines = "\n".join(_series_order_book_line(b) for b in books)
    if known_series:
        names = "\n".join(f"- {name}" for name in list(known_series.values())[:60])
        library_series = f"\nSeries names already used in this library:\n{names}\n"
    else:
        library_series = ""

    api_url = (get_setting("AI_API_URL") or _DEFAULT_API_URL).strip()
    api_key = (get_setting("AI_API_KEY") or "").strip()
    model = (get_setting("AI_MODEL") or _DEFAULT_MODEL).strip()

    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": _SERIES_ORDER_PROMPT.format(
                hint=hint, book_lines=book_lines, library_series=library_series,
            ),
        }],
        "response_format": {"type": "json_object"},
    }

    try:
        resp = requests.post(api_url, json=payload,
                             headers=_build_headers(api_key), timeout=60)
    except requests.Timeout:
        return {"ok": False, "error": "timeout"}
    except requests.RequestException as exc:
        logger.warning("AI series-order request error: %s", exc)
        return {"ok": False, "error": "request_failed"}

    if resp.status_code in (401, 403):
        return {"ok": False, "error": "auth"}
    if resp.status_code == 429:
        return _rate_limit_error(resp)
    if not resp.ok:
        return {"ok": False, "error": "api_error"}

    try:
        body = resp.json()
        parsed = json.loads(body["choices"][0]["message"]["content"])
    except (KeyError, IndexError, json.JSONDecodeError, ValueError):
        return {"ok": False, "error": "invalid_json"}

    usage = body.get("usage", {})
    if usage:
        _log_usage(provider=_detect_provider(api_url), model=model, usage=usage)

    input_ids = [b.get("id") for b in books]
    input_id_set = set(input_ids)

    series_name = str(parsed.get("series_name") or "").strip()
    snapped = False
    key = _norm_key(series_name)
    if key in known_series:
        series_name = known_series[key]
        snapped = True

    seen = set()
    out_books = []
    for entry in parsed.get("books") or []:
        if not isinstance(entry, dict):
            continue
        book_id = entry.get("id")
        if book_id not in input_id_set or book_id in seen:
            continue
        index = str(entry.get("index") if entry.get("index") is not None else "").strip()
        if not index:
            continue
        confidence = entry.get("confidence")
        if confidence not in ("high", "medium", "low"):
            confidence = "low"
        reason = str(entry.get("reason") or "")[:200]
        seen.add(book_id)
        out_books.append({
            "id": book_id, "index": index,
            "confidence": confidence, "reason": reason,
        })

    not_in_series = []
    nis_seen = set()
    for book_id in parsed.get("not_in_series") or []:
        if book_id in input_id_set and book_id not in nis_seen:
            not_in_series.append(book_id)
            nis_seen.add(book_id)

    nis_set = set(not_in_series)
    out_books = [b for b in out_books if b["id"] not in nis_set]

    ranked_ids = {b["id"] for b in out_books} | nis_set
    unranked = [book_id for book_id in input_ids if book_id not in ranked_ids]

    return {
        "ok": True,
        "series_name": series_name,
        "series_name_snapped": snapped,
        "books": out_books,
        "not_in_series": not_in_series,
        "unranked": unranked,
    }
