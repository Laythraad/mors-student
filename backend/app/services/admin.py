"""Admin / CMS service layer.

Students never reach these functions — the API guards them behind
``role == "admin"``. The prompt registry is the only runtime-editable part of
the AI layer, which is exactly why it needs an audit trail.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..config import settings
from ..core.errors import ConflictError, NotFoundError, ValidationError
from ..db import (
    AIEvent,
    AIPrompt,
    AIUsage,
    AppSetting,
    Book,
    Chapter,
    Lesson,
    Stage,
    Subject,
    Unit,
    Upload,
    User,
    utcnow,
)
from ..ai import PROMPT_MAP


def list_prompts(db: Session) -> list[dict[str, Any]]:
    rows = db.query(AIPrompt).order_by(AIPrompt.key).all()
    by_key = {r.key: r for r in rows}
    out: list[dict[str, Any]] = []
    for key, spec in PROMPT_MAP.items():
        row = by_key.get(key)
        out.append(
            {
                "key": key,
                "name": row.name if row else spec.name,
                "name_ar": spec.name_ar,
                "description": row.description if row else "",
                "template": row.template if row else spec.system + "\n\n" + spec.user,
                "model_tier": row.model_tier if row else spec.tier,
                "version": row.version if row else 1,
                "is_active": row.is_active if row else True,
                "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
                "overridden": row is not None and row.version > 1,
            }
        )
    return out


def update_prompt(
    db: Session,
    key: str,
    *,
    template: str,
    updated_by: str | None = None,
    model_tier: str | None = None,
) -> dict[str, Any]:
    if key not in PROMPT_MAP:
        raise NotFoundError("البرومبت غير موجود.")
    template = (template or "").strip()
    if len(template) < 40:
        raise ValidationError("البرومبت قصير جداً.")
    for placeholder in ("{input}",):
        if placeholder not in template:
            raise ValidationError(f"البرومبت لازم يحتوي على {placeholder}.")

    row = db.query(AIPrompt).filter(AIPrompt.key == key).first()
    if row is None:
        row = AIPrompt(key=key, name=PROMPT_MAP[key].name, template=template, version=2)
        if model_tier:
            row.model_tier = model_tier
        row.updated_by = updated_by
        db.add(row)
    else:
        row.template = template
        row.version = (row.version or 1) + 1
        row.updated_by = updated_by
        if model_tier:
            row.model_tier = model_tier
    db.flush()
    return {
        "key": row.key,
        "version": row.version,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def reset_prompt(db: Session, key: str) -> dict[str, Any]:
    row = db.query(AIPrompt).filter(AIPrompt.key == key).first()
    if row is None:
        raise NotFoundError("لا يوجد تعديل محفوظ لهذا البرومبت.")
    db.delete(row)
    db.flush()
    return {"key": key, "reset": True}


def curriculum_stats(db: Session) -> dict[str, Any]:
    counts = {
        "stages": db.query(func.count(Stage.id)).scalar() or 0,
        "subjects": db.query(func.count(Subject.id)).scalar() or 0,
        "books": db.query(func.count(Book.id)).scalar() or 0,
        "chapters": db.query(func.count(Chapter.id)).scalar() or 0,
        "units": db.query(func.count(Unit.id)).scalar() or 0,
        "lessons": db.query(func.count(Lesson.id)).scalar() or 0,
        "users": db.query(func.count(User.id)).scalar() or 0,
        "chunks": _count(db, "AIChunk"),
        "uploads": db.query(func.count(Upload.id)).scalar() or 0,
    }
    empty_units = [
        u.id
        for u in db.query(Unit).limit(400).all()
        if not u.lessons
    ]
    counts["empty_units"] = len(empty_units)
    return counts


def _count(db: Session, model_name: str) -> int:
    from ..db import AIChunk

    if model_name == "AIChunk":
        return db.query(func.count(AIChunk.id)).scalar() or 0
    return 0


def ai_usage(db: Session, *, days: int = 7) -> dict[str, Any]:
    since = (utcnow() - timedelta(days=days)).date().isoformat()
    rows = (
        db.query(
            AIUsage.day,
            AIUsage.task,
            func.sum(AIUsage.prompt_tokens),
            func.sum(AIUsage.completion_tokens),
            func.count(AIUsage.id),
        )
        .filter(AIUsage.day >= since)
        .group_by(AIUsage.day, AIUsage.task)
        .all()
    )
    by_day: dict[str, dict[str, Any]] = {}
    total_prompt = total_completion = requests = 0
    for day, task, prompt, completion, count in rows:
        bucket = by_day.setdefault(day, {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "tasks": {}})
        bucket["requests"] += count
        bucket["prompt_tokens"] += int(prompt or 0)
        bucket["completion_tokens"] += int(completion or 0)
        bucket["tasks"][task] = bucket["tasks"].get(task, 0) + count
        requests += count
        total_prompt += int(prompt or 0)
        total_completion += int(completion or 0)
    return {
        "days": days,
        "requests": requests,
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
        "budget": settings.ai_daily_token_budget,
        "by_day": by_day,
        "provider": settings.ai_provider,
    }


def recent_events(db: Session, *, limit: int = 50, event_type: str | None = None) -> list[dict[str, Any]]:
    q = db.query(AIEvent)
    if event_type:
        q = q.filter(AIEvent.type == event_type)
    rows = q.order_by(AIEvent.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "type": r.type,
            "student_id": r.student_id,
            "source": r.source,
            "handled": r.handled or [],
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def get_setting(db: Session, key: str, default: Any = None) -> Any:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row is None:
        return default
    value = row.value
    if isinstance(value, dict) and set(value.keys()) == {"value"}:
        return value["value"]
    return value


def set_setting(db: Session, key: str, value: Any, *, description: str = "") -> Any:
    if not key or len(key) > 80:
        raise ValidationError("مفتاح الإعداد غير صالح.")
    stored = value if isinstance(value, dict) else {"value": value}
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row is None:
        row = AppSetting(key=key, value=stored, description=description)
        db.add(row)
    else:
        row.value = stored
        if description:
            row.description = description
    db.flush()
    return get_setting(db, key)


def list_users(db: Session, *, query: str = "", limit: int = 50) -> list[dict[str, Any]]:
    q = db.query(User)
    if query:
        like = f"%{query.strip()}%"
        q = q.filter(or_(User.full_name.like(like), User.email.like(like)))
    rows = q.order_by(User.created_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "full_name": r.full_name,
            "email": r.email,
            "phone": r.phone,
            "role": r.role,
            "is_active": r.is_active,
            "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def set_user_active(db: Session, user_id: str, active: bool) -> dict[str, Any]:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("المستخدم غير موجود.")
    if user.role == "admin" and not active:
        raise ConflictError("لا يمكن تعطيل حساب مدير.")
    user.is_active = active
    db.flush()
    return {"id": user.id, "is_active": user.is_active}


__all__ = [
    "list_prompts",
    "update_prompt",
    "reset_prompt",
    "curriculum_stats",
    "ai_usage",
    "recent_events",
    "get_setting",
    "set_setting",
    "list_users",
    "set_user_active",
]
