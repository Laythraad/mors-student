"""Event bus — one event, many independent handlers.

`emit()` is synchronous and transaction-safe: handlers receive the same
session, and failures are collected rather than aborting the whole fan-out
(one broken notification must never roll back a completed study session).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from .events import PERSISTED_EVENTS, EventType
from .models_helper import persist_event

logger = logging.getLogger(__name__)

Handler = Callable[[Session, str, dict[str, Any]], dict[str, Any] | None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[tuple[str, Handler]]] = defaultdict(list)

    def on(self, event: EventType | str, name: str = "") -> Callable[[Handler], Handler]:
        key = str(event)

        def decorator(func: Handler) -> Handler:
            self._handlers[key].append((name or func.__name__, func))
            return func

        return decorator

    def handlers_for(self, event: EventType | str) -> list[tuple[str, Handler]]:
        return list(self._handlers.get(str(event), []))

    def emit(
        self,
        db: Session,
        student_id: str,
        event: EventType | str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = dict(payload or {})
        key = str(event)
        results: dict[str, Any] = {}
        errors: dict[str, str] = {}

        for name, handler in self._handlers.get(key, []):
            try:
                outcome = handler(db, student_id, data)
                if outcome:
                    results[name] = outcome
            except Exception as exc:  # noqa: BLE001 - fan-out must not abort
                logger.exception("handler %s failed for %s", name, key)
                errors[name] = str(exc)

        try:
            persist_event(db, student_id, key, data, results)
        except Exception:  # noqa: BLE001
            logger.exception("failed persisting event %s", key)
            errors["persist"] = "persist_failed"

        db.commit()
        return {"event": key, "results": results, "errors": errors}


bus = EventBus()

__all__ = ["EventBus", "bus", "Handler"]
