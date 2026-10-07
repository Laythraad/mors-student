"""Notification inbox and Mors' own feed."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ...core.deps import CurrentProfile, DbSession
from ...core.errors import NotFoundError
from ...services import notifications as service

router = APIRouter(prefix="/inbox", tags=["inbox"])


class MarkReadIn(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=100)
    all: bool = False


class DeliveredIn(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=50)


@router.get("/notifications")
def notifications(
    profile: CurrentProfile,
    db: DbSession,
    unread: bool = False,
    kind: str | None = None,
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    return {
        "notifications": service.list_notifications(
            db,
            profile.id,
            unread_only=unread,
            kinds=[kind] if kind else None,
            limit=limit,
        ),
        "unread": service.unread_count(db, profile.id),
    }


@router.post("/notifications/read")
def mark_read(payload: MarkReadIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    if payload.all:
        count = service.mark_read(db, profile.id, all=True)
    elif payload.ids:
        count = 0
        for notification_id in payload.ids:
            count += service.mark_read(db, profile.id, notification_id=notification_id)
    else:
        count = service.mark_read(db, profile.id, all=True)
    db.commit()
    return {"updated": count, "unread": service.unread_count(db, profile.id)}


@router.delete("/notifications/read")
def clear_read(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    removed = service.clear_read(db, profile.id)
    db.commit()
    return {"removed": removed}


@router.get("/mors/state")
def mors_state(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return service.mors_state(db, profile.id)


@router.get("/mors/messages")
def mors_messages(profile: CurrentProfile, db: DbSession, limit: int = Query(6, ge=1, le=20)) -> dict[str, Any]:
    return {"messages": service.pending_messages(db, profile.id, limit=limit)}


@router.post("/mors/delivered")
def delivered(payload: DeliveredIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    count = service.mark_delivered(db, profile.id, payload.ids)
    db.commit()
    return {"delivered": count}


@router.post("/mors/messages/{message_id}/dismiss")
def dismiss(message_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    if not service.dismiss(db, profile.id, message_id):
        raise NotFoundError("الرسالة غير موجودة.")
    db.commit()
    return {"ok": True}


@router.get("/mors/history")
def mors_history(profile: CurrentProfile, db: DbSession, limit: int = Query(40, ge=1, le=100)) -> dict[str, Any]:
    return {"messages": service.history(db, profile.id, limit=limit)}


@router.get("/delivery-policy")
def delivery_policy(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return {
        "focus_mode": service.focus_mode(db, profile.id),
        "quiet": service.is_quiet(db, profile.id),
        "quiet_hours": list(service.quiet_hours(db, profile.id)),
        "can_nudge": service.should_nudge(db, profile.id),
    }


__all__ = ["router"]
