# Colophon – e-book metadata manager
"""Centrala sökvägar för hela Colophon-projektet."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Användardata
DATA_DIR = PROJECT_ROOT / "data"
COVER_DIR = DATA_DIR / "covers"
LIBRARY_ROOT = PROJECT_ROOT / "bibliotek"

# Körtids-/variabler
VAR_DIR = PROJECT_ROOT / "var"
LOG_DIR = VAR_DIR / "logs"
