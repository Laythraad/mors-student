"""Collects every versioned router under `/api`."""

from __future__ import annotations

from fastapi import APIRouter

from .routes import (
    admin,
    advisor,
    assessment,
    auth,
    books,
    chat,
    curriculum,
    exams,
    inbox,
    library,
    media,
    plan,
    progress,
    reminders,
    study,
    onboarding,
    voice,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(onboarding.router)
api_router.include_router(curriculum.router)
api_router.include_router(books.router)
api_router.include_router(plan.router)
api_router.include_router(study.router)
api_router.include_router(assessment.router)
api_router.include_router(advisor.router)
api_router.include_router(exams.router)
api_router.include_router(chat.router)
api_router.include_router(progress.router)
api_router.include_router(library.router)
api_router.include_router(media.router)
api_router.include_router(inbox.router)
api_router.include_router(reminders.router)
api_router.include_router(admin.router)
api_router.include_router(voice.router)

__all__ = ["api_router"]
