"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import auth, billing, days, moments_router, payments, personas, planner, plans_router
from .generation_worker import run_worker as run_generation_worker
from .user_admin import process_due_user_deletions

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"          

def _resolve_deletion_poll_interval(default: float = 3600.0) -> float | None:
    """Return the background worker interval or ``None`` if disabled."""

    raw = os.getenv("USER_DELETION_POLL_SECONDS")
    if raw is None:
        return default
    try:
        interval = float(raw)
    except ValueError:
        logger.warning(
            "Invalid USER_DELETION_POLL_SECONDS=%r; using default %.0fs", raw, default
        )
        return default
    return interval if interval > 0 else None


app = FastAPI(title="Gemzy Moments BFF")
app.include_router(auth.router)
app.include_router(auth.oauth_router)
# Payments & Plans
app.include_router(payments.router)
app.include_router(plans_router.router)
# Billing & Entitlements
app.include_router(billing.router)
# Gemzy Moments
app.include_router(personas.router)
app.include_router(days.router)
app.include_router(moments_router.router)
app.include_router(planner.router)

_deletion_worker_task: asyncio.Task | None = None
_generation_worker_task: asyncio.Task | None = None


@app.on_event("startup")
async def start_deletion_worker() -> None:
    """Launch a background task that periodically drains the deletion queue."""

    global _deletion_worker_task
    interval = _resolve_deletion_poll_interval()
    if interval is None:
        logger.info("User deletion worker disabled; set USER_DELETION_POLL_SECONDS > 0")
        return

    async def worker() -> None:
        while True:
            try:
                processed = await asyncio.to_thread(process_due_user_deletions)
                if processed:
                    logger.info("Processed %s queued user deletion(s)", processed)
            except asyncio.CancelledError:  # pragma: no cover - task cancellation
                raise
            except Exception:  # pragma: no cover - background best effort logging
                logger.exception("Failed to process queued user deletions")
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:  # pragma: no cover - task cancellation
                raise

    _deletion_worker_task = asyncio.create_task(
        worker(), name="user-deletion-queue-worker"
    )

    # Start generation worker
    global _generation_worker_task
    _generation_worker_task = asyncio.create_task(
        run_generation_worker(), name="generation-worker"
    )
    logger.info("Generation worker background task started")


@app.on_event("shutdown")
async def stop_deletion_worker() -> None:
    """Cancel the background deletion worker when the app stops."""

    global _deletion_worker_task
    if not _deletion_worker_task:
        return
    _deletion_worker_task.cancel()
    with suppress(asyncio.CancelledError):
        await _deletion_worker_task
    _deletion_worker_task = None

    global _generation_worker_task
    if _generation_worker_task:
        _generation_worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await _generation_worker_task
        _generation_worker_task = None
        logger.info("Generation worker stopped")


@app.get("/")
async def root() -> dict:
    """Simple health check endpoint."""
    return {"status": "ok"}

  
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


