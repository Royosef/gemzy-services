"""Browser session support for the Gemzy web app.

Native clients receive ``{access, refresh}`` in the JSON body and store them in
secure device storage. A browser cannot do that safely: anything readable by
JavaScript is exposed to XSS. For allow-listed web origins we therefore keep the
refresh token in an ``HttpOnly`` cookie scoped to ``/auth`` and return an empty
``refresh`` field in the body. The access token stays in the response body and
is held in memory by the web client only.

Web-session mode is opt-in per request and requires BOTH:

* ``X-Gemzy-Client: web`` - a non-simple header, so cross-site requests must pass
  a CORS preflight (a CSRF guard for the cookie-bearing ``/auth/refresh``), and
* an ``Origin`` listed in ``WEB_SESSION_ORIGINS``.

Requests that do not meet both conditions behave exactly as before, so the
mobile app is unaffected.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import Request, Response

from .schemas import Token

WEB_CLIENT_HEADER = "x-gemzy-client"
WEB_CLIENT_VALUE = "web"
_COOKIE_PATH = "/auth"
_DEFAULT_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # Supabase refresh tokens are long-lived; cap at 30 days.


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def cookie_name() -> str:
    return os.getenv("WEB_SESSION_COOKIE_NAME", "gemzy_rt").strip() or "gemzy_rt"


def allowed_origins() -> set[str]:
    raw = os.getenv("WEB_SESSION_ORIGINS", "")
    return {origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()}


def is_web_session_request(request: Request) -> bool:
    if request.headers.get(WEB_CLIENT_HEADER, "").strip().lower() != WEB_CLIENT_VALUE:
        return False
    origin = request.headers.get("origin", "").strip().rstrip("/")
    return bool(origin) and origin in allowed_origins()


def _cookie_kwargs() -> dict:
    kwargs: dict = {
        "path": _COOKIE_PATH,
        "httponly": True,
        # Secure must only be disabled for plain-http local development.
        "secure": _env_flag("WEB_SESSION_COOKIE_SECURE", True),
        # API and web app share a registrable domain (same-site), so Lax is enough
        # and blocks the cookie on cross-site subresource/POST requests.
        "samesite": "lax",
    }
    domain = os.getenv("WEB_SESSION_COOKIE_DOMAIN", "").strip()
    if domain:
        kwargs["domain"] = domain
    return kwargs


def issue(request: Request, response: Response, token: Token) -> Token:
    """Move the refresh token into a cookie for web-session requests.

    Returns the token object that should be serialised in the response body.
    """
    if not is_web_session_request(request):
        return token
    max_age = int(os.getenv("WEB_SESSION_MAX_AGE_SECONDS", _DEFAULT_MAX_AGE_SECONDS))
    response.set_cookie(cookie_name(), token.refresh, max_age=max_age, **_cookie_kwargs())
    response.headers["Cache-Control"] = "no-store"
    return Token(access=token.access, refresh="")


def read_refresh(request: Request) -> Optional[str]:
    if not is_web_session_request(request):
        return None
    value = request.cookies.get(cookie_name())
    return value or None


def clear(response: Response) -> None:
    response.delete_cookie(cookie_name(), **_cookie_kwargs())
