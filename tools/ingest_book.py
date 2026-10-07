"""Ingest real curriculum PDFs (الرابع العلمي) into the library + RAG index.

Creates Book + BookPage rows from extracted PDF text, then builds the
retrieval index (AIChunks) so the reader, in-book search and chat citations
all work on real content. Idempotent: a book that already exists is skipped.

Run from the project root (backend deps installed):

    python -X utf8 tools/ingest_book.py            # ingest all mapped books
    python -X utf8 tools/ingest_book.py --only MATH
    python -X utf8 tools/ingest_book.py --status   # what is already ingested
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

CONTENT_DIR = Path(r"C:\Users\sha\Desktop\student\رابع اعدادي")

# PDF file name -> subject code (grade12 / science branch).
BOOKS: dict[str, str] = {
    "كتاب الاحياء الرابع العلمي.pdf": "BIO",
    "كتاب الرياضيات الرابع العلمي.pdf": "MATH",
    "كتاب الفيزياء الرابع العلمي.pdf": "PHY",
    "كتاب الكيمياء الرابع العلمي.pdf": "CHEM",
}

STAGE_CODE = "grade12"
BRANCH_CODE = "science"
MIN_CHARS = 500  # below this the PDF is scanned images, not text


def heading_from(text: str) -> str:
    for line in text.splitlines():
        line = " ".join(line.split()).strip()
        if line:
            return line[:100]
    return ""


def resolve_subject(db, code: str):
    from app.db import Branch, Stage, Subject

    stage = db.query(Stage).filter(Stage.code == STAGE_CODE).first()
    branch = (
        db.query(Branch)
        .filter(Branch.stage_id == stage.id, Branch.code == BRANCH_CODE)
        .first()
        if stage
        else None
    )
    if not stage or not branch:
        raise SystemExit("stage/branch not found: %s/%s" % (STAGE_CODE, BRANCH_CODE))
    return db.query(Subject).filter(Subject.branch_id == branch.id, Subject.code == code).first()


def ingest(db, pdf_name: str, code: str) -> str:
    from app.db import Book, BookPage
    from app.rag.ingest import index_book
    from app.rag.ocr import extract_pdf

    pdf = CONTENT_DIR / pdf_name
    if not pdf.exists():
        return "SKIP (file missing): %s" % pdf_name

    subject = resolve_subject(db, code)
    if subject is None:
        return "SKIP (subject %s not found): %s" % (code, pdf_name)

    title = pdf.stem
    existing = (
        db.query(Book).filter(Book.subject_id == subject.id, Book.title == title).first()
    )
    if existing:
        pages = db.query(BookPage).filter(BookPage.book_id == existing.id).count()
        return "OK (already ingested): %s pages=%d" % (title, pages)

    extraction = extract_pdf(pdf)
    if extraction.chars < MIN_CHARS:
        return "FAIL (no extractable text, scanned?): %s chars=%d" % (pdf_name, extraction.chars)

    book = Book(
        subject_id=subject.id,
        title=title,
        edition="الطبعة الرسمية",
        author="وزارة التربية",
        page_count=0,
        is_demo=False,
    )
    db.add(book)
    db.flush()

    made = 0
    for page_number, body in extraction.pages:
        body = (body or "").strip()
        if not body:
            continue
        db.add(
            BookPage(
                book_id=book.id,
                page_number=page_number,
                heading=heading_from(body),
                text=body,
                is_demo=False,
            )
        )
        made += 1
    book.page_count = made
    db.flush()

    indexed = index_book(db, book)
    db.commit()
    return "OK ingested: %s subject=%s pages=%d chunks=%d" % (title, code, made, indexed)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default=None, help="ingest a single subject code")
    parser.add_argument("--status", action="store_true", help="print ingest status only")
    args = parser.parse_args()

    from app.db import Book, SessionLocal

    db = SessionLocal()
    try:
        if args.status:
            for book in db.query(Book).filter(Book.is_demo.is_(False)).all():
                print("REAL: %s" % book.title)
            return
        for pdf_name, code in BOOKS.items():
            if args.only and code != args.only:
                continue
            print(ingest(db, pdf_name, code))
    finally:
        db.close()


if __name__ == "__main__":
    main()
