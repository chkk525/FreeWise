from typing import Optional, List
from fastapi import APIRouter, Depends, Request, Form, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, func
from datetime import datetime
import os
import uuid
import aiofiles
import httpx

from app.db import get_session, get_settings
from app.models import Book, Highlight, Settings


router = APIRouter(prefix="/library", tags=["library"])
templates = Jinja2Templates(directory="app/templates")

COVER_UPLOAD_DIR = os.path.join("app", "static", "uploads", "covers")
ALLOWED_COVER_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_COVER_SIZE_BYTES = 5 * 1024 * 1024


DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


@router.get("/ui", response_class=HTMLResponse)
async def ui_library(
    request: Request,
    sort: Optional[str] = "highlight_count",
    order: Optional[str] = "desc",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    session: Session = Depends(get_session)
):
    """Render library page with sortable + paginated table of books.

    At 3,780+ books an unpaginated render took ~0.5s on prod due to ORM
    hydration of every row. Server-side OFFSET/LIMIT keeps initial render
    sub-100ms. Default sort flipped to highlight_count desc since that's
    by far the most useful entry view.

    Query params: sort (title|author|highlight_count|last_highlight),
    order (asc|desc), page (1-based), page_size (1..200).
    """
    settings = get_settings(session)

    valid_sorts = {"title", "author", "highlight_count", "last_highlight"}
    if sort not in valid_sorts:
        sort = "highlight_count"
    if order not in ("asc", "desc"):
        order = "desc"

    page = max(1, page)
    page_size = max(1, min(MAX_PAGE_SIZE, page_size))

    highlight_count_col = func.count(Highlight.id).label("highlight_count")
    last_highlight_col = func.max(Highlight.created_at).label("last_highlight_date")

    books_query = (
        select(
            Book.id,
            Book.title,
            Book.author,
            Book.document_tags,
            highlight_count_col,
            last_highlight_col,
        )
        .outerjoin(Highlight, Book.id == Highlight.book_id)
        .group_by(Book.id)
    )

    sort_col = {
        "title": Book.title,
        "author": Book.author,
        "highlight_count": highlight_count_col,
        "last_highlight": last_highlight_col,
    }[sort]
    books_query = books_query.order_by(sort_col.desc() if order == "desc" else sort_col.asc())

    total = session.exec(select(func.count()).select_from(Book)).one()
    if isinstance(total, tuple):
        total = total[0]
    total_pages = max(1, (total + page_size - 1) // page_size)
    if page > total_pages:
        page = total_pages

    page_query = books_query.offset((page - 1) * page_size).limit(page_size)
    results = session.exec(page_query).all()

    books = [
        {
            "id": r.id,
            "title": r.title,
            "author": r.author or "Unknown",
            "document_tags": r.document_tags,
            "highlight_count": r.highlight_count,
            "last_highlight_date": r.last_highlight_date,
        }
        for r in results
    ]

    showing_first = 0 if total == 0 else (page - 1) * page_size + 1
    showing_last = min(page * page_size, total)

    return templates.TemplateResponse(
        request,
        "library.html",
        {
            "settings": settings,
            "books": books,
            "current_sort": sort,
            "current_order": order,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "showing_first": showing_first,
            "showing_last": showing_last,
        },
    )


@router.get("/ui/book/{book_id}", response_class=HTMLResponse)
async def ui_book_detail(
    request: Request,
    book_id: int,
    session: Session = Depends(get_session)
):
    """Display all highlights from a specific book."""
    # Get settings for theme
    settings = get_settings(session)

    # Get book
    book = session.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    
    # Get all highlights for this book, ordered by location if available, then by date
    # Order: location ASC (if available), created_at DESC (for fallback)
    highlights_stmt = (
        select(Highlight)
        .where(Highlight.book_id == book_id)
        .order_by(
            Highlight.location.asc().nullslast(),  # Location first (page/order), nulls last
            Highlight.created_at.desc()             # Then by date
        )
    )
    highlights = session.exec(highlights_stmt).all()
    
    return templates.TemplateResponse(request, "book_detail.html", {"settings": settings,
        "book": book,
        "highlights": highlights})


@router.post("/ui/book/{book_id}/cover/upload", response_class=HTMLResponse)
async def ui_book_cover_upload(
    request: Request,
    book_id: int,
    cover_file: UploadFile = File(...),
    session: Session = Depends(get_session)
):
    """Upload a cover image for a book and return updated cover section."""
    book = session.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    if cover_file.content_type not in ALLOWED_COVER_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    original_name = cover_file.filename or ""
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in ALLOWED_COVER_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file extension")

    content = await cover_file.read()
    if len(content) > MAX_COVER_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File is too large")

    _delete_existing_cover_file(book)
    os.makedirs(COVER_UPLOAD_DIR, exist_ok=True)
    filename = f"book-{book_id}-{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(COVER_UPLOAD_DIR, filename)

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    book.cover_image_url = f"/static/uploads/covers/{filename}"
    book.cover_image_source = "upload"
    session.add(book)
    session.commit()
    session.refresh(book)

    return _render_cover_section(request, book)


@router.post("/ui/book/{book_id}/cover/search", response_class=HTMLResponse)
async def ui_book_cover_search(
    request: Request,
    book_id: int,
    query: str = Form(""),
    session: Session = Depends(get_session)
):
    """Search Open Library for book covers and return search results HTML."""
    book = session.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    search_query = query.strip()
    if not search_query:
        return _render_cover_search_results(request, book_id, [], "")

    results: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://openlibrary.org/search.json",
                params={"q": search_query, "limit": 8}
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError:
        return HTMLResponse(content="<div class=\"text-sm text-gray-500 dark:text-gray-400 text-center\">Open Library search failed. Please try again.</div>")

    for doc in data.get("docs", []):
        cover_id = doc.get("cover_i")
        if not cover_id:
            continue
        title = doc.get("title") or "Untitled"
        author_list = doc.get("author_name") or []
        author = author_list[0] if author_list else "Unknown"
        year = doc.get("first_publish_year")
        results.append({
            "cover_id": cover_id,
            "title": title,
            "author": author,
            "year": year
        })

    return _render_cover_search_results(request, book_id, results, search_query)


@router.post("/ui/book/{book_id}/cover/select", response_class=HTMLResponse)
async def ui_book_cover_select(
    request: Request,
    book_id: int,
    cover_url: str = Form(""),
    session: Session = Depends(get_session)
):
    """Select an Open Library cover image for a book and return updated cover section."""
    book = session.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    if not (cover_url.startswith("https://covers.openlibrary.org/") or cover_url.startswith("http://covers.openlibrary.org/")):
        raise HTTPException(status_code=400, detail="Invalid cover URL")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(cover_url, follow_redirects=True)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            content = response.content
    except httpx.HTTPError:
        return HTMLResponse(
            content="<div class=\"text-sm text-red-600 dark:text-red-400 text-center\">Failed to download cover image. Please try again.</div>",
            status_code=400
        )

    ext = os.path.splitext(cover_url)[1].lower()
    inferred_ok = ext in ALLOWED_COVER_EXTENSIONS
    if content_type and content_type not in ALLOWED_COVER_TYPES and not inferred_ok:
        return HTMLResponse(
            content="<div class=\"text-sm text-red-600 dark:text-red-400 text-center\">Unsupported cover image type.</div>",
            status_code=400
        )

    if len(content) > MAX_COVER_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Cover image is too large")

    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    if content_type in ext_map:
        ext = ext_map[content_type]
    elif inferred_ok:
        ext = os.path.splitext(cover_url)[1].lower()
    else:
        ext = ".jpg"

    _delete_existing_cover_file(book)
    os.makedirs(COVER_UPLOAD_DIR, exist_ok=True)
    filename = f"book-{book_id}-{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(COVER_UPLOAD_DIR, filename)

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    book.cover_image_url = f"/static/uploads/covers/{filename}"
    book.cover_image_source = "openlibrary"
    session.add(book)
    session.commit()
    session.refresh(book)

    return _render_cover_section(request, book)


@router.post("/ui/book/{book_id}/cover/delete", response_class=HTMLResponse)
async def ui_book_cover_delete(
    request: Request,
    book_id: int,
    session: Session = Depends(get_session)
):
    """Delete the existing cover image for a book and return updated cover section."""
    book = session.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    _delete_existing_cover_file(book)
    book.cover_image_url = None
    book.cover_image_source = None
    session.add(book)
    session.commit()
    session.refresh(book)

    return _render_cover_section(request, book)


@router.get("/ui/book/{book_id}/edit", response_class=HTMLResponse)
async def ui_book_edit_form(
    request: Request,
    book_id: int,
    session: Session = Depends(get_session)
):
    """Return inline form for editing book metadata."""
    book = session.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")

    return templates.TemplateResponse(request, "_book_edit_form.html", {"book": book})


@router.post("/ui/book/{book_id}/edit", response_class=HTMLResponse)
async def ui_book_update(
    request: Request,
    book_id: int,
    title: str = Form(...),
    author: str = Form(""),
    review_weight: float = Form(1.0),
    session: Session = Depends(get_session)
):
    """Update book metadata and return updated header."""
    book = session.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    
    # Update book metadata
    book.title = title.strip()
    book.author = author.strip() if author.strip() else None
    book.review_weight = min(2.0, max(0.0, float(review_weight)))
    
    session.add(book)
    session.commit()
    session.refresh(book)
    
    # Highlight count via SQL aggregate (perf H5) — pre-fix this hydrated
    # every Highlight row just to call len().
    highlight_count = session.exec(
        select(func.count(Highlight.id)).where(Highlight.book_id == book_id)
    ).one()
    if isinstance(highlight_count, tuple):
        highlight_count = highlight_count[0]

    return _render_book_header(request, book, highlight_count)


@router.get("/ui/book/{book_id}/cancel-edit", response_class=HTMLResponse)
async def ui_book_cancel_edit(
    request: Request,
    book_id: int,
    session: Session = Depends(get_session)
):
    """Cancel editing and return normal book header."""
    book = session.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    
    # Highlight count via SQL aggregate (perf H5) — pre-fix this hydrated
    # every Highlight row just to call len().
    highlight_count = session.exec(
        select(func.count(Highlight.id)).where(Highlight.book_id == book_id)
    ).one()
    if isinstance(highlight_count, tuple):
        highlight_count = highlight_count[0]

    return _render_book_header(request, book, highlight_count)


@router.get("/ui/book/{book_id}/add-tag", response_class=HTMLResponse)
async def ui_book_add_tag_form(
    request: Request,
    book_id: int,
    session: Session = Depends(get_session)
):
    """Return inline form for adding a new tag."""
    book = session.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    
    form_html = f"""
    <form hx-post="/library/ui/book/{book_id}/add-tag" hx-target="#document-tags-section" hx-swap="innerHTML" style="display: inline-block;">
        <input 
            type="text" 
            name="new_tag" 
            placeholder="Enter new tag..."
            style="padding: 8px 12px; border: 1px solid var(--border-color); border-radius: 4px; background: var(--bg-color); color: var(--text-color); min-width: 200px;"
            autofocus>
        <button type="submit" style="margin-left: 8px; padding: 8px 16px; background: var(--link-color); color: white; border: none; border-radius: 4px; cursor: pointer;">Add</button>
        <button type="button" 
            hx-get="/library/ui/book/{book_id}/cancel-add-tag" 
            hx-target="#add-tag-form" 
            hx-swap="innerHTML"
            style="margin-left: 8px; padding: 8px 16px; background: transparent; color: var(--muted-text); border: 1px solid var(--border-color); border-radius: 4px; cursor: pointer;">Cancel</button>
    </form>
    """
    return HTMLResponse(content=form_html)


@router.post("/ui/book/{book_id}/add-tag", response_class=HTMLResponse)
async def ui_book_add_tag(
    request: Request,
    book_id: int,
    new_tag: str = Form(""),
    session: Session = Depends(get_session)
):
    """Add a new tag to the book and return updated tags section."""
    book = session.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    
    # Add new tag
    new_tag = new_tag.strip()
    if new_tag:
        if book.document_tags:
            # Split existing tags, add new one, deduplicate
            existing_tags = [t.strip() for t in book.document_tags.split(',')]
            if new_tag not in existing_tags:
                existing_tags.append(new_tag)
            book.document_tags = ', '.join(existing_tags)
        else:
            book.document_tags = new_tag
        
        session.add(book)
        session.commit()
        session.refresh(book)
    
    # Return updated tags section
    return _render_tags_section(request, book)


@router.post("/ui/book/{book_id}/remove-tag", response_class=HTMLResponse)
async def ui_book_remove_tag(
    request: Request,
    book_id: int,
    tag: str = Form(...),
    session: Session = Depends(get_session)
):
    """Remove a tag from the book and return updated tags section."""
    book = session.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    
    # Remove tag
    if book.document_tags:
        existing_tags = [t.strip() for t in book.document_tags.split(',')]
        existing_tags = [t for t in existing_tags if t != tag.strip()]
        book.document_tags = ', '.join(existing_tags) if existing_tags else None
        
        session.add(book)
        session.commit()
        session.refresh(book)
    
    # Return updated tags section
    return _render_tags_section(request, book)


@router.get("/ui/book/{book_id}/cancel-add-tag", response_class=HTMLResponse)
async def ui_book_cancel_add_tag(
    request: Request,
    book_id: int,
    session: Session = Depends(get_session)
):
    """Cancel adding a tag."""
    return HTMLResponse(content="")


@router.delete("/ui/book/{book_id}", response_class=HTMLResponse)
async def ui_book_delete(
    request: Request,
    book_id: int,
    session: Session = Depends(get_session)
):
    """Delete a book and all its highlights from the library."""
    book = session.get(Book, book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    
    # Bulk delete instead of N×DELETE round-trips (perf H4). On a book
    # with hundreds of highlights this drops from O(n) to O(1) statements.
    from sqlalchemy import delete as sa_delete
    session.exec(sa_delete(Highlight).where(Highlight.book_id == book_id))
    # And the book row.
    session.delete(book)
    session.commit()
    
    # Return response that triggers redirect to library
    return HTMLResponse(
        content="",
        headers={"HX-Redirect": "/library/ui"}
    )


def _render_cover_section(request: Request, book: Book) -> HTMLResponse:
    """Render the cover image display section only."""
    return templates.TemplateResponse(request, "_cover_section.html", {"book": book})


def _render_cover_search_results(request: Request, book_id: int, results: list[dict], query: str) -> HTMLResponse:
    """Render Open Library cover search results list."""
    return templates.TemplateResponse(request, "_cover_search_results.html", {"book_id": book_id,
        "results": results,
        "query": query})


def _render_tags_section(request: Request, book: Book) -> HTMLResponse:
    """Render the document tags section."""
    return templates.TemplateResponse(request, "_tags_section.html", {"book": book})


def _delete_existing_cover_file(book: Book) -> None:
    """Delete existing local cover file if present."""
    if not book.cover_image_url:
        return
    if not book.cover_image_url.startswith("/static/uploads/covers/"):
        return

    filename = book.cover_image_url.split("/")[-1]
    file_path = os.path.join(COVER_UPLOAD_DIR, filename)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except OSError:
        pass


def _render_book_header(request: Request, book: Book, highlight_count: int) -> HTMLResponse:
    """Render the book header section."""
    return templates.TemplateResponse(request, "_book_header.html", {"book": book,
        "highlight_count": highlight_count})
