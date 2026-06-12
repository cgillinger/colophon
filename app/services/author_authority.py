# Colophon – e-book metadata manager
"""Author authority matching — layers 1–3 as pure functions.

See docs/author-authority-design.md. No DB access, no UI, no network:
the caller (resolve-on-upload, step 3) builds the lookup indexes from the
authors/author_aliases tables and passes them in.

Layers, cheapest first:
  1. normalize_author_name() — light normalisation; exact-match key.
  2. author_signature()      — format-/order-invariant signature:
                               "Tolkien, J.R.R." == "J. R. R. Tolkien" ==
                               "JRR Tolkien". Highest layer safe to auto-apply.
  3. fuzzy_similarity()      — typo/diacritic/transliteration distance.
                               At or above FUZZY_SUGGEST_THRESHOLD the match
                               is *suggested*, never auto-applied.

Iron rule: auto-apply only layers 1–2. A false merge ("Michael Connelly"
vs "Michael Connolly" scores ~0.94 on layer 3) would mutate real book
files and propagate upstream — when uncertain, do not merge.

Multi-author caveat: _collect_authors() comma-joins several authors into
one string ("John Smith, Jane Doe"), syntactically identical to the sort
form "Tolkien, J.R.R.". The signature is safe for this — a multi-author
string gets a combined signature that cannot collide with any single
author — so the worst case is "new author", never a false merge. The
splitting policy belongs to resolve-on-upload (step 3).
"""
import re
import unicodedata
from difflib import SequenceMatcher

# Same threshold the duplicate detector has proven in practice.
FUZZY_SUGGEST_THRESHOLD = 0.85


def normalize_author_name(name):
    """Layer 1: light normalisation for exact matching (the alias key).

    Casefold + Unicode NFC + trim + collapse internal whitespace. Keeps
    punctuation and diacritics: "tolkien" matches "Tolkien", but
    "J.R.R. Tolkien" does not match "JRR Tolkien" here — that is layer 2.
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFC", name).casefold().strip()
    return re.sub(r"\s+", " ", s)


def author_signature(name):
    """Layer 2: format-/order-invariant signature.

    Tokens are casefolded, punctuation-stripped and sorted, so word order
    ("Lastname, First" vs "First Lastname") does not matter. Runs of
    consecutive single-letter tokens are joined before sorting, so
    "J.R.R.", "J. R. R." and "JRR" all yield the token "jrr".

    Diacritics are kept: "Müller" and "Muller" deliberately do NOT share
    a signature — that ambiguity belongs to fuzzy (layer 3), which only
    suggests.
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFC", name).casefold()
    s = s.replace("_", " ")
    s = re.sub(r"[^\w\s]", " ", s)
    tokens = s.split()

    collapsed = []
    run = []
    for token in tokens:
        if len(token) == 1:
            run.append(token)
            continue
        if run:
            collapsed.append("".join(run))
            run = []
        collapsed.append(token)
    if run:
        collapsed.append("".join(run))

    return " ".join(sorted(collapsed))


def _fuzzy_key(name):
    """ASCII-folded signature for layer-3 distance: diacritics dropped
    ("Müller" → "muller") so typo and transliteration variants compare
    close regardless of word order."""
    sig = author_signature(name)
    sig = unicodedata.normalize("NFKD", sig)
    return sig.encode("ascii", "ignore").decode("ascii")


def fuzzy_similarity(a, b):
    """Layer 3: similarity 0..1 between two author names.

    Order-invariant (compares signatures) and diacritic-insensitive.
    At or above FUZZY_SUGGEST_THRESHOLD → present as a suggestion.
    Never auto-merge on this value.
    """
    key_a, key_b = _fuzzy_key(a), _fuzzy_key(b)
    if not key_a or not key_b:
        return 0.0
    return SequenceMatcher(None, key_a, key_b).ratio()


def resolve_author(name, exact_index, signature_index, fuzzy_candidates=()):
    """Resolve one observed author string against the known registry.

    Pure — the caller supplies the lookup structures:
      exact_index       dict: normalize_author_name(form) -> author_id,
                        built from author_aliases.variant_key (+ canonical
                        names).
      signature_index   dict: author_signature(form) -> author_id.
      fuzzy_candidates  iterable of (author_id, canonical_name).

    Returns (kind, payload):
      ("exact", author_id)     — layer 1 hit; safe to auto-link.
      ("signature", author_id) — layer 2 hit; safe to auto-link.
      ("suggest", [(author_id, score), ...]) — layer 3, best first;
                                 requires user confirmation.
      ("new", None)            — no match; a tentative canonical may be
                                 created (it has not yet earned file writes).
      ("none", None)           — empty/unusable input.
    """
    normalized = normalize_author_name(name)
    if not normalized:
        return ("none", None)

    author_id = exact_index.get(normalized)
    if author_id is not None:
        return ("exact", author_id)

    signature = author_signature(name)
    if signature:
        author_id = signature_index.get(signature)
        if author_id is not None:
            return ("signature", author_id)

    suggestions = []
    for candidate_id, candidate_name in fuzzy_candidates:
        score = fuzzy_similarity(name, candidate_name)
        if score >= FUZZY_SUGGEST_THRESHOLD:
            suggestions.append((candidate_id, score))
    if suggestions:
        suggestions.sort(key=lambda entry: entry[1], reverse=True)
        return ("suggest", suggestions)

    return ("new", None)
