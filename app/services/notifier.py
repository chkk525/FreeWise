"""Tiny webhook notifier mirroring tools/kindle_notify.sh on the QNAP side.

Posts a Slack-compatible JSON payload to ``FREEWISE_NOTIFY_URL`` when set.
Used by the Kindle auto-import watcher to confirm imports landed in the DB,
which is the *receiving* end of the QNAP cron's "scrape OK" notification —
together they let the user verify the full pipeline from one place.

Disabled by default. Enabled by setting ``FREEWISE_NOTIFY_URL``.
``FREEWISE_NOTIFY_ON``: ``failure`` (default) | ``always`` | ``never``.
"""

from __future__ import annotations

import json
import logging
import os
import socket
from typing import Literal

import httpx


logger = logging.getLogger(__name__)


NOTIFY_URL_ENV = "FREEWISE_NOTIFY_URL"
NOTIFY_ON_ENV = "FREEWISE_NOTIFY_ON"
NOTIFY_HOST_ENV = "FREEWISE_NOTIFY_HOST"

Status = Literal["success", "failure", "info"]


def notify(
    status: Status,
    message: str,
    *,
    extra: dict[str, object] | None = None,
    timeout_seconds: float = 10.0,
) -> bool:
    """Best-effort POST to the configured webhook.

    Returns True if a request was sent and accepted (2xx). Returns False if
    the feature is disabled, the mode skipped this status, or the request
    failed for any reason. Never raises — the caller should not have to wrap.
    """

    url = os.environ.get(NOTIFY_URL_ENV)
    if not url:
        return False

    mode = (os.environ.get(NOTIFY_ON_ENV) or "failure").lower()
    if mode == "never":
        return False
    if mode == "failure" and status == "success":
        return False

    host = os.environ.get(NOTIFY_HOST_ENV) or socket.gethostname() or "freewise"
    emoji = {"success": ":white_check_mark:", "failure": ":x:", "info": ":information_source:"}.get(
        status, ":grey_question:"
    )
    text = f"{emoji} FreeWise {status} on {host}: {message}"

    payload: dict[str, object] = {
        "text": text,
        "status": status,
        "host": host,
        "service": "freewise",
    }
    if extra:
        payload.update(extra)

    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            r = client.post(url, json=payload)
            r.raise_for_status()
        return True
    except Exception:  # noqa: BLE001
        logger.exception("notifier: webhook POST failed (url=%s)", _redact(url))
        return False


def _redact(url: str) -> str:
    """Strip tokens / secret paths from the URL when logging."""
    if "://" not in url:
        return "<bad-url>"
    scheme, _, rest = url.partition("://")
    host = rest.split("/", 1)[0]
    return f"{scheme}://{host}/…"
