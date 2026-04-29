"""Validate + atomically write Playwright storage_state.json files.

Used by the dashboard's POST /dashboard/kindle/cookie route. Replaces
the old `ssh + rsync` workflow for refreshing the Amazon login cookie
that the monthly QNAP scraper uses.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_BYTES = 100_000
REQUIRED_COOKIE_NAMES = {"at-main", "session-token"}
AMAZON_DOMAIN_SUFFIXES = (".amazon.com", ".amazon.co.jp", "amazon.com", "amazon.co.jp")


class CookieValidationError(ValueError):
    """Raised when an uploaded payload is not a valid Playwright storage_state."""


class ScrapeRunningError(RuntimeError):
    """Raised when a scrape is in flight; cookie write must be deferred."""


def _scrape_running() -> bool:
    state_file = os.environ.get("KINDLE_SCRAPE_STATE_FILE")
    if not state_file:
        return False
    p = Path(state_file)
    if not p.is_file():
        return False
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("finished_at") is None and data.get("pid") is not None


def _validate(payload: bytes) -> dict[str, Any]:
    if len(payload) > MAX_BYTES:
        raise CookieValidationError(
            f"File size {len(payload)} bytes exceeds {MAX_BYTES} byte limit."
        )
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CookieValidationError(f"Invalid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise CookieValidationError("Top-level must be a JSON object.")
    cookies = data.get("cookies")
    if not isinstance(cookies, list) or not cookies:
        raise CookieValidationError(
            "Missing or empty 'cookies' array — not a Playwright storage_state.json."
        )

    cookie_names = {c.get("name") for c in cookies if isinstance(c, dict)}
    if not cookie_names & REQUIRED_COOKIE_NAMES:
        raise CookieValidationError(
            f"None of {sorted(REQUIRED_COOKIE_NAMES)} cookies found — "
            f"this does not look like a logged-in amazon session."
        )

    has_amazon_domain = any(
        any(d.get("domain", "").endswith(suffix) for suffix in AMAZON_DOMAIN_SUFFIXES)
        for d in cookies if isinstance(d, dict)
    )
    if not has_amazon_domain:
        raise CookieValidationError(
            "No amazon.com / amazon.co.jp cookie domains found."
        )
    return data


def write_storage_state(payload: bytes, target_path: Path) -> dict[str, Any]:
    """Validate, then atomically write storage_state.json. Raises on conflict."""
    if _scrape_running():
        raise ScrapeRunningError(
            "A Kindle scrape is currently running. Wait or cancel it first."
        )
    data = _validate(payload)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target_path.with_suffix(target_path.suffix + f".tmp.{os.getpid()}")
    tmp_path.write_bytes(payload)
    os.replace(tmp_path, target_path)
    os.chmod(target_path, 0o644)
    return read_storage_state_status(target_path)


def read_storage_state_status(path: Path) -> dict[str, Any]:
    """Return a JSON-serializable summary of the cookie file's state."""
    if not path.is_file():
        return {"exists": False}
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"exists": True, "valid": False, "size": len(raw)}

    cookies = data.get("cookies", []) if isinstance(data, dict) else []
    domains = sorted({c.get("domain") for c in cookies
                       if isinstance(c, dict) and c.get("domain")})
    has_at_main = any(c.get("name") == "at-main" for c in cookies if isinstance(c, dict))
    return {
        "exists": True,
        "valid": True,
        "size": len(raw),
        "cookie_count": len(cookies),
        "domains": [d for d in domains if d],
        "has_at_main": has_at_main,
        "mtime": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
    }
