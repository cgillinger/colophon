# Colophon – e-book metadata manager
"""authors_bp — author authority registry endpoints (step 4 of
docs/author-authority-design.md).

The manage page is server-rendered; everything else is small JSON APIs
consumed by book-modal.js (combobox) and authors.html (inline actions).
All mutations here are DB-only — files pick up canonical names at the
next metadata-write moment (modal save / enrichment), per the design's
file-write-timing rule.
"""
from flask import Blueprint, jsonify, render_template, request

from app.models import db, Author, LibraryItem
from app.routes.helpers import get_item_or_404
from app.services.author_resolver import (
    STATUS_LINKED,
    assign_author_to_item,
    authors_overview,
    find_existing_author,
    merge_authors,
    rename_author,
    suggest_similar_authors,
)

authors_bp = Blueprint("authors", __name__)


def _get_author_or_404(author_id):
    return Author.query.get_or_404(author_id)


def _author_dict(author, book_count=None):
    d = {
        "id": author.id,
        "name": author.canonical_name,
        "source": author.source,
        "wikidata_qid": author.wikidata_qid,
        "libris_id": author.libris_id,
        "viaf_id": author.viaf_id,
    }
    if book_count is not None:
        d["book_count"] = book_count
    return d


@authors_bp.route("/authors")
def manage_authors():
    """The "Manage authors" view — registry backstop (design guard 3)."""
    rows, pairs = authors_overview(db.session)
    review_count = (
        LibraryItem.query.filter(
            LibraryItem.author_status.in_(["review", "new", "missing"])
        ).count()
    )
    return render_template(
        "authors.html",
        rows=rows,
        duplicate_pairs=pairs,
        review_count=review_count,
    )


@authors_bp.route("/authors/search")
def search_authors():
    """Typeahead for the combobox: layered — exact/signature hit first,
    then substring matches on the canonical name."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"ok": True, "authors": []})

    results = []
    seen = set()
    exact = find_existing_author(db.session, q)
    if exact:
        results.append(_author_dict(exact))
        seen.add(exact.id)
    for author in (
        Author.query.filter(Author.canonical_name.ilike(f"%{q}%"))
        .order_by(Author.canonical_name)
        .limit(10)
        .all()
    ):
        if author.id not in seen:
            results.append(_author_dict(author))
            seen.add(author.id)
    return jsonify({"ok": True, "authors": results[:10]})


@authors_bp.route("/authors/items/<int:item_id>/suggestions")
def item_suggestions(item_id):
    """Combobox bootstrap for one book: its author state + fuzzy
    suggestions (recomputed now — the registry may have changed since the
    item was flagged)."""
    item = get_item_or_404(item_id)
    suggestions = []
    if item.author:
        suggestions = [
            {**_author_dict(author), "score": round(score, 3)}
            for author, score in suggest_similar_authors(
                db.session, item.author, exclude_id=item.author_id
            )
        ]
    linked = db.session.get(Author, item.author_id) if item.author_id else None
    return jsonify({
        "ok": True,
        "author_status": item.author_status,
        "linked": _author_dict(linked) if linked else None,
        "suggestions": suggestions,
    })


@authors_bp.route("/authors/items/<int:item_id>/assign", methods=["POST"])
def assign_item_author(item_id):
    """Confirm an author for one book — the combobox commit.

    Body: {"author_id": N} to link an existing entry, or
          {"name": "...", "force": bool} to create/confirm by name.
    Without force, a fuzzy near-match blocks creation (design guard 2)
    and is returned as similar[] for the "sure it's a new author?" ask.
    """
    item = get_item_or_404(item_id)
    data = request.get_json(silent=True) or {}

    author = None
    if data.get("author_id"):
        author = _get_author_or_404(data["author_id"])
    else:
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"ok": False, "error": "name_required"}), 400
        author = find_existing_author(db.session, name)
        if author is None and not data.get("force"):
            similar = suggest_similar_authors(db.session, name)
            if similar:
                return jsonify({
                    "ok": False,
                    "error": "similar_exists",
                    "similar": [
                        {**_author_dict(a), "score": round(s, 3)}
                        for a, s in similar
                    ],
                })
        if author is None:
            author = assign_author_to_item(db.session, item, name=name)
            db.session.commit()
            return jsonify({"ok": True, "author": _author_dict(author),
                            "author_status": STATUS_LINKED, "created": True})

    assign_author_to_item(db.session, item, author=author)
    db.session.commit()
    return jsonify({"ok": True, "author": _author_dict(author),
                    "author_status": STATUS_LINKED, "created": False})


@authors_bp.route("/authors/<int:author_id>/rename", methods=["POST"])
def rename(author_id):
    author = _get_author_or_404(author_id)
    name = ((request.get_json(silent=True) or {}).get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name_required"}), 400
    try:
        count = rename_author(db.session, author, name)
    except ValueError:
        db.session.rollback()
        return jsonify({"ok": False, "error": "name_taken"}), 409
    db.session.commit()
    return jsonify({"ok": True, "author": _author_dict(author),
                    "relabelled": count})


@authors_bp.route("/authors/<int:author_id>/merge", methods=["POST"])
def merge(author_id):
    source = _get_author_or_404(author_id)
    target_id = (request.get_json(silent=True) or {}).get("target_id")
    if not target_id:
        return jsonify({"ok": False, "error": "target_required"}), 400
    target = _get_author_or_404(target_id)
    try:
        count = merge_authors(db.session, source, target)
    except ValueError:
        db.session.rollback()
        return jsonify({"ok": False, "error": "same_author"}), 400
    db.session.commit()
    return jsonify({"ok": True, "author": _author_dict(target),
                    "relabelled": count})


@authors_bp.route("/authors/<int:author_id>/confirm", methods=["POST"])
def confirm(author_id):
    """Tentative → user_confirmed: the entry has earned file writes."""
    author = _get_author_or_404(author_id)
    if author.source == "tentative":
        author.source = "user_confirmed"
        db.session.commit()
    return jsonify({"ok": True, "author": _author_dict(author)})


@authors_bp.route("/authors/confirm-bulk", methods=["POST"])
def confirm_bulk():
    """Bulk variant of /confirm: flip every selected tentative entry to
    user_confirmed in one commit. Non-tentative ids in the selection are
    silently ignored (confirming them is a no-op), so the UI can offer
    checkboxes on all rows without special-casing already-confirmed ones."""
    ids = (request.get_json(silent=True) or {}).get("ids") or []
    ids = [i for i in ids if isinstance(i, int)]
    if not ids:
        return jsonify({"ok": False, "error": "no_ids"}), 400
    authors = Author.query.filter(
        Author.id.in_(ids), Author.source == "tentative"
    ).all()
    for author in authors:
        author.source = "user_confirmed"
    db.session.commit()
    return jsonify({"ok": True, "confirmed": len(authors)})


@authors_bp.route("/authors/<int:author_id>/verify", methods=["POST"])
def verify(author_id):
    """Authority anchoring (design step 5): resolve the canonical name
    against Wikidata and store QID/VIAF/LIBRIS. The canonical *name* is
    never changed here — anchoring adds ids, the user controls spelling.
    User-triggered from the manage view; never runs during scans."""
    from app.services.author_authority_lookup import lookup_author_authority

    author = _get_author_or_404(author_id)
    result = lookup_author_authority(author.canonical_name)
    if not result["ok"]:
        return jsonify({"ok": False, "error": "lookup_failed"}), 502
    if not result["matched"]:
        return jsonify({"ok": True, "matched": False})

    author.wikidata_qid = result["qid"] or author.wikidata_qid
    author.viaf_id = result["viaf_id"] or author.viaf_id
    author.libris_id = result["libris_id"] or author.libris_id
    author.source = "authority_linked"
    db.session.commit()
    return jsonify({
        "ok": True,
        "matched": True,
        "author": _author_dict(author),
        "label": result["label"],
        "description": result["description"],
    })


@authors_bp.route("/authors/adjudicate", methods=["POST"])
def adjudicate():
    """AI adjudicator for a likely-duplicate pair. Advisory only — the
    verdict is shown next to the pair; merging stays a user click (the
    iron rule: AI proposes, never merges)."""
    from app.services.ai_metadata import adjudicate_author_names, ai_is_configured

    data = request.get_json(silent=True) or {}
    a = db.session.get(Author, data.get("a_id") or 0)
    b = db.session.get(Author, data.get("b_id") or 0)
    if not a or not b:
        return jsonify({"ok": False, "error": "not_found"}), 404
    if not ai_is_configured():
        return jsonify({"ok": False, "error": "not_configured"}), 400

    result = adjudicate_author_names(a.canonical_name, b.canonical_name)
    if not result["ok"]:
        return jsonify({"ok": False, "error": result["error"]}), 502
    return jsonify({"ok": True, "verdict": result["verdict"],
                    "reason": result["reason"]})


@authors_bp.route("/authors/<int:author_id>/delete", methods=["POST"])
def delete(author_id):
    """Remove an unused entry (0 books). Entries with books must be
    merged or renamed instead — deletion would orphan the links."""
    author = _get_author_or_404(author_id)
    in_use = LibraryItem.query.filter_by(author_id=author.id).count()
    if in_use:
        return jsonify({"ok": False, "error": "in_use", "book_count": in_use}), 409
    from app.models import AuthorAlias
    AuthorAlias.query.filter_by(author_id=author.id).delete()
    db.session.delete(author)
    db.session.commit()
    return jsonify({"ok": True})
