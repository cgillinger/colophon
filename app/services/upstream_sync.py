# Colophon – e-book metadata manager
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def upstream_configured() -> bool:
    """Return True if upstream dir is set (env or db) and the path exists."""
    from app.services.app_settings import get_upstream_dir
    upstream_dir = get_upstream_dir()
    if not upstream_dir:
        return False
    return os.path.isdir(upstream_dir)


def pull_from_upstream():
    """Generator: pull new/updated files from upstream into the local library.

    Yields SSE-style dicts with type 'progress' or 'done'.
    Uses rsync --update so locally-modified files are never overwritten.
    --delete is intentionally omitted to prevent data loss.
    """
    from flask import current_app
    from app.services.app_settings import get_upstream_dir

    upstream_dir = (get_upstream_dir() or "").rstrip("/")
    library_dir = current_app.config.get("LIBRARY_DIR", "").rstrip("/")

    if not upstream_dir or not os.path.isdir(upstream_dir):
        return

    # Require at least one file to be present — guards against unmounted volumes.
    has_files = any(True for _ in Path(upstream_dir).rglob("*") if _.is_file())
    if not has_files:
        logger.warning("upstream_sync: upstream directory appears empty, skipping pull")
        return

    cmd = [
        "rsync",
        "-a",
        "--update",
        "--itemize-changes",
        upstream_dir + "/",
        library_dir + "/",
    ]

    added = 0
    updated = 0

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        for line in proc.stdout:
            line = line.rstrip("\n")
            if not line:
                continue

            # rsync --itemize-changes format: "<YXcstpoguax> filename"
            # First char: < (sent), > (received), c (local change), . (no change)
            # Second char: f (file), d (dir), L (symlink)
            if len(line) < 10:
                continue

            flags = line[:11]
            filename = line[12:] if len(line) > 12 else ""

            if not filename or flags.startswith("."):
                continue

            # Determine action from flags
            if flags[0] == ">":
                if flags[2] == "+":
                    action = "new"
                    added += 1
                else:
                    action = "updated"
                    updated += 1
            else:
                continue

            yield {"type": "progress", "file": filename, "action": action}

        proc.wait()

        if proc.returncode not in (0, 24):  # 24 = partial transfer (vanishing files)
            stderr = proc.stderr.read()
            logger.error("rsync pull failed (rc=%d): %s", proc.returncode, stderr)

    except FileNotFoundError:
        logger.error("upstream_sync: rsync not found")
        return
    except Exception as exc:
        logger.exception("upstream_sync: pull failed: %s", exc)
        return

    yield {"type": "done", "added": added, "updated": updated, "deleted": 0}


def push_to_upstream():
    """Generator: push locally-modified files back to upstream.

    Only copies files that Colophon itself has written (file_modified_by_colophon
    is set and newer than upstream_synced_at). Yields SSE-style dicts.
    """
    from flask import current_app
    from app.models import db, LibraryItem
    from app.services.app_settings import get_upstream_dir

    upstream_dir = (get_upstream_dir() or "").rstrip("/")
    library_dir = current_app.config.get("LIBRARY_DIR", "").rstrip("/")

    if not upstream_dir or not os.path.isdir(upstream_dir):
        return

    # Require upstream to be mounted (not empty).
    has_files = any(True for _ in Path(upstream_dir).rglob("*") if _.is_file())
    if not has_files:
        logger.warning("upstream_sync: upstream directory appears empty, skipping push")
        return

    items = _pending_query().all()

    total = len(items)
    synced = 0
    errors = 0

    for i, item in enumerate(items, start=1):
        try:
            if not item.file_path or not os.path.exists(item.file_path):
                raise FileNotFoundError(f"source not found: {item.file_path}")

            # Compute relative path from library root.
            rel_path = os.path.relpath(item.file_path, library_dir)
            dest_path = os.path.join(upstream_dir, rel_path)

            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copy2(item.file_path, dest_path)

            # Copy cover alongside the book if available.
            if item.cover_path and os.path.isfile(item.cover_path):
                cover_ext = os.path.splitext(item.cover_path)[1] or ".jpg"
                book_stem = os.path.splitext(os.path.basename(dest_path))[0]
                cover_dest = os.path.join(os.path.dirname(dest_path), book_stem + cover_ext)
                shutil.copy2(item.cover_path, cover_dest)

            item.upstream_synced_at = datetime.utcnow()
            synced += 1

        except Exception as exc:
            logger.error("upstream_sync: push failed for %r: %s", item.title, exc)
            errors += 1
            yield {"type": "file_error", "file": item.title, "error": str(exc)}
            continue

        yield {"type": "progress", "file": item.title, "current": i, "total": total}

    db.session.commit()
    yield {"type": "done", "synced": synced, "errors": errors}


def _pending_query():
    """Shared query for items modified by Colophon but not yet pushed upstream.

    Single source of truth so get_unsynced_count() and list_pending_items()
    can never drift apart.
    """
    from app.models import db, LibraryItem

    return LibraryItem.query.filter(
        LibraryItem.file_modified_by_colophon.isnot(None),
        db.or_(
            LibraryItem.upstream_synced_at.is_(None),
            LibraryItem.file_modified_by_colophon > LibraryItem.upstream_synced_at,
        ),
    )


def get_unsynced_count() -> int:
    """Return number of items modified by Colophon but not yet pushed upstream."""
    if not upstream_configured():
        return 0

    return _pending_query().count()


def list_pending_items() -> list:
    """Return the items pending upstream push as a list of dicts. No side effects.

    Each dict: {"id", "title", "author", "file_modified" (isoformat),
    "last_synced" (isoformat or None)}.
    """
    if not upstream_configured():
        return []

    items = _pending_query().all()
    return [
        {
            "id": item.id,
            "title": item.title,
            "author": item.author,
            "file_modified": item.file_modified_by_colophon.isoformat()
            if item.file_modified_by_colophon
            else None,
            "last_synced": item.upstream_synced_at.isoformat()
            if item.upstream_synced_at
            else None,
        }
        for item in items
    ]
