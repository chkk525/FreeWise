"""Build the daily email digest.

Pulls three sections from the DB:
- Today's deterministic highlight (same logic as /highlights/today)
- On-this-day past-year highlights
- Library-health summary (active count, untagged count, dup groups)

Returns a ``Digest`` with subject + plain-text + HTML bodies. The CLI
command and any scheduler trigger compose Digest → email.send_email.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy.orm import selectinload
from sqlmodel import Session, func, select

from app.models import Highlight, HighlightTag, Tag


@dataclass(frozen=True)
class Digest:
    subject: str
    text_body: str
    html_body: str


def _today_pick(session: Session, user_id: int = 1) -> Optional[Highlight]:
    """Same deterministic pick as /highlights/today — sha256 of today's
    ISO date, modulo the active-highlight count."""
    ids = session.exec(
        select(Highlight.id)
        .where(Highlight.user_id == user_id)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .order_by(Highlight.id.asc())
    ).all()
    if not ids:
        return None
    seed = hashlib.sha256(date.today().isoformat().encode()).digest()
    idx = int.from_bytes(seed[:8], "big") % len(ids)
    chosen_id = ids[idx]
    return session.exec(
        select(Highlight)
        .options(selectinload(Highlight.book))
        .where(Highlight.id == chosen_id)
    ).first()


def _on_this_day(session: Session, user_id: int = 1, limit: int = 5) -> list[Highlight]:
    today = date.today()
    mmdd = f"{today.month:02d}-{today.day:02d}"
    return list(session.exec(
        select(Highlight)
        .options(selectinload(Highlight.book))
        .where(Highlight.user_id == user_id)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .where(func.strftime("%m-%d", Highlight.created_at) == mmdd)
        .order_by(Highlight.created_at.desc())
        .limit(limit)
    ).all())


def _library_health(session: Session, user_id: int = 1) -> dict:
    active = int(session.exec(
        select(func.count(Highlight.id))
        .where(Highlight.user_id == user_id)
        .where(Highlight.is_discarded == False)  # noqa: E712
    ).one() or 0)

    dup_groups = session.exec(
        select(func.count(Highlight.id))
        .where(Highlight.user_id == user_id)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .group_by(func.substr(Highlight.text, 1, 80))
        .having(func.count(Highlight.id) >= 2)
    ).all()

    tagged = int(session.exec(
        select(func.count(func.distinct(HighlightTag.highlight_id)))
        .join(Tag, Tag.id == HighlightTag.tag_id)
        .join(Highlight, Highlight.id == HighlightTag.highlight_id)
        .where(Highlight.user_id == user_id)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .where(~Tag.name.in_(["favorite", "discard"]))
    ).one() or 0)

    return {
        "active": active,
        "dup_groups": len(dup_groups),
        "untagged": max(0, active - tagged),
    }


def _attribution(h: Highlight) -> str:
    """Human attribution string: "— Author, Title" or "— Title" or ''."""
    if not h.book:
        return ""
    title = (h.book.title or "").strip()
    author = (getattr(h.book, "author", None) or "").strip()
    if title and author:
        return f"— {author}, {title}"
    if title:
        return f"— {title}"
    if author:
        return f"— {author}"
    return ""


def _render_text(today_pick: Optional[Highlight], on_this_day: list, health: dict) -> str:
    lines: list[str] = [f"FreeWise digest — {date.today().isoformat()}", "=" * 40, ""]
    if today_pick:
        lines.append("TODAY'S PICK")
        lines.append("-" * 40)
        lines.append(today_pick.text or "")
        attr = _attribution(today_pick)
        if attr:
            lines.append(attr)
        lines.append("")
    if on_this_day:
        today = date.today()
        lines.append(f"ON THIS DAY ({today.month:02d}-{today.day:02d}, past years)")
        lines.append("-" * 40)
        for h in on_this_day:
            year = h.created_at.year if h.created_at else "?"
            text = (h.text or "")[:200]
            if len(h.text or "") > 200:
                text += "…"
            lines.append(f"[{year}] {text}")
            attr = _attribution(h)
            if attr:
                lines.append(f"        {attr}")
            lines.append("")
    lines.append("LIBRARY HEALTH")
    lines.append("-" * 40)
    lines.append(f"Active highlights: {health['active']}")
    lines.append(f"Duplicate groups: {health['dup_groups']}")
    lines.append(f"Untagged: {health['untagged']}")
    return "\n".join(lines)


def _esc(s: str) -> str:
    """Minimal HTML escape for body text."""
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_html(today_pick: Optional[Highlight], on_this_day: list, health: dict) -> str:
    parts: list[str] = [
        '<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
        'max-width:640px;margin:0 auto;padding:24px;color:#111;">',
        f'<h1 style="font-size:18px;color:#666;border-bottom:1px solid #eee;'
        f'padding-bottom:8px;">FreeWise digest — {date.today().isoformat()}</h1>',
    ]
    if today_pick:
        parts.append('<h2 style="font-size:14px;color:#444;margin-top:20px;">Today\'s pick</h2>')
        parts.append(
            '<blockquote style="margin:0;padding:16px 20px;border-left:4px solid #f59e0b;'
            'background:#fffbeb;font-family:Georgia,serif;font-size:16px;line-height:1.5;">'
            f'{_esc(today_pick.text or "")}'
            f'<footer style="font-size:13px;color:#666;margin-top:8px;">{_esc(_attribution(today_pick))}</footer>'
            '</blockquote>'
        )
    if on_this_day:
        today = date.today()
        parts.append(
            f'<h2 style="font-size:14px;color:#444;margin-top:24px;">'
            f'On this day ({today.month:02d}-{today.day:02d}, past years)</h2>'
        )
        for h in on_this_day:
            year = h.created_at.year if h.created_at else "?"
            text = (h.text or "")[:200]
            if len(h.text or "") > 200:
                text += "…"
            parts.append(
                '<div style="margin:12px 0;padding:12px 16px;border-left:3px solid #2563eb;'
                'background:#eff6ff;">'
                f'<div style="font-family:monospace;font-size:11px;color:#2563eb;">{year}</div>'
                f'<div style="font-family:Georgia,serif;font-size:15px;line-height:1.5;'
                f'margin-top:4px;">{_esc(text)}</div>'
                f'<div style="font-size:12px;color:#666;margin-top:4px;">{_esc(_attribution(h))}</div>'
                '</div>'
            )
    parts.append('<h2 style="font-size:14px;color:#444;margin-top:24px;">Library health</h2>')
    parts.append(
        '<table cellpadding="6" style="font-size:13px;color:#444;border-collapse:collapse;">'
        f'<tr><td style="color:#666;">Active highlights</td><td><strong>{health["active"]}</strong></td></tr>'
        f'<tr><td style="color:#666;">Duplicate groups</td><td><strong>{health["dup_groups"]}</strong></td></tr>'
        f'<tr><td style="color:#666;">Untagged</td><td><strong>{health["untagged"]}</strong></td></tr>'
        '</table>'
    )
    parts.append('</body></html>')
    return "".join(parts)


def build_digest(session: Session, user_id: int = 1) -> Digest:
    """Compose the daily Digest. Single function the CLI / scheduler call."""
    pick = _today_pick(session, user_id=user_id)
    history = _on_this_day(session, user_id=user_id)
    health = _library_health(session, user_id=user_id)
    subject = f"FreeWise digest — {date.today().isoformat()}"
    return Digest(
        subject=subject,
        text_body=_render_text(pick, history, health),
        html_body=_render_html(pick, history, health),
    )
