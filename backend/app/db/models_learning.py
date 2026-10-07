"""Planning, study, assessment, knowledge and media tables."""

from __future__ import annotations

from datetime import date, datetime

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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin, utcnow


# --------------------------------------------------------------------------- #
# planning
# --------------------------------------------------------------------------- #
class StudyPlan(Base, IdMixin, TimestampMixin):
    __tablename__ = "study_plans"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), default="regular")
    # regular | recovery | exam | diagnostic
    generated_by: Mapped[str] = mapped_column(String(20), default="ai")  # ai | manual
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    rationale: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    days: Mapped[list[PlanDay]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="PlanDay.date"
    )


class PlanDay(Base, IdMixin, TimestampMixin):
    __tablename__ = "plan_days"
    __table_args__ = (UniqueConstraint("plan_id", "date", name="uq_plan_day"),)

    plan_id: Mapped[str] = mapped_column(ForeignKey("study_plans.id"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(80), default="")
    focus: Mapped[str] = mapped_column(String(120), default="")
    total_minutes: Mapped[int] = mapped_column(Integer, default=0)
    is_rest: Mapped[bool] = mapped_column(Boolean, default=False)

    plan: Mapped[StudyPlan] = relationship(back_populates="days")
    tasks: Mapped[list[Task]] = relationship(
        back_populates="day", cascade="all, delete-orphan", order_by="Task.scheduled_start"
    )


class Task(Base, IdMixin, TimestampMixin):
    __tablename__ = "tasks"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("study_plans.id"), index=True)
    day_id: Mapped[str | None] = mapped_column(ForeignKey("plan_days.id"), index=True)
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    exam_id: Mapped[str | None] = mapped_column(ForeignKey("exams.id"))
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    type: Mapped[str] = mapped_column(String(20), default="study")
    # study | review | quiz | mock | rest | reading | homework
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # pending | in_progress | completed | skipped | postponed
    priority: Mapped[int] = mapped_column(Integer, default=2)
    scheduled_date: Mapped[date | None] = mapped_column(Date, index=True)
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=45)
    goal: Mapped[str] = mapped_column(String(400), default="")
    rationale: Mapped[str] = mapped_column(String(400), default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_seconds: Mapped[int] = mapped_column(Integer, default=0)
    mastery_before: Mapped[float | None] = mapped_column(Float)
    mastery_after: Mapped[float | None] = mapped_column(Float)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    day: Mapped[PlanDay | None] = relationship(back_populates="tasks")


class Exam(Base, IdMixin, TimestampMixin):
    __tablename__ = "exams"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    exam_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=90)
    topics: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="upcoming")  # upcoming|done|cancelled
    score: Mapped[float | None] = mapped_column(Float)
    max_score: Mapped[float | None] = mapped_column(Float)
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("study_plans.id"))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)


class CalendarEvent(Base, IdMixin, TimestampMixin):
    __tablename__ = "calendar_events"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), default="custom")
    # school | sleep | task | exam | review | custom
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    color: Mapped[str] = mapped_column(String(16), default="#2f8ff7")
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    exam_id: Mapped[str | None] = mapped_column(ForeignKey("exams.id"))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


# --------------------------------------------------------------------------- #
# study
# --------------------------------------------------------------------------- #
class StudySession(Base, IdMixin, TimestampMixin):
    __tablename__ = "study_sessions"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), index=True)
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    title: Mapped[str] = mapped_column(String(220), default="")
    goal: Mapped[str] = mapped_column(String(400), default="")
    planned_minutes: Mapped[int] = mapped_column(Integer, default=45)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    # active | completed | interrupted | on_break
    focus_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    feedback: Mapped[str | None] = mapped_column(String(20))  # easy|medium|hard|not_understood
    understanding: Mapped[float | None] = mapped_column(Float)
    mistakes: Mapped[int] = mapped_column(Integer, default=0)
    quiz_id: Mapped[str | None] = mapped_column(String(32))
    review_id: Mapped[str | None] = mapped_column(String(32))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Review(Base, IdMixin, TimestampMixin):
    __tablename__ = "reviews"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    topic: Mapped[str] = mapped_column(String(220), default="")
    kind: Mapped[str] = mapped_column(String(20), default="lesson")  # lesson|topic|flashcard
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    interval_days: Mapped[float] = mapped_column(Float, default=1.0)
    ease: Mapped[float] = mapped_column(Float, default=2.5)
    reps: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    last_result: Mapped[str | None] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(16), default="due", index=True)
    # due | scheduled | done
    source: Mapped[str] = mapped_column(String(20), default="auto")


# --------------------------------------------------------------------------- #
# assessment
# --------------------------------------------------------------------------- #
class Quiz(Base, IdMixin, TimestampMixin):
    __tablename__ = "quizzes"

    student_id: Mapped[str | None] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    teacher_id: Mapped[str | None] = mapped_column(ForeignKey("teachers.id"))
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), default="quiz")
    # quiz | practice | chapter | mock | final | diagnostic
    difficulty: Mapped[int] = mapped_column(Integer, default=3)
    time_limit_seconds: Mapped[int] = mapped_column(Integer, default=0)
    is_adaptive: Mapped[bool] = mapped_column(Boolean, default=True)
    source_scope: Mapped[str] = mapped_column(String(20), default="curriculum")
    generated_by: Mapped[str] = mapped_column(String(20), default="ai")
    status: Mapped[str] = mapped_column(String(16), default="ready")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    questions: Mapped[list[Question]] = relationship(
        back_populates="quiz", cascade="all, delete-orphan", order_by="Question.order"
    )


class Question(Base, IdMixin, TimestampMixin):
    __tablename__ = "questions"

    # nullable: a question with no quiz lives in the reusable question bank
    quiz_id: Mapped[str | None] = mapped_column(ForeignKey("quizzes.id"), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(20), default="mcq")
    # mcq | true_false | fill_blank | short_answer | problem | essay | calculation
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, default="")
    difficulty: Mapped[int] = mapped_column(Integer, default=3)
    points: Mapped[float] = mapped_column(Float, default=1.0)
    order: Mapped[int] = mapped_column(Integer, default=0)
    answer_key: Mapped[str] = mapped_column(Text, default="")
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), index=True)
    topic: Mapped[str] = mapped_column(String(220), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    # provenance: never present an AI question as an official one (spec §75/§76)
    source_kind: Mapped[str] = mapped_column(String(20), default="ai")
    # official | ai | external | bank
    # §10: an official question only ships with a verified web link + check date
    source_url: Mapped[str] = mapped_column(String(500), default="")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    chapter_id: Mapped[str | None] = mapped_column(ForeignKey("chapters.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    year: Mapped[str] = mapped_column(String(12), default="")
    page: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="published")
    # draft | validated | published | rejected
    dedup_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    quiz: Mapped[Quiz | None] = relationship(back_populates="questions")
    options: Mapped[list[Option]] = relationship(
        back_populates="question", cascade="all, delete-orphan", order_by="Option.order"
    )


class Option(Base, IdMixin):
    __tablename__ = "options"

    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    order: Mapped[int] = mapped_column(Integer, default=0)

    question: Mapped[Question] = relationship(back_populates="options")


class QuizAttempt(Base, IdMixin, TimestampMixin):
    __tablename__ = "quiz_attempts"

    quiz_id: Mapped[str] = mapped_column(ForeignKey("quizzes.id"), nullable=False, index=True)
    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="in_progress")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    max_score: Mapped[float] = mapped_column(Float, default=0.0)
    accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    time_seconds: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    report: Mapped[dict] = mapped_column(JSON, default=dict)


class Answer(Base, IdMixin, TimestampMixin):
    __tablename__ = "answers"

    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("quiz_attempts.id"), nullable=False, index=True
    )
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id"), nullable=False, index=True)
    student_answer: Mapped[str] = mapped_column(Text, default="")
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    awarded_points: Mapped[float] = mapped_column(Float, default=0.0)
    time_seconds: Mapped[int] = mapped_column(Integer, default=0)
    difficulty_before: Mapped[int | None] = mapped_column(Integer)
    difficulty_after: Mapped[int | None] = mapped_column(Integer)
    hint_used: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    feedback: Mapped[str] = mapped_column(Text, default="")


class MasteryScore(Base, IdMixin, TimestampMixin):
    __tablename__ = "mastery_scores"
    __table_args__ = (
        UniqueConstraint("student_id", "subject_id", "lesson_id", name="uq_mastery_lesson"),
    )

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    topic: Mapped[str] = mapped_column(String(220), default="")
    score: Mapped[float] = mapped_column(Float, default=0.0)  # 0..100
    trend: Mapped[float] = mapped_column(Float, default=0.0)
    samples: Mapped[int] = mapped_column(Integer, default=0)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    wrong: Mapped[int] = mapped_column(Integer, default=0)
    last_practiced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WeakTopic(Base, IdMixin, TimestampMixin):
    __tablename__ = "weak_topics"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    topic: Mapped[str] = mapped_column(String(220), nullable=False)
    severity: Mapped[int] = mapped_column(Integer, default=1)  # 1..5
    errors: Mapped[int] = mapped_column(Integer, default=0)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class Mistake(Base, IdMixin, TimestampMixin):
    """Exam mistake book (spec §66) — every important error keeps its context."""

    __tablename__ = "mistakes"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    question_id: Mapped[str | None] = mapped_column(ForeignKey("questions.id"))
    attempt_id: Mapped[str | None] = mapped_column(ForeignKey("quiz_attempts.id"), index=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    student_answer: Mapped[str] = mapped_column(Text, default="")
    correct_answer: Mapped[str] = mapped_column(Text, default="")
    explanation: Mapped[str] = mapped_column(Text, default="")
    topic: Mapped[str] = mapped_column(String(220), default="")
    difficulty: Mapped[int] = mapped_column(Integer, default=3)
    source_kind: Mapped[str] = mapped_column(String(20), default="ai")
    reason: Mapped[str] = mapped_column(String(40), default="wrong")
    # wrong | skipped | unclear
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExamAttempt(Base, IdMixin, TimestampMixin):
    """A timed exam simulation session: timer, navigation, marks, submission.

    Grading itself stays in `quiz_attempts`; this table owns the exam UX state
    required by the spec (timer + mark-for-review + final submission).
    """

    __tablename__ = "exam_attempts"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    exam_id: Mapped[str | None] = mapped_column(ForeignKey("exams.id"), index=True)
    quiz_id: Mapped[str] = mapped_column(ForeignKey("quizzes.id"), nullable=False, index=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("quiz_attempts.id"), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(16), default="mock")
    # mock | practice | final
    time_limit_seconds: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default="in_progress")
    # in_progress | submitted | expired
    marked: Mapped[list] = mapped_column(JSON, default=list)
    current_index: Mapped[int] = mapped_column(Integer, default=0)
    overtime: Mapped[bool] = mapped_column(Boolean, default=False)
    report: Mapped[dict] = mapped_column(JSON, default=dict)


# --------------------------------------------------------------------------- #
# knowledge â€” papers, notes, summaries, flashcards
# --------------------------------------------------------------------------- #
class Paper(Base, IdMixin, TimestampMixin):
    __tablename__ = "papers"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), default="note")
    # note | ai_summary | study_sheet | homework | preparation | exam_paper
    #       | handwritten | uploaded | flashcards
    created_by_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    emoji: Mapped[str] = mapped_column(String(8), default="")
    color: Mapped[str] = mapped_column(String(16), default="#2f8ff7")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    pages: Mapped[list[PaperPage]] = relationship(
        back_populates="paper", cascade="all, delete-orphan", order_by="PaperPage.position"
    )
    sources: Mapped[list[PaperSource]] = relationship(
        back_populates="paper", cascade="all, delete-orphan"
    )


class PaperPage(Base, IdMixin, TimestampMixin):
    __tablename__ = "paper_pages"

    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(220), default="")
    background: Mapped[str] = mapped_column(String(20), default="plain")

    paper: Mapped[Paper] = relationship(back_populates="pages")
    blocks: Mapped[list[PaperBlock]] = relationship(
        back_populates="page", cascade="all, delete-orphan", order_by="PaperBlock.position"
    )


class PaperBlock(Base, IdMixin, TimestampMixin):
    __tablename__ = "paper_blocks"

    page_id: Mapped[str] = mapped_column(ForeignKey("paper_pages.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(20), default="text")
    # text | heading | table | image | drawing | math | highlight | list | divider | flashcard
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    position: Mapped[int] = mapped_column(Integer, default=0)
    x: Mapped[int] = mapped_column(Integer, default=0)
    y: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int] = mapped_column(Integer, default=100)
    height: Mapped[int] = mapped_column(Integer, default=0)

    page: Mapped[PaperPage] = relationship(back_populates="blocks")


class PaperSource(Base, IdMixin):
    __tablename__ = "paper_sources"
    __table_args__ = (UniqueConstraint("paper_id", "source_id", name="uq_paper_source"),)

    paper_id: Mapped[str] = mapped_column(ForeignKey("papers.id"), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False)
    note: Mapped[str] = mapped_column(String(300), default="")

    paper: Mapped[Paper] = relationship(back_populates="sources")


class Note(Base, IdMixin, TimestampMixin):
    __tablename__ = "notes"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    paper_id: Mapped[str | None] = mapped_column(ForeignKey("papers.id"), index=True)
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)


class Summary(Base, IdMixin, TimestampMixin):
    __tablename__ = "summaries"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    kind: Mapped[str] = mapped_column(String(24), default="quick")
    # quick | detailed | exam | last_minute | definitions | formulas | key_points
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="")
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    paper_id: Mapped[str | None] = mapped_column(ForeignKey("papers.id"))


class Flashcard(Base, IdMixin, TimestampMixin):
    __tablename__ = "flashcards"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    front: Mapped[str] = mapped_column(Text, nullable=False)
    back: Mapped[str] = mapped_column(Text, nullable=False)
    ease: Mapped[float] = mapped_column(Float, default=2.5)
    interval_days: Mapped[float] = mapped_column(Float, default=1.0)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reps: Mapped[int] = mapped_column(Integer, default=0)
    lapses: Mapped[int] = mapped_column(Integer, default=0)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"))


# --------------------------------------------------------------------------- #
# media â€” teachers, courses, videos, uploads
# --------------------------------------------------------------------------- #
class Teacher(Base, IdMixin, TimestampMixin):
    __tablename__ = "teachers"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    headline: Mapped[str] = mapped_column(String(255), default="")
    bio: Mapped[str] = mapped_column(Text, default="")
    style: Mapped[str] = mapped_column(String(120), default="")
    avatar_path: Mapped[str | None] = mapped_column(String(300))
    subjects: Mapped[list] = mapped_column(JSON, default=list)
    stages: Mapped[list] = mapped_column(JSON, default=list)
    lessons_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    has_summaries: Mapped[bool] = mapped_column(Boolean, default=False)
    has_tests: Mapped[bool] = mapped_column(Boolean, default=False)
    level: Mapped[str] = mapped_column(String(30), default="intermediate")
    rating: Mapped[float | None] = mapped_column(Float)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    # Directory honesty fields (iraqi-teacher-directory skill): only a link
    # verified against the teacher's own cross-linked accounts may be stored,
    # and every stored link remembers when/by whom it was checked.
    channel_url: Mapped[str] = mapped_column(String(300), default="")
    link_status: Mapped[str] = mapped_column(String(30), default="none")  # official | search | none
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by: Mapped[str] = mapped_column(String(120), default="")


class Course(Base, IdMixin, TimestampMixin):
    __tablename__ = "courses"

    teacher_id: Mapped[str | None] = mapped_column(ForeignKey("teachers.id"), index=True)
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    stage_id: Mapped[str | None] = mapped_column(ForeignKey("stages.id"))
    branch_id: Mapped[str | None] = mapped_column(ForeignKey("branches.id"))
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[str] = mapped_column(String(30), default="intermediate")
    cover_path: Mapped[str | None] = mapped_column(String(300))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    videos: Mapped[list[Video]] = relationship(back_populates="course", cascade="all, delete-orphan")


class Video(Base, IdMixin, TimestampMixin):
    __tablename__ = "videos"

    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id"), index=True)
    teacher_id: Mapped[str | None] = mapped_column(ForeignKey("teachers.id"), index=True)
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True)
    chapter_id: Mapped[str | None] = mapped_column(ForeignKey("chapters.id"))
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    url: Mapped[str] = mapped_column(String(500), default="")
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    thumbnail_path: Mapped[str | None] = mapped_column(String(300))
    transcript: Mapped[str] = mapped_column(Text, default="")
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)

    course: Mapped[Course | None] = relationship(back_populates="videos")


class VideoProgress(Base, IdMixin, TimestampMixin):
    __tablename__ = "video_progress"
    __table_args__ = (UniqueConstraint("student_id", "video_id", name="uq_video_progress"),)

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id"), nullable=False, index=True)
    watched_seconds: Mapped[int] = mapped_column(Integer, default=0)
    last_position: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    quiz_score: Mapped[float | None] = mapped_column(Float)
    key_idea: Mapped[str] = mapped_column(Text, default="")


class ContentReport(Base, IdMixin, TimestampMixin):
    """Content review queue (spec §84–§85): broken video, missing link…"""

    __tablename__ = "content_reports"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    video_id: Mapped[str | None] = mapped_column(ForeignKey("videos.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="not_working")
    # not_working | not_linked | unclear | other
    detail: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    # open | resolved
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuestionFlag(Base, IdMixin, TimestampMixin):
    """Student flag on a quiz/exam question for human follow-up.

    Same shape as ContentReport but scoped to an assessed question: a wrong
    option, a misleading prompt or an unclear explanation reaches the admin
    inbox instead of being silently shown to the next student.
    """

    __tablename__ = "question_flags"

    student_id: Mapped[str] = mapped_column(
        ForeignKey("student_profiles.id"), nullable=False, index=True
    )
    question_id: Mapped[str | None] = mapped_column(ForeignKey("questions.id"), index=True)
    quiz_id: Mapped[str | None] = mapped_column(ForeignKey("quizzes.id"), index=True)
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30), default="unclear")
    # wrong_answer | unclear | bad_options | other
    detail: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    # open | resolved
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Upload(Base, IdMixin, TimestampMixin):

    __tablename__ = "uploads"

    student_id: Mapped[str | None] = mapped_column(ForeignKey("student_profiles.id"), index=True)
    uploader_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="document")
    # document | image | notebook | book
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str] = mapped_column(String(400), nullable=False)
    mime: Mapped[str] = mapped_column(String(100), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="received", index=True)
    # received | scanning | indexing | ready | failed
    error: Mapped[str] = mapped_column(String(300), default="")
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"))
    lesson_id: Mapped[str | None] = mapped_column(ForeignKey("lessons.id"))
    book_id: Mapped[str | None] = mapped_column(ForeignKey("books.id"))
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    ocr_engine: Mapped[str] = mapped_column(String(40), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


__all__ = [
    "StudyPlan",
    "PlanDay",
    "Task",
    "Exam",
    "CalendarEvent",
    "StudySession",
    "Review",
    "Quiz",
    "Question",
    "Option",
    "QuizAttempt",
    "Answer",
    "MasteryScore",
    "WeakTopic",
    "Mistake",
    "ExamAttempt",
    "Paper",
    "PaperPage",
    "PaperBlock",
    "PaperSource",
    "Note",
    "Summary",
    "Flashcard",
    "Teacher",
    "Course",
    "Video",
    "VideoProgress",
    "ContentReport",
    "Upload",
]

