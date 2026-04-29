"""argparse CLI for the Kindle Notebook scraper.

Examples
--------

Initial headed login (writes ``storage_state.json``)::

    python -m scrapers.kindle login --state /work/state/storage_state.json

Headless scrape of every book in the Kindle library::

    python -m scrapers.kindle scrape \
        --state /work/state/storage_state.json \
        --output /work/output/kindle_highlights.json

Add ``--headed`` to ``scrape`` to watch the browser (useful for debugging
DOM changes on Amazon's side).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from logging import Logger
from pathlib import Path

from scrapers.kindle.scraper import (
    DEFAULT_LOGIN_TIMEOUT_SECONDS,
    run_login,
    run_scrape,
)

DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s :: %(message)s"


def _configure_logging(verbose: bool) -> Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format=DEFAULT_LOG_FORMAT)
    return logging.getLogger("scrapers.kindle.cli")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scrapers.kindle",
        description="Scrape Kindle Notebook highlights into a JSON file.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="enable DEBUG logging",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser(
        "login",
        help="Open a headed Chromium so the user can sign in to Amazon, "
        "then save storage_state.json.",
    )
    p_login.add_argument(
        "--state",
        required=True,
        type=Path,
        help="Path to write storage_state.json (Playwright session)",
    )
    p_login.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_LOGIN_TIMEOUT_SECONDS,
        help=f"Login timeout in seconds (default: {DEFAULT_LOGIN_TIMEOUT_SECONDS})",
    )

    p_scrape = sub.add_parser(
        "scrape",
        help="Scrape every book + highlight using a stored Amazon session.",
    )
    p_scrape.add_argument(
        "--state",
        required=True,
        type=Path,
        help="Path to existing storage_state.json (created by `login`)",
    )
    p_scrape.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path to write the kindle_highlights.json export.",
    )
    p_scrape.add_argument(
        "--headed",
        action="store_true",
        help="Run Chromium with a visible window (default: headless).",
    )
    p_scrape.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_LOGIN_TIMEOUT_SECONDS,
        help=f"Per-page wait timeout in seconds (default: {DEFAULT_LOGIN_TIMEOUT_SECONDS})",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    log = _configure_logging(verbose=args.verbose)

    if args.command == "login":
        asyncio.run(
            run_login(
                storage_state_path=args.state,
                login_timeout_seconds=args.timeout,
                log=log,
            )
        )
        return 0

    if args.command == "scrape":
        asyncio.run(
            run_scrape(
                storage_state_path=args.state,
                output_path=args.output,
                headless=not args.headed,
                login_timeout_seconds=args.timeout,
                log=log,
            )
        )
        return 0

    # argparse should have already errored out, but be defensive.
    print(f"unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
