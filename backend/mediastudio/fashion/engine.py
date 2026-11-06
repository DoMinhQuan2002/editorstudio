"""Qwen-Image-Edit engine for Fashion Studio.

Runs locally through Hugging Face diffusers (QwenImageEditPlusPipeline, multi-image input).
Heavy optional dependencies (torch, diffusers, ...) are imported lazily so the rest of
the backend starts without them; status() explains what is missing.

Environment variables
  MEDIASTUDIO_QWEN_EDIT_MODEL   repo id or local folder   (default Qwen/Qwen-Image-Edit-2511)
  MEDIASTUDIO_QWEN_MEMORY       auto | gpu | offload | low (default auto, picked from VRAM)
  MEDIASTUDIO_QWEN_LIGHTNING    repo id of a Lightning LoRA (optional, fewer steps)
  MEDIASTUDIO_QWEN_LIGHTNING_FILE  weight file name inside that repo
  HF_HOME                       where model files are cached (default under the app data folder)
"""
from __future__ import annotations

import importlib.util
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from PIL import Image

from .prompts import NEGATIVE_PROMPT, FashionRequest, build_prompt

logger = logging.getLogger("mediastudio.fashion")

DEFAULT_MODEL = "Qwen/Qwen-Image-Edit-2511"
REQUIRED_PACKAGES = ("torch", "diffusers", "transformers", "accelerate", "huggingface_hub")
MAX_SIDE = 1328          # Qwen-Image native resolution around 1 megapixel
LIGHTNING_STEPS = 8
FULL_STEPS = 40


class FashionError(Exception):
    def __init__(self, message: str, code: str = "FASHION_ERROR") -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class FashionResult:
    image: Image.Image
    prompt: str
    seed: int
    steps: int
    seconds: float
    memory_mode: str


# Weights downloaded by download-qwen-model.bat live inside the project:  <project>/models/Qwen-Image-Edit-2511
LOCAL_MODEL_DIR = Path(__file__).resolve().parents[3] / "models" / "Qwen-Image-Edit-2511"


def _local_model() -> str:
    return str(LOCAL_MODEL_DIR) if (LOCAL_MODEL_DIR / "model_index.json").is_file() else ""


def _weights_complete(folder: Path) -> bool:
    """True when every weight shard listed by the sharded index files is on disk (download finished)."""
    import json
    if not (folder / "model_index.json").is_file():
        return False
    for part in ("transformer", "text_encoder", "vae"):
        sub = folder / part
        indexes = list(sub.glob("*.safetensors.index.json"))
        if indexes:
            shards = set(json.loads(indexes[0].read_text(encoding="utf-8"))["weight_map"].values())
            if not all((sub / name).is_file() for name in shards):
                return False
        elif not list(sub.glob("*.safetensors")):
            return False
    return True


def _has(package: str) -> bool:
    return importlib.util.find_spec(package) is not None


class QwenFashionEngine:
    def __init__(self, cache_directory: Path) -> None:
        self.model_id = os.environ.get("MEDIASTUDIO_QWEN_EDIT_MODEL", "").strip() or _local_model() or DEFAULT_MODEL
        self.memory_setting = os.environ.get("MEDIASTUDIO_QWEN_MEMORY", "auto").strip().lower() or "auto"
        self.lightning_repo = os.environ.get("MEDIASTUDIO_QWEN_LIGHTNING", "").strip()
        self.lightning_file = os.environ.get("MEDIASTUDIO_QWEN_LIGHTNING_FILE", "").strip()
        self.cache_directory = cache_directory
        os.environ.setdefault("HF_HOME", str(cache_directory))
        self._pipeline = None
        self._memory_mode = ""
        self._lightning_loaded = False
        self._lock = Lock()

    # ------------------------------------------------------------------ status
    def _gpu(self) -> tuple[bool, str, float]:
        if not _has("torch"):
            return False, "", 0.0
        import torch
        if not torch.cuda.is_available():
            return False, "", 0.0
        props = torch.cuda.get_device_properties(0)
        return True, props.name, round(props.total_memory / 1024 ** 3, 1)

    def _pick_memory_mode(self, vram_gb: float) -> str:
        if self.memory_setting in {"gpu", "offload", "low"}:
            return self.memory_setting
        if vram_gb >= 40:
            return "gpu"
        if vram_gb >= 16:
            return "offload"
        return "low"

    def model_downloaded(self) -> bool:
        if Path(self.model_id).is_dir():
            return _weights_complete(Path(self.model_id))
        if not _has("huggingface_hub"):
            return False
        from huggingface_hub import try_to_load_from_cache
        found = try_to_load_from_cache(self.model_id, "model_index.json")
        return isinstance(found, str)

    def status(self) -> dict[str, object]:
        missing = [name for name in REQUIRED_PACKAGES if not _has(name)]
        has_cuda, gpu_name, vram = self._gpu() if "torch" not in missing else (False, "", 0.0)
        mode = self._pick_memory_mode(vram) if has_cuda else "cpu"
        downloaded = not missing and self.model_downloaded()
        if missing:
            state, message = "missing_packages", (
                "Chưa cài thư viện AI cho Fashion Studio: " + ", ".join(missing)
                + ". Chạy backend\\setup-fashion.ps1 rồi khởi động lại app.")
        elif not has_cuda:
            state, message = "no_gpu", "Không tìm thấy GPU NVIDIA (CUDA). Qwen-Image cần GPU để chạy được trong thời gian hợp lý."
        elif mode == "low" and not _has("bitsandbytes"):
            state, message = "missing_packages", (
                f"GPU {gpu_name} có {vram} GB VRAM: cần chế độ tiết kiệm bộ nhớ (thư viện bitsandbytes). "
                "Chạy backend\\setup-fashion.ps1 để cài.")
        elif not downloaded:
            state, message = "model_missing", (
                f"Chưa tải model {self.model_id}. Bấm \"Tải model\" (khoảng 40–60 GB, chỉ tải một lần).")
        else:
            state, message = "ready", f"Sẵn sàng trên {gpu_name} ({vram} GB VRAM, chế độ {mode})."
        return {
            "state": state,
            "message": message,
            "model": self.model_id,
            "missingPackages": missing,
            "gpu": gpu_name,
            "vramGb": vram,
            "memoryMode": mode,
            "modelDownloaded": downloaded,
            "modelLoaded": self._pipeline is not None,
            "lightning": bool(self.lightning_repo),
        }

    # ------------------------------------------------------------------ download
    def download(self, progress=None) -> None:
        if Path(self.model_id).is_dir():
            return
        from huggingface_hub import snapshot_download
        if self.model_id == DEFAULT_MODEL:
            # Download into the project folder so the weights sit next to the app.
            snapshot_download(self.model_id, local_dir=str(LOCAL_MODEL_DIR))
            self.model_id = str(LOCAL_MODEL_DIR)
            return
        if progress:
            progress("Đang tải model từ Hugging Face (có thể mất nhiều giờ tùy mạng)…")
        snapshot_download(self.model_id)
        if self.lightning_repo:
            if progress:
                progress("Đang tải gói tăng tốc Lightning…")
            snapshot_download(self.lightning_repo, allow_patterns=[self.lightning_file] if self.lightning_file else None)

    # ------------------------------------------------------------------ load
    def _load(self, progress=None):
        if self._pipeline is not None:
            return self._pipeline
        import torch
        from diffusers import QwenImageEditPlusPipeline

        _, gpu_name, vram = self._gpu()
        mode = self._pick_memory_mode(vram)
        dtype = torch.bfloat16
        if progress:
            progress(f"Đang nạp model vào bộ nhớ (chế độ {mode}) — lần đầu có thể mất vài phút…")

        if mode == "low":
            # 4-bit transformer and text encoder so the model fits small GPUs, then stream to the GPU.
            from diffusers import BitsAndBytesConfig as DiffusersBnb, QwenImageTransformer2DModel
            from transformers import BitsAndBytesConfig as TransformersBnb, Qwen2_5_VLForConditionalGeneration
            transformer = QwenImageTransformer2DModel.from_pretrained(
                self.model_id, subfolder="transformer", torch_dtype=dtype,
                quantization_config=DiffusersBnb(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                 bnb_4bit_compute_dtype=dtype))
            text_encoder = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                self.model_id, subfolder="text_encoder", torch_dtype=dtype,
                quantization_config=TransformersBnb(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                    bnb_4bit_compute_dtype=dtype))
            pipe = QwenImageEditPlusPipeline.from_pretrained(
                self.model_id, transformer=transformer, text_encoder=text_encoder, torch_dtype=dtype)
            pipe.enable_model_cpu_offload()
        else:
            pipe = QwenImageEditPlusPipeline.from_pretrained(self.model_id, torch_dtype=dtype)
            if mode == "gpu":
                pipe.to("cuda")
            else:
                pipe.enable_model_cpu_offload()
        pipe.set_progress_bar_config(disable=True)

        if self.lightning_repo:
            try:
                pipe.load_lora_weights(self.lightning_repo, weight_name=self.lightning_file or None)
                self._lightning_loaded = True
            except Exception:
                logger.exception("Could not load Lightning LoRA %s; using full steps", self.lightning_repo)
        self._pipeline, self._memory_mode = pipe, mode
        logger.info("Qwen-Image-Edit loaded: %s on %s (%s GB, %s)", self.model_id, gpu_name, vram, mode)
        return pipe

    def unload(self) -> None:
        with self._lock:
            self._pipeline = None
            if _has("torch"):
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()

    # ------------------------------------------------------------------ run
    @staticmethod
    def _prepare(image: Image.Image) -> Image.Image:
        image = image.convert("RGB")
        scale = MAX_SIDE / max(image.size)
        if scale < 1:
            image = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
        return image

    def run(self, request: FashionRequest, images: list[Image.Image], seed: int | None = None,
            steps: int | None = None, progress=None, step_progress=None) -> FashionResult:
        state = self.status()
        if state["state"] != "ready":
            raise FashionError(str(state["message"]), str(state["state"]).upper())
        prompt = build_prompt(request)
        import torch

        with self._lock:
            pipe = self._load(progress)
            use_steps = steps or (LIGHTNING_STEPS if self._lightning_loaded else FULL_STEPS)
            cfg = 1.0 if self._lightning_loaded else 4.0
            used_seed = seed if seed is not None else int(time.time()) % 2_147_483_647
            generator = torch.Generator(device="cpu").manual_seed(used_seed)

            def on_step(pipeline, index, timestep, kwargs):
                if step_progress:
                    step_progress(index + 1, use_steps)
                return kwargs

            if progress:
                progress("Đang tạo ảnh…")
            started = time.perf_counter()
            try:
                output = pipe(
                    image=[self._prepare(img) for img in images],
                    prompt=prompt,
                    negative_prompt=NEGATIVE_PROMPT if cfg > 1 else " ",
                    true_cfg_scale=cfg,
                    guidance_scale=1.0,
                    num_inference_steps=use_steps,
                    num_images_per_prompt=1,
                    generator=generator,
                    callback_on_step_end=on_step,
                )
            except torch.cuda.OutOfMemoryError as error:
                torch.cuda.empty_cache()
                raise FashionError(
                    "GPU hết bộ nhớ. Đóng các ứng dụng dùng GPU khác hoặc đặt MEDIASTUDIO_QWEN_MEMORY=low rồi thử lại.",
                    "OUT_OF_MEMORY") from error
            return FashionResult(output.images[0], prompt, used_seed, use_steps,
                                 time.perf_counter() - started, self._memory_mode)
