"""Small persistence helpers used by the Mors engine and the event bus.

Kept separate from `services/` so `mors/` never imports the service layer at
module import time (which would create a cycle).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..db import AIEvent, MorsEvent, MorsMessage, MorsState, utcnow
from .engine import MorsReaction, PersonalityContext, react
from .events import PERSISTED_EVENTS
from .states import MorsState as State


def current_state(db: Session, student_id: str | None) -> MorsState | None:
    q = db.query(MorsState)
    if student_id:
        q = q.filter(MorsState.student_id == student_id)
    return q.order_by(MorsState.changed_at.desc()).first()


def record_state(
    db: Session,
    student_id: str | None,
    reaction: MorsReaction,
    *,
    event: str = "",
    reason: str = "",
) -> MorsState:
    previous = current_state(db, student_id)
    row = MorsState(
        student_id=student_id,
        current_expression=reaction.expression,
        previous_expression=previous.current_expression if previous else None,
        state=reaction.state.value,
        event=event,
        reason=reason or reaction.scenario,
        message=reaction.message,
        priority=reaction.priority,
        animation=reaction.animation,
    )
    db.add(row)
    db.flush()
    return row


def queue_message(
    db: Session,
    student_id: str,
    reaction: MorsReaction,
    *,
    context: str = "",
    category: str = "",
    suppress: bool = False,
) -> MorsMessage | None:
    if suppress or not reaction.message:
        return None
    row = MorsMessage(
        student_id=student_id,
        expression=reaction.expression,
        tone=reaction.tone,
        text=reaction.message,
        context=context or reaction.scenario,
        priority=reaction.priority,
        category=category or reaction.category,
        expires_at=utcnow() + timedelta(days=2),
    )
    db.add(row)
    db.flush()
    return row


def react_and_persist(
    db: Session,
    student_id: str,
    ctx: PersonalityContext,
    *,
    seed: str = "",
    deliver: bool = True,
    reason: str = "",
) -> MorsReaction:
    reaction = react(ctx, seed=seed)
    record_state(db, student_id, reaction, event=ctx.event, reason=reason)
    if deliver:
        queue_message(db, student_id, reaction, suppress=reaction.suppressed)
    return reaction


def persist_event(
    db: Session,
    student_id: str,
    event: str,
    payload: dict[str, Any],
    outcome: dict[str, Any],
) -> None:
    db.add(
        MorsEvent(
            student_id=student_id or None,
            type=event,
            payload=payload,
            outcome=outcome,
        )
    )
    if event in {str(e) for e in PERSISTED_EVENTS}:
        db.add(
            AIEvent(
                student_id=student_id or None,
                type=event,
                payload=payload,
                handled=list(outcome.keys()),
                source="bus",
            )
        )


__all__ = [
    "current_state",
    "record_state",
    "queue_message",
    "react_and_persist",
    "persist_event",
    "State",
]
