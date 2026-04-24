"""Helpers for retrieving reference assets for the generation workflow."""

from __future__ import annotations

import base64

import httpx

from .models import GenerationModel, GenerationRequest
from .settings import Settings


class ModelImageUnavailable(RuntimeError):
    """Raised when the model reference image cannot be resolved."""


async def _fetch_remote_bytes(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


async def resolve_model_image(request: GenerationRequest, settings: Settings) -> bytes:
    """Return the binary contents of the model reference image."""

    model: GenerationModel = request.model
    if model.imageBase64:
        try:
            return base64.b64decode(model.imageBase64)
        except Exception as exc:  # pragma: no cover - upstream data issue
            raise ModelImageUnavailable("Invalid base64 for model reference image") from exc

    uri = model.imageUri
    if uri and uri.startswith("http"):
        return await _fetch_remote_bytes(uri)

    if settings.model_service_url:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(f"{settings.model_service_url.rstrip('/')}/models/{model.id}")
            response.raise_for_status()
            data = response.json()
            remote = data.get("img")
            if remote:
                return await _fetch_remote_bytes(remote)

    raise ModelImageUnavailable("Model reference image could not be fetched")


def decode_upload_image(base64_data: str) -> bytes:
    """Decode a base64-encoded upload from the client."""

    return base64.b64decode(base64_data)
