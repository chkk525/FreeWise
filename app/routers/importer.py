import csv
import io
import base64
from datetime import datetime
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.db import get_session, get_settings
from app.models import Highlight, Tag, HighlightTag, Settings, Book
from app.template_filters import make_templates
from app.utils.tags import parse_tags


router = APIRouter(prefix="/import", tags=["import"])
templates = make_templates()


def parse_readwise_datetime(dt_str: str) -> Optional[datetime]:
    """Parse various datetime formats from Readwise CSV.
    
    Returns None if the date string is empty or cannot be parsed.
    """
    if not dt_str or dt_str.strip() == "":
        return None
    
    formats = [
        "%B %d, %Y %I:%M:%S %p",      # January 15, 2024 10:30:00 AM
        "%Y-%m-%d %H:%M:%S",           # 2024-01-15 10:30:00
        "%Y-%m-%dT%H:%M:%S",           # 2024-01-15T10:30:00
        "%Y-%m-%d %H:%M:%S%z",         # 2025-12-10 14:18:00+00:00
        "%Y-%m-%dT%H:%M:%S%z",         # 2025-12-10T14:18:00+00:00
        "%Y-%m-%d %H:%M:%S.%f",        # 2024-01-15 10:30:00.000000
        "%Y-%m-%d %H:%M:%S.%f%z",      # 2024-01-15 10:30:00.000000+00:00
    ]
    
    for fmt in formats:
        try:
            parsed = datetime.strptime(dt_str.strip(), fmt)
            # If the source had a timezone, convert to UTC FIRST and then
            # strip tzinfo so the stored value matches the rest of the
            # codebase's naive-UTC convention. The previous version stripped
            # tzinfo without converting, so a "14:18+09:00" string was
            # silently stored as if it were 14:18 UTC — a 9-hour error.
            if parsed.tzinfo is not None:
                from datetime import timezone as _tz
                parsed = parsed.astimezone(_tz.utc).replace(tzinfo=None)
            return parsed
        except ValueError:
            continue

    # If all formats fail, return None
    return None


def get_or_create_tag(session: Session, tag_name: str) -> Optional[Tag]:
    """Get existing tag or create new one. Returns ``None`` for empty input."""
    tag_name = tag_name.strip()
    if not tag_name:
        return None

    # Check if tag exists
    statement = select(Tag).where(Tag.name == tag_name)
    tag = session.exec(statement).first()

    if not tag:
        tag = Tag(name=tag_name)
        session.add(tag)
        session.commit()
        session.refresh(tag)

    return tag


def batch_get_or_create_tags(
    session: Session, tag_names: list[str]
) -> dict[str, Tag]:
    """Resolve multiple tag names in two SQL round-trips total.

    Used by the Readwise / Meebook CSV importers, each of which previously
    issued one SELECT + (worst-case) one INSERT per tag per row. For a
    10k-row CSV with 5 tags per row that was 50k+ extra round-trips on the
    SQLite single-writer. This batches:

      1. SELECT WHERE name IN (...) → existing tags
      2. INSERT new ones in a single transaction

    Returns a dict keyed by stripped tag name. Empty / blank inputs are
    silently dropped.
    """
    cleaned = [n.strip() for n in tag_names if n and n.strip()]
    deduped = list(dict.fromkeys(cleaned))  # preserve order, drop dupes
    if not deduped:
        return {}
    existing = list(
        session.exec(select(Tag).where(Tag.name.in_(deduped))).all()
    )
    by_name = {t.name: t for t in existing}
    missing = [n for n in deduped if n not in by_name]
    if missing:
        new_rows = [Tag(name=n) for n in missing]
        for t in new_rows:
            session.add(t)
        session.commit()
        for t in new_rows:
            session.refresh(t)
            by_name[t.name] = t
    return by_name


def get_or_create_book(session: Session, title: str, author: Optional[str] = None, document_tags: Optional[str] = None) -> Optional[Book]:
    """Get existing book or create new one based on title and author."""
    if not title or not title.strip():
        return None
    
    title = title.strip()
    author = author.strip() if author else None
    
    # Check if book exists (match on title and author)
    statement = select(Book).where(Book.title == title)
    if author:
        statement = statement.where(Book.author == author)
    else:
        statement = statement.where(Book.author == None)
    
    book = session.exec(statement).first()
    
    if not book:
        book = Book(
            title=title,
            author=author,
            document_tags=document_tags
        )
        session.add(book)
        session.commit()
        session.refresh(book)
    elif document_tags and not book.document_tags:
        # Update document tags if they weren't set before
        book.document_tags = document_tags
        session.add(book)
        session.commit()
        session.refresh(book)
    
    return book


@router.get("/ui", response_class=HTMLResponse)
async def ui_import(
    request: Request,
    session: Session = Depends(get_session)
):
    """Render main import page with source selection."""
    # Get settings for theme
    settings = get_settings(session)

    return templates.TemplateResponse(request, "import_main.html", {"settings": settings})


@router.get("/ui/readwise", response_class=HTMLResponse)
async def ui_import_readwise(
    request: Request,
    session: Session = Depends(get_session)
):
    """Render Readwise import page."""
    # Get settings for theme
    settings = get_settings(session)

    return templates.TemplateResponse(request, "import_readwise.html", {"settings": settings})


@router.get("/ui/custom", response_class=HTMLResponse)
async def ui_import_custom(
    request: Request,
    session: Session = Depends(get_session)
):
    """Render custom CSV import page."""
    # Get settings for theme
    settings = get_settings(session)

    return templates.TemplateResponse(request, "import_custom.html", {"settings": settings})


# ── Kindle notebook JSON import ──────────────────────────────────────────────


@router.get("/ui/kindle", response_class=HTMLResponse)
async def ui_import_kindle(
    request: Request,
    session: Session = Depends(get_session),
):
    """Render Kindle notebook JSON import page."""
    settings = get_settings(session)
    # Use the new starlette 1.0 positional signature so this route works
    # regardless of the legacy-style failures elsewhere in the codebase.
    return templates.TemplateResponse(
        request,
        "import_kindle.html",
        {"settings": settings},
    )


@router.post("/ui/kindle", response_class=HTMLResponse)
async def process_kindle_import(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """Process an uploaded Kindle notebook JSON file via the kindle_notebook importer."""
    from app.importers.kindle_notebook import import_kindle_notebook_json

    filename = file.filename or ""
    if not filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="File must be a JSON file (.json)")

    contents = await file.read()
    file_obj = io.BytesIO(contents)

    settings = get_settings(session)

    try:
        result = import_kindle_notebook_json(file_obj, session, user_id=1)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "import_kindle.html",
            {
                "settings": settings,
                "error_message": str(exc),
            },
            status_code=400,
        )
    except Exception as exc:  # pragma: no cover — defensive
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")

    success_message = (
        f"Imported {result.highlights_created} highlights "
        f"({result.books_created} new books, {result.books_matched} matched). "
        f"Skipped {result.highlights_skipped_duplicates} duplicates."
    )
    return templates.TemplateResponse(
        request,
        "import_kindle.html",
        {
            "settings": settings,
            "success_message": success_message,
            "imported_count": result.highlights_created,
            "duplicate_count": result.highlights_skipped_duplicates,
            "books_created": result.books_created,
            "books_matched": result.books_matched,
            "errors": result.errors,
        },
    )


@router.post("/kindle/scan-now")
async def kindle_scan_now(
    session: Session = Depends(get_session),
):
    """Manually trigger one Kindle imports-dir scan (no waiting for the scheduler).

    Returns a JSON summary. Useful right after a fresh ``kindle_dl.sh`` run, or
    in tests. Does nothing if KINDLE_IMPORTS_DIR is unset.
    """
    from app.services.kindle_import_watcher import (
        imports_dir_from_env,
        scan_and_import,
        user_id_from_env,
    )

    imports_dir = imports_dir_from_env()
    if imports_dir is None:
        raise HTTPException(
            status_code=400,
            detail="KINDLE_IMPORTS_DIR not configured on this server.",
        )

    result = scan_and_import(
        imports_dir=imports_dir,
        session=session,
        user_id=user_id_from_env(),
    )
    return {
        "files_scanned": result.files_scanned,
        "files_imported": result.files_imported,
        "files_failed": result.files_failed,
        "books_created": result.books_created,
        "books_matched": result.books_matched,
        "highlights_created": result.highlights_created,
        "highlights_skipped_duplicates": result.highlights_skipped_duplicates,
        "errors": list(result.errors),
    }


# ── Meebook / Haoqing HTML import ────────────────────────────────────────────

@router.get("/ui/meebook", response_class=HTMLResponse)
async def ui_import_meebook(
    request: Request,
    session: Session = Depends(get_session)
):
    """Render Meebook HTML import page."""
    settings = get_settings(session)
    return templates.TemplateResponse(request, "import_meebook.html", {"settings": settings})


@router.post("/ui/meebook", response_class=HTMLResponse)
async def process_meebook_import(
    request: Request,
    file: UploadFile = File(...),
    diagnostic: str = Form("true"),
    session: Session = Depends(get_session),
):
    """Process an uploaded Haoqing HTML file and import highlights directly."""
    from app.utils.meebook import extract_highlights

    # Validate file type
    if not file.filename.endswith(".html") and not file.filename.endswith(".htm"):
        raise HTTPException(status_code=400, detail="File must be an HTML file (.html or .htm)")

    try:
        contents = await file.read()
        html_text = contents.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File encoding error. Please ensure the file is UTF-8 encoded.")

    try:
        highlights = extract_highlights(html_text)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse HTML: {e}")

    if not highlights:
        settings = get_settings(session)
        return templates.TemplateResponse(request, "import_meebook.html", {"settings": settings,
            "success_message": "No highlights found in the uploaded file.",
            "imported_count": 0,
            "skipped_count": 0,
            "duplicate_count": 0,
            "skipped_rows": []})

    imported_count = 0
    duplicate_count = 0
    skipped_rows = []
    is_diagnostic = (diagnostic == "true")

    for idx, h in enumerate(highlights, start=1):
        # Get or create book
        book = get_or_create_book(
            session=session,
            title=h["title"],
            author=h["author"],
        )

        # Deduplicate
        existing_stmt = select(Highlight).where(
            Highlight.text == h["text"],
            Highlight.note == h["note"],
            Highlight.book_id == (book.id if book else None),
        )
        if session.exec(existing_stmt).first():
            duplicate_count += 1
            if is_diagnostic:
                skipped_rows.append({
                    "row": idx,
                    "reason": "Duplicate highlight",
                    "highlight": h["text"][:120],
                    "note": (h["note"] or "")[:80],
                    "book_title": h["title"],
                })
            continue

        highlight = Highlight(
            text=h["text"],
            book_id=book.id if book else None,
            note=h["note"],
            created_at=h["created_at"],
            location=h["location"],
            location_type=h["location_type"],
            user_id=1,
        )
        session.add(highlight)
        if is_diagnostic:
            session.commit()
            session.refresh(highlight)
        else:
            session.flush()

        imported_count += 1

    if not is_diagnostic:
        session.commit()

    settings = get_settings(session)
    return templates.TemplateResponse(request, "import_meebook.html", {"settings": settings,
        "success_message": f"Successfully imported {imported_count} highlights. Deduplicated {duplicate_count} duplicates.",
        "imported_count": imported_count,
        "skipped_count": 0,
        "duplicate_count": duplicate_count,
        "skipped_rows": skipped_rows})


@router.post("/ui/custom/preview", response_class=HTMLResponse)
async def ui_import_custom_preview(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session)
):
    """Preview CSV and show column mapping interface."""
    # Validate file type
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")
    
    try:
        # Read file content
        contents = await file.read()
        csv_text = contents.decode('utf-8')
        csv_file = io.StringIO(csv_text)
        
        # Parse CSV
        reader = csv.DictReader(csv_file)
        
        # Get column names
        csv_columns = reader.fieldnames
        if not csv_columns:
            raise HTTPException(status_code=400, detail="CSV file has no columns")
        
        # Get first 3 rows for preview
        preview_data = []
        for i, row in enumerate(reader):
            if i >= 3:
                break
            preview_data.append(row)
        
        # Encode CSV data for passing to next step
        csv_data_b64 = base64.b64encode(csv_text.encode('utf-8')).decode('utf-8')
        
        # Get settings for theme
        settings = get_settings(session)

        return templates.TemplateResponse(request, "import_custom.html", {"settings": settings,
            "preview_data": preview_data,
            "csv_columns": csv_columns,
            "csv_data_b64": csv_data_b64})
    
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File encoding error. Please ensure the file is UTF-8 encoded.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Preview failed: {str(e)}")


@router.post("/ui/custom/process", response_class=HTMLResponse)
async def process_custom_import(
    request: Request,
    csv_data: str = Form(...),
    highlight: str = Form(...),
    book_title: str = Form(...),
    book_author: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    document_tags: Optional[str] = Form(None),
    highlighted_at: Optional[str] = Form(None),
    location: Optional[str] = Form(None),
    location_type: Optional[str] = Form(None),
    diagnostic: str = Form("true"),
    session: Session = Depends(get_session)
):
    """Process custom CSV with user-defined column mapping."""
    try:
        # Decode CSV data
        csv_text = base64.b64decode(csv_data).decode('utf-8')
        csv_file = io.StringIO(csv_text)
        
        # Parse CSV
        reader = csv.DictReader(csv_file)
        
        # Build column mapping
        # Validate location_type — only accept the two known values
        valid_location_type = location_type if location_type in ('page', 'order') else None

        column_mapping = {
            'highlight': highlight,
            'book_title': book_title if book_title else None,
            'book_author': book_author if book_author else None,
            'note': note if note else None,
            'tags': tags if tags else None,
            'document_tags': document_tags if document_tags else None,
            'highlighted_at': highlighted_at if highlighted_at else None,
            'location': location if location else None
        }
        
        imported_count = 0
        skipped_count = 0
        duplicate_count = 0
        skipped_rows = []
        is_diagnostic = (diagnostic == "true")

        for idx, row in enumerate(reader, start=1):
            # Map columns
            highlight_text = row.get(column_mapping['highlight'], '').strip() if column_mapping['highlight'] else ''
            
            # Skip empty rows
            if not highlight_text:
                skipped_count += 1
                if is_diagnostic:
                    skipped_rows.append({
                        "row": idx,
                        "reason": "Empty highlight",
                        "highlight": highlight_text,
                        "note": "",
                        "book_title": ""
                    })
                continue
            
            # Extract mapped data
            book_title_val = row.get(column_mapping['book_title'], '').strip() if column_mapping['book_title'] else ''
            book_author_val = row.get(column_mapping['book_author'], '').strip() if column_mapping['book_author'] else ''
            note_val = row.get(column_mapping['note'], '').strip() if column_mapping['note'] else ''

            # Require book title
            if not book_title_val:
                skipped_count += 1
                if is_diagnostic:
                    skipped_rows.append({
                        "row": idx,
                        "reason": "Missing book title",
                        "highlight": highlight_text,
                        "note": note_val,
                        "book_title": book_title_val
                    })
                continue
            
            # Skip header marker notes
            if note_val.lower() in {'.h1', '.h2', '.h3', '.h4', '.h5', '.h6'}:
                skipped_count += 1
                if is_diagnostic:
                    skipped_rows.append({
                        "row": idx,
                        "reason": "Header marker note (.h1-.h6)",
                        "highlight": highlight_text,
                        "note": note_val,
                        "book_title": book_title_val
                    })
                continue
            
            tags_val = row.get(column_mapping['tags'], '').strip() if column_mapping['tags'] else ''
            document_tags_val = row.get(column_mapping['document_tags'], '').strip() if column_mapping['document_tags'] else ''
            highlighted_at_val = row.get(column_mapping['highlighted_at'], '').strip() if column_mapping['highlighted_at'] else ''
            location_val = row.get(column_mapping['location'], '').strip() if column_mapping['location'] else ''
            
            # Parse datetime
            created_at = parse_readwise_datetime(highlighted_at_val) if highlighted_at_val else None
            
            # Get or create book
            book = get_or_create_book(
                session=session,
                title=book_title_val,
                author=book_author_val if book_author_val else None,
                document_tags=document_tags_val if document_tags_val else None
            )
            
            # Parse tags
            is_favorited = False
            is_discarded = False
            regular_tags = []
            
            if tags_val:
                tag_names = parse_tags(tags_val)
                for tag_name in tag_names:
                    tag_lower = tag_name.lower()
                    if tag_lower == "favorite":
                        is_favorited = True
                    elif tag_lower == "discard":
                        is_discarded = True
                    else:
                        regular_tags.append(tag_name)
            
            # Deduplicate
            existing_stmt = select(Highlight).where(
                Highlight.text == highlight_text,
                Highlight.note == (note_val if note_val else None),
                Highlight.book_id == (book.id if book else None)
            )
            existing_highlight = session.exec(existing_stmt).first()
            if existing_highlight:
                duplicate_count += 1
                if is_diagnostic:
                    skipped_rows.append({
                        "row": idx,
                        "reason": "Duplicate highlight",
                        "highlight": highlight_text,
                        "note": note_val,
                        "book_title": book_title_val
                    })
                continue
            
            # Parse location
            location_int = None
            if location_val:
                try:
                    location_int = int(location_val)
                except (ValueError, TypeError):
                    location_int = None
            
            # Create highlight
            highlight = Highlight(
                text=highlight_text,
                book_id=book.id if book else None,
                note=note_val if note_val else None,
                created_at=created_at,
                location=location_int,
                location_type=valid_location_type if location_int is not None else None,
                user_id=1,
                is_favorited=is_favorited,
                is_discarded=is_discarded,
            )

            session.add(highlight)
            if is_diagnostic:
                session.commit()
                session.refresh(highlight)
            else:
                session.flush()

            # Process tags
            for tag_name in regular_tags:
                tag = get_or_create_tag(session, tag_name)
                if tag:
                    highlight_tag = HighlightTag(
                        highlight_id=highlight.id,
                        tag_id=tag.id
                    )
                    session.add(highlight_tag)
            
            if regular_tags and is_diagnostic:
                session.commit()
            
            imported_count += 1
        
        if not is_diagnostic:
            session.commit()

        # Get settings for theme
        settings = get_settings(session)

        # Return success page on custom import page
        return templates.TemplateResponse(request, "import_custom.html", {"settings": settings,
            "success_message": f"Successfully imported {imported_count} highlights. Skipped {skipped_count} rows. Deduplicated {duplicate_count} duplicates.",
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "duplicate_count": duplicate_count,
            "skipped_rows": skipped_rows})
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


@router.post("/ui/readwise", response_class=HTMLResponse)
async def process_readwise_import(
    request: Request,
    file: UploadFile = File(...),
    diagnostic: str = Form("true"),
    session: Session = Depends(get_session)
):
    """
    Process uploaded Readwise CSV file and import highlights.
    
    Accepts both:
    1. Standard Readwise CSV exports with columns:
       Highlight, Book Title, Book Author, Amazon Book ID, Note, Color, Tags,
       Location Type, Location, Highlighted at, Document tags
    
    2. Extended FreeWise CSV exports with additional columns:
       is_favorited, is_discarded
    
    The importer is backwards-compatible and will use extended metadata if present,
    or fall back to defaults if columns are missing.
    """
    # Validate file type
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")
    
    try:
        # Read file content
        contents = await file.read()
        csv_text = contents.decode('utf-8')
        csv_file = io.StringIO(csv_text)
        
        # Parse CSV
        reader = csv.DictReader(csv_file)
        
        # Validate required columns (must have at least Highlight column)
        required_columns = ['Highlight']
        if not all(col in reader.fieldnames for col in required_columns):
            raise HTTPException(
                status_code=400, 
                detail=f"CSV must contain at least 'Highlight' column. Found: {reader.fieldnames}"
            )
        
        imported_count = 0
        skipped_count = 0
        duplicate_count = 0
        skipped_rows = []
        is_diagnostic = (diagnostic == "true")

        for idx, row in enumerate(reader, start=1):
            # Skip empty rows
            if not row.get('Highlight', '').strip():
                skipped_count += 1
                if is_diagnostic:
                    skipped_rows.append({
                        "row": idx,
                        "reason": "Empty highlight",
                        "highlight": row.get('Highlight', '').strip(),
                        "note": row.get('Note', '').strip(),
                        "book_title": row.get('Book Title', '').strip()
                    })
                continue
            
            # Extract data from CSV - support both Readwise and extended format
            highlight_text = row.get('Highlight', '').strip()
            book_title = row.get('Book Title', '').strip()
            book_author = row.get('Book Author', '').strip()
            note = row.get('Note', '').strip()
            if note.lower() in {'.h1', '.h2', '.h3', '.h4', '.h5', '.h6'}:
                skipped_count += 1
                if is_diagnostic:
                    skipped_rows.append({
                        "row": idx,
                        "reason": "Header marker note (.h1-.h6)",
                        "highlight": highlight_text,
                        "note": note,
                        "book_title": book_title
                    })
                continue
            tags_str = row.get('Tags', '').strip()
            document_tags_str = row.get('Document tags', '').strip()
            highlighted_at_str = row.get('Highlighted at', '').strip()
            location_type_str = row.get('Location Type', '').strip()
            location_str = row.get('Location', '').strip()
            
            # Extended columns (optional - only in FreeWise exports)
            is_favorited_str = row.get('is_favorited', '').strip().lower()
            is_discarded_str = row.get('is_discarded', '').strip().lower()
            
            # Parse datetime
            datetime_str = highlighted_at_str
            created_at = parse_readwise_datetime(datetime_str)
            # If no date is provided, created_at remains None (don't use today's date as fallback)
            
            # Get or create book
            book = None
            if book_title:
                book = get_or_create_book(
                    session=session,
                    title=book_title,
                    author=book_author if book_author else None,
                    document_tags=document_tags_str if document_tags_str else None
                )
            
            # Parse tags and check for special tags (favorite, discard)
            # Extended format: use explicit is_favorited/is_discarded columns if present
            # Standard format: parse from tags
            is_favorited = False
            is_discarded = False
            regular_tags = []
            
            # Check extended columns first (takes precedence)
            if is_favorited_str in ['true', '1', 'yes']:
                is_favorited = True
            if is_discarded_str in ['true', '1', 'yes']:
                is_discarded = True
            
            # Parse tags string for both tag creation and legacy favorite/discard detection
            if tags_str:
                tag_names = parse_tags(tags_str)
                for tag_name in tag_names:
                    tag_lower = tag_name.lower()
                    # Only use tag-based favorite/discard if extended columns not present
                    if tag_lower == "favorite" and not is_favorited_str:
                        is_favorited = True
                    elif tag_lower == "discard" and not is_discarded_str:
                        is_discarded = True
                    else:
                        regular_tags.append(tag_name)
            
            # Deduplicate: skip if an identical highlight (same text and note) already exists for this book
            existing_stmt = select(Highlight).where(
                Highlight.text == highlight_text,
                Highlight.note == (note if note else None),
                Highlight.book_id == (book.id if book else None)
            )
            existing_highlight = session.exec(existing_stmt).first()
            if existing_highlight:
                duplicate_count += 1
                if is_diagnostic:
                    skipped_rows.append({
                        "row": idx,
                        "reason": "Duplicate highlight",
                        "highlight": highlight_text,
                        "note": note,
                        "book_title": book_title
                    })
                continue

            # Parse location if provided
            location = None
            location_type = location_type_str if location_type_str else None
            if location_str:
                try:
                    location = int(location_str)
                except (ValueError, TypeError):
                    # If location is not a valid integer, skip it
                    location = None
                    location_type = None

            # Create highlight with appropriate boolean flags
            highlight = Highlight(
                text=highlight_text,
                book_id=book.id if book else None,
                note=note if note else None,
                created_at=created_at,
                location_type=location_type,
                location=location,
                user_id=1,  # Default user for single-user mode
                is_favorited=is_favorited,
                is_discarded=is_discarded,
            )
            
            session.add(highlight)
            if is_diagnostic:
                session.commit()
                session.refresh(highlight)
            else:
                session.flush()
            
            # Process regular tags (excluding favorite/discard which are now boolean fields)
            for tag_name in regular_tags:
                tag = get_or_create_tag(session, tag_name)
                if tag:
                    # Create highlight-tag relationship
                    highlight_tag = HighlightTag(
                        highlight_id=highlight.id,
                        tag_id=tag.id
                    )
                    session.add(highlight_tag)
            
            if regular_tags and is_diagnostic:
                session.commit()
            
            imported_count += 1
        
        if not is_diagnostic:
            session.commit()

        # Get settings for theme
        settings = get_settings(session)

        # Return success page
        return templates.TemplateResponse(request, "import_readwise.html", {"settings": settings,
            "success_message": f"Successfully imported {imported_count} highlights. Skipped {skipped_count} rows. Deduplicated {duplicate_count} duplicates.",
            "imported_count": imported_count,
            "skipped_count": skipped_count,
            "duplicate_count": duplicate_count,
            "skipped_rows": skipped_rows})
    
    except HTTPException:
        raise  # Let FastAPI handle HTTP exceptions directly
    except csv.Error as e:
        raise HTTPException(status_code=400, detail=f"Invalid CSV format: {str(e)}")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File encoding error. Please ensure the file is UTF-8 encoded.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


# Legacy route for backward compatibility
@router.post("/ui", response_class=HTMLResponse)
async def process_import_legacy(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session)
):
    """Legacy import route - redirects to Readwise import for backward compatibility."""
    return await process_readwise_import(request, file, diagnostic="true", session=session)
