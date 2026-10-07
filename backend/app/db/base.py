"""Declarative base, shared column helpers and generic mixins."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    """Current UTC time as a *naive* datetime.

    SQLite stores `DateTime(timezone=True)` values without the offset, so every
    value read back from the database is naive. Keeping "now" naive as well
    means Python-side arithmetic never mixes offset-aware and offset-naive
    datetimes (the classic `TypeError: can't subtract offset-naive and
    offset-aware datetimes`).
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class IdMixin:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)


__all__ = ["Base", "TimestampMixin", "IdMixin", "new_id", "utcnow"]
