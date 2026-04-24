"""Test fixtures and compatibility shims."""

from __future__ import annotations

import sys
import types

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
