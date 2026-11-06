from __future__ import annotations

"""Measure Smart V2 production stages and D1 retry costs without source edits."""

import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable
import argparse

import numpy as np
from PIL import Image, ImageOps

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
ARTIFACTS = BACKEND / "artifacts/contour_preserving/task_08b_0_6"
CAMERA = BACKEND / "artifacts/contour_preserving/task_08a_1/acquired/scikit_image/camera.png"
FIXTURES = [
    ("active_fox_native_jpeg", "native logo", BACKEND / "tests/fixtures/active_fox.jpg"),
    ("synthetic_thin_line", "synthetic thin line", BACKEND / "artifacts/contour_preserving/task_07_2/synthetic_sources/thin_line.png"),
    ("synthetic_multiregion_illustration", "synthetic multiregion illustration", BACKEND / "artifacts/contour_preserving/task_07_2/synthetic_sources/multiregion_illustration.png"),
    ("synthetic_flat_geometry", "flat geometry", BACKEND / "artifacts/contour_preserving/task_07_2/synthetic_sources/rounded_rectangle.png"),
    ("synthetic_linear_gradient", "linear gradient", BACKEND / "artifacts/contour_preserving/task_07_2/synthetic_sources/linear_gradient.png"),
]
sys.path.insert(0, str(BACKEND))

from mediastudio.image_tools.vectorization_v2 import phase_d, phase_d1, production  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_hashes() -> dict[str, str]:
    groups = {
        "smart_v2": [*sorted((BACKEND / "mediastudio/image_tools/vectorization_v2").glob("*.py")),
                     BACKEND / "mediastudio/image_tools/vectorize.py"],
        "contour": sorted((BACKEND / "mediastudio/image_tools/vectorization_contour").glob("*.py")),
    }
    return {
        f"{group}/{path.relative_to(BACKEND).as_posix()}": sha256_file(path)
        for group, paths in groups.items() for path in paths if path.is_file()
    }


def metric_snapshot(metrics: dict[str, Any]) -> dict[str, Any]:
    per_region: dict[str, int] = {}
    for row in metrics.get("per_region", {}).values():
        region_id = str(row.get("region_id"))
        per_region[region_id] = per_region.get(region_id, 0) + int(row.get("self_intersection_count", 0))
    keys = (
        "self_intersection_count", "silhouette_iou", "silhouette_area_error_ratio",
        "mean_boundary_error", "max_boundary_error", "shared_boundary_count",
        "shared_boundary_mismatch_count", "shared_interface_gap_pixels",
        "shared_interface_overlap_pixels", "shared_interface_overlap_area_status",
        "pixel_center_region_overlap_pixels", "geometry_missing_source_pixels",
        "geometry_extra_pixels", "topology_relationship_mismatch_count",
        "hole_count_before", "hole_count_after", "total_regions",
        "total_raw_boundary_points", "total_bezier_segments", "total_bezier_anchor_count",
    )
    result = {key: metrics.get(key) for key in keys}
    result["per_region_invalid_ring_counts"] = per_region
    result["shared_interface_overlap_failure_count"] = len(
        metrics.get("shared_interface_overlap_area_failures", [])
    )
    return result


def boundary_ref_transition(previous: list[dict[str, Any]] | None,
                            current: list[dict[str, Any]]) -> dict[str, Any] | None:
    if previous is None:
        return None
    key = lambda row: (row.get("boundary_id"), row.get("component_index"))
    before, after = {key(row) for row in previous}, {key(row) for row in current}
    return {
        "persistent": [list(item) for item in sorted(before & after, key=str)],
        "new": [list(item) for item in sorted(after - before, key=str)],
        "removed": [list(item) for item in sorted(before - after, key=str)],
    }


class PerformanceRecorder:
    """Monotonic timings and event traces for one isolated diagnostic run."""

    def __init__(self) -> None:
        self.reset("uninitialized")
        self.wrappers: list[tuple[Any, str, Any]] = []
        self.capture: dict[str, Any] = {}

    def reset(self, run_id: str) -> None:
        self.run_id = run_id
        self.enabled = True
        self.d1_active = False
        self.local_repair_active = False
        self.active_retry: dict[str, Any] | None = None
        self.retry_rows: list[dict[str, Any]] = []
        self.previous_retry_refs: list[dict[str, Any]] | None = None
        self.metric_rows: list[dict[str, Any]] = []
        self.stage_stats: dict[str, dict[str, float | int]] = {}
        self.d1_started_ns: int | None = None
        self.d1_elapsed_ms: float | None = None
        self.metric_role_counts: dict[str, int] = {}
        self.local_repair_summary: dict[str, Any] | None = None
        self.local_repair_metrics: dict[str, Any] | None = None
        self.last_metric_snapshot: dict[str, Any] | None = None
        self.expect_post_repair_metrics = False
        self.d1_result: Any | None = None

    def add(self, name: str, elapsed_ns: int, *, call_count: int = 1) -> None:
        row = self.stage_stats.setdefault(name, {"calls": 0, "total_ms": 0.0, "max_ms": 0.0})
        elapsed_ms = elapsed_ns / 1_000_000
        row["calls"] = int(row["calls"]) + call_count
        row["total_ms"] = float(row["total_ms"]) + elapsed_ms
        row["max_ms"] = max(float(row["max_ms"]), elapsed_ms)

    def wrap(self, owner: Any, attr: str, name: str,
             predicate: Callable[[], bool] | None = None,
             after: Callable[[Any, tuple[Any, ...], dict[str, Any]], None] | None = None) -> None:
        original = getattr(owner, attr)

        def measured(*args: Any, **kwargs: Any) -> Any:
            enabled = self.enabled and (predicate is None or predicate())
            if not enabled:
                return original(*args, **kwargs)
            started_ns = time.perf_counter_ns()
            value = original(*args, **kwargs)
            elapsed_ns = time.perf_counter_ns() - started_ns
            self.add(name, elapsed_ns)
            if after is not None:
                after(value, args, kwargs)
            return value

        setattr(owner, attr, measured)
        self.wrappers.append((owner, attr, original))

    def restore(self) -> None:
        for owner, attr, original in reversed(self.wrappers):
            setattr(owner, attr, original)
        self.wrappers.clear()

    def begin_d1(self) -> None:
        self.d1_active = True
        self.local_repair_active = False
        self.active_retry = None
        self.retry_rows = []
        self.previous_retry_refs = None
        self.metric_rows = []
        self.metric_role_counts = {}
        self.local_repair_summary = None
        self.local_repair_metrics = None
        self.last_metric_snapshot = None
        self.expect_post_repair_metrics = False
        self.d1_started_ns = time.perf_counter_ns()

    def end_d1(self, model: Any) -> None:
        self.d1_elapsed_ms = (time.perf_counter_ns() - self.d1_started_ns) / 1_000_000
        self.d1_active = False
        self.d1_result = model

    def on_metrics(self, metrics: dict[str, Any], elapsed_ns: int) -> None:
        snap = metric_snapshot(metrics)
        if self.active_retry is not None:
            row = self.active_retry
            row["metrics_after_ms"] = elapsed_ns / 1_000_000
            row["crossings_after"] = metrics.get("self_intersection_count")
            row["metrics_after"] = snap
            before_regions = row.get("metrics_before", {}).get("per_region_invalid_ring_counts", {})
            after_regions = snap.get("per_region_invalid_ring_counts", {})
            region_deltas = []
            for region_id in sorted(set(before_regions) | set(after_regions), key=lambda v: int(v)):
                before, after = int(before_regions.get(region_id, 0)), int(after_regions.get(region_id, 0))
                if before != after:
                    region_deltas.append({"region_id": int(region_id), "before": before,
                                          "after": after, "delta": after - before})
            row["region_invalid_ring_deltas"] = region_deltas
            row["invalid_rings_increased"] = sum(max(0, item["delta"]) for item in region_deltas)
            row["invalid_rings_decreased"] = sum(max(0, -item["delta"]) for item in region_deltas)
            row["duration_ms"] = (time.perf_counter_ns() - row["started_ns"]) / 1_000_000
            row["outcome"] = "completed_refit_and_metrics"
            self.active_retry = None
        elif self.local_repair_active:
            self.local_repair_metrics = snap
        elif self.expect_post_repair_metrics:
            self.metric_role_counts["post_local_repair"] = self.metric_role_counts.get("post_local_repair", 0) + 1
            self.metric_rows.append({"role": "post_local_repair", "metrics": snap})
            self.expect_post_repair_metrics = False
        else:
            role = "initial_fit" if not self.metric_rows else "metrics_recompute"
            self.metric_role_counts[role] = self.metric_role_counts.get(role, 0) + 1
            self.metric_rows.append({"role": role, "metrics": snap})
        self.last_metric_snapshot = snap

    def begin_retry(self, invalid_refs: set[tuple[str, int | None]],
                    started_ns: int | None = None) -> None:
        attempt = len(self.retry_rows) + 1
        refs = [{"boundary_id": boundary_id, "component_index": component_index}
                for boundary_id, component_index in sorted(
                    invalid_refs, key=lambda item: (item[0], -1 if item[1] is None else item[1]))]
        row: dict[str, Any] = {
            "attempt": attempt,
            "crossings_before": None if self.last_metric_snapshot is None else
                self.last_metric_snapshot.get("self_intersection_count"),
            "metrics_before": self.last_metric_snapshot,
            "invalid_boundary_refs": refs,
            "invalid_boundary_ref_count": len(refs),
            "boundary_ref_transition": boundary_ref_transition(self.previous_retry_refs, refs),
            "started_ns": started_ns if started_ns is not None else time.perf_counter_ns(),
        }
        self.retry_rows.append(row)
        self.previous_retry_refs = refs
        self.active_retry = row
        if not refs:
            row["duration_ms"] = 0.0
            row["outcome"] = "no_invalid_boundary_refs"
            row["crossings_after"] = row["crossings_before"]
            self.active_retry = None

    def finish_unclosed_retry(self) -> None:
        if self.active_retry is None:
            return
        self.active_retry["duration_ms"] = (time.perf_counter_ns() - self.active_retry["started_ns"]) / 1_000_000
        self.active_retry["outcome"] = "no_post_refit_metrics_observed"
        self.active_retry = None

    def d1_report(self) -> dict[str, Any]:
        rows = []
        for row in self.retry_rows:
            rows.append({key: value for key, value in row.items() if key != "started_ns"})
        return {
            "run_id": self.run_id,
            "d1_total_ms": self.d1_elapsed_ms,
            "timings": {key.removeprefix(self.run_id + ".d1."): value
                        for key, value in self.stage_stats.items()
                        if key.startswith(self.run_id + ".d1.")},
            "metric_snapshots": self.metric_rows,
            "retry_attempts": rows,
            "local_repair": self.local_repair_summary,
            "final_geometry_validation": None if self.d1_result is None else
                self.d1_result.metrics.get("final_geometry_validation"),
            "final_metrics": None if self.d1_result is None else metric_snapshot(self.d1_result.metrics),
        }


RECORDER = PerformanceRecorder()


def _active_d1(name: str) -> str:
    if RECORDER.active_retry is not None:
        return f"{RECORDER.run_id}.d1.retry_{RECORDER.active_retry['attempt']}.{name}"
    if RECORDER.local_repair_active:
        return f"{RECORDER.run_id}.d1.local_repair.{name}"
    return f"{RECORDER.run_id}.d1.{name}"


def install_instrumentation() -> None:
    def wrap_d1(attr: str, label: str,
                after: Callable[..., None] | None = None) -> None:
        original = getattr(phase_d1, attr)

        def measured(*args: Any, **kwargs: Any) -> Any:
            if not RECORDER.enabled or not RECORDER.d1_active:
                return original(*args, **kwargs)
            started = time.perf_counter_ns()
            value = original(*args, **kwargs)
            elapsed_ns = time.perf_counter_ns() - started
            RECORDER.add(_active_d1(label), elapsed_ns)
            if after is not None:
                after(value, args, kwargs, started, elapsed_ns)
            return value

        setattr(phase_d1, attr, measured)
        RECORDER.wrappers.append((phase_d1, attr, original))

    def on_invalid_refs(value: Any, _args: tuple[Any, ...], _kwargs: dict[str, Any],
                        started_ns: int, _elapsed_ns: int) -> None:
        if RECORDER.d1_active and not RECORDER.local_repair_active:
            RECORDER.begin_retry(value, started_ns)

    def on_metrics(value: Any, _args: tuple[Any, ...], _kwargs: dict[str, Any],
                   _started_ns: int, elapsed_ns: int) -> None:
        if RECORDER.d1_active:
            RECORDER.on_metrics(value, elapsed_ns)

    for attr, label, after in (
        ("_construct_model", "geometry_preparation", None),
        ("_fit_all_boundaries", "initial_bezier_fitting", None),
        ("_fit_boundary_component", "boundary_component_fit", None),
        ("_fit_regularized_polyline", "bezier_polyline_fit", None),
        ("_invalid_boundary_refs", "invalid_boundary_scan", on_invalid_refs),
        ("_compute_metrics", "geometry_metrics", on_metrics),
        ("_geometry_validation_report", "final_geometry_validation", None),
    ):
        wrap_d1(attr, label, after)

    original_repair = phase_d1._repair_cubic_self_crossings

    def measured_repair(*args: Any, **kwargs: Any) -> Any:
        if not RECORDER.enabled or not RECORDER.d1_active:
            return original_repair(*args, **kwargs)
        RECORDER.local_repair_active = True
        started = time.perf_counter_ns()
        try:
            value = original_repair(*args, **kwargs)
        finally:
            RECORDER.add(f"{RECORDER.run_id}.d1.local_repair", time.perf_counter_ns() - started)
            RECORDER.local_repair_active = False
        RECORDER.local_repair_summary = value
        RECORDER.expect_post_repair_metrics = value.get("status") == "applied"
        return value

    phase_d1._repair_cubic_self_crossings = measured_repair
    RECORDER.wrappers.append((phase_d1, "_repair_cubic_self_crossings", original_repair))

    for owner, attr, label in (
        (phase_d, "_measure_shared_polygon_overlap", "shared_overlap_metric"),
        (phase_d, "path_points", "polygon_sampling_path_points"),
        (phase_d, "_segment_samples", "bezier_sample_generation"),
        (phase_d1, "path_points", "polygon_sampling_path_points"),
        (phase_d1, "_segment_samples", "bezier_sample_generation"),
    ):
        original = getattr(owner, attr)

        def measured(*args: Any, _orig: Any = original, _label: str = label,
                     _owner: Any = owner, **kwargs: Any) -> Any:
            if not RECORDER.enabled or not RECORDER.d1_active:
                return _orig(*args, **kwargs)
            started = time.perf_counter_ns()
            value = _orig(*args, **kwargs)
            RECORDER.add(_active_d1(_label), time.perf_counter_ns() - started)
            return value

        setattr(owner, attr, measured)
        RECORDER.wrappers.append((owner, attr, original))

    original_d1 = production.run_phase_d1

    def measured_d1(*args: Any, **kwargs: Any) -> Any:
        if not RECORDER.enabled:
            return original_d1(*args, **kwargs)
        RECORDER.begin_d1()
        started = time.perf_counter_ns()
        try:
            model = original_d1(*args, **kwargs)
            return model
        finally:
            RECORDER.finish_unclosed_retry()
            elapsed = time.perf_counter_ns() - started
            RECORDER.add(f"{RECORDER.run_id}.d1.wrapper_total", elapsed)
            if "model" in locals():
                RECORDER.end_d1(model)
            else:
                RECORDER.d1_active = False

    production.run_phase_d1 = measured_d1
    RECORDER.wrappers.append((production, "run_phase_d1", original_d1))

    for attr, label in (
        ("run_phase_a", "phase_a"),
        ("run_phase_b", "phase_b_ocr"),
        ("run_phase_c", "phase_c_segmentation"),
        ("run_phase_e1", "phase_e1_appearance"),
        ("reconstruct_text_layers", "text_reconstruction"),
        ("compose_production_svg", "svg_composition"),
        ("rasterize_svg", "svg_render_validation"),
    ):
        original = getattr(production, attr)

        def measured(*args: Any, _orig: Any = original, _label: str = label, **kwargs: Any) -> Any:
            started = time.perf_counter_ns()
            value = _orig(*args, **kwargs)
            RECORDER.add(f"{RECORDER.run_id}.{_label}", time.perf_counter_ns() - started)
            if _label == "phase_b_ocr":
                RECORDER.capture["phase_b"] = value
            elif _label == "phase_c_segmentation":
                RECORDER.capture["phase_c"] = value
            elif _label == "phase_e1_appearance":
                RECORDER.capture["appearance"] = value
            elif _label == "text_reconstruction":
                RECORDER.capture["text_layers"] = value[0]
                RECORDER.capture["text_warnings"] = value[1]
            elif _label == "svg_render_validation":
                RECORDER.capture["baseline_render_array"] = value
            return value

        setattr(production, attr, measured)
        RECORDER.wrappers.append((production, attr, original))

    original_pipeline = production.run_vectorization_v2

    def measured_pipeline(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter_ns()
        result = original_pipeline(*args, **kwargs)
        RECORDER.add(f"{RECORDER.run_id}.vectorization_core", time.perf_counter_ns() - started)
        RECORDER.capture["production_result"] = result
        return result

    production.run_vectorization_v2 = measured_pipeline
    RECORDER.wrappers.append((production, "run_vectorization_v2", original_pipeline))


def _json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def phase_summary(metrics: dict[str, Any], direct_stats: dict[str, Any], wall_ms: float) -> dict[str, Any]:
    timings = metrics.get("phaseTimingsMs", {})
    return {
        "wall_ms_monotonic": round(wall_ms, 3),
        "production_phase_timings_ms": timings,
        "production_total_ms": timings.get("totalProcessingMs"),
        "diagnostic_stage_timings": direct_stats,
        "relative_share_of_total": {
            key: round(value / max(1, timings.get("totalProcessingMs", 1)), 4)
            for key, value in timings.items() if key != "totalProcessingMs" and isinstance(value, (int, float))
        },
        "phase_d1_metrics_timing_ms": metrics.get("phaseD1", {}).get("timing_ms"),
        "phase_d1_wrapper_timing_ms": direct_stats.get("d1.wrapper_total", {}).get("total_ms"),
    }


def run_camera_api() -> tuple[dict[str, Any], Any, dict[str, Any]]:
    from fastapi.testclient import TestClient
    from mediastudio.api import create_app

    run_id = "camera_baseline"
    RECORDER.reset(run_id)
    source = CAMERA.read_bytes()
    with Image.open(CAMERA) as image:
        dimensions = list(image.size)
    workspace = ARTIFACTS / "camera_api_workspace"
    models_directory = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "MediaStudio/models/realesrgan"
    token = "task08b-0-6-camera-profile-token"
    app = create_app(token, workspace, models_directory)
    headers = {"X-Media-Studio-Token": token}
    request = {
        "asset_id": None, "engine": "auto", "mode": "auto", "color_count": None,
        "simplification": None, "smooth_paths": True, "transparent_background": True,
        "text_mode": "outlined", "vector_method": "smart_reconstruction",
    }
    start_ns = time.perf_counter_ns()
    start_utc = utc_now()
    with TestClient(app) as client:
        client.get("/api/v1/health", headers=headers).raise_for_status()
        upload = client.post("/api/v1/assets", headers=headers,
                             files={"file": (CAMERA.name, source, "image/png")})
        upload.raise_for_status()
        request["asset_id"] = upload.json()["assetId"]
        queued = client.post("/api/v1/vectorize/jobs", headers=headers, json=request)
        queued.raise_for_status()
        job_id = queued.json()["jobId"]
        deadline = time.monotonic() + 1200
        progress: list[dict[str, Any]] = []
        final = None
        while time.monotonic() < deadline:
            response = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
            response.raise_for_status()
            final = response.json()
            progress.append({"state": final.get("state"), "stage": final.get("stage"),
                             "progress": final.get("progress"), "atUtc": utc_now()})
            if final.get("state") in {"succeeded", "failed"}:
                break
            time.sleep(0.2)
        if final is None or final.get("state") not in {"succeeded", "failed"}:
            raise TimeoutError("Camera diagnostic API job timed out after 1200 seconds.")
        result_path = ARTIFACTS / "camera_profiled.svg"
        render_path = ARTIFACTS / "camera_profiled_render.png"
        result_status = None
        result_bytes = 0
        if final.get("state") == "succeeded":
            result = client.get(f"/api/v1/jobs/{job_id}/result", headers=headers)
            result_status = result.status_code
            result.raise_for_status()
            result_bytes = len(result.content)
            result_path.write_bytes(result.content)
            rendered = RECORDER.capture.get("baseline_render_array")
            if rendered is None:
                was_enabled = RECORDER.enabled
                RECORDER.enabled = False
                try:
                    rendered = production.rasterize_svg(result.text, expected_size=tuple(dimensions))
                finally:
                    RECORDER.enabled = was_enabled
            Image.fromarray(rendered, mode="RGBA").save(render_path)
    elapsed_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
    result_tuple = RECORDER.capture.get("production_result")
    metrics = result_tuple[0] if result_tuple else {}
    d1 = RECORDER.d1_report()
    camera = {
        "schemaVersion": 1,
        "task": "08B.0.6",
        "recordedAtUtc": utc_now(),
        "startedAtUtc": start_utc,
        "fixture": {"path": str(CAMERA.resolve()), "sha256": sha256_file(CAMERA),
                    "dimensions": dimensions, "bytes": len(source)},
        "runtimeConfiguration": {"apiPath": "POST asset -> POST vectorize job -> poll job -> download SVG",
                                 "request": request,
                                 "environmentVariables": {
                                     "MEDIASTUDIO_CONTOUR_EXPERIMENTAL": os.environ.get("MEDIASTUDIO_CONTOUR_EXPERIMENTAL"),
                                     "MEDIASTUDIO_VECTORIZE_PIPELINE": os.environ.get("MEDIASTUDIO_VECTORIZE_PIPELINE"),
                                     "DEBUG_VECTOR": os.environ.get("DEBUG_VECTOR"),
                                 }},
        "job": {"jobId": job_id, "state": final.get("state"), "stage": final.get("stage"),
                "error": final.get("error"), "resultPipeline": final.get("resultPipeline"),
                "resultVectorMethod": final.get("resultVectorMethod"),
                "elapsed_seconds_api_client_wall": round(elapsed_ms / 1000, 3),
                "elapsed_seconds_server_job": final.get("elapsedSeconds"),
                "progressHistory": progress, "resultDownloadStatus": result_status,
                "resultBytes": result_bytes},
        "phaseTiming": phase_summary(metrics, {
            key.removeprefix(run_id + "."): value for key, value in RECORDER.stage_stats.items()
            if key.startswith(run_id + ".")
        }, elapsed_ms),
        "productionMetrics": metrics,
        "d1Diagnostics": d1,
        "artifacts": {"svg": str(result_path.resolve()) if result_path.is_file() else None,
                      "render": str(render_path.resolve()) if render_path.is_file() else None},
    }
    _json_write(ARTIFACTS / "camera_phase_timing.json", camera)
    _json_write(ARTIFACTS / "d1_retry_trace.json", {
        "schemaVersion": 1, "task": "08B.0.6", "fixture": camera["fixture"],
        "d1Timing": d1, "historicalTask08B05Reference": {
            "api_elapsed_seconds": 391.533,
            "d1_timing_ms": 57892.244,
            "retry_self_intersection_counts": [6, 7, 9, 10],
            "local_repair_crossing_segments": 7,
            "local_repair_final_count": 0,
        },
    })
    return camera, RECORDER.capture.get("phase_c"), metrics


def run_counterfactual(phase_c: Any, camera_metrics: dict[str, Any],
                       phase_b: Any | None = None) -> dict[str, Any]:
    import unittest.mock

    if phase_c is None:
        return {"status": "not_run", "reason": "Camera Phase C object was not captured."}
    run_id = "camera_no_d1_boundary_retries"
    RECORDER.reset(run_id)
    phase_c_copy = copy.deepcopy(phase_c)
    start_ns = time.perf_counter_ns()
    with unittest.mock.patch.object(phase_d1, "_invalid_boundary_refs", lambda _model: set()):
        geometry = production.run_phase_d1(phase_c_copy, debug_directory=None)
    d1_wall_ms = (time.perf_counter_ns() - start_ns) / 1_000_000
    RECORDER.finish_unclosed_retry()
    # The wrapper has already validated the final geometry. Apply the same production gate.
    gate_error = None
    try:
        production._require_valid_d1_geometry(geometry.metrics)
    except production.VectorizationV2Error as error:
        gate_error = str(error)
    result: dict[str, Any] = {
        "status": "completed" if gate_error is None else "rejected_by_production_geometry_gate",
        "experiment": "same Phase C input; force D1 invalid-boundary lookup to return empty, preserving local repair and final validators",
        "production_configuration_changed": False,
        "d1_elapsed_ms": round(d1_wall_ms, 3),
        "geometry_gate_error": gate_error,
        "baseline": metric_snapshot(camera_metrics.get("phaseD1", {})),
        "counterfactual": metric_snapshot(geometry.metrics),
        "geometry_validation": geometry.metrics.get("final_geometry_validation"),
        "retry_trace": RECORDER.d1_report(),
        "local_repair": geometry.metrics.get("local_self_intersection_repair"),
        "deltas": {},
        "render_comparison": {"status": "not_run"},
    }
    baseline_metrics = result["baseline"]
    candidate_metrics = result["counterfactual"]
    for key in ("self_intersection_count", "silhouette_iou", "silhouette_area_error_ratio",
                "mean_boundary_error", "max_boundary_error", "shared_boundary_count",
                "shared_boundary_mismatch_count", "shared_interface_gap_pixels",
                "geometry_missing_source_pixels", "geometry_extra_pixels",
                "topology_relationship_mismatch_count", "total_bezier_anchor_count"):
        before, after = baseline_metrics.get(key), candidate_metrics.get(key)
        result["deltas"][key] = None if before is None or after is None else after - before

    if gate_error is None:
        appearance_started = time.perf_counter_ns()
        appearance = production.run_phase_e1(phase_c_copy, geometry, debug_directory=None)
        appearance_ms = (time.perf_counter_ns() - appearance_started) / 1_000_000
        if phase_b is None:
            phase_b = RECORDER.capture.get("phase_b")
        if phase_b is not None:
            text_layers, _text_warnings = production.reconstruct_text_layers(phase_b, mode="outlined")
            composition = production.compose_production_svg(
                geometry, appearance, text_layers, output_size=(geometry.width, geometry.height)
            )
            rendered = production.rasterize_svg(
                composition.svg_text, expected_size=(geometry.width, geometry.height)
            )
            output_svg = ARTIFACTS / "camera_no_retries.svg"
            output_png = ARTIFACTS / "camera_no_retries_render.png"
            output_svg.write_text(composition.svg_text, encoding="utf-8")
            Image.fromarray(rendered, mode="RGBA").save(output_png)
            baseline_png_path = ARTIFACTS / "camera_profiled_render.png"
            if baseline_png_path.is_file():
                baseline_rgba = np.asarray(Image.open(baseline_png_path).convert("RGBA"), dtype=np.int16)
                candidate_rgba = rendered.astype(np.int16)
                diff = np.abs(baseline_rgba - candidate_rgba)
                result["render_comparison"] = {
                    "status": "compared_with_same_e1_and_text_layers",
                    "appearance_policy": "recomputed E1 against counterfactual geometry; reused same Phase C source and outlined-text mode",
                    "counterfactual_e1_ms": round(appearance_ms, 3),
                    "mean_absolute_rgba_difference": float(diff.mean()),
                    "p95_absolute_rgba_difference": float(np.percentile(diff, 95)),
                    "changed_pixel_fraction_gt_1": float(np.mean(np.max(diff, axis=2) > 1)),
                    "baseline_render": str(baseline_png_path.resolve()),
                    "counterfactual_render": str(output_png.resolve()),
                    "counterfactual_svg": str(output_svg.resolve()),
                }
            else:
                result["render_comparison"] = {"status": "not_run", "reason": "Baseline render missing."}
        else:
            result["render_comparison"] = {"status": "not_run", "reason": "Phase B object not captured for text reconstruction."}
    _json_write(ARTIFACTS / "counterfactual_comparison.json", result)
    return result


def run_multifixture() -> dict[str, Any]:
    records = []
    models_directory = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "MediaStudio/models/realesrgan"
    for fixture_id, category, source in FIXTURES:
        RECORDER.reset(fixture_id)
        if not source.is_file():
            records.append({"fixture_id": fixture_id, "category": category, "status": "missing",
                            "path": str(source.resolve())})
            continue
        started = time.perf_counter_ns()
        with Image.open(source) as image:
            working_image = ImageOps.exif_transpose(image).convert("RGBA")
        width, height = working_image.size
        max_dimension = production._resolve_working_max_dimension("auto", None)
        if max(working_image.size) > max_dimension:
            scale = max_dimension / max(working_image.size)
            working_image = working_image.resize(
                (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
                Image.Resampling.LANCZOS,
            )
        t0 = time.perf_counter_ns()
        phase_a = production.run_phase_a(working_image, processing_scale=1, debug_directory=None)
        phase_a_ms = (time.perf_counter_ns() - t0) / 1_000_000
        t0 = time.perf_counter_ns()
        engine = production.get_process_ocr_engine(models_directory)
        phase_b = production.run_phase_b(phase_a, ocr_engine=engine, debug_directory=None)
        phase_b_ms = (time.perf_counter_ns() - t0) / 1_000_000
        t0 = time.perf_counter_ns()
        phase_c_value = production.run_phase_c(phase_b, debug_directory=None)
        phase_c_ms = (time.perf_counter_ns() - t0) / 1_000_000
        d1_started = time.perf_counter_ns()
        geometry = production.run_phase_d1(phase_c_value, debug_directory=None)
        d1_ms = (time.perf_counter_ns() - d1_started) / 1_000_000
        gate_error = None
        try:
            production._require_valid_d1_geometry(geometry.metrics)
        except production.VectorizationV2Error as error:
            gate_error = str(error)
        total_ms = (time.perf_counter_ns() - started) / 1_000_000
        records.append({
            "fixture_id": fixture_id, "category": category, "status": "completed" if gate_error is None else "geometry_gate_failed",
            "path": str(source.resolve()), "sha256": sha256_file(source), "bytes": source.stat().st_size,
            "dimensions": [width, height], "working_dimensions": list(working_image.size),
            "phase_timings_ms": {"phase_a": round(phase_a_ms, 3), "phase_b_ocr": round(phase_b_ms, 3),
                                 "phase_c_segmentation": round(phase_c_ms, 3), "phase_d1_geometry": round(d1_ms, 3),
                                 "phase_a_to_d1_total": round(total_ms, 3)},
            "phase_d1_profile": RECORDER.d1_report(),
            "geometry_gate_error": gate_error,
            "complexity": {"phase_c_region_count": phase_c_value.metrics.get("final_region_count"),
                           "phase_c_boundary_count": phase_c_value.metrics.get("final_boundary_count"),
                           "d1_boundary_count": geometry.metrics.get("shared_boundary_count"),
                           "d1_region_count": geometry.metrics.get("total_regions"),
                           "initial_self_intersection_count": (geometry.metrics.get("d1_repair_flow") or [{}])[0].get("self_intersection_count"),
                           "retry_count": sum(1 for row in geometry.metrics.get("d1_repair_flow", [])
                                               if row.get("stage") == "boundary_refit" and row.get("status") == "completed"),
                           "local_repair_status": geometry.metrics.get("local_self_intersection_repair", {}).get("status"),
                           "final_self_intersection_count": geometry.metrics.get("self_intersection_count"),
                           "shared_boundary_mismatch_count": geometry.metrics.get("shared_boundary_mismatch_count")},
            "phase_d1_metric_snapshot": metric_snapshot(geometry.metrics),
            "warm_ocr_engine_initialization_count": int(getattr(engine, "initialization_count", 0)),
        })
        _json_write(ARTIFACTS / "multi_fixture_performance.json", {
            "schemaVersion": 1, "task": "08B.0.6", "recordedAtUtc": utc_now(),
            "measurement_scope": "real current Phase A/B/C/D1 functions; no Phase E1/SVG stage for this D1-focused fixture matrix",
            "fixtures": records,
        })
    result = {
        "schemaVersion": 1, "task": "08B.0.6", "recordedAtUtc": utc_now(),
        "measurement_scope": "real current Phase A/B/C/D1 functions; no Phase E1/SVG stage for this D1-focused fixture matrix",
        "fixtures": records,
    }
    _json_write(ARTIFACTS / "multi_fixture_performance.json", result)
    return result


def rebuild_camera_phase_c() -> tuple[Any, Any]:
    """Rebuild only A/B/C when resuming after an already-profiled camera job."""
    models_directory = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "MediaStudio/models/realesrgan"
    with Image.open(CAMERA) as image:
        working_image = ImageOps.exif_transpose(image).convert("RGBA")
    phase_a = production.run_phase_a(working_image, processing_scale=1, debug_directory=None)
    engine = production.get_process_ocr_engine(models_directory)
    phase_b = production.run_phase_b(phase_a, ocr_engine=engine, debug_directory=None)
    phase_c = production.run_phase_c(phase_b, debug_directory=None)
    return phase_b, phase_c


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume-after-camera", action="store_true",
                        help="reuse the saved camera phase timings/retry trace and continue with counterfactual + fixture matrix")
    parser.add_argument("--counterfactual-geometry-only", action="store_true",
                        help="rerun only the no-boundary-retry D1 candidate and save full per-region fidelity metrics")
    args = parser.parse_args()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    start_hashes = source_hashes()
    os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
    os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
    os.environ["DEBUG_VECTOR"] = "1" if not args.resume_after_camera else "0"
    install_instrumentation()
    try:
        if args.counterfactual_geometry_only:
            os.environ["DEBUG_VECTOR"] = "0"
            phase_b, phase_c = rebuild_camera_phase_c()
            RECORDER.reset("camera_no_d1_boundary_retries_fidelity")
            with __import__("unittest.mock", fromlist=["patch"]).patch.object(
                    phase_d1, "_invalid_boundary_refs", lambda _model: set()):
                geometry = production.run_phase_d1(copy.deepcopy(phase_c), debug_directory=None)
            try:
                production._require_valid_d1_geometry(geometry.metrics)
                gate_status = "valid"
            except production.VectorizationV2Error as error:
                gate_status = f"invalid: {error}"
            _json_write(ARTIFACTS / "counterfactual_geometry_metrics.json", {
                "schemaVersion": 1, "task": "08B.0.6", "fixture": str(CAMERA.resolve()),
                "counterfactual": "D1 boundary refit retries skipped; original local crossing repair and final geometry validator retained",
                "geometry_gate": gate_status,
                "d1_profile": RECORDER.d1_report(),
                "full_d1_metrics": geometry.metrics,
            })
            print(json.dumps({"geometry_gate": gate_status,
                              "self_intersection_count": geometry.metrics.get("self_intersection_count"),
                              "region_count": geometry.metrics.get("total_regions"),
                              "profile": str((ARTIFACTS / "counterfactual_geometry_metrics.json").resolve())},
                             indent=2, ensure_ascii=False))
            return 0
        if args.resume_after_camera:
            camera_path = ARTIFACTS / "camera_phase_timing.json"
            if not camera_path.is_file():
                raise FileNotFoundError("Cannot resume: camera_phase_timing.json is missing.")
            camera = json.loads(camera_path.read_text(encoding="utf-8"))
            camera_metrics = camera.get("productionMetrics", {})
            _phase_b, phase_c = rebuild_camera_phase_c()
        else:
            camera, phase_c, camera_metrics = run_camera_api()
            _phase_b = RECORDER.capture.get("phase_b")
        counterfactual = run_counterfactual(phase_c, camera_metrics, _phase_b)
        multi = run_multifixture()
    finally:
        RECORDER.restore()
    end_hashes = source_hashes()
    changes = {
        "schemaVersion": 1, "task": "08B.0.6", "production_algorithm_changed": False,
        "smart_v2_production_unchanged": start_hashes == end_hashes,
        "contour_unchanged": {
            key: value for key, value in {
                "unchanged": all(start_hashes.get(k) == v for k, v in end_hashes.items()
                                  if k.startswith("contour/")) and
                             all(k in start_hashes for k in end_hashes if k.startswith("contour/")),
                "file_count_before": sum(k.startswith("contour/") for k in start_hashes),
                "file_count_after": sum(k.startswith("contour/") for k in end_hashes),
            }.items()
        },
        "scope": "diagnostic timers, profiler harness, counterfactual research branch, and profiler tests only",
        "production_files_changed": [],
        "source_hashes_before": start_hashes,
        "source_hashes_after": end_hashes,
        "candidate_metrics": {"camera_api_succeeded": camera.get("job", {}).get("state") == "succeeded",
                              "counterfactual_status": counterfactual.get("status"),
                              "multifixture_run_count": len(multi.get("fixtures", []))},
    }
    changes["smart_v2_production_unchanged"] = all(
        start_hashes.get(key) == end_hashes.get(key) for key in end_hashes if key.startswith("smart_v2/")
    ) and all(key in start_hashes for key in end_hashes if key.startswith("smart_v2/"))
    _json_write(ARTIFACTS / "production_changes.json", changes)
    print(json.dumps({"camera_job": camera.get("job"),
                      "camera_phase_timings": camera.get("phaseTiming", {}).get("production_phase_timings_ms"),
                      "counterfactual": {"status": counterfactual.get("status"),
                                         "final_valid": (counterfactual.get("geometry_validation") or {}).get("valid"),
                                         "local_repair_status": (counterfactual.get("local_repair") or {}).get("status")},
                      "fixtures": [{"id": row.get("fixture_id"), "status": row.get("status"),
                                    "d1_ms": row.get("phase_timings_ms", {}).get("phase_d1_geometry")}
                                   for row in multi.get("fixtures", [])],
                      "production_unchanged": changes["smart_v2_production_unchanged"],
                      "contour_unchanged": changes["contour_unchanged"]["unchanged"]},
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
