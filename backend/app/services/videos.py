"""Video catalogue, course progress, watch progress and transcript search.

Completion is decided by watched time (§38), never by opening the player, and
a short post-video quiz (§40) is what actually closes the lesson. Every video
keeps its resume point (§39) and students can report broken media (§84–§85)
into the content review queue.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..core.errors import NotFoundError, ValidationError
from ..db import (
    Chapter,
    ContentReport,
    Course,
    Lesson,
    Quiz,
    QuizAttempt,
    StudentProfile,
    Subject,
    Teacher,
    User,
    Video,
    VideoProgress,
    utcnow,
)
from ..mors import EventType, bus
from . import assessment

COMPLETION_RATIO = 0.9
VIDEO_QUIZ_PASS = 60.0

# §36 — only the official YouTube embed plays in-app; we never download or
# re-host. A URL that doesn't resolve to a video id is not playable at all.
_YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/)|youtu\.be/)"
    r"([\w-]{11})"
)


def youtube_id(url: str | None) -> str:
    """Return the 11-char YouTube video id for `url`, or "" if it isn't one."""
    if not url:
        return ""
    match = _YOUTUBE_RE.search(url.strip())
    return match.group(1) if match else ""

STATE_LABELS = {
    "new": "غير مبدأ",
    "started": "بدأ",
    "watched": "شاهدته",
    "quiz_failed": "اجتز الاختبار",
    "completed": "مكتمل",
}


# --------------------------------------------------------------------------- #
# teachers / courses / videos
# --------------------------------------------------------------------------- #
def list_teachers(db: Session, *, subject_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    # Verified official links and explicit "search suggestion" entries only —
    # never guessed or half-checked channels.
    query = db.query(Teacher).filter(
        or_(Teacher.verified.is_(True), Teacher.link_status == "search")
    )
    rows = query.order_by(Teacher.rating.desc()).limit(limit).all()
    if subject_id:
        rows = [r for r in rows if not r.subjects or subject_id in (r.subjects or [])]
    return [
        {
            "id": r.id,
            "name": r.name,
            "headline": r.headline,
            "style": r.style,
            "avatar_path": r.avatar_path,
            "rating": r.rating,
            "rating_count": r.rating_count,
            "lessons_count": r.lessons_count,
            "duration_minutes": r.duration_minutes,
            "subjects": r.subjects or [],
            "stages": r.stages or [],
            "level": r.level,
            "verified": r.verified,
            "is_demo": r.is_demo,
            "has_summaries": r.has_summaries,
            "has_tests": r.has_tests,
            "channel_url": r.channel_url or "",
            "link_status": r.link_status or "none",
            "verified_at": r.verified_at.isoformat() if r.verified_at else None,
            "search_url": f"https://www.youtube.com/results?search_query={quote(r.name)}",
        }
        for r in rows
    ]


def _progress_map(db: Session, student_id: str, video_ids: list[str]) -> dict[str, VideoProgress]:
    if not video_ids:
        return {}
    rows = (
        db.query(VideoProgress)
        .filter(
            VideoProgress.student_id == student_id,
            VideoProgress.video_id.in_(video_ids),
        )
        .all()
    )
    return {row.video_id: row for row in rows}


def _video_credit(progress: VideoProgress | None, duration: int) -> float:
    """§86 weight: quiz-passed = 1, watched = 0.9, partial = proportional."""
    if progress is None:
        return 0.0
    if progress.completed and progress.quiz_score is not None and progress.quiz_score >= VIDEO_QUIZ_PASS:
        return 1.0
    if progress.completed:
        return 0.9
    if duration and progress.watched_seconds:
        return min(0.5, progress.watched_seconds / duration * 0.5)
    return 0.0


def list_courses(
    db: Session,
    student_id: str | None = None,
    *,
    subject_id: str | None = None,
    stage_id: str | None = None,
    limit: int = 40,
) -> list[dict[str, Any]]:
    q = db.query(Course)
    if subject_id:
        q = q.filter(Course.subject_id == subject_id)
    if stage_id:
        q = q.filter(Course.stage_id == stage_id)
    rows = q.order_by(Course.title).limit(limit).all()
    out: list[dict[str, Any]] = []
    for row in rows:
        videos = list(row.videos)
        teacher = db.get(Teacher, row.teacher_id) if row.teacher_id else None
        subject = db.get(Subject, row.subject_id) if row.subject_id else None
        percent = None
        if student_id:
            progress = _progress_map(db, student_id, [v.id for v in videos])
            percent = (
                round(sum(_video_credit(progress.get(v.id), v.duration_seconds) for v in videos) / len(videos) * 100, 1)
                if videos
                else 0.0
            )
        out.append(
            {
                "id": row.id,
                "title": row.title,
                "description": row.description,
                "level": row.level,
                "cover_path": row.cover_path,
                "subject_id": row.subject_id,
                "subject": subject.name_ar if subject else "",
                "teacher": teacher.name if teacher else "",
                "teacher_id": row.teacher_id,
                "video_count": len(videos),
                "duration_minutes": round(sum(v.duration_seconds for v in videos) / 60),
                "progress_percent": percent,
            }
        )
    return out


def list_videos(
    db: Session,
    student_id: str,
    *,
    course_id: str | None = None,
    subject_id: str | None = None,
    lesson_id: str | None = None,
    query: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    q = db.query(Video)
    if course_id:
        q = q.filter(Video.course_id == course_id)
    if subject_id:
        q = q.filter(Video.subject_id == subject_id)
    if lesson_id:
        q = q.filter(Video.lesson_id == lesson_id)
    if query:
        like = f"%{query.strip()}%"
        q = q.filter(or_(Video.title.like(like), Video.description.like(like)))
    rows = q.order_by(Video.position).limit(limit).all()
    progress = _progress_map(db, student_id, [r.id for r in rows])
    return [video_payload(r, progress.get(r.id)) for r in rows]


def get_video(db: Session, student_id: str, video_id: str) -> dict[str, Any]:
    row = db.get(Video, video_id)
    if row is None:
        raise NotFoundError("الفيديو غير موجود.")
    progress = (
        db.query(VideoProgress)
        .filter(VideoProgress.student_id == student_id, VideoProgress.video_id == video_id)
        .first()
    )
    data = video_payload(row, progress, with_transcript=True)
    data["course"] = (
        {"id": row.course.id, "title": row.course.title} if row.course else None
    )
    if row.lesson_id:
        lesson = db.get(Lesson, row.lesson_id)
        data["lesson"] = {"id": row.lesson_id, "title": lesson.title if lesson else ""}
    else:
        data["lesson"] = None
    neighbours = _neighbours(db, row)
    data.update(neighbours)
    return data


def _neighbours(db: Session, row: Video) -> dict[str, Any]:
    siblings = (
        db.query(Video)
        .filter(Video.course_id == row.course_id)
        .order_by(Video.position, Video.title)
        .all()
        if row.course_id
        else [row]
    )
    ids = [v.id for v in siblings]
    index = ids.index(row.id) if row.id in ids else 0
    previous = siblings[index - 1] if index > 0 else None
    following = siblings[index + 1] if index + 1 < len(siblings) else None
    return {
        "prev": {"id": previous.id, "title": previous.title} if previous else None,
        "next": {"id": following.id, "title": following.title} if following else None,
    }


def _state(progress: VideoProgress | None) -> str:
    """§38 states: started → watched → completed / quiz_failed."""
    if progress is None:
        return "new"
    if progress.quiz_score is not None:
        if progress.quiz_score >= VIDEO_QUIZ_PASS and progress.completed:
            return "completed"
        return "quiz_failed"
    if progress.completed:
        return "watched"
    if progress.watched_seconds or progress.last_position:
        return "started"
    return "new"


def video_payload(
    row: Video, progress: VideoProgress | None = None, *, with_transcript: bool = False
) -> dict[str, Any]:
    watched = progress.watched_seconds if progress else 0
    duration = row.duration_seconds or 0
    state = _state(progress)
    yt_id = youtube_id(row.url)
    # §36: either the official YouTube embed, or a file we already host
    # ourselves. Anything else cannot play in this player and must say so.
    hosted = bool(row.url) and row.url.startswith("/")
    return {
        "id": row.id,
        "title": row.title,
        "url": row.url,
        "youtube_id": yt_id,
        "playable": bool(yt_id) or hosted,
        "description": row.description,
        "duration_seconds": duration,
        "thumbnail_path": row.thumbnail_path,
        "subject_id": row.subject_id,
        "lesson_id": row.lesson_id,
        "course_id": row.course_id,
        "transcript": (row.transcript or "") if with_transcript else "",
        "status": state,
        "status_label": STATE_LABELS[state],
        "progress": {
            "watched_seconds": watched,
            "last_position": progress.last_position if progress else 0,
            "completed": bool(progress and progress.completed),
            "quiz_passed": state == "completed",
            "quiz_score": progress.quiz_score if progress and progress.quiz_score is not None else None,
            "percent": round(min(100.0, watched / duration * 100), 1) if duration else 0.0,
            "key_idea": progress.key_idea if progress else "",
        },
    }


# --------------------------------------------------------------------------- #
# §37/§86 — course → module → lesson → video progress
# --------------------------------------------------------------------------- #
def course_progress(db: Session, student_id: str, course_id: str) -> dict[str, Any]:
    course = db.get(Course, course_id)
    if course is None:
        raise NotFoundError("الكورس غير موجود.")
    rows = (
        db.query(Video)
        .filter(Video.course_id == course_id)
        .order_by(Video.position, Video.title)
        .all()
    )
    progress = _progress_map(db, student_id, [r.id for r in rows])

    modules: dict[str, dict[str, Any]] = {}
    lessons: dict[str, dict[str, Any]] = {}
    credits: list[float] = []

    for video in rows:
        item = video_payload(video, progress.get(video.id))
        credit = _video_credit(progress.get(video.id), video.duration_seconds)
        credits.append(credit)

        key = video.chapter_id or video.lesson_id or "all"
        module = modules.get(key)
        if module is None:
            module = _module_header(db, key, has_chapter=bool(video.chapter_id))
            modules[key] = module
        module["videos"].append(item)
        module["credit"] += credit
        _bump(module, item["status"])

        if video.lesson_id:
            lesson = lessons.get(video.lesson_id)
            if lesson is None:
                row = db.get(Lesson, video.lesson_id)
                lesson = {
                    "lesson_id": video.lesson_id,
                    "title": row.title if row else "",
                    "videos": 0,
                    "states": [],
                }
                lessons[video.lesson_id] = lesson
            lesson["videos"] += 1
            lesson["states"].append(item["status"])

    module_list = []
    for module in modules.values():
        total = len(module.pop("videos"))
        module["total"] = total
        module["percent"] = round(module.pop("credit") / total * 100, 1) if total else 0.0
        module_list.append(module)

    state_order = ["new", "started", "watched", "quiz_failed", "completed"]
    lesson_list = []
    for lesson in lessons.values():
        states = lesson.pop("states")
        best = max(states, key=lambda s: state_order.index(s))
        lesson["status"] = best
        lesson["status_label"] = STATE_LABELS[best]
        lesson_list.append(lesson)

    percent = round(sum(credits) / len(credits) * 100, 1) if rows else 0.0
    teacher = db.get(Teacher, course.teacher_id) if course.teacher_id else None
    subject = db.get(Subject, course.subject_id) if course.subject_id else None
    return {
        "id": course.id,
        "title": course.title,
        "description": course.description,
        "subject": subject.name_ar if subject else "",
        "teacher": teacher.name if teacher else "",
        "progress_percent": percent,
        "video_total": len(rows),
        "watched": sum(1 for p in progress.values() if p.completed),
        "quiz_passed": sum(
            1
            for p in progress.values()
            if p.completed and p.quiz_score is not None and p.quiz_score >= VIDEO_QUIZ_PASS
        ),
        "modules": module_list,
        "lessons": lesson_list,
        "videos": [video_payload(r, progress.get(r.id)) for r in rows],
    }


def _module_header(db: Session, key: str, *, has_chapter: bool) -> dict[str, Any]:
    title = "دروس الكورس"
    if has_chapter:
        chapter = db.get(Chapter, key)
        title = chapter.title if chapter else title
    elif key != "all":
        lesson = db.get(Lesson, key)
        title = lesson.title if lesson else title
    return {
        "key": key,
        "title": title,
        "videos": [],
        "credit": 0.0,
        "started": 0,
        "watched": 0,
        "completed": 0,
        "quiz_failed": 0,
    }


def _bump(module: dict[str, Any], state: str) -> None:
    if state == "started":
        module["started"] += 1
    elif state == "watched":
        module["watched"] += 1
    elif state == "completed":
        module["completed"] += 1
    elif state == "quiz_failed":
        module["quiz_failed"] += 1


# --------------------------------------------------------------------------- #
# §39 — continue watching
# --------------------------------------------------------------------------- #
def continue_watching(db: Session, student_id: str) -> dict[str, Any] | None:
    row = (
        db.query(VideoProgress)
        .filter(VideoProgress.student_id == student_id)
        .order_by(VideoProgress.updated_at.desc())
        .first()
    )
    if row is None:
        return None
    video = db.get(Video, row.video_id)
    if video is None:
        return None
    data = video_payload(video, row)
    data["link"] = f"/videos/{video.id}"
    data["resume_from"] = row.last_position
    if video.course_id:
        course = db.get(Course, video.course_id)
        data["course"] = {"id": course.id, "title": course.title} if course else None
    else:
        data["course"] = None
    return data


# --------------------------------------------------------------------------- #
# watch progress (§38/§39)
# --------------------------------------------------------------------------- #
def report_progress(
    db: Session,
    student_id: str,
    video_id: str,
    *,
    position: int,
    watched_seconds: int,
    key_idea: str = "",
) -> dict[str, Any]:
    video = db.get(Video, video_id)
    if video is None:
        raise NotFoundError("الفيديو غير موجود.")

    progress = (
        db.query(VideoProgress)
        .filter(VideoProgress.student_id == student_id, VideoProgress.video_id == video_id)
        .first()
    )
    if progress is None:
        progress = VideoProgress(student_id=student_id, video_id=video_id)
        db.add(progress)

    progress.last_position = max(0, int(position))
    progress.watched_seconds = max(int(watched_seconds), progress.watched_seconds or 0)
    if key_idea:
        progress.key_idea = key_idea[:400]

    duration = video.duration_seconds or 0
    was_completed = bool(progress.completed)
    if duration and progress.watched_seconds >= duration * COMPLETION_RATIO:
        progress.completed = True
    db.flush()

    if progress.completed and not was_completed:
        bus.emit(
            db,
            student_id,
            EventType.VIDEO_COMPLETED,
            {
                "video_id": video.id,
                "lesson_id": video.lesson_id,
                "subject_id": video.subject_id,
                "key_idea": progress.key_idea,
            },
        )
    return video_payload(video, progress)


# --------------------------------------------------------------------------- #
# §40 — after every video: a short quiz decides completion
# --------------------------------------------------------------------------- #
def start_video_quiz(db: Session, student_id: str, video_id: str) -> dict[str, Any]:
    video = db.get(Video, video_id)
    if video is None:
        raise NotFoundError("الفيديو غير موجود.")
    payload = assessment.generate_quiz(
        db,
        student_id,
        lesson_id=video.lesson_id,
        subject_id=video.subject_id,
        title=f"فهم الفيديو — {video.title}",
        kind="quiz",
        count=5,
        difficulty=3,
    )
    quiz = db.get(Quiz, payload["id"])
    meta = dict(quiz.meta or {})
    meta["video_id"] = video.id
    quiz.meta = meta
    db.flush()
    return {
        "quiz_id": payload["id"],
        "video_id": video.id,
        "question_count": payload["question_count"],
        "title": payload["title"],
        "pass_score": VIDEO_QUIZ_PASS,
    }


def record_video_quiz(
    db: Session, student_id: str, video_id: str, attempt_id: str
) -> dict[str, Any]:
    """Grade a finished attempt against the video: pass closes the lesson."""
    video = db.get(Video, video_id)
    if video is None:
        raise NotFoundError("الفيديو غير موجود.")
    attempt = db.get(QuizAttempt, attempt_id)
    if attempt is None or attempt.student_id != student_id:
        raise NotFoundError("المحاولة غير موجودة.")
    if attempt.status != "finished":
        raise ValidationError("أنهِ اختبار الفيديو أولاً.")

    progress = (
        db.query(VideoProgress)
        .filter(VideoProgress.student_id == student_id, VideoProgress.video_id == video_id)
        .first()
    )
    if progress is None:
        progress = VideoProgress(student_id=student_id, video_id=video_id)
        db.add(progress)

    progress.quiz_score = attempt.accuracy
    passed = attempt.accuracy >= VIDEO_QUIZ_PASS
    was_completed = bool(progress.completed)
    if passed:
        progress.completed = True
    db.flush()

    if passed and not was_completed:
        bus.emit(
            db,
            student_id,
            EventType.VIDEO_COMPLETED,
            {
                "video_id": video.id,
                "lesson_id": video.lesson_id,
                "subject_id": video.subject_id,
                "quiz_score": attempt.accuracy,
                "via": "quiz",
            },
        )

    weak = ((attempt.report or {}).get("weak_topics") or []) if attempt.report else []
    message = (
        "أحسنت — درجتك تكفي، الدرس مكتمل."
        if passed
        else f"ما ضلّ — راجع «{weak[0]}» وجرّب مرة ثانية."
        if weak
        else "ما ضلّ — راجع الجزء المرتبط بالموضوع وجرّب مرة ثانية."
    )
    return {
        "passed": passed,
        "score": attempt.accuracy,
        "pass_score": VIDEO_QUIZ_PASS,
        "completed": bool(progress.completed),
        "video_id": video.id,
        "message": message,
    }


# --------------------------------------------------------------------------- #
# §84/§85 — content review queue
# --------------------------------------------------------------------------- #
def report_content(
    db: Session, student_id: str, video_id: str, *, kind: str, detail: str = ""
) -> dict[str, Any]:
    video = db.get(Video, video_id)
    if video is None:
        raise NotFoundError("الفيديو غير موجود.")
    row = ContentReport(
        student_id=student_id,
        video_id=video.id,
        lesson_id=video.lesson_id,
        kind=kind,
        detail=(detail or "").strip()[:500],
    )
    db.add(row)
    db.flush()
    return {
        "report_id": row.id,
        "kind": row.kind,
        "status": row.status,
        "message": "وصلنا البلاغ — يراجعه فريق المحتوى.",
    }


def list_content_reports(
    db: Session, *, status: str | None = None, limit: int = 100
) -> dict[str, Any]:
    q = db.query(ContentReport).order_by(ContentReport.created_at.desc())
    if status:
        q = q.filter(ContentReport.status == status)
    rows = q.limit(limit).all()
    items = []
    for row in rows:
        video = db.get(Video, row.video_id) if row.video_id else None
        profile = db.get(StudentProfile, row.student_id)
        user = profile.user if profile else None
        items.append(
            {
                "id": row.id,
                "kind": row.kind,
                "detail": row.detail,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
                "video": {"id": row.video_id, "title": video.title if video else ""},
                "lesson_id": row.lesson_id,
                "student": user.full_name if user else "",
            }
        )
    return {"reports": items, "open": sum(1 for r in rows if r.status == "open")}


def resolve_content_report(db: Session, report_id: str) -> dict[str, Any]:
    row = db.get(ContentReport, report_id)
    if row is None:
        raise NotFoundError("البلاغ غير موجود.")
    row.status = "resolved"
    row.resolved_at = utcnow()
    db.flush()
    return {"report_id": row.id, "status": row.status}


def search_transcripts(
    db: Session, student_id: str, query: str, *, limit: int = 8
) -> list[dict[str, Any]]:
    like = f"%{(query or '').strip()}%"
    rows = (
        db.query(Video)
        .filter(or_(Video.transcript.like(like), Video.title.like(like)))
        .limit(limit)
        .all()
    )
    out = []
    for row in rows:
        snippet = ""
        text = row.transcript or ""
        index = text.lower().find((query or "").lower())
        if index >= 0:
            snippet = text[max(0, index - 80) : index + 160]
        out.append(
            {
                "id": row.id,
                "title": row.title,
                "snippet": snippet,
                "lesson_id": row.lesson_id,
                "link": f"/videos/{row.id}",
            }
        )
    return out


__all__ = [
    "STATE_LABELS",
    "VIDEO_QUIZ_PASS",
    "continue_watching",
    "course_progress",
    "get_video",
    "list_content_reports",
    "list_courses",
    "list_teachers",
    "list_videos",
    "record_video_quiz",
    "report_content",
    "report_progress",
    "resolve_content_report",
    "search_transcripts",
    "start_video_quiz",
    "video_payload",
]
