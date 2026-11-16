"""In-memory tracking for generation jobs and their progress."""

from __future__ import annotations

import logging

from .analytics import record_generation

from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import Any, Dict, List, Optional

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
    aspect: str | None = None
    dims: dict[str, int] | None = None
    quality: str | None = None
    unsaved_collection_id: str | None = None
    job_type: str = "generation"
    edit_source: dict[str, Any] | None = None
    edit_instructions: list[dict[str, Any]] = field(default_factory=list)
    edit_credit_cost: int | None = None
    edit_trial_applied: bool = False
    edit_mode_trial_edits_remaining: int | None = None
    reserved_credit_cost: int = 0
    refunded_credit_cost: int = 0
    credit_cost_per_look: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    analytics_started_recorded: bool = False
    analytics_terminal_pending: bool = False
    analytics_terminal_recorded: bool = False
    analytics_context: dict[str, Any] = field(default_factory=dict)
    lifecycle_lock: RLock = field(default_factory=RLock, repr=False, compare=False)

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
    aspect: str | None = None,
    dims: dict[str, int] | None = None,
    quality: str | None = None,
    unsaved_collection_id: str | None = None,
    job_type: str = "generation",
    edit_source: dict[str, Any] | None = None,
    edit_instructions: list[dict[str, Any]] | None = None,
    edit_credit_cost: int | None = None,
    edit_trial_applied: bool = False,
    edit_mode_trial_edits_remaining: int | None = None,
    reserved_credit_cost: int = 0,
    credit_cost_per_look: int = 0,
    analytics_context: dict[str, Any] | None = None,
) -> GenerationJob:
    job = GenerationJob(
        analytics_context=analytics_context or {},
        id=job_id,
        user_id=user_id,
        total_looks=total_looks,
        model_id=model_id,
        model_name=model_name,
        style=style,
        aspect=aspect,
        dims=dims,
        quality=quality,
        unsaved_collection_id=unsaved_collection_id,
        job_type=job_type,
        edit_source=edit_source,
        edit_instructions=edit_instructions or [],
        edit_credit_cost=edit_credit_cost,
        edit_trial_applied=edit_trial_applied,
        edit_mode_trial_edits_remaining=edit_mode_trial_edits_remaining,
        reserved_credit_cost=reserved_credit_cost,
        credit_cost_per_look=credit_cost_per_look,
    )
    with _LOCK:
        _JOBS[job_id] = job
    _record_analytics(job)
    return job


def _record_analytics(job, terminal=False, strict=False):
    if terminal:
        job.analytics_terminal_pending = True
    if (terminal and job.analytics_terminal_recorded) or (not terminal and job.analytics_started_recorded):
        return
    try:
        if terminal and not job.analytics_started_recorded:
            record_generation(job)
            job.analytics_started_recorded = True
        record_generation(job, terminal=terminal)
        if terminal:
            job.analytics_terminal_recorded = True
        else:
            job.analytics_started_recorded = True
    except Exception:
        logging.getLogger(__name__).exception("Failed to enqueue generation analytics for %s", job.id)
        if strict:
            raise


def retry_generation_analytics():
    with _LOCK:
        jobs = list(_JOBS.values())
    for job in jobs:
        # Only retry terminal snapshots requested after refunds/settlement.
        _record_analytics(job, terminal=job.analytics_terminal_pending)


def get_job(job_id: str) -> Optional[GenerationJob]:
    with _LOCK:
        return _JOBS.get(job_id)


def delete_job(job_id: str) -> bool:
    with _LOCK:
        return _JOBS.pop(job_id, None) is not None


def to_response(job: GenerationJob, *, strict_analytics: bool = False) -> dict:
    if job.status in {"completed", "failed"}:
        _record_analytics(job, terminal=True, strict=strict_analytics)
    payload = {
        "id": job.id,
        "status": job.status,
        "progress": job.progress,
        "results": [result.model_dump() for result in job.results],
        "totalLooks": job.total_looks,
        "completedLooks": job.completed_looks,
        "errors": job.errors,
    }
    if job.job_type != "generation":
        payload.update(
            {
                "jobType": job.job_type,
                "editSource": job.edit_source,
                "editInstructions": job.edit_instructions,
                "editCreditCost": job.edit_credit_cost,
                "editTrialApplied": job.edit_trial_applied,
                "editModeTrialEditsRemaining": job.edit_mode_trial_edits_remaining,
            }
        )
    return payload


def mark_started(job: GenerationJob) -> None:
    with _LOCK:
        if job.status in {"completed", "failed"}:
            return
        job.status = "in_progress"
        job.touch()


def add_result(job: GenerationJob, result: GenerationResultPayload) -> None:
    with _LOCK:
        if job.status == "failed" or len(job.results) >= job.total_looks:
            job.touch()
            return
        job.results.append(result)
        job.completed_looks = min(job.total_looks, len(job.results))
        if job.total_looks:
            job.progress = min(1.0, job.completed_looks / job.total_looks)
        job.touch()


def update_progress(job: GenerationJob, progress: float, completed: Optional[int] = None) -> None:
    with _LOCK:
        if job.status in {"completed", "failed"}:
            return
        job.progress = max(0.0, min(1.0, progress))
        if completed is not None:
            job.completed_looks = min(job.total_looks, max(job.completed_looks, completed))
        job.touch()


def mark_completed(job: GenerationJob) -> None:
    with _LOCK:
        if job.status == "failed":
            return
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
