"""Search, uploads, videos and teachers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, Query, UploadFile
from pydantic import BaseModel, Field

from ...config import settings
from ...core.deps import CurrentProfile, CurrentUser, DbSession
from ...core.errors import NotFoundError, ValidationError
from ...core.rate_limit import enforce_ai
from ...services import search as search_service
from ...services import upload as upload_service
from ...services import videos as videos_service

router = APIRouter(prefix="/media", tags=["media"])


class VideoProgressIn(BaseModel):
    position: int = Field(default=0, ge=0)
    watched_seconds: int = Field(default=0, ge=0)
    key_idea: str = Field(default="", max_length=400)


class VideoQuizResultIn(BaseModel):
    attempt_id: str


class ContentReportIn(BaseModel):
    kind: str = Field(default="not_working", pattern="^(not_working|not_linked|unclear|other)$")
    detail: str = Field(default="", max_length=500)


@router.get("/search")
def search(
    profile: CurrentProfile,
    db: DbSession,
    q: str = Query("", max_length=200),
    kind: str = Query("all", pattern="^(all|lessons|notes|papers|uploads|videos|sources)$"),
    subject_id: str | None = None,
    limit: int = Query(6, ge=1, le=20),
) -> dict[str, Any]:
    return search_service.global_search(
        db, profile.id, q, kind=kind, subject_id=subject_id, limit=limit
    )


# ------------------------------------------------------------------------ uploads
@router.post("/uploads")
async def upload(
    profile: CurrentProfile,
    user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
    subject_id: str | None = Form(None),
    lesson_id: str | None = Form(None),
    book_id: str | None = Form(None),
    kind: str = Form("document"),
) -> dict[str, Any]:
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise ValidationError(f"حجم الملف يتجاوز {settings.max_upload_mb} ميغابايت.")
    result = upload_service.save_upload(
        db,
        student_id=profile.id,
        uploader_id=user.id,
        filename=file.filename or "file",
        data=data,
        mime=file.content_type or "",
        subject_id=subject_id,
        lesson_id=lesson_id,
        book_id=book_id,
        kind=kind,
    )
    db.commit()
    return result


@router.get("/uploads")
def list_uploads(profile: CurrentProfile, db: DbSession, status: str | None = None) -> dict[str, Any]:
    return {"uploads": upload_service.list_uploads(db, profile.id, status=status)}


@router.get("/uploads/{upload_id}")
def get_upload(upload_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return upload_service.get_upload(db, profile.id, upload_id)


@router.post("/uploads/{upload_id}/reindex")
def reindex(upload_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    result = upload_service.reindex(db, profile.id, upload_id)
    db.commit()
    return result


@router.delete("/uploads/{upload_id}")
def delete_upload(upload_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    upload_service.delete_upload(db, profile.id, upload_id)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------------- videos
@router.get("/teachers")
def teachers(db: DbSession, subject_id: str | None = None) -> dict[str, Any]:
    return {"teachers": videos_service.list_teachers(db, subject_id=subject_id)}


@router.get("/courses")
def courses(
    profile: CurrentProfile,
    db: DbSession,
    subject_id: str | None = None,
    stage_id: str | None = None,
) -> dict[str, Any]:
    return {
        "courses": videos_service.list_courses(
            db, profile.id, subject_id=subject_id, stage_id=stage_id
        )
    }


@router.get("/courses/{course_id}")
def course(course_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return videos_service.course_progress(db, profile.id, course_id)


@router.get("/continue")
def continue_learning(profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return {"video": videos_service.continue_watching(db, profile.id)}


@router.get("/videos")
def videos(
    profile: CurrentProfile,
    db: DbSession,
    course_id: str | None = None,
    subject_id: str | None = None,
    lesson_id: str | None = None,
    q: str = "",
) -> dict[str, Any]:
    return {
        "videos": videos_service.list_videos(
            db,
            profile.id,
            course_id=course_id,
            subject_id=subject_id,
            lesson_id=lesson_id,
            query=q,
        )
    }


@router.get("/videos/{video_id}")
def video(video_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    return videos_service.get_video(db, profile.id, video_id)


@router.post("/videos/{video_id}/progress")
def video_progress(video_id: str, payload: VideoProgressIn, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    result = videos_service.report_progress(
        db,
        profile.id,
        video_id,
        position=payload.position,
        watched_seconds=payload.watched_seconds,
        key_idea=payload.key_idea,
    )
    db.commit()
    return result


@router.post("/videos/{video_id}/quiz")
def video_quiz(video_id: str, profile: CurrentProfile, db: DbSession) -> dict[str, Any]:
    result = videos_service.start_video_quiz(db, profile.id, video_id)
    db.commit()
    return result


@router.post("/videos/{video_id}/quiz-result")
def video_quiz_result(
    video_id: str, payload: VideoQuizResultIn, profile: CurrentProfile, db: DbSession
) -> dict[str, Any]:
    result = videos_service.record_video_quiz(db, profile.id, video_id, payload.attempt_id)
    db.commit()
    return result


@router.post("/videos/{video_id}/report")
def video_report(
    video_id: str, payload: ContentReportIn, profile: CurrentProfile, db: DbSession
) -> dict[str, Any]:
    result = videos_service.report_content(
        db, profile.id, video_id, kind=payload.kind, detail=payload.detail
    )
    db.commit()
    return result


@router.get("/videos-search")
def videos_search(profile: CurrentProfile, db: DbSession, q: str = Query("", max_length=200)) -> dict[str, Any]:
    enforce_ai(profile.id)
    return {"results": videos_service.search_transcripts(db, profile.id, q)}


__all__ = ["router"]
