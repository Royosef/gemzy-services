"""Rate limiting configuration for the API."""
import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def client_ip(request: Request) -> str:
    """The caller's IP address, as seen through our own proxy.

    Behind a proxy or load balancer every request comes from the proxy's address, so all
    visitors would share one rate-limit bucket. Forwarding headers can be forged by the caller,
    so they are only read when configured for the proxy actually in front of the API:

    - ``CLIENT_IP_HEADER``: a header the proxy overwrites with the client IP, e.g.
      ``CF-Connecting-IP`` behind Cloudflare. Only set it if every request passes that proxy.
    - ``TRUSTED_PROXY_HOPS``: number of trusted proxies that append to ``X-Forwarded-For``
      (1 for Cloud Run or a single load balancer). The entry that many places from the right
      was written by our proxy; anything left of it came from the caller.

    Neither set (the default): the socket peer address, as before.
    """

    header = os.getenv("CLIENT_IP_HEADER", "").strip()
    if header:
        value = request.headers.get(header, "").strip()
        if value:
            return value

    try:
        hops = int(os.getenv("TRUSTED_PROXY_HOPS", "0") or 0)
    except ValueError:
        hops = 0
    if hops > 0:
        forwarded = [
            part.strip()
            for part in request.headers.get("x-forwarded-for", "").split(",")
            if part.strip()
        ]
        if len(forwarded) >= hops:
            return forwarded[-hops]

    return get_remote_address(request)


# Configure rate limiter
# Uses in-memory storage by default, which is fine for single-instance deployment.
# For multi-instance, we'd need Redis.
limiter = Limiter(key_func=client_ip)

# Define rate limit constants
LIMIT_auth_send = "5/minute"  # Magic link requests
LIMIT_auth_verify = "10/minute"  # Login attempts
LIMIT_oauth_login = "10/minute"  # OAuth login attempts
LIMIT_generation_create = "10/minute"  # Generation requests per user (cost protection)

def get_limiter():
    return limiter
