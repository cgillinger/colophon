"""Centrala sökvägar för hela Bookstation-projektet.

Importeras av både app/-moduler och tools/-skript.
Definierar alla Path-konstanter på ett ställe.
"""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Användardata
DATA_DIR = PROJECT_ROOT / "data"
COVER_DIR = DATA_DIR / "covers"
EPUB_CACHE_DIR = DATA_DIR / "epub_cache"
LIBRARY_ROOT = PROJECT_ROOT / "bibliotek"

# Körtids-/variabler
VAR_DIR = PROJECT_ROOT / "var"
LOG_DIR = VAR_DIR / "logs"
DRM_STATUS_DIR = VAR_DIR / "drm"
DRM_STATUS_FILE = DRM_STATUS_DIR / "last_status.json"

# Butiksjobbshantering
JOB_DIR = VAR_DIR / "bookstore_jobs"
JOB_LOG_PATH = JOB_DIR / "current.log"
JOB_PID_PATH = JOB_DIR / "current.pid"
JOB_COMMAND_PATH = JOB_DIR / "current_command.txt"
SKIPPED_DRM_PATH = JOB_DIR / "skipped_drm.jsonl"

# Nedladdningar (Playwright-workers)
DOWNLOAD_ROOT = PROJECT_ROOT / "downloads" / "bookstores"
MYEBOOKFLOW_INPUT = DOWNLOAD_ROOT / "_myebookflow_input"

# Webbläsarprofiler (Playwright-workers)
PROFILE_ROOT = PROJECT_ROOT / "browser_profiles"
