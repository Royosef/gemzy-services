"""Shared helpers for interacting with Google Cloud Storage."""
from __future__ import annotations

import json
import os
from datetime import timedelta

from fastapi import HTTPException, status
from google.auth import default
from google.auth.iam import Signer
from google.auth.transport.requests import Request
from google.cloud import storage
from google.oauth2 import service_account

_STORAGE_CLIENT: storage.Client | None = None
_SIGNER: Signer | None = None
_SIGNING_SA: str | None = None


def get_storage_client(project: str | None) -> storage.Client:
    """Return a cached storage client using configured credentials."""

    global _STORAGE_CLIENT

    if _STORAGE_CLIENT is not None:
        return _STORAGE_CLIENT

    credentials_json = os.getenv("GCS_CREDENTIALS")
    if credentials_json:
        try:
            info = json.loads(credentials_json)
            credentials = service_account.Credentials.from_service_account_info(info)
        except Exception as exc:  # pragma: no cover - env misconfiguration
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Invalid storage credentials",
            ) from exc
        _STORAGE_CLIENT = storage.Client(credentials=credentials, project=project)
        return _STORAGE_CLIENT

    try:
        if project:
            _STORAGE_CLIENT = storage.Client(project=project)
        else:  # pragma: no cover - project-less environments
            _STORAGE_CLIENT = storage.Client()
        return _STORAGE_CLIENT
    except Exception as exc:  # pragma: no cover - environment without GCP client
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage backend unavailable",
        ) from exc


def _get_signer() -> tuple[Signer, str]:
    """Return a cached keyless signer and its service account."""

    global _SIGNER, _SIGNING_SA

    if _SIGNER is not None and _SIGNING_SA is not None:
        return _SIGNER, _SIGNING_SA

    try:
        credentials, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    except Exception as exc:  # pragma: no cover - environment misconfiguration
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage signing credentials unavailable",
        ) from exc

    request = Request()
    service_account_email = os.getenv("GCS_SIGNING_SERVICE_ACCOUNT")

    if not service_account_email:
        service_account_email = getattr(credentials, "service_account_email", None)
        if not service_account_email:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Set GCS_SIGNING_SERVICE_ACCOUNT or run with a service account to "
                    "enable signed URLs"
                ),
            )

    try:
        signer = Signer(request, credentials, service_account_email)
    except Exception as exc:  # pragma: no cover - IAMCredentials failure
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to initialise signer",
        ) from exc

    _SIGNER = signer
    _SIGNING_SA = service_account_email
    return signer, service_account_email


def generate_signed_read_url_v4(blob: storage.Blob, seconds: int = 300) -> str:
    creds, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if not creds.valid or creds.expired or creds.token is None:
        creds.refresh(Request())

    sa_email = os.getenv("GCS_SIGNING_SERVICE_ACCOUNT") or getattr(creds, "service_account_email", None)
    if not sa_email:
        raise RuntimeError("Set GCS_SIGNING_SERVICE_ACCOUNT or run with a service account identity.")

    return blob.generate_signed_url(
        version="v4",
        method="GET",
        expiration=timedelta(seconds=max(60, seconds)),
        service_account_email=sa_email,
        access_token=creds.token,  # <- IAMCredentials used under the hood
    )

def maybe_get_bucket(
    bucket_name: str | None, project: str | None = None
) -> storage.Bucket | None:
    """Return the bucket instance when configured, otherwise ``None``."""

    if not bucket_name:
        return None
    try:
        return get_storage_client(project).bucket(bucket_name)
    except Exception as exc:  # pragma: no cover - storage outage
        return None


def get_bucket(
    bucket_name: str | None,
    project: str | None,
    *,
    missing_message: str | None = None,
) -> storage.Bucket:
    """Return the configured bucket or raise a 503 error when absent."""

    bucket = maybe_get_bucket(bucket_name, project)
    if bucket is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=missing_message or "Storage bucket is not configured",
        )
    return bucket


def build_public_url(object_path: str, bucket_name: str | None, *, public_host: str | None = None) -> str:
    """Construct the publicly accessible URL for a stored object."""

    normalized = object_path.lstrip("/")
    if public_host:
        return f"{public_host.rstrip('/')}/{normalized}"
    if not bucket_name:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storage bucket is not configured",
        )
    return f"https://storage.googleapis.com/{bucket_name}/{normalized}"


def user_storage_prefix(user_id: str) -> str:
    """Return the canonical prefix for user-owned storage objects."""

    return user_id.replace("/", "_")


__all__ = [
    "generate_signed_read_url_v4",
    "build_public_url",
    "get_bucket",
    "get_storage_client",
    "maybe_get_bucket",
    "user_storage_prefix",
]
