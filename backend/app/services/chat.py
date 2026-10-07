"""Student ↔ Mors chat (Socratic tutoring).

The anti-hallucination rule lives here, not in the prompt: if the retrieval
step found nothing for a curriculum-shaped question, we never call the model
at all — we answer with an explicit "no source found".
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from ..ai import (
    AIRequest,
    ChatMessage,
    ask,
    citations_from,
    history_messages,
    lesson_context,
    retrieve,
    route,
    student_context,
)
from ..config import settings
from ..core.errors import NotFoundError, ValidationError
from ..db import AIMessage, AIConversation, Lesson, Subject, utcnow
from ..mors import EventType, PersonalityContext, bus
from ..mors.models_helper import react_and_persist

NO_SOURCE = (
    "ما لقيت مصدراً موثوق بهالسؤال ضمن منهجك، وما راح أخمّنه. "
    "افتح الدرس المذكور وابعتلي الفقرة أو رقم الصفحة، أو جرّب صياغة أسهل."
)

CHITCHAT = re.compile(
    r"^(مرحبا|هلا|السلام|صباح الخير|مساء الخير|شلونك|هاي|من انت|مين انت|"
    r"شكرا|شكراً|تسلم|باي|مع السلامة|كيفك)\b",
    re.U,
)

MODE_TO_TASK = {
    "tutor": "explain",
    "explain": "explain",
    "socratic": "socratic_hint",
    "hint": "socratic_hint",
    "quiz": "quiz",
    "summarize": "summarize",
    "curriculum": "curriculum",
    "title": "title",
}

#: modes that must never answer a curriculum question without a source
SOURCE_BOUND_MODES = {"tutor", "explain", "socratic", "hint", "curriculum"}


# --------------------------------------------------------------------------- #
# conversations
# --------------------------------------------------------------------------- #
def get_or_create_conversation(
    db: Session,
    student_id: str,
    *,
    conversation_id: str | None = None,
    subject_id: str | None = None,
    lesson_id: str | None = None,
    agent: str = "tutor",
    title: str = "",
) -> AIConversation:
    if conversation_id:
        row = db.get(AIConversation, conversation_id)
        if row is None or row.student_id != student_id:
            raise NotFoundError("المحادثة غير موجودة.")
        return row

    if subject_id is None and lesson_id:
        lesson = db.get(Lesson, lesson_id)
        subject_id = lesson.subject_id if lesson else None

    row = AIConversation(
        student_id=student_id,
        title=title,
        agent=agent,
        subject_id=subject_id,
        lesson_id=lesson_id,
        last_message_at=utcnow(),
    )
    db.add(row)
    db.flush()
    return row


def list_conversations(
    db: Session, student_id: str, *, limit: int = 30, include_archived: bool = False
) -> list[dict[str, Any]]:
    q = db.query(AIConversation).filter(AIConversation.student_id == student_id)
    if not include_archived:
        q = q.filter(AIConversation.archived.is_(False))
    rows = q.order_by(AIConversation.last_message_at.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "agent": r.agent,
            "subject_id": r.subject_id,
            "lesson_id": r.lesson_id,
            "message_count": r.message_count,
            "last_message_at": r.last_message_at.isoformat() if r.last_message_at else None,
        }
        for r in rows
    ]


def transcript(db: Session, student_id: str, conversation_id: str) -> dict[str, Any]:
    conversation = db.get(AIConversation, conversation_id)
    if conversation is None or conversation.student_id != student_id:
        raise NotFoundError("المحادثة غير موجودة.")
    return {
        "id": conversation.id,
        "title": conversation.title,
        "subject_id": conversation.subject_id,
        "lesson_id": conversation.lesson_id,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "citations": m.citations or [],
                "confidence": m.confidence,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in conversation.messages
        ],
    }


def archive_conversation(db: Session, student_id: str, conversation_id: str) -> None:
    conversation = db.get(AIConversation, conversation_id)
    if conversation is None or conversation.student_id != student_id:
        raise NotFoundError("المحادثة غير موجودة.")
    conversation.archived = True
    db.flush()


def rename_conversation(db: Session, student_id: str, conversation_id: str, title: str) -> None:
    conversation = db.get(AIConversation, conversation_id)
    if conversation is None or conversation.student_id != student_id:
        raise NotFoundError("المحادثة غير موجودة.")
    conversation.title = (title or "").strip()[:220]
    db.flush()


# --------------------------------------------------------------------------- #
# chat
# --------------------------------------------------------------------------- #
def _is_chitchat(text: str) -> bool:
    return bool(CHITCHAT.match((text or "").strip()))


def _needs_source(mode: str, text: str) -> bool:
    if mode not in SOURCE_BOUND_MODES:
        return False
    return len((text or "").strip()) >= 12 and not _is_chitchat(text)


def _build_context(
    db: Session,
    student_id: str,
    chunks: list[dict[str, Any]],
    *,
    subject_id: str | None,
    lesson_id: str | None,
    page_context: str = "",
) -> dict[str, str]:
    context: dict[str, str] = {}
    profile_block = student_context(db, student_id)
    if profile_block:
        context["طالب"] = profile_block
    lesson_block = lesson_context(db, lesson_id)
    if lesson_block:
        context["الدرس"] = lesson_block
    if chunks:
        context["مصدر"] = "\n".join(c.get("text", "") for c in chunks)
    if page_context:
        context["صفحة الكتاب"] = page_context
    if subject_id:
        subject = db.get(Subject, subject_id)
        if subject:
            context["المادة"] = subject.name_ar
    return context


def chat(
    db: Session,
    student_id: str,
    message: str,
    *,
    conversation_id: str | None = None,
    subject_id: str | None = None,
    lesson_id: str | None = None,
    mode: str = "tutor",
    agent: str = "tutor",
    images: list[str] | None = None,
    book_id: str | None = None,
    page_number: int | None = None,
    selection: str = "",
) -> dict[str, Any]:
    text = (message or "").strip()
    if not text:
        raise ValidationError("اكتب سؤالك أولاً.")
    if len(text) > 4000:
        raise ValidationError("الرسالة طويلة جداً — اختصرها.")

    task = MODE_TO_TASK.get(mode, "explain")
    conversation = get_or_create_conversation(
        db,
        student_id,
        conversation_id=conversation_id,
        subject_id=subject_id,
        lesson_id=lesson_id,
        agent=agent,
        title=_auto_title(text),
    )
    subject_id = subject_id or conversation.subject_id
    lesson_id = lesson_id or conversation.lesson_id

    # the open book page is a first-class source: the student is reading it now
    page_context = ""
    page_citation: dict[str, Any] | None = None
    if book_id:
        from .books import get_page

        page = get_page(db, book_id, page_number or 1, None)
        subject_id = subject_id or page.get("subject_id")
        lesson_id = lesson_id or page.get("lesson_id")
        page_context = f"[{page['citation']}]\n{str(page.get('text') or '')[:4000]}"
        if (selection or "").strip():
            page_context += f"\n\nالمحدد من الطالب:\n{selection.strip()[:1500]}"
        page_citation = {
            "chunk_id": None,
            "source_id": None,
            "citation": page.get("citation", ""),
            "title": page.get("book_title", ""),
            "book": page.get("book_title", ""),
            "chapter": page.get("chapter", ""),
            "lesson": page.get("lesson", ""),
            "page": page.get("page_number"),
            "score": 1.0,
        }

    db.add(
        AIMessage(
            conversation_id=conversation.id,
            role="user",
            content=text,
            agent=agent,
        )
    )
    # Commit before the slow AI call: holding SQLite's write lock for the whole
    # upstream request starves the scheduler ("database is locked"). It also
    # keeps the student's message when the AI call fails.
    db.commit()

    chunks = retrieve(
        db,
        text,
        student_id=student_id,
        subject_id=subject_id,
        lesson_id=lesson_id,
        top_k=settings.rag_top_k,
    )
    needs_source = _needs_source(mode, text)

    if needs_source and not chunks and not page_context:
        reply = NO_SOURCE
        citations: list[dict[str, Any]] = []
        confidence = 0.0
        route_info = route(task, text)
        refused = True
    else:
        history = history_messages(db, conversation.id)
        answer = ask(
            db,
            AIRequest(
                task=task,
                input=text,
                student_id=student_id,
                conversation_id=conversation.id,
                subject_id=subject_id,
                lesson_id=lesson_id,
                context=_build_context(
                    db,
                    student_id,
                    chunks,
                    subject_id=subject_id,
                    lesson_id=lesson_id,
                    page_context=page_context,
                ),
                constraints=(
                    "لا تخترع معلومات منهجية. "
                    "إذا لم تظهر معلومة في السياق، قل إنك لم تجدها. "
                    "اذكر المصدر (الدرس/الصفحة) عند توفره."
                ),
                history=history,
                images=list(images or []),
                max_tokens=1400,
            ),
        )
        reply = answer.text.strip() or "جرّب تعيد صياغة السؤال."
        citations = ([page_citation] if page_citation else []) + citations_from(chunks)
        confidence = answer.confidence
        if needs_source and not citations:
            confidence = min(confidence, 0.4)
        route_info = route(task, text)
        refused = False

    db.add(
        AIMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=reply,
            agent=route_info.agent,
            citations=citations,
            confidence=confidence,
            structured={"refused": refused, "mode": mode},
        )
    )
    conversation.message_count = (conversation.message_count or 0) + 2
    conversation.last_message_at = utcnow()
    if not conversation.title:
        conversation.title = _auto_title(text)
    db.flush()

    ctx = PersonalityContext(
        event=str(EventType.CHAT_MESSAGE),
        subject=conversation.subject_id or "",
        extra={"topic": text[:60]},
    )
    reaction = react_and_persist(db, student_id, ctx, seed=f"chat|{conversation.id}")

    return {
        "conversation_id": conversation.id,
        "reply": reply,
        "citations": citations,
        "confidence": confidence,
        "refused": refused,
        "mode": mode,
        "route": route_info.agent,
        "mors": reaction.as_dict(),
        "needs_source": needs_source,
    }


def ask_for_help(
    db: Session,
    student_id: str,
    *,
    question: str,
    lesson_id: str | None = None,
    subject_id: str | None = None,
) -> dict[str, Any]:
    """Explicit "I'm stuck" button — routes straight to the hint prompt."""
    result = bus.emit(
        db,
        student_id,
        EventType.HELP_REQUESTED,
        {"lesson_id": lesson_id, "subject_id": subject_id, "question": question[:200]},
    )
    hint = chat(
        db,
        student_id,
        question,
        lesson_id=lesson_id,
        subject_id=subject_id,
        mode="hint",
        agent="tutor",
    )
    hint["mors_from_event"] = result.get("results", {}).get("mors", {})
    return hint


def _auto_title(text: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    return clean[:60] + ("…" if len(clean) > 60 else "")


__all__ = [
    "chat",
    "ask_for_help",
    "get_or_create_conversation",
    "list_conversations",
    "transcript",
    "archive_conversation",
    "rename_conversation",
    "NO_SOURCE",
    "MODE_TO_TASK",
    "SOURCE_BOUND_MODES",
]
