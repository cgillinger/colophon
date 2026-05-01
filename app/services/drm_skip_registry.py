import json
from datetime import datetime
from pathlib import Path

from app.paths import SKIPPED_DRM_PATH as REGISTRY_PATH


def record_skipped_drm(store, title, reason, filename="", path=""):
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "store": (store or "").strip(),
        "title": (title or "").strip(),
        "reason": (reason or "").strip(),
        "filename": (filename or "").strip(),
        "path": (path or "").strip(),
    }

    with REGISTRY_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def read_skipped_drm(limit=200):
    if not REGISTRY_PATH.exists():
        return []

    rows = []

    with REGISTRY_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue

            try:
                rows.append(json.loads(line))
            except Exception:
                continue

    rows.reverse()
    return rows[:limit]
