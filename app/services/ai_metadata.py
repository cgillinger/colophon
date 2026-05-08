import json
import logging
import os
from datetime import datetime

import requests

from app.models import LibraryItem

logger = logging.getLogger(__name__)

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_MODELS_URL = "https://api.mistral.ai/v1/models"
_DEFAULT_MODEL = "mistral-small-latest"

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
        logger.warning("Kunde inte spara AI-användning: %s", exc)


def test_ai_connection() -> dict:
    """GET /v1/models med API-nyckeln.
    Returns {"ok": True, "models": [...]} or {"ok": False, "error": "..."}
    """
    api_key = os.environ.get("COLOPHON_MISTRAL_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "error": "no_key"}

    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.get(MISTRAL_MODELS_URL, headers=headers, timeout=10)
    except requests.Timeout:
        return {"ok": False, "error": "timeout"}
    except requests.RequestException as exc:
        logger.warning("Mistral models request error: %s", exc)
        return {"ok": False, "error": "request_failed"}

    if resp.status_code in (401, 403):
        return {"ok": False, "error": "auth"}

    if resp.status_code == 429:
        return {"ok": False, "error": "rate_limit"}

    if not resp.ok:
        return {"ok": False, "error": "api_error"}

    try:
        data = resp.json()
        models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    except (ValueError, KeyError):
        return {"ok": False, "error": "invalid_json"}

    return {"ok": True, "models": models}


def fetch_ai_suggestions(item: LibraryItem, fields=None) -> dict:
    """Returns {"ok": True, "suggestions": {...}} or {"ok": False, "error": "..."}

    If `fields` is provided (list of UI field names), the prompt is narrowed
    to ask only for those fields and other suggestions are dropped.
    """
    api_key = os.environ.get("COLOPHON_MISTRAL_API_KEY", "").strip()
    if not api_key:
        return {"ok": False, "error": "no_key"}

    model = os.environ.get("COLOPHON_MISTRAL_MODEL", "").strip() or _DEFAULT_MODEL
    description = (item.description or "")[:2000]

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

    prompt = _PROMPT.format(
        title=item.title or "",
        authors=item.author or "",
        isbn=item.isbn or "",
        publisher=item.publisher or "",
        language=item.language or "",
        description=description,
    )
    if fields_instruction:
        prompt = prompt.replace(
            "Book metadata:",
            fields_instruction + "\n\nBook metadata:",
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }

    try:
        resp = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=30)
    except requests.Timeout:
        return {"ok": False, "error": "timeout"}
    except requests.RequestException as exc:
        logger.warning("Mistral request error: %s", exc)
        return {"ok": False, "error": "request_failed"}

    if resp.status_code in (401, 403):
        return {"ok": False, "error": "auth"}

    if resp.status_code == 429:
        return {"ok": False, "error": "rate_limit"}

    if not resp.ok:
        logger.warning("Mistral HTTP %s: %s", resp.status_code, resp.text[:300])
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
            provider="mistral",
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
            suggestions[field] = {
                "value": str(value),
                "confidence": confidence,
                "reason": reason,
            }

    return {"ok": True, "suggestions": suggestions}
