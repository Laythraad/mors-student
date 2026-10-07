"""Hybrid retrieval: cosine similarity + BM25 over the local chunk store.

No external vector database is required — embeddings live as JSON on
`ai_chunks` and are scored in-process. That is a deliberate trade: it keeps
the whole RAG stack runnable on a student's machine with no services.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..db import AIChunk, Lesson, Source, Subject
from .embedder import bm25_score, cosine, inverse_document_frequency, tokens

MAX_CANDIDATES = 3000


def _citation_for(db: Session, chunk: AIChunk) -> dict[str, Any]:
    from ..db import Book, Chapter

    source = db.get(Source, chunk.source_id) if chunk.source_id else None
    lesson = db.get(Lesson, chunk.lesson_id) if chunk.lesson_id else None
    subject = db.get(Subject, chunk.subject_id) if chunk.subject_id else None
    book = db.get(Book, chunk.book_id) if chunk.book_id else None
    chapter_title = str(chunk.meta.get("chapter") or "")
    if not chapter_title and source and source.chapter_id:
        chapter_row = db.get(Chapter, source.chapter_id)
        chapter_title = chapter_row.title if chapter_row else ""
    book_title = (book.title if book else None) or str(chunk.meta.get("book") or "")
    if chapter_title and chapter_title == book_title:
        chapter_title = ""  # demo seeds name chapters after the book

    if source and source.citation:
        citation = source.citation
    else:
        bits = []
        if book_title:
            bits.append(book_title)
        elif subject:
            bits.append(subject.name_ar)
        if chapter_title:
            bits.append(chapter_title)
        if lesson:
            bits.append(lesson.title)
        page = source.page_number if source else chunk.meta.get("page")
        if page:
            bits.append(f"صفحة {page}")
        citation = " — ".join(bits) if bits else (chunk.meta.get("title") or "")

    return {
        "citation": citation,
        "title": (source.title if source else chunk.meta.get("title", "")) or "",
        "book": book_title,
        "chapter": chapter_title,
        "lesson": lesson.title if lesson else (chunk.meta.get("lesson") or ""),
        "page": (source.page_number if source else None) or chunk.meta.get("page"),
        "subject": subject.name_ar if subject else "",
        "source_id": chunk.source_id,
    }


def _filters(
    student_id: str | None,
    subject_id: str | None,
    lesson_id: str | None,
    upload_only: bool,
) -> dict[str, Any]:
    conds: list[Any] = [AIChunk.indexed.is_(True)]
    if subject_id:
        conds.append(AIChunk.subject_id == subject_id)
    if lesson_id:
        conds.append(AIChunk.lesson_id == lesson_id)
    if upload_only:
        conds.append(AIChunk.upload_id.isnot(None))
    return {"conds": conds}


def hybrid_search(
    db: Session,
    query: str,
    *,
    student_id: str | None = None,
    subject_id: str | None = None,
    lesson_id: str | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
) -> list[dict[str, Any]]:
    """Return the most relevant chunks, each carrying its citation."""
    if not query or not query.strip():
        return []
    top_k = top_k or settings.rag_top_k
    threshold = settings.rag_min_score if min_score is None else min_score

    # Prefer a lesson-scoped search first, then widen — this keeps retrieval
    # cheap while still answering cross-lesson questions.
    rows = (
        db.query(AIChunk)
        .filter(*_filters(student_id, subject_id, lesson_id, False)["conds"])
        .limit(MAX_CANDIDATES)
        .all()
    )
    if not rows and subject_id:
        rows = db.query(AIChunk).filter(AIChunk.indexed.is_(True)).limit(MAX_CANDIDATES).all()
    if not rows:
        rows = db.query(AIChunk).filter(AIChunk.indexed.is_(True)).limit(MAX_CANDIDATES).all()
    if not rows:
        return []

    terms = [r.terms or {} for r in rows]
    idf = inverse_document_frequency(terms)
    lengths = [sum(t.values()) for t in terms]
    avg_len = (sum(lengths) / len(lengths)) if lengths else 1.0
    query_tokens = set(tokens(query))

    results: list[dict[str, Any]] = []
    for row, doc_terms, doc_len in zip(rows, terms, lengths):
        if query_tokens and not query_tokens.intersection(doc_terms):
            # cheap lexical pre-filter; embedding still gets a chance below
            semantic = cosine(query_embedding_cache(query), row.embedding or [])
            if semantic < 0.35:
                continue
        dense = cosine(query_embedding_cache(query), row.embedding or [])
        sparse = bm25_score(query, doc_terms or {}, doc_len, avg_len, idf)
        score = 0.6 * dense + 0.4 * min(sparse / 6.0, 1.0)
        if score < threshold:
            continue
        meta = dict(row.meta or {})
        meta.update(_citation_for(db, row))
        results.append(
            {
                "chunk_id": row.id,
                "text": row.text,
                "score": round(float(score), 4),
                "dense": round(dense, 4),
                "sparse": round(min(sparse / 6.0, 1.0), 4),
                "lesson_id": row.lesson_id,
                "subject_id": row.subject_id,
                "meta": meta,
                **meta,
            }
        )

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]


_embedding_cache: dict[str, list[float]] = {}


def query_embedding_cache(query: str) -> list[float]:
    from .embedder import embed

    key = query.strip()
    if key not in _embedding_cache:
        if len(_embedding_cache) > 512:
            _embedding_cache.clear()
        _embedding_cache[key] = embed(key)
    return _embedding_cache[key]


def clear_query_cache() -> None:
    _embedding_cache.clear()


__all__ = ["hybrid_search", "clear_query_cache"]
