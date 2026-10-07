"""AI runtime, Mors character, notifications, achievements and search tables."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin, utcnow


# --------------------------------------------------------------------------- #
# AI
# --------------------------------------------------------------------------- #
class AIConversation(Base, IdMixin, TimestampMixin):
    __tablename__ = "ai_conversations"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(220), default="")
    agent: Mapped[str] = mapped_column(String(30), default="tutor")
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    messages: Mapped[list[AIMessage]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="AIMessage.created_at"
    )


class AIMessage(Base, IdMixin, TimestampMixin):
    __tablename__ = "ai_messages"

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("ai_conversations.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), default="user")  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, default="")
    agent: Mapped[str] = mapped_column(String(30), default="tutor")
    model: Mapped[str] = mapped_column(String(80), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float)
    state: Mapped[str] = mapped_column(String(24), default="")
    structured: Mapped[dict] = mapped_column(JSON, default=dict)

    conversation: Mapped[AIConversation] = relationship(back_populates="messages")


class AIEvent(Base, IdMixin, TimestampMixin):
    __tablename__ = "ai_events"

    student_id: Mapped[str | None] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    handled: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(30), default="system")


class AIUsage(Base, IdMixin, TimestampMixin):
    __tablename__ = "ai_usage"

    student_id: Mapped[str | None] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    agent: Mapped[str] = mapped_column(String(30), default="")
    model: Mapped[str] = mapped_column(String(80), default="")
    task: Mapped[str] = mapped_column(String(60), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    day: Mapped[str] = mapped_column(String(10), default="", index=True)


class AIPrompt(Base, IdMixin, TimestampMixin):
    """Admin-editable prompt templates. Students can never touch these."""

    __tablename__ = "ai_prompts"
    __table_args__ = (UniqueConstraint("key", "version", name="uq_prompt_key_version"),)

    key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(400), default="")
    template: Mapped[str] = mapped_column(Text, nullable=False)
    model_tier: Mapped[str] = mapped_column(String(20), default="primary")
    # fast | primary | reasoning | vision
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    updated_by: Mapped[str | None] = mapped_column(String(32))
    system_preamble: Mapped[str] = mapped_column(Text, default="")


class AIChunk(Base, IdMixin, TimestampMixin):
    """Retrievable text unit. This *is* the vector index (embedding stored as JSON)."""

    __tablename__ = "ai_chunks"

    upload_id: Mapped[str | None] = mapped_column(ForeignKey("uploads.id"), index=True)
    book_id: Mapped[str | None] = mapped_column(ForeignKey("books.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), index=True)
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    terms: Mapped[dict] = mapped_column(JSON, default=dict)  # bm25-ish term frequencies
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    indexed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


# --------------------------------------------------------------------------- #
# Mors character
# --------------------------------------------------------------------------- #
class MorsState(Base, IdMixin):
    """Append-only log of every expression change, with the reason."""

    __tablename__ = "mors_states"

    student_id: Mapped[str | None] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    current_expression: Mapped[str] = mapped_column(String(30), nullable=False)
    previous_expression: Mapped[str | None] = mapped_column(String(30))
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    event: Mapped[str] = mapped_column(String(60), default="")
    reason: Mapped[str] = mapped_column(String(400), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer, default=5)
    animation: Mapped[str] = mapped_column(String(30), default="fade")
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class MorsEvent(Base, IdMixin):
    __tablename__ = "mors_events"

    student_id: Mapped[str | None] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    outcome: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class MorsMessage(Base, IdMixin):
    __tablename__ = "mors_messages"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    expression: Mapped[str] = mapped_column(String(30), default="neutral")
    tone: Mapped[str] = mapped_column(String(24), default="friendly")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str] = mapped_column(String(80), default="")
    priority: Mapped[int] = mapped_column(Integer, default=5)
    category: Mapped[str] = mapped_column(String(30), default="general")
    delivered: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


# --------------------------------------------------------------------------- #
# system
# --------------------------------------------------------------------------- #
class Notification(Base, IdMixin, TimestampMixin):
    __tablename__ = "notifications"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(40), default="general", index=True)
    # study_reminder | review_reminder | exam_reminder | missed_task |
    # achievement | mors_message | system
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(300), default="")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Achievement(Base, IdMixin, TimestampMixin):
    __tablename__ = "achievements"

    code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(400), default="")
    icon: Mapped[str] = mapped_column(String(40), default="trophy")
    threshold: Mapped[int] = mapped_column(Integer, default=1)
    metric: Mapped[str] = mapped_column(String(40), default="sessions")


class StudentAchievement(Base, IdMixin):
    __tablename__ = "student_achievements"
    __table_args__ = (
        UniqueConstraint("student_id", "achievement_id", name="uq_student_achievement"),
    )

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    achievement_id: Mapped[str] = mapped_column(
        ForeignKey("achievements.id"), nullable=False, index=True
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    earned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppSetting(Base, IdMixin, TimestampMixin):
    __tablename__ = "app_settings"
    __table_args__ = (UniqueConstraint("key", name="uq_setting_key"),)

    key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[str] = mapped_column(String(300), default="")


class SearchDocument(Base, IdMixin, TimestampMixin):
    """Unified keyword + semantic index across every content type."""

    __tablename__ = "search_documents"

    student_id: Mapped[str | None] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    # lesson | note | summary | paper | video | question | conversation | book | quiz
    entity_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    url: Mapped[str] = mapped_column(String(300), default="")
    terms: Mapped[dict] = mapped_column(JSON, default=dict)
    embedding: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class RateLimitCounter(Base, IdMixin):
    __tablename__ = "rate_limit_counters"

    bucket: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    count: Mapped[int] = mapped_column(Integer, default=0)


__all__ = [
    "AIConversation",
    "AIMessage",
    "AIEvent",
    "AIUsage",
    "AIPrompt",
    "AIChunk",
    "MorsState",
    "MorsEvent",
    "MorsMessage",
    "Notification",
    "Achievement",
    "StudentAchievement",
    "AppSetting",
    "SearchDocument",
    "RateLimitCounter",
]
