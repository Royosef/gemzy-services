"""Test fixtures and compatibility shims."""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:  # pragma: no cover - prefer the real implementation when available
    from postgrest.exceptions import APIError as _APIError  # type: ignore
except Exception:  # pragma: no cover - fallback for environments without postgrest deps
    class _APIError(Exception):
        def __init__(self, message: str | None = None, code: int | str | None = None):
            super().__init__(message or "")
            self.code = code

    exceptions_module = types.ModuleType("postgrest.exceptions")
    exceptions_module.APIError = _APIError
    sys.modules.setdefault("postgrest.exceptions", exceptions_module)

    class _APIResponse(dict):
        pass

    base_module = types.ModuleType("postgrest")
    base_module.exceptions = exceptions_module
    base_module.APIError = _APIError
    base_module.APIResponse = _APIResponse
    sys.modules.setdefault("postgrest", base_module)
else:
    sys.modules.setdefault("postgrest.exceptions", sys.modules["postgrest.exceptions"])


try:  # pragma: no cover - prefer the real implementation when available
    import slowapi  # type: ignore  # noqa: F401
except Exception:  # pragma: no cover - fallback for environments without slowapi
    slowapi_module = types.ModuleType("slowapi")
    slowapi_util_module = types.ModuleType("slowapi.util")

    class _Limiter:
        def __init__(self, *args, **kwargs):
            pass

        def limit(self, *_args, **_kwargs):
            def decorator(fn):
                return fn

            return decorator

    def _get_remote_address(_request):
        return "test"

    slowapi_module.Limiter = _Limiter
    slowapi_util_module.get_remote_address = _get_remote_address
    sys.modules.setdefault("slowapi", slowapi_module)
    sys.modules.setdefault("slowapi.util", slowapi_util_module)
