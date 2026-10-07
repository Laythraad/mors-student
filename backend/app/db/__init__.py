"""Database package: engine, session factory and every mapped model."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings
from .base import Base, IdMixin, TimestampMixin, new_id, utcnow
from .models_curriculum import (
    Book,
    BookPage,
    Branch,
    Chapter,
    Curriculum,
    Lesson,
    LessonPage,
    LearningProfile,
    ReadingProgress,
    Role,
    Source,
    Stage,
    StudentProfile,
    StudentSettings,
    StudentSubject,
    StudyStreak,
    Subject,
    Unit,
    User,
)
from .models_learning import (
    Answer,
    CalendarEvent,
    ContentReport,
    Course,
    Exam,
    ExamAttempt,
    Flashcard,
    MasteryScore,
    Mistake,
    Note,
    Option,
    Paper,
    PaperBlock,
    PaperPage,
    PaperSource,
    PlanDay,
    Question,
    QuestionFlag,
    Quiz,
    QuizAttempt,
    Review,
    StudyPlan,
    StudySession,
    Summary,
    Task,
    Teacher,
    Upload,
    Video,
    VideoProgress,
    WeakTopic,
)
from .models_system import (
    AIChunk,
    AIConversation,
    AIEvent,
    AIMessage,
    AIPrompt,
    AIUsage,
    Achievement,
    AppSetting,
    MorsEvent,
    MorsMessage,
    MorsState,
    Notification,
    RateLimitCounter,
    SearchDocument,
    StudentAchievement,
)
from .models_publishing import ContentDraft, SchedulerRun

__all__ = [
    "Base",
    "IdMixin",
    "TimestampMixin",
    "new_id",
    "utcnow",
    "engine",
    "SessionLocal",
    "get_db",
    "init_db",
    "drop_db",
    # identity / curriculum
    "Role",
    "User",
    "Stage",
    "Branch",
    "Subject",
    "Curriculum",
    "Source",
    "Book",
    "BookPage",
    "Chapter",
    "Unit",
    "Lesson",
    "LessonPage",
    "ReadingProgress",
    "StudentProfile",
    "StudentSubject",
    "StudentSettings",
    "LearningProfile",
    "StudyStreak",
    # planning / study / assessment
    "StudyPlan",
    "PlanDay",
    "Task",
    "Exam",
    "CalendarEvent",
    "StudySession",
    "Review",
    "Quiz",
    "Question",
    "QuestionFlag",
    "Option",
    "QuizAttempt",
    "Answer",
    "MasteryScore",
    "WeakTopic",
    # knowledge / media
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
    # ai / mors / system
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
    # publishing / scheduling (§83 / §126)
    "ContentDraft",
    "SchedulerRun",
]

_connect_args: dict = {}
if settings.database_url.startswith("sqlite"):
    # timeout = busy timeout: concurrent writers (scheduler vs requests) wait
    # for the lock instead of failing instantly with "database is locked".
    _connect_args = {"check_same_thread": False, "timeout": 30}

engine: Engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    future=True,
    pool_pre_ping=True,
)

if settings.database_url.startswith("sqlite"):

    @event.listens_for(Engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _record):  # pragma: no cover
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    Base.metadata.create_all(engine)
    _migrate_existing_tables()


def _column_ddl(column) -> str:
    """Column type + NULL rules for a runtime ALTER TABLE."""
    ddl = column.type.compile(engine.dialect)
    if column.default is not None and column.default.is_scalar:
        value = column.default.arg
        if isinstance(value, str):
            ddl += f" DEFAULT '{value}'"
        elif isinstance(value, bool):
            ddl += f" DEFAULT {int(value)}"
        elif isinstance(value, (int, float)):
            ddl += f" DEFAULT {value}"
    if not column.nullable and "DEFAULT" not in ddl:
        # SQLite refuses ADD COLUMN NOT NULL without a default
        ddl += " DEFAULT ''" if "CHAR" in ddl.upper() or ddl.upper() in {"TEXT", "CLOB"} else " DEFAULT 0"
    if not column.nullable:
        ddl += " NOT NULL"
    return ddl


def _migrate_existing_tables() -> None:
    """Bring older databases up to the current schema.

    `create_all` only creates missing tables; columns added to existing tables
    (and constraint relaxations such as `questions.quiz_id` becoming nullable
    for the question bank) are applied here.
    """
    raw = engine.raw_connection()
    try:
        cursor = raw.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")

        for table in Base.metadata.tables.values():
            cursor.execute(f'PRAGMA table_info("{table.name}")')
            existing = {row[1] for row in cursor.fetchall()}
            if not existing:
                continue
            for column in table.columns:
                if column.name not in existing:
                    cursor.execute(
                        f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {_column_ddl(column)}'
                    )

        # questions.quiz_id used to be NOT NULL — the bank needs nullable rows,
        # and SQLite cannot drop a NOT NULL constraint in place.
        cursor.execute('PRAGMA table_info("questions")')
        info = cursor.fetchall()
        quiz_id = next((row for row in info if row[1] == "quiz_id"), None)
        if quiz_id and quiz_id[3]:
            from sqlalchemy.schema import CreateIndex

            table = Base.metadata.tables["questions"]
            columns_ddl = []
            for column in table.columns:
                part = f'"{column.name}" {_column_ddl(column)}'
                if column.primary_key:
                    part += " PRIMARY KEY"
                columns_ddl.append(part)
            cursor.execute(f'CREATE TABLE "questions_rebuild" ({", ".join(columns_ddl)})')
            names = [column.name for column in table.columns if any(r[1] == column.name for r in info)]
            quoted = ", ".join(f'"{name}"' for name in names)
            cursor.execute(
                f"INSERT INTO questions_rebuild ({quoted}) SELECT {quoted} FROM questions"
            )
            cursor.execute("DROP TABLE questions")
            cursor.execute('ALTER TABLE questions_rebuild RENAME TO "questions"')
            for index in table.indexes:
                index_ddl = str(CreateIndex(index).compile(engine)).strip()
                cursor.execute(index_ddl.replace("CREATE INDEX", "CREATE INDEX IF NOT EXISTS", 1))

        cursor.execute("PRAGMA foreign_keys=ON")
        raw.commit()
    finally:
        raw.close()


def drop_db() -> None:
    Base.metadata.drop_all(engine)
