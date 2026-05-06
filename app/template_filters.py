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


def localfmt(dt, fmt: str = "%b %d, %Y") -> str:
    """Format a UTC datetime in the user's local timezone (JST for this fork).

    Models store ``datetime.now(UTC).replace(tzinfo=None)`` — UTC time as a
    naïve value. Templates were rendering that with bare ``strftime``,
    so the date "next to" a UTC midnight rolled over a day before the
    JS timestamp formatter (which uses the browser's locale and
    correctly converts UTC → JST). Result was a flicker between
    server-rendered "Apr 29" and JS-rendered "Apr 30" on every page
    load. This filter brings the static fallback into the same TZ the
    JS uses, eliminating the flicker.

    Single-user fork: the locale is hard-coded to Asia/Tokyo. If a
    future user wants a different TZ this becomes a settings lookup.
    """
    if dt is None:
        return ""
    from datetime import timezone
    from zoneinfo import ZoneInfo

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo("Asia/Tokyo")).strftime(fmt)


def register(templates) -> None:
    """Attach all custom filters to a ``Jinja2Templates`` instance.

    Kept for callers that have already constructed a Jinja2Templates;
    new code should prefer ``make_templates()`` which builds and
    registers in one call.
    """
    from jinja2 import pass_context

    from app.i18n import DEFAULT_LANGUAGE, t as _t

    @pass_context
    def t_global(ctx, key: str) -> str:
        """Translate via the template's `settings.language`.

        Wired as a Jinja global so templates can write the natural
        ``{{ t("Library") }}`` instead of ``{{ "Library" | t(settings.language) }}``
        every time. The decorator gives us access to the rendering
        context, which already carries the singleton settings row on
        every route.
        """
        settings = ctx.get("settings")
        lang = getattr(settings, "language", None) or DEFAULT_LANGUAGE
        return _t(key, lang)

    templates.env.filters["autolink"] = autolink
    templates.env.filters["localfmt"] = localfmt
    # Both forms supported: `{{ t("Library") }}` and `{{ "Library" | t }}`.
    # The filter form is handy in chained expressions; the global form
    # is what the templates use for the bulk of UI strings.
    templates.env.filters["t"] = t_global
    templates.env.globals["t"] = t_global


def make_templates(directory: str = "app/templates"):
    """Construct a ``Jinja2Templates`` with all custom filters attached.

    Replaces the boilerplate that every router previously duplicated:

        templates = Jinja2Templates(directory="app/templates")
        from app.template_filters import register as _register_filters
        _register_filters(templates)

    Single call site, no post-construction setup, no E402 import-after-
    statement noise.
    """
    from fastapi.templating import Jinja2Templates
    templates = Jinja2Templates(directory=directory)
    register(templates)
    return templates
