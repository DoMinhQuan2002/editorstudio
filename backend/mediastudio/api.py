from __future__ import annotations

import hmac
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from mediastudio.image_tools.upscale import UpscaleError, UpscaleService
from mediastudio.image_tools import layered_vector
from mediastudio.image_tools.die_cut import DieCutError, DieCutLineService
from mediastudio.fashion.api import install_fashion_api
from mediastudio.jobs.manager import Job, JobManager
from mediastudio.storage.assets import AssetStore
from mediastudio.video_editor.api import install_video_editor_api


logger = logging.getLogger("mediastudio")


class UpscaleJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=32, max_length=32)
    scale: int = Field(ge=2, le=8)
    model: str = Field(min_length=1, max_length=40)
    reduce_noise: bool = True
    sharpen: bool = True
    output_format: str = Field(min_length=3, max_length=4)


class VectorizeJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=32, max_length=32)
    engine: str = Field(pattern="^(auto|vtracer|potrace)$")
    mode: str = Field(default="auto", pattern="^(auto|fast|quality|ai)$")
    color_count: int | None = Field(default=None, ge=2, le=24)
    simplification: int | None = Field(default=None, ge=0, le=100)
    smooth_paths: bool = True
    transparent_background: bool = True
    text_mode: Literal["editable", "outlined"] = "outlined"
    # Kept for older desktop builds; ignored. Layered colour tracing is the only method.
    vector_method: str | None = Field(default=None, max_length=40)
    detail: int | None = Field(default=None, ge=0, le=100)
    # cutout: keep the logo's own pixels, remove the background (PNG + SVG wrapper)
    # vector: redraw the logo as colour layers
    output_mode: Literal["cutout", "vector"] = "cutout"


class DieCutPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class DieCutStroke(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["foreground", "background"]
    points: list[DieCutPoint] = Field(min_length=1, max_length=5000)


class DieCutJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=32, max_length=32)
    offset_mm: float = Field(ge=0, le=20)
    artwork_width_mm: float = Field(ge=1, le=2000)
    auto_detect: bool = True
    smooth_path: bool = True
    complexity: Literal["Đơn giản", "Vừa", "Chi tiết"] = "Vừa"
    strokes: list[DieCutStroke] = Field(default_factory=list, max_length=200)


def create_app(token: str, data_directory: Path, models_directory: Path) -> FastAPI:
    data_directory.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="Media Studio Local API", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.token = token
    app.state.assets = AssetStore(data_directory / "assets")
    app.state.jobs = JobManager(max_workers=1)
    app.state.upscaler = UpscaleService(models_directory)
    shared_ocr = Path(models_directory).parent / "easyocr"
    app.state.easyocr_directory = shared_ocr if shared_ocr.is_dir() else Path(models_directory) / "easyocr"
    app.state.die_cutter = DieCutLineService()
    app.state.output_directory = data_directory / "results"
    app.state._shutdown_lock = Lock()
    install_video_editor_api(app, data_directory)

    def authorize(x_media_studio_token: str | None = Header(default=None)) -> None:
        if x_media_studio_token is None or not hmac.compare_digest(x_media_studio_token, app.state.token):
            raise HTTPException(status_code=401, detail="Yêu cầu không hợp lệ.")

    install_fashion_api(app, data_directory, authorize)

    @app.get("/api/v1/health", dependencies=[Depends(authorize)])
    def health() -> dict[str, str | bool]:
        return {
            "status": "ok",
            "engine": "Real-ESRGAN",
            "device": app.state.upscaler.device_description,
            "modelLoaded": bool(app.state.upscaler._model_cache),
            "vectorizationPipeline": "layered_trace",
        }

    @app.post("/api/v1/assets", dependencies=[Depends(authorize)])
    async def import_asset(file: UploadFile = File(...)) -> dict[str, object]:
        asset = await app.state.assets.import_image(file)
        return {
            "assetId": asset.asset_id,
            "fileName": asset.file_name,
            "width": asset.width,
            "height": asset.height,
            "byteSize": asset.byte_size,
            "mode": asset.mode,
        }

    @app.post("/api/v1/upscale/jobs", status_code=202, dependencies=[Depends(authorize)])
    def create_upscale_job(request: UpscaleJobRequest) -> dict[str, object]:
        asset = app.state.assets.get(request.asset_id)
        if request.scale not in {2, 4, 8}:
            raise HTTPException(status_code=422, detail="Chỉ hỗ trợ mức phóng 2×, 4× hoặc 8×.")
        if request.output_format.upper() not in {"PNG", "JPG", "TIFF"}:
            raise HTTPException(status_code=422, detail="Định dạng đầu ra chưa được hỗ trợ.")

        output_directory: Path = app.state.output_directory

        def run(job: Job) -> None:
            job.update(state="processing", progress=1, stage="Đã nhận tác vụ", is_indeterminate=False)
            try:
                result_path, width, height, size = app.state.upscaler.run(
                    job,
                    asset,
                    scale=request.scale,
                    model_choice=request.model,
                    reduce_noise=request.reduce_noise,
                    sharpen=request.sharpen,
                    output_format=request.output_format.upper(),
                    output_directory=output_directory,
                )
                job.update(
                    state="succeeded",
                    progress=100,
                    stage="Đã nâng cấp ảnh xong",
                    is_indeterminate=False,
                    result_path=result_path,
                    result_width=width,
                    result_height=height,
                    result_size=size,
                )
            except UpscaleError as error:
                job.update(state="failed", progress=0, stage="Không thể nâng cấp ảnh", is_indeterminate=False, error=str(error))
            except Exception:
                logger.exception("Image upscale job %s failed", job.job_id)
                job.update(
                    state="failed",
                    progress=0,
                    stage="Không thể nâng cấp ảnh",
                    is_indeterminate=False,
                    error="Đã xảy ra lỗi khi xử lý ảnh. Hãy thử lại với ảnh khác hoặc kiểm tra log backend.",
                )

        job = app.state.jobs.submit(request.asset_id, run)
        return job.snapshot()

    @app.post("/api/v1/vectorize/jobs", status_code=202, dependencies=[Depends(authorize)])
    def create_vectorize_job(request: VectorizeJobRequest) -> dict[str, object]:
        asset = app.state.assets.get(request.asset_id)
        colors = request.color_count or 8
        if request.detail is not None:
            detail = request.detail
        elif request.simplification is not None:
            detail = 100 - request.simplification
        else:
            detail = 50

        def run(job: Job) -> None:
            job.update(state="processing", progress=5, stage="Đang nhận diện logo và nền…", is_indeterminate=True)
            if request.output_mode == "cutout":
                try:
                    from PIL import Image
                    with Image.open(asset.path) as source:
                        source.load()
                        cut = layered_vector.cutout(source)
                    output_directory = app.state.output_directory
                    output_directory.mkdir(parents=True, exist_ok=True)
                    path = output_directory / f"{job.job_id}.svg"
                    path.write_text(cut.svg, encoding="utf-8")
                    (output_directory / f"{job.job_id}.png").write_bytes(cut.png)
                    job.update(
                        state="succeeded", progress=100, is_indeterminate=False,
                        stage="Đã tách logo khỏi nền",
                        result_path=path, result_width=cut.width, result_height=cut.height,
                        result_size=path.stat().st_size, result_paths=1,
                        result_engine="cutout", result_image_type="auto", result_mode="cutout",
                        result_text_layers=0, result_gradients=0,
                        result_processing_time_ms=round(cut.seconds * 1000),
                        result_input_width=cut.width, result_input_height=cut.height,
                        result_trace_width=cut.width, result_trace_height=cut.height,
                        result_regions=1, result_pipeline="cutout", result_vector_method="cutout",
                        result_engine_metadata={"background": cut.background, "aiMatte": cut.ai_matte},
                        result_text_mode="outlined", result_warnings=list(cut.warnings))
                except Exception:
                    logger.exception("Background cut-out job %s failed", job.job_id)
                    job.update(state="failed", progress=0, stage="Không thể tách nền", is_indeterminate=False,
                               error="Đã xảy ra lỗi khi tách nền. Hãy thử lại với ảnh khác hoặc kiểm tra log backend.")
                return
            try:
                from PIL import Image
                source_path = asset.path
                longest = max(asset.width or 0, asset.height or 0)
                if 0 < longest < 1600:
                    # Small/JPEG logos: sharpen and enlarge with the app's Real-ESRGAN
                    # (anime model keeps flat colours and crisp edges) before tracing.
                    try:
                        upscaled_path, _, _, _ = app.state.upscaler.run(
                            job, asset, scale=4 if longest <= 800 else 2,
                            model_choice="Real-ESRGAN Anime", reduce_noise=True, sharpen=False,
                            output_format="PNG",
                            output_directory=app.state.output_directory / "vector-inputs")
                        source_path = upscaled_path
                    except Exception:
                        logger.exception("AI upscale before vectorization failed; tracing the original")
                job.update(progress=70, stage="Đang tách nền và vẽ các lớp màu…", is_indeterminate=True)
                with Image.open(source_path) as source:
                    source.load()
                    result = layered_vector.vectorize(
                        source, colors=colors, detail=detail,
                        remove_background=request.transparent_background,
                        ocr_dir=app.state.easyocr_directory if app.state.easyocr_directory.is_dir() else None)
                output_directory = app.state.output_directory
                output_directory.mkdir(parents=True, exist_ok=True)
                path = output_directory / f"{job.job_id}.svg"
                path.write_text(result.svg, encoding="utf-8")
                job.update(
                    state="succeeded", progress=100, is_indeterminate=False,
                    stage="Đã chuyển ảnh thành vector",
                    result_path=path, result_width=result.width, result_height=result.height,
                    result_size=path.stat().st_size, result_paths=result.path_count,
                    result_engine="layered-trace", result_image_type="auto", result_mode="auto",
                    result_text_layers=0, result_gradients=0,
                    result_processing_time_ms=round(result.seconds * 1000),
                    result_input_width=result.width, result_input_height=result.height,
                    result_trace_width=result.width, result_trace_height=result.height,
                    result_regions=len(result.colors), result_pipeline="layered_trace",
                    result_vector_method="layered_trace",
                    result_engine_metadata={"colors": result.colors, "background": result.background,
                                            "aiMatte": result.ai_matte, "detail": detail},
                    result_text_mode="outlined", result_warnings=list(result.warnings))
            except Exception:
                logger.exception("Image vectorization job %s failed", job.job_id)
                job.update(state="failed", progress=0, stage="Không thể vector hóa ảnh", is_indeterminate=False,
                           error="Đã xảy ra lỗi khi xử lý ảnh. Hãy thử lại với ảnh khác hoặc kiểm tra log backend.")

        job = app.state.jobs.submit(request.asset_id, run)
        return job.snapshot()

    @app.post("/api/v1/die-cut/jobs", status_code=202, dependencies=[Depends(authorize)])
    def create_die_cut_job(request: DieCutJobRequest) -> dict[str, object]:
        asset = app.state.assets.get(request.asset_id)

        def run(job: Job) -> None:
            try:
                result_path, width, height, size, path_count = app.state.die_cutter.run(
                    job,
                    asset,
                    offset_mm=request.offset_mm,
                    artwork_width_mm=request.artwork_width_mm,
                    auto_detect=request.auto_detect,
                    smooth_path=request.smooth_path,
                    complexity=request.complexity,
                    strokes=[stroke.model_dump() for stroke in request.strokes],
                    output_directory=app.state.output_directory,
                )
                job.update(
                    state="succeeded",
                    progress=100,
                    stage="Đã tạo đường bế SVG",
                    is_indeterminate=False,
                    result_path=result_path,
                    result_width=width,
                    result_height=height,
                    result_size=size,
                    result_paths=path_count,
                )
            except DieCutError as error:
                job.update(state="failed", progress=0, stage="Không thể tạo đường bế", is_indeterminate=False, error=str(error))
            except Exception:
                logger.exception("Die-cut job %s failed", job.job_id)
                job.update(
                    state="failed",
                    progress=0,
                    stage="Không thể tạo đường bế",
                    is_indeterminate=False,
                    error="Đã xảy ra lỗi khi tạo đường bế. Hãy thử ảnh khác hoặc kiểm tra log backend.",
                )

        job = app.state.jobs.submit(request.asset_id, run)
        return job.snapshot()

    @app.get("/api/v1/jobs/{job_id}", dependencies=[Depends(authorize)])
    def get_job(job_id: str) -> dict[str, object]:
        job = app.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ.")
        return job.snapshot()

    @app.get("/api/v1/jobs/{job_id}/result", dependencies=[Depends(authorize)])
    def get_job_result(job_id: str) -> FileResponse:
        job = app.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ.")
        snapshot = job.snapshot()
        if snapshot["state"] != "succeeded" or job.result_path is None or not job.result_path.is_file():
            raise HTTPException(status_code=409, detail="Ảnh kết quả chưa sẵn sàng.")
        suffix = job.result_path.suffix.lower()
        media_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".tif": "image/tiff",
            ".svg": "image/svg+xml",
        }.get(suffix, "application/octet-stream")
        return FileResponse(job.result_path, media_type=media_type, filename=job.result_path.name)

    @app.post("/api/v1/shutdown", status_code=202, dependencies=[Depends(authorize)])
    def shutdown(background_tasks: BackgroundTasks, request: Request) -> dict[str, str]:
        def stop_after_response() -> None:
            server = getattr(request.app.state, "uvicorn_server", None)
            if server is not None:
                server.should_exit = True

        with app.state._shutdown_lock:
            background_tasks.add_task(stop_after_response)
        return {"status": "stopping"}

    @app.on_event("shutdown")
    def close_services() -> None:
        app.state.jobs.shutdown()
        app.state.upscaler.clear()
        app.state.fashion.unload()

    return app
