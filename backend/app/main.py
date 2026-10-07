"""FastAPI application factory.

Startup does three things only: create missing tables, register the event
handlers, and (in development) seed demo data. Nothing else runs at import
time, so `import app.main` stays side-effect free for the tests.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .core.errors import AppError, RateLimitError

logger = logging.getLogger(__name__)


def _enforce_production_policy(cfg=None) -> None:
    """Fail closed before a production process starts.

    Anything in `production_blockers()` is a shipped developer default (a
    public signing key, a switched-off rate limiter) — the process must not
    come up at all. `production_warnings()` are leftovers we still boot with,
    but never silently.
    """
    cfg = cfg if cfg is not None else settings
    blockers = cfg.production_blockers()
    if blockers:
        raise RuntimeError(
            "Refusing to start with APP_ENV=production:\n  - " + "\n  - ".join(blockers)
        )
    for warning in cfg.production_warnings():
        logger.warning("production leftover: %s", warning)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .db import init_db
    from .mors.handlers import register_handlers

    init_db()
    register_handlers()

    if settings.demo_data:
        try:
            from .seed import seed_if_empty

            seed_if_empty()
        except ImportError:
            # a release build ships no demo dataset at all (tools/build_release.py)
            logger.warning("DEMO_DATA=true but this build carries no demo dataset")
        except Exception:  # noqa: BLE001 - seeding must never block boot
            logger.exception("demo seed failed")

    from .services import scheduler

    if settings.scheduler_enabled and settings.app_env != "test":
        scheduler.start_scheduler()

    try:
        yield
    finally:
        scheduler.stop_scheduler()


def create_app() -> FastAPI:
    _enforce_production_policy()

    docs_url = f"{settings.api_prefix}/docs" if settings.docs_enabled else None
    openapi_url = f"{settings.api_prefix}/openapi.json" if settings.docs_enabled else None
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description="Mors.ai — مدرّس شخصي للطالب العراقي (Educational Operating System).",
        openapi_url=openapi_url,
        docs_url=docs_url,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RateLimitError)
    async def rate_limit_handler(_: Request, exc: RateLimitError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "حدث خطأ غير متوقع."}},
        )

    from .api import api_router

    app.include_router(api_router, prefix=settings.api_prefix)

    def _health() -> dict[str, object]:
        # the release script reads this: it must be able to see demo mode
        return {
            "status": "ok",
            "env": settings.app_env,
            "provider": settings.ai_provider,
            "demo_data": settings.demo_data,
            "debug": settings.debug,
            "docs": settings.docs_enabled,
        }

    @app.get("/health", tags=["system"])
    def health() -> dict[str, object]:
        return _health()

    @app.get(f"{settings.api_prefix}/health", tags=["system"])
    def api_health() -> dict[str, object]:
        return _health()

    return app


app = create_app()

__all__ = ["create_app", "app"]
