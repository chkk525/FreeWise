"""
HTML parsing utilities for Meebook / Haoqing reading app exports.

Converts the Haoqing-flavoured HTML into a list of highlight dicts that
can be written straight into the database — no intermediate CSV step.
"""

import re
from datetime import datetime
from typing import List, Dict, Optional

from bs4 import BeautifulSoup


def extract_title_author(soup: BeautifulSoup) -> tuple[str, str]:
    """Extract book title and author from the H2 tag.

    Haoqing uses ``Title - Author`` inside a single ``<h2>``.
    """
    h2_tag = soup.find("h2")
    if not h2_tag:
        return "", ""
    title_author = h2_tag.get_text().strip()
    if " - " in title_author:
        parts = title_author.rsplit(" - ", 1)
        return parts[0].strip(), parts[1].strip()
    return title_author, ""


def parse_date(date_str: str) -> Optional[datetime]:
    """Parse a Haoqing date string into a datetime object.

    Accepts ``YYYY-MM-DD`` and ``YYYY-MM-DD HH:MM`` formats.
    Returns ``None`` on failure.
    """
    date_str = date_str.strip()
    if not date_str:
        return None
    try:
        if len(date_str) == 10:
            date_str += " 00:00"
        return datetime.strptime(date_str, "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def extract_highlights(html_content: str) -> List[Dict]:
    """Parse Haoqing HTML and return a list of highlight dicts.

    Each dict has the keys:
        title, author, text, note, location (int), location_type, created_at
    """
    soup = BeautifulSoup(html_content, "html.parser")
    title, author = extract_title_author(soup)

    raw: list[dict] = []
    highlight_divs = soup.find_all(
        "div",
        style=lambda x: x and "padding-top: 1em; padding-bottom: 1em" in x,
    )

    for div in highlight_divs:
        # Skip chapter headers
        if div.find(
            "span",
            style=lambda x: x
            and "color: #48b4c1" in x
            and "font-weight: bold" in x,
        ):
            continue

        # Date
        date_div = div.find(
            "div",
            style=lambda x: x and "border-left: 5px solid rgb(237,108,0)" in x,
        )
        created_at = parse_date(date_div.get_text()) if date_div else None

        # Highlight text
        highlight_div = div.find(
            "div",
            style=lambda x: x
            and "font-size: 12pt" in x
            and "border-left" not in (x or ""),
        )
        if not highlight_div:
            continue
        text = highlight_div.get_text().strip()
        if not text:
            continue

        # Note
        note = None
        table = div.find("table")
        if table:
            tds = table.find_all("td")
            if len(tds) >= 2:
                note_text = tds[1].get_text().strip()
                if note_text and note_text != "Underline notes":
                    note = note_text

        raw.append(
            {
                "title": title,
                "author": author or None,
                "text": text,
                "note": note,
                "created_at": created_at,
            }
        )

    # Reverse to chronological order and assign sequential location
    raw.reverse()
    for i, h in enumerate(raw, 1):
        h["location"] = i
        h["location_type"] = "order"

    return raw
