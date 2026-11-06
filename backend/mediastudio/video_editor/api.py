from __future__ import annotations

import hmac
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
import threading
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from mediastudio.video_editor.media_selection import (
    SelectionPayloadRequest, TemplateProcessingRequest, prepare_payload,
)
from mediastudio.video_editor.catalog import get_template, list_templates
from mediastudio.video_editor.composition import CompositionGraphError, build_composition_graph
from mediastudio.video_editor.composition_renderer import render_composition_project, render_preview_frame
from mediastudio.video_editor.cutout import BackgroundRemovalError, ensure_background_removed_image
from mediastudio.video_editor.diagnostics import video_request_id
from mediastudio.video_editor.ffmpeg import FFmpegToolchain, FFmpegUnavailableError
from mediastudio.video_editor.jobs import VideoJob, VideoJobManager
from mediastudio.video_editor.models import (
    CreateBlankProjectRequest, CreateProjectRequest, RenderRequest, VideoCreatorExportRequest,
)
from mediastudio.video_editor.project_v2 import (
    TIMEBASE, TimelineEngineV2, VideoProjectV2, apply_api_compatibility_projection, project_api_payload,
    to_legacy_project,
)
from mediastudio.video_editor.template_compiler import TemplateCompilerError, compile_template
from mediastudio.video_editor.renderer import VideoRenderError
from mediastudio.video_editor.storage import (
    MAX_MEDIA_BYTES, ProjectRevisionConflict, VideoMediaStore, VideoProjectStore,
)


logger = logging.getLogger("mediastudio.video_editor")
ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
WINDOWS_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_FILENAME = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE)
PROCESSING_STAGE_TIMEOUT_SECONDS = 30
BACKGROUND_REMOVAL_STAGE_TIMEOUT_SECONDS = 90
PROCESSING_TOTAL_TIMEOUT_SECONDS = 120
# Cutout cost grows with the number of overlay images and with the chosen model,
# so the background-removal stage gets a per-image budget instead of one flat
# ceiling. Results are cached per asset, so this budget only applies the first
# time a given image is cut out.
BACKGROUND_REMOVAL_SECONDS_PER_IMAGE = 75


class TemplateProcessingTimeoutError(TimeoutError):
    pass


def _preview_proxy_dimensions(width: int, height: int, max_width: int = 540,
                              max_height: int = 960) -> tuple[int, int]:
    """Fit an even-dimension playback proxy inside its size limits without distortion."""
    if min(width, height, max_width, max_height) <= 0:
        raise ValueError("Canvas and preview limits must be positive.")
    scale = min(1.0, max_width / width, max_height / height)
    proxy_width = max(2, int(round((width * scale) / 2) * 2))
    proxy_height = max(2, int(round((height * scale) / 2) * 2))
    return proxy_width, proxy_height


def _template_version(project: VideoProjectV2) -> str | None:
    value = project.template_metadata.get("templateDefinitionVersion")
    return value if isinstance(value, str) and value.strip() else None


def _composition_has_audio(graph) -> bool:
    solo_audio = any(track.kind == "audio" and track.solo and not track.muted for track in graph.tracks)
    has_audio = any(track.kind == "audio" and clip.enabled and clip.attributes.get("volume", 1.0) > 0
                    for track in graph.tracks for clip in track.clips)
    if not has_audio and not solo_audio:
        has_audio = any(track.kind == "visual" and clip.enabled and clip.media_has_audio
                        and clip.attributes.get("audioVolume", 1.0) > 0
                        for track in graph.tracks for clip in track.clips)
    return has_audio or solo_audio


def _export_capability_payload(project: VideoProjectV2, graph, ffmpeg: FFmpegToolchain) -> dict[str, object]:
    capabilities = ffmpeg.capabilities()
    has_audio = _composition_has_audio(graph)
    reasons: list[str] = []
    if not capabilities.get("available") or not capabilities.get("h264Encoding"):
        reasons.append("Backend cần FFmpeg/FFprobe và encoder H.264 (libx264) để xuất MP4.")
    if has_audio and not capabilities.get("aacEncoding"):
        reasons.append("Composition có audio nhưng backend không có encoder AAC.")
    has_text = any(track.kind == "text" and any(clip.enabled for clip in track.clips)
                   for track in graph.tracks)
    if has_text and not capabilities.get("textOverlay"):
        reasons.append("Composition có text layer nhưng FFmpeg drawtext chưa khả dụng.")
    template_version = _template_version(project)
    if not template_version:
        reasons.append("Bản nháp thiếu Template Definition Version đã commit.")
    bindings = project.template_metadata.get("templateBindings", {})
    if not isinstance(bindings, dict):
        bindings = {}
    bindings = {str(key): str(value) for key, value in bindings.items()}
    return {
        "canExport": not reasons,
        "errorMessage": " ".join(reasons) if reasons else None,
        "draftProjectId": project.project_id,
        "draftRevision": project.revision,
        "templateId": project.template_id,
        "templateVersion": template_version,
        "compositionFingerprint": graph.source_fingerprint,
        "compositionReference": f"/api/v1/video/projects/{project.project_id}",
        "mediaBindings": bindings,
        "width": graph.width,
        "height": graph.height,
        "frameRateNumerator": graph.frame_rate_numerator,
        "frameRateDenominator": graph.frame_rate_denominator,
        "durationTicks": graph.duration_ticks,
        "timebase": graph.timebase,
        "qualities": ["standard", "high"],
        "format": "mp4",
        "videoCodec": "h264",
        "audioCodec": "aac" if has_audio else None,
        "hasAudio": has_audio,
        "supportsCancel": True,
    }


def _validated_export_stem(file_name: str) -> str:
    if file_name != file_name.strip() or not file_name:
        raise ValueError("Tên file không được để trống hoặc có khoảng trắng ở đầu/cuối.")
    stem = file_name[:-4] if file_name.lower().endswith(".mp4") else file_name
    if not stem or stem in {".", ".."}:
        raise ValueError("Tên file không hợp lệ.")
    if stem.lower().endswith(".mp4"):
        raise ValueError("Tên file không được lặp đuôi .mp4.")
    if WINDOWS_INVALID_FILENAME.search(stem) or stem.endswith((".", " ")):
        raise ValueError("Tên file chứa ký tự không hợp lệ trên Windows.")
    if WINDOWS_RESERVED_FILENAME.fullmatch(stem):
        raise ValueError("Tên file trùng tên thiết bị dành riêng của Windows.")
    if len(stem) > 120:
        raise ValueError("Tên file vượt quá 120 ký tự.")
    return stem


def _publish_export_file(rendered_path: Path, target_path: Path, overwrite: bool) -> None:
    descriptor, staging_name = tempfile.mkstemp(
        prefix=f".{target_path.stem}.", suffix=".partial.mp4", dir=target_path.parent,
    )
    staging_path = Path(staging_name)
    try:
        with os.fdopen(descriptor, "wb") as destination, rendered_path.open("rb") as source:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
            destination.flush()
            os.fsync(destination.fileno())
        if staging_path.stat().st_size != rendered_path.stat().st_size or staging_path.stat().st_size <= 0:
            raise OSError("Không thể ghi đủ dữ liệu video vào thư mục đích.")
        if overwrite:
            os.replace(staging_path, target_path)
        elif os.name == "nt":
            # Windows rename is atomic and refuses to replace an existing file.
            os.rename(staging_path, target_path)
        else:
            # A hard-link publishes a fully written file without a race that
            # could overwrite an output created by another process.
            os.link(staging_path, target_path)
            staging_path.unlink()
    finally:
        staging_path.unlink(missing_ok=True)


def _probe_and_decode_export(path: Path, graph, ffmpeg: FFmpegToolchain, job: VideoJob,
                             has_audio: bool) -> dict[str, object]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise VideoRenderError("File MP4 chưa tồn tại hoặc có dung lượng bằng 0.")
    if not ffmpeg.ffprobe or not ffmpeg.ffmpeg:
        raise FFmpegUnavailableError("Cần FFprobe và FFmpeg để xác minh output.")
    try:
        probe = subprocess.run(
            [ffmpeg.ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise VideoRenderError(f"Không thể chạy FFprobe: {error}") from error
    if probe.returncode != 0:
        raise VideoRenderError("FFprobe không đọc được container hoặc luồng video đầu ra.")
    try:
        payload = json.loads(probe.stdout)
    except json.JSONDecodeError as error:
        raise VideoRenderError("FFprobe trả dữ liệu không hợp lệ.") from error
    format_info = payload.get("format", {})
    if "mp4" not in str(format_info.get("format_name", "")).lower():
        raise VideoRenderError("Output không phải container MP4.")
    streams = payload.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if video is None or video.get("codec_name") != "h264":
        raise VideoRenderError("Output thiếu luồng H.264 hợp lệ.")
    if (video.get("width"), video.get("height")) != (graph.width, graph.height):
        raise VideoRenderError("Độ phân giải MP4 không khớp Composition Graph.")
    try:
        frame_rate = Fraction(str(video.get("avg_frame_rate") or video.get("r_frame_rate")))
        expected_rate = Fraction(graph.frame_rate_numerator, graph.frame_rate_denominator)
    except (ValueError, ZeroDivisionError):
        raise VideoRenderError("Không đọc được frame rate của MP4.")
    if frame_rate != expected_rate:
        raise VideoRenderError("Frame rate MP4 không khớp bản nháp Project V2.")
    if has_audio and (audio is None or audio.get("codec_name") != "aac"):
        raise VideoRenderError("Composition có audio nhưng output thiếu luồng AAC hợp lệ.")
    try:
        actual_duration = float(video.get("duration") or format_info.get("duration"))
    except (TypeError, ValueError):
        raise VideoRenderError("Không đọc được duration của MP4.")
    expected_duration = graph.duration_ticks / graph.timebase
    frame_duration = graph.frame_rate_denominator / graph.frame_rate_numerator
    if actual_duration <= 0 or abs(actual_duration - expected_duration) > max(0.1, frame_duration * 1.5):
        raise VideoRenderError("Duration MP4 không khớp thời lượng Composition Graph.")

    if job.cancel_event.is_set():
        raise VideoRenderError("Người dùng đã hủy kiểm tra output.")
    job.update(progress=99, stage="Đang giải mã toàn bộ video để kiểm tra lỗi")
    try:
        process = subprocess.Popen(
            [ffmpeg.ffmpeg, "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        while process.poll() is None:
            if job.cancel_event.wait(0.1):
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise VideoRenderError("Người dùng đã hủy kiểm tra giải mã video.")
        stderr = process.stderr.read() if process.stderr else b""
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace")[-800:]
            raise VideoRenderError(f"Giải mã toàn bộ MP4 thất bại: {detail or 'FFmpeg báo lỗi'}")
    except OSError as error:
        raise VideoRenderError(f"Không thể giải mã kiểm tra MP4: {error}") from error
    finally:
        if "process" in locals() and process.stderr:
            process.stderr.close()
    return {
        "outputPath": str(path),
        "durationMs": round(actual_duration * 1000),
        "width": graph.width,
        "height": graph.height,
        "frameRateNumerator": graph.frame_rate_numerator,
        "frameRateDenominator": graph.frame_rate_denominator,
        "format": "MP4",
        "videoCodec": "H.264",
        "audioCodec": "AAC" if audio is not None else None,
        "sizeBytes": path.stat().st_size,
        "fullDecodePassed": True,
    }


def install_video_editor_api(app: FastAPI, data_directory: Path) -> None:
    ffmpeg = FFmpegToolchain()
    media_store = VideoMediaStore(data_directory / "video_editor", ffmpeg)
    project_store = VideoProjectStore(data_directory / "video_editor" / "projects")
    job_manager = VideoJobManager(max_workers=1)
    app.state.video_ffmpeg = ffmpeg
    app.state.video_media = media_store
    app.state.video_projects = project_store
    app.state.video_jobs = job_manager
    export_history_directory = data_directory / "video_editor" / "export_history"
    export_history_lock = threading.Lock()

    @app.middleware("http")
    async def log_video_request(request: Request, call_next):
        if not request.url.path.startswith("/api/v1/video/"):
            return await call_next(request)
        supplied_id = request.headers.get("X-Correlation-ID", "")
        correlation_id = supplied_id if re.fullmatch(r"[A-Za-z0-9._-]{1,80}", supplied_id) else uuid4().hex
        context_token = video_request_id.set(correlation_id)
        started = time.perf_counter()
        logger.info("video.request.begin correlation_id=%s pid=%s thread_id=%s method=%s path=%s",
                    correlation_id, os.getpid(), threading.get_ident(),
                    request.method, request.url.path)
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("video.request.error correlation_id=%s pid=%s method=%s path=%s",
                             correlation_id, os.getpid(), request.method, request.url.path)
            raise
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info("video.request.end correlation_id=%s pid=%s thread_id=%s method=%s path=%s duration_ms=%s",
                        correlation_id, os.getpid(), threading.get_ident(),
                        request.method, request.url.path, duration_ms)
            video_request_id.reset(context_token)
        response.headers["X-Correlation-ID"] = correlation_id
        return response

    def authorize_video(
        request: Request,
        x_media_studio_token: str | None = Header(default=None),
    ) -> None:
        expected = request.app.state.token
        if x_media_studio_token is None or not hmac.compare_digest(x_media_studio_token, expected):
            raise HTTPException(status_code=401, detail="Yêu cầu không hợp lệ.")

    router = APIRouter(prefix="/api/v1/video", dependencies=[Depends(authorize_video)])

    @router.get("/capabilities")
    def capabilities() -> dict[str, object]:
        return {"ffmpeg": ffmpeg.capabilities(), "maxMediaBytes": MAX_MEDIA_BYTES,
                "composition": {
                    "graphVersion": 1,
                    "timelineTimebase": TIMEBASE,
                    "layerOrder": "ascending-back-to-front",
                    "previewEndpoint": "GET /api/v1/video/projects/{projectId}/preview/frame?timestampTicks=...",
                    "visualTracks": "SUPPORTED_VERIFIED",
                    "videoOverlay": "SUPPORTED_VERIFIED",
                    "imageAlphaOverlay": "SUPPORTED_VERIFIED",
                    "textLayers": "SUPPORTED_VERIFIED",
                    "audioOverlap": "SUPPORTED_VERIFIED",
                    "fractionalFrameRates": "SUPPORTED_VERIFIED",
                    "sourceTimeOffsets": "SUPPORTED_VERIFIED",
                    "visualGaps": "SUPPORTED_VERIFIED",
                    "embeddedVideoAudioMix": "SUPPORTED_VERIFIED",
                    "audioFadesAndGain": "SUPPORTED_VERIFIED",
                    "trackState": "SUPPORTED_UNVERIFIED",
                    "nativeVisualTransformParity": "SUPPORTED_UNVERIFIED",
                    "nativePreviewCompositor": ("SUPPORTED_UNVERIFIED" if ffmpeg.native_engine and
                                                  ffmpeg.native_engine.composition_preview_available else "UNSUPPORTED"),
                    "nativeExportOrchestration": ("SUPPORTED_UNVERIFIED" if ffmpeg.native_engine and
                                                   ffmpeg.native_engine.composition_runner_available else "UNSUPPORTED"),
                    "transitions": "UNSUPPORTED",
                    "legacyLinearTailExtension": "SUPPORTED_VERIFIED",
                    "multiTrackPreviewExportParity": "SUPPORTED_VERIFIED",
                    "audioMixPolicy": {
                        "legacyLinearCompatibility": "legacy-input-count-normalization",
                        "newMultiTrackProjects": "sum-gains-no-normalization",
                        "limiter": False,
                        "loudnessNormalization": False,
                    },
                },
                "supportedMedia": {"image": ["jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff"],
                                   "video": ["mp4", "mov", "mkv", "webm", "avi", "m4v"],
                                   "audio": ["mp3", "wav", "m4a", "aac", "ogg", "flac"]}}

    @router.get("/templates")
    def templates() -> dict[str, object]:
        return {"templates": list_templates()}

    @router.post("/media-selection/prepare")
    def prepare_media_selection(request: SelectionPayloadRequest) -> dict[str, object]:
        try:
            return prepare_payload(request, media_store.get_metadata)
        except (ValueError, KeyError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.post("/stories/{template_id}/preview")
    def preview_story_page(template_id: str, request: dict[str, object]) -> Response:
        """One page of a photo story while photos are still being chosen (PNG).

        ``bindings`` may be partial; unfilled slots render as numbered placeholders.
        """
        from mediastudio.video_editor.media_selection import _story_template, story_slot_ids
        from mediastudio.video_editor.story_templates import StoryTemplateError, render_page_preview
        story = _story_template(template_id)
        if story is None:
            raise HTTPException(status_code=404, detail=f"Không có mẫu ảnh {template_id}.")
        bindings = request.get("bindings") or {}
        if not isinstance(bindings, dict):
            raise HTTPException(status_code=422, detail="bindings phải là object.")
        slot_ids = story_slot_ids(story)
        unknown = set(bindings) - set(slot_ids)
        if unknown:
            raise HTTPException(status_code=422, detail=f"Ô không có trong mẫu: {', '.join(sorted(unknown))}.")
        try:
            page = int(request.get("page", 1))
            width = max(120, min(1080, int(request.get("width", 540))))
            photos: list[Path | None] = []
            for slot_id in slot_ids:
                asset_id = bindings.get(slot_id)
                if not asset_id:
                    photos.append(None)
                    continue
                if media_store.get_metadata(asset_id).kind != "image":
                    photos.append(None)
                    continue
                photos.append(Path(media_store.get_path(asset_id)))
            image = render_page_preview(story, page, photos, width=width)
        except (StoryTemplateError, ValueError, KeyError, OSError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        buffer = __import__("io").BytesIO()
        image.save(buffer, format="PNG")
        return Response(content=buffer.getvalue(), media_type="image/png",
                        headers={"X-Story-Page": str(page), "X-Story-Page-Count": str(len(story.pages))})

    @router.post("/stories/{template_id}/render")
    def render_story_template(template_id: str, request: dict[str, object]) -> dict[str, object]:
        """Render a photo story template (image output) to one image per page."""
        from mediastudio.video_editor.media_selection import SelectionPayloadRequest as _Selection
        from mediastudio.video_editor.media_selection import prepare_story_payload, _story_template
        from mediastudio.video_editor.story_templates import StoryTemplateError, export_story, export_story_page
        story = _story_template(template_id)
        if story is None:
            raise HTTPException(status_code=404, detail=f"Không có mẫu ảnh {template_id}.")
        image_format = str(request.get("format", "png")).lower()
        if image_format not in {"png", "jpg", "jpeg"}:
            raise HTTPException(status_code=422, detail="Định dạng ảnh chỉ hỗ trợ png hoặc jpg.")
        try:
            prepared = prepare_story_payload(story, _Selection(
                template_id=template_id,
                template_definition_version=str(request.get("templateDefinitionVersion", "")),
                bindings=request.get("bindings") or {},
            ), media_store.get_metadata)
            photo_paths = [Path(media_store.get_path(asset_id)) for asset_id in prepared["photoOrder"]]
            # "page" renders one page into the run folder "runId", so the desktop
            # app can show real progress; without it every page is rendered at once.
            run_id = str(request.get("runId") or uuid4().hex[:12])
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", run_id):
                raise ValueError("runId không hợp lệ.")
            output_directory = data_directory / "video_editor" / "stories" / f"{template_id}_{run_id}"
            page = request.get("page")
            if page is None:
                written = export_story(story, photo_paths, output_directory, image_format=image_format)
            else:
                page_index = int(page)
                written = [export_story_page(story, photo_paths, output_directory, page_index,
                                             image_format=image_format)]
        except (StoryTemplateError, ValueError, KeyError, OSError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        logger.info("story.render template_id=%s pages=%s directory=%s", template_id, len(written), output_directory)
        return {
            "templateId": template_id,
            "templateDefinitionVersion": prepared["templateDefinitionVersion"],
            "directory": str(output_directory),
            "pageCount": len(story.pages),
            "pages": ([{"index": int(page), "path": str(written[0])}] if page is not None else
                      [{"index": index, "path": str(path)} for index, path in enumerate(written, start=1)]),
        }

    @router.post("/processing-jobs", status_code=202)
    def create_template_processing_job(request: TemplateProcessingRequest) -> dict[str, object]:
        preflight_started = time.perf_counter()
        template = get_template(request.template_id)
        if template is None:
            raise HTTPException(status_code=422, detail="Không tìm thấy Template Definition.")
        catalog_entry = template.public_dict()
        if (catalog_entry["availabilityStatus"] not in {"PILOT_RENDERABLE", "READY_FOR_USERS"}
                or catalog_entry["templateDefinitionVersion"] != request.template_definition_version):
            raise HTTPException(status_code=422, detail="Template chưa sẵn sàng hoặc phiên bản definition đã thay đổi.")
        logger.info(
            "video.template.canvas template_id=%s version=%s width=%s height=%s",
            request.template_id, catalog_entry["templateDefinitionVersion"],
            catalog_entry["width"], catalog_entry["height"],
        )

        try:
            prepared = prepare_payload(SelectionPayloadRequest(
                template_id=request.template_id,
                template_definition_version=request.template_definition_version,
                bindings=request.bindings,
            ), media_store.get_metadata)
            for asset_id in request.bindings.values():
                path = media_store.get_path(asset_id)
                if not path.is_file():
                    raise KeyError(f"Không tìm thấy tệp media {asset_id}.")
                with path.open("rb") as stream:
                    if not stream.read(1):
                        raise ValueError(f"Tệp media {asset_id} rỗng hoặc không đọc được.")
        except (ValueError, KeyError, OSError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        logger.info(
            "template_processing.preflight_complete template_id=%s version=%s bindings=%s duration_seconds=%.3f",
            request.template_id, request.template_definition_version, len(request.bindings),
            time.perf_counter() - preflight_started,
        )

        fingerprint_source = json.dumps({
            "templateId": request.template_id,
            "templateVersion": request.template_definition_version,
            "bindings": dict(sorted(request.bindings.items())),
        }, ensure_ascii=False, separators=(",", ":"))
        binding_fingerprint = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
        stages = [
            {"stageId": "analyze_media", "name": "Phân tích media", "status": "PENDING", "message": None, "errorCode": None, "durationSeconds": None},
            {"stageId": "apply_layout", "name": "Áp dụng bố cục mẫu", "status": "PENDING", "message": None, "errorCode": None, "durationSeconds": None},
            {"stageId": "remove_background", "name": "Tách nền ảnh phủ", "status": "PENDING", "message": None, "errorCode": None, "durationSeconds": None},
            {"stageId": "build_composition", "name": "Tạo chuyển cảnh và hiệu ứng", "status": "PENDING", "message": None, "errorCode": None, "durationSeconds": None},
            {"stageId": "sync_audio", "name": "Đồng bộ nhạc nền", "status": "PENDING", "message": None, "errorCode": None, "durationSeconds": None},
            {"stageId": "prepare_preview", "name": "Hoàn tất...", "status": "PENDING", "message": None, "errorCode": None, "durationSeconds": None},
        ]

        def worker(job: VideoJob) -> None:
            processing_started = time.perf_counter()
            active_stage_id: str | None = None
            active_stage_started: float | None = None

            # Raised once the overlay count is known; see the remove_background stage.
            background_removal_budget_seconds = BACKGROUND_REMOVAL_STAGE_TIMEOUT_SECONDS

            def stage_timeout_seconds(stage_id: str | None) -> int:
                return (background_removal_budget_seconds if stage_id == "remove_background"
                        else PROCESSING_STAGE_TIMEOUT_SECONDS)

            def total_budget_seconds() -> int:
                # Every stage except background removal stays inside the original
                # ceiling; cutting out N images is allowed the extra time its own
                # per-image budget asks for.
                return PROCESSING_TOTAL_TIMEOUT_SECONDS + max(
                    0, background_removal_budget_seconds - BACKGROUND_REMOVAL_STAGE_TIMEOUT_SECONDS
                )

            def check_total_timeout() -> None:
                elapsed = time.perf_counter() - processing_started
                budget = total_budget_seconds()
                if elapsed > budget:
                    raise TemplateProcessingTimeoutError(
                        f"Tác vụ xử lý mẫu vượt quá {budget} giây."
                    )

            def begin_stage(stage_id: str, message: str) -> None:
                nonlocal active_stage_id, active_stage_started
                check_total_timeout()
                active_stage_id = stage_id
                active_stage_started = time.perf_counter()
                job.update_stage(stage_id, "RUNNING", message)

            def check_active_stage_timeout() -> None:
                if active_stage_id is None or active_stage_started is None:
                    return
                duration = time.perf_counter() - active_stage_started
                timeout_seconds = stage_timeout_seconds(active_stage_id)
                if duration > timeout_seconds:
                    raise TemplateProcessingTimeoutError(
                        f"Giai đoạn {active_stage_id} vượt quá {timeout_seconds} giây."
                    )
                check_total_timeout()

            def finish_stage(stage_id: str, status: str, message: str) -> None:
                nonlocal active_stage_id, active_stage_started
                stage_started = active_stage_started if active_stage_id == stage_id else time.perf_counter()
                duration = time.perf_counter() - stage_started
                timeout_seconds = stage_timeout_seconds(stage_id)
                if duration > timeout_seconds:
                    raise TemplateProcessingTimeoutError(
                        f"Giai đoạn {stage_id} vượt quá {timeout_seconds} giây."
                    )
                check_total_timeout()
                logger.info(
                    "template_processing.stage_complete job_id=%s template_id=%s stage_id=%s status=%s duration_seconds=%.3f",
                    job.job_id, request.template_id, stage_id, status.lower(), duration,
                )
                job.update_stage(stage_id, status, f"{message} ({duration:.2f}s)", duration_seconds=duration)
                if active_stage_id == stage_id:
                    active_stage_id = None
                    active_stage_started = None

            def fail_active_stage(error_code: str, message: str) -> None:
                nonlocal active_stage_id, active_stage_started
                stage_id = active_stage_id or job.current_stage
                if stage_id is None:
                    return
                started = active_stage_started if active_stage_id == stage_id else time.perf_counter()
                duration = time.perf_counter() - started
                logger.warning(
                    "template_processing.stage_failed job_id=%s template_id=%s stage_id=%s error_code=%s duration_seconds=%.3f message=%s",
                    job.job_id, request.template_id, stage_id, error_code, duration, message,
                )
                job.update_stage(stage_id, "FAILED", f"{message} ({duration:.2f}s)", error_code,
                                 duration_seconds=duration)
                active_stage_id = None
                active_stage_started = None

            try:
                job.update(state="running", progress=None, stage="Đang áp dụng mẫu")
                begin_stage("analyze_media", "Đang kiểm tra media và binding.")
                for slot_id, asset_id in request.bindings.items():
                    metadata = media_store.get_metadata(asset_id)
                    if metadata.kind not in {"image", "video"}:
                        raise ValueError(f"Media tại vị trí {slot_id} không phải ảnh hoặc video.")
                    path = media_store.get_path(asset_id)
                    with path.open("rb") as stream:
                        if not stream.read(1):
                            raise ValueError(f"Tệp media tại vị trí {slot_id} không đọc được.")
                finish_stage("analyze_media", "COMPLETED", "Media, loại tệp và binding đã được xác thực.")

                begin_stage("apply_layout", "Đang biên dịch Template Definition thành Project V2.")
                compiled = compile_template(prepared["definition"], request.bindings, media_store.get_metadata)
                if (compiled.project.template_id != request.template_id
                        or compiled.project.template_metadata.get("templateDefinitionVersion") != request.template_definition_version
                        or compiled.project.template_metadata.get("templateBindings") != dict(sorted(request.bindings.items()))):
                    raise ValueError("Project V2 không khớp Template ID, version hoặc media bindings đã chọn.")
                finish_stage("apply_layout", "COMPLETED", "Template Compiler đã tạo Project V2 chuẩn.")

                cutout_clips = [
                    clip for track in compiled.project.tracks if track.kind == "visual"
                    for clip in track.clips if clip.properties.get("removeBackground") is True
                ]
                if cutout_clips:
                    background_removal_budget_seconds = max(
                        BACKGROUND_REMOVAL_STAGE_TIMEOUT_SECONDS,
                        BACKGROUND_REMOVAL_SECONDS_PER_IMAGE * len(cutout_clips),
                    )
                    begin_stage("remove_background", f"Đang tách nền {len(cutout_clips)} ảnh phủ bằng mô hình cục bộ.")
                    for index, clip in enumerate(cutout_clips, start=1):
                        if clip.media_id is None:
                            raise BackgroundRemovalError(f"Ảnh phủ {clip.clip_id} không có media nguồn.")
                        source_path = media_store.get_path(clip.media_id)
                        cutout_path = media_store.get_cutout_path(clip.media_id)
                        crop_transparent_bounds = clip.properties.get("trimTransparentBounds") is True
                        if crop_transparent_bounds:
                            cutout_path = cutout_path.with_name(f"{cutout_path.stem}_trimmed-v1.png")
                        model_home = Path(media_store.root).parent / "models" / "rembg"
                        ensure_background_removed_image(
                            source_path, cutout_path, model_home,
                            crop_transparent_bounds=crop_transparent_bounds,
                        )
                        check_active_stage_timeout()
                        job.update_stage(
                            "remove_background", "RUNNING",
                            f"Đã tách nền {index}/{len(cutout_clips)} ảnh phủ.",
                        )
                    finish_stage("remove_background", "COMPLETED", "Ảnh phủ đã được tách nền tự động.")
                else:
                    begin_stage("remove_background", "Mẫu này không có ảnh phủ cần tách nền.")
                    finish_stage("remove_background", "SKIPPED", "Mẫu này không có ảnh phủ cần tách nền.")

                begin_stage("build_composition", "Đang kiểm tra Composition Graph và khả năng renderer.")
                graph = build_composition_graph(compiled.project, media_store.get_metadata)
                finish_stage(
                    "build_composition", "COMPLETED",
                    "Composition Graph hợp lệ; các hiệu ứng/chuyển cảnh ngoài khả năng hiện có bị từ chối.",
                )

                has_audio = any(track.kind == "audio" and any(clip.enabled for clip in track.clips)
                                for track in graph.tracks)
                if has_audio:
                    begin_stage("sync_audio", "Đang kiểm tra đồng bộ track âm thanh.")
                    finish_stage("sync_audio", "COMPLETED", "Track âm thanh đã được đồng bộ theo Composition Graph.")
                else:
                    begin_stage("sync_audio", "Template Definition hiện tại không khai báo track nhạc nền.")
                    finish_stage("sync_audio", "SKIPPED", "Template Definition hiện tại không khai báo track nhạc nền.")

                begin_stage("prepare_preview", "Đang dựng khung preview thật và lưu bản nháp.")
                if not ffmpeg.ffmpeg:
                    raise FFmpegUnavailableError("Không tìm thấy FFmpeg để tạo preview composition.")
                frame, _renderer_name = render_preview_frame(
                    graph, media_store, ffmpeg.ffmpeg, 0, ffmpeg.native_engine,
                    timeout_seconds=PROCESSING_STAGE_TIMEOUT_SECONDS,
                )
                logger.info(
                    "template_processing.preview_renderer job_id=%s template_id=%s renderer=%s width=%s height=%s",
                    job.job_id, request.template_id, _renderer_name, graph.width, graph.height,
                )
                if len(frame) < 8 or not frame.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise VideoRenderError("Renderer không trả frame PNG hợp lệ cho preview.")
                check_active_stage_timeout()
                saved_project = project_store.create(compiled.project)
                persisted_project = project_store.get(saved_project.project_id)
                if (persisted_project.template_id != request.template_id
                        or persisted_project.template_metadata.get("templateBindings") != dict(sorted(request.bindings.items()))):
                    raise ValueError("Bản nháp đã lưu không khớp template và bindings.")
                preview_reference = f"/api/v1/video/projects/{saved_project.project_id}/preview/frame?timestamp_ticks=0"
                composition_reference = f"/api/v1/video/projects/{saved_project.project_id}"
                finish_stage("prepare_preview", "COMPLETED", "Project V2 đã lưu và preview PNG đã được dựng thành công.")
                job.update(
                    draft_project_id=saved_project.project_id,
                    composition_reference=composition_reference,
                    preview_reference=preview_reference,
                    state="succeeded", progress=100, stage="Bản nháp có thể xem trước",
                    current_stage="prepare_preview",
                )
            except (TemplateProcessingTimeoutError, subprocess.TimeoutExpired, TimeoutError) as error:
                stage_name = active_stage_id or "processing"
                message = (str(error) if not isinstance(error, subprocess.TimeoutExpired)
                           else f"Giai đoạn {stage_name} vượt quá {PROCESSING_STAGE_TIMEOUT_SECONDS} giây.")
                fail_active_stage("PROCESSING_TIMEOUT", message)
                job.update(state="failed", error_code="PROCESSING_TIMEOUT", error=message, progress=None)
            except TemplateCompilerError as error:
                fail_active_stage("UNSUPPORTED_FEATURE", str(error))
                job.update(state="failed", error_code="UNSUPPORTED_FEATURE", error=str(error), progress=None)
            except (FileNotFoundError, KeyError) as error:
                fail_active_stage("MISSING_MEDIA", str(error))
                job.update(state="failed", error_code="MISSING_MEDIA", error=str(error), progress=None)
            except FFmpegUnavailableError as error:
                fail_active_stage("PREVIEW_UNAVAILABLE", str(error))
                job.update(state="failed", error_code="PREVIEW_UNAVAILABLE", error=str(error), progress=None)
            except BackgroundRemovalError as error:
                fail_active_stage("BACKGROUND_REMOVAL_FAILED", str(error))
                job.update(state="failed", error_code="BACKGROUND_REMOVAL_FAILED", error=str(error), progress=None)
            except (CompositionGraphError, VideoRenderError) as error:
                fail_active_stage("PREVIEW_FAILED", str(error))
                job.update(state="failed", error_code="PREVIEW_FAILED", error=str(error), progress=None)
            except Exception as error:
                logger.exception("Template processing job %s failed", job.job_id)
                fail_active_stage("PROCESSING_FAILED", "Đã xảy ra lỗi khi chuẩn bị bản nháp.")
                job.update(state="failed", error_code="PROCESSING_FAILED",
                           error="Đã xảy ra lỗi khi chuẩn bị bản nháp. Media gốc được giữ nguyên.", progress=None)
            finally:
                logger.info(
                    "template_processing.complete job_id=%s template_id=%s status=%s duration_seconds=%.3f",
                    job.job_id, request.template_id, job.state, time.perf_counter() - processing_started,
                )

        try:
            job = job_manager.submit(
                project_id="", worker=worker, job_type="template-processing",
                template_id=request.template_id,
                template_version=request.template_definition_version,
                selection_session_id=request.selection_session_id,
                binding_fingerprint=binding_fingerprint, stages=stages,
                idempotency_key=f"{request.selection_session_id}:{binding_fingerprint}",
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return job.snapshot()

    @router.get("/processing-jobs/{job_id}")
    def get_template_processing_job(job_id: str) -> dict[str, object]:
        job = _get_job(job_manager, job_id)
        if job.job_type != "template-processing":
            raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ áp dụng mẫu.")
        return job.snapshot()

    @router.post("/media", status_code=201)
    async def import_media(file: UploadFile = File(...)) -> dict[str, object]:
        try:
            metadata = await media_store.import_upload(file)
            logger.info("video.media.import correlation_id=%s pid=%s media_id=%s kind=%s name=%s",
                        video_request_id.get(), os.getpid(), metadata.asset_id, metadata.kind,
                        metadata.file_name)
            return metadata.model_dump(mode="json", by_alias=True)
        except FFmpegUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.get("/media")
    def list_media() -> dict[str, object]:
        return {"media": [item.model_dump(mode="json", by_alias=True)
                          for item in media_store.list_metadata()]}

    @router.get("/media/{asset_id}")
    def get_media(asset_id: str) -> dict[str, object]:
        try:
            return media_store.get_metadata(asset_id).model_dump(mode="json", by_alias=True)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @router.post("/media/library-delete")
    def delete_library_media(asset_ids: list[str] = Body(..., min_length=1, max_length=500)) -> dict[str, object]:
        try:
            return {"deletedAssetIds": media_store.delete_from_library(asset_ids)}
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.get("/media/{asset_id}/thumbnail")
    def get_media_thumbnail(asset_id: str) -> FileResponse:
        try:
            path = media_store.thumbnail_path(asset_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return FileResponse(path, media_type="image/jpeg", filename=f"{asset_id}.jpg")

    @router.get("/media/{asset_id}/frame")
    def get_media_frame(asset_id: str, timestamp_ms: int = Query(..., ge=0)) -> Response:
        try:
            frame = media_store.frame_jpeg(asset_id, timestamp_ms)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except FFmpegUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return Response(content=frame, media_type="image/jpeg")

    @router.get("/media/{asset_id}/filmstrip")
    def get_media_filmstrip(
        asset_id: str,
        frames: int = Query(default=24, ge=4, le=24),
    ) -> FileResponse:
        try:
            path = media_store.filmstrip_path(asset_id, frames)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except FFmpegUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return FileResponse(path, media_type="image/jpeg", filename=f"{asset_id}_filmstrip.jpg")

    @router.get("/media/{asset_id}/waveform")
    def get_media_waveform(
        asset_id: str,
        samples: int = Query(default=480, ge=100, le=2000),
    ) -> dict[str, object]:
        try:
            values = media_store.waveform_samples(asset_id, samples)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except FFmpegUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"samples": values}

    @router.get("/media/{asset_id}/content")
    def get_media_content(asset_id: str) -> FileResponse:
        try:
            path = media_store.get_path(asset_id)
            metadata = media_store.get_metadata(asset_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return FileResponse(path, media_type=metadata.content_type, filename=metadata.file_name)

    @router.get("/projects")
    def list_projects() -> dict[str, object]:
        return {"projects": [project_api_payload(project) for project in project_store.list()]}

    @router.post("/projects", status_code=201)
    def create_project(request: CreateProjectRequest) -> dict[str, object]:
        template = get_template(request.template_id)
        if template is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy mẫu video.")
        project = project_store.create(template.create_project(request.title))
        return project_api_payload(project)

    @router.post("/projects/blank", status_code=201)
    def create_blank_project(request: CreateBlankProjectRequest) -> dict[str, object]:
        try:
            project = TimelineEngineV2(VideoProjectV2.blank(
                request.title, request.width, request.height,
                request.frame_rate_numerator, request.frame_rate_denominator,
            )).project
            return project_api_payload(project_store.create(project))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @router.get("/projects/{project_id}")
    def get_project(project_id: str) -> dict[str, object]:
        try:
            project = project_store.get(project_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error
        return project_api_payload(project)

    @router.get("/projects/{project_id}/export-capabilities")
    def get_export_capabilities(project_id: str) -> dict[str, object]:
        try:
            project = project_store.get(project_id)
            graph = build_composition_graph(project, media_store.get_metadata)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy media nguồn: {error}") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _export_capability_payload(project, graph, ffmpeg)

    @router.post("/projects/{project_id}/export-jobs", status_code=202)
    def create_export_job(project_id: str, request: VideoCreatorExportRequest) -> dict[str, object]:
        try:
            project = project_store.get(project_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Không tìm thấy bản nháp Project V2.") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        if project.revision != request.draft_revision:
            raise HTTPException(status_code=409, detail={
                "code": "DRAFT_REVISION_MISMATCH",
                "message": "Bản nháp đã thay đổi. Hãy tải lại preview trước khi xuất.",
            })
        if project.template_id != request.template_id or _template_version(project) != request.template_version:
            raise HTTPException(status_code=409, detail={
                "code": "DRAFT_TEMPLATE_MISMATCH",
                "message": "Template ID hoặc phiên bản không khớp bản nháp đã duyệt.",
            })
        try:
            graph = build_composition_graph(project, media_store.get_metadata)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy media nguồn: {error}") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not hmac.compare_digest(graph.source_fingerprint, request.composition_fingerprint):
            raise HTTPException(status_code=409, detail={
                "code": "COMPOSITION_FINGERPRINT_MISMATCH",
                "message": "Composition Graph đã thay đổi kể từ khi mở preview. Hãy tải lại bản nháp.",
            })
        capability = _export_capability_payload(project, graph, ffmpeg)
        if not capability["canExport"]:
            raise HTTPException(status_code=422, detail=capability["errorMessage"])
        if request.media_bindings != capability["mediaBindings"]:
            raise HTTPException(status_code=409, detail={
                "code": "MEDIA_BINDINGS_MISMATCH",
                "message": "Media bindings không còn khớp với bản nháp đã duyệt.",
            })

        try:
            stem = _validated_export_stem(request.file_name)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        supplied_directory = Path(request.output_directory).expanduser()
        if not supplied_directory.is_absolute():
            raise HTTPException(status_code=422, detail="Thư mục lưu phải là đường dẫn đầy đủ.")
        try:
            output_directory = supplied_directory.resolve(strict=False)
        except OSError as error:
            raise HTTPException(status_code=422, detail="Không thể chuẩn hóa đường dẫn thư mục lưu.") from error
        if not output_directory.exists():
            parent_directory = output_directory.parent
            if not parent_directory.is_dir():
                raise HTTPException(status_code=422, detail="Thư mục lưu không tồn tại và thư mục cha chưa sẵn sàng để tạo an toàn.")
            try:
                output_directory.mkdir()
            except FileExistsError:
                if not output_directory.is_dir():
                    raise HTTPException(status_code=422, detail="Đường dẫn lưu đã được tạo nhưng không phải là thư mục.")
            except OSError as error:
                raise HTTPException(status_code=422, detail=f"Không thể tạo thư mục lưu: {error}") from error
        if not output_directory.is_dir():
            raise HTTPException(status_code=422, detail="Vị trí lưu phải là một thư mục.")
        target_path = output_directory / f"{stem}.mp4"
        if os.name == "nt" and len(str(target_path)) > 240:
            raise HTTPException(status_code=422, detail="Đường dẫn file đầu ra quá dài trên Windows.")
        if target_path.is_dir():
            raise HTTPException(status_code=422, detail="Đường dẫn file đầu ra đang là một thư mục.")
        export_settings = {
            "quality": request.quality,
            "format": "mp4",
            "videoCodec": "h264",
            "audioCodec": capability["audioCodec"],
            "width": graph.width,
            "height": graph.height,
            "frameRateNumerator": graph.frame_rate_numerator,
            "frameRateDenominator": graph.frame_rate_denominator,
        }
        idempotency_material = "|".join((project_id, str(project.revision), graph.source_fingerprint,
                                          str(target_path), request.quality, str(request.overwrite)))
        idempotency_key = f"video-creator-export:{request.request_id}"
        request_fingerprint = hashlib.sha256(idempotency_material.encode("utf-8")).hexdigest()
        existing_job = job_manager.get_idempotent(idempotency_key)
        if existing_job is not None:
            if (existing_job.idempotency_fingerprint != request_fingerprint
                    or existing_job.media_bindings != capability["mediaBindings"]
                    or existing_job.output_settings != export_settings):
                raise HTTPException(status_code=409, detail="Request ID đã được dùng với cấu hình export khác.")
            return existing_job.snapshot()
        try:
            descriptor, write_test_name = tempfile.mkstemp(prefix=".mediastudio-write-test-", dir=output_directory)
            os.close(descriptor)
            Path(write_test_name).unlink()
        except OSError as error:
            raise HTTPException(status_code=422, detail=f"Không có quyền ghi vào thư mục đã chọn: {error}") from error
        if target_path.exists() and not request.overwrite:
            raise HTTPException(status_code=409, detail={
                "code": "OUTPUT_FILE_EXISTS",
                "message": "File đích đã tồn tại. Hãy đổi tên hoặc xác nhận ghi đè.",
            })
        source_paths = {
            os.path.normcase(str(media_store.get_path(clip.media_id).resolve()))
            for track in graph.tracks for clip in track.clips if clip.media_id
        }
        if os.path.normcase(str(target_path.resolve())) in source_paths:
            raise HTTPException(status_code=422, detail="Không thể ghi đè file media nguồn.")

        render_staging_directory = data_directory / "video_editor" / "export_staging"

        def export_worker(job: VideoJob) -> None:
            try:
                assert ffmpeg.ffmpeg is not None
                render_composition_project(
                    job, graph, media_store, ffmpeg.ffmpeg, render_staging_directory,
                    request.quality, ffmpeg.native_engine, defer_success=True,
                )
                rendered_path = job.output_path
                if job.state == "cancelled" or job.cancel_event.is_set():
                    job.update(state="cancelled", progress=0, stage="Đã hủy", output_path=None)
                    return
                if rendered_path is None or not rendered_path.is_file():
                    raise VideoRenderError("Renderer không tạo được file MP4 để xác minh.")
                job.update(progress=99, stage="Đang xác minh container, luồng và duration")
                result = _probe_and_decode_export(rendered_path, graph, ffmpeg, job, bool(capability["hasAudio"]))
                if job.cancel_event.is_set():
                    raise VideoRenderError("Người dùng đã hủy trước khi công bố output.")
                required_space = rendered_path.stat().st_size + 1024 * 1024
                if shutil.disk_usage(output_directory).free < required_space:
                    raise VideoRenderError("Không đủ dung lượng trống trong thư mục đích để công bố file MP4.")
                job.update(progress=99, stage="Đang công bố file MP4 đã xác minh")
                _publish_export_file(rendered_path, target_path, request.overwrite)
                result["outputPath"] = str(target_path)
                result["sizeBytes"] = target_path.stat().st_size
                result["jobId"] = job.job_id
                result["draftProjectId"] = project.project_id
                result["draftRevision"] = project.revision
                result["templateId"] = project.template_id
                result["templateVersion"] = _template_version(project)
                result["compositionFingerprint"] = graph.source_fingerprint
                result["outputSettings"] = export_settings
                history_entry = {
                    "projectId": project.project_id,
                    "draftRevision": project.revision,
                    "templateId": project.template_id,
                    "templateVersion": _template_version(project),
                    "exportJobId": job.job_id,
                    "compositionFingerprint": graph.source_fingerprint,
                    "outputPath": str(target_path),
                    "outputSettings": export_settings,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sizeBytes": target_path.stat().st_size,
                    "status": "SUCCEEDED",
                }
                try:
                    export_history_directory.mkdir(parents=True, exist_ok=True)
                    history_path = export_history_directory / f"{project.project_id}.json"
                    with export_history_lock:
                        history = json.loads(history_path.read_text(encoding="utf-8")) if history_path.exists() else []
                        history.append(history_entry)
                        temporary_history = history_path.with_suffix(f".{job.job_id}.tmp")
                        temporary_history.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
                        os.replace(temporary_history, history_path)
                except (OSError, ValueError):
                    logger.exception("Unable to persist export history for job %s", job.job_id)
                try:
                    rendered_path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Unable to clean validated staging output %s", rendered_path)
                job.update(state="succeeded", progress=100, stage="Xuất video thành công",
                           output_path=target_path, export_result=result)
            except VideoRenderError as error:
                if job.cancel_event.is_set():
                    job.update(state="cancelled", progress=0, stage="Đã hủy", error=str(error),
                               error_code="CANCELLED")
                else:
                    job.update(state="failed", progress=0, stage="Không thể xuất video", error=str(error),
                               error_code="EXPORT_VALIDATION_FAILED")
            except FFmpegUnavailableError as error:
                job.update(state="failed", progress=0, stage="Thiếu FFmpeg", error=str(error),
                           error_code="FFMPEG_UNAVAILABLE")
            except Exception as error:
                logger.exception("Video Creator export job %s failed", job.job_id)
                code = "OUTPUT_FILE_EXISTS" if isinstance(error, FileExistsError) else "EXPORT_FAILED"
                job.update(state="failed", progress=0, stage="Không thể xuất video", error=str(error),
                           error_code=code)
            finally:
                if job.state != "succeeded" and job.output_path is not None:
                    try:
                        job.output_path.unlink(missing_ok=True)
                    except OSError:
                        logger.warning("Unable to clean failed export staging output %s", job.output_path)
                    job.update(output_path=None)

        try:
            job = job_manager.submit(
                project_id, export_worker, job_type="video-creator-export",
                template_id=project.template_id, template_version=_template_version(project),
                binding_fingerprint=graph.source_fingerprint,
                media_bindings=dict(capability["mediaBindings"]), output_settings=export_settings,
                composition_reference=str(capability["compositionReference"]),
                draft_project_id=project.project_id,
                idempotency_fingerprint=request_fingerprint,
                idempotency_key=idempotency_key,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return job.snapshot()

    @router.get("/projects/{project_id}/preview/frame")
    def get_project_preview_frame(project_id: str, timestamp_ticks: int = Query(..., ge=0)) -> Response:
        try:
            project = project_store.get(project_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not ffmpeg.ffmpeg:
            raise HTTPException(status_code=503, detail="Không tìm thấy FFmpeg để dựng preview composition.")
        return render_project_preview(project, timestamp_ticks)

    @router.post("/projects/{project_id}/preview/frame")
    def post_project_preview_frame(
        project_id: str, project_payload: dict[str, object], timestamp_ticks: int = Query(..., ge=0),
    ) -> Response:
        """Render the editor's current V2 snapshot without saving it first."""
        if project_payload.get("projectId") != project_id:
            raise HTTPException(status_code=422, detail="projectId trong URL và nội dung không khớp.")
        try:
            project = apply_api_compatibility_projection(project_payload)
            _validate_v2_references(project, media_store)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return render_project_preview(project, timestamp_ticks)

    def render_project_preview(project: VideoProjectV2, timestamp_ticks: int) -> Response:
        if not ffmpeg.ffmpeg:
            raise HTTPException(status_code=503, detail="Không tìm thấy FFmpeg để dựng preview composition.")
        try:
            graph = build_composition_graph(project, media_store.get_metadata)
            frame, renderer_name = render_preview_frame(
                graph, media_store, ffmpeg.ffmpeg, timestamp_ticks, ffmpeg.native_engine,
            )
        except CompositionGraphError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except VideoRenderError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return Response(content=frame, media_type="image/png", headers={
            "X-Composition-Graph-Version": str(graph.graph_version),
            "X-Composition-Frame-Index": str(graph.frame_index_at(timestamp_ticks)),
            "X-Composition-Source-Fingerprint": graph.source_fingerprint,
            "X-Composition-Renderer": renderer_name,
            "X-Composition-Project-Revision": str(project.revision),
        })

    @router.post("/projects/{project_id}/preview/overlay-edit")
    def post_overlay_edit_layer(
        project_id: str, project_payload: dict[str, object],
        clip_id: str = Query(..., min_length=1), timestamp_ticks: int = Query(..., ge=0),
    ) -> dict[str, object]:
        """Everything the edit screen needs to move one overlay live, CapCut style.

        Returns the frame with that overlay hidden, the overlay image itself, and
        where the template places it before any manual adjustment, so the client
        can draw and drag the overlay without a backend round trip per mouse move.
        """
        import base64
        from PIL import Image as PilImage
        from mediastudio.video_editor.composition_renderer import _clip_file
        from mediastudio.video_editor.framing import apply_subject_placement, subject_box_of

        if project_payload.get("projectId") != project_id:
            raise HTTPException(status_code=422, detail="projectId trong URL và nội dung không khớp.")
        try:
            project = apply_api_compatibility_projection(project_payload)
            _validate_v2_references(project, media_store)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        target = next((clip for track in project.tracks if track.kind == "visual"
                       for clip in track.clips if clip.clip_id == clip_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail=f"Không có clip {clip_id} trong bản nháp.")
        if not ffmpeg.ffmpeg:
            raise HTTPException(status_code=503, detail="Không tìm thấy FFmpeg để dựng preview composition.")
        hidden = project.model_copy(deep=True)
        for track in hidden.tracks:
            for clip in track.clips:
                if clip.clip_id == clip_id:
                    clip.properties = {**clip.properties, "opacity": 0.0}
        try:
            graph = build_composition_graph(project, media_store.get_metadata)
            hidden_graph = build_composition_graph(hidden, media_store.get_metadata)
            graph_clip = next(clip for track in graph.tracks for clip in track.clips if clip.clip_id == clip_id)
            background, _ = render_preview_frame(
                hidden_graph, media_store, ffmpeg.ffmpeg, timestamp_ticks, ffmpeg.native_engine,
            )
            path = _clip_file(graph_clip, media_store)
        except CompositionGraphError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except VideoRenderError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        canvas_w, canvas_h = graph.width, graph.height
        base = {key: value for key, value in graph_clip.attributes.items()
                if key not in {"userScale", "userOffsetX", "userOffsetY"}}
        placed = apply_subject_placement(base, Path(path), (canvas_w, canvas_h))
        with PilImage.open(path) as opened:
            layer = opened.convert("RGBA")
        box = subject_box_of(layer)
        # The client only needs screen resolution; keep the payload small.
        preview_layer = layer.copy()
        preview_layer.thumbnail((1600, 1600), PilImage.Resampling.LANCZOS)
        buffer = __import__("io").BytesIO()
        preview_layer.save(buffer, format="PNG")
        image_w, image_h = layer.size
        fit = (max if placed["fitMode"] == "cover" else min)(canvas_w / image_w, canvas_h / image_h)
        shown_w = image_w * fit * float(placed["scale"]) / canvas_w
        shown_h = image_h * fit * float(placed["scale"]) / canvas_h
        left = (1 - shown_w) / 2 + float(placed["positionX"])
        top = (1 - shown_h) / 2 + float(placed["positionY"])
        return {
            "clipId": clip_id,
            "canvasWidth": canvas_w,
            "canvasHeight": canvas_h,
            "backgroundPng": base64.b64encode(background).decode("ascii"),
            "layerPng": base64.b64encode(buffer.getvalue()).decode("ascii"),
            # Template placement before manual adjustment, in canvas fractions.
            "baseLeft": left, "baseTop": top, "baseWidth": shown_w, "baseHeight": shown_h,
            # Visible subject inside the layer image, in image fractions.
            "subjectBox": None if box is None else [
                box[0] / image_w, box[1] / image_h, box[2] / image_w, box[3] / image_h],
            "userScale": float(graph_clip.attributes.get("userScale", 1.0)),
            "userOffsetX": float(graph_clip.attributes.get("userOffsetX", 0.0)),
            "userOffsetY": float(graph_clip.attributes.get("userOffsetY", 0.0)),
        }

    @router.post("/projects/{project_id}/preview/video")
    def render_project_preview_video(project_id: str, project_payload: dict[str, object]) -> FileResponse:
        """Render a disposable, low-resolution playback preview from a Project V2 snapshot."""
        if project_payload.get("projectId") != project_id:
            raise HTTPException(status_code=422, detail="projectId trong URL và nội dung không khớp.")
        try:
            project = apply_api_compatibility_projection(project_payload)
            _validate_v2_references(project, media_store)
            graph = build_composition_graph(project, media_store.get_metadata)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (CompositionGraphError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not ffmpeg.ffmpeg or not ffmpeg.ffprobe:
            raise HTTPException(status_code=503, detail="Không tìm thấy FFmpeg để dựng video preview.")
        capabilities = ffmpeg.capabilities()
        if not capabilities.get("h264Encoding"):
            raise HTTPException(status_code=503, detail="Bản FFmpeg hiện tại không có encoder H.264 cho video preview.")
        if capabilities.get("aacEncoding") is False and any(
            clip.enabled and (track.kind == "audio" or (track.kind == "visual" and clip.media_has_audio))
            for track in graph.tracks for clip in track.clips
        ):
            raise HTTPException(status_code=503, detail="Bản FFmpeg hiện tại không có encoder AAC cho audio preview.")

        # A bounded proxy remains tied to the exact graph and keeps the template's
        # aspect ratio, timing, text and audio while reducing render work.
        width, height = _preview_proxy_dimensions(graph.width, graph.height)
        playback_graph = replace(graph, width=width, height=height)
        temporary_directory = Path(tempfile.mkdtemp(prefix="mediastudio_draft_preview_"))
        job = VideoJob(job_id=uuid4().hex, project_id=project_id, job_type="draft-preview")
        try:
            assert ffmpeg.ffmpeg is not None
            render_composition_project(
                job, playback_graph, media_store, ffmpeg.ffmpeg, temporary_directory, "draft", ffmpeg.native_engine,
            )
            if job.state != "succeeded" or job.output_path is None or not job.output_path.is_file():
                raise VideoRenderError(job.error or "Không tạo được video preview từ Composition Graph.")
        except (VideoRenderError, FFmpegUnavailableError) as error:
            shutil.rmtree(temporary_directory, ignore_errors=True)
            raise HTTPException(status_code=422, detail=f"Không thể dựng video preview: {error}") from error
        except Exception:
            shutil.rmtree(temporary_directory, ignore_errors=True)
            logger.exception("Draft preview render failed project_id=%s revision=%s", project_id, project.revision)
            raise HTTPException(status_code=500, detail="Không thể dựng video preview cho bản nháp hiện tại.")

        return FileResponse(
            job.output_path,
            media_type="video/mp4",
            filename=f"{project_id}-preview-r{project.revision}.mp4",
            headers={
                "X-Composition-Project-Revision": str(project.revision),
                "X-Composition-Source-Fingerprint": graph.source_fingerprint,
            },
            background=BackgroundTask(shutil.rmtree, temporary_directory, ignore_errors=True),
        )

    @router.put("/projects/{project_id}")
    def save_project(project_id: str, project: dict[str, object]) -> dict[str, object]:
        if project.get("projectId") != project_id:
            raise HTTPException(status_code=422, detail="projectId trong URL và nội dung không khớp.")
        try:
            canonical = apply_api_compatibility_projection(project)
            if canonical.project_id != project_id:
                raise ValueError("projectId trong URL và nội dung không khớp.")
            _validate_v2_references(canonical, media_store)
            canonical = project_store.save(project_id, canonical)
        except ProjectRevisionConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        legacy = to_legacy_project(canonical)
        logger.info(
            "video.project.save.begin correlation_id=%s pid=%s project_id=%s revision=%s "
            "clip_ids=%s media_ids=%s audio_track_ids=%s",
            video_request_id.get(), os.getpid(), canonical.project_id, canonical.revision,
            ",".join(clip.clip_id for clip in legacy.clips),
            ",".join(clip.media_id or "-" for clip in legacy.clips),
            ",".join(track.track_id for track in legacy.audio_tracks),
        )
        logger.info("video.project.save.end correlation_id=%s pid=%s project_id=%s revision=%s",
                    video_request_id.get(), os.getpid(), canonical.project_id, canonical.revision)
        return project_api_payload(canonical)

    @router.post("/projects/{project_id}/render-jobs", status_code=202)
    def create_render_job(project_id: str, request: RenderRequest) -> dict[str, object]:
        try:
            project = project_store.get(project_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            composition_graph = build_composition_graph(project, media_store.get_metadata)
        except CompositionGraphError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not ffmpeg.ffmpeg or not ffmpeg.ffprobe:
            raise HTTPException(status_code=503, detail="Không tìm thấy FFmpeg. Hãy cài ffmpeg.exe và ffprobe.exe, rồi khởi động lại backend.")
        ffmpeg_capabilities = ffmpeg.capabilities()
        if not ffmpeg_capabilities.get("h264Encoding"):
            raise HTTPException(status_code=503, detail="Bản FFmpeg hiện tại không có encoder H.264 (libx264).")
        audio_solo_active = any(track.kind == "audio" and track.solo and not track.muted
                                for track in composition_graph.tracks)
        has_audio = any(track.kind == "audio" and clip.enabled and clip.attributes.get("volume", 1.0) > 0
                        for track in composition_graph.tracks for clip in track.clips)
        if not has_audio and not audio_solo_active:
            has_audio = any(track.kind == "visual" and clip.enabled and clip.media_has_audio
                            and clip.attributes.get("audioVolume", 1.0) > 0
                            for track in composition_graph.tracks for clip in track.clips)
        if has_audio and not ffmpeg_capabilities.get("aacEncoding"):
            raise HTTPException(status_code=503, detail="Bản FFmpeg hiện tại không có encoder AAC để xuất âm thanh.")
        has_text = any(track.kind == "text" and any(clip.enabled for clip in track.clips)
                       for track in composition_graph.tracks)
        if has_text and not ffmpeg_capabilities.get("textOverlay"):
            raise HTTPException(status_code=503, detail="Bản FFmpeg hiện tại không có bộ lọc drawtext để dựng chữ.")

        def worker(job: VideoJob) -> None:
            try:
                output_directory = data_directory / "video_editor" / "renders"
                assert ffmpeg.ffmpeg is not None
                render_composition_project(job, composition_graph, media_store, ffmpeg.ffmpeg,
                                           output_directory, request.quality, ffmpeg.native_engine)
            except VideoRenderError as error:
                if job.state != "cancelled":
                    job.update(state="failed", progress=0, stage="Không thể xuất video", error=str(error))
            except FFmpegUnavailableError as error:
                job.update(state="failed", progress=0, stage="Thiếu FFmpeg", error=str(error))
            except Exception:
                logger.exception("Video render job %s failed", job.job_id)
                job.update(state="failed", progress=0, stage="Không thể xuất video",
                           error="Đã xảy ra lỗi khi kết xuất. Kiểm tra log backend để biết chi tiết.")

        job = job_manager.submit(project_id, worker)
        return job.snapshot()

    @router.get("/jobs/{job_id}")
    def get_video_job(job_id: str) -> dict[str, object]:
        job = _get_job(job_manager, job_id)
        return job.snapshot()

    @router.delete("/jobs/{job_id}")
    def cancel_video_job(job_id: str) -> dict[str, object]:
        job = job_manager.cancel(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ video.")
        return job.snapshot()

    @router.get("/jobs/{job_id}/result")
    def get_video_result(job_id: str) -> FileResponse:
        job = _get_job(job_manager, job_id)
        snapshot = job.snapshot()
        if snapshot["state"] != "succeeded" or job.output_path is None or not job.output_path.is_file():
            raise HTTPException(status_code=409, detail="Video chưa kết xuất xong.")
        return FileResponse(job.output_path, media_type="video/mp4", filename=job.output_path.name)

    app.include_router(router)
    app.add_event_handler("shutdown", job_manager.shutdown)


def _get_job(manager: VideoJobManager, job_id: str) -> VideoJob:
    if not ID_PATTERN.fullmatch(job_id):
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ video.")
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ video.")
    return job


def _validate_v2_references(project: VideoProjectV2, media_store: VideoMediaStore) -> None:
    for track in project.tracks:
        for clip in track.clips:
            if not clip.media_id:
                continue
            try:
                metadata = media_store.get_metadata(clip.media_id)
            except KeyError as error:
                raise HTTPException(status_code=422, detail=f"Không tìm thấy media cho clip {clip.clip_id}.") from error
            if clip.clip_kind == "audio":
                if metadata.kind != "audio" or not metadata.audio_codec:
                    raise HTTPException(status_code=422, detail="Audio clip cần media có luồng âm thanh.")
            else:
                if metadata.kind not in {"image", "video"}:
                    raise HTTPException(status_code=422, detail="Visual clip cần media ảnh hoặc video.")
                if metadata.kind == "video":
                    if metadata.duration_ms is None:
                        raise HTTPException(status_code=422, detail="Không đọc được thời lượng video nguồn.")
                    if clip.source_start_ticks + clip.duration_ticks > metadata.duration_ms * 90:
                        raise HTTPException(status_code=422, detail="Visual clip vượt thời lượng video nguồn.")
            if clip.clip_kind == "audio" and metadata.duration_ms is not None \
                    and clip.source_start_ticks + clip.duration_ticks > metadata.duration_ms * 90:
                raise HTTPException(status_code=422, detail="Audio clip vượt thời lượng nguồn.")
