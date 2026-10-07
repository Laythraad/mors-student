"""Content publication pipeline — spec §81/§83.

New curriculum content walks: Draft → AI Processing → Validation →
Admin Review → Published (or Rejected). Approving can park the draft as
`scheduled` until `publish_at`, at which point the background scheduler
publishes it automatically (§126 background jobs).

Publishing *materialises* the draft into the real curriculum tables, so
students see the new content through the existing read endpoints.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.orm import Session

from ..core.errors import NotFoundError, ValidationError
from ..db import (
    Book,
    Branch,
    Chapter,
    ContentDraft,
    Lesson,
    Source,
    Stage,
    Subject,
    Teacher,
    Unit,
    Video,
    Course,
    new_id,
    utcnow,
)

ENTITIES: tuple[str, ...] = (
    "subject",
    "chapter",
    "unit",
    "lesson",
    "source",
    "teacher",
    "video",
    "course",
)

REQUIRED: dict[str, tuple[str, ...]] = {
    "subject": ("branch_id", "code", "name_ar"),
    "chapter": ("book_id", "title"),
    "unit": ("chapter_id", "title"),
    "lesson": ("subject_id", "title"),
    "source": ("title",),
    "teacher": ("name",),
    "video": ("title", "url"),
    "course": ("title",),
}

_MODELS = {
    "subject": Subject,
    "chapter": Chapter,
    "unit": Unit,
    "lesson": Lesson,
    "source": Source,
    "teacher": Teacher,
    "video": Video,
    "course": Course,
}

_MODEL_BY_NAME = {
    "Branch": Branch,
    "Book": Book,
    "Chapter": Chapter,
    "Unit": Unit,
    "Lesson": Lesson,
    "Source": Source,
    "Subject": Subject,
    "Teacher": Teacher,
    "Video": Video,
    "Course": Course,
    "Stage": Stage,
}


def _naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _draft_title(entity: str, payload: dict[str, Any]) -> str:
    for key in ("title", "name_ar", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:255]
    return f"مسودة {entity}"


def out(draft: ContentDraft) -> dict[str, Any]:
    return {
        "id": draft.id,
        "entity": draft.entity,
        "title": draft.title,
        "status": draft.status,
        "payload": draft.payload or {},
        "ai_notes": draft.ai_notes or "",
        "issues": draft.issues or [],
        "publish_at": draft.publish_at.isoformat() if draft.publish_at else None,
        "created_by": draft.created_by,
        "reviewed_by": draft.reviewed_by,
        "review_note": draft.review_note or "",
        "entity_id": draft.entity_id,
        "published_at": draft.published_at.isoformat() if draft.published_at else None,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
    }


def _get(db: Session, draft_id: str) -> ContentDraft:
    draft = db.get(ContentDraft, draft_id)
    if draft is None:
        raise NotFoundError("المسودة غير موجودة.")
    return draft


# --------------------------------------------------------------------------- #
# creation / editing
# --------------------------------------------------------------------------- #
def create_draft(
    db: Session,
    *,
    entity: str,
    payload: dict[str, Any] | None = None,
    title: str | None = None,
    publish_at: datetime | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    if entity not in ENTITIES:
        raise ValidationError(
            "نوع المحتوى غير مدعوم.",
            details={"allowed": list(ENTITIES)},
        )
    payload = dict(payload or {})
    draft = ContentDraft(
        entity=entity,
        title=(title or _draft_title(entity, payload))[:255],
        payload=payload,
        status="draft",
        publish_at=_naive(publish_at),
        created_by=created_by,
    )
    db.add(draft)
    db.flush()
    return out(draft)


def update_draft(
    db: Session,
    draft_id: str,
    *,
    payload: dict[str, Any] | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    draft = _get(db, draft_id)
    if draft.status == "published":
        raise ValidationError("لا يمكن تعديل محتوى منشور.")
    if payload is not None:
        draft.payload = dict(payload)
        draft.issues = []
        draft.ai_notes = ""
        draft.status = "draft"
        if not title:
            draft.title = _draft_title(draft.entity, draft.payload)[:255]
    if title:
        draft.title = title.strip()[:255]
    db.flush()
    return out(draft)


def delete_draft(db: Session, draft_id: str) -> dict[str, Any]:
    draft = _get(db, draft_id)
    if draft.status == "published":
        raise ValidationError("لا يمكن حذف محتوى منشور.")
    db.delete(draft)
    db.flush()
    return {"id": draft_id, "deleted": True}


# --------------------------------------------------------------------------- #
# validation + AI processing (§83)
# --------------------------------------------------------------------------- #
def _validate(db: Session, entity: str, payload: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if entity not in REQUIRED:
        return [f"نوع المحتوى «{entity}» غير مدعوم."]

    for field in REQUIRED[entity]:
        value = payload.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            issues.append(f"الحقل «{field}» مطلوب.")
        elif isinstance(value, str) and len(value) > 500:
            issues.append(f"الحقل «{field}» أطول من المسموح.")

    def ref(model_name: str, key: str, label: str) -> None:
        value = payload.get(key)
        if value:
            model = _MODEL_BY_NAME[model_name]
            if db.get(model, value) is None:
                issues.append(f"{label} غير موجود.")

    checks = {
        "subject": [("Branch", "branch_id", "الفرع")],
        "chapter": [("Book", "book_id", "الكتاب")],
        "unit": [("Chapter", "chapter_id", "الفصل")],
        "lesson": [
            ("Subject", "subject_id", "المادة"),
            ("Unit", "unit_id", "الوحدة"),
            ("Chapter", "chapter_id", "الفصل"),
            ("Source", "source_id", "المصدر"),
        ],
        "source": [
            ("Book", "book_id", "الكتاب"),
            ("Chapter", "chapter_id", "الفصل"),
            ("Lesson", "lesson_id", "الدرس"),
        ],
        "teacher": [],
        "video": [
            ("Course", "course_id", "الكورس"),
            ("Teacher", "teacher_id", "المعلم"),
            ("Subject", "subject_id", "المادة"),
            ("Chapter", "chapter_id", "الفصل"),
            ("Lesson", "lesson_id", "الدرس"),
            ("Source", "source_id", "المصدر"),
        ],
        "course": [
            ("Teacher", "teacher_id", "المعلم"),
            ("Subject", "subject_id", "المادة"),
            ("Stage", "stage_id", "المرحلة"),
            ("Branch", "branch_id", "الفرع"),
        ],
    }
    for model_name, key, label in checks.get(entity, []):
        ref(model_name, key, label)

    if entity == "video" and isinstance(payload.get("url"), str):
        from .videos import youtube_id

        url = payload["url"].strip()
        if url and not any(url.startswith(p) for p in ("http://", "https://", "/")):
            issues.append("رابط الفيديو يجب أن يبدأ بـ http أو https.")
        elif url and url.startswith(("http://", "https://")) and not youtube_id(url):
            # §36: the in-app player only embeds YouTube officially; anything
            # else would ship a link that silently cannot play.
            issues.append(
                "رابط الفيديو ليس فيديو يوتيوب — المشغّل الداخلي يدعم روابط "
                "youtube.com/watch أو youtu.be فقط."
            )
    return issues


def _ai_notes(db: Session, draft: ContentDraft) -> str:
    """The AI Processing step: a short Arabic review of the proposed content."""
    snapshot = json.dumps(draft.payload or {}, ensure_ascii=False)[:1500]
    prompt = (
        "هذه مسودة محتوى منهجي جديد قبل نشره على المنصة.\n"
        f"النوع: {draft.entity}\nالعنوان: {draft.title}\nالحقول: {snapshot}\n"
        "أعطني ملاحظات مراجعة قصيرة بالعربية: نقاط قوة وخطة تحسين، دون اختراع معلومات."
    )
    try:
        from ..ai.orchestrator import AIRequest, ask

        answer = ask(
            db,
            AIRequest(task="curriculum", input=prompt, max_tokens=500, cache=True),
        )
        text = (answer.text or "").strip()
        if text:
            return text[:2000]
    except Exception:  # noqa: BLE001 — AI must never block the pipeline
        pass
    return (
        "تعذر استدعاء المساعد الذكي الآن — أُنجز التحقق الآلي من الحقول فقط. "
        "راجع المحتوى يدوياً قبل النشر."
    )


def process_draft(db: Session, draft_id: str) -> dict[str, Any]:
    """Run the AI Processing + Validation steps (§83)."""
    draft = _get(db, draft_id)
    if draft.status == "published":
        raise ValidationError("تم نشر هذه المسودة سابقاً.")
    if draft.status == "processing":
        raise ValidationError("المعالجة جارية بالفعل.")

    draft.status = "processing"
    draft.issues = []
    db.flush()

    draft.ai_notes = _ai_notes(db, draft)
    issues = _validate(db, draft.entity, draft.payload or {})
    draft.issues = issues
    draft.status = "rejected" if issues else "validated"
    db.flush()
    return out(draft)


# --------------------------------------------------------------------------- #
# admin review + publish (§83)
# --------------------------------------------------------------------------- #
def _materialise(db: Session, draft: ContentDraft) -> str:
    issues = _validate(db, draft.entity, draft.payload or {})
    if issues:
        draft.issues = issues
        draft.status = "rejected"
        db.flush()
        raise ValidationError("تعذر النشر — الحقول غير مكتملة.", details=issues)

    model = _MODELS[draft.entity]
    columns = set(model.__table__.columns.keys())
    kwargs = {k: v for k, v in (draft.payload or {}).items() if k in columns}
    # JSON payloads carry datetimes as ISO strings (e.g. teacher.verified_at).
    for key, value in list(kwargs.items()):
        column = model.__table__.columns[key]
        if isinstance(value, str) and value and isinstance(column.type, DateTime):
            try:
                kwargs[key] = _naive(datetime.fromisoformat(value))
            except ValueError as exc:
                raise ValidationError(f"قيمة تاريخ غير صالحة في الحقل «{key}».") from exc
    if draft.entity == "teacher" and not kwargs.get("slug"):
        kwargs["slug"] = f"teacher-{new_id()[:10]}"

    row = model(**kwargs)
    db.add(row)
    db.flush()

    draft.entity_id = row.id
    draft.status = "published"
    draft.published_at = utcnow()
    draft.review_note = draft.review_note or ""
    db.flush()
    return row.id


def publish_now(db: Session, draft: ContentDraft) -> str:
    if draft.status == "published":
        raise ValidationError("تم نشر هذه المسودة سابقاً.")
    return _materialise(db, draft)


def review_draft(
    db: Session,
    draft_id: str,
    *,
    approve: bool,
    note: str = "",
    publish_at: datetime | None = None,
    reviewer: str | None = None,
) -> dict[str, Any]:
    draft = _get(db, draft_id)
    if draft.status == "published":
        raise ValidationError("تم نشر هذه المسودة سابقاً.")
    draft.reviewed_by = reviewer
    draft.review_note = (note or "")[:400]

    if not approve:
        draft.status = "rejected"
        draft.publish_at = None
        draft.review_note = draft.review_note or "رفض من المراجعة."
        db.flush()
        return out(draft)

    if draft.status not in ("validated", "scheduled"):
        raise ValidationError("يجب إكمال المعالجة والتحقق قبل النشر.")

    target = _naive(publish_at) or draft.publish_at
    if target is not None and target > utcnow():
        draft.status = "scheduled"
        draft.publish_at = target
        db.flush()
        return out(draft)

    draft.publish_at = None
    _materialise(db, draft)
    return out(draft)


# --------------------------------------------------------------------------- #
# queries + scheduled publishing (used by the background scheduler)
# --------------------------------------------------------------------------- #
def list_drafts(
    db: Session,
    *,
    status: str | None = None,
    entity: str | None = None,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    query = db.query(ContentDraft)
    if status:
        query = query.filter(ContentDraft.status == status)
    if entity:
        query = query.filter(ContentDraft.entity == entity)
    if q:
        query = query.filter(ContentDraft.title.ilike(f"%{q}%"))
    total = query.count()
    rows = query.order_by(ContentDraft.created_at.desc()).offset(offset).limit(limit).all()
    return {"drafts": [out(d) for d in rows], "total": total, "offset": offset, "limit": limit}


def run_due_publications(db: Session, now: datetime | None = None) -> dict[str, Any]:
    """Publish every scheduled draft whose time has come (auto-publish job)."""
    moment = _naive(now) or utcnow()
    rows = (
        db.query(ContentDraft)
        .filter(
            ContentDraft.status == "scheduled",
            ContentDraft.publish_at.isnot(None),
            ContentDraft.publish_at <= moment,
        )
        .order_by(ContentDraft.publish_at)
        .all()
    )
    published: list[str] = []
    failed: list[dict[str, str]] = []
    for draft in rows:
        try:
            with db.begin_nested():
                _materialise(db, draft)
            published.append(draft.title)
        except Exception as exc:  # noqa: BLE001 — one bad draft must not stop the job
            failed.append({"id": draft.id, "title": draft.title, "error": str(exc)[:300]})
            draft.status = "rejected"
            draft.review_note = f"فشل النشر التلقائي: {str(exc)[:300]}"
            db.flush()
    return {"published": published, "failed": failed, "count": len(published)}


__all__ = [
    "ENTITIES",
    "REQUIRED",
    "create_draft",
    "update_draft",
    "delete_draft",
    "process_draft",
    "review_draft",
    "list_drafts",
    "publish_now",
    "run_due_publications",
    "out",
]
