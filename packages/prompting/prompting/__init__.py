"""Shared prompt registry helpers used across Gemzy services."""

from .defaults import (
    PROMPT_TASK_IMAGE_GENERATION_COMPOSE,
    PROMPT_TASK_IMAGE_GENERATION_DEFAULTS,
    PROMPT_TASK_ON_MODEL,
    PROMPT_TASK_ON_MODEL_EDIT,
    PROMPT_TASK_PLANNER_ENRICH,
    PROMPT_TASK_PLANNER_RANK,
    PROMPT_TASK_PURE_JEWELRY,
    PROMPT_TASK_PURE_JEWELRY_EDIT,
    get_default_registry,
)
from .registry import (
    PromptRegistryError,
    PromptRouteNotFound,
    ensure_default_prompt_registry,
    render_default_task,
    render_engine_version,
    resolve_prompt_task,
)

__all__ = [
    "PROMPT_TASK_IMAGE_GENERATION_COMPOSE",
    "PROMPT_TASK_IMAGE_GENERATION_DEFAULTS",
    "PROMPT_TASK_ON_MODEL",
    "PROMPT_TASK_ON_MODEL_EDIT",
    "PROMPT_TASK_PLANNER_ENRICH",
    "PROMPT_TASK_PLANNER_RANK",
    "PROMPT_TASK_PURE_JEWELRY",
    "PROMPT_TASK_PURE_JEWELRY_EDIT",
    "PromptRegistryError",
    "PromptRouteNotFound",
    "ensure_default_prompt_registry",
    "get_default_registry",
    "render_default_task",
    "render_engine_version",
    "resolve_prompt_task",
]
