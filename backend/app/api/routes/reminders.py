"""Reminders: create, edit, complete, snooze, delete."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ...core.deps import CurrentProfile, DbSession
from ...services import reminders as service

router = APIRouter(prefix="/reminders", tags=["reminders"])


class ReminderIn(BaseModel):
    title: str = Field(min_length=1, max_length=220)
    due_at: str
    note: str = Field(default="", max_length=500)


class ReminderPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=220)
    due_at: str | None = None
    note: str | None = Field(default=None, max_length=500)
    done: bool | None = None


class SnoozeIn(BaseModel):
    minutes: int = Field(default=30, ge=1, le=10080)


@router.get("")
def list_reminders(
    profile: CurrentProfile,
    db: DbSession,
    status: str | None = Query(default=None, max_length=20),
) -> dict[str, Any]:
    rows = service.list_reminders(db, profile.id, status=status)
    # a GET is where due reminders become inbox notifications — persist them
    db.commit()
    return {"reminders": rows}


@router.post("")
def create_reminder(payload: ReminderIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    row = service.create_reminder(
        db, profile.id, title=payload.title, due_at=payload.due_at, note=payload.note
    )
    db.commit()
    return row


@router.patch("/{reminder_id}")
def patch_reminder(
    reminder_id: str, payload: ReminderPatch, profile: CurrentProfile, db: DbSession
) -> dict[str, Any]:
    row = service.update_reminder(
        db, profile.id, reminder_id, payload.model_dump(exclude_unset=True)
    )
    db.commit()
    return row


@router.post("/{reminder_id}/snooze")
def snooze_reminder(
    reminder_id: str, payload: SnoozeIn, profile: CurrentProfile, db: DbSession
) -> dict[str, Any]:
    row = service.snooze_reminder(
        db, profile.id, reminder_id, minutes=payload.minutes
    )
    db.commit()
    return row


@router.delete("/{reminder_id}")
def delete_reminder(reminder_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    service.delete_reminder(db, profile.id, reminder_id)
    db.commit()
    return {"ok": True}
