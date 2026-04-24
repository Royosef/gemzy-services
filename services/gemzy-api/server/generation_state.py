"""In-memory tracking for generation jobs and their progress."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import Dict, List, Optional

from .schemas import GenerationResultPayload


@dataclass
class GenerationJob:
    """Mutable state for a generation job lifecycle."""

    id: str
    user_id: str
    total_looks: int
    status: str = "queued"
    completed_looks: int = 0
    progress: float = 0.0
    results: List[GenerationResultPayload] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    model_id: str | None = None
    model_name: str | None = None
    style: Dict[str, str] | None = None
    unsaved_collection_id: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def touch(self) -> None:
        self.updated_at = datetime.utcnow()


_JOBS: Dict[str, GenerationJob] = {}
_LOCK = RLock()


def create_job(
    job_id: str,
    user_id: str,
    total_looks: int,
    *,
    model_id: str | None = None,
    model_name: str | None = None,
    style: Dict[str, str] | None = None,
) -> GenerationJob:
    job = GenerationJob(
        id=job_id,
        user_id=user_id,
        total_looks=total_looks,
        model_id=model_id,
        model_name=model_name,
        style=style,
    )
    with _LOCK:
        _JOBS[job_id] = job
    return job


def get_job(job_id: str) -> Optional[GenerationJob]:
    with _LOCK:
        return _JOBS.get(job_id)


def to_response(job: GenerationJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "results": [result.model_dump() for result in job.results],
        "totalLooks": job.total_looks,
        "completedLooks": job.completed_looks,
        "errors": job.errors,
    }


def mark_started(job: GenerationJob) -> None:
    with _LOCK:
        job.status = "in_progress"
        job.touch()


def add_result(job: GenerationJob, result: GenerationResultPayload) -> None:
    with _LOCK:
        job.results.append(result)
        job.completed_looks = min(job.total_looks, len(job.results))
        if job.total_looks:
            job.progress = min(1.0, job.completed_looks / job.total_looks)
        job.touch()


def update_progress(job: GenerationJob, progress: float, completed: Optional[int] = None) -> None:
    with _LOCK:
        job.progress = max(0.0, min(1.0, progress))
        if completed is not None:
            job.completed_looks = max(job.completed_looks, completed)
        job.touch()


def mark_completed(job: GenerationJob) -> None:
    with _LOCK:
        job.status = "completed"
        job.progress = 1.0
        job.completed_looks = max(job.completed_looks, job.total_looks)
        job.touch()


def mark_failed(job: GenerationJob, error: str | None = None) -> None:
    with _LOCK:
        job.status = "failed"
        if error:
            job.errors.append(error)
        job.touch()


def reset_jobs() -> None:
    with _LOCK:
        _JOBS.clear()
