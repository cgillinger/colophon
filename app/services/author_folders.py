# Colophon – e-book metadata manager
"""Author subfolders for uploaded books (DESIGN-author-folders.md).

Uploads land flat in LIBRARY_DIR — deliberately. Moving a book into
LIBRARY_DIR/<Author>/ is an explicit user action from the edit modal
("root + move-on-demand"), performed when the metadata is at its best,
never silently. Core rules:

- The folder is the PRIMARY author's (position 0) canonical registry
  name — same convention as Calibre/Komga.
- Cosmetic consolidation: an existing sister folder whose
  author_folder_key() matches is reused ("arthur_c_clarke" lands in
  "Arthur C. Clarke"), otherwise the sanitized display spelling creates
  a new folder. Semantic variants are the registry's job, not ours.
- The whole format group moves together (EPUB+MOBI never split).
- Disk move + file_path update happen in one commit and the row id is
  preserved — reading state, rating and the Kobo entitlement all hang
  on LibraryItem.id. content_updated_at is deliberately NOT bumped
  (nothing device-visible changed; a bump would make every synced Kobo
  archive + re-download the book — see docs/kobo-reading-state-sync.md).
- If a copy of the file is known to live upstream, the old relative
  path is recorded in pending_upstream_cleanup so the push flow can
  remove the orphan (upstream_sync.py) once cleanup is enabled.
"""
import logging
import os
import re
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# Windows-reserved device names — refuse them as folder names even on
# Linux; the library may be consumed over SMB by Windows clients.
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {
    f"{base}{n}" for base in ("COM", "LPT") for n in range(1, 10)
}

_MAX_FOLDER_LEN = 120


def author_folder_key(name):
    """Cosmetic consolidation key for folder names.

    Casefold + NFC, dots/underscores become spaces, whitespace collapses:
    "arthur_c_clarke", "Arthur C. Clarke" and "ARTHUR C CLARKE" share a
    key. Deliberately does NOT touch semantic variation ("A. C. Clarke"
    is a different key) — that is fixed via the author field + a re-move.
    """
    s = unicodedata.normalize("NFC", str(name or "")).casefold()
    s = s.replace(".", " ").replace("_", " ")
    return re.sub(r"\s+", " ", s).strip()


def sanitize_folder_name(name):
    """A safe single folder name under LIBRARY_DIR, or None.

    Same hostile-input treatment as uploaded filenames (path components,
    control chars, filesystem-unsafe bytes), plus Windows-reserved names
    and a length cap. Returns None when nothing safe remains — the
    caller refuses the move rather than inventing a folder name.
    """
    name = os.path.basename(str(name or "").replace("\\", "/"))
    name = unicodedata.normalize("NFC", name)
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = re.sub(r'[<>:"|?*/\x00]', "", name)
    name = re.sub(r"\s+", " ", name).strip().strip(". ")
    if len(name) > _MAX_FOLDER_LEN:
        name = name[:_MAX_FOLDER_LEN].rstrip(". ")
    if not name or name in (".", "..") or name.upper() in _RESERVED_NAMES:
        return None
    return name


def resolve_author_folder(library_dir, author_name):
    """The folder name to use for this author: an existing sister folder
    with a matching key, else the sanitized display spelling. None when
    no safe name can be produced."""
    key = author_folder_key(author_name)
    if not key:
        return None
    try:
        entries = sorted(
            e.name for e in os.scandir(library_dir) if e.is_dir()
        )
    except OSError:
        entries = []
    for entry in entries:
        if author_folder_key(entry) == key:
            return entry
    return sanitize_folder_name(author_name)


def _library_root():
    from flask import current_app
    return os.path.realpath(current_app.config.get("LIBRARY_DIR", ""))


def _primary_author_name(session, item):
    """The primary (position 0) author's canonical registry name, with
    the string's first '&' part as fallback for unresolved stragglers."""
    from app.models import Author
    from app.services.author_authority import split_author_string

    if item.author_id:
        author = session.get(Author, item.author_id)
        if author and author.canonical_name.strip():
            return author.canonical_name.strip()
    parts = split_author_string(item.author or "")
    return parts[0] if parts else None


def _root_group_members(session, item, root):
    """The item plus its format siblings (same group_key) that also sit
    in the library root — they move together. Siblings already inside a
    folder are left where they are."""
    from app.models import LibraryItem

    members = [item]
    if item.group_key:
        for sibling in session.query(LibraryItem).filter(
            LibraryItem.group_key == item.group_key,
            LibraryItem.id != item.id,
        ).all():
            members.append(sibling)
    return [
        m for m in members
        if m.file_path
        and os.path.dirname(os.path.realpath(m.file_path)) == root
    ]


def describe_move(session, item):
    """Preview/eligibility for the modal button. Never touches disk.

    Returns {"eligible", "in_root", "reason", "folder", "targets":
    [{"id", "from", "to"}]} — reason set when not eligible:
    'not_in_root' / 'no_author' / 'bad_folder_name' / 'target_exists' /
    'file_missing'.
    """
    root = _library_root()
    result = {"eligible": False, "in_root": False, "reason": None,
              "folder": None, "targets": []}

    if not item.file_path or not os.path.isfile(item.file_path):
        result["reason"] = "file_missing"
        return result
    if os.path.dirname(os.path.realpath(item.file_path)) != root:
        result["reason"] = "not_in_root"
        return result
    result["in_root"] = True

    author_name = _primary_author_name(session, item)
    if not author_name:
        result["reason"] = "no_author"
        return result

    folder = resolve_author_folder(root, author_name)
    if not folder:
        result["reason"] = "bad_folder_name"
        return result

    # Belt and braces: the resolved target must stay under LIBRARY_DIR.
    target_dir = os.path.realpath(os.path.join(root, folder))
    if os.path.dirname(target_dir) != root:
        result["reason"] = "bad_folder_name"
        return result

    targets = []
    for member in _root_group_members(session, item, root):
        dest = os.path.join(target_dir, os.path.basename(member.file_path))
        if os.path.exists(dest):
            result["reason"] = "target_exists"
            result["folder"] = folder
            return result
        targets.append({"id": member.id, "from": member.file_path, "to": dest})

    result.update({"eligible": True, "folder": folder, "targets": targets})
    return result


def move_item_to_author_folder(session, item):
    """Perform the move: whole root format group onto disk + file_path
    in the same commit (caller commits). Returns the describe_move dict
    with 'moved' (count) added on success.

    Upstream bookkeeping per member: if a copy is known to exist
    upstream (tracked upstream_rel_path, or upstream_synced_at from
    before tracking — then the old rel path IS what was pushed), the old
    relative path is stored in pending_upstream_cleanup for the push
    flow. file_modified_by_colophon is stamped so the new path enters
    the push queue.
    """
    info = describe_move(session, item)
    if not info["eligible"]:
        return info

    root = _library_root()
    target_dir = os.path.join(root, info["folder"])
    os.makedirs(target_dir, exist_ok=True)

    by_id = {t["id"]: t for t in info["targets"]}
    moved = []
    try:
        for member in _root_group_members(session, item, root):
            plan = by_id.get(member.id)
            if not plan:
                continue
            shutil.move(plan["from"], plan["to"])
            moved.append(plan)

            old_rel = os.path.relpath(plan["from"], root)
            new_rel = os.path.relpath(plan["to"], root)
            upstream_copy = member.upstream_rel_path or (
                old_rel if member.upstream_synced_at else None
            )
            member.file_path = plan["to"]
            if upstream_copy and upstream_copy != new_rel:
                member.pending_upstream_cleanup = upstream_copy
            member.file_modified_by_colophon = datetime.utcnow()
    except Exception:
        # Best-effort rollback of already-moved files; the DB changes die
        # with the caller's rollback.
        for plan in moved:
            try:
                shutil.move(plan["to"], plan["from"])
            except OSError:
                logger.exception(
                    "move rollback failed for %s", plan["to"]
                )
        raise

    # A move is not a content change: suppress the content_updated_at
    # stamp (file_path is in _DEVICE_CONTENT_COLUMNS) so synced Kobos
    # don't archive + re-download an unchanged book.
    session.info["suppress_content_stamp"] = True
    try:
        session.flush()
    finally:
        session.info.pop("suppress_content_stamp", None)

    logger.info(
        "Moved %d file(s) to author folder %r", len(moved), info["folder"]
    )
    info["moved"] = len(moved)
    return info
