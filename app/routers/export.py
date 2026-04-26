import csv
import io
import re
import zipfile
from collections import defaultdict
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.db import get_session
from app.models import Highlight, Book, Tag, HighlightTag


router = APIRouter(prefix="/export", tags=["export"])


@router.get("/csv")
async def export_highlights_csv(
    session: Session = Depends(get_session)
):
    """
    Export all highlights to CSV with Readwise-compatible schema.

    The export follows the official Readwise CSV format for the first 11 columns,
    allowing direct re-import into Readwise or FreeWise. Additional FreeWise-specific
    metadata columns are appended after the Readwise-compatible block.

    Readwise columns (1-11):
    - Highlight, Book Title, Book Author, Amazon Book ID, Note, Color,
      Tags, Location Type, Location, Highlighted at, Document tags

    Extended columns (12-13):
    - is_favorited, is_discarded
    """
    # Pull all highlights + book in one join.
    statement = (
        select(Highlight, Book)
        .outerjoin(Book, Highlight.book_id == Book.id)
        .order_by(Highlight.created_at.desc())
    )
    results = session.exec(statement).all()

    if not results:
        raise HTTPException(status_code=400, detail="No highlights available to export.")

    # Pre-load every (highlight_id, tag_name) pair in ONE query, replacing
    # the previous N+1 (one query per highlight). For 25k highlights with
    # tags that's a 25,000× round-trip reduction.
    tag_pairs = session.exec(
        select(HighlightTag.highlight_id, Tag.name)
        .join(Tag, HighlightTag.tag_id == Tag.id)
    ).all()
    tags_by_highlight: dict[int, list[str]] = defaultdict(list)
    for hl_id, tag_name in tag_pairs:
        # Filter system tags here so the per-row loop stays cheap.
        if tag_name and tag_name.lower() not in ("favorite", "discard"):
            tags_by_highlight[hl_id].append(tag_name)

    headers = [
        # Readwise-compatible columns (exact naming and order)
        'Highlight',
        'Book Title',
        'Book Author',
        'Amazon Book ID',
        'Note',
        'Color',
        'Tags',
        'Location Type',
        'Location',
        'Highlighted at',
        'Document tags',
        # Extended FreeWise columns
        'is_favorited',
        'is_discarded',
    ]

    def _gen():
        # Stream the CSV instead of buffering the whole library in memory —
        # at 25k+ highlights the previous Response(content=...) approach
        # held the entire file in RAM and delayed TTFB until generation
        # finished.
        buf = io.StringIO()
        writer = csv.writer(buf, quoting=csv.QUOTE_ALL)
        writer.writerow(headers)
        yield buf.getvalue()
        buf.seek(0); buf.truncate(0)

        for highlight, book in results:
            tags_str = ', '.join(tags_by_highlight.get(highlight.id, []))
            highlighted_at = highlight.created_at.isoformat() if highlight.created_at else ''
            writer.writerow([
                highlight.text or '',                                           # Highlight
                book.title if book else '',                                     # Book Title
                book.author if book else '',                                    # Book Author
                '',                                                             # Amazon Book ID (not used)
                highlight.note or '',                                           # Note
                '',                                                             # Color (not used)
                tags_str,                                                       # Tags (highlight-level)
                highlight.location_type or '',                                  # Location Type (page or order)
                str(highlight.location) if highlight.location else '',          # Location (page number or order)
                highlighted_at,                                                 # Highlighted at (ISO format)
                book.document_tags if book and book.document_tags else '',      # Document tags (book-level)
                'true' if highlight.is_favorited else 'false',                  # is_favorited
                'true' if highlight.is_discarded else 'false',                  # is_discarded
            ])
            yield buf.getvalue()
            buf.seek(0); buf.truncate(0)

    filename = f"freewise_export_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        _gen(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Markdown export (Obsidian / Logseq compatible) ──────────────────────────


# Filesystem-safe filename: strip characters that break on FAT/NTFS/HFS, keep
# unicode letters intact so Japanese/Chinese book titles round-trip cleanly.
_FILENAME_BAD = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _safe_filename(s: str, fallback: str = "untitled") -> str:
    cleaned = _FILENAME_BAD.sub("_", s).strip().strip(".")
    cleaned = cleaned[:120]  # keep well under FAT32 255-byte limit incl. unicode
    return cleaned or fallback


def _yaml_escape(s: str | None) -> str:
    """Quote a YAML scalar value safely. We use double-quoted form throughout."""
    if s is None:
        return '""'
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render_book_markdown(book: Book, highlights: list[Highlight]) -> str:
    """Render a single .md file: YAML frontmatter + blockquoted highlights.

    Compatible with Obsidian and Logseq vaults (both parse YAML frontmatter
    and standard Markdown blockquotes). Tags from ``Book.document_tags`` are
    surfaced as YAML frontmatter ``tags:`` so vault search picks them up.
    """
    tags: list[str] = []
    if book.document_tags:
        for raw in book.document_tags.split(","):
            t = raw.strip()
            if t:
                tags.append(t)

    lines: list[str] = ["---"]
    lines.append(f"title: {_yaml_escape(book.title)}")
    if book.author:
        lines.append(f"author: {_yaml_escape(book.author)}")
    lines.append(f"highlight_count: {len(highlights)}")
    lines.append(f"exported_at: {_yaml_escape(datetime.now().isoformat(timespec='seconds'))}")
    lines.append("source: freewise")
    if tags:
        lines.append("tags:")
        for t in tags:
            lines.append(f"  - {_yaml_escape(t)}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {book.title}")
    if book.author:
        lines.append(f"*{book.author}*")
    lines.append("")

    if not highlights:
        lines.append("_No highlights yet._")
    else:
        for h in highlights:
            # Blockquote the highlight text — every line of the quote needs a
            # leading "> " or Obsidian/Logseq breaks the block.
            for ln in (h.text or "").splitlines() or [""]:
                lines.append(f"> {ln}")
            # Metadata footer: location + flags.
            meta_bits: list[str] = []
            if h.location is not None:
                meta_bits.append(
                    f"location {h.location}" + (f" ({h.location_type})" if h.location_type else "")
                )
            if h.is_favorited:
                meta_bits.append("★ favorited")
            if meta_bits:
                lines.append(">")
                lines.append(f"> *{' · '.join(meta_bits)}*")
            # Note as a regular paragraph beneath the quote.
            if h.note:
                lines.append("")
                lines.append(h.note)
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


@router.get("/markdown.zip")
async def export_markdown_zip(session: Session = Depends(get_session)):
    """Stream a ZIP of one Markdown file per book (Obsidian/Logseq friendly).

    Excludes discarded highlights — the Markdown export is meant to populate
    a knowledge vault, not preserve trash. Re-running the export overwrites
    files in the destination vault.
    """
    # Fetch all books that have at least one non-discarded highlight, then
    # group highlights per book. One pass each — no N+1.
    rows = session.exec(
        select(Highlight, Book)
        .outerjoin(Book, Highlight.book_id == Book.id)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .order_by(
            Highlight.book_id.asc().nullslast(),
            Highlight.location.asc().nullslast(),
            Highlight.created_at.asc().nullslast(),
            Highlight.id.asc(),
        )
    ).all()

    if not rows:
        raise HTTPException(status_code=400, detail="No active highlights to export.")

    by_book: dict[int | None, list[Highlight]] = defaultdict(list)
    book_lookup: dict[int | None, Book | None] = {}
    for h, b in rows:
        by_book[h.book_id].append(h)
        book_lookup[h.book_id] = b

    # Disambiguate filename collisions when two books have the same title.
    seen: dict[str, int] = {}

    def _gen():
        # Build the ZIP in memory and yield it. SQLite databases at this
        # app's expected scale (low-tens of MB) fit comfortably; if a future
        # user has 500MB of highlights we can switch to chunked zipfile
        # writing. For now this stays simple.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for book_id, hl_list in by_book.items():
                book = book_lookup.get(book_id)
                if book is None:
                    book = Book(title="Unbound highlights", author=None)
                # Guard against a Book row with NULL title — _safe_filename
                # calls re.sub which would TypeError on None and crash the
                # generator mid-stream (silent truncation to client).
                title_safe = _safe_filename(book.title or "")
                key = title_safe.lower()
                if key in seen:
                    seen[key] += 1
                    fname = f"{title_safe} ({seen[key]}).md"
                else:
                    seen[key] = 0
                    fname = f"{title_safe}.md"
                zf.writestr(fname, _render_book_markdown(book, hl_list))
        buf.seek(0)
        # Single-shot yield — keeps the in-memory ZIP intact.
        yield buf.getvalue()

    fname = f"freewise-vault-{datetime.now().strftime('%Y%m%d')}.zip"
    return StreamingResponse(
        _gen(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
