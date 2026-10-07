"""Textbook library: browsing, reading, in-book search and reading progress."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ...core.deps import AdminUser, CurrentProfile, DbSession
from ...core.errors import NotFoundError
from ...db import Book, BookPage, StudentProfile
from ...services import books as service

router = APIRouter(prefix="/books", tags=["books"])


class ProgressIn(BaseModel):
    last_page: int | None = Field(default=None, ge=1, le=100000)
    bookmark: dict[str, Any] | None = None
    remove_bookmark: int | None = None
    highlight: dict[str, Any] | None = None
    remove_highlight: int | None = None


@router.get("")
def index(
    db: DbSession,
    profile: CurrentProfile,
    subject_id: str | None = None,
    q: str = Query("", max_length=120),
    limit: int = Query(60, ge=1, le=200),
) -> dict[str, Any]:
    return service.list_books(db, profile, subject_id=subject_id, q=q, limit=limit)


@router.get("/{book_id}")
def detail(book_id: str, db: DbSession, profile: CurrentProfile) -> dict[str, Any]:
    row = service.get_book(db, book_id, profile)
    # get_book records the open; get_db() only closes the session, and a
    # closed session rolls back — without this the counter never moved.
    db.commit()
    return row


@router.get("/{book_id}/page")
def page(
    book_id: str,
    db: DbSession,
    profile: CurrentProfile,
    n: int = Query(1, ge=1, le=100000),
) -> dict[str, Any]:
    row = service.get_page(db, book_id, n, profile)
    # reading is what saves the place; commit so the position survives
    db.commit()
    return row


@router.get("/{book_id}/search")
def search(
    book_id: str,
    db: DbSession,
    profile: CurrentProfile,
    q: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=50),
) -> dict[str, Any]:
    return service.search_book(db, book_id, q, limit)


@router.get("/{book_id}/progress")
def progress(book_id: str, db: DbSession, profile: CurrentProfile) -> dict[str, Any]:
    return service.get_progress(db, profile, book_id)


@router.put("/{book_id}/progress")
def save_progress(book_id: str, payload: ProgressIn, db: DbSession, profile: CurrentProfile) -> dict[str, Any]:
    row = service.save_progress(
        db,
        profile,
        book_id,
        last_page=payload.last_page,
        bookmark=payload.bookmark,
        remove_bookmark=payload.remove_bookmark,
        highlight=payload.highlight,
        remove_highlight=payload.remove_highlight,
    )
    db.commit()
    return row


@router.post("/{book_id}/reindex")
def reindex(book_id: str, db: DbSession, admin: AdminUser) -> dict[str, Any]:
    """(Re)build the search/embedding index for a book's pages."""
    from ...rag.ingest import index_book

    book = db.get(Book, book_id)
    if book is None:
        raise NotFoundError("الكتاب غير موجود.")
    if not db.query(BookPage).filter(BookPage.book_id == book.id).count():
        raise NotFoundError("لا توجد صفحات مستخرجة لهذا الكتاب بعد.")
    indexed = index_book(db, book)
    db.commit()
    return {"indexed": indexed, "book_id": book.id}


__all__ = ["router"]
