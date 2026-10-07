"""Reusable question bank (spec §34 validation, §77 scale, §78 dedup).

A bank question lives with ``quiz_id IS NULL``. Exam generation draws from
here first, and every generated question that passes validation is registered
back so the bank keeps growing instead of being regenerated each time.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..core.errors import NotFoundError, ValidationError
from ..db import Chapter, Lesson, Option, Question, Subject, utcnow

VALID_TYPES = {"mcq", "true_false", "fill_blank", "short_answer", "problem", "essay", "calculation"}
MAX_PROMPT = 4000

# §10: the label a student sees next to a question's provenance.
SOURCE_LABELS = {
    "official": "مصدر وزاري موثّق",
    "ai": "توليد AI",
    "external": "مدرس",
    "bank": "كتاب",
    "manual": "محتوى المنصة",
}


def provenance(question: Question) -> dict[str, Any]:
    """What the student is told about where a question came from (§10).

    An "official" claim is demoted automatically when its verified link is
    missing — without source_url + checked_at it is never called official.
    """
    kind = str(question.source_kind or "ai")
    url = question.source_url or ""
    checked_at = question.checked_at
    if kind == "official" and not url:
        kind = "bank" if question.source_id else "ai"
        url = ""
        checked_at = None
    return {
        "kind": kind,
        "label": SOURCE_LABELS.get(kind, "محتوى المنصة"),
        "url": url if kind == "official" else "",
        "checked_at": checked_at.isoformat() if checked_at else None,
    }


def parse_checked_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def normalize_prompt(text: str) -> str:
    """Canonical form used for deduplication (spec §78)."""
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"[^\w\u0600-\u06FF]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def dedup_hash(prompt: str) -> str:
    return hashlib.sha256(normalize_prompt(prompt).encode("utf-8")).hexdigest()


def item_from_question(question: Question) -> dict[str, Any]:
    options = sorted(question.options, key=lambda o: o.order)
    answer_index = next((i for i, o in enumerate(options) if o.is_correct), -1)
    return {
        "type": question.type,
        "prompt": question.prompt,
        "options": [o.text for o in options],
        "answer_index": answer_index,
        "explanation": question.explanation,
        "difficulty": question.difficulty,
        "topic": question.topic,
        "subject_id": question.subject_id,
        "lesson_id": question.lesson_id,
        "chapter_id": question.chapter_id,
        "source_kind": question.source_kind,
        "source_id": question.source_id,
        "source_url": question.source_url or "",
        "checked_at": question.checked_at.isoformat() if question.checked_at else None,
        "year": question.year,
        "page": question.page,
    }


def validate_item(
    item: dict[str, Any],
    *,
    db: Session | None = None,
    exclude_id: str | None = None,
) -> list[dict[str, str]]:
    """Spec §34: an invalid question is never shown to a student.

    Returns every issue found; ``severity == "error"`` blocks the question.
    """
    issues: list[dict[str, str]] = []
    prompt = str(item.get("prompt") or "").strip()
    qtype = str(item.get("type") or "mcq")
    options = [str(o) for o in (item.get("options") or [])]
    explanation = str(item.get("explanation") or "").strip()
    source_kind = str(item.get("source_kind") or "ai")

    if len(normalize_prompt(prompt)) < 10:
        issues.append({"code": "prompt_short", "severity": "error", "message": "نص السؤال قصير جداً."})
    if len(prompt) > MAX_PROMPT:
        issues.append({"code": "prompt_long", "severity": "error", "message": "نص السؤال طويل جداً."})
    if qtype not in VALID_TYPES:
        issues.append({"code": "type_invalid", "severity": "error", "message": "نوع السؤال غير مدعوم."})
    if qtype in ("mcq", "true_false"):
        if len(options) < 2:
            issues.append({"code": "options_missing", "severity": "error", "message": "الخيارات أقل من اثنين."})
        else:
            try:
                answer_index = int(item.get("answer_index", -1))
            except (TypeError, ValueError):
                answer_index = -1
            if not 0 <= answer_index < len(options):
                issues.append(
                    {"code": "answer_invalid", "severity": "error", "message": "لا توجد إجابة واحدة صحيحة."}
                )
            elif not str(options[answer_index]).strip():
                issues.append({"code": "answer_empty", "severity": "error", "message": "الإجابة الصحيحة فارغة."})
        if len(set(options)) != len(options):
            issues.append({"code": "options_duplicate", "severity": "error", "message": "الخيارات مكرّرة."})

    try:
        difficulty = int(item.get("difficulty", 3) or 3)
    except (TypeError, ValueError):
        difficulty = -1
    if not 1 <= difficulty <= 5:
        issues.append({"code": "difficulty_invalid", "severity": "error", "message": "الصعوبة خارج 1..5."})

    if source_kind == "official" and not item.get("source_id"):
        issues.append(
            {"code": "source_missing", "severity": "error", "message": "سؤال رسمي بلا مصدر — لا يُنشر."}
        )
    if source_kind == "official":
        # §10: no verified link, no "official" label.
        url = str(item.get("source_url") or "").strip()
        if not url:
            issues.append(
                {
                    "code": "source_url_missing",
                    "severity": "error",
                    "message": "سؤال رسمي بلا رابط مصدر موثّق — لا يُنشر.",
                }
            )
        elif not url.startswith(("http://", "https://")):
            issues.append(
                {
                    "code": "source_url_invalid",
                    "severity": "error",
                    "message": "رابط مصدر السؤال يجب أن يبدأ بـ http أو https.",
                }
            )
    if not item.get("subject_id") and not item.get("lesson_id"):
        issues.append({"code": "curriculum_link", "severity": "warning", "message": "غير مرتبط بمادة في المنهج."})
    if not explanation:
        issues.append({"code": "explanation_missing", "severity": "warning", "message": "لا يوجد شرح للإجابة."})

    if db is not None and prompt:
        query = db.query(func.count(Question.id)).filter(Question.dedup_hash == dedup_hash(prompt))
        if exclude_id:
            query = query.filter(Question.id != exclude_id)
        if query.scalar():
            issues.append({"code": "duplicate", "severity": "error", "message": "السؤال موجود في البنك مسبقاً."})
    return issues


def has_errors(issues: list[dict[str, str]]) -> bool:
    return any(issue["severity"] == "error" for issue in issues)


def validate_question(db: Session, question: Question) -> dict[str, Any]:
    issues = validate_item(item_from_question(question), db=db, exclude_id=question.id)
    return {"id": question.id, "valid": not has_errors(issues), "issues": issues, "status": question.status}


def add_question(db: Session, payload: dict[str, Any], *, status: str = "validated") -> Question:
    """Bank entry point — rejects anything that fails §34."""
    item = dict(payload)
    item["subject_id"] = item.get("subject_id") or None
    item["lesson_id"] = item.get("lesson_id") or None
    item["chapter_id"] = item.get("chapter_id") or None
    issues = validate_item(item, db=db)
    if has_errors(issues):
        raise ValidationError(
            "السؤال لا يجوز التحقق: " + " ".join(issue["message"] for issue in issues if issue["severity"] == "error"),
            details=issues,
        )
    question = _persist(db, item, status=status)
    db.add(question)
    db.flush()
    return question


def register_generated(
    db: Session,
    item: dict[str, Any],
    *,
    status: str = "published",
) -> Question | None:
    """Return a bank copy of a generated question, or None when it is a
    duplicate / fails validation (then the exam simply moves on)."""
    subject_id = item.get("subject_id")
    lesson_id = item.get("lesson_id")
    issues = validate_item(item, db=db)
    if has_errors(issues):
        return None
    question = _persist(db, item, status=status)
    question.subject_id = subject_id
    question.lesson_id = lesson_id
    question.chapter_id = item.get("chapter_id")
    db.add(question)
    db.flush()
    return question


def _persist(db: Session, item: dict[str, Any], *, status: str) -> Question:
    prompt = str(item.get("prompt", "")).strip()
    options = [str(o) for o in (item.get("options") or [])]
    try:
        answer_index = int(item.get("answer_index", -1))
    except (TypeError, ValueError):
        answer_index = -1
    source_kind = str(item.get("source_kind") or "ai")
    checked_at = parse_checked_at(item.get("checked_at"))
    if source_kind == "official" and checked_at is None:
        checked_at = utcnow()
    question = Question(
        quiz_id=None,
        type=str(item.get("type") or "mcq"),
        prompt=prompt,
        explanation=str(item.get("explanation") or ""),
        difficulty=max(1, min(5, int(item.get("difficulty", 3) or 3))),
        topic=str(item.get("topic") or ""),
        source_kind=source_kind,
        source_id=item.get("source_id"),
        source_url=str(item.get("source_url") or "").strip(),
        checked_at=checked_at,
        subject_id=item.get("subject_id"),
        chapter_id=item.get("chapter_id"),
        lesson_id=item.get("lesson_id"),
        year=str(item.get("year") or ""),
        page=item.get("page"),
        status=status,
        dedup_hash=dedup_hash(prompt),
        answer_key=str(answer_index) if answer_index >= 0 else str(item.get("answer_key") or ""),
        meta={"local": bool(item.get("local"))},
    )
    if item.get("type") in ("mcq", "true_false"):
        for index, text in enumerate(options):
            question.options.append(
                Option(
                    text=text,
                    is_correct=index == answer_index,
                    order=index,
                )
            )
    else:
        question.answer_key = str(item.get("answer_key") or (options[answer_index] if 0 <= answer_index < len(options) else ""))
    db.flush()
    return question


def publish(db: Session, question_id: str) -> dict[str, Any]:
    question = db.get(Question, question_id)
    if question is None or question.quiz_id is not None:
        raise NotFoundError("السؤال غير موجود في البنك.")
    result = validate_question(db, question)
    if not result["valid"]:
        raise ValidationError("السؤال لا يجوز التحقق — راجع التقرير.", details=result["issues"])
    question.status = "published"
    db.flush()
    return result | {"status": question.status}


def list_questions(
    db: Session,
    *,
    subject_id: str | None = None,
    chapter_id: str | None = None,
    lesson_id: str | None = None,
    difficulty: int | None = None,
    source_kind: str | None = None,
    status: str | None = None,
    year: str | None = None,
    q: str = "",
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    query = db.query(Question).filter(Question.quiz_id.is_(None))
    if subject_id:
        query = query.filter(Question.subject_id == subject_id)
    if chapter_id:
        query = query.filter(Question.chapter_id == chapter_id)
    if lesson_id:
        query = query.filter(Question.lesson_id == lesson_id)
    if difficulty:
        query = query.filter(Question.difficulty == difficulty)
    if source_kind:
        query = query.filter(Question.source_kind == source_kind)
    if status:
        query = query.filter(Question.status == status)
    if year:
        query = query.filter(Question.year == year)
    if q.strip():
        needle = f"%{q.strip()}%"
        query = query.filter(or_(Question.prompt.like(needle), Question.topic.like(needle)))
    total = query.count()
    rows = query.order_by(Question.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": row.id,
                "type": row.type,
                "prompt": row.prompt,
                "explanation": row.explanation,
                "difficulty": row.difficulty,
                "topic": row.topic,
                "source_kind": row.source_kind,
                "source_url": row.source_url or "",
                "checked_at": row.checked_at.isoformat() if row.checked_at else None,
                "subject_id": row.subject_id,
                "lesson_id": row.lesson_id,
                "chapter_id": row.chapter_id,
                "year": row.year,
                "page": row.page,
                "status": row.status,
                "options": [o.text for o in sorted(row.options, key=lambda o: o.order)],
            }
            for row in rows
        ],
    }


def bank_stats(db: Session) -> dict[str, Any]:
    total = db.query(func.count(Question.id)).filter(Question.quiz_id.is_(None)).scalar() or 0
    published = (
        db.query(func.count(Question.id))
        .filter(Question.quiz_id.is_(None), Question.status == "published")
        .scalar()
        or 0
    )
    by_source = dict(
        db.query(Question.source_kind, func.count(Question.id))
        .filter(Question.quiz_id.is_(None))
        .group_by(Question.source_kind)
        .all()
    )
    by_subject = dict(
        db.query(Question.subject_id, func.count(Question.id))
        .filter(Question.quiz_id.is_(None))
        .group_by(Question.subject_id)
        .all()
    )
    return {
        "total": total,
        "published": published,
        "by_source": by_source,
        "by_subject": {str(k): v for k, v in by_subject.items() if k},
    }


__all__ = [
    "add_question",
    "bank_stats",
    "dedup_hash",
    "has_errors",
    "item_from_question",
    "list_questions",
    "normalize_prompt",
    "publish",
    "register_generated",
    "validate_item",
    "validate_question",
]
