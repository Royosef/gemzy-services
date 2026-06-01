"""LLM integration tasks for Gemzy Moments planner using the google-genai SDK."""

import json
import logging

from google import genai
from google.genai import types
from prompting import (
    PROMPT_TASK_PLANNER_ENRICH,
    PROMPT_TASK_PLANNER_RANK,
    resolve_prompt_task,
)

from .models import (
    PlannerEnrichRequest,
    PlannerEnrichResponse,
    PlannerRankRequest,
    PlannerRankResponse,
)
from .settings import get_settings

logger = logging.getLogger(__name__)


def _get_client() -> genai.Client | None:
    settings = get_settings()
    if settings.provider != "google_gemini":
        return None
    if settings.google_gemini_use_vertex_ai:
        if not settings.google_cloud_project:
            return None
        return genai.Client(
            vertexai=True,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location or "global",
        )
    api_key = (settings.google_gemini_api_key or "").strip()
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


async def run_planner_enrichment(request: PlannerEnrichRequest) -> PlannerEnrichResponse:
    """Uses Gemini to generate the day arc and moments based on the user prompt."""
    client = _get_client()
    if not client:
        settings = get_settings()
        if settings.google_gemini_use_vertex_ai:
            raise ValueError("Vertex AI is not configured for planner enrichment")
        raise ValueError("GOOGLE_GEMINI_API_KEY is not configured")

    rendered = resolve_prompt_task(
        PROMPT_TASK_PLANNER_ENRICH,
        request.model_dump(mode="json"),
    )
    model_name = str(rendered.get("model_name") or "gemini-2.5-flash")
    system_instruction = str(rendered.get("system_instruction") or "")
    combined_prompt = str(rendered.get("user_prompt") or "")
    temperature = float(rendered.get("temperature") or 0.7)

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=combined_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=PlannerEnrichResponse,
                temperature=temperature,
            )
        )
        
        response_text = response.text
        if not response_text:
             raise ValueError("Model returned an empty text response")
             
        data = json.loads(response_text)
        return PlannerEnrichResponse(**data)

    except Exception as exc:
        logger.exception("Failed to run planner enrichment")
        raise ValueError(f"Planner enrichment failed: {exc}") from exc


async def run_planner_ranking(request: PlannerRankRequest) -> PlannerRankResponse:
    """Uses Gemini to score moments and allocate the best formats (Stoy vs Post)."""
    client = _get_client()
    if not client:
        settings = get_settings()
        if settings.google_gemini_use_vertex_ai:
            raise ValueError("Vertex AI is not configured for planner ranking")
        raise ValueError("GOOGLE_GEMINI_API_KEY is not configured")

    rendered = resolve_prompt_task(
        PROMPT_TASK_PLANNER_RANK,
        request.model_dump(mode="json"),
    )
    model_name = str(rendered.get("model_name") or "gemini-2.5-flash")
    system_instruction = str(rendered.get("system_instruction") or "")
    combined_prompt = str(rendered.get("user_prompt") or "")
    temperature = float(rendered.get("temperature") or 0.3)

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=combined_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=PlannerRankResponse,
                temperature=temperature,
            )
        )
        
        response_text = response.text
        if not response_text:
             raise ValueError("Model returned an empty text response")
             
        data = json.loads(response_text)
        return PlannerRankResponse(**data)

    except Exception as exc:
        logger.exception("Failed to run planner ranking")
        raise ValueError(f"Planner ranking failed: {exc}") from exc
