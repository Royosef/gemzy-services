"""Async runner that delegates generations to Google Gen AI backends."""

from __future__ import annotations

import asyncio
import base64
import random
import re
import threading
import time
from typing import Any, Iterable, Literal, Sequence

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:  # pragma: no cover - optional dependency in test environments
    genai = None
    genai_types = None


class GoogleGeminiError(RuntimeError):
    """Raised when the Google Gemini API returns an unexpected response."""


class GoogleGeminiRunner:
    """Thin wrapper around the Google Gemini SDK suitable for our worker loop."""

    supports_parallel_look_generation = True

    def __init__(
        self,
        api_key: str | None,
        model: str | None = None,
        *,
        models: Sequence[str] | None = None,
        use_vertex_ai: bool = False,
        vertex_project: str | None = None,
        vertex_location: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 4,
        retry_initial_delay: float = 1.0,
        retry_max_delay: float = 16.0,
        retry_jitter: float = 0.25,
        client: genai.Client | None = None,
    ) -> None:
        configured_models = tuple(
            candidate.strip()
            for candidate in (models or ((model,) if model else ()))
            if candidate and candidate.strip()
        )
        if not configured_models:
            raise ValueError("at least one model must be provided")
        if use_vertex_ai:
            if not vertex_project:
                raise ValueError("vertex_project must be provided when use_vertex_ai is enabled")
            if not vertex_location:
                raise ValueError("vertex_location must be provided when use_vertex_ai is enabled")
        elif not api_key:
            raise ValueError("api_key must be provided")

        self._models = configured_models
        self._model_index = 0
        self._model_lock = threading.Lock()
        self._timeout = timeout
        self._max_retries = max(0, int(max_retries))
        self._retry_initial_delay = max(0.0, float(retry_initial_delay))
        self._retry_max_delay = max(0.0, float(retry_max_delay))
        self._retry_jitter = max(0.0, float(retry_jitter))
        if client is not None:
            self._client = client
        else:
            if genai is None:
                raise RuntimeError(
                    "google-genai is required to use the Google Gemini provider"
                )
            if use_vertex_ai:
                self._client = genai.Client(
                    vertexai=True,
                    project=vertex_project,
                    location=vertex_location,
                )
            else:
                self._client = genai.Client(api_key=api_key)

    async def initialize(self) -> None:
        """No-op initializer to match the generation runner protocol."""

        return None

    def _next_model(self) -> str:
        """Select one model per provider request in round-robin order."""

        with self._model_lock:
            model = self._models[self._model_index]
            self._model_index = (self._model_index + 1) % len(self._models)
            return model

    async def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        product_images: Iterable[bytes],
        model_image: bytes,
        product_image_mime_types: Iterable[str] | None = None,
        product_image_labels: Iterable[str] | None = None,
        model_image_mime_type: str | None = None,
        aspect: Literal["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "9:16", "16:9", "21:9"],
        look_index: int,
    ) -> bytes:
        return await asyncio.wait_for(
            asyncio.to_thread(
                self._generate_sync,
                prompt,
                negative_prompt,
                tuple(product_images),
                model_image,
                tuple(product_image_mime_types or ()),
                tuple(product_image_labels or ()),
                model_image_mime_type,
                aspect,
                look_index,
            ),
            timeout=self._timeout,
        )

    def _generate_sync(
        self,
        prompt: str,
        negative_prompt: str,
        product_images: Sequence[bytes],
        model_image: bytes,
        product_image_mime_types: Sequence[str],
        product_image_labels: Sequence[str],
        model_image_mime_type: str | None,
        aspect: Literal["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "9:16", "16:9", "21:9"],
        look_index: int,
    ) -> bytes:
        contents = self._build_contents(
            prompt=prompt,
            negative_prompt=negative_prompt,
            product_images=product_images,
            model_image=model_image,
            product_image_mime_types=product_image_mime_types,
            product_image_labels=product_image_labels,
            model_image_mime_type=model_image_mime_type,
            look_index=look_index,
        )

        if genai_types is None:
            raise GoogleGeminiError(
                "google-genai types are unavailable; install google-genai to use this provider"
            )


        selected_model = self._next_model()
        generation_config_kwargs: dict[str, Any] = {}
        if selected_model == "gemini-nano-banana-2.1":
            generation_config_kwargs["thinking_config"] = genai_types.ThinkingConfig(
                thinking_level="HIGH"
            )

        generation_config = genai_types.GenerateContentConfig(
            temperature=0.2,
            candidate_count=1,
            response_modalities=["IMAGE"],
            image_config=genai_types.ImageConfig(
                aspect_ratio=aspect,
                output_mime_type="image/png",
            ),
            **generation_config_kwargs,
        )

        response = self._generate_content_with_retries(
            contents=contents,
            generation_config=generation_config,
            model=selected_model,
        )

        image_bytes = self._extract_image_bytes(response)
        if not image_bytes:
            block_reason = self._extract_block_reason(response)
            if block_reason:
                raise GoogleGeminiError(f"Response did not include an image payload: {block_reason}")
            raise GoogleGeminiError("Response did not include an image payload")

        if isinstance(image_bytes, str):
            try:
                return base64.b64decode(image_bytes)
            except Exception as exc:  # pragma: no cover - invalid upstream payload
                raise GoogleGeminiError("Invalid base64 image returned by Google Gemini") from exc

        if not isinstance(image_bytes, (bytes, bytearray)):
            raise GoogleGeminiError("Unexpected image payload type returned by Google Gemini")

        return bytes(image_bytes)

    def _generate_content_with_retries(
        self,
        *,
        contents: Sequence[Any],
        generation_config: Any,
        model: str,
    ) -> Any:
        attempt = 0
        while True:
            try:
                return self._client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=generation_config,
                )
            except Exception as exc:
                if attempt >= self._max_retries or not self._is_retryable_error(exc):
                    raise
                delay = self._compute_retry_delay(exc=exc, attempt=attempt)
                time.sleep(delay)
                attempt += 1

    def _compute_retry_delay(self, *, exc: Exception, attempt: int) -> float:
        retry_after = self._extract_retry_after_seconds(exc)
        if retry_after is not None:
            base_delay = retry_after
        else:
            base_delay = self._retry_initial_delay * (2**attempt)
        capped_delay = min(self._retry_max_delay, max(0.0, base_delay))
        if capped_delay <= 0.0:
            return 0.0
        if self._retry_jitter <= 0.0:
            return capped_delay
        lower_bound = max(0.0, capped_delay * (1.0 - self._retry_jitter))
        upper_bound = capped_delay * (1.0 + self._retry_jitter)
        return random.uniform(lower_bound, upper_bound)

    @staticmethod
    def _extract_retry_after_seconds(exc: Exception) -> float | None:
        for attr_name in ("retry_after", "retry_after_seconds"):
            value = getattr(exc, attr_name, None)
            parsed = GoogleGeminiRunner._parse_seconds(value)
            if parsed is not None:
                return parsed

        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers:
            try:
                value = headers.get("retry-after")
            except Exception:  # pragma: no cover - defensive for odd header types
                value = None
            parsed = GoogleGeminiRunner._parse_seconds(value)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _parse_seconds(value: object) -> float | None:
        if value is None:
            return None
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return None
        return max(0.0, seconds)

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        status_code = GoogleGeminiRunner._extract_status_code(exc)
        if status_code in {429, 500, 502, 503, 504}:
            return True

        message = str(exc).upper()
        retryable_markers = (
            "RESOURCE_EXHAUSTED",
            "UNAVAILABLE",
            "DEADLINE_EXCEEDED",
            "INTERNAL",
            "TOO MANY REQUESTS",
        )
        return any(marker in message for marker in retryable_markers)

    @staticmethod
    def _extract_status_code(exc: Exception) -> int | None:
        for attr_name in ("status_code", "code"):
            value = getattr(exc, attr_name, None)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)

        response = getattr(exc, "response", None)
        for attr_name in ("status_code", "code"):
            value = getattr(response, attr_name, None)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)

        match = re.search(r"\b(429|500|502|503|504)\b", str(exc))
        if match:
            return int(match.group(1))
        return None

    def _build_contents(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        product_images: Sequence[bytes],
        model_image: bytes,
        product_image_mime_types: Sequence[str],
        product_image_labels: Sequence[str],
        model_image_mime_type: str | None,
        look_index: int,
    ) -> Sequence[Any]:
        if genai_types is None:
            raise GoogleGeminiError(
                "google-genai types are unavailable; install google-genai to use this provider"
            )

        prompt_parts = [genai_types.Part(text=prompt.strip())]

        if negative_prompt.strip():
            prompt_parts.append(
                genai_types.Part(text=f"Avoid: {negative_prompt.strip()}")
            )

        prompt_parts.append(
            genai_types.Part(
                text=f"Render look {look_index + 1}"
            )
        )

        has_labeled_product_images = any(
            label.strip() for label in product_image_labels
        )
        if has_labeled_product_images or model_image:
            prompt_parts.append(
                genai_types.Part(
                    text=(
                        "The following numbered image references are jewelry/product inputs only. "
                        "Treat each label as authoritative metadata for the image immediately after it. "
                        "Treat each uploaded jewelry image as an immutable product specification, "
                        "not as inspiration. Reproduce the exact product and preserve its geometry, "
                        "proportions, silhouette, topology, construction, relative scale, materials, "
                        "colors, finish, and every visible stone, crystal, bead, pearl, link, setting, "
                        "prong, clasp, connector, engraving, edge, opening, and repeated element, "
                        "including their exact count, order, spacing, size relationships, and placement. "
                        "Do not redesign, stylize, simplify, merge, blur, substitute, recolor, resize, "
                        "add, remove, repair, or reinterpret any jewelry detail. The scene, pose, styling, "
                        "lighting, and camera treatment may change; the jewelry product may not. If product "
                        "fidelity conflicts with aesthetics or creative direction, product fidelity wins. "
                        "If any people, faces, bodies, hair, clothing, "
                        "or persona traits appear in those jewelry images, ignore them."
                    )
                )
            )

        for index, product_image in enumerate(product_images):
            if not product_image:
                continue
            label = (
                product_image_labels[index].strip()
                if index < len(product_image_labels) and product_image_labels[index].strip()
                else ""
            )
            if label:
                prompt_parts.append(
                    genai_types.Part(
                        text=f"{label}. The immediately following image is this jewelry reference."
                    )
                )
            mime_type = (
                product_image_mime_types[index]
                if index < len(product_image_mime_types) and product_image_mime_types[index]
                else "image/png"
            )
            prompt_parts.append(
                genai_types.Part(
                    inline_data=genai_types.Blob(
                        mime_type=mime_type,
                        data=product_image,
                    )
                )
            )

        if model_image:
            prompt_parts.append(
                genai_types.Part(
                    text=(
                        "The next image is the authoritative model/persona reference. "
                        "Use only this image for identity, face, body, skin tone, hair, "
                        "and overall persona. Do not borrow persona traits from the jewelry "
                        "reference images."
                    )
                )
            )
            prompt_parts.append(
                genai_types.Part(
                    inline_data=genai_types.Blob(
                        mime_type=model_image_mime_type or "image/png",
                        data=model_image,
                    )
                )
            )

        return [genai_types.Content(role="user", parts=prompt_parts)]

    @staticmethod
    def encode_base64(image_bytes: bytes) -> str:
        """Return a base64 encoded representation of ``image_bytes``."""

        return base64.b64encode(image_bytes).decode("utf-8")

    def _extract_image_bytes(self, response: object) -> bytes | str | None:
        images = getattr(response, "images", None)
        if images:
            for image in images:
                data = getattr(image, "data", None)
                if data:
                    return data

        response_parts = getattr(response, "parts", None)
        if response_parts:
            for part in response_parts:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    return inline.data

        candidates = getattr(response, "candidates", None)
        if candidates:
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                if not content:
                    continue
                parts = getattr(content, "parts", None)
                if not parts:
                    continue
                for part in parts:
                    inline = getattr(part, "inline_data", None)
                    if inline and getattr(inline, "data", None):
                        return inline.data
                    # Image responses are delivered as inline_data. Never
                    # interpret an arbitrary text response as base64: ordinary
                    # prompt-like text can consist entirely of base64 alphabet
                    # characters and decode into convincing but invalid bytes.
        return None

    def _extract_block_reason(self, response: object) -> str | None:
        prompt_feedback = getattr(response, "prompt_feedback", None)
        if not prompt_feedback:
            return None

        block_reason = getattr(prompt_feedback, "block_reason", None)
        block_reason_message = getattr(prompt_feedback, "block_reason_message", None)
        if block_reason and block_reason_message:
            return f"{block_reason}: {block_reason_message}"
        if block_reason:
            return str(block_reason)
        if block_reason_message:
            return str(block_reason_message)
        return None


__all__ = ["GoogleGeminiError", "GoogleGeminiRunner"]
