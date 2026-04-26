import csv
import io
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
