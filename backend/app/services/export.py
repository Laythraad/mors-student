"""Exports: JSON, iCal and a printable PDF of the student's progress.

The PDF must render Arabic properly, so it reshapes + bidi-reorders the text
and registers a system font. If no Arabic-capable font is found we still
return a PDF rather than failing the request.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..db import CalendarEvent, StudentProfile, utcnow
from .dashboard import home, weekly_summary
from .planner import plan_payload
from .progress import progress_report
from .review import due_reviews

ARABIC_FONTS = (
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
    "C:/Windows/Fonts/segoeuia.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def progress_json(db: Session, student_id: str) -> dict[str, Any]:
    profile = db.get(StudentProfile, student_id)
    plans = []
    from ..db import StudyPlan

    for plan in (
        db.query(StudyPlan)
        .filter(StudyPlan.student_id == student_id, StudyPlan.is_active.is_(True))
        .order_by(StudyPlan.created_at.desc())
        .limit(3)
        .all()
    ):
        plans.append(plan_payload(plan))

    return {
        "generated_at": utcnow().isoformat(),
        "student": {
            "id": student_id,
            "name": profile.user.full_name if profile and profile.user else "",
            "stage_id": profile.stage_id if profile else None,
            "onboarding_step": profile.onboarding_step if profile else 0,
        },
        "dashboard": home(db, student_id),
        "progress": progress_report(db, student_id),
        "week": weekly_summary(db, student_id),
        "plans": plans,
        "reviews_due": due_reviews(db, student_id, limit=30),
    }


def plan_ics(db: Session, student_id: str) -> str:
    """iCal feed of study tasks — imports into Google/Apple calendar."""
    from datetime import datetime

    rows = (
        db.query(CalendarEvent)
        .filter(CalendarEvent.student_id == student_id)
        .order_by(CalendarEvent.start_at)
        .limit(500)
        .all()
    )
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Mors.ai//AR//EN",
        "CALSCALE:GREGORIAN",
    ]
    for event in rows:
        start = event.start_at
        end = event.end_at or (start + timedelta(minutes=30))
        if start is None:
            continue
        if start.tzinfo is None:
            from ..db import utcnow as _utcnow

            start = start.replace(tzinfo=_utcnow().tzinfo)
        if end.tzinfo is None:
            from ..db import utcnow as _utcnow

            end = end.replace(tzinfo=_utcnow().tzinfo)
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{event.id}@mors.ai",
                f"DTSTAMP:{_ics(utcnow())}",
                f"DTSTART:{_ics(start)}",
                f"DTEND:{_ics(end)}",
                f"SUMMARY:{_escape(event.title)}",
                f"DESCRIPTION:{_escape(event.kind)}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


def _ics(value) -> str:
    from datetime import timezone

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
def _arabic(text: str) -> str:
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        return get_display(arabic_reshaper.reshape(text or ""))
    except Exception:  # noqa: BLE001 - font/reshaper optional
        return text or ""


def _register_font() -> str:
    from pathlib import Path

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for candidate in ARABIC_FONTS:
        if Path(candidate).exists():
            try:
                pdfmetrics.registerFont(TTFont("MorsArabic", candidate))
                return "MorsArabic"
            except Exception:  # noqa: BLE001
                continue
    return "Helvetica"


def progress_pdf(db: Session, student_id: str) -> bytes:
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    data = progress_json(db, student_id)
    font = _register_font()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title="Mors.ai — تقرير التقدم",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ArTitle", parent=styles["Title"], fontName=font, fontSize=18, leading=24, alignment=2
    )
    body_style = ParagraphStyle(
        "ArBody", parent=styles["BodyText"], fontName=font, fontSize=11, leading=18, alignment=2
    )
    small_style = ParagraphStyle(
        "ArSmall", parent=styles["BodyText"], fontName=font, fontSize=9, leading=14, alignment=2
    )

    story = [
        Paragraph(_arabic("تقرير التقدم — Mors.ai"), title_style),
        Spacer(1, 0.3 * cm),
        Paragraph(
            _arabic(
                f"الطالب: {data['student']['name'] or '—'}  |  "
                f"تاريخ التقرير: {utcnow().strftime('%Y-%m-%d')}"
            ),
            body_style,
        ),
        Spacer(1, 0.4 * cm),
    ]

    totals = data["progress"].get("totals", {})
    rows = [
        [_arabic("المؤشر"), _arabic("القيمة")],
        [_arabic("جلسات الدراسة"), str(totals.get("sessions", 0))],
        [_arabic("مجموع الدقائق"), str(totals.get("study_minutes", 0))],
        [_arabic("دقائق الأسبوع"), str(totals.get("week_minutes", 0))],
        [_arabic("السلسلة الحالية"), str(data["dashboard"]["streak"]["current"])],
        [_arabic("متوسط الدقة"), str(data["week"].get("average_accuracy") or "—")],
    ]
    table = Table(rows, colWidths=[6 * cm, 5 * cm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2f8ff7")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d7e3f2")),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.5 * cm))

    subjects = data["progress"].get("subjects", [])
    if subjects:
        story.append(Paragraph(_arabic("المواد"), body_style))
        for subject in subjects:
            mastery = subject.get("mastery")
            story.append(
                Paragraph(
                    _arabic(
                        f"• {subject['name_ar']}: {subject['minutes']} دقيقة، "
                        f"الإتقان {mastery if mastery is not None else '—'}"
                    ),
                    small_style,
                )
            )
        story.append(Spacer(1, 0.4 * cm))

    weak = data["progress"].get("weak_topics", [])
    if weak:
        story.append(Paragraph(_arabic("مواضيع تحتاج تركيزاً"), body_style))
        for item in weak[:8]:
            story.append(
                Paragraph(_arabic(f"• {item['topic']} (severity {item['severity']})"), small_style)
            )
    else:
        story.append(Paragraph(_arabic("ما عندك مواضيع ضعيفة حالياً."), body_style))

    doc.build(story)
    return buffer.getvalue()


__all__ = ["progress_json", "plan_ics", "progress_pdf"]
