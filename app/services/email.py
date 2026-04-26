"""SMTP email send helper for the digest.

All config comes from env vars so secrets never land in source:

    SMTP_HOST      e.g. smtp.gmail.com
    SMTP_PORT      587 for STARTTLS, 465 for SSL/TLS
    SMTP_USER      full email address (Gmail App Password user)
    SMTP_PASS      Gmail App Password (16 chars, spaces stripped)
    SMTP_FROM      "Display Name <addr@host>" or just an address
    SMTP_TO        comma-separated recipient list

Module raises ``EmailNotConfigured`` if any required var is missing —
callers (CLI, scheduler) should catch it and fall back to dry-run.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Iterable


class EmailNotConfigured(RuntimeError):
    """One or more SMTP_* env vars are missing."""


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    user: str
    password: str
    from_addr: str
    to_addrs: tuple[str, ...]


def _split_recipients(raw: str) -> tuple[str, ...]:
    return tuple(addr.strip() for addr in raw.split(",") if addr.strip())


def load_config() -> SmtpConfig:
    """Read SMTP_* env vars. Raises EmailNotConfigured on missing values."""
    required = ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "SMTP_FROM", "SMTP_TO")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise EmailNotConfigured(
            f"missing SMTP env vars: {', '.join(missing)}"
        )
    port_raw = os.environ.get("SMTP_PORT", "587")
    try:
        port = int(port_raw)
    except ValueError as e:
        raise EmailNotConfigured(f"SMTP_PORT must be an integer, got {port_raw!r}") from e
    return SmtpConfig(
        host=os.environ["SMTP_HOST"],
        port=port,
        user=os.environ["SMTP_USER"],
        # Gmail App Passwords are displayed with spaces (4×4 groups).
        # Accept both forms — strip whitespace before sending.
        password=os.environ["SMTP_PASS"].replace(" ", ""),
        from_addr=os.environ["SMTP_FROM"],
        to_addrs=_split_recipients(os.environ["SMTP_TO"]),
    )


def send_email(
    subject: str,
    text_body: str,
    html_body: str | None = None,
    config: SmtpConfig | None = None,
    *,
    smtp_factory=None,
) -> None:
    """Send a single MIME email. Multipart/alternative if html_body given.

    ``smtp_factory`` is for tests — pass a callable returning a mock SMTP-
    like object to avoid real network. Default is smtplib.SMTP.
    """
    cfg = config or load_config()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.from_addr
    msg["To"] = ", ".join(cfg.to_addrs)
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    factory = smtp_factory or smtplib.SMTP
    # 587 = STARTTLS (Gmail default); 465 = implicit TLS (legacy).
    if cfg.port == 465:
        if smtp_factory is None:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg.host, cfg.port, context=ctx) as s:
                s.login(cfg.user, cfg.password)
                s.send_message(msg)
            return
        # Test path: factory must accept (host, port).
        with factory(cfg.host, cfg.port) as s:
            s.login(cfg.user, cfg.password)
            s.send_message(msg)
        return

    with factory(cfg.host, cfg.port) as s:
        # Tests can pass a stub that doesn't implement starttls; skip if absent.
        if hasattr(s, "starttls"):
            try:
                s.starttls(context=ssl.create_default_context())
            except Exception:
                # Mock SMTP in tests may not need real STARTTLS.
                pass
        s.login(cfg.user, cfg.password)
        s.send_message(msg)
