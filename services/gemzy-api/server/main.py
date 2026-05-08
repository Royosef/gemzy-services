"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import suppress
from pathlib import Path

from fastapi import FastAPI, Request

from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from . import (
    auth,
    dashboard_brain_context,
    content,
    dashboard_coach,
    dashboard_email,
    dashboard_email_advanced,
    dashboard_email_public,
    dashboard_fx,
    dashboard_funnel,
    dashboard_meta,
    dashboard_revenue,
    dashboard_social,
    dashboard_social_sources,
    dashboard_webhooks,
    generations,
    notifications,
    payments,
    plans_router,
    prompt_engines,
)
from .user_admin import process_due_credit_resets, process_due_user_deletions
from .logging_config import setup_logging

import sentry_sdk

sentry_dsn = os.getenv("SENTRY_DSN")
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "1.0")),
    )

setup_logging()
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


from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from .rate_limit import limiter

app = FastAPI(title="Gemzy BFF")

# CORS Configuration
allow_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(auth.router)
app.include_router(auth.oauth_router)
# Content endpoints
app.include_router(content.collections_router)
app.include_router(content.models_router)
# Generation endpoints
app.include_router(generations.router)
app.include_router(payments.router)
app.include_router(notifications.router)
app.include_router(prompt_engines.router)
app.include_router(dashboard_meta.router)
app.include_router(dashboard_coach.router)
app.include_router(dashboard_social.router)
app.include_router(dashboard_social_sources.router)
app.include_router(dashboard_fx.router)
app.include_router(dashboard_revenue.router)
app.include_router(dashboard_brain_context.router)
app.include_router(dashboard_email.router)
app.include_router(dashboard_email_advanced.router)
app.include_router(dashboard_email_public.router)
app.include_router(dashboard_webhooks.router)
app.include_router(dashboard_funnel.router)
app.include_router(dashboard_funnel.coach_stream_router)
# Plans configuration
app.include_router(plans_router.router)

_deletion_worker_task: asyncio.Task | None = None


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

_credit_reset_worker_task: asyncio.Task | None = None

@app.on_event("startup")
async def start_credit_reset_worker() -> None:
    """Launch a background task that periodically checks for due credit resets."""
    global _credit_reset_worker_task
    # Defaulting to 1 hour polling, configure by env if needed
    interval = float(os.getenv("CREDIT_RESET_POLL_SECONDS", "3600.0"))
    
    async def worker() -> None:
        while True:
            try:
                processed = await asyncio.to_thread(process_due_credit_resets)
                if processed:
                    logger.info("Processed %s queued credit reset(s)", processed)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Failed to process due credit resets")
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise

    _credit_reset_worker_task = asyncio.create_task(
        worker(), name="credit-reset-worker"
    )


@app.on_event("shutdown")
async def stop_deletion_worker() -> None:
    """Cancel the background deletion worker when the app stops."""

    global _deletion_worker_task
    if not _deletion_worker_task:
        # Fall through
        pass
    else:
        _deletion_worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await _deletion_worker_task
        _deletion_worker_task = None
        
    global _credit_reset_worker_task
    if not _credit_reset_worker_task:
        return
    _credit_reset_worker_task.cancel()
    with suppress(asyncio.CancelledError):
        await _credit_reset_worker_task
    _credit_reset_worker_task = None


from fastapi import FastAPI, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

class LimitUploadSize(BaseHTTPMiddleware):
    def __init__(self, app, max_upload_size: int) -> None:
        super().__init__(app)
        self.max_upload_size = max_upload_size

    async def dispatch(self, request: Request, call_next):
        if request.method == 'POST':
            if 'content-length' not in request.headers:
                # We can choose to block or allow chunked encoding. 
                # For strictness, often blocking is safer if we expect known sizes.
                # But let's be lenient if missing, or strictly require it?
                # Most clients send it. Let's pass if missing but warn? 
                # Actually, for security, if missing, we can't check size easily without streaming.
                # Let's just check if it EXISTS and is too big.
                pass
            else:
                try:
                    content_length = int(request.headers['content-length'])
                    if content_length > self.max_upload_size:
                        return Response("Request entity too large", status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
                except ValueError:
                    pass
        return await call_next(request)

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    logger.info(f"Request: {request.method} {request.url.path} - Duration: {process_time:.4f}s")
    return response

# Add the Size Limit Middleware (50MB)
app.add_middleware(LimitUploadSize, max_upload_size=50 * 1024 * 1024)

@app.get("/")
async def root() -> dict:
    """Enhanced health check endpoint."""
    db_status = "ok"
    try:
        from .supabase_client import get_client
        # Lightweight check
        get_client().table('profiles').select("id").limit(1).execute()
    except Exception as e:
        db_status = f"error: {str(e)}"
        logger.error(f"Health check failed: {e}")

    return {
        "status": "ok",
        "database": db_status
    }

  
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


