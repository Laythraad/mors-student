"""Notifications and Mors' own feed.

Notifications are an inbox (opt-in, grouped, never urgent-by-default); Mors'
messages are dialogue. Focus Mode only changes *immediacy*, never whether an
event was recorded — so nothing is silently dropped.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.errors import NotFoundError
from ..db import (
    MorsMessage,
    MorsState,
    Notification,
    StudentSettings,
    utcnow,
)
from ..mors import MorsState as State, sprite_for, spec


# --------------------------------------------------------------------------- #
# notifications
# --------------------------------------------------------------------------- #
def list_notifications(
    db: Session,
    student_id: str,
    *,
    unread_only: bool = False,
    kinds: list[str] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    q = db.query(Notification).filter(Notification.student_id == student_id)
    if unread_only:
        q = q.filter(Notification.read_at.is_(None))
    if kinds:
        q = q.filter(Notification.kind.in_(kinds))
    rows = q.order_by(Notification.created_at.desc()).limit(limit).all()
    return [_payload(r) for r in rows]


def unread_count(db: Session, student_id: str) -> int:
    return (
        db.query(func.count(Notification.id))
        .filter(Notification.student_id == student_id, Notification.read_at.is_(None))
        .scalar()
        or 0
    )


def mark_read(
    db: Session,
    student_id: str,
    *,
    notification_id: str | None = None,
    all: bool = False,
) -> int:
    q = db.query(Notification).filter(
        Notification.student_id == student_id, Notification.read_at.is_(None)
    )
    if not all:
        if not notification_id:
            raise NotFoundError("حدد الإشعار أو استخدم الكل.")
        q = q.filter(Notification.id == notification_id)
    count = q.update({Notification.read_at: utcnow()}, synchronize_session=False)
    db.flush()
    return int(count or 0)


def clear_read(db: Session, student_id: str) -> int:
    count = (
        db.query(Notification)
        .filter(Notification.student_id == student_id, Notification.read_at.isnot(None))
        .delete(synchronize_session=False)
    )
    db.flush()
    return int(count or 0)


def _payload(row: Notification) -> dict[str, Any]:
    meta = row.meta or {}
    return {
        "id": row.id,
        "kind": row.kind,
        "title": row.title,
        "body": row.body,
        "link": row.link,
        "read": row.read_at is not None,
        "deferred": bool(meta.get("deferred")),
        "event": meta.get("event", ""),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# --------------------------------------------------------------------------- #
# mors feed
# --------------------------------------------------------------------------- #
def mors_state(db: Session, student_id: str) -> dict[str, Any]:
    row = (
        db.query(MorsState)
        .filter(MorsState.student_id == student_id)
        .order_by(MorsState.changed_at.desc())
        .first()
    )
    if row is None:
        reaction = spec(State.IDLE)
        return {
            "state": State.IDLE.value,
            "expression": reaction.sprite,
            "sprite": f"/mors/{reaction.sprite}.png",
            "message": "",
            "priority": reaction.priority,
            "animation": reaction.animation,
            "changed_at": None,
        }
    return {
        "state": row.state,
        "expression": row.current_expression,
        "sprite": f"/mors/{row.current_expression}.png",
        "message": row.message,
        "event": row.event,
        "reason": row.reason,
        "priority": row.priority,
        "animation": row.animation,
        "previous_expression": row.previous_expression,
        "changed_at": row.changed_at.isoformat() if row.changed_at else None,
    }


def pending_messages(db: Session, student_id: str, *, limit: int = 6) -> list[dict[str, Any]]:
    rows = (
        db.query(MorsMessage)
        .filter(
            MorsMessage.student_id == student_id,
            MorsMessage.delivered.is_(False),
            MorsMessage.dismissed.is_(False),
        )
        .order_by(MorsMessage.priority.asc(), MorsMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "expression": r.expression,
            "sprite": f"/mors/{r.expression}.png",
            "text": r.text,
            "tone": r.tone,
            "category": r.category,
            "context": r.context,
            "priority": r.priority,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def mark_delivered(db: Session, student_id: str, ids: list[str]) -> int:
    if not ids:
        return 0
    count = (
        db.query(MorsMessage)
        .filter(
            MorsMessage.student_id == student_id,
            MorsMessage.id.in_(ids),
            MorsMessage.delivered.is_(False),
        )
        .update({MorsMessage.delivered: True}, synchronize_session=False)
    )
    db.flush()
    return int(count or 0)


def dismiss(db: Session, student_id: str, message_id: str) -> bool:
    row = db.get(MorsMessage, message_id)
    if row is None or row.student_id != student_id:
        return False
    row.dismissed = True
    row.delivered = True
    db.flush()
    return True


def history(db: Session, student_id: str, *, limit: int = 40) -> list[dict[str, Any]]:
    rows = (
        db.query(MorsMessage)
        .filter(MorsMessage.student_id == student_id)
        .order_by(MorsMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "text": r.text,
            "expression": r.expression,
            "tone": r.tone,
            "category": r.category,
            "read": r.delivered,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


# --------------------------------------------------------------------------- #
# delivery rules
# --------------------------------------------------------------------------- #
def focus_mode(db: Session, student_id: str) -> bool:
    from ..db import StudentProfile

    profile = db.get(StudentProfile, student_id)
    if profile is None:
        return False
    row = db.query(StudentSettings).filter(StudentSettings.user_id == profile.user_id).first()
    return bool(row and row.focus_mode)


def quiet_hours(db: Session, student_id: str) -> tuple[int, int]:
    """Respect the student's own sleep window before any nudge."""
    from ..db import StudentProfile

    profile = db.get(StudentProfile, student_id)
    if profile is None or profile.sleep_start is None or profile.sleep_end is None:
        return (23, 7)
    return (profile.sleep_start.hour, profile.sleep_end.hour)


def is_quiet(db: Session, student_id: str) -> bool:
    hour = utcnow().hour
    start, end = quiet_hours(db, student_id)
    if start > end:  # window crosses midnight
        return hour >= start or hour < end
    return start <= hour < end


#: only these count against the nudge cooldown — a streak celebration must
#: never suppress the daily brief
NUDGE_KINDS = ("coach", "nudge", "reminder")


def should_nudge(db: Session, student_id: str, *, cooldown_minutes: int = 45) -> bool:
    if focus_mode(db, student_id) or is_quiet(db, student_id):
        return False
    recent = (
        db.query(Notification)
        .filter(Notification.student_id == student_id, Notification.kind.in_(NUDGE_KINDS))
        .order_by(Notification.created_at.desc())
        .first()
    )
    if recent is None or recent.created_at is None:
        return True
    created = recent.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=utcnow().tzinfo)
    return utcnow() - created >= timedelta(minutes=cooldown_minutes)


__all__ = [
    "list_notifications",
    "unread_count",
    "mark_read",
    "clear_read",
    "mors_state",
    "pending_messages",
    "mark_delivered",
    "dismiss",
    "history",
    "focus_mode",
    "quiet_hours",
    "is_quiet",
    "should_nudge",
    "sprite_for",
]
