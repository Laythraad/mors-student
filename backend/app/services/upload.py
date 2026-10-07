"""Uploads: save → extract (PDF/OCR/text) → chunk → embed → searchable.

Every stage records its own status so a student sees "جاري الفهرسة" instead of
a silent failure, and a broken OCR never loses the original file.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..core.errors import NotFoundError, ValidationError
from ..db import Upload, utcnow
from ..mors import EventType, bus
from ..rag import ingest_upload

SAFE_NAME = re.compile(r"[^\w.\- ؀-ۿ]+", re.U)


def _safe_filename(filename: str) -> str:
    name = Path(filename or "file").name
    name = SAFE_NAME.sub("_", name).strip("._") or "file"
    return name[:120]


def _extension(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def validate(filename: str, size: int) -> str:
    ext = _extension(filename)
    if ext not in settings.upload_types:
        raise ValidationError(
            f"نوع الملف غير مدعوم. الأنواع المسموحة: {', '.join(sorted(settings.upload_types))}."
        )
    if size <= 0:
        raise ValidationError("الملف فارغ.")
    if size > settings.max_upload_mb * 1024 * 1024:
        raise ValidationError(f"حجم الملف يتجاوز {settings.max_upload_mb} ميغابايت.")
    return ext


def save_upload(
    db: Session,
    *,
    student_id: str,
    uploader_id: str,
    filename: str,
    data: bytes,
    mime: str = "",
    subject_id: str | None = None,
    lesson_id: str | None = None,
    book_id: str | None = None,
    kind: str = "document",
    process: bool = True,
) -> dict[str, Any]:
    validate(filename, len(data))

    directory = Path(settings.upload_dir) / student_id
    directory.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}.{_extension(filename) or 'bin'}"
    path = directory / stored
    path.write_bytes(data)

    upload = Upload(
        student_id=student_id,
        uploader_id=uploader_id,
        kind=kind,
        filename=_safe_filename(filename),
        path=str(path),
        mime=mime,
        size=len(data),
        status="received",
        subject_id=subject_id,
        lesson_id=lesson_id,
        book_id=book_id,
    )
    db.add(upload)
    db.flush()

    if process:
        _process(db, upload)
    return payload(upload)


def _process(db: Session, upload: Upload) -> None:
    upload.status = "processing"
    db.flush()
    try:
        ingest_upload(db, upload)
        upload.status = "indexed"
        upload.error = ""
        upload.meta = {**(upload.meta or {}), "chunks": _chunk_count(db, upload)}
        db.flush()
        bus.emit(
            db,
            upload.student_id,
            EventType.UPLOAD_INDEXED,
            {
                "upload_id": upload.id,
                "filename": upload.filename,
                "subject_id": upload.subject_id,
                "lesson_id": upload.lesson_id,
            },
        )
    except Exception as exc:  # noqa: BLE001 - keep the file, report the failure
        upload.status = "failed"
        upload.error = str(exc)[:300]
        db.flush()


def _chunk_count(db: Session, upload: Upload) -> int:
    from ..db import AIChunk

    return db.query(AIChunk).filter(AIChunk.upload_id == upload.id).count()


def reindex(db: Session, student_id: str, upload_id: str) -> dict[str, Any]:
    upload = _owned(db, student_id, upload_id)
    if not Path(upload.path).exists():
        raise NotFoundError("ملف الرفع لم يعد موجوداً على القرص.")
    _process(db, upload)
    return payload(upload)


def delete_upload(db: Session, student_id: str, upload_id: str) -> bool:
    upload = _owned(db, student_id, upload_id)
    from ..db import AIChunk

    db.query(AIChunk).filter(AIChunk.upload_id == upload.id).delete(synchronize_session=False)
    path = Path(upload.path)
    db.delete(upload)
    db.flush()
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
    return True


def _owned(db: Session, student_id: str, upload_id: str) -> Upload:
    row = db.get(Upload, upload_id)
    if row is None or row.student_id != student_id:
        raise NotFoundError("الملف غير موجود.")
    return row


def get_upload(db: Session, student_id: str, upload_id: str) -> dict[str, Any]:
    return payload(_owned(db, student_id, upload_id), with_text=True)


def list_uploads(
    db: Session, student_id: str, *, status: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    q = db.query(Upload).filter(Upload.student_id == student_id)
    if status:
        q = q.filter(Upload.status == status)
    rows = q.order_by(Upload.created_at.desc()).limit(limit).all()
    return [payload(r) for r in rows]


def payload(upload: Upload, *, with_text: bool = False) -> dict[str, Any]:
    data = {
        "id": upload.id,
        "filename": upload.filename,
        "kind": upload.kind,
        "mime": upload.mime,
        "size": upload.size,
        "status": upload.status,
        "error": upload.error,
        "subject_id": upload.subject_id,
        "lesson_id": upload.lesson_id,
        "book_id": upload.book_id,
        "ocr_engine": upload.ocr_engine,
        "meta": upload.meta or {},
        "created_at": upload.created_at.isoformat() if upload.created_at else None,
    }
    if with_text:
        data["extracted_text"] = upload.extracted_text or ""
    return data


def read_file(upload: Upload) -> bytes:
    path = Path(upload.path)
    if not path.exists():
        raise NotFoundError("الملف غير موجود.")
    return path.read_bytes()


__all__ = [
    "validate",
    "save_upload",
    "reindex",
    "delete_upload",
    "get_upload",
    "list_uploads",
    "payload",
    "read_file",
]
