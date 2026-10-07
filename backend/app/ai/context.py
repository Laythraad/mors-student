"""Context assembly — what the model is allowed to know.

Context is *assembled, not accumulated*: profile facts + current lesson +
mastery/weak spots + retrieved RAG chunks. Full textbooks are never sent.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from ..config import settings
from ..db import (
    AIChunk,
    Branch,
    Chapter,
    Exam,
    LearningProfile,
    Lesson,
    MasteryScore,
    Source,
    Stage,
    StudentProfile,
    StudentSubject,
    Subject,
    Task,
    Unit,
    WeakTopic,
    StudySession,
)
from .base import ChatMessage


def _fmt_date(value: date | None) -> str:
    return value.isoformat() if value else "—"


def student_context(db: Session, student_id: str, *, upto: int = 1400) -> str:
    """Compact, privacy-minimal profile block."""
    profile = db.get(StudentProfile, student_id)
    if profile is None:
        return "لا يوجد ملف تعريفي."

    lines: list[str] = []
    if profile.stage_id:
        stage = db.get(Stage, profile.stage_id)
        if stage:
            lines.append(f"المرحلة: {stage.name_ar}")
    if profile.branch_id:
        branch = db.get(Branch, profile.branch_id)
        if branch:
            lines.append(f"الفرع: {branch.name_ar}")

    subject_ids = [
        row.subject_id
        for row in db.query(StudentSubject).filter(
            StudentSubject.profile_id == student_id, StudentSubject.is_active.is_(True)
        )
    ]
    if subject_ids:
        names = [
            s.name_ar
            for s in db.query(Subject).filter(Subject.id.in_(subject_ids)).order_by(Subject.sort_order)
        ]
        lines.append("المواد: " + "، ".join(names))

    lp = db.query(LearningProfile).filter(LearningProfile.student_id == student_id).one_or_none()
    if lp:
        lines.append(
            f"متوسط الجلسة {int(lp.avg_session_minutes)} دقيقة، معدل إتمام {int(lp.session_completion_rate * 100)}٪، "
            f"سرعة التعلم: {lp.learning_speed}، الشرح المفضل: {lp.preferred_explanation}"
        )

    weak = (
        db.query(WeakTopic)
        .filter(WeakTopic.student_id == student_id, WeakTopic.is_active.is_(True))
        .order_by(WeakTopic.severity.desc())
        .limit(5)
        .all()
    )
    if weak:
        lines.append("مواضيع ضعيفة: " + "، ".join(w.topic for w in weak))

    today = date.today()
    upcoming = (
        db.query(Exam)
        .filter(Exam.student_id == student_id, Exam.exam_date >= today, Exam.status == "upcoming")
        .order_by(Exam.exam_date)
        .limit(3)
        .all()
    )
    if upcoming:
        lines.append(
            "امتحانات قادمة: "
            + "؛ ".join(f"{e.title} بتاريخ {_fmt_date(e.exam_date)}" for e in upcoming)
        )

    pending = (
        db.query(Task)
        .filter(
            Task.student_id == student_id,
            Task.status.in_(["pending", "in_progress"]),
            Task.scheduled_date <= today + timedelta(days=3),
        )
        .order_by(Task.scheduled_date)
        .limit(6)
        .all()
    )
    if pending:
        lines.append(
            "مهام قريبة: "
            + "؛ ".join(
                f"{t.title} [{_fmt_date(t.scheduled_date)} - {t.duration_minutes}د]" for t in pending
            )
        )

    text = "\n".join(f"- {line}" for line in lines)
    return text[:upto] if upto else text


def lesson_context(db: Session, lesson_id: str | None, *, include_pages: bool = True) -> str:
    if not lesson_id:
        return ""
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        return ""

    lines: list[str] = [f"الدرس الحالي: {lesson.title}"]
    subject = db.get(Subject, lesson.subject_id)
    if subject:
        lines.insert(0, f"المادة: {subject.name_ar}")
    if lesson.chapter_id:
        chapter = db.get(Chapter, lesson.chapter_id)
        if chapter:
            lines.append(f"الفصل: {chapter.title}")
    if lesson.unit_id:
        unit = db.get(Unit, lesson.unit_id)
        if unit:
            lines.append(f"الوحدة: {unit.title}")
    if lesson.summary:
        lines.append(f"ملخص الدرس: {lesson.summary[:600]}")
    if lesson.objectives:
        lines.append("الأهداف: " + "؛ ".join(str(o) for o in lesson.objectives[:6]))
    if lesson.page_start:
        lines.append(f"الصفحات: {lesson.page_start}–{lesson.page_end or lesson.page_start}")

    if include_pages:
        pages = lesson.pages[:2]
        for page in pages:
            if page.text:
                lines.append(f"[صفحة {page.page_number}] {page.text[:700]}")
    return "\n".join(lines)


def mastery_context(db: Session, student_id: str, subject_id: str | None = None, limit: int = 8) -> str:
    q = db.query(MasteryScore).filter(MasteryScore.student_id == student_id)
    if subject_id:
        q = q.filter(MasteryScore.subject_id == subject_id)
    rows = q.order_by(MasteryScore.score.asc()).limit(limit).all()
    if not rows:
        return ""
    parts = []
    for row in rows:
        lesson = db.get(Lesson, row.lesson_id) if row.lesson_id else None
        label = row.topic or (lesson.title if lesson else "درس")
        parts.append(f"{label}: {int(row.score)}٪")
    return "الإتقان (الأضعف أولاً): " + "، ".join(parts)


def retrieve(db: Session, query: str, *, student_id: str | None = None, subject_id: str | None = None,
             lesson_id: str | None = None, top_k: int | None = None) -> list[dict]:
    """Hybrid retrieval: term overlap + cosine over stored embeddings."""
    from ..rag.search import hybrid_search  # local import avoids a package cycle

    return hybrid_search(
        db,
        query,
        student_id=student_id,
        subject_id=subject_id,
        lesson_id=lesson_id,
        top_k=top_k or settings.rag_top_k,
    )


def chunks_to_context(chunks: list[dict]) -> str:
    if not chunks:
        return ""
    lines = ["المصادر المسترجَعة:"]
    for i, chunk in enumerate(chunks, 1):
        citation = chunk.get("citation") or chunk.get("title") or "مصدر"
        lines.append(f"[{i}] ({citation}) {chunk.get('text', '')[:700]}")
    return "\n".join(lines)


def citations_from(chunks: list[dict]) -> list[dict]:
    """Only retrieved ids may be cited — this is the anti-hallucination gate."""
    allowed = {c.get("chunk_id") for c in chunks}
    out: list[dict] = []
    for chunk in chunks:
        cid = chunk.get("chunk_id")
        if cid not in allowed:
            continue
        out.append(
            {
                "chunk_id": cid,
                "source_id": chunk.get("source_id"),
                "citation": chunk.get("citation", ""),
                "title": chunk.get("title", ""),
                "book": chunk.get("book", ""),
                "chapter": chunk.get("chapter", ""),
                "lesson": chunk.get("lesson", ""),
                "page": chunk.get("page"),
                "score": round(float(chunk.get("score", 0.0)), 4),
            }
        )
    return out


def history_messages(db: Session, conversation_id: str | None, limit: int | None = None) -> list[ChatMessage]:
    if not conversation_id:
        return []
    from ..db import AIMessage

    rows = (
        db.query(AIMessage)
        .filter(AIMessage.conversation_id == conversation_id)
        .order_by(AIMessage.created_at.desc())
        .limit(limit or settings.ai_max_history_messages)
        .all()
    )
    rows.reverse()
    return [ChatMessage(role=m.role, content=m.content) for m in rows if m.role in ("user", "assistant")]


def compact_history(messages: list[ChatMessage], budget: int = 1600) -> str:
    """Summarise older turns instead of resending them (cost control)."""
    if not messages:
        return "—"
    parts: list[str] = []
    used = 0
    for m in reversed(messages):
        line = f"{'الطالب' if m.role == 'user' else 'مورس'}: {m.content[:220]}"
        if used + len(line) > budget:
            break
        parts.append(line)
        used += len(line)
    parts.reverse()
    return "\n".join(parts) or "—"


__all__ = [
    "student_context",
    "lesson_context",
    "mastery_context",
    "retrieve",
    "chunks_to_context",
    "citations_from",
    "history_messages",
    "compact_history",
]
