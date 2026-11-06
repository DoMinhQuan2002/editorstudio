from __future__ import annotations

import hashlib
import math
import os
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import torch
import torchvision.transforms.functional as torchvision_functional

# BasicSR 1.4.2 imports this pre-0.18 torchvision module path.
sys.modules.setdefault("torchvision.transforms.functional_tensor", torchvision_functional)
from basicsr.archs.rrdbnet_arch import RRDBNet

from mediastudio.jobs.manager import Job
from mediastudio.storage.assets import Asset


ProgressCallback = Callable[[int, str, bool], None]


@dataclass(frozen=True, slots=True)
class ModelSpec:
    key: str
    file_name: str
    url: str
    sha256: str
    native_scale: int
    blocks: int
    max_grow_channels: int = 32


GENERAL_X2 = ModelSpec(
    key="general-x2",
    file_name="RealESRGAN_x2plus.pth",
    url="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth",
    sha256="49fafd45f8fd7aa8d31ab2a22d14d91b536c34494a5cfe31eb5d89c2fa266abb",
    native_scale=2,
    blocks=23,
)
GENERAL_X4 = ModelSpec(
    key="general-x4",
    file_name="RealESRGAN_x4plus.pth",
    url="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
    sha256="4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1",
    native_scale=4,
    blocks=23,
)
ANIME_X4 = ModelSpec(
    key="anime-x4",
    file_name="RealESRGAN_x4plus_anime_6B.pth",
    url="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
    sha256="f872d837d3c90ed2e05227bed711af5671a6fd1c9f7d7e91c911a61f155e99da",
    native_scale=4,
    blocks=6,
)

MAX_OUTPUT_PIXELS = 140_000_000
TILE_SIZES = (256, 128, 64)


class UpscaleError(RuntimeError):
    pass


class UpscaleService:
    def __init__(self, models_directory: Path) -> None:
        self.models_directory = models_directory
        self.models_directory.mkdir(parents=True, exist_ok=True)
        self._model_cache: dict[tuple[str, str], torch.nn.Module] = {}
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if self.device.type == "cuda":
            torch.backends.cudnn.benchmark = True

    @property
    def device_description(self) -> str:
        if self.device.type == "cuda":
            return f"CUDA · {torch.cuda.get_device_name(self.device)}"
        return "CPU · chế độ tương thích"

    def clear(self) -> None:
        self._model_cache.clear()
        if self.device.type == "cuda":
            torch.cuda.empty_cache()

    def run(
        self,
        job: Job,
        asset: Asset,
        *,
        scale: int,
        model_choice: str,
        reduce_noise: bool,
        sharpen: bool,
        output_format: str,
        output_directory: Path,
    ) -> tuple[Path, int, int, int]:
        if scale not in {2, 4, 8}:
            raise UpscaleError("Chỉ hỗ trợ mức phóng 2×, 4× hoặc 8×.")
        if output_format not in {"PNG", "JPG", "TIFF"}:
            raise UpscaleError("Định dạng đầu ra chưa được hỗ trợ.")

        output_width = asset.width * scale
        output_height = asset.height * scale
        if output_width * output_height > MAX_OUTPUT_PIXELS or max(output_width, output_height) > 24000:
            raise UpscaleError("Ảnh sau nâng cấp quá lớn để xử lý an toàn. Hãy giảm hệ số hoặc chọn ảnh nhỏ hơn.")

        spec, inference_scale = self._choose_model(model_choice, scale)
        self._set_job_progress(job, 3, "Đang đọc và chuẩn bị ảnh", False)
        image = cv2.imdecode(np.fromfile(asset.path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise UpscaleError("Không đọc được ảnh nguồn sau khi nhập.")

        if reduce_noise and image.dtype == np.uint8 and image.ndim == 3 and image.shape[2] >= 3:
            self._set_job_progress(job, 8, "Đang giảm nhiễu ảnh nguồn", False)
            alpha = image[:, :, 3] if image.shape[2] == 4 else None
            rgb = image[:, :, :3]
            denoised = cv2.fastNlMeansDenoisingColored(rgb, None, 3, 3, 7, 15)
            image = cv2.merge((*cv2.split(denoised), alpha)) if alpha is not None else denoised

        alpha_channel: np.ndarray | None = None
        if image.ndim == 2:
            color_bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            was_grayscale = True
        elif image.ndim == 3 and image.shape[2] == 4:
            color_bgr = image[:, :, :3]
            alpha_channel = image[:, :, 3]
            was_grayscale = False
        elif image.ndim == 3 and image.shape[2] == 3:
            color_bgr = image
            was_grayscale = False
        else:
            raise UpscaleError("Ảnh cần có 1, 3 hoặc 4 kênh màu.")

        if color_bgr.dtype not in (np.uint8, np.uint16):
            color_bgr = cv2.normalize(color_bgr, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        source_is_16bit = color_bgr.dtype == np.uint16
        max_value = 65535.0 if source_is_16bit else 255.0
        color_rgb = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2RGB)
        input_tensor = torch.from_numpy(np.ascontiguousarray(color_rgb.transpose(2, 0, 1))).float().unsqueeze(0)
        input_tensor.div_(max_value)

        self._set_job_progress(job, 12, "Đang nạp mô hình AI", False)
        engine = self._get_model(spec, self.device, job)
        try:
            output_rgb = self._infer_with_retries(engine, input_tensor, inference_scale, job, source_is_16bit)
        except torch.cuda.OutOfMemoryError as error:
            torch.cuda.empty_cache()
            raise UpscaleError("GPU hết bộ nhớ. Hãy đóng ứng dụng đang dùng GPU hoặc chọn ảnh/hệ số nhỏ hơn.") from error
        except RuntimeError as error:
            if "out of memory" in str(error).lower() and self.device.type == "cuda":
                torch.cuda.empty_cache()
                raise UpscaleError("GPU hết bộ nhớ. Hãy đóng ứng dụng đang dùng GPU hoặc chọn ảnh/hệ số nhỏ hơn.") from error
            raise

        if scale != inference_scale:
            self._set_job_progress(job, 82, "Đang căn kích thước đầu ra", False)
            output_rgb = cv2.resize(output_rgb, (output_width, output_height), interpolation=cv2.INTER_LANCZOS4)

        output_bgr = cv2.cvtColor(output_rgb, cv2.COLOR_RGB2BGR)
        if was_grayscale:
            output_bgr = cv2.cvtColor(output_bgr, cv2.COLOR_BGR2GRAY)
        if sharpen:
            self._set_job_progress(job, 87, "Đang áp dụng làm nét nhẹ", False)
            blur = cv2.GaussianBlur(output_bgr, (0, 0), sigmaX=0.8)
            output_bgr = cv2.addWeighted(output_bgr, 1.15, blur, -0.15, 0)

        if alpha_channel is not None:
            alpha_upscaled = cv2.resize(alpha_channel, (output_width, output_height), interpolation=cv2.INTER_LANCZOS4)
            output_bgr = cv2.merge((*cv2.split(output_bgr), alpha_upscaled))

        if output_format == "JPG" and output_bgr.ndim == 3 and output_bgr.shape[2] == 4:
            channel_max = 65535.0 if output_bgr.dtype == np.uint16 else 255.0
            alpha = output_bgr[:, :, 3:4].astype(np.float32) / channel_max
            rgb = output_bgr[:, :, :3].astype(np.float32)
            output_bgr = (rgb * alpha + channel_max * (1.0 - alpha)).round()
            if channel_max == 65535.0:
                output_bgr = (output_bgr / 257.0).round()
            output_bgr = output_bgr.clip(0, 255).astype(np.uint8)
        elif output_format == "JPG" and output_bgr.dtype == np.uint16:
            output_bgr = (output_bgr / 257.0).round().astype(np.uint8)

        extension = {"PNG": ".png", "JPG": ".jpg", "TIFF": ".tif"}[output_format]
        output_directory.mkdir(parents=True, exist_ok=True)
        output_path = output_directory / f"{Path(asset.file_name).stem}_upscaled_{scale}x{extension}"
        self._set_job_progress(job, 93, "Đang ghi tệp kết quả", False)
        parameters: list[int] = []
        if output_format == "JPG":
            parameters = [cv2.IMWRITE_JPEG_QUALITY, 95]
        elif output_format == "PNG":
            parameters = [cv2.IMWRITE_PNG_COMPRESSION, 3]
        success, encoded = cv2.imencode(extension, output_bgr, parameters)
        if not success:
            raise UpscaleError("Không thể mã hóa ảnh ở định dạng đã chọn.")
        encoded.tofile(output_path)
        size = output_path.stat().st_size
        return output_path, output_width, output_height, size

    @staticmethod
    def _choose_model(model_choice: str, requested_scale: int) -> tuple[ModelSpec, int]:
        if model_choice == "Real-ESRGAN Anime":
            return ANIME_X4, 4
        if model_choice != "Real-ESRGAN":
            raise UpscaleError("Mô hình được chọn không được hỗ trợ.")
        return (GENERAL_X2, 2) if requested_scale == 2 else (GENERAL_X4, 4)

    def _get_model(self, spec: ModelSpec, device: torch.device, job: Job) -> torch.nn.Module:
        cache_key = (spec.key, str(device))
        if cache_key in self._model_cache:
            return self._model_cache[cache_key]

        weight_path = self._ensure_weights(spec, job)
        self._set_job_progress(job, 15, "Đang khởi tạo mạng nơron", False)
        model = RRDBNet(
            num_in_ch=3,
            num_out_ch=3,
            num_feat=64,
            num_block=spec.blocks,
            num_grow_ch=spec.max_grow_channels,
            scale=spec.native_scale,
        )
        checkpoint = torch.load(weight_path, map_location="cpu", weights_only=True)
        state = checkpoint.get("params_ema", checkpoint.get("params", checkpoint))
        model.load_state_dict(state, strict=True)
        model.eval().to(device)
        if device.type == "cuda":
            model.half()
        self._model_cache[cache_key] = model
        return model

    def _ensure_weights(self, spec: ModelSpec, job: Job) -> Path:
        path = self.models_directory / spec.file_name
        if path.is_file() and path.stat().st_size > 1024 * 1024:
            with path.open("rb") as model_file:
                digest = hashlib.file_digest(model_file, "sha256").hexdigest()
            if digest == spec.sha256:
                return path
            path.unlink(missing_ok=True)

        temporary_path = path.with_suffix(path.suffix + ".part")
        try:
            request = urllib.request.Request(spec.url, headers={"User-Agent": "MediaStudio/0.1"})
            with urllib.request.urlopen(request, timeout=30) as response, temporary_path.open("wb") as destination:
                total_size = int(response.headers.get("Content-Length", "0"))
                downloaded = 0
                digest = hashlib.sha256()
                while chunk := response.read(1024 * 1024):
                    destination.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if total_size:
                        fraction = min(downloaded / total_size, 1.0)
                        self._set_job_progress(job, 5 + round(fraction * 9), f"Đang tải mô hình AI · {round(fraction * 100)}%", False)
                destination.flush()
                os.fsync(destination.fileno())
            if total_size and downloaded != total_size:
                raise UpscaleError("Tải mô hình AI chưa hoàn tất. Hãy thử lại khi có kết nối mạng.")
            if downloaded < 1024 * 1024:
                raise UpscaleError("Tệp mô hình tải về không hợp lệ.")
            if digest.hexdigest() != spec.sha256:
                raise UpscaleError("Trọng số mô hình không vượt kiểm tra toàn vẹn; hãy thử tải lại.")
            temporary_path.replace(path)
        except UpscaleError:
            temporary_path.unlink(missing_ok=True)
            raise
        except Exception as error:
            temporary_path.unlink(missing_ok=True)
            raise UpscaleError("Không tải được mô hình AI. Hãy kiểm tra kết nối mạng rồi thử lại.") from error
        return path

    def _infer_with_retries(
        self,
        model: torch.nn.Module,
        source: torch.Tensor,
        scale: int,
        job: Job,
        source_is_16bit: bool,
    ) -> np.ndarray:
        source_height, source_width = source.shape[-2:]
        last_error: RuntimeError | None = None
        for attempt, tile_size in enumerate(TILE_SIZES):
            try:
                return self._infer_tiled(model, source, scale, tile_size, job, source_is_16bit)
            except RuntimeError as error:
                if self.device.type != "cuda" or "out of memory" not in str(error).lower():
                    raise
                last_error = error
                torch.cuda.empty_cache()
                self._set_job_progress(job, max(12, job.progress), f"Ảnh lớn, đang thử lại với tile {TILE_SIZES[min(attempt + 1, len(TILE_SIZES) - 1)]} px", False)
        if last_error is not None:
            raise last_error
        raise UpscaleError(f"Không thể xử lý ảnh {source_width}×{source_height} px.")

    def _infer_tiled(
        self,
        model: torch.nn.Module,
        source: torch.Tensor,
        scale: int,
        tile_size: int,
        job: Job,
        source_is_16bit: bool,
    ) -> np.ndarray:
        source_height, source_width = source.shape[-2:]
        padding = 10
        tiles_x = math.ceil(source_width / tile_size)
        tiles_y = math.ceil(source_height / tile_size)
        total_tiles = tiles_x * tiles_y
        output_dtype = np.uint16 if source_is_16bit else np.uint8
        output = np.empty((source_height * scale, source_width * scale, 3), dtype=output_dtype)
        max_value = 65535.0 if source_is_16bit else 255.0

        for tile_index, (start_y, start_x) in enumerate(
            ((y, x) for y in range(0, source_height, tile_size) for x in range(0, source_width, tile_size)),
            start=1,
        ):
            end_y = min(start_y + tile_size, source_height)
            end_x = min(start_x + tile_size, source_width)
            crop_start_y = max(start_y - padding, 0)
            crop_start_x = max(start_x - padding, 0)
            crop_end_y = min(end_y + padding, source_height)
            crop_end_x = min(end_x + padding, source_width)
            tile = source[:, :, crop_start_y:crop_end_y, crop_start_x:crop_end_x].to(self.device)
            if self.device.type == "cuda":
                tile = tile.half()
            try:
                with torch.inference_mode():
                    enhanced = model(tile).float().clamp_(0, 1).squeeze(0).cpu().numpy()
            finally:
                del tile

            enhanced = np.transpose(enhanced, (1, 2, 0))
            crop_y0 = (start_y - crop_start_y) * scale
            crop_x0 = (start_x - crop_start_x) * scale
            crop_y1 = crop_y0 + (end_y - start_y) * scale
            crop_x1 = crop_x0 + (end_x - start_x) * scale
            enhanced = enhanced[crop_y0:crop_y1, crop_x0:crop_x1, :]
            output[start_y * scale:end_y * scale, start_x * scale:end_x * scale] = np.rint(enhanced * max_value).clip(0, max_value).astype(output_dtype)

            progress = 18 + round(60 * tile_index / total_tiles)
            self._set_job_progress(job, progress, f"AI đang xử lý tile {tile_index}/{total_tiles}", False)

        return output

    @staticmethod
    def _set_job_progress(job: Job, progress: int, stage: str, is_indeterminate: bool) -> None:
        job.update(progress=progress, stage=stage, is_indeterminate=is_indeterminate, state="processing")
