"""Integration wrapper around the exported ComfyUI workflow."""

from __future__ import annotations

# --- uvicorn/embedded safety: make sure __main__.__file__ exists ---
import os, sys, types
_main = sys.modules.get("__main__")
if _main is None:
    _main = types.ModuleType("__main__")
    sys.modules["__main__"] = _main
if not hasattr(_main, "__file__"):
    # best-effort: use the app’s file or argv[0]
    guess = __file__ if "__file__" in globals() else sys.argv[0] or "app.py"
    _main.__file__ = os.path.abspath(guess)


import asyncio
import base64
import importlib
import logging
from pathlib import Path
from typing import Iterable, Literal


logger = logging.getLogger(__name__)


class ComfyUIUnavailableError(RuntimeError):
    """Raised when the ComfyUI workflow cannot be initialised."""


def find_path(name: str, path: str | None = None) -> str | None:
    """Walk parent directories until the requested entry is found."""

    search_root = path or os.getcwd()
    if name in os.listdir(search_root):
        return os.path.join(search_root, name)

    parent_directory = os.path.dirname(search_root)
    if parent_directory == search_root:
        return None
    return find_path(name, parent_directory)


def add_comfyui_directory_to_sys_path() -> str | None:
    """Add the local ComfyUI checkout to ``sys.path`` if present."""

    comfy_root = find_path("ComfyUI")
    assert comfy_root and os.path.isdir(comfy_root), "ComfyUI repo not found"

    comfy_sub = os.path.join(comfy_root, "comfy")

    # 1) Remove any prior entries so we control the order cleanly
    sys.path = [p for p in sys.path if p not in (comfy_root, comfy_sub)]

    # 2) Prepend ONLY the repo root (not the comfy subdir)
    sys.path.insert(0, comfy_root)

    # 3) Ensure 'utils' refers to the package at /ComfyUI/utils (with __path__)
    utils_pkg = os.path.join(comfy_root, "utils")
    init_py   = os.path.join(utils_pkg, "__init__.py")
    if ("utils" not in sys.modules) or (not hasattr(sys.modules["utils"], "__path__")):
        spec = importlib.util.spec_from_file_location(
            "utils", init_py, submodule_search_locations=[utils_pkg]
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["utils"] = mod
        assert spec.loader is not None
        spec.loader.exec_module(mod)

    # 4) Force re-import of Comfy modules AFTER path & utils are correct
    for name in ("nodes", "execution", "server"):
        sys.modules.pop(name, None)


class _PlaceholderImplementation:
    """Fallback implementation used in tests when ComfyUI is unavailable."""

    supports_parallel_look_generation = False

    _PLACEHOLDER_PNG = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg=="
    )

    def __init__(self, output_dir: Path, reason: Exception | None = None) -> None:
        self._output_dir = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._reason = reason
        if reason:
            logger.warning("Using placeholder Comfy runner: %s", reason)
            
    async def initialize():
        pass

    async def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        product_images: Iterable[bytes],
        model_image: bytes,
        product_image_mime_types: Iterable[str] | None = None,
        model_image_mime_type: str | None = None,
        aspect: Literal["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "9:16", "16:9", "21:9"],
        look_index: int,
    ) -> bytes:
        await asyncio.sleep(0)
        output_path = self._output_dir / f"look-{look_index + 1}.png"
        output_path.write_bytes(self._PLACEHOLDER_PNG)
        return self._PLACEHOLDER_PNG

    @staticmethod
    def encode_base64(image_bytes: bytes) -> str:
        return base64.b64encode(image_bytes).decode("utf-8")


class ComfyWorkflowRunner:
    """Facade that chooses between the real Comfy workflow and the placeholder."""

    supports_parallel_look_generation = False

    def __init__(self, output_dir: str) -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

        try:
            implementation = self._load_comfy_impl()
        except Exception as exc:  # pragma: no cover - tests use placeholder
            implementation = _PlaceholderImplementation(self._output_dir, exc)

        # implementation = _PlaceholderImplementation(self._output_dir)
        self._impl = implementation
        
    async def initialize(self):
        if not isinstance(self._impl, _PlaceholderImplementation):
            await self._impl.ensure_init()
        pass

    def _load_comfy_impl(self):
        try:
            add_comfyui_directory_to_sys_path()
            module = importlib.import_module("ComfyUI.gemzy_workflow2")
        except ModuleNotFoundError as exc:  # pragma: no cover - depends on deployment
            raise ComfyUIUnavailableError(
                "ComfyUI workflow module not found"
            ) from exc

        try:
            workflow_cls = getattr(module, "GemzyWorkflow")
        except AttributeError as exc:  # pragma: no cover - deployment specific
            raise ComfyUIUnavailableError(
                "ComfyUI workflow module is missing GemzyWorkflow"
            ) from exc

        try:
            return workflow_cls(self._output_dir)
        except Exception as exc:  # pragma: no cover - runtime specific
            raise ComfyUIUnavailableError(
                "Failed to initialise ComfyUI workflow"
            ) from exc

    async def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        product_images: Iterable[bytes],
        model_image: bytes,
        product_image_mime_types: Iterable[str] | None = None,
        model_image_mime_type: str | None = None,
        aspect: Literal["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "9:16", "16:9", "21:9"],
        look_index: int,
    ) -> bytes:
        return await self._impl.generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            product_images=product_images,
            model_image=model_image,
            aspect=aspect,
            look_index=look_index,
        )

    def encode_base64(self, image_bytes: bytes) -> str:
        return self._impl.encode_base64(image_bytes)


__all__ = ["ComfyWorkflowRunner", "ComfyUIUnavailableError"]

