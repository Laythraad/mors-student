"""Publishing workflow models (spec §83) and background job runs (§126)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin, utcnow


class ContentDraft(Base, IdMixin, TimestampMixin):
    """A piece of new curriculum content awaiting the §83 approval pipeline:

    draft → processing (AI) → validated → review → published / rejected,
    optionally parked as `scheduled` until `publish_at` (auto-publish job).
    """

    __tablename__ = "content_drafts"

    entity: Mapped[str] = mapped_column(String(20), index=True)
    # subject | chapter | unit | lesson | source | teacher | video | course
    title: Mapped[str] = mapped_column(String(255), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    # draft | processing | validated | scheduled | published | rejected
    ai_notes: Mapped[str] = mapped_column(Text, default="")
    issues: Mapped[list] = mapped_column(JSON, default=list)
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    review_note: Mapped[str] = mapped_column(String(400), default="")
    entity_id: Mapped[str | None] = mapped_column(String(32), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class SchedulerRun(Base, IdMixin):
    """One background-job execution — durable so schedules survive restarts."""

    __tablename__ = "scheduler_runs"

    job: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | error
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")


__all__ = ["ContentDraft", "SchedulerRun"]
