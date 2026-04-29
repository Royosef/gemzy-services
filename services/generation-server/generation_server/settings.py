"""Environment configuration for the generation service."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional


def _env_flag(*names: str, default: bool = False) -> bool:
    for name in names:
        raw_value = os.getenv(name)
        if raw_value is None:
            continue
        value = raw_value.strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off", ""}:
            return False
        raise RuntimeError(f"Invalid boolean value for {name}")
    return default


@dataclass(slots=True)
class Settings:
    """Runtime configuration derived from environment variables."""

    shared_secret: Optional[str]
    app_callback_base: str
    provider: Literal["comfyui", "google_gemini"]
    model_service_url: Optional[str]
    gcs_bucket: Optional[str]
    gcs_credentials: Optional[Dict[str, Any]]
    worker_concurrency: int
    callback_timeout: float
    callback_max_attempts: int
    callback_retry_delay: float
    result_poll_interval: float
    output_dir: str
    google_gemini_api_key: Optional[str]
    google_gemini_model: Optional[str]
    google_gemini_timeout: float
    google_gemini_use_vertex_ai: bool
    google_cloud_project: Optional[str]
    google_cloud_location: Optional[str]

    @classmethod
    def from_env(cls) -> "Settings":
        shared_secret = os.getenv("GENERATION_SHARED_SECRET")
        app_callback_base = os.getenv("GENERATION_APP_URL", "").strip()
        if not app_callback_base:
            raise RuntimeError("GENERATION_APP_URL must be configured")

        raw_credentials = os.getenv("GCS_CREDENTIALS")
        gcs_credentials: Optional[Dict[str, Any]] = None
        if raw_credentials:
            try:
                gcs_credentials = json.loads(raw_credentials)
            except json.JSONDecodeError as exc:  # pragma: no cover - validated at boot
                raise RuntimeError("Invalid JSON for GCS_CREDENTIALS") from exc

        provider = os.getenv("GENERATION_PROVIDER", "comfyui").strip().lower() or "comfyui"
        if provider not in {"comfyui", "google_gemini"}:
            raise RuntimeError("Unsupported GENERATION_PROVIDER value")

        google_gemini_api_key = os.getenv("GOOGLE_GEMINI_API_KEY")
        google_gemini_model = os.getenv("GOOGLE_GEMINI_MODEL")
        google_gemini_timeout = float(os.getenv("GOOGLE_GEMINI_TIMEOUT", "120"))
        google_gemini_use_vertex_ai = _env_flag(
            "GOOGLE_GEMINI_USE_VERTEX_AI",
            "GOOGLE_GENAI_USE_VERTEXAI",
        )
        google_cloud_project = os.getenv("GOOGLE_CLOUD_PROJECT")
        google_cloud_location = os.getenv("GOOGLE_CLOUD_LOCATION", "global").strip() or "global"

        if provider == "google_gemini":
            if google_gemini_use_vertex_ai:
                if not google_cloud_project:
                    raise RuntimeError(
                        "GOOGLE_CLOUD_PROJECT is required when Vertex AI is enabled for GENERATION_PROVIDER=google_gemini"
                    )
            elif not google_gemini_api_key:
                raise RuntimeError(
                    "GOOGLE_GEMINI_API_KEY is required when GENERATION_PROVIDER=google_gemini"
                )
            if not google_gemini_model:
                google_gemini_model = "gemini-2.5-flash-image"

        return cls(
            shared_secret=shared_secret,
            app_callback_base=app_callback_base.rstrip("/"),
            provider=provider,
            model_service_url=os.getenv("GENERATION_MODEL_SERVICE_URL"),
            gcs_bucket=os.getenv("GENERATION_MODEL_BUCKET"),
            gcs_credentials=gcs_credentials,
            worker_concurrency=max(1, int(os.getenv("GENERATION_WORKER_CONCURRENCY", "1"))),
            callback_timeout=float(os.getenv("GENERATION_CALLBACK_TIMEOUT", "15")),
            callback_max_attempts=max(1, int(os.getenv("GENERATION_CALLBACK_MAX_ATTEMPTS", "5"))),
            callback_retry_delay=max(0.0, float(os.getenv("GENERATION_CALLBACK_RETRY_DELAY", "1"))),
            result_poll_interval=float(os.getenv("GENERATION_RESULT_POLL", "0.5")),
            output_dir=os.getenv("GENERATION_OUTPUT_DIR", "./outputs"),
            google_gemini_api_key=google_gemini_api_key,
            google_gemini_model=google_gemini_model,
            google_gemini_timeout=google_gemini_timeout,
            google_gemini_use_vertex_ai=google_gemini_use_vertex_ai,
            google_cloud_project=google_cloud_project,
            google_cloud_location=google_cloud_location,
        )


def get_settings() -> Settings:
    """Return cached settings instance."""

    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = Settings.from_env()
    return _SETTINGS


_SETTINGS: Settings | None = None
