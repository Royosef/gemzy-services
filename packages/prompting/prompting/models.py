"""Shared data models used by prompt builders."""

from __future__ import annotations

from pydantic import BaseModel


class GenerationItem(BaseModel):
    """Metadata for a single uploaded generation item."""

    id: str
    type: str
    size: str
    uploadId: str
