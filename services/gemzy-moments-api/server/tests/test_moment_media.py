from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.moment_media import get_available_moment_media, get_moment_media_mode


def test_media_mode_defaults_to_photos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOMENTS_MEDIA_MODE", raising=False)

    assert get_moment_media_mode() == "photos"
    assert get_available_moment_media() == ["photo"]


def test_media_mode_supports_both(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOMENTS_MEDIA_MODE", "both")

    assert get_moment_media_mode() == "both"
    assert get_available_moment_media() == ["photo", "video"]


def test_media_mode_supports_videos_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOMENTS_MEDIA_MODE", "video")

    assert get_moment_media_mode() == "videos"
    assert get_available_moment_media() == ["video"]
