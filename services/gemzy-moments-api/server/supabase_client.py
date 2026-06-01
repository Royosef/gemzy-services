"""Supabase client initialization."""
from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from supabase import AsyncClient, Client, create_async_client, create_client

from pathlib import Path

for env_path in (
    Path(__file__).resolve().parent.parent / ".env",
    Path(__file__).resolve().parent / ".env",
):
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=False)
        break


def _create_client(key: str) -> Client:
    url = os.getenv("SUPABASE_URL")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    return create_client(url, key)


def _create_async_client(key: str) -> AsyncClient:
    url = os.getenv("SUPABASE_URL")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    return create_async_client(url, key)


def _service_role_key() -> str:
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    return key


def get_client() -> Client:
    """Return a fresh Supabase client instance.

    The Moments API uses the sync client from async request handlers and a
    background worker. Returning a fresh client avoids sharing one underlying
    HTTP/2 session across concurrent tasks, which has been causing intermittent
    transport errors in practice.
    """

    return _create_client(_service_role_key())


@lru_cache
def get_async_client() -> AsyncClient:
    """Return a cached asynchronous Supabase client instance."""

    return _create_async_client(_service_role_key())


def get_service_role_client(*, fresh: bool = False) -> Client:
    """Return a Supabase client authenticated with the service role key."""

    if fresh:
        return _create_client(_service_role_key())
    return get_client()


def create_user_client() -> Client:
    """Return a Supabase client suitable for user-scoped auth operations."""

    anon_key = os.getenv("SUPABASE_ANON_KEY") or _service_role_key()
    return _create_client(anon_key)


__all__ = [
    "create_user_client",
    "get_async_client",
    "get_client",
    "get_service_role_client",
]

