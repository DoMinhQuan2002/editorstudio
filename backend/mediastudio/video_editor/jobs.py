from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock
from uuid import uuid4


@dataclass(slots=True)
class VideoJob:
    job_id: str
    project_id: str
    state: str = "queued"
    progress: int | None = 0
    stage: str = "Đang chờ kết xuất"
    output_path: Path | None = None
    export_result: dict[str, object] | None = None
    error: str | None = None
    error_code: str | None = None
    job_type: str = "render"
    template_id: str | None = None
    template_version: str | None = None
    selection_session_id: str | None = None
    binding_fingerprint: str | None = None
    idempotency_fingerprint: str | None = None
    media_bindings: dict[str, str] = field(default_factory=dict)
    output_settings: dict[str, object] = field(default_factory=dict)
    current_stage: str | None = None
    stages: list[dict[str, object]] = field(default_factory=list)
    draft_project_id: str | None = None
    composition_reference: str | None = None
    preview_reference: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    cancel_event: Event = field(default_factory=Event, repr=False)
    lock: Lock = field(default_factory=Lock, repr=False)

    def update(self, **changes: object) -> None:
        with self.lock:
            for name, value in changes.items():
                setattr(self, name, value)
            self.updated_at = datetime.now(timezone.utc)

    def update_stage(self, stage_id: str, status: str, message: str | None = None,
                     error_code: str | None = None, duration_seconds: float | None = None) -> None:
        with self.lock:
            for item in self.stages:
                if item["stageId"] == stage_id:
                    item["status"] = status
                    item["message"] = message
                    item["errorCode"] = error_code
                    item["durationSeconds"] = (round(duration_seconds, 3)
                                                if duration_seconds is not None else None)
                    self.current_stage = stage_id if status in {"RUNNING", "FAILED"} else self.current_stage
                    self.stage = str(item["name"])
                    break
            self.updated_at = datetime.now(timezone.utc)

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            return {
                "jobId": self.job_id,
                "projectId": self.project_id,
                "state": self.state,
                "progress": self.progress,
                "progressPercent": self.progress,
                "stage": self.stage,
                "outputFileName": self.output_path.name if self.output_path else None,
                "outputPath": str(self.output_path) if self.output_path else None,
                "exportResult": dict(self.export_result) if self.export_result else None,
                "error": self.error,
                "errorCode": self.error_code,
                "errorMessage": self.error,
                "jobType": self.job_type,
                "jobStatus": self.state.upper(),
                "templateId": self.template_id,
                "templateVersion": self.template_version,
                "selectionSessionId": self.selection_session_id,
                "bindingFingerprint": self.binding_fingerprint,
                "idempotencyFingerprint": self.idempotency_fingerprint,
                "mediaBindings": dict(self.media_bindings),
                "outputSettings": dict(self.output_settings),
                "currentStage": self.current_stage,
                "stages": [dict(item) for item in self.stages],
                "draftProjectId": self.draft_project_id,
                "compositionReference": self.composition_reference,
                "previewReference": self.preview_reference,
                "createdAt": self.created_at.isoformat(),
                "updatedAt": self.updated_at.isoformat(),
            }


class VideoJobManager:
    def __init__(self, max_workers: int = 1) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="video-render")
        self._jobs: dict[str, VideoJob] = {}
        self._futures: dict[str, Future[None]] = {}
        self._idempotency: dict[str, str] = {}
        self._lock = Lock()

    def submit(self, project_id: str, worker, *, job_type: str = "render",
               template_id: str | None = None, template_version: str | None = None,
               selection_session_id: str | None = None, binding_fingerprint: str | None = None,
               stages: list[dict[str, object]] | None = None,
               media_bindings: dict[str, str] | None = None,
               output_settings: dict[str, object] | None = None,
               composition_reference: str | None = None,
               draft_project_id: str | None = None,
               idempotency_fingerprint: str | None = None,
               idempotency_key: str | None = None) -> VideoJob:
        with self._lock:
            if idempotency_key is not None and idempotency_key in self._idempotency:
                existing = self._jobs.get(self._idempotency[idempotency_key])
                if existing is not None and existing.state not in {"failed", "cancelled"}:
                    if existing.binding_fingerprint != binding_fingerprint:
                        raise ValueError("Selection session đã được dùng với binding khác.")
                    if (existing.idempotency_fingerprint != idempotency_fingerprint
                            or existing.media_bindings != (media_bindings or {})
                            or existing.output_settings != (output_settings or {})):
                        raise ValueError("Request ID đã được dùng với cấu hình export khác.")
                    return existing
            job = VideoJob(
                job_id=uuid4().hex, project_id=project_id, job_type=job_type,
                template_id=template_id, template_version=template_version,
                selection_session_id=selection_session_id,
                binding_fingerprint=binding_fingerprint, media_bindings=media_bindings or {},
                output_settings=output_settings or {}, composition_reference=composition_reference,
                draft_project_id=draft_project_id,
                idempotency_fingerprint=idempotency_fingerprint,
                stages=stages or [],
                progress=None if job_type == "template-processing" else 0,
                stage="Đang chờ xử lý mẫu" if job_type == "template-processing" else "Đang chờ kết xuất",
            )
            self._jobs[job.job_id] = job
            self._futures[job.job_id] = self._executor.submit(worker, job)
            if idempotency_key is not None:
                self._idempotency[idempotency_key] = job.job_id
        return job

    def get(self, job_id: str) -> VideoJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def get_idempotent(self, idempotency_key: str) -> VideoJob | None:
        with self._lock:
            job_id = self._idempotency.get(idempotency_key)
            return self._jobs.get(job_id) if job_id is not None else None

    def cancel(self, job_id: str) -> VideoJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            future = self._futures.get(job_id)
        if job is None:
            return None
        job.cancel_event.set()
        if future is not None and future.cancel():
            job.update(state="cancelled", progress=0, stage="Đã hủy")
        return job

    def shutdown(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel_event.set()
        self._executor.shutdown(wait=False, cancel_futures=True)
