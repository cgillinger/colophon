# Colophon – e-book metadata manager
"""Downscaled cover thumbnails, shared by the web UI and the Kobo endpoint.

Originals are large — several MB is common — and both consumers fetch one
cover per book. For the browser that is a slow catalogue page; for a Kobo it
is the whole "downloading book covers" phase, which is what makes a large
library look hung. Measured on a real 639-book library: 187 MB of originals
against 20 MB at 320 px, i.e. 11 %.

The cache key is derived from the source file's identity (realpath + mtime +
size) and the width, so it changes automatically whenever a cover is replaced
or rewritten. That means none of the (many) ``cover_path`` write sites need
explicit invalidation — a new cover simply misses the old thumb. Thumbnails
live in a dedicated ``thumbs/`` subdir; originals are untouched.
"""
import hashlib
import logging
import os

from flask import current_app

logger = logging.getLogger(__name__)

# Allowlisted thumbnail widths. A requested width snaps up to the smallest of
# these so the on-disk cache can never explode into one file per arbitrary
# width — the Kobo asks for whatever its layout wants. 320 covers the shelf
# (--cover-width:160px @2x) and is crisp for the 80px table cell; 160/640 are
# kept for smaller widgets / retina.
THUMB_WIDTHS = (160, 320, 640)


def snap_width(requested):
    """Snap a requested width up to the nearest allowlisted one."""
    return min((w for w in THUMB_WIDTHS if w >= requested), default=THUMB_WIDTHS[-1])


def get_or_make_thumbnail(src_path, width):
    """Return a path to a cached downscaled JPEG of *src_path* at *width*, or
    None if Pillow is unavailable or generation fails.

    The None return is the contract: callers fall back to the original file,
    so a host without an imaging library keeps working unchanged.
    """
    try:
        from PIL import Image, ImageOps
    except Exception:
        return None
    try:
        st = os.stat(src_path)
    except OSError:
        return None

    key = "%s|%d|%d|%d" % (
        os.path.realpath(src_path), st.st_mtime_ns, st.st_size, width,
    )
    name = hashlib.sha1(key.encode("utf-8")).hexdigest() + ".jpg"
    thumb_dir = os.path.join(current_app.config["COVER_DIR"], "thumbs")
    dest = os.path.join(thumb_dir, name)
    if os.path.exists(dest):
        return dest

    try:
        os.makedirs(thumb_dir, exist_ok=True)
        with Image.open(src_path) as im:
            im = ImageOps.exif_transpose(im)  # respect embedded orientation
            # Flatten any transparency onto white so JPEG output is sane.
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            if im.width > width:
                height = max(1, round(im.height * width / im.width))
                im = im.resize((width, height), Image.LANCZOS)
            tmp = dest + ".tmp"
            im.save(tmp, "JPEG", quality=82, optimize=True, progressive=True)
            os.replace(tmp, dest)  # atomic publish; concurrent workers are safe
        return dest
    except Exception:
        logger.exception("thumbnail generation failed for %s", src_path)
        return None
