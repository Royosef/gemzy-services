"""FastAPI application for the standalone generation service."""

from __future__ import annotations

import base64

from fastapi import FastAPI, HTTPException, Request, status
from prompting import PROMPT_TASK_IMAGE_GENERATION_DEFAULTS, resolve_prompt_task

from .models import (
    GenerationJobPayload,
    WorkerResponse,
    GenerateSyncRequest,
    GenerateSyncResponse,
    PlannerEnrichRequest,
    PlannerEnrichResponse,
    PlannerRankRequest,
    PlannerRankResponse,
)
from .job_queue import GenerationQueue
from .settings import get_settings
from .tasks import (
    _get_runner,
    generate_looks,
    initialize_generation_backend,
    process_generation_job,
)
from .llm_tasks import run_planner_enrichment, run_planner_ranking

app = FastAPI(title="Gemzy Generation Server")

_settings = get_settings()
_queue = GenerationQueue(process_generation_job, concurrency=_settings.worker_concurrency)


def _require_secret(request: Request) -> None:
    expected = _settings.shared_secret
    if not expected:
        return
    provided = request.headers.get("X-Generation-Secret", "").strip()
    if provided != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid secret")


@app.on_event("startup")
async def _startup() -> None:
    await _queue.start()
    await initialize_generation_backend()


@app.on_event("shutdown")
async def _shutdown() -> None:
    await _queue.stop()


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/generate", response_model=WorkerResponse)
async def create_generation(payload: GenerationJobPayload, request: Request) -> WorkerResponse:
    _require_secret(request)
    await _queue.enqueue(payload)
    return WorkerResponse(
        id=payload.job.id,
        status="queued",
        totalLooks=payload.request.looks,
    )


@app.post("/generate-sync", response_model=GenerateSyncResponse)
async def generate_sync(payload: GenerateSyncRequest, request: Request) -> GenerateSyncResponse:
    """Synchronous generation endpoint for the Moments generation worker."""
    _require_secret(request)
    
    runner = _get_runner()
    results = []
    
    try:
        rendered_defaults = resolve_prompt_task(
            PROMPT_TASK_IMAGE_GENERATION_DEFAULTS,
            {},
        )
        negative_prompt = str(rendered_defaults.get("negative_prompt") or "")
        model_image = (
            base64.b64decode(payload.model_image_base64)
            if payload.model_image_base64
            else b""
        )
        reference_images = [base64.b64decode(item) for item in payload.reference_images_base64]

        generated_images = await generate_looks(
            settings=_settings,
            runner=runner,
            prompts=[payload.prompt] * payload.num_images,
            negative_prompt=negative_prompt,
            product_images=reference_images,
            model_image=model_image,
            product_image_mime_types=payload.reference_image_mime_types,
            model_image_mime_type=payload.model_image_mime_type,
            aspect=payload.aspect_ratio,
        )

        for image_bytes in generated_images:
            encoded = runner.encode_base64(image_bytes)
            results.append({"url": f"data:image/jpeg;base64,{encoded}"})
            
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Generation failed: {str(exc)}"
        )
        
    urls = [r["url"] for r in results if r.get("url")]
    return GenerateSyncResponse(urls=urls, results=results)


@app.post("/planner/enrich", response_model=PlannerEnrichResponse)
async def planner_enrich(payload: PlannerEnrichRequest, request: Request) -> PlannerEnrichResponse:
    _require_secret(request)
    try:
        return await run_planner_enrichment(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/planner/rank", response_model=PlannerRankResponse)
async def planner_rank(payload: PlannerRankRequest, request: Request) -> PlannerRankResponse:
    _require_secret(request)
    try:
        return await run_planner_ranking(payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


__all__ = ["app"]
