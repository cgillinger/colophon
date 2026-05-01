#!/usr/bin/env python3
"""Bookstation bookstore web worker — tunnt CLI-skal som delegerar till tools/stores/."""
import argparse
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.stores.adlibris import download_adlibris
from tools.stores.common import STORE_URLS
from tools.stores.generic import generic_download, login_window, watch_downloads


def _configure_logging():
    level_name = os.environ.get("BOOKSTATION_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(message)s",
        stream=sys.stdout,
        force=True,
    )


def main():
    _configure_logging()

    parser = argparse.ArgumentParser(description="Bookstation bookstore web worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("login")
    login_parser.add_argument("--store", choices=sorted(STORE_URLS.keys()), required=True)
    login_parser.add_argument("--url", default="")

    watch_parser = subparsers.add_parser("watch")
    watch_parser.add_argument("--store", choices=sorted(STORE_URLS.keys()), required=True)
    watch_parser.add_argument("--url", default="")

    generic_parser = subparsers.add_parser("generic-download")
    generic_parser.add_argument("--store", choices=sorted(STORE_URLS.keys()), required=True)
    generic_parser.add_argument("--url", default="")
    generic_parser.add_argument("--max-downloads", type=int, default=20)
    generic_parser.add_argument("--dry-run", action="store_true")
    generic_parser.add_argument("--headless", action="store_true")

    adlibris_parser = subparsers.add_parser("download-adlibris")
    adlibris_parser.add_argument("--url", default=STORE_URLS["adlibris"]["library_url"])
    adlibris_parser.add_argument("--max-downloads", type=int, default=999)
    adlibris_parser.add_argument("--dry-run", action="store_true")
    adlibris_parser.add_argument("--headless", action="store_true")

    args = parser.parse_args()

    if args.command == "login":
        config = STORE_URLS[args.store]
        login_window(args.store, args.url or config.get("login_url") or config["start_url"])

    elif args.command == "watch":
        config = STORE_URLS[args.store]
        watch_downloads(args.store, args.url or config.get("library_url") or config["start_url"])

    elif args.command == "generic-download":
        config = STORE_URLS[args.store]
        generic_download(
            store=args.store,
            url=args.url or config.get("library_url") or config["start_url"],
            max_downloads=args.max_downloads,
            dry_run=args.dry_run,
            headless=args.headless,
        )

    elif args.command == "download-adlibris":
        download_adlibris(
            url=args.url,
            max_downloads=args.max_downloads,
            dry_run=args.dry_run,
            headless=args.headless,
        )


if __name__ == "__main__":
    main()
