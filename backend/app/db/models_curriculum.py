"""Curriculum, identity and learner-profile tables.

Nothing about the Iraqi curriculum is hard-coded anywhere else in the code
base: stages, branches, subjects, books, chapters, units, lessons and pages
are rows, and every content row carries a ``source_id`` so an AI answer can
be traced back to *book → chapter → lesson → page*.
"""

from __future__ import annotations

from datetime import datetime, time

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin

# --------------------------------------------------------------------------- #
# identity
# --------------------------------------------------------------------------- #
class Role(Base, IdMixin, TimestampMixin):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="")
    permissions: Mapped[list] = mapped_column(JSON, default=list)


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(40))
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(30), default="student", index=True)
    locale: Mapped[str] = mapped_column(String(8), default="ar")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    profile: Mapped[StudentProfile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    settings: Mapped[StudentSettings | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


# --------------------------------------------------------------------------- #
# curriculum
# --------------------------------------------------------------------------- #
class Stage(Base, IdMixin, TimestampMixin):
    __tablename__ = "stages"

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name_ar: Mapped[str] = mapped_column(String(120), nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    branches: Mapped[list[Branch]] = relationship(back_populates="stage")


class Branch(Base, IdMixin, TimestampMixin):
    __tablename__ = "branches"

    stage_id: Mapped[str] = mapped_column(ForeignKey("stages.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(120), nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), default="")
    track: Mapped[str] = mapped_column(String(20), default="science")  # science|literary|vocational|general
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    stage: Mapped[Stage] = relationship(back_populates="branches")
    subjects: Mapped[list[Subject]] = relationship(back_populates="branch")


class Subject(Base, IdMixin, TimestampMixin):
    __tablename__ = "subjects"
    __table_args__ = (UniqueConstraint("branch_id", "code", name="uq_subject_branch_code"),)

    branch_id: Mapped[str] = mapped_column(ForeignKey("branches.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name_ar: Mapped[str] = mapped_column(String(120), nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), default="")
    color: Mapped[str] = mapped_column(String(16), default="#2f8ff7")
    icon: Mapped[str] = mapped_column(String(40), default="book")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    branch: Mapped[Branch] = relationship(back_populates="subjects")


class Curriculum(Base, IdMixin, TimestampMixin):
    __tablename__ = "curriculums"

    stage_id: Mapped[str] = mapped_column(ForeignKey("stages.id"), nullable=False, index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(20), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class Source(Base, IdMixin, TimestampMixin):
    """The provenance record for anything the AI is allowed to cite."""

    __tablename__ = "sources"

    kind: Mapped[str] = mapped_column(String(30), default="book")  # book|page|lesson|admin|web
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    book_id: Mapped[str | None] = mapped_column(ForeignKey("books.id"), index=True)
    chapter_id: Mapped[str | None] = mapped_column(ForeignKey("chapters.id"))
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    page_number: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str | None] = mapped_column(String(500))
    citation: Mapped[str] = mapped_column(String(500), default="")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class Book(Base, IdMixin, TimestampMixin):
    __tablename__ = "books"

    subject_id: Mapped[str] = mapped_column(ForeignKey("subjects.id"), nullable=False, index=True)
    curriculum_id: Mapped[str | None] = mapped_column(ForeignKey("curriculums.id"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    edition: Mapped[str] = mapped_column(String(80), default="")
    author: Mapped[str] = mapped_column(String(160), default="")
    cover_path: Mapped[str | None] = mapped_column(String(300))
    upload_id: Mapped[str | None] = mapped_column(String(32))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    chapters: Mapped[list[Chapter]] = relationship(back_populates="book", cascade="all, delete-orphan")
    pages: Mapped[list[BookPage]] = relationship(back_populates="book", cascade="all, delete-orphan")


class Chapter(Base, IdMixin, TimestampMixin):
    __tablename__ = "chapters"

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False, index=True)
    index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)

    book: Mapped[Book] = relationship(back_populates="chapters")
    units: Mapped[list[Unit]] = relationship(back_populates="chapter", cascade="all, delete-orphan")


class Unit(Base, IdMixin, TimestampMixin):
    __tablename__ = "units"

    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id"), nullable=False, index=True)
    index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(255), nullable=False)

    chapter: Mapped[Chapter] = relationship(back_populates="units")
    lessons: Mapped[list[Lesson]] = relationship(back_populates="unit", cascade="all, delete-orphan")


class Lesson(Base, IdMixin, TimestampMixin):
    __tablename__ = "lessons"

    unit_id: Mapped[str | None] = mapped_column(ForeignKey("units.id"), index=True)
    chapter_id: Mapped[str | None] = mapped_column(ForeignKey("chapters.id"), index=True)
    subject_id: Mapped[str] = mapped_column(ForeignKey("subjects.id"), nullable=False, index=True)
    index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="")
    objectives: Mapped[list] = mapped_column(JSON, default=list)
    difficulty: Mapped[int] = mapped_column(Integer, default=3)  # 1..5
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=45)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), index=True)
    prerequisites: Mapped[list] = mapped_column(JSON, default=list)  # lesson ids
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    unit: Mapped[Unit | None] = relationship(back_populates="lessons")
    pages: Mapped[list[LessonPage]] = relationship(back_populates="lesson", cascade="all, delete-orphan")


class LessonPage(Base, IdMixin, TimestampMixin):
    __tablename__ = "lesson_pages"
    __table_args__ = (UniqueConstraint("lesson_id", "page_number", name="uq_lesson_page"),)

    lesson_id: Mapped[str] = mapped_column(ForeignKey("lessons.id"), nullable=False, index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, default="")
    image_path: Mapped[str | None] = mapped_column(String(300))

    lesson: Mapped[Lesson] = relationship(back_populates="pages")


class BookPage(Base, IdMixin, TimestampMixin):
    """One physical textbook page — what the reader renders and RAG cites."""

    __tablename__ = "book_pages"
    __table_args__ = (UniqueConstraint("book_id", "page_number", name="uq_book_page"),)

    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False, index=True)
    chapter_id: Mapped[str | None] = mapped_column(ForeignKey("chapters.id"), index=True)
    unit_id: Mapped[str | None] = mapped_column(ForeignKey("units.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[str] = mapped_column(String(255), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    book: Mapped[Book] = relationship(back_populates="pages")


class ReadingProgress(Base, IdMixin, TimestampMixin):
    """Per-student place in a book: position, bookmarks and highlights."""

    __tablename__ = "reading_progress"
    __table_args__ = (UniqueConstraint("profile_id", "book_id", name="uq_reading_profile_book"),)

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), nullable=False, index=True)
    last_page: Mapped[int] = mapped_column(Integer, default=1)
    bookmarks: Mapped[list] = mapped_column(JSON, default=list)  # [{page, label}]
    highlights: Mapped[list] = mapped_column(JSON, default=list)  # [{page, text, note}]
    opened_count: Mapped[int] = mapped_column(Integer, default=0)


# --------------------------------------------------------------------------- #
# learner
# --------------------------------------------------------------------------- #
class StudentProfile(Base, IdMixin, TimestampMixin):
    __tablename__ = "student_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    stage_id: Mapped[str | None] = mapped_column(ForeignKey("stages.id"), index=True)
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"), index=True)
    school_name: Mapped[str] = mapped_column(String(160), default="")
    school_start: Mapped[time | None] = mapped_column(Time)
    school_end: Mapped[time | None] = mapped_column(Time)
    sleep_start: Mapped[time | None] = mapped_column(Time)
    sleep_end: Mapped[time | None] = mapped_column(Time)
    daily_study_minutes: Mapped[int] = mapped_column(Integer, default=120)
    study_days: Mapped[list] = mapped_column(JSON, default=lambda: [0, 1, 2, 3, 4])  # mon..fri
    free_windows: Mapped[list] = mapped_column(JSON, default=list)
    goals: Mapped[str] = mapped_column(Text, default="")
    current_level: Mapped[str] = mapped_column(String(20), default="beginner")
    onboarding_step: Mapped[int] = mapped_column(Integer, default=0)
    diagnostic_done: Mapped[bool] = mapped_column(Boolean, default=False)
    goal_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    streak_id: Mapped[str | None] = mapped_column(String(32))

    user: Mapped[User] = relationship(back_populates="profile")
    subjects: Mapped[list[StudentSubject]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )


class StudentSubject(Base, IdMixin, TimestampMixin):
    __tablename__ = "student_subjects"
    __table_args__ = (UniqueConstraint("profile_id", "subject_id", name="uq_profile_subject"),)

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    subject_id: Mapped[str] = mapped_column(ForeignKey("subjects.id"), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=2)  # 1 high 2 normal 3 low
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    profile: Mapped[StudentProfile] = relationship(back_populates="subjects")


class StudentSettings(Base, IdMixin, TimestampMixin):
    __tablename__ = "student_settings"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    theme: Mapped[str] = mapped_column(String(20), default="light")
    primary_color: Mapped[str] = mapped_column(String(16), default="#2f8ff7")
    accent_color: Mapped[str] = mapped_column(String(16), default="#8ad4ff")
    font_scale: Mapped[float] = mapped_column(Float, default=1.0)
    card_style: Mapped[str] = mapped_column(String(20), default="soft")
    reduce_motion: Mapped[bool] = mapped_column(Boolean, default=False)
    high_contrast: Mapped[bool] = mapped_column(Boolean, default=False)
    mors_size: Mapped[str] = mapped_column(String(12), default="normal")
    mors_idle_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    focus_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    notification_freq: Mapped[str] = mapped_column(String(16), default="normal")  # off|quiet|normal|all
    categories: Mapped[dict] = mapped_column(JSON, default=dict)
    celebrate_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    voice_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tts_voice: Mapped[str] = mapped_column(String(60), default="system")
    stt_provider: Mapped[str] = mapped_column(String(40), default="browser")

    user: Mapped[User] = relationship(back_populates="settings")


class LearningProfile(Base, IdMixin, TimestampMixin):
    __tablename__ = "learning_profiles"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), unique=True, nullable=False
    )
    learning_speed: Mapped[str] = mapped_column(String(16), default="normal")  # slow|normal|fast
    preferred_explanation: Mapped[str] = mapped_column(String(20), default="step_by_step")
    avg_session_minutes: Mapped[float] = mapped_column(Float, default=45.0)
    session_completion_rate: Mapped[float] = mapped_column(Float, default=0.6)
    best_time_of_day: Mapped[str] = mapped_column(String(12), default="evening")
    sessions_completed: Mapped[int] = mapped_column(Integer, default=0)
    sessions_abandoned: Mapped[int] = mapped_column(Integer, default=0)
    total_study_seconds: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")


class StudyStreak(Base, IdMixin, TimestampMixin):
    __tablename__ = "study_streaks"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), unique=True, nullable=False
    )
    current: Mapped[int] = mapped_column(Integer, default=0)
    longest: Mapped[int] = mapped_column(Integer, default=0)
    last_study_day: Mapped[str | None] = mapped_column(String(10))  # YYYY-MM-DD
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)


__all__ = [
    "Role",
    "User",
    "Stage",
    "Branch",
    "Subject",
    "Curriculum",
    "Source",
    "Book",
    "Chapter",
    "Unit",
    "Lesson",
    "LessonPage",
    "StudentProfile",
    "StudentSubject",
    "StudentSettings",
    "LearningProfile",
    "StudyStreak",
]
