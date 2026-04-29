"""Async runner that delegates generations to Google Gen AI backends."""

from __future__ import annotations

import asyncio
import base64
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

    def __init__(
        self,
        api_key: str | None,
        model: str,
        *,
        use_vertex_ai: bool = False,
        vertex_project: str | None = None,
        vertex_location: str | None = None,
        timeout: float = 120.0,
        client: genai.Client | None = None,
    ) -> None:
        if not model:
            raise ValueError("model must be provided")
        if use_vertex_ai:
            if not vertex_project:
                raise ValueError("vertex_project must be provided when use_vertex_ai is enabled")
            if not vertex_location:
                raise ValueError("vertex_location must be provided when use_vertex_ai is enabled")
        elif not api_key:
            raise ValueError("api_key must be provided")

        self._model = model
        self._timeout = timeout
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

    async def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        product_images: Iterable[bytes],
        model_image: bytes,
        product_image_mime_types: Iterable[str] | None = None,
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
            model_image_mime_type=model_image_mime_type,
            look_index=look_index,
        )

        if genai_types is None:
            raise GoogleGeminiError(
                "google-genai types are unavailable; install google-genai to use this provider"
            )


        generation_config = genai_types.GenerateContentConfig(
            temperature=0.2,
            candidate_count=1,
            response_modalities=["IMAGE"],
            image_config=genai_types.ImageConfig(
                aspect_ratio=aspect,
                output_mime_type="image/png",
            ),
        )

        response = self._client.models.generate_content(
            model=self._model,
            contents=contents,
            config=generation_config,
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

    def _build_contents(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        product_images: Sequence[bytes],
        model_image: bytes,
        product_image_mime_types: Sequence[str],
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

        if model_image:
            prompt_parts.append(
                genai_types.Part(
                    text=(
                        "The next image references are jewelry/product inputs only. "
                        "Use them only for jewelry design, gemstones, materials, scale, "
                        "and placement cues. If any people, faces, bodies, hair, clothing, "
                        "or persona traits appear in those jewelry images, ignore them."
                    )
                )
            )

        for index, product_image in enumerate(product_images):
            if not product_image:
                continue
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
                    if getattr(part, "text", None):
                        try:
                            parsed = base64.b64decode(part.text)
                        except Exception:  # pragma: no cover - best effort fallback
                            continue
                        return parsed
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
