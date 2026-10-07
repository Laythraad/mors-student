"""RAG ingestion: PDF/image/text → clean → chunk → embed → index."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..db import AIChunk, Book, Lesson, Source, Upload
from .chunker import Chunk, chunk_pages, clean_text
from .embedder import embed, term_frequencies
from .ocr import Extraction, extract_image, extract_pdf, extract_text_file

logger = logging.getLogger(__name__)


def index_chunks(
    db: Session,
    chunks: list[Chunk],
    *,
    upload_id: str | None = None,
    book_id: str | None = None,
    lesson_id: str | None = None,
    source_id: str | None = None,
    subject_id: str | None = None,
    replace: bool = True,
) -> int:
    """Persist chunks with embeddings. Returns the number indexed."""
    if replace and upload_id:
        db.query(AIChunk).filter(AIChunk.upload_id == upload_id).delete(synchronize_session=False)

    count = 0
    for chunk in chunks:
        db.add(
            AIChunk(
                upload_id=upload_id,
                book_id=book_id,
                lesson_id=lesson_id or chunk.meta.get("lesson_id"),
                source_id=source_id,
                subject_id=subject_id,
                seq=chunk.seq,
                text=chunk.text,
                embedding=embed(chunk.text),
                terms=term_frequencies(chunk.text),
                meta=dict(chunk.meta),
                indexed=True,
            )
        )
        count += 1
    db.flush()
    return count


def index_extraction(
    db: Session,
    extraction: Extraction,
    *,
    upload_id: str | None = None,
    book_id: str | None = None,
    lesson_id: str | None = None,
    source_id: str | None = None,
    subject_id: str | None = None,
    title: str = "",
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> int:
    base_meta: dict[str, Any] = {"title": title, "engine": extraction.engine}
    chunks = chunk_pages(
        extraction.pages,
        chunk_size=chunk_size or settings.rag_chunk_size,
        overlap=overlap or settings.rag_chunk_overlap,
        meta=base_meta,
    )
    return index_chunks(
        db,
        chunks,
        upload_id=upload_id,
        book_id=book_id,
        lesson_id=lesson_id,
        source_id=source_id,
        subject_id=subject_id,
    )


def ingest_upload(db: Session, upload: Upload) -> int:
    """Full pipeline for an uploaded file; updates `upload.status` as it goes."""
    path = Path(upload.path)
    upload.status = "scanning"
    db.flush()

    try:
        if not path.exists():
            raise FileNotFoundError(upload.path)
        suffix = path.suffix.lower()

        if suffix == ".pdf":
            extraction = extract_pdf(path)
        elif suffix in {".txt", ".md"}:
            extraction = extract_text_file(path)
        elif suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            extraction = extract_image(path, hint=upload.filename)
        else:
            raise ValueError(f"unsupported type: {suffix}")

        upload.extracted_text = clean_text(extraction.text)[:200_000]
        upload.ocr_engine = extraction.engine
        upload.status = "indexing"
        db.flush()

        if not upload.extracted_text.strip():
            upload.status = "failed"
            upload.error = "لم يتم استخراج أي نص من الملف."
            db.flush()
            return 0

        count = index_extraction(
            db,
            extraction,
            upload_id=upload.id,
            book_id=upload.book_id,
            lesson_id=upload.lesson_id,
            subject_id=upload.subject_id,
            title=upload.filename,
        )
        upload.status = "ready"
        upload.error = ""
        upload.meta = {
            **(upload.meta or {}),
            "pages": len(extraction.pages),
            "chars": extraction.chars,
            "chunks": count,
            "engine": extraction.engine,
        }
        db.flush()
        return count
    except Exception as exc:  # noqa: BLE001 - status must reflect the failure
        logger.exception("ingest failed for %s", upload.filename)
        upload.status = "failed"
        upload.error = str(exc)[:300]
        db.flush()
        return 0


def index_book(db: Session, book: Book) -> int:
    """(Re)build the retrieval index for a book's pages.

    Page-level rows are the source of truth: every chunk remembers its page so
    an answer can be cited as *book → chapter → page*. Falls back to lesson
    pages for books that were seeded before the reader existed.
    """
    from ..db import BookPage, Chapter, Lesson, Unit

    pages = (
        db.query(BookPage)
        .filter(BookPage.book_id == book.id)
        .order_by(BookPage.page_number)
        .all()
    )

    if pages:
        chapters = {c.id: c.title for c in db.query(Chapter).filter(Chapter.book_id == book.id)}
        units = {u.id: u.title for u in db.query(Unit).join(Chapter, Unit.chapter_id == Chapter.id).filter(Chapter.book_id == book.id)}
        lessons = {l.id: l.title for l in db.query(Lesson).filter(Lesson.subject_id == book.subject_id)}

        db.query(AIChunk).filter(AIChunk.book_id == book.id).delete(synchronize_session=False)
        db.flush()

        total = 0
        batch_size = 40
        for start in range(0, len(pages), batch_size):
            window = pages[start : start + batch_size]
            pairs = [(p.page_number, p.text.strip()) for p in window if (p.text or "").strip()]
            if not pairs:
                continue
            base_meta: dict[str, Any] = {
                "title": book.title,
                "book": book.title,
                "book_id": book.id,
                "engine": "book",
            }
            chunks = chunk_pages(
                pairs,
                chunk_size=settings.rag_chunk_size,
                overlap=settings.rag_chunk_overlap,
                meta=base_meta,
            )
            by_number = {p.page_number: p for p in window}
            for chunk in chunks:
                page_row = by_number.get(chunk.meta.get("page"))
                if page_row is None:
                    continue
                if page_row.chapter_id:
                    chunk.meta["chapter"] = chapters.get(page_row.chapter_id, "")
                if page_row.unit_id:
                    chunk.meta["unit"] = units.get(page_row.unit_id, "")
                if page_row.lesson_id:
                    chunk.meta["lesson"] = lessons.get(page_row.lesson_id, "")
                    chunk.meta["lesson_id"] = page_row.lesson_id
                chunk.meta["citation"] = (
                    f"{book.title} — {chunk.meta.get('chapter') or 'الكتاب'} — صفحة {page_row.page_number}"
                )
            total += index_chunks(
                db,
                chunks,
                book_id=book.id,
                subject_id=book.subject_id,
                replace=False,
            )
        return total

    # legacy path: pages only exist as lesson pages
    chapter_ids = [row.id for row in db.query(Chapter).filter(Chapter.book_id == book.id)]
    if not chapter_ids:
        return 0
    lessons = db.query(Lesson).filter(Lesson.chapter_id.in_(chapter_ids)).all()
    total = 0
    for lesson in lessons:
        lesson_pages = [(p.page_number, p.text) for p in lesson.pages if p.text.strip()]
        if not lesson_pages:
            continue
        extraction = Extraction(
            pages=lesson_pages, engine="book", chars=sum(len(t) for _, t in lesson_pages)
        )
        total += index_extraction(
            db,
            extraction,
            book_id=book.id,
            lesson_id=lesson.id,
            source_id=lesson.source_id,
            subject_id=lesson.subject_id,
            title=f"{book.title} — {lesson.title}",
        )
    return total


def build_source_citation(source: Source | None, book: Book | None = None) -> str:
    if source and source.citation:
        return source.citation
    bits: list[str] = []
    if book:
        bits.append(book.title)
    if source:
        if source.lesson_id:
            bits.append(source.lesson_id)
        if source.page_number:
            bits.append(f"صفحة {source.page_number}")
    return " — ".join(bits)


__all__ = ["index_chunks", "index_extraction", "ingest_upload", "index_book"]
