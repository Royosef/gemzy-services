"""Webhook dispatch helpers for streaming generation updates."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import httpx

from .models import CallbackEvent, JobMetadata
from .settings import Settings


async def send_event(settings: Settings, job: JobMetadata, event: CallbackEvent) -> None:
    """POST the event payload to the Gemzy application server."""

    payload: Dict[str, Any] = event.model_dump(exclude_none=True)
    headers = {"Content-Type": "application/json"}
    if settings.shared_secret:
        headers["X-Generation-Secret"] = settings.shared_secret

    async with httpx.AsyncClient(timeout=settings.callback_timeout) as client:
        response = await client.post(job.callbackUrl, json=payload, headers=headers)
        response.raise_for_status()


async def safe_send_event(settings: Settings, job: JobMetadata, event: CallbackEvent) -> None:
    """Dispatch an event while swallowing network failures."""

    try:
        await send_event(settings, job, event)
    except Exception as exc:  # pragma: no cover - logged at runtime
        await asyncio.sleep(0)
        print(f"Failed to send generation event for job {job.id}: {exc}")
