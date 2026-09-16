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
(P31=Q5), its label/alias is a confident match for the name (same fuzzy
threshold as the matcher), AND it writes for a living (P106 occupation).
No match → matched=False, nothing is guessed. User-triggered from the
manage view — never run during scans.

The occupation test is not decoration. "Dennis Taylor" returns a British
snooker player first, and human + matching name accepted him — so a
Canadian science fiction author was anchored to a snooker player, and
because `authority_linked` gates file writes, a wrong anchor is worse
than none. In a library of books, a name-matching person who is not
recorded as writing anything is the wrong person; the honest answer is
no match. The cost is a false negative for an author Wikidata has not
given an occupation, which leaves the entry exactly as it was.
"""
import logging

import requests

from app.services.author_authority import (
    FUZZY_SUGGEST_THRESHOLD,
    author_signature,
    fuzzy_similarity,
)
from app.services.grouping import normalize_title_key

logger = logging.getLogger(__name__)

_API = "https://www.wikidata.org/w/api.php"
_SPARQL = "https://query.wikidata.org/sparql"
_UA = "Colophon/1.0 (self-hosted ebook manager)"
_TIMEOUT = 10

_HUMAN_QID = "Q5"

# P106 (occupation) values that mean "this person writes things other
# people read". Deliberately broad — a library holds novels, history,
# philosophy and journalism alike — and deliberately a flat list: Wikidata
# subclass resolution would cost another round trip per candidate.
_WRITING_OCCUPATIONS = {
    "Q36180",     # writer
    "Q482980",    # author
    "Q6625963",   # novelist
    "Q18844224",  # science fiction writer
    "Q49757",     # poet
    "Q214917",    # playwright
    "Q28389",     # screenwriter
    "Q1930187",   # journalist
    "Q4853732",   # children's writer
    "Q11774202",  # essayist
    "Q15980158",  # non-fiction writer
    "Q12144794",  # writer of fiction
    "Q201788",    # historian
    "Q4964182",   # philosopher
    "Q333634",    # translator
    "Q1622272",   # university teacher — academics publish
}


def _writes(claims):
    """True when any P106 occupation is one we treat as writing."""
    for claim in claims.get("P106", []):
        value = (claim.get("mainsnak", {}).get("datavalue", {}) or {}).get("value")
        if isinstance(value, dict) and value.get("id") in _WRITING_OCCUPATIONS:
            return True
    return False


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


def _works_by_candidate(qids):
    """{qid: {normalized title, ...}} — the works each candidate is
    credited as author of (P50), in one SPARQL query for all of them.

    Any failure returns {}: Wikidata is evidence here, never a
    precondition. A lookup that cannot reach the query service falls back
    to the occupation test, exactly as if no work were recorded.
    """
    if not qids:
        return {}
    values = " ".join(f"wd:{q}" for q in qids)
    query = f"""
    SELECT ?person ?workLabel WHERE {{
      VALUES ?person {{ {values} }}
      ?work wdt:P50 ?person .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,sv". }}
    }}
    LIMIT 400
    """
    try:
        resp = requests.get(
            _SPARQL,
            params={"query": query, "format": "json"},
            headers={"User-Agent": _UA},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        bindings = resp.json().get("results", {}).get("bindings", [])
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Wikidata works lookup failed for %r: %s", qids, exc)
        return {}

    works = {}
    for row in bindings:
        person = (row.get("person", {}).get("value") or "").rsplit("/", 1)[-1]
        title = normalize_title_key(row.get("workLabel", {}).get("value") or "")
        if person and title:
            works.setdefault(person, set()).add(title)
    return works


def _candidate_written_a_book_we_hold(qids, known_titles):
    """The first candidate, in Wikidata's ranking order, credited with a
    title this library already holds — or None.

    This is the only hard evidence available: a name is shared, an
    occupation is a guess, but "wrote a book that is on the shelf" picks
    the right person out of a group of namesakes. It therefore outranks
    the occupation test rather than refining it.
    """
    wanted = {normalize_title_key(t) for t in (known_titles or [])}
    wanted.discard("")
    if not wanted or len(qids) < 2:
        return None
    works = _works_by_candidate(qids)
    for qid in qids:
        if works.get(qid, set()) & wanted:
            return qid
    return None


def _search_ids(query, limit=5):
    """wbsearchentities → ids, empty on any failure."""
    try:
        resp = requests.get(
            _API,
            params={
                "action": "wbsearchentities", "search": query,
                "language": "en", "uselang": "en", "type": "item",
                "limit": limit, "format": "json",
            },
            headers={"User-Agent": _UA},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return [h["id"] for h in resp.json().get("search", []) if h.get("id")]
    except (requests.RequestException, ValueError, KeyError):
        return []


def _get_entities(qids, props="claims|labels|aliases|descriptions"):
    """wbgetentities → {qid: entity}, empty on any failure."""
    if not qids:
        return {}
    try:
        resp = requests.get(
            _API,
            params={
                "action": "wbgetentities", "ids": "|".join(qids[:20]),
                "props": props, "languages": "en|sv", "format": "json",
            },
            headers={"User-Agent": _UA},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("entities", {})
    except (requests.RequestException, ValueError):
        return {}


def _author_of_a_book_we_hold(name, known_titles):
    """Find the person by looking up the *book* instead of the name.

    The name search is the weak link, not the filtering: "Dennis Taylor"
    returns a snooker player, a racing driver and a footballer, while the
    novelist is labelled "Dennis E. Taylor" and never appears at all. No
    amount of filtering can pick a candidate that was never a candidate.

    Searching a title we hold finds the book in one step, and the book
    says who wrote it (P50). The name still has to match — this asks
    Wikidata "who wrote this book?", then checks the answer is plausibly
    the author we were asking about. Only runs when the name search found
    nobody we trust, so the common path costs nothing.
    """
    work_ids = []
    for title in (known_titles or [])[:3]:
        work_ids.extend(_search_ids(title))
        if work_ids:
            break
    if not work_ids:
        return None, {}

    person_ids = []
    for entity in _get_entities(work_ids, props="claims").values():
        for claim in entity.get("claims", {}).get("P50", []):
            value = (claim.get("mainsnak", {}).get("datavalue", {}) or {}).get("value")
            if isinstance(value, dict) and value.get("id"):
                if value["id"] not in person_ids:
                    person_ids.append(value["id"])
    if not person_ids:
        return None, {}

    people = _get_entities(person_ids)
    for qid in person_ids:
        entity = people.get(qid) or {}
        if not _is_human(entity.get("claims", {})):
            continue
        if not _name_matches(name, entity):
            continue
        return qid, entity
    return None, {}


def lookup_author_authority(name, known_titles=None):
    """Resolve one author name against Wikidata.

    `known_titles` are titles this library already holds for the author.
    They are only consulted when the name is ambiguous, and they decide
    it: a candidate credited with a book on the shelf is the right person
    in a way no name or occupation test can establish.

    Returns {"ok": bool, "matched": bool, "qid", "viaf_id", "libris_id",
    "label", "description", "matched_on"}. `matched_on` is "title" or
    "occupation" — which evidence chose the candidate. ok=False only on
    network/API failure; a clean miss is ok=True, matched=False.
    """
    result = {"ok": True, "matched": False, "qid": "", "viaf_id": "",
              "libris_id": "", "label": "", "description": "",
              "matched_on": ""}
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
        # No hits is not the end: the book-title fallback below can still
        # find someone the name search never offered. Same for a search
        # that returns only wrong people.
        entities = {}
        if qids:
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

    # Everyone the name could plausibly be, in Wikidata's ranking order.
    people = [qid for qid in qids
              if _is_human((entities.get(qid) or {}).get("claims", {}))
              and _name_matches(name, entities.get(qid) or {})]

    # Hard evidence first: did one of them write a book we hold? Only asked
    # when there is genuinely a choice to make.
    chosen = _candidate_written_a_book_we_hold(people, known_titles)
    matched_on = "title" if chosen else ""

    # Otherwise fall back to "this person writes for a living". Wikidata
    # ranks by general notability, so the snooker player comes before the
    # novelist and the ranking alone cannot be trusted here.
    if not chosen:
        for qid in people:
            if _writes((entities.get(qid) or {}).get("claims", {})):
                chosen = qid
                matched_on = "occupation"
                break
    # Last resort: the name search may simply never have offered the right
    # person. Ask the books instead.
    entity = entities.get(chosen) or {} if chosen else {}
    if not chosen:
        chosen, entity = _author_of_a_book_we_hold(name, known_titles)
        matched_on = "title" if chosen else ""
    if not chosen:
        return result

    claims = entity.get("claims", {})
    return {
        "ok": True,
        "matched": True,
        "qid": chosen,
        "viaf_id": _claim_value(claims, "P214"),
        "libris_id": _claim_value(claims, "P5587") or _claim_value(claims, "P906"),
        "label": (entity.get("labels", {}).get("en")
                  or entity.get("labels", {}).get("sv") or {}).get("value", ""),
        "description": (entity.get("descriptions", {}).get("en")
                        or entity.get("descriptions", {}).get("sv") or {}).get("value", ""),
        "matched_on": matched_on,
    }
