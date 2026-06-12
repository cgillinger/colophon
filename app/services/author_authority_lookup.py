# Colophon – e-book metadata manager
"""Authority anchoring for authors (step 5 of
docs/author-authority-design.md): resolve a canonical author name to a
Wikidata person entity and capture its authority ids. The QID then
becomes the dedup key — far more robust than strings ("Leo Tolstoy" =
"Lev Tolstoj" = "Лев Толстой" → one QID).

One Wikidata lookup yields all three ids we store:
  - the QID itself
  - P214  → VIAF
  - P5587 → LIBRIS-URI (KB), with P906 (SELIBR) as the legacy fallback

Conservative by design: a candidate is accepted only if it is a human
(P31=Q5) AND its label/alias is a confident match for the name (same
fuzzy threshold as the matcher). No match → matched=False, nothing is
guessed. User-triggered from the manage view — never run during scans.
"""
import logging

import requests

from app.services.author_authority import (
    FUZZY_SUGGEST_THRESHOLD,
    author_signature,
    fuzzy_similarity,
)

logger = logging.getLogger(__name__)

_API = "https://www.wikidata.org/w/api.php"
_UA = "Colophon/1.0 (self-hosted ebook manager)"
_TIMEOUT = 10

_HUMAN_QID = "Q5"


def _claim_value(claims, prop):
    """First plain string value of a property, or ''."""
    for claim in claims.get(prop, []):
        value = (claim.get("mainsnak", {}).get("datavalue", {}) or {}).get("value")
        if isinstance(value, str) and value:
            return value
    return ""


def _is_human(claims):
    for claim in claims.get("P31", []):
        value = (claim.get("mainsnak", {}).get("datavalue", {}) or {}).get("value")
        if isinstance(value, dict) and value.get("id") == _HUMAN_QID:
            return True
    return False


def _name_matches(name, entity):
    """Confident name match: signature-equal to, or fuzzy-close to, the
    entity's label or one of its aliases (en/sv)."""
    sig = author_signature(name)
    forms = []
    for lang in ("en", "sv"):
        label = (entity.get("labels", {}).get(lang) or {}).get("value")
        if label:
            forms.append(label)
        for alias in entity.get("aliases", {}).get(lang, []) or []:
            if alias.get("value"):
                forms.append(alias["value"])
    for form in forms:
        if sig and author_signature(form) == sig:
            return True
        if fuzzy_similarity(name, form) >= FUZZY_SUGGEST_THRESHOLD:
            return True
    return False


def lookup_author_authority(name):
    """Resolve one author name against Wikidata.

    Returns {"ok": bool, "matched": bool, "qid", "viaf_id", "libris_id",
    "label", "description"}. ok=False only on network/API failure;
    a clean miss is ok=True, matched=False.
    """
    result = {"ok": True, "matched": False, "qid": "", "viaf_id": "",
              "libris_id": "", "label": "", "description": ""}
    if not (name or "").strip():
        return result

    qids = []
    try:
        for lang in ("en", "sv"):
            resp = requests.get(
                _API,
                params={
                    "action": "wbsearchentities", "search": name,
                    "language": lang, "uselang": lang, "type": "item",
                    "limit": 5, "format": "json",
                },
                headers={"User-Agent": _UA},
                timeout=_TIMEOUT,
            )
            if not resp.ok:
                continue
            for hit in resp.json().get("search", []):
                qid = hit.get("id")
                if qid and qid not in qids:
                    qids.append(qid)
            if qids:
                break
        if not qids:
            return result

        resp = requests.get(
            _API,
            params={
                "action": "wbgetentities", "ids": "|".join(qids[:5]),
                "props": "claims|labels|aliases|descriptions",
                "languages": "en|sv", "format": "json",
            },
            headers={"User-Agent": _UA},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        entities = resp.json().get("entities", {})
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Wikidata author lookup failed for %r: %s", name, exc)
        return {**result, "ok": False}

    # Keep the search ranking: take the first candidate that is a human
    # with a confidently matching name.
    for qid in qids:
        entity = entities.get(qid) or {}
        claims = entity.get("claims", {})
        if not _is_human(claims):
            continue
        if not _name_matches(name, entity):
            continue
        label = (entity.get("labels", {}).get("en")
                 or entity.get("labels", {}).get("sv") or {}).get("value", "")
        description = (entity.get("descriptions", {}).get("en")
                       or entity.get("descriptions", {}).get("sv") or {}).get("value", "")
        return {
            "ok": True,
            "matched": True,
            "qid": qid,
            "viaf_id": _claim_value(claims, "P214"),
            "libris_id": _claim_value(claims, "P5587") or _claim_value(claims, "P906"),
            "label": label,
            "description": description,
        }
    return result
