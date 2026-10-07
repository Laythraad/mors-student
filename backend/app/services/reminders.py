"""Student reminders — full CRUD + snooze.

Reminders ride on the shared `calendar_events` table (kind="custom"), which the
plan calendar already renders, so a reminder shows up in the timetable the
moment it is created. Times are stored as naive UTC (the project convention):
the browser converts its `datetime-local` input to UTC on the way in, and the
API marks every `due_at` with a `Z` so the browser can render it back in the
student's own timezone.

Status is derived, never stored: done > due > snoozed > pending.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..core.errors import NotFoundError, ValidationError
from ..db import CalendarEvent, Notification, utcnow

MAX_SNOOZE_MINUTES = 7 * 24 * 60


def parse_due(value: str | datetime | None) -> datetime:
    """Accept an ISO string (naive or tz-aware) and return naive UTC."""
    if isinstance(value, datetime):
        dt = value
    else:
        text = (value or "").strip()
        if not text:
            raise ValidationError("حدد وقت التذكير.")
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValidationError("وقت التذكير غير صالح.") from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.replace(microsecond=0)


def _owned(db: Session, student_id: str, reminder_id: str) -> CalendarEvent:
    row = db.get(CalendarEvent, reminder_id)
    # planner/advisor entries (task_id, exam_id, meta.source) are not student
    # reminders — only rows this service created are editable here
    if (
        row is None
        or row.student_id != student_id
        or row.kind != "custom"
        or row.task_id
        or row.exam_id
        or not _meta(row).get("is_reminder")
    ):
        raise NotFoundError("التذكير غير موجود.")
    return row


def _meta(row: CalendarEvent) -> dict[str, Any]:
    return row.meta if isinstance(row.meta, dict) else {}


def status_of(row: CalendarEvent, now: datetime | None = None) -> str:
    now = now or utcnow()
    meta = _meta(row)
    if meta.get("done"):
        return "done"
    if row.start_at and row.start_at <= now:
        return "due"
    if meta.get("snoozed_until"):
        return "snoozed"
    return "pending"


def payload(row: CalendarEvent, now: datetime | None = None) -> dict[str, Any]:
    meta = _meta(row)
    return {
        "id": row.id,
        "title": row.title,
        # Z = UTC, so `new Date(...)` renders the right wall-clock anywhere
        "due_at": f"{row.start_at.isoformat()}Z" if row.start_at else None,
        "note": str(meta.get("note") or ""),
        "status": status_of(row, now),
        "done": bool(meta.get("done")),
        "snooze_count": int(meta.get("snooze_count") or 0),
        "created_at": f"{row.created_at.isoformat()}Z" if row.created_at else None,
    }


def _rows(db: Session, student_id: str) -> list[CalendarEvent]:
    rows = (
        db.query(CalendarEvent)
        .filter(
            CalendarEvent.student_id == student_id,
            CalendarEvent.kind == "custom",
            CalendarEvent.task_id.is_(None),
            CalendarEvent.exam_id.is_(None),
        )
        .order_by(CalendarEvent.start_at)
        .all()
    )
    # the advisor also writes kind="custom" slots — those are not reminders
    return [r for r in rows if _meta(r).get("is_reminder")]


def notify_due(db: Session, student_id: str, rows: list[CalendarEvent]) -> int:
    """Turn newly due reminders into inbox notifications, once each."""
    now = utcnow()
    created = 0
    for row in rows:
        meta = _meta(row)
        if meta.get("done") or meta.get("notified"):
            continue
        if not row.start_at or row.start_at > now:
            continue
        db.add(
            Notification(
                student_id=student_id,
                kind="study_reminder",
                title=f"تذكير: {row.title}",
                body=str(meta.get("note") or "حان وقت التذكير."),
                link="/plan",
                meta={"event": "reminder_due", "reminder_id": row.id},
            )
        )
        meta = dict(meta)
        meta["notified"] = True
        row.meta = meta
        created += 1
    if created:
        db.flush()
    return created


def list_reminders(
    db: Session, student_id: str, *, status: str | None = None, notify: bool = True
) -> list[dict[str, Any]]:
    rows = _rows(db, student_id)
    if notify:
        notify_due(db, student_id, rows)
    now = utcnow()
    out = [payload(r, now) for r in rows]
    if status:
        out = [r for r in out if r["status"] == status]
    return out


def create_reminder(
    db: Session, student_id: str, *, title: str, due_at: str, note: str = ""
) -> dict[str, Any]:
    clean = (title or "").strip()
    if not clean:
        raise ValidationError("اكتب عنوان التذكير.")
    row = CalendarEvent(
        student_id=student_id,
        kind="custom",
        title=clean[:220],
        start_at=parse_due(due_at),
        color="#f59f00",
        meta={"note": (note or "").strip()[:500], "done": False, "is_reminder": True},
    )
    db.add(row)
    db.flush()
    return payload(row)


def update_reminder(
    db: Session,
    student_id: str,
    reminder_id: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    row = _owned(db, student_id, reminder_id)
    if fields.get("title") is not None:
        clean = str(fields["title"]).strip()
        if not clean:
            raise ValidationError("اكتب عنوان التذكير.")
        row.title = clean[:220]
    if fields.get("due_at") is not None:
        row.start_at = parse_due(fields["due_at"])
    meta = dict(_meta(row))
    if fields.get("note") is not None:
        meta["note"] = str(fields["note"]).strip()[:500]
    if fields.get("done") is not None:
        meta["done"] = bool(fields["done"])
        if meta["done"]:
            # a finished reminder keeps its time but stops nagging
            meta["notified"] = True
    row.meta = meta
    db.flush()
    return payload(row)


def delete_reminder(db: Session, student_id: str, reminder_id: str) -> bool:
    row = _owned(db, student_id, reminder_id)
    db.delete(row)
    db.flush()
    return True


def snooze_reminder(
    db: Session, student_id: str, reminder_id: str, *, minutes: int = 30
) -> dict[str, Any]:
    if minutes < 1 or minutes > MAX_SNOOZE_MINUTES:
        raise ValidationError("مدة التأجيل بين دقيقة وأسبوع.")
    row = _owned(db, student_id, reminder_id)
    now = utcnow()
    base = row.start_at if row.start_at and row.start_at > now else now
    new_due = (base + timedelta(minutes=minutes)).replace(microsecond=0)
    meta = dict(_meta(row))
    meta["done"] = False
    meta["snoozed_until"] = f"{new_due.isoformat()}Z"
    meta["snooze_count"] = int(meta.get("snooze_count") or 0) + 1
    # it is a new moment: let it raise a notification again when it comes round
    meta["notified"] = False
    row.meta = meta
    row.start_at = new_due
    db.flush()
    return payload(row)


__all__ = [
    "create_reminder",
    "delete_reminder",
    "list_reminders",
    "notify_due",
    "parse_due",
    "payload",
    "snooze_reminder",
    "status_of",
    "update_reminder",
]
