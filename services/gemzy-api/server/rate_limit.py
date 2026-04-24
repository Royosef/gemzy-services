"""Rate limiting configuration for the API."""
import os
from slowapi import Limiter
from slowapi.util import get_remote_address

# Configure rate limiter
# Uses in-memory storage by default, which is fine for single-instance deployment.
# For multi-instance, we'd need Redis.
limiter = Limiter(key_func=get_remote_address)

# Define rate limit constants
LIMIT_auth_send = "5/minute"  # Magic link requests
LIMIT_auth_verify = "10/minute"  # Login attempts
LIMIT_oauth_login = "10/minute"  # OAuth login attempts
LIMIT_generation_create = "10/minute"  # Generation requests per user (cost protection)

def get_limiter():
    return limiter
