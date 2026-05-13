"""Supabase client initialization."""
from __future__ import annotations

import os
from functools import lru_cache
from threading import local

from dotenv import load_dotenv
from supabase import AsyncClient, Client, create_async_client, create_client

load_dotenv()

_PROMPT_TARGET_ENV = local()


def normalize_prompt_target_env(value: str | None) -> str:
    return "prod" if str(value or "").strip().lower() == "prod" else "dev"


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


def _prompt_registry_prod_service_role_key() -> str:
    key = os.getenv("PROMPT_REGISTRY_PROD_SUPABASE_SERVICE_KEY")
    if not key:
        raise RuntimeError(
            "PROMPT_REGISTRY_PROD_SUPABASE_URL and "
            "PROMPT_REGISTRY_PROD_SUPABASE_SERVICE_KEY must be set"
        )
    return key


def _prompt_registry_prod_url() -> str:
    url = os.getenv("PROMPT_REGISTRY_PROD_SUPABASE_URL")
    if not url:
        raise RuntimeError(
            "PROMPT_REGISTRY_PROD_SUPABASE_URL and "
            "PROMPT_REGISTRY_PROD_SUPABASE_SERVICE_KEY must be set"
        )
    return url


@lru_cache
def get_client() -> Client:
    """Return a cached Supabase client instance."""

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


@lru_cache
def _get_prompt_registry_prod_client() -> Client:
    return create_client(
        _prompt_registry_prod_url(),
        _prompt_registry_prod_service_role_key(),
    )


def set_prompt_target_env(value: str | None) -> str:
    previous = get_prompt_target_env()
    _PROMPT_TARGET_ENV.value = normalize_prompt_target_env(value)
    return previous


def reset_prompt_target_env(token: str) -> None:
    _PROMPT_TARGET_ENV.value = normalize_prompt_target_env(token)


def get_prompt_target_env() -> str:
    return normalize_prompt_environment_from_local()


def normalize_prompt_environment_from_local() -> str:
    return normalize_prompt_target_env(getattr(_PROMPT_TARGET_ENV, "value", "dev"))


def get_prompt_registry_client(*, fresh: bool = False) -> Client:
    if get_prompt_target_env() == "prod":
        if fresh:
            return create_client(
                _prompt_registry_prod_url(),
                _prompt_registry_prod_service_role_key(),
            )
        return _get_prompt_registry_prod_client()
    return get_service_role_client(fresh=fresh)


def create_user_client() -> Client:
    """Return a Supabase client suitable for user-scoped auth operations."""

    anon_key = os.getenv("SUPABASE_ANON_KEY") or _service_role_key()
    return _create_client(anon_key)


__all__ = [
    "create_user_client",
    "get_async_client",
    "get_client",
    "get_prompt_registry_client",
    "get_prompt_target_env",
    "get_service_role_client",
    "normalize_prompt_target_env",
    "reset_prompt_target_env",
    "set_prompt_target_env",
]

