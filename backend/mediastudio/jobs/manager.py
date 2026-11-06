from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Callable
from uuid import uuid4


@dataclass(slots=True)
class Job:
    job_id: str
    asset_id: str
    state: str = "queued"
    progress: int = 0
    stage: str = "Đang chờ xử lý"
    is_indeterminate: bool = False
    result_path: Path | None = None
    result_width: int | None = None
    result_height: int | None = None
    result_size: int | None = None
    result_paths: int | None = None
    result_engine: str | None = None
    result_image_type: str | None = None
    result_mode: str | None = None
    result_text_layers: int | None = None
    result_gradients: int | None = None
    result_processing_time_ms: int | None = None
    result_input_width: int | None = None
    result_input_height: int | None = None
    result_trace_width: int | None = None
    result_trace_height: int | None = None
    result_regions: int | None = None
    result_pipeline: str | None = None
    result_vector_method: str | None = None
    result_engine_metadata: dict[str, object] = field(default_factory=dict)
    result_text_mode: str | None = None
    result_editable_text_count: int | None = None
    result_outlined_text_count: int | None = None
    result_appearance_layers: int | None = None
    result_clip_paths: int | None = None
    result_warnings: list[str] = field(default_factory=list)
    result_warning_details: list[dict[str, str]] = field(default_factory=list)
    result_text_element_count: int | None = None
    result_outlined_text_path_count: int | None = None
    result_embedded_raster_count: int | None = None
    result_phase_timings_ms: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    error_code: str | None = None
    error_details: dict[str, object] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def update(self, **changes: object) -> None:
        with self._lock:
            for name, value in changes.items():
                setattr(self, name, value)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "jobId": self.job_id,
                "assetId": self.asset_id,
                "state": self.state,
                "progress": self.progress,
                "stage": self.stage,
                "isIndeterminate": self.is_indeterminate,
                "resultWidth": self.result_width,
                "resultHeight": self.result_height,
                "resultSize": self.result_size,
                "resultPaths": self.result_paths,
                "resultEngine": self.result_engine,
                "resultImageType": self.result_image_type,
                "resultMode": self.result_mode,
                "resultTextLayers": self.result_text_layers,
                "resultGradients": self.result_gradients,
                "resultProcessingTimeMs": self.result_processing_time_ms,
                "resultInputWidth": self.result_input_width,
                "resultInputHeight": self.result_input_height,
                "resultTraceWidth": self.result_trace_width,
                "resultTraceHeight": self.result_trace_height,
                "resultRegions": self.result_regions,
                "resultPipeline": self.result_pipeline,
                "resultVectorMethod": self.result_vector_method,
                "resultEngineMetadata": dict(self.result_engine_metadata),
                "resultTextMode": self.result_text_mode,
                "resultEditableTextCount": self.result_editable_text_count,
                "resultOutlinedTextCount": self.result_outlined_text_count,
                "resultAppearanceLayers": self.result_appearance_layers,
                "resultClipPaths": self.result_clip_paths,
                "resultWarnings": list(self.result_warnings),
                "resultWarningDetails": [dict(item) for item in self.result_warning_details],
                "resultTextElementCount": self.result_text_element_count,
                "resultOutlinedTextPathCount": self.result_outlined_text_path_count,
                "resultEmbeddedRasterCount": self.result_embedded_raster_count,
                "resultPhaseTimingsMs": dict(self.result_phase_timings_ms),
                "error": self.error,
                "errorCode": self.error_code,
                "errorDetails": dict(self.error_details),
            }


class JobManager:
    def __init__(self, max_workers: int = 1) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="media-ai")
        self._jobs: dict[str, Job] = {}
        self._lock = Lock()
        self._futures: dict[str, Future[None]] = {}

    def submit(self, asset_id: str, run: Callable[[Job], None]) -> Job:
        job = Job(job_id=uuid4().hex, asset_id=asset_id)
        with self._lock:
            self._jobs[job.job_id] = job
            self._futures[job.job_id] = self._executor.submit(run, job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
