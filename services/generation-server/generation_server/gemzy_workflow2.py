"""ComfyUI workflow generated from the exported Gemzy pipeline."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import tempfile
from pathlib import Path
from typing import Any, Iterable, List, Literal, Mapping, Sequence

try:  # pragma: no cover - requires GPU runtime
    import torch
except Exception as exc:  # pragma: no cover - used to detect availability
    torch = None  # type: ignore[assignment]
    _TORCH_IMPORT_ERROR = exc
else:  # pragma: no cover - only executed in GPU environments
    _TORCH_IMPORT_ERROR = None

logger = logging.getLogger(__name__)

BASE_DIMS = {
    "1:1": {"w": 1024, "h": 1024},
    "2:3": {"w": 912, "h": 1368},
    "3:2": {"w": 1368, "h": 912},
    "3:4": {"w": 1024, "h": 1368},
    "4:3": {"w": 1184, "h": 888},
    "4:5": {"w": 912, "h": 1144},
    "9:16": {"w": 768, "h": 1368},
    "16:9": {"w": 1392, "h": 752},
    "21:9": {"w": 1752, "h": 752},
}


def get_value_at_index(obj: Sequence | Mapping, index: int) -> Any:
    """Returns the value at ``index`` for ComfyUI node outputs."""

    try:
        return obj[index]  # type: ignore[index]
    except KeyError:
        return obj["result"][index]  # type: ignore[index]


def find_path(name: str, path: str | None = None) -> str | None:
    """Search upwards from ``path`` (defaulting to this file) for ``name``."""

    search_root = Path(path or __file__).resolve()
    if search_root.is_file():
        search_root = search_root.parent

    if name in os.listdir(search_root):
        return str(search_root / name)

    parent = search_root.parent
    if parent == search_root:
        return None
    return find_path(name, str(parent))


def add_extra_model_paths() -> None:
    """Parse ``extra_model_paths.yaml`` so ComfyUI can resolve custom assets."""

    try:  # pragma: no cover - depends on ComfyUI packaging
        from main import load_extra_path_config  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover - alternate ComfyUI layout
        from utils.extra_config import load_extra_path_config  # type: ignore[import-not-found]

    extra_model_paths = find_path("extra_model_paths.yaml")
    if extra_model_paths:
        load_extra_path_config(extra_model_paths)
    else:  # pragma: no cover - deployment specific
        logger.warning("extra_model_paths.yaml not found; using default model paths")


async def import_custom_nodes() -> None:
    """Initialise ComfyUI custom nodes as expected by the exported workflow."""

    import execution  # type: ignore[import-not-found]
    from nodes import init_extra_nodes  # type: ignore[import-not-found]
    import server  # type: ignore[import-not-found]
    import inspect  # type: ignore[import-not-found]

    loop = asyncio.get_running_loop()
    srv = server.PromptServer(loop)  # sets up server globals some nodes expect
    execution.PromptQueue(srv)  # sets up queue globals

    res = init_extra_nodes(init_custom_nodes=True, init_api_nodes=True)
    if inspect.isawaitable(res):
        await res


class GemzyWorkflow:
    """Wrapper around the ComfyUI workflow exported for Gemzy."""

    def __init__(self, output_dir: str | Path) -> None:
        if torch is None:
            raise RuntimeError(
                "PyTorch is not available; cannot initialise ComfyUI workflow"
            ) from _TORCH_IMPORT_ERROR

        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

        self.initialized = False

    async def ensure_init(self):
        from nodes import NODE_CLASS_MAPPINGS  # type: ignore[import-not-found]

        self._nodes = NODE_CLASS_MAPPINGS

        add_extra_model_paths()
        await import_custom_nodes()

        try:
            self._prepare_static_nodes()
        except Exception as exc:  # pragma: no cover - runtime specific
            raise RuntimeError("Failed to bootstrap ComfyUI workflow") from exc

    async def generate(
        self,
        prompt: str,
        negative_prompt: str,
        product_images: Iterable[bytes],
        model_image: bytes,
        aspect: Literal["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "9:16", "16:9", "21:9"],
        look_index: int,
    ) -> bytes:
        if not self.initialized:
            await self.ensure_init()

        return await asyncio.to_thread(
            self._generate_sync,
            prompt,
            negative_prompt,
            list(product_images),
            model_image,
            aspect,
            look_index,
        )

    def encode_base64(self, image_bytes: bytes) -> str:
        import base64

        return base64.b64encode(image_bytes).decode("utf-8")

    # -------------------------------------------------------------------------------------
    # Internal helpers mirroring the exported script
    # -------------------------------------------------------------------------------------

    def _prepare_static_nodes(self) -> None:
        with torch.inference_mode():
            self._unetloader = self._nodes["UNETLoader"]()
            self._unet = get_value_at_index(
                self._unetloader.load_unet(
                    unet_name="qwen_image_edit_2509_fp8_e4m3fn.safetensors",
                    weight_dtype="default",
                ),
                0,
            )

            self._cliploader = self._nodes["CLIPLoader"]()
            self._clip = get_value_at_index(
                self._cliploader.load_clip(
                    clip_name="qwen_2.5_vl_7b_fp8_scaled.safetensors",
                    type="qwen_image",
                    device="default",
                ),
                0,
            )

            self._vaeloader = self._nodes["VAELoader"]()
            self._vae = get_value_at_index(
                self._vaeloader.load_vae(vae_name="qwen_image_vae.safetensors"),
                0,
            )

            self._loraloader = self._nodes["LoraLoaderModelOnly"]()
            self._model = get_value_at_index(
                self._loraloader.load_lora_model_only(
                    lora_name="Qwen-Image-Lightning-4steps-V1.0.safetensors",
                    strength_model=1,
                    model=self._unet,
                ),
                0,
            )

            self._modelsamplingauraflow = self._nodes["ModelSamplingAuraFlow"]()
            self._cfgnorm = self._nodes["CFGNorm"]()
            self._imagescaletototalpixels = self._nodes["ImageScaleToTotalPixels"]()
            self._textencode = self._nodes["TextEncodeQwenImageEditPlus"]()
            self._ksampler = self._nodes["KSampler"]()
            self._vaedecode = self._nodes["VAEDecode"]()
            self._easycolor = self._nodes["EasyColorCorrection"]()
            self._loadimage_cls = self._nodes["LoadImage"]
            self._latent_cls = self._nodes["EmptyHunyuanLatentVideo"]
            self._saveimage_cls = self._nodes.get("SaveImage")

    def _generate_sync(
        self,
        prompt: str,
        negative_prompt: str,
        product_images: List[bytes],
        model_image: bytes,
        aspect: Literal["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "9:16", "16:9", "21:9"],
        look_index: int,
    ) -> bytes:
        import folder_paths

        if not product_images:
            raise ValueError("At least one product image is required")
        print("folder_paths", folder_paths.get_input_directory())
        folder_paths.set_input_directory(self._output_dir)
        print("folder_paths2", folder_paths.get_input_directory())

        with tempfile.TemporaryDirectory() as tmpdir:
            # tmp_dir = Path(tmpdir)
            tmp_dir = self._output_dir
            model_path = tmp_dir / "model.png"
            model_path.write_bytes(model_image)

            product_paths: List[Path] = []
            for idx, image_bytes in enumerate(product_images):
                product_path = tmp_dir / f"product-{idx}.png"
                product_path.write_bytes(image_bytes)
                product_paths.append(product_path)

            output_path = self._output_dir / f"look-{look_index + 1}.png"

            with torch.inference_mode():
                loadimage = self._loadimage_cls()
                model_loaded = loadimage.load_image(image=str(model_path))
                product_loaded = loadimage.load_image(image=str(product_paths[0]))
                reference_loaded = loadimage.load_image(
                    image=str(
                        product_paths[1] if len(product_paths) > 1 else product_paths[0]
                    )
                )

                scaled_model = self._imagescaletototalpixels.EXECUTE_NORMALIZED(
                    upscale_method="lanczos",
                    megapixels=1,
                    image=get_value_at_index(model_loaded, 0),
                )
                scaled_product = self._imagescaletototalpixels.EXECUTE_NORMALIZED(
                    upscale_method="lanczos",
                    megapixels=2.0,
                    image=get_value_at_index(product_loaded, 0),
                )

                dims = BASE_DIMS.get(aspect)

                latent = self._latent_cls().generate(
                    width=dims["w"],
                    height=dims["h"],
                    length=1,
                    batch_size=1,
                )

                sampling_model = self._modelsamplingauraflow.patch_aura(
                    shift=3,
                    model=self._model,
                )

                cfg_model = self._cfgnorm.EXECUTE_NORMALIZED(
                    strength=1.0000000000000002,
                    model=get_value_at_index(sampling_model, 0),
                )

                positive = self._textencode.EXECUTE_NORMALIZED(
                    prompt=prompt,
                    clip=self._clip,
                    vae=self._vae,
                    image1=get_value_at_index(scaled_model, 0),
                    image2=get_value_at_index(scaled_product, 0),
                )

                negative = self._textencode.EXECUTE_NORMALIZED(
                    prompt=negative_prompt or "",
                    clip=self._clip,
                    vae=self._vae,
                    image1=get_value_at_index(scaled_model, 0),
                    image2=get_value_at_index(scaled_product, 0),
                )

                samples = self._ksampler.sample(
                    seed=random.randint(1, 2**64 - 1),
                    steps=4,
                    cfg=1,
                    sampler_name="euler_cfg_pp",
                    scheduler="simple",
                    denoise=1,
                    model=get_value_at_index(cfg_model, 0),
                    positive=get_value_at_index(positive, 0),
                    negative=get_value_at_index(negative, 0),
                    latent_image=get_value_at_index(latent, 0),
                )

                decoded = self._vaedecode.decode(
                    samples=get_value_at_index(samples, 0),
                    vae=self._vae,
                )

                adjusted = self._easycolor.run(
                    mode="Auto",
                    reference_strength=0.3,
                    extract_palette=False,
                    lock_input_image=True,
                    ai_analysis=True,
                    adjust_for_skin_tone=False,
                    white_balance_strength=0,
                    enhancement_strength=0.2,
                    pop_factor=0.7,
                    effect_strength=0.6,
                    warmth=0,
                    vibrancy=0,
                    contrast=0,
                    brightness=0,
                    tint=0,
                    preset="Natural Portrait",
                    variation=0,
                    lift=0,
                    gamma=0,
                    gain=0,
                    noise=0,
                    skin_tone_adjustment=0,
                    sky_adjustment=0,
                    foliage_adjustment=0,
                    selective_hue_shift=0,
                    selective_saturation=0,
                    selective_strength=1,
                    colorize_strength=0.8,
                    skin_warmth=0.3,
                    sky_saturation=0.6,
                    vegetation_green=0.5,
                    sepia_tone=0,
                    colorize_mode="deep_learning",
                    force_colorize=False,
                    use_gpu=True,
                    image=get_value_at_index(decoded, 0),
                    reference_image=get_value_at_index(reference_loaded, 0),
                )

                final_image = adjusted

                image_tensor = get_value_at_index(final_image, 0)

                if self._saveimage_cls is not None:
                    saveimage = self._saveimage_cls()
                    save_result = saveimage.save_images(
                        images=image_tensor, filename_prefix=f"look-{look_index + 1}"
                    )
                    paths = self._saved_image_paths(save_result)
                    data = paths[0].read_bytes()
                    return data

                return self._tensor_to_png(image_tensor)

    def _saved_image_paths(self, save_result) -> List[Path]:
        """
        Turn the object returned by save_images(...) into absolute Paths.
        """
        import folder_paths

        paths = []
        base = Path("ComfyUI") / Path(folder_paths.get_output_directory())

        for img in save_result["ui"]["images"]:
            sub = img.get("subfolder") or ""  # subfolder can be "" or None
            name = img["filename"]

            print("\n\nPATH: \n", base, "\n", sub, "\n", name)
            paths.append(base / sub / name)

        return paths

    def _tensor_to_png(self, tensor: Any) -> bytes:
        try:  # pragma: no cover - optional dependency
            import numpy as np  # type: ignore[import-not-found]
            from PIL import Image  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - serialisation requires Pillow
            raise RuntimeError(
                "Pillow is required to serialise workflow outputs"
            ) from exc

        if hasattr(tensor, "cpu"):
            tensor = tensor.cpu()
        array = tensor.numpy()
        if array.ndim == 4:
            array = array[0]
        array = (array * 255).clip(0, 255).astype("uint8")
        if array.shape[0] in (1, 3):
            array = array.transpose(1, 2, 0)

        image = Image.fromarray(array)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            image.save(tmp.name, format="PNG")
            tmp.seek(0)
            data = tmp.read()
        Path(tmp.name).unlink(missing_ok=True)
        return data


__all__ = ["GemzyWorkflow", "get_value_at_index", "import_custom_nodes"]
