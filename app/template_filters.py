"""Custom Jinja2 filters shared across all routers.

Each module that creates a ``Jinja2Templates`` instance must call
``register(templates)`` so the filters are available in templates
rendered through it.
"""
from __future__ import annotations

import re

from markupsafe import Markup, escape

# Bare http(s) URLs only — schemes like javascript: and data: must NEVER
# match. We also stop at any HTML-significant character so a user-typed
# `>` after a URL doesn't end up inside the href.
_URL_RE = re.compile(r"https?://[^\s<>\"']+")

# Sentence-ending punctuation that follows a URL almost always belongs
# to the surrounding prose, not the URL itself ("see https://x.com.").
# Parens and brackets are intentionally NOT included — they're real
# parts of Wikipedia-style URLs like /wiki/Foo_(bar).
_URL_TRAILING_PUNCT = ".,;:!?"

_LINK_CLASS = "underline text-blue-600 dark:text-blue-400"


def autolink(text: str | None) -> Markup:
    """Escape ``text`` for HTML and wrap bare http(s) URLs in anchor tags.

    Output is marked safe so the caller can drop it into a template
    without ``|safe``. Everything that isn't a matched URL goes through
    ``escape()`` so user-typed angle brackets, ampersands, and quotes
    cannot break out of the surrounding context.
    """
    if not text:
        return Markup("")
    parts: list[str] = []
    last = 0
    for m in _URL_RE.finditer(text):
        parts.append(str(escape(text[last:m.start()])))
        url = m.group(0)
        # Peel off trailing sentence punctuation so "see https://x.com."
        # doesn't link the period (and produce a 404 on click).
        trailing = ""
        while url and url[-1] in _URL_TRAILING_PUNCT:
            trailing = url[-1] + trailing
            url = url[:-1]
        if not url:
            # All punctuation, no URL — fall back to plain escape.
            parts.append(str(escape(trailing)))
            last = m.end()
            continue
        href = str(escape(url))
        label = str(escape(url))
        parts.append(
            f'<a href="{href}" target="_blank" rel="noopener nofollow" '
            f'class="{_LINK_CLASS}">{label}</a>'
        )
        if trailing:
            parts.append(str(escape(trailing)))
        last = m.end()
    parts.append(str(escape(text[last:])))
    return Markup("".join(parts))


def register(templates) -> None:
    """Attach all custom filters to a ``Jinja2Templates`` instance."""
    templates.env.filters["autolink"] = autolink
