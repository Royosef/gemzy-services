"""Motion source URL allowlist (L5), OAuth rejection status (P11), proxy-aware client IP (P10)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from supabase_auth.errors import AuthApiError

from server import auth
from server.generations import _validate_motion_frame_url
from server.rate_limit import client_ip


@pytest.fixture
def storage_env(monkeypatch):
    monkeypatch.setenv("GCS_COLLECTIONS_PUBLIC_BUCKET", "public.gemzy.co")
    monkeypatch.setenv("GCS_COLLECTIONS_APP_BUCKET", "app.gemzy.co")
    monkeypatch.setenv("GCS_PUBLIC_HOST", "https://public.gemzy.co")
    monkeypatch.delenv("MOTION_FRAME_ALLOWED_HOSTS", raising=False)


@pytest.mark.parametrize(
    "url",
    [
        "https://storage.googleapis.com/app.gemzy.co/user/item.png?X-Goog-Signature=abc",
        "https://storage.googleapis.com/public.gemzy.co/user/item.png",
        "https://app.gemzy.co.storage.googleapis.com/user/item.png",
        "https://public.gemzy.co/user/item.png",
    ],
)
def test_motion_frame_accepts_gemzy_storage(storage_env, url):
    assert _validate_motion_frame_url(f"  {url} ") == url


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/a.png",
        "https://storage.googleapis.com/someone-elses-bucket/a.png",
        "https://public.gemzy.co.evil.example.com/a.png",
        "http://169.254.169.254/latest/meta-data",
        "file:///etc/passwd",
    ],
)
def test_motion_frame_rejects_other_hosts(storage_env, url):
    with pytest.raises(HTTPException) as exc:
        _validate_motion_frame_url(url)
    assert exc.value.status_code == 400


def test_motion_frame_extra_hosts(storage_env, monkeypatch):
    monkeypatch.setenv("MOTION_FRAME_ALLOWED_HOSTS", "cdn.gemzy.co, demo.gemzy.co")
    assert _validate_motion_frame_url("https://demo.gemzy.co/x.png") == "https://demo.gemzy.co/x.png"


def test_motion_frame_without_storage_config_allows_http(monkeypatch):
    for name in (
        "GCS_COLLECTIONS_PUBLIC_BUCKET",
        "GCS_COLLECTIONS_APP_BUCKET",
        "GCS_PUBLIC_HOST",
        "MOTION_FRAME_ALLOWED_HOSTS",
    ):
        monkeypatch.delenv(name, raising=False)
    assert _validate_motion_frame_url("http://localhost:9000/x.png") == "http://localhost:9000/x.png"


def test_rejected_id_token_is_401_not_500():
    def reject(_credentials):
        raise AuthApiError("Unacceptable audience in id_token", 400, None)

    sb = SimpleNamespace(auth=SimpleNamespace(sign_in_with_id_token=reject))
    with pytest.raises(HTTPException) as exc:
        auth._sign_in_with_id_token(sb, {"provider": "apple", "token": "t"})
    assert exc.value.status_code == 401


def _request(headers: dict[str, str], peer: str = "10.0.0.1") -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
            "client": (peer, 1234),
        }
    )


def test_client_ip_defaults_to_socket_peer(monkeypatch):
    monkeypatch.delenv("CLIENT_IP_HEADER", raising=False)
    monkeypatch.delenv("TRUSTED_PROXY_HOPS", raising=False)
    assert client_ip(_request({"X-Forwarded-For": "1.2.3.4"})) == "10.0.0.1"


def test_client_ip_uses_entry_written_by_trusted_proxy(monkeypatch):
    monkeypatch.delenv("CLIENT_IP_HEADER", raising=False)
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    # The caller forged "6.6.6.6"; the proxy appended the real address.
    assert client_ip(_request({"X-Forwarded-For": "6.6.6.6, 203.0.113.9"})) == "203.0.113.9"


def test_client_ip_header_override(monkeypatch):
    monkeypatch.setenv("CLIENT_IP_HEADER", "CF-Connecting-IP")
    assert client_ip(_request({"CF-Connecting-IP": "198.51.100.7"})) == "198.51.100.7"
