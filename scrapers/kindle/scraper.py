"""Async Playwright scraper for the Kindle "Your Notebook" web app.

Endpoint: ``https://read.amazon.com/kp/notebook``

The page is a single-page React app. The library appears in the left
sidebar; clicking a book swaps the right pane to show that book's
highlights and notes. There is no public API, so we drive a real
Chromium via Playwright with a persisted ``storage_state.json``.

DOM selectors (verified against typical kp/notebook builds in
2024-2026 — Amazon does change these every so often, so we keep them
defensive and easy to swap):

================  ================================================
What              Selector
================  ================================================
Library section   ``#kp-notebook-library``  (sometimes ``#library-section``)
Each library row  ``div.kp-notebook-library-each-book``
Book ASIN         ``data-asin`` attribute on the row above (or
                  ``id`` attribute matching the ASIN)
Book title        ``h2.kp-notebook-searchable``
Book author       ``p.kp-notebook-searchable``
Book cover img    ``img.kp-notebook-cover-image``
Highlight rows    ``div.a-row.a-spacing-base`` inside
                  ``#kp-notebook-annotations`` — each row carries
                  an ``id`` like ``QID:...`` we use as ``highlight.id``
Highlight text    ``span#highlight``
Highlight note    ``span#note``  (sibling row)
Highlight color   ``.kp-notebook-highlight-{yellow|blue|pink|orange}``
                  applied to the highlight wrapper div
Location/page     ``span#kp-annotation-location`` inside the meta
                  row, plus a header label that says either
                  "Page" or "Location"
================  ================================================

If Amazon changes any of these, the per-book scrape catches the error
and continues to the next book — we never let one broken row kill the
whole export.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from logging import Logger
from pathlib import Path
from typing import Any, Sequence

from scrapers.kindle.models import (
    HIGHLIGHT_COLORS,
    SCHEMA_VERSION,
    SOURCE_NAME,
    KindleBook,
    KindleHighlight,
    ScrapeOutput,
)

NOTEBOOK_URL = "https://read.amazon.com/kp/notebook"

# Selector groups — try each in order so we degrade gracefully if Amazon
# tweaks the DOM. We never trust a single selector in production code.
LIBRARY_CONTAINER_SELECTORS: tuple[str, ...] = (
    "#kp-notebook-library",
    "#library-section",
    "div.kp-notebook-library",
)
LIBRARY_ROW_SELECTOR = "div.kp-notebook-library-each-book"
ANNOTATIONS_CONTAINER_SELECTORS: tuple[str, ...] = (
    "#kp-notebook-annotations",
    "#annotations",
    "div.kp-notebook-annotation-list",
)
ANNOTATION_ROW_SELECTOR = "div.a-row.a-spacing-base.a-spacing-top-medium"
HIGHLIGHT_TEXT_SELECTOR = "span#highlight"
NOTE_TEXT_SELECTOR = "span#note"
HIGHLIGHT_COLOR_PREFIX = "kp-notebook-highlight-"
LOCATION_TEXT_SELECTOR = "span#kp-annotation-location"
HEADER_NOTE_LABEL_SELECTOR = "span#annotationNoteHeader"

DEFAULT_LOGIN_TIMEOUT_SECONDS = 300
SCROLL_PAUSE_MS = 500
MAX_LIBRARY_SCROLLS = 200  # ~1000 books worth, more than any realistic library

_log_default = logging.getLogger("scrapers.kindle")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_login(
    *,
    storage_state_path: Path,
    login_timeout_seconds: int = DEFAULT_LOGIN_TIMEOUT_SECONDS,
    log: Logger | None = None,
) -> None:
    """Open a headed Chromium so the user can sign in to Amazon (with 2FA),
    then save the storage state to ``storage_state_path``.

    The browser stays open until the library section is visible (= login
    complete) or ``login_timeout_seconds`` elapses, whichever comes first.
    """

    log = log or _log_default
    storage_state_path = Path(storage_state_path)
    storage_state_path.parent.mkdir(parents=True, exist_ok=True)

    from playwright.async_api import async_playwright

    log.info("Launching headed Chromium for Amazon login")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        try:
            context = await browser.new_context()
            page = await context.new_page()
            log.info("Navigating to %s — please sign in (incl. 2FA)", NOTEBOOK_URL)
            await page.goto(NOTEBOOK_URL, wait_until="domcontentloaded")

            try:
                await _wait_for_library(page, timeout_ms=login_timeout_seconds * 1000)
            except Exception as exc:  # noqa: BLE001 — we want to log every failure
                log.warning(
                    "Library section did not appear within %ss (%s). "
                    "Saving storage state anyway so partial progress is not lost.",
                    login_timeout_seconds,
                    exc,
                )

            await context.storage_state(path=str(storage_state_path))
            log.info("Saved storage state to %s", storage_state_path)
        finally:
            await browser.close()


async def run_scrape(
    *,
    storage_state_path: Path,
    output_path: Path,
    headless: bool = True,
    login_timeout_seconds: int = DEFAULT_LOGIN_TIMEOUT_SECONDS,
    log: Logger | None = None,
) -> ScrapeOutput:
    """Scrape every book and highlight from the user's Kindle library.

    Returns the assembled :class:`ScrapeOutput` and also writes it to
    ``output_path`` as JSON (UTF-8, indented).
    """

    log = log or _log_default
    storage_state_path = Path(storage_state_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not storage_state_path.exists():
        raise FileNotFoundError(
            f"storage_state_path does not exist: {storage_state_path}. "
            f"Run `python -m scrapers.kindle login` first."
        )

    from playwright.async_api import async_playwright

    log.info("Launching %s Chromium with stored Amazon session",
             "headless" if headless else "headed")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        try:
            context = await browser.new_context(storage_state=str(storage_state_path))
            page = await context.new_page()
            await page.goto(NOTEBOOK_URL, wait_until="domcontentloaded")

            await _wait_for_library(page, timeout_ms=login_timeout_seconds * 1000)
            log.info("Library loaded; enumerating books")

            book_rows = await _collect_library_rows(page, log=log)
            log.info("Found %d books in library", len(book_rows))

            books: list[KindleBook] = []
            for index, row_meta in enumerate(book_rows, start=1):
                title = row_meta.get("title") or "(unknown title)"
                log.info("[%d/%d] Scraping %r", index, len(book_rows), title)
                try:
                    book = await _scrape_one_book(page, row_meta, log=log)
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "Failed to scrape book %r (asin=%s): %s — skipping",
                        title,
                        row_meta.get("asin"),
                        exc,
                    )
                    continue
                log.info(
                    "    -> %d highlights for %r",
                    len(book.highlights),
                    book.title,
                )
                books.append(book)
        finally:
            await browser.close()

    scrape = ScrapeOutput(
        schema_version=SCHEMA_VERSION,
        exported_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        source=SOURCE_NAME,
        books=tuple(books),
    )
    output_path.write_text(scrape.to_json(), encoding="utf-8")
    log.info(
        "Wrote %d books / %d total highlights to %s",
        len(scrape.books),
        sum(len(b.highlights) for b in scrape.books),
        output_path,
    )
    return scrape


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------


async def _wait_for_library(page: Any, *, timeout_ms: int) -> None:
    """Wait for any of the known library-container selectors to appear."""

    deadline_ms = timeout_ms
    last_exc: Exception | None = None
    for sel in LIBRARY_CONTAINER_SELECTORS:
        try:
            await page.wait_for_selector(sel, state="visible", timeout=deadline_ms)
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            # Try the next selector with the remaining budget — Playwright's
            # wait_for_selector consumes time even on failure.
            continue
    raise TimeoutError(
        f"None of the library selectors {LIBRARY_CONTAINER_SELECTORS} "
        f"became visible within {timeout_ms}ms"
    ) from last_exc


async def _collect_library_rows(page: Any, *, log: Logger) -> list[dict[str, Any]]:
    """Scroll the library list to the bottom, then gather one metadata dict
    per book. We do this BEFORE clicking any book, so that the row count is
    stable for the rest of the run.
    """

    # Lazy-loaded list: scroll the library container until row count stabilises.
    previous_count = -1
    for _ in range(MAX_LIBRARY_SCROLLS):
        count = await page.locator(LIBRARY_ROW_SELECTOR).count()
        if count == previous_count and count > 0:
            break
        previous_count = count
        await page.mouse.wheel(0, 1500)
        await page.wait_for_timeout(SCROLL_PAUSE_MS)

    rows = page.locator(LIBRARY_ROW_SELECTOR)
    total = await rows.count()
    out: list[dict[str, Any]] = []
    for i in range(total):
        row = rows.nth(i)
        meta = await _read_library_row_meta(row)
        if not meta.get("asin") or not meta.get("title"):
            log.debug("Skipping malformed library row %d: %r", i, meta)
            continue
        out.append(meta)
    return out


async def _read_library_row_meta(row: Any) -> dict[str, Any]:
    """Extract ASIN / title / author / cover_url from a library row."""

    asin = await _first_attr(row, ["data-asin", "id"])
    title = await _first_text(row, ["h2.kp-notebook-searchable", "h2", "div.kp-notebook-searchable"])
    author = await _first_text(
        row,
        ["p.kp-notebook-searchable", "p.a-spacing-none.kp-notebook-searchable", "p"],
    )
    cover_url = await _first_attr(
        row,
        ["src"],
        inside="img.kp-notebook-cover-image",
    )
    if cover_url is None:
        cover_url = await _first_attr(row, ["src"], inside="img")
    return {
        "asin": _clean(asin),
        "title": _clean(title),
        "author": _clean_author(author),
        "cover_url": _clean(cover_url),
    }


async def _scrape_one_book(
    page: Any,
    row_meta: dict[str, Any],
    *,
    log: Logger,
) -> KindleBook:
    """Click a library row and scrape all highlights on the right pane."""

    asin = row_meta["asin"]
    selector = f'{LIBRARY_ROW_SELECTOR}[id="{asin}"], ' \
               f'{LIBRARY_ROW_SELECTOR}[data-asin="{asin}"]'
    target = page.locator(selector).first
    await target.scroll_into_view_if_needed()
    await target.click()

    # The annotations pane re-renders. Wait for either the container or the
    # "no annotations" empty state.
    await _wait_for_annotations_pane(page)

    # If Amazon shows the "You have no notes or highlights" empty state,
    # short-circuit with an empty highlights tuple.
    annotations_root = await _first_visible(page, ANNOTATIONS_CONTAINER_SELECTORS)
    if annotations_root is None:
        return _book_from_meta(row_meta, highlights=())

    # Scroll the annotations pane to load all rows. Highlights are also
    # lazy-loaded on long books.
    await _scroll_to_bottom(page, annotations_root)

    raw = await page.evaluate(_HIGHLIGHTS_DOM_PROBE_JS, annotations_root)
    log.debug("annotations rows: %d", len(raw))
    highlights = _highlights_from_dom_probe(raw)
    return _book_from_meta(row_meta, highlights=highlights)


async def _wait_for_annotations_pane(page: Any) -> None:
    """Wait for any annotation container OR the empty state."""

    selectors = list(ANNOTATIONS_CONTAINER_SELECTORS) + [
        "#kp-notebook-no-annotations",
    ]
    last_exc: Exception | None = None
    for sel in selectors:
        try:
            await page.wait_for_selector(sel, state="attached", timeout=15000)
            return
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            continue
    if last_exc is not None:
        raise last_exc


async def _scroll_to_bottom(page: Any, container_selector: str) -> None:
    """Scroll the given container until its scrollHeight stabilises."""

    js = (
        "(sel) => {"
        " const el = document.querySelector(sel);"
        " if (!el) return null;"
        " el.scrollTop = el.scrollHeight;"
        " return el.scrollHeight;"
        "}"
    )
    last_height = -1
    for _ in range(MAX_LIBRARY_SCROLLS):
        height = await page.evaluate(js, container_selector)
        if height is None:
            return
        if height == last_height:
            return
        last_height = height
        await page.wait_for_timeout(SCROLL_PAUSE_MS)


_HIGHLIGHTS_DOM_PROBE_JS = """
(rootSelector) => {
  const root = document.querySelector(rootSelector) || document;
  const wrappers = root.querySelectorAll('div[id^="highlight-"]');
  const out = [];
  for (const w of wrappers) {
    const id = w.id;
    const baseId = id.replace(/^highlight-/, '');
    const textEl = w.querySelector('span#highlight, [id="highlight"]');
    const text = textEl ? (textEl.textContent || '').trim() : '';
    if (!text) continue;
    const cm = (w.className || '').match(/kp-notebook-highlight-(yellow|blue|pink|orange)/);
    const color = cm ? cm[1] : null;
    let location = null;
    let page_no = null;
    const headerById = root.querySelector(`[id="${CSS.escape(baseId)}"]`);
    if (headerById) {
      const locInput = headerById.querySelector('input#kp-annotation-location');
      if (locInput && locInput.value) {
        const v = parseInt(locInput.value.replace(/,/g, ''), 10);
        if (!isNaN(v)) location = v;
      }
      const headerText =
        headerById.querySelector('#annotationHighlightHeader')?.textContent
        || headerById.querySelector('#annotationNoteHeader')?.textContent
        || '';
      const pm = headerText.match(/Page[:\\s]+([\\d,]+)/);
      if (pm) {
        const v = parseInt(pm[1].replace(/,/g, ''), 10);
        if (!isNaN(v)) page_no = v;
      }
      const lm = headerText.match(/Location[:\\s]+([\\d,]+)/);
      if (location === null && lm) {
        const v = parseInt(lm[1].replace(/,/g, ''), 10);
        if (!isNaN(v)) location = v;
      }
    }
    let note = null;
    let cur = w.nextElementSibling;
    while (cur) {
      if (cur.id && cur.id.startsWith('highlight-')) break;
      if (cur.matches('.kp-notebook-note') || (cur.id || '').startsWith('note')) {
        const ns = cur.querySelector('span#note, [id="note"]');
        const nt = ns ? (ns.textContent || '').trim() : '';
        if (nt) note = nt;
        break;
      }
      cur = cur.nextElementSibling;
    }
    out.push({id, text, note, color, location, page: page_no});
  }
  return out;
}
"""


def _highlights_from_dom_probe(
    raw: Sequence[dict[str, Any]],
) -> tuple[KindleHighlight, ...]:
    """Convert the JS DOM probe result into KindleHighlight tuples."""

    out: list[KindleHighlight] = []
    for r in raw:
        text = r.get("text")
        rid = r.get("id")
        if not text or not rid:
            continue
        color = r.get("color")
        if color not in HIGHLIGHT_COLORS:
            color = None
        out.append(
            KindleHighlight(
                id=str(rid),
                text=str(text),
                note=r.get("note") or None,
                color=color,
                location=_as_int_or_none(r.get("location")),
                page=_as_int_or_none(r.get("page")),
                created_at=None,
            )
        )
    return tuple(out)


def _as_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _parse_annotation_rows(
    rows: Any,
    total_rows: int,
    *,
    log: Logger,
) -> tuple[KindleHighlight, ...]:
    """Legacy locator-based parser. Retained for potential future use; the
    DOM-probe path in _scrape_one_book is the active code path.
    """

    raw: list[dict[str, Any]] = []
    for i in range(total_rows):
        row = rows.nth(i)
        try:
            row_id = await row.get_attribute("id")
            text = await _safe_text(row, HIGHLIGHT_TEXT_SELECTOR)
            note = await _safe_text(row, NOTE_TEXT_SELECTOR)
            location, page_no = await _parse_location_and_page(row)
            color = await _parse_color(row)
            raw.append(
                {
                    "id": row_id,
                    "text": text,
                    "note": note,
                    "color": color,
                    "location": location,
                    "page": page_no,
                }
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Skipping malformed annotation row %d: %s", i, exc)
            continue

    return _merge_rows_into_highlights(raw)


def _merge_rows_into_highlights(
    raw_rows: Sequence[dict[str, Any]],
) -> tuple[KindleHighlight, ...]:
    """Combine highlight + note rows that share the same DOM id."""

    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for r in raw_rows:
        rid = r.get("id")
        if not rid:
            continue
        if rid not in by_id:
            by_id[rid] = {"id": rid, "text": None, "note": None,
                          "color": None, "location": None, "page": None}
            order.append(rid)
        slot = by_id[rid]
        if r.get("text") and not slot["text"]:
            slot["text"] = r["text"]
        if r.get("note") and not slot["note"]:
            slot["note"] = r["note"]
        if r.get("color") and not slot["color"]:
            slot["color"] = r["color"]
        if r.get("location") is not None and slot["location"] is None:
            slot["location"] = r["location"]
        if r.get("page") is not None and slot["page"] is None:
            slot["page"] = r["page"]

    out: list[KindleHighlight] = []
    for rid in order:
        s = by_id[rid]
        if not s["text"]:
            # An orphan note row without a highlight is unusable; skip it.
            continue
        out.append(
            KindleHighlight(
                id=str(rid),
                text=str(s["text"]),
                note=s["note"],
                color=s["color"] if s["color"] in HIGHLIGHT_COLORS else None,
                location=s["location"],
                page=s["page"],
                created_at=None,
            )
        )
    return tuple(out)


async def _parse_color(row: Any) -> str | None:
    """Pull the highlight color out of the row's class list."""

    cls = await row.get_attribute("class") or ""
    for color in HIGHLIGHT_COLORS:
        if f"{HIGHLIGHT_COLOR_PREFIX}{color}" in cls:
            return color
    # Fallback: check inner descendants — sometimes the class is on a child.
    handle = await row.element_handle()
    if handle is None:
        return None
    inner_class = await handle.evaluate(
        "(el) => Array.from(el.querySelectorAll('[class]'))"
        ".map(n => n.className)"
        ".filter(c => typeof c === 'string' && c.includes('kp-notebook-highlight-'))"
        ".join(' ')"
    )
    for color in HIGHLIGHT_COLORS:
        if f"{HIGHLIGHT_COLOR_PREFIX}{color}" in (inner_class or ""):
            return color
    return None


async def _parse_location_and_page(row: Any) -> tuple[int | None, int | None]:
    """Parse the metadata header that precedes each highlight.

    Examples seen in the wild:
      - "Yellow highlight | Page: 45 · Location 1234"
      - "Blue highlight | Location 4821"
      - "Pink highlight | Page: 87"
    """

    text = await _safe_text(row, "#annotationHighlightHeader")
    if not text:
        text = await _safe_text(row, ".kp-notebook-metadata")
    if not text:
        text = await _safe_text(row, LOCATION_TEXT_SELECTOR)
    if not text:
        return None, None

    # Allow thousand separators (commas) — Amazon localises some metadata.
    location = _extract_int(text, r"Location[:\s]+([\d,]+)")
    page_no = _extract_int(text, r"Page[:\s]+([\d,]+)")
    return location, page_no


# ---------------------------------------------------------------------------
# Tiny utilities — kept here so the scraper is one self-contained module.
# ---------------------------------------------------------------------------


def _book_from_meta(
    row_meta: dict[str, Any],
    *,
    highlights: tuple[KindleHighlight, ...],
) -> KindleBook:
    return KindleBook(
        asin=str(row_meta["asin"]),
        title=str(row_meta["title"]),
        author=row_meta.get("author"),
        cover_url=row_meta.get("cover_url"),
        highlights=highlights,
    )


async def _first_text(row: Any, selectors: Sequence[str]) -> str | None:
    for sel in selectors:
        text = await _safe_text(row, sel)
        if text:
            return text
    return None


async def _first_attr(
    row: Any,
    attrs: Sequence[str],
    *,
    inside: str | None = None,
) -> str | None:
    target = row.locator(inside).first if inside else row
    for attr in attrs:
        try:
            value = await target.get_attribute(attr)
        except Exception:  # noqa: BLE001
            value = None
        if value:
            return value
    return None


async def _safe_text(row: Any, selector: str) -> str | None:
    try:
        loc = row.locator(selector).first
        if await loc.count() == 0:
            return None
        return (await loc.inner_text()).strip() or None
    except Exception:  # noqa: BLE001
        return None


async def _first_visible(page: Any, selectors: Sequence[str]) -> str | None:
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                return sel
        except Exception:  # noqa: BLE001
            continue
    return None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _clean_author(value: str | None) -> str | None:
    """Authors are often rendered as 'By: Author Name' on Kindle."""

    cleaned = _clean(value)
    if cleaned is None:
        return None
    return re.sub(r"^[Bb]y[:\s]+", "", cleaned).strip() or None


def _extract_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except (ValueError, IndexError):
        return None


