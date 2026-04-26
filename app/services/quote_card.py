"""Render a 1200×630 PNG quote card for a highlight (U98).

Twitter / Facebook / Slack expect og:image at 1200×630 ("summary_large_image").
The card design follows a vercel/og-style approach in spirit — declarative
layout described once, rasterized via Pillow. Pillow is pure-Python with
wheels for every platform, no system cairo / chromium needed.

The card has three regions:

  ┌─────────────────────────────────────────────────────┐
  │  ▌ "Highlight text wraps here, up to N lines and    │
  │  ▌  trims with an ellipsis if it overflows."        │
  │  ▌                                                  │
  │                                                      │
  │  — Author, Title                                     │
  │                                            FreeWise │
  └─────────────────────────────────────────────────────┘

A vertical amber bar on the left mirrors the "blockquote" styling used in
the email digest and the existing in-app blockquote borders.
"""
from __future__ import annotations

import io
import textwrap
import unicodedata
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

# Card geometry — Twitter Large Image card spec.
WIDTH = 1200
HEIGHT = 630
PADDING_X = 80
PADDING_Y = 70
BAR_X = 60
BAR_WIDTH = 8

# Color palette mirrors the in-app email digest blockquote.
BG_COLOR = (255, 251, 235)      # amber-50
BAR_COLOR = (245, 158, 11)      # amber-500
TEXT_COLOR = (17, 24, 39)       # gray-900
META_COLOR = (107, 114, 128)    # gray-500
WATERMARK_COLOR = (156, 163, 175)  # gray-400

# Layout: line-wrap heuristics. Trigger CJK mode when ≥ 30% of the first
# 50 chars are unified CJK ideographs / kana / hangul — those scripts
# don't tokenize on whitespace and need character-based slicing.
ASCII_LINE_CHARS = 38
CJK_LINE_CHARS = 22
MAX_LINES = 9


def _is_cjk_char(c: str) -> bool:
    if not c:
        return False
    name = unicodedata.name(c, "")
    return ("CJK" in name) or ("HIRAGANA" in name) or ("KATAKANA" in name) or ("HANGUL" in name)


def _is_cjk_dominant(text: str) -> bool:
    sample = text[:50]
    if not sample:
        return False
    cjk = sum(1 for c in sample if _is_cjk_char(c))
    return cjk / len(sample) >= 0.3


def wrap_for_card(text: str) -> list[str]:
    """Greedy line wrap that handles ASCII (word-based) and CJK (char-based).

    Returns at most ``MAX_LINES`` lines. Overflow is signalled by an
    ellipsis character on the final line.
    """
    text = (text or "").strip()
    if not text:
        return []
    if _is_cjk_dominant(text):
        # Strip newlines so the slicer doesn't break mid-paragraph.
        flat = text.replace("\n", " ")
        lines = [flat[i:i + CJK_LINE_CHARS] for i in range(0, len(flat), CJK_LINE_CHARS)]
    else:
        # textwrap respects word boundaries; break_long_words handles URLs.
        lines = textwrap.wrap(text, width=ASCII_LINE_CHARS, break_long_words=True)

    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES]
        # Replace last char with ellipsis to signal truncation.
        last = lines[-1]
        lines[-1] = (last[:-1] if len(last) > 1 else last) + "…"
    return lines


# Font discovery: Pillow ships with a tiny default that doesn't render
# Japanese. We probe a short list of common system paths and use the
# first match. None still renders fine for ASCII via DejaVuSans.
_BODY_CANDIDATES = (
    # macOS
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    # Linux (Debian/Ubuntu)
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    # Alpine
    "/usr/share/fonts/dejavu/DejaVuSerif.ttf",
)
_META_CANDIDATES = (
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
)


def _first_existing(paths: tuple[str, ...]) -> Optional[str]:
    for p in paths:
        if Path(p).is_file():
            return p
    return None


def _load_font(paths: tuple[str, ...], size: int) -> ImageFont.ImageFont:
    path = _first_existing(paths)
    if path:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            pass
    # Pillow's bundled bitmap font — no Japanese glyphs but won't crash.
    return ImageFont.load_default()


def _attribution(book_title: Optional[str], book_author: Optional[str]) -> str:
    title = (book_title or "").strip()
    author = (book_author or "").strip()
    if author and title:
        return f"— {author}, {title}"
    if title:
        return f"— {title}"
    if author:
        return f"— {author}"
    return ""


def render_quote_png(
    text: str,
    book_title: Optional[str] = None,
    book_author: Optional[str] = None,
) -> bytes:
    """Compose the quote card and return the PNG bytes.

    Designed to be cheap enough to call inline from a request handler:
    a fresh image is allocated on every invocation but stays around
    only for the duration of the response. No global state.
    """
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Left amber bar.
    draw.rectangle(
        (BAR_X, PADDING_Y, BAR_X + BAR_WIDTH, HEIGHT - PADDING_Y),
        fill=BAR_COLOR,
    )

    body_font = _load_font(_BODY_CANDIDATES, size=42)
    meta_font = _load_font(_META_CANDIDATES, size=24)
    watermark_font = _load_font(_META_CANDIDATES, size=18)

    lines = wrap_for_card(text)
    line_height = 58
    text_x = PADDING_X
    text_y = PADDING_Y

    for line in lines:
        draw.text((text_x, text_y), line, fill=TEXT_COLOR, font=body_font)
        text_y += line_height

    # Attribution sits a fixed offset above the bottom edge so the whole
    # card has a consistent footer regardless of how many lines the body
    # consumed. If the body filled the canvas, the attribution still
    # gets its space because MAX_LINES caps the body height.
    attribution = _attribution(book_title, book_author)
    if attribution:
        draw.text(
            (PADDING_X, HEIGHT - PADDING_Y - 60),
            attribution, fill=META_COLOR, font=meta_font,
        )

    # Watermark — subtle bottom-right.
    watermark = "FreeWise"
    bbox = draw.textbbox((0, 0), watermark, font=watermark_font)
    w = bbox[2] - bbox[0]
    draw.text(
        (WIDTH - PADDING_X - w, HEIGHT - PADDING_Y),
        watermark, fill=WATERMARK_COLOR, font=watermark_font,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
