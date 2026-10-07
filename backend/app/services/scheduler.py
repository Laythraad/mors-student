"""Background jobs — spec §121/§126/§132 (Scheduling).

A small, durable scheduler: every job declares its interval, executions are
persisted as `SchedulerRun` rows (so schedules survive restarts), and a daemon
thread ticks every `scheduler_interval_seconds` to run whatever is due.
Jobs can always be run on demand through `POST /api/admin/scheduler/{job}/run`.
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..core.errors import NotFoundError
from ..db import RateLimitCounter, SchedulerRun, StudySession, SessionLocal, utcnow
from . import publishing

logger = logging.getLogger(__name__)

STALE_SESSION_HOURS = 12


def job_publish_due_content(db: Session) -> dict[str, Any]:
    """Auto-publish scheduled content drafts (§83 scheduled publishing)."""
    return publishing.run_due_publications(db)


def job_close_stale_sessions(db: Session) -> dict[str, Any]:
    """Close study sessions abandoned >12h (no fabricated feedback)."""
    cutoff = utcnow() - timedelta(hours=STALE_SESSION_HOURS)
    rows = (
        db.query(StudySession)
        .filter(StudySession.status == "active", StudySession.updated_at < cutoff)
        .limit(1000)
        .all()
    )
    now = utcnow()
    for session in rows:
        if not session.elapsed_seconds:
            started = session.started_at or now
            session.elapsed_seconds = int(max(0, (now - started).total_seconds()))
        session.status = "interrupted"
        session.ended_at = session.ended_at or now
        session.meta = {**(session.meta or {}), "closed_by": "scheduler"}
    db.flush()
    return {"closed": len(rows)}


def job_prune_rate_counters(db: Session) -> dict[str, Any]:
    """Drop rate-limit windows older than a day (housekeeping)."""
    cutoff = utcnow() - timedelta(days=1)
    deleted = (
        db.query(RateLimitCounter)
        .filter(RateLimitCounter.window_start < cutoff)
        .delete(synchronize_session=False)
    )
    return {"deleted": int(deleted or 0)}


JOBS: dict[str, dict[str, Any]] = {
    "publish_due_content": {
        "fn": job_publish_due_content,
        "interval": 60,
        "description": "ينشر المسودات المجدولة التي حان وقتها.",
    },
    "close_stale_sessions": {
        "fn": job_close_stale_sessions,
        "interval": 1800,
        "description": "يغلق جلسات الدراسة المعلقة منذ أكثر من 12 ساعة.",
    },
    "prune_rate_counters": {
        "fn": job_prune_rate_counters,
        "interval": 3600,
        "description": "ينظف عدادات حد الطلبات القديمة.",
    },
}


def run_job(db: Session, name: str) -> dict[str, Any]:
    spec = JOBS.get(name)
    if spec is None:
        raise NotFoundError("المهمة غير موجودة.")
    started = utcnow()
    status, detail, error = "ok", {}, ""
    try:
        result = spec["fn"](db)
        detail = result if isinstance(result, dict) else {}
        # Commit job work separately: a later audit-row failure (DB busy)
        # must never discard what the job already did.
        db.commit()
    except Exception as exc:  # noqa: BLE001 — a job failure must never crash the app
        logger.exception("background job %s failed", name)
        db.rollback()
        status, error = "error", str(exc)[:500]
    try:
        run = SchedulerRun(job=name, status=status, started_at=started, detail=detail, error=error)
        db.add(run)
        db.commit()
    except Exception as exc:  # noqa: BLE001 — audit row is optional; skip if DB is busy
        logger.warning("scheduler run record skipped for %s: %s", name, str(exc)[:200])
        db.rollback()
    return {
        "job": name,
        "status": status,
        "detail": detail,
        "error": error,
        "ran_at": started.isoformat(),
    }


def _last_run(db: Session, name: str) -> SchedulerRun | None:
    return (
        db.query(SchedulerRun)
        .filter(SchedulerRun.job == name)
        .order_by(SchedulerRun.started_at.desc())
        .first()
    )


def jobs_status(db: Session) -> list[dict[str, Any]]:
    rows = []
    for name, spec in JOBS.items():
        last = _last_run(db, name)
        rows.append(
            {
                "name": name,
                "description": spec["description"],
                "interval_seconds": spec["interval"],
                "enabled": settings.scheduler_enabled,
                "last_run_at": last.started_at.isoformat() if last else None,
                "last_status": last.status if last else None,
                "last_detail": last.detail if last else None,
                "last_error": last.error if last else None,
            }
        )
    return rows


def run_due_jobs(db: Session) -> list[dict[str, Any]]:
    """Run every job whose interval has elapsed since its last execution."""
    now = utcnow()
    ran: list[dict[str, Any]] = []
    for name, spec in JOBS.items():
        last = _last_run(db, name)
        if last is None or (now - last.started_at).total_seconds() >= spec["interval"]:
            ran.append(run_job(db, name))
    return ran


# --------------------------------------------------------------------------- #
# daemon thread
# --------------------------------------------------------------------------- #
_stop = threading.Event()
_thread: threading.Thread | None = None


def _loop() -> None:
    while not _stop.wait(settings.scheduler_interval_seconds):
        if not settings.scheduler_enabled:
            continue
        db = SessionLocal()
        try:
            run_due_jobs(db)
            db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("scheduler tick failed")
            db.rollback()
        finally:
            db.close()


def start_scheduler() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="mors-scheduler", daemon=True)
    _thread.start()
    logger.info("scheduler started (interval=%ss)", settings.scheduler_interval_seconds)


def stop_scheduler() -> None:
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=5)


__all__ = [
    "JOBS",
    "run_job",
    "jobs_status",
    "run_due_jobs",
    "start_scheduler",
    "stop_scheduler",
    "job_publish_due_content",
    "job_close_stale_sessions",
    "job_prune_rate_counters",
]
