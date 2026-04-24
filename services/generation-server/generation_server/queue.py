"""Async job queue management for generation requests."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from .models import GenerationJobPayload

WorkerFn = Callable[[GenerationJobPayload], Awaitable[None]]


class GenerationQueue:
    """Simple FIFO queue with configurable concurrency."""

    def __init__(self, worker: WorkerFn, concurrency: int = 1) -> None:
        self._worker = worker
        self._queue: asyncio.Queue[GenerationJobPayload] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []
        self._concurrency = max(1, concurrency)
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        for _ in range(self._concurrency):
            self._tasks.append(asyncio.create_task(self._run()))

    async def stop(self) -> None:
        self._stop_event.set()
        for _ in range(self._concurrency):
            await self._queue.put(None)  # type: ignore[arg-type]
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def enqueue(self, payload: GenerationJobPayload) -> None:
        await self._queue.put(payload)

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            payload = await self._queue.get()
            if payload is None:
                self._queue.task_done()
                break
            try:
                await self._worker(payload)
            finally:
                self._queue.task_done()
