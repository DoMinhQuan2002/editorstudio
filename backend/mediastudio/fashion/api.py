"""HTTP endpoints for Fashion Studio. Results use the shared /api/v1/jobs/{id}/result route."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Literal

from fastapi import Depends, FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from mediastudio.jobs.manager import Job

from .engine import FashionError, QwenFashionEngine
from .prompts import SCENE_PRESETS, VIEW_PRESETS, FashionRequest, build_prompt

logger = logging.getLogger("mediastudio.fashion")


class FashionJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: Literal["try_on", "scene", "recolor", "new_view"]
    person_asset_id: str = Field(min_length=32, max_length=32)
    garment_asset_id: str | None = Field(default=None, min_length=32, max_length=32)
    scene_preset: str | None = Field(default=None, max_length=40)
    scene_text: str | None = Field(default=None, max_length=400)
    color: str | None = Field(default=None, max_length=60)
    view_preset: str | None = Field(default=None, max_length=40)
    extra_prompt: str | None = Field(default=None, max_length=400)
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647)
    steps: int | None = Field(default=None, ge=4, le=60)


def install_fashion_api(app: FastAPI, data_directory: Path, authorize: Callable[..., None]) -> None:
    engine = QwenFashionEngine(data_directory / "models" / "huggingface")
    app.state.fashion = engine
    output_directory = data_directory / "results" / "fashion"

    @app.get("/api/v1/fashion/status", dependencies=[Depends(authorize)])
    def fashion_status() -> dict[str, object]:
        status = engine.status()
        status["scenePresets"] = list(SCENE_PRESETS)
        status["viewPresets"] = list(VIEW_PRESETS)
        return status

    @app.post("/api/v1/fashion/download", status_code=202, dependencies=[Depends(authorize)])
    def fashion_download() -> dict[str, object]:
        status = engine.status()
        if status["missingPackages"]:
            raise HTTPException(status_code=409, detail=status["message"])

        def run(job: Job) -> None:
            job.update(state="processing", progress=1, is_indeterminate=True, stage="Đang chuẩn bị tải model…")
            try:
                engine.download(lambda text: job.update(stage=text))
                job.update(state="succeeded", progress=100, is_indeterminate=False, stage="Đã tải xong model.")
            except Exception as error:
                logger.exception("Qwen model download failed")
                job.update(state="failed", progress=0, is_indeterminate=False, stage="Tải model thất bại",
                           error=f"Không tải được model: {error}")

        return app.state.jobs.submit("qwen-image-edit", run).snapshot()

    @app.post("/api/v1/fashion/jobs", status_code=202, dependencies=[Depends(authorize)])
    def create_fashion_job(request: FashionJobRequest) -> dict[str, object]:
        person = app.state.assets.get(request.person_asset_id)
        garment = app.state.assets.get(request.garment_asset_id) if request.garment_asset_id else None
        fashion_request = FashionRequest(
            task=request.task, has_garment=garment is not None, scene_preset=request.scene_preset,
            scene_text=request.scene_text, color=request.color, view_preset=request.view_preset,
            extra=request.extra_prompt)
        try:
            build_prompt(fashion_request)            # validate inputs before queuing
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        def run(job: Job) -> None:
            job.update(state="processing", progress=1, stage="Đã nhận tác vụ", is_indeterminate=True)
            try:
                images = [Image.open(person.path)]
                if garment is not None:
                    images.append(Image.open(garment.path))
                result = engine.run(
                    fashion_request, images, seed=request.seed, steps=request.steps,
                    progress=lambda text: job.update(stage=text, is_indeterminate=True),
                    step_progress=lambda done, total: job.update(
                        progress=max(2, min(98, round(done * 100 / total))), is_indeterminate=False,
                        stage=f"Đang tạo ảnh… bước {done}/{total}"))
                output_directory.mkdir(parents=True, exist_ok=True)
                path = output_directory / f"{job.job_id}.png"
                result.image.save(path, "PNG")
                job.update(state="succeeded", progress=100, is_indeterminate=False, stage="Đã tạo ảnh xong",
                           result_path=path, result_width=result.image.width, result_height=result.image.height,
                           result_size=path.stat().st_size, result_engine=engine.model_id,
                           result_mode=request.task,
                           result_processing_time_ms=round(result.seconds * 1000),
                           result_engine_metadata={"seed": result.seed, "steps": result.steps,
                                                   "memoryMode": result.memory_mode, "prompt": result.prompt})
            except FashionError as error:
                job.update(state="failed", progress=0, is_indeterminate=False, stage="Không thể tạo ảnh",
                           error=str(error), error_code=error.code)
            except Exception:
                logger.exception("Fashion job %s failed", job.job_id)
                job.update(state="failed", progress=0, is_indeterminate=False, stage="Không thể tạo ảnh",
                           error="Đã xảy ra lỗi khi tạo ảnh. Kiểm tra log backend để biết chi tiết.")

        return app.state.jobs.submit(request.person_asset_id, run).snapshot()
