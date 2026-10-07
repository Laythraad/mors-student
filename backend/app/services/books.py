"""Textbook library: browse → open → read → keep your place.

A book is a real object here, not a PDF on a shelf: `BookPage` rows carry the
extracted text of every page, each page knows its chapter/unit/lesson, and the
student's position, bookmarks and highlights live in `ReadingProgress`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..core.errors import NotFoundError, ValidationError
from ..db import (
    Book,
    BookPage,
    Branch,
    Chapter,
    Lesson,
    ReadingProgress,
    Source,
    Stage,
    StudentProfile,
    StudentSubject,
    Subject,
    Unit,
)


def _book_filters(db: Session, profile: StudentProfile | None, subject_id: str | None):
    q = db.query(Book).join(Subject, Book.subject_id == Subject.id)
    if subject_id:
        q = q.filter(Book.subject_id == subject_id)
    elif profile is not None:
        # A student reads the books of THEIR branch. The stage is only the
        # fallback when the branch is unknown — OR-ing the two widened the
        # scope to every branch of the stage, so a science student was handed
        # the literary shelf as duplicates.
        if profile.branch_id:
            q = q.filter(Subject.branch_id == profile.branch_id)
        elif profile.stage_id:
            stage_branches = [
                b.id for b in db.query(Branch).filter(Branch.stage_id == profile.stage_id)
            ]
            if stage_branches:
                q = q.filter(Subject.branch_id.in_(stage_branches))
    return q


def _subject_labels(db: Session, subject_ids: set[str]) -> dict[str, dict[str, str]]:
    """grade + branch per subject, straight from the curriculum tree."""
    if not subject_ids:
        return {}
    rows = (
        db.query(Subject.id, Stage.name_ar, Branch.name_ar)
        .join(Branch, Subject.branch_id == Branch.id, isouter=True)
        .join(Stage, Branch.stage_id == Stage.id, isouter=True)
        .filter(Subject.id.in_(subject_ids))
        .all()
    )
    return {sid: {"grade": grade or "", "branch": branch or ""} for sid, grade, branch in rows}


def _first_chapters(db: Session, book_ids: list[str]) -> dict[str, str]:
    if not book_ids:
        return {}
    out: dict[str, str] = {}
    for book_id, title in (
        db.query(Chapter.book_id, Chapter.title)
        .filter(Chapter.book_id.in_(book_ids))
        .order_by(Chapter.index)
        .all()
    ):
        out.setdefault(book_id, title)
    return out


def _progress_map(db: Session, profile: StudentProfile | None, book_ids: list[str]) -> dict[str, ReadingProgress]:
    if profile is None or not book_ids:
        return {}
    rows = (
        db.query(ReadingProgress)
        .filter(ReadingProgress.profile_id == profile.id, ReadingProgress.book_id.in_(book_ids))
        .all()
    )
    return {row.book_id: row for row in rows}


def _page_count(db: Session, book: Book) -> int:
    count = db.query(BookPage).filter(BookPage.book_id == book.id).count()
    return count or book.page_count or 0


def _progress_payload(row: ReadingProgress | None, page_count: int) -> dict[str, Any]:
    if row is None:
        return {
            "last_page": 1,
            "percent": 0,
            "bookmarks": [],
            "highlights": [],
            "opened_count": 0,
        }
    percent = round(min(100.0, (row.last_page / page_count) * 100)) if page_count else 0
    return {
        "last_page": row.last_page,
        "percent": percent,
        "bookmarks": row.bookmarks or [],
        "highlights": row.highlights or [],
        "opened_count": row.opened_count,
    }


def list_books(
    db: Session,
    profile: StudentProfile | None = None,
    *,
    subject_id: str | None = None,
    q: str = "",
    limit: int = 60,
) -> dict[str, Any]:
    scope = _book_filters(db, profile, subject_id)

    # A real (ministry) book replaces the demo copy of the same subject: two
    # cards for الرياضيات is a duplicate, not a choice.
    real_subject_ids = {
        sid
        for (sid,) in scope.filter(Book.is_demo.is_(False))
        .with_entities(Book.subject_id)
        .distinct()
        .all()
    }
    if real_subject_ids:
        scope = scope.filter(
            or_(Book.is_demo.is_(False), Book.subject_id.notin_(real_subject_ids))
        )

    term = (q or "").strip()
    if term:
        pattern = f"%{term}%"
        scope = scope.filter(
            or_(
                Book.title.ilike(pattern),
                Book.author.ilike(pattern),
                Book.edition.ilike(pattern),
                Subject.name_ar.ilike(pattern),
            )
        )

    books = scope.order_by(Book.is_demo.asc(), Book.title).limit(limit).all()

    # Chips describe the student's whole shelf, never the filtered page —
    # otherwise a search with no hits erases the filter bar itself.
    chip_ids = {
        sid
        for (sid,) in _book_filters(db, profile, None).with_entities(Book.subject_id).distinct()
    }
    book_ids = [b.id for b in books]
    subject_ids = chip_ids | {b.subject_id for b in books}
    subjects = {
        s.id: s for s in db.query(Subject).filter(Subject.id.in_(subject_ids)).all()
    }
    labels = _subject_labels(db, set(subjects))
    first_chapter = _first_chapters(db, book_ids)
    progress = _progress_map(db, profile, book_ids)

    enrolled: set[str] = set()
    if profile is not None:
        enrolled = {
            row.subject_id
            for row in db.query(StudentSubject)
            .filter(StudentSubject.profile_id == profile.id, StudentSubject.is_active.is_(True))
            .all()
        }

    chapters_by_book: dict[str, int] = {}
    for book_id, count in (
        db.query(Chapter.book_id, func.count(Chapter.id)).group_by(Chapter.book_id).all()
    ):
        chapters_by_book[book_id] = count

    rows = []
    for book in books:
        page_count = _page_count(db, book)
        subject = subjects.get(book.subject_id)
        label = labels.get(book.subject_id, {})
        rows.append(
            {
                "id": book.id,
                "title": book.title,
                "edition": book.edition,
                "author": book.author,
                "cover": book.cover_path or "",
                "is_demo": book.is_demo,
                "subject_id": book.subject_id,
                "subject": subject.name_ar if subject else "",
                "subject_color": subject.color if subject else "#2f8ff7",
                "grade": label.get("grade", ""),
                "branch": label.get("branch", ""),
                "chapter": first_chapter.get(book.id, ""),
                "chapter_count": chapters_by_book.get(book.id, 0),
                "page_count": page_count,
                "recommended": book.subject_id in enrolled,
                "progress": _progress_payload(progress.get(book.id), page_count),
            }
        )

    chips = sorted(
        (
            {
                "id": sid,
                "name": subjects[sid].name_ar,
                "color": subjects[sid].color,
                "recommended": sid in enrolled,
            }
            for sid in chip_ids
            if sid in subjects
        ),
        key=lambda chip: chip["name"],
    )
    return {"books": rows, "subjects": chips}


def get_book(db: Session, book_id: str, profile: StudentProfile | None = None) -> dict[str, Any]:
    book = db.get(Book, book_id)
    if book is None:
        raise NotFoundError("الكتاب غير موجود.")
    subject = db.get(Subject, book.subject_id)

    chapters = (
        db.query(Chapter).filter(Chapter.book_id == book.id).order_by(Chapter.index).all()
    )
    # reader page numbering is global per book, so each lesson gets the page
    # where it actually starts (independent from the printed page ranges)
    first_pages: dict[str, int] = dict(
        db.query(BookPage.lesson_id, func.min(BookPage.page_number))
        .filter(BookPage.book_id == book.id, BookPage.lesson_id.isnot(None))
        .group_by(BookPage.lesson_id)
        .all()
    )

    toc: list[dict[str, Any]] = []
    for chapter in chapters:
        units = db.query(Unit).filter(Unit.chapter_id == chapter.id).order_by(Unit.index).all()
        unit_rows = []
        for unit in units:
            lessons = (
                db.query(Lesson).filter(Lesson.unit_id == unit.id).order_by(Lesson.index).all()
            )
            unit_rows.append(
                {
                    "id": unit.id,
                    "title": unit.title,
                    "lessons": [
                        {
                            "id": lesson.id,
                            "title": lesson.title,
                            "page_start": lesson.page_start,
                            "page_end": lesson.page_end,
                            "first_page": first_pages.get(lesson.id),
                            "difficulty": lesson.difficulty,
                        }
                        for lesson in lessons
                    ],
                }
            )
        toc.append(
            {
                "id": chapter.id,
                "title": chapter.title,
                "index": chapter.index,
                "page_start": chapter.page_start,
                "page_end": chapter.page_end,
                "units": unit_rows,
            }
        )

    if not toc:
        # chapters may be missing while pages already exist — still readable
        toc = [{"id": None, "title": "الكتاب", "index": 1, "page_start": 1, "page_end": None, "units": []}]

    page_count = _page_count(db, book)
    progress = _progress_map(db, profile, [book.id]).get(book.id)
    source = db.get(Source, book.upload_id) if book.upload_id else None
    label = _subject_labels(db, {book.subject_id}).get(book.subject_id, {})

    if profile is not None:
        # Opening the book is what "opened" means — one count per open, not
        # one per page turn. The route commits (get_db only closes).
        record = (
            db.query(ReadingProgress)
            .filter(ReadingProgress.profile_id == profile.id, ReadingProgress.book_id == book.id)
            .one_or_none()
        )
        if record is None:
            record = ReadingProgress(
                profile_id=profile.id, book_id=book.id, last_page=1, opened_count=1
            )
            db.add(record)
        else:
            record.opened_count = (record.opened_count or 0) + 1
        db.flush()
        progress = _progress_payload(record, page_count)

    return {
        "id": book.id,
        "title": book.title,
        "edition": book.edition,
        "author": book.author,
        "cover": book.cover_path or "",
        "is_demo": book.is_demo,
        "page_count": page_count,
        "subject_id": book.subject_id,
        "subject": subject.name_ar if subject else "",
        "subject_color": subject.color if subject else "#2f8ff7",
        "grade": label.get("grade", ""),
        "branch": label.get("branch", ""),
        "chapter": toc[0]["title"] if toc else "",
        "citation": source.citation if source else "",
        "toc": toc,
        "progress": progress if progress is not None else _progress_payload(None, page_count),
        "is_indexed": db.query(BookPage).filter(BookPage.book_id == book.id).count() > 0,
    }


def _page_row(db: Session, book_id: str, page_number: int) -> BookPage | None:
    page = (
        db.query(BookPage)
        .filter(BookPage.book_id == book_id, BookPage.page_number == page_number)
        .one_or_none()
    )
    if page is not None:
        return page
    # tolerate out-of-range requests by clamping to the closest existing page
    fallback = (
        db.query(BookPage)
        .filter(BookPage.book_id == book_id, BookPage.page_number >= page_number)
        .order_by(BookPage.page_number)
        .first()
    )
    if fallback:
        return fallback
    return db.query(BookPage).filter(BookPage.book_id == book_id).order_by(-BookPage.page_number).first()


def page_payload(db: Session, page: BookPage | None) -> dict[str, Any] | None:
    if page is None:
        return None
    chapter = db.get(Chapter, page.chapter_id) if page.chapter_id else None
    unit = db.get(Unit, page.unit_id) if page.unit_id else None
    lesson = db.get(Lesson, page.lesson_id) if page.lesson_id else None
    return {
        "page_number": page.page_number,
        "heading": page.heading,
        "text": page.text,
        "is_demo": page.is_demo,
        "chapter_id": page.chapter_id,
        "chapter": chapter.title if chapter else "",
        "unit_id": page.unit_id,
        "unit": unit.title if unit else "",
        "lesson_id": page.lesson_id,
        "lesson": lesson.title if lesson else "",
        "lesson_title": lesson.title if lesson else "",
    }


def get_page(
    db: Session,
    book_id: str,
    page_number: int,
    profile: StudentProfile | None = None,
) -> dict[str, Any]:
    book = db.get(Book, book_id)
    if book is None:
        raise NotFoundError("الكتاب غير موجود.")
    row = _page_row(db, book_id, page_number)
    if row is None:
        raise NotFoundError("الكتاب فارغ — لم تُستخرج صفحاته بعد.")

    payload = page_payload(db, row)
    assert payload is not None
    page_count = _page_count(db, book)
    chapter_label = payload["chapter"] or ""
    if chapter_label and chapter_label != book.title:
        citation = f"{book.title} — {chapter_label} — صفحة {row.page_number}"
    else:
        citation = f"{book.title} — صفحة {row.page_number}"
    payload.update(
        {
            "book_id": book.id,
            "book_title": book.title,
            "subject_id": book.subject_id,
            "page_count": page_count,
            "prev": row.page_number - 1 if row.page_number > 1 else None,
            "next": row.page_number + 1 if row.page_number < page_count else None,
            "citation": citation,
        }
    )

    if profile is not None:
        # Reading a page saves the place. `opened_count` is owned by
        # get_book (one per open), not by page turns. The route commits.
        record = (
            db.query(ReadingProgress)
            .filter(ReadingProgress.profile_id == profile.id, ReadingProgress.book_id == book.id)
            .one_or_none()
        )
        if record is None:
            record = ReadingProgress(profile_id=profile.id, book_id=book.id, last_page=row.page_number)
            db.add(record)
        else:
            record.last_page = row.page_number
        db.flush()

    return payload


def search_book(db: Session, book_id: str, q: str, limit: int = 20) -> dict[str, Any]:
    book = db.get(Book, book_id)
    if book is None:
        raise NotFoundError("الكتاب غير موجود.")
    term = (q or "").strip()
    if not term:
        return {"results": [], "query": ""}
    pattern = f"%{term}%"
    rows = (
        db.query(BookPage)
        .filter(BookPage.book_id == book_id, or_(BookPage.text.ilike(pattern), BookPage.heading.ilike(pattern)))
        .order_by(BookPage.page_number)
        .limit(limit)
        .all()
    )
    results = []
    for row in rows:
        index = row.text.lower().find(term.lower())
        snippet = ""
        if index >= 0:
            start = max(0, index - 70)
            snippet = ("…" if start else "") + row.text[start : index + len(term) + 110].strip() + "…"
        else:
            snippet = (row.text or "")[:160].strip()
        chapter = db.get(Chapter, row.chapter_id) if row.chapter_id else None
        results.append(
            {
                "page_number": row.page_number,
                "heading": row.heading,
                "chapter": chapter.title if chapter else "",
                "snippet": snippet,
            }
        )
    return {"results": results, "query": term}


def get_progress(db: Session, profile: StudentProfile, book_id: str) -> dict[str, Any]:
    book = db.get(Book, book_id)
    if book is None:
        raise NotFoundError("الكتاب غير موجود.")
    row = (
        db.query(ReadingProgress)
        .filter(ReadingProgress.profile_id == profile.id, ReadingProgress.book_id == book_id)
        .one_or_none()
    )
    return _progress_payload(row, _page_count(db, book))


def save_progress(
    db: Session,
    profile: StudentProfile,
    book_id: str,
    *,
    last_page: int | None = None,
    bookmark: dict[str, Any] | None = None,
    remove_bookmark: int | None = None,
    highlight: dict[str, Any] | None = None,
    remove_highlight: int | None = None,
) -> dict[str, Any]:
    book = db.get(Book, book_id)
    if book is None:
        raise NotFoundError("الكتاب غير موجود.")
    if last_page is not None and last_page < 0:
        raise ValidationError("رقم الصفحة غير صالح.")

    row = (
        db.query(ReadingProgress)
        .filter(ReadingProgress.profile_id == profile.id, ReadingProgress.book_id == book_id)
        .one_or_none()
    )
    if row is None:
        row = ReadingProgress(profile_id=profile.id, book_id=book_id)
        db.add(row)

    if last_page is not None:
        row.last_page = int(last_page)
    if bookmark is not None:
        page = int(bookmark.get("page") or 0)
        if page > 0:
            marks = [b for b in (row.bookmarks or []) if b.get("page") != page]
            marks.append({"page": page, "label": str(bookmark.get("label") or "")[:120]})
            row.bookmarks = sorted(marks, key=lambda b: b.get("page") or 0)
    if remove_bookmark is not None:
        row.bookmarks = [b for b in (row.bookmarks or []) if b.get("page") != remove_bookmark]
    if highlight is not None:
        text = str(highlight.get("text") or "").strip()
        if text:
            items = [
                h
                for h in (row.highlights or [])
                if h.get("text") != text or h.get("page") != highlight.get("page")
            ]
            items.append(
                {
                    "page": int(highlight.get("page") or 0),
                    "text": text[:800],
                    "note": str(highlight.get("note") or "")[:400],
                }
            )
            row.highlights = items[-200:]
    if remove_highlight is not None:
        row.highlights = [h for h in (row.highlights or []) if int(h.get("page") or -1) != remove_highlight]

    db.flush()
    return _progress_payload(row, _page_count(db, book))


__all__ = [
    "list_books",
    "get_book",
    "get_page",
    "page_payload",
    "search_book",
    "get_progress",
    "save_progress",
]
