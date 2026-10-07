"""Daily coach: one short, useful brief — never a nag.

Rule-first (works with no API key), AI-polished when a provider is
configured. Nudging respects focus mode, quiet hours and a cooldown so the
student never gets spammed.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..ai import AIRequest, ask
from ..db import Notification, StudyStreak, utcnow
from . import notifications as inbox
from .dashboard import recent_results
from .planner import what_now
from .progress import active_weak, progress_report
from .review import due_reviews, review_pressure


def _rule_brief(db: Session, student_id: str) -> dict[str, Any]:
    plan = what_now(db, student_id)
    pressure = review_pressure(db, student_id)
    weak = active_weak(db, student_id, 3)
    streak = db.query(StudyStreak).filter(StudyStreak.student_id == student_id).first()
    recent = recent_results(db, student_id, 3)
    due = len(due_reviews(db, student_id))

    focus = []
    if pressure["overdue"]:
        focus.append(f"{pressure['overdue']} مواضيع متأخرة")
    if weak:
        focus.append(weak[0].topic)
    if due:
        focus.append(f"{due} مراجعات")

    lines: list[str] = []
    if plan.get("available"):
        lines.append(
            f"ابدأ بـ{plan['lesson']['title']} ({plan['duration_minutes']} دقيقة)."
        )
    else:
        lines.append(plan.get("message", "ما عندك مهام حالياً."))
    if due:
        lines.append(f"عندك {due} مراجعات مستحقة اليوم.")
    if recent:
        lines.append(f"آخر نتيجة لك {int(recent[0]['accuracy'])}%.")
    if streak and streak.current:
        lines.append(f"سلسلتك {streak.current} يوم — كمّل.")

    return {
        "headline": lines[0],
        "lines": lines,
        "focus": focus,
        "available": bool(plan.get("available")),
        "next": plan,
        "generated_by": "rules",
    }


def daily_brief(
    db: Session,
    student_id: str,
    *,
    deliver: bool = False,
    use_ai: bool = True,
) -> dict[str, Any]:
    brief = _rule_brief(db, student_id)

    if use_ai:
        report = progress_report(db, student_id)
        try:
            answer = ask(
                db,
                AIRequest(
                    task="coach",
                    input=(
                        f"الساعة {utcnow().strftime('%H:%M')}. "
                        f"النقاط: {brief['focus']}. "
                        f"الخطة: {brief['headline']}"
                    ),
                    student_id=student_id,
                    context={
                        "ملف الطالب": str(report.get("totals", {})),
                        "المواد": str([s["name_ar"] for s in report.get("subjects", [])]),
                    },
                    constraints="ثلاث نقاط كحد أقصى، بدون لوم، وبخطوة واحدة واضحة.",
                    want_json=True,
                    max_tokens=500,
                    cache=True,
                ),
            )
            data = answer.data or {}
            if isinstance(data, dict) and data.get("lines"):
                brief["lines"] = [str(x) for x in data["lines"]][:4]
                brief["headline"] = str(data.get("headline") or brief["headline"])
                brief["focus"] = [str(x) for x in (data.get("focus") or brief["focus"])][:4]
                brief["generated_by"] = "ai"
        except Exception:  # noqa: BLE001 - rules already give a real brief
            pass

    if deliver and inbox.should_nudge(db, student_id):
        db.add(
            Notification(
                student_id=student_id,
                kind="coach",
                title="توجيهات اليوم",
                body="\n".join(brief["lines"]),
                link="/dashboard",
                meta={"event": "daily_brief", "deferred": inbox.focus_mode(db, student_id)},
            )
        )
        db.flush()
        brief["delivered"] = True
    else:
        brief["delivered"] = False
    return brief


def streak_brief(db: Session, student_id: str) -> dict[str, Any]:
    """Called by the daily job: streak intact, broken, or returned."""
    row = db.query(StudyStreak).filter(StudyStreak.student_id == student_id).first()
    if row is None or not row.last_study_day:
        return {"state": "none", "current": 0}
    from datetime import date as _date

    last = _date.fromisoformat(row.last_study_day)
    gap = (utcnow().date() - last).days
    if gap <= 1:
        return {"state": "active", "current": row.current, "longest": row.longest}
    if gap == 2:
        return {"state": "at_risk", "current": row.current, "gap": gap}
    return {"state": "broken", "was": row.current, "gap": gap}


def action_items(db: Session, student_id: str) -> list[dict[str, Any]]:
    """Small, always-available shortcuts the UI can render."""
    items: list[dict[str, Any]] = []
    plan = what_now(db, student_id)
    if plan.get("available"):
        items.append(
            {
                "kind": "study",
                "title": plan["lesson"]["title"],
                "meta": f"{plan['duration_minutes']} دقيقة",
                "link": f"/lesson/{plan['lesson']['id']}",
            }
        )
    due = due_reviews(db, student_id, limit=5)
    if due:
        items.append(
            {
                "kind": "review",
                "title": f"{len(due)} مراجعات مستحقة",
                "meta": "استرجاع نشط",
                "link": "/review",
            }
        )
    last = recent_results(db, student_id, 1)
    if not last:
        items.append(
            {"kind": "quiz", "title": "اختبر نفسك", "meta": "اختبار قصير", "link": "/quiz/new"}
        )
    weak = active_weak(db, student_id, 1)
    if weak:
        items.append(
            {
                "kind": "weak",
                "title": weak[0].topic,
                "meta": "موضوع يحتاج تدريب",
                "link": "/practice",
            }
        )
    return items[:5]


__all__ = ["daily_brief", "streak_brief", "action_items"]
