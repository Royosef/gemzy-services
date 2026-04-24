import asyncio
import base64
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("GENERATION_APP_URL", "https://example.test")

from generation_server import google_runner
from generation_server.google_runner import GoogleGeminiError, GoogleGeminiRunner


class StubBlob:
    def __init__(self, *, mime_type, data):
        self.mime_type = mime_type
        self.data = data


class StubPart:
    def __init__(self, text=None, inline_data=None):
        self.text = text
        self.inline_data = inline_data


class StubContent:
    def __init__(self, *, role, parts):
        self.role = role
        self.parts = list(parts)


class StubGenerationConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class StubImageConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


google_runner.genai_types = SimpleNamespace(  # type: ignore[attr-defined]
    Blob=StubBlob,
    Part=StubPart,
    Content=StubContent,
    GenerateContentConfig=StubGenerationConfig,
    ImageConfig=StubImageConfig,
)


class DummyInlineData:
    def __init__(self, data):
        self.data = data


class DummyPart:
    def __init__(self, inline_data=None, text=None):
        self.inline_data = inline_data
        self.text = text


class DummyContent:
    def __init__(self, parts):
        self.parts = parts


class DummyCandidate:
    def __init__(self, parts):
        self.content = DummyContent(parts)


class DummyResponse:
    def __init__(self, parts, *, response_parts=None, prompt_feedback=None):
        self.candidates = [DummyCandidate(parts)]
        self.parts = response_parts
        self.prompt_feedback = prompt_feedback


class DummyModels:
    def __init__(self, client):
        self._client = client

    def generate_content(self, *, model, contents, config):
        self._client.calls.append(
            {
                "model": model,
                "contents": contents,
                "config": config,
            }
        )
        return self._client.response


class DummyClient:
    def __init__(self, response):
        self.calls = []
        self.response = response
        self.models = DummyModels(self)


def test_generate_returns_bytes():
    response = DummyResponse([DummyPart(inline_data=DummyInlineData(b"image-bytes"))])
    client = DummyClient(response)

    runner = GoogleGeminiRunner(
        api_key="secret",
        model="gemini-test",
        client=client,
    )

    result = asyncio.run(
        runner.generate(
            prompt="prompt",
            negative_prompt="no",
            product_images=[b"foo"],
            model_image=b"bar",
            product_image_mime_types=["image/jpeg"],
            model_image_mime_type="image/png",
            aspect="1:1",
            look_index=1,
        )
    )

    assert result == b"image-bytes"
    assert client.calls[0]["model"] == "gemini-test"
    assert client.calls[0]["contents"][0].parts[0].text == "prompt"
    assert client.calls[0]["config"].kwargs["response_modalities"] == ["IMAGE"]
    assert client.calls[0]["config"].kwargs["image_config"].kwargs["output_mime_type"] == "image/png"


def test_generate_reads_top_level_response_parts():
    response = DummyResponse(
        [],
        response_parts=[DummyPart(inline_data=DummyInlineData(b"top-level-image"))],
    )
    client = DummyClient(response)

    runner = GoogleGeminiRunner(
        api_key="secret",
        model="gemini-test",
        client=client,
    )

    result = asyncio.run(
        runner.generate(
            prompt="prompt",
            negative_prompt="",
            product_images=[],
            model_image=b"",
            aspect="1:1",
            look_index=0,
        )
    )

    assert result == b"top-level-image"


def test_generate_missing_payload_raises():
    response = DummyResponse([DummyPart(text="no image here")])
    client = DummyClient(response)

    runner = GoogleGeminiRunner(
        api_key="secret",
        model="gemini-test",
        client=client,
    )

    with pytest.raises(GoogleGeminiError):
        asyncio.run(
            runner.generate(
                prompt="prompt",
                negative_prompt="no",
                product_images=[],
                model_image=b"bar",
                aspect="4:5",
                look_index=1,
            )
        )


def test_generate_blocked_payload_includes_feedback():
    prompt_feedback = SimpleNamespace(
        block_reason="SAFETY",
        block_reason_message="Image generation blocked by policy",
    )
    response = DummyResponse([], prompt_feedback=prompt_feedback)
    client = DummyClient(response)

    runner = GoogleGeminiRunner(
        api_key="secret",
        model="gemini-test",
        client=client,
    )

    with pytest.raises(GoogleGeminiError, match="SAFETY"):
        asyncio.run(
            runner.generate(
                prompt="prompt",
                negative_prompt="",
                product_images=[],
                model_image=b"",
                aspect="1:1",
                look_index=0,
            )
        )


def test_encode_base64():
    runner = GoogleGeminiRunner(
        api_key="secret",
        model="gemini-test",
        client=DummyClient(DummyResponse([])),
    )

    assert runner.encode_base64(b"test") == base64.b64encode(b"test").decode("utf-8")


def test_vertex_ai_requires_project():
    with pytest.raises(ValueError, match="vertex_project"):
        GoogleGeminiRunner(
            api_key=None,
            model="gemini-test",
            use_vertex_ai=True,
            vertex_location="global",
            client=DummyClient(DummyResponse([])),
        )


def test_vertex_ai_client_uses_project_and_location(monkeypatch: pytest.MonkeyPatch):
    captured: list[dict[str, object]] = []

    class FakeClientFactory:
        def __call__(self, **kwargs):
            captured.append(kwargs)
            return DummyClient(DummyResponse([]))

    monkeypatch.setattr(google_runner, "genai", SimpleNamespace(Client=FakeClientFactory()))

    GoogleGeminiRunner(
        api_key=None,
        model="gemini-test",
        use_vertex_ai=True,
        vertex_project="demo-project",
        vertex_location="global",
    )

    assert captured == [
        {
            "vertexai": True,
            "project": "demo-project",
            "location": "global",
        }
    ]
