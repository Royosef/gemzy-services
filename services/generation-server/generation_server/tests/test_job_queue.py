import asyncio
import logging
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("GENERATION_APP_URL", "https://app.example")

import pytest

from generation_server.job_queue import GenerationQueue
from generation_server.models import (
    GenerationDimensions,
    GenerationJobPayload,
    GenerationModel,
    GenerationRequest,
    GenerationUpload,
    JobMetadata,
    UserState,
)


def _payload(job_id: str) -> GenerationJobPayload:
    request = GenerationRequest(
        uploads=[
            GenerationUpload(
                id="upload-1",
                uri="https://example.com/asset.png",
                base64="ZmFrZQ==",
            )
        ],
        model=GenerationModel(
            id="model-1",
            slug="model",
            name="Model",
            planTier="Pro",
        ),
        style={},
        mode="SIMPLE",
        aspect="1:1",
        dims=GenerationDimensions(w=512, h=512),
        looks=1,
        quality="1k",
        plan="Pro",
        creditsNeeded=1,
        promptOverrides=[],
    )

    return GenerationJobPayload(
        job=JobMetadata(
            id=job_id,
            userId="user-1",
            callbackUrl="https://example.com/callback",
            looks=1,
        ),
        user=UserState(id="user-1", name="User", plan="Pro", credits=10),
        request=request,
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_worker_exception_does_not_stop_queue(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR, logger="generation_server.job_queue")

    processed: list[str] = []

    async def worker(payload: GenerationJobPayload) -> None:
        if payload.job.id == "job-1":
            raise RuntimeError("boom")
        processed.append(payload.job.id)

    queue = GenerationQueue(worker, concurrency=1)
    await queue.start()

    try:
        await queue.enqueue(_payload("job-1"))
        await queue.enqueue(_payload("job-2"))

        await asyncio.wait_for(queue._queue.join(), timeout=1)

        assert processed == ["job-2"]
        assert any(
            "Worker raised while processing job job-1" in record.getMessage()
            for record in caplog.records
        )
    finally:
        await queue.stop()
