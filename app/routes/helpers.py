from pathlib import Path

from flask import current_app, request
from werkzeug.utils import secure_filename

from app.models import LibraryItem


ALLOWED_COVER_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}


def get_item_or_404(item_id):
    return LibraryItem.query.get_or_404(item_id)


def get_mimetype(item):
    extension = item.extension.lower()

    mimetypes_map = {
        ".epub": "application/epub+zip",
        ".pdf": "application/pdf",
        ".txt": "text/plain; charset=utf-8",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".m4b": "audio/mp4",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".wav": "audio/wav",
        ".cbz": "application/vnd.comicbook+zip",
        ".cbr": "application/vnd.comicbook-rar",
    }

    return mimetypes_map.get(extension)


def save_uploaded_cover(item, uploaded_file):
    if not uploaded_file:
        return None

    if not uploaded_file.filename:
        return None

    original_name = secure_filename(uploaded_file.filename)
    extension = Path(original_name).suffix.lower()

    if extension not in ALLOWED_COVER_EXTENSIONS:
        return None

    cover_dir = Path(current_app.config["COVER_DIR"])
    cover_dir.mkdir(parents=True, exist_ok=True)

    cover_filename = f"manual_cover_{item.id}{extension}"
    cover_path = cover_dir / cover_filename

    uploaded_file.save(cover_path)

    return str(cover_path.resolve())


def get_int_form_value(name, default_value, minimum, maximum):
    try:
        value = int(request.form.get(name, default_value))
    except Exception:
        value = default_value

    if value < minimum:
        value = minimum

    if value > maximum:
        value = maximum

    return value
