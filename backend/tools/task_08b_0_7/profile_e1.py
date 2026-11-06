from __future__ import annotations

"""Isolated, output-preserving profiling for Smart V2 Phase E1.

This harness wraps selected Python/native call sites at runtime. It does not edit
production modules and restores every patched callable before returning.
"""

import argparse
import contextvars
import dataclasses
import hashlib
import inspect
import json
import os
import pickle
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, ImageOps

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
ARTIFACTS = BACKEND / "artifacts/contour_preserving/task_08b_0_7"
CAMERA = BACKEND / "artifacts/contour_preserving/task_08a_1/acquired/scikit_image/camera.png"
FIXTURES = [
    ("active_fox_native_jpeg", "native_logo", BACKEND / "tests/fixtures/active_fox.jpg"),
    ("synthetic_flat_geometry", "flat_color", BACKEND / "artifacts/contour_preserving/task_07_2/synthetic_sources/rounded_rectangle.png"),
    ("synthetic_linear_gradient", "gradient", BACKEND / "artifacts/contour_preserving/task_07_2/synthetic_sources/linear_gradient.png"),
]
sys.path.insert(0, str(BACKEND))

from mediastudio.image_tools.vectorization_v2 import (  # noqa: E402
    phase_e, phase_e1, production,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_hashes() -> dict[str, str]:
    groups = {
        "smart_v2": [*sorted((BACKEND / "mediastudio/image_tools/vectorization_v2").glob("*.py")),
                     BACKEND / "mediastudio/image_tools/vectorize.py"],
        "contour": sorted((BACKEND / "mediastudio/image_tools/vectorization_contour").glob("*.py")),
    }
    return {
        f"{group}/{path.relative_to(BACKEND).as_posix()}": sha256_file(path)
        for group, paths in groups.items() for path in paths if path.is_file()
    }


_MEMORY_API: tuple[Any, Any, Any] | None = None


class ProcessRssSampler:
    """Sample current process working set on Windows; stage peak is sampled, not OS high-water."""

    def __init__(self, interval_seconds: float = 0.05) -> None:
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._samples: list[int] = []
        self.error: str | None = None

    @staticmethod
    def _rss_bytes() -> int:
        global _MEMORY_API
        if os.name != "nt":
            raise OSError("This task's process RSS sampler is implemented for Windows.")
        import ctypes
        from ctypes import wintypes

        if _MEMORY_API is None:
            class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            psapi.GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX), wintypes.DWORD,
            ]
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            _MEMORY_API = (kernel32, psapi, kernel32.GetCurrentProcess(), PROCESS_MEMORY_COUNTERS_EX)
        _kernel32, psapi, handle, counters_type = _MEMORY_API
        counters = counters_type()
        counters.cb = ctypes.sizeof(counters)
        ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        if not ok:
            raise OSError("GetProcessMemoryInfo failed")
        return int(counters.WorkingSetSize)

    def _sample(self) -> None:
        try:
            while not self._stop.is_set():
                self._samples.append(self._rss_bytes())
                self._stop.wait(self.interval_seconds)
        except Exception as exc:  # reported as unavailable rather than a fabricated value
            self.error = f"{type(exc).__name__}: {exc}"

    def __enter__(self) -> ProcessRssSampler:
        try:
            self._samples.append(self._rss_bytes())
            self._thread = threading.Thread(target=self._sample, name="e1-rss-sampler", daemon=True)
            self._thread.start()
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
        return self

    def __exit__(self, *_: Any) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        try:
            self._samples.append(self._rss_bytes())
        except Exception as exc:
            self.error = self.error or f"{type(exc).__name__}: {exc}"

    @property
    def result(self) -> dict[str, Any]:
        if not self._samples:
            return {"available": False, "error": self.error, "sampling_interval_ms": self.interval_seconds * 1000}
        return {
            "available": True,
            "method": "GetProcessMemoryInfo WorkingSetSize sampled by a background thread",
            "sampling_interval_ms": self.interval_seconds * 1000,
            "sample_count": len(self._samples),
            "start_rss_mb": round(self._samples[0] / (1024 * 1024), 2),
            "peak_sampled_rss_mb": round(max(self._samples) / (1024 * 1024), 2),
            "end_rss_mb": round(self._samples[-1] / (1024 * 1024), 2),
            "peak_delta_from_start_mb": round((max(self._samples) - self._samples[0]) / (1024 * 1024), 2),
            "limitation": f"Transient allocations shorter than the {self.interval_seconds * 1000:g} ms sampling interval may be missed.",
            "error": self.error,
        }


class E1Profiler:
    """Monotonic inclusive/exclusive timers with region and candidate-scope attribution."""

    def __init__(self) -> None:
        self._region = contextvars.ContextVar("e1_profile_region", default=None)
        self._scope = contextvars.ContextVar("e1_profile_scope", default=None)
        self._stack: list[dict[str, Any]] = []
        self._rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._patches: list[tuple[Any, str, Any]] = []
        self.region_data: dict[str, dict[str, Any]] = defaultdict(dict)
        self._installed = False

    def _begin(self, label: str, region_id: Any = None, scope: str | None = None) -> tuple[Any, Any, dict[str, Any]]:
        region_token = self._region.set(str(region_id) if region_id is not None else self._region.get())
        scope_token = self._scope.set(scope if scope is not None else self._scope.get())
        frame = {"label": label, "started": time.perf_counter_ns(), "children_ns": 0,
                 "region_id": self._region.get(), "scope": self._scope.get()}
        self._stack.append(frame)
        return region_token, scope_token, frame

    def _end(self, frame: dict[str, Any], region_token: Any, scope_token: Any) -> None:
        elapsed = time.perf_counter_ns() - frame["started"]
        self._stack.pop()
        exclusive = max(0, elapsed - frame["children_ns"])
        self._rows[frame["label"]].append({
            "inclusive_ns": elapsed, "exclusive_ns": exclusive,
            "region_id": frame["region_id"], "scope": frame["scope"],
        })
        if self._stack:
            self._stack[-1]["children_ns"] += elapsed
        if frame["region_id"] is not None:
            data = self.region_data[str(frame["region_id"])]
            data["instrumented_exclusive_ms"] = data.get("instrumented_exclusive_ms", 0.0) + exclusive / 1_000_000
        self._region.reset(region_token)
        self._scope.reset(scope_token)

    def instrument_function(self, owner: Any, attr: str, label: str, *,
                            region_arg: int | None = None, scope: str | None = None,
                            after: Callable[[Any, tuple[Any, ...], dict[str, Any]], None] | None = None) -> None:
        original = getattr(owner, attr)

        def measured(*args: Any, **kwargs: Any) -> Any:
            region_id = None
            if region_arg is not None and len(args) > region_arg:
                region_id = getattr(args[region_arg], "id", None)
            rtoken, stoken, frame = self._begin(label, region_id=region_id, scope=scope)
            value = None
            try:
                value = original(*args, **kwargs)
                if after is not None:
                    after(value, args, kwargs)
                return value
            finally:
                self._end(frame, rtoken, stoken)

        measured.__name__ = getattr(original, "__name__", attr)
        measured.__doc__ = getattr(original, "__doc__", None)
        setattr(owner, attr, measured)
        self._patches.append((owner, attr, original))

    def _capture_sample(self, result: Any, args: tuple[Any, ...], _: dict[str, Any]) -> None:
        region = args[1]
        key = str(int(region.id))
        data = self.region_data[key]
        data["region_id"] = int(region.id)
        data["area_px"] = int(np.asarray(region.mask, dtype=bool).sum())
        data["bbox_xyxy"] = [int(v) for v in region.bbox]
        data["source_sample_count_before_cap"] = int(result.source_sample_count)
        data["sample_count_after_cap"] = int(len(result.rgb))

    def _capture_baseline_fit(self, result: Any, args: tuple[Any, ...], _: dict[str, Any]) -> None:
        region = args[0]
        data = self.region_data[str(int(region.id))]
        data["baseline_appearance_type"] = result.appearance_type
        data["baseline_flat_error"] = float(result.flat_error)
        data["baseline_linear_candidate_present"] = result.linear_candidate is not None
        data["baseline_radial_candidate_present"] = result.radial_candidate is not None

    def _capture_e1_fit(self, result: Any, args: tuple[Any, ...], _: dict[str, Any]) -> None:
        region = args[0]
        model, search = result
        data = self.region_data[str(int(region.id))]
        data["e1_appearance_type"] = model.appearance_type
        data["e1_linear_direction_candidates"] = len(search)
        data["e1_selected_gradient_stops"] = len(model.gradient_stops)

    def _capture_adaptive_fit(self, result: Any, args: tuple[Any, ...], _: dict[str, Any]) -> None:
        positions = result[0]
        key = self._region.get()
        if key is not None:
            data = self.region_data[str(key)]
            data["e1_adaptive_stop_insertions"] = data.get("e1_adaptive_stop_insertions", 0) + max(0, len(positions) - 2)

    def _capture_linear_search(self, result: Any, args: tuple[Any, ...], _: dict[str, Any]) -> None:
        key = self._region.get()
        if key is not None:
            data = self.region_data[str(key)]
            data["e1_linear_candidate_searches"] = data.get("e1_linear_candidate_searches", 0) + len(result[2])

    def _capture_layer_result(self, result: Any, *_: Any) -> None:
        selected, diagnostics = result
        self.layer_diagnostics = diagnostics
        for key, row in diagnostics.items():
            region_id = key.removeprefix("R")
            data = self.region_data[region_id]
            data["layer_feature_selected"] = bool(row.get("selected"))
            data["layer_cluster_count_candidates"] = len(row.get("candidate_search", []))
            data["layer_selected_feature_count"] = len(selected.get(int(region_id), {}).get("features", []))

    def _wrap_layers(self, owner: Any, attr: str) -> None:
        original = getattr(owner, attr)
        profiler = self

        class GraphProxy:
            def __init__(self, graph: Any) -> None:
                self._graph = graph

            @property
            def regions(self):
                return TimedRegions(self._graph.regions, profiler)

            def __getattr__(self, name: str) -> Any:
                return getattr(self._graph, name)

        class PhaseCProxy:
            def __init__(self, phase_c: Any) -> None:
                self._phase_c = phase_c
                self.graph = GraphProxy(phase_c.graph)

            def __getattr__(self, name: str) -> Any:
                return getattr(self._phase_c, name)

        class TimedRegions:
            def __init__(self, regions: Any, owner_profiler: E1Profiler) -> None:
                self._regions = regions
                self._profiler = owner_profiler

            def __iter__(self):
                for region in self._regions:
                    key = str(int(region.id))
                    token = self._profiler._region.set(key)
                    started = time.perf_counter_ns()
                    try:
                        yield region
                    finally:
                        elapsed = time.perf_counter_ns() - started
                        data = self._profiler.region_data[key]
                        data["appearance_layer_loop_ms"] = data.get("appearance_layer_loop_ms", 0.0) + elapsed / 1_000_000
                        self._profiler._region.reset(token)

        def measured(phase_c: Any, models: Any) -> Any:
            rtoken, stoken, frame = profiler._begin("E1._fit_appearance_layers")
            value = None
            try:
                value = original(PhaseCProxy(phase_c), models)
                return value
            finally:
                profiler._end(frame, rtoken, stoken)
                if value is not None:
                    profiler._capture_layer_result(value)

        measured.__name__ = getattr(original, "__name__", attr)
        measured.__doc__ = getattr(original, "__doc__", None)
        setattr(owner, attr, measured)
        self._patches.append((owner, attr, original))

    def install(self) -> None:
        if self._installed:
            raise RuntimeError("E1 profiler is already installed")
        self.layer_diagnostics: dict[str, Any] = {}
        self.instrument_function(phase_e1, "run_phase_e1", "E1.run_phase_e1")
        self.instrument_function(phase_e1, "run_phase_e", "E.run_phase_e")
        self.instrument_function(phase_e, "_sample_region", "E._sample_region", region_arg=1,
                                 after=self._capture_sample)
        self.instrument_function(phase_e, "_fit_appearance", "E._fit_appearance", region_arg=0,
                                 after=self._capture_baseline_fit)
        self.instrument_function(phase_e, "_linear_candidates", "E._linear_candidates", scope="E.linear")
        self.instrument_function(phase_e, "_radial_candidates", "E._radial_candidates", scope="E.radial")
        self.instrument_function(phase_e, "_fit_profile", "E._fit_profile")
        self.instrument_function(phase_e, "_weighted_quantile", "E._weighted_quantile")
        self.instrument_function(phase_e, "_weighted_median", "E._weighted_median")
        self.instrument_function(phase_e, "_delta_e", "E._delta_e")
        self.instrument_function(phase_e, "_predict_model_rgb", "E._predict_model_rgb")
        self.instrument_function(phase_e, "_render_geometry_rgba", "E._render_geometry_rgba")
        self.instrument_function(phase_e, "_build_metrics", "E._build_metrics")

        self.instrument_function(phase_e1, "_fit_appearance_e1", "E1._fit_appearance_e1", region_arg=0,
                                 after=self._capture_e1_fit)
        self.instrument_function(phase_e1, "_linear_candidate_e1", "E1._linear_candidate_e1",
                                 scope="E1.linear", after=self._capture_linear_search)
        self.instrument_function(phase_e1, "_fit_adaptive_stops", "E1._fit_adaptive_stops",
                                 after=self._capture_adaptive_fit)
        self.instrument_function(phase_e1, "_fit_colors", "E1._fit_colors")
        self.instrument_function(phase_e1, "_profile_bins", "E1._profile_bins")
        self._wrap_layers(phase_e1, "_fit_appearance_layers")
        self.instrument_function(phase_e1, "_local_feature_fill", "E1._local_feature_fill")
        self.instrument_function(phase_e1, "_contour_complexity_count", "E1._contour_complexity_count")
        self.instrument_function(phase_e1, "_contours_to_svg_d", "E1._contours_to_svg_d")
        self.instrument_function(phase_e1, "render_model_prediction", "E1.render_model_prediction")
        self.instrument_function(phase_e1, "_appearance_svg_e1", "E1._appearance_svg_e1")
        self.instrument_function(phase_e1, "rasterize_svg", "E1.rasterize_svg")
        self.instrument_function(phase_e1, "_svg_coordinate_audit", "E1._svg_coordinate_audit")
        self.instrument_function(phase_e1, "_appearance_metrics", "E1._appearance_metrics")
        self.instrument_function(phase_e1, "_stop_source_samples", "E1._stop_source_samples")

        # E1 imported these functions as module globals; time their E1 aliases too.
        self.instrument_function(phase_e1, "_delta_e", "E1._delta_e")
        self.instrument_function(phase_e1, "_weighted_median", "E1._weighted_median")
        self.instrument_function(phase_e1, "_predict_model_rgb", "E1._predict_model_rgb")
        self.instrument_function(phase_e1, "_render_geometry_rgba", "E1._render_geometry_rgba")

        # Measure expensive native operations whose work is otherwise inside Python callers.
        for attr in ("bilateralFilter", "distanceTransform", "remap", "kmeans",
                     "connectedComponentsWithStats", "findContours", "morphologyEx", "cvtColor"):
            if hasattr(phase_e1.cv2, attr):
                self.instrument_function(phase_e1.cv2, attr, f"OpenCV.{attr}")
        self.instrument_function(np.linalg, "lstsq", "NumPy.linalg.lstsq")
        self._installed = True

    def restore(self) -> None:
        for owner, attr, original in reversed(self._patches):
            setattr(owner, attr, original)
        self._patches.clear()
        self._installed = False

    @staticmethod
    def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        inclusive = np.asarray([row["inclusive_ns"] for row in rows], dtype=np.float64) / 1_000_000
        exclusive = np.asarray([row["exclusive_ns"] for row in rows], dtype=np.float64) / 1_000_000
        return {
            "calls": len(rows),
            "inclusive_total_ms": round(float(inclusive.sum()), 3),
            "exclusive_total_ms": round(float(exclusive.sum()), 3),
            "inclusive_mean_ms": round(float(inclusive.mean()), 6) if len(inclusive) else 0,
            "inclusive_p95_ms": round(float(np.percentile(inclusive, 95)), 6) if len(inclusive) else 0,
            "inclusive_max_ms": round(float(inclusive.max()), 6) if len(inclusive) else 0,
            "exclusive_mean_ms": round(float(exclusive.mean()), 6) if len(exclusive) else 0,
        }

    def report(self, total_runtime_ms: float) -> dict[str, Any]:
        operation_rows = []
        for name, rows in self._rows.items():
            summary = self._summary(rows)
            summary["operation"] = name
            summary["exclusive_share_of_total_percent"] = round(
                summary["exclusive_total_ms"] / max(total_runtime_ms, 1e-9) * 100, 4)
            by_scope: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                by_scope[str(row.get("scope") or "unspecified")].append(row)
            summary["scopes"] = {scope: self._summary(bucket) for scope, bucket in by_scope.items()}
            operation_rows.append(summary)
        operation_rows.sort(key=lambda row: row["exclusive_total_ms"], reverse=True)

        regions = []
        for key, data in self.region_data.items():
            row = {"region_id": int(key), **data}
            sample_ms = self._sum_for_region("E._sample_region", key, "inclusive_ns") / 1_000_000
            baseline_fit_ms = self._sum_for_region("E._fit_appearance", key, "inclusive_ns") / 1_000_000
            e1_fit_ms = self._sum_for_region("E1._fit_appearance_e1", key, "inclusive_ns") / 1_000_000
            layer_ms = float(data.get("appearance_layer_loop_ms", 0.0))
            row.update({
                "sample_region_ms": round(sample_ms, 3),
                "baseline_fit_ms": round(baseline_fit_ms, 3),
                "e1_region_fit_ms": round(e1_fit_ms, 3),
                "appearance_layer_loop_ms": round(layer_ms, 3),
                "region_measured_total_ms": round(sample_ms + baseline_fit_ms + e1_fit_ms + layer_ms, 3),
                "region_measured_ms_per_1000_pixels": round(
                    (sample_ms + baseline_fit_ms + e1_fit_ms + layer_ms) * 1000 / max(1, int(data.get("area_px", 0))), 6),
                "baseline_linear_profile_fit_calls": self._count("E._fit_profile", key, "E.linear"),
                "baseline_radial_profile_fit_calls": self._count("E._fit_profile", key, "E.radial"),
                "adaptive_color_fit_calls": self._count("E1._fit_colors", key),
                "kmeans_calls": self._count("OpenCV.kmeans", key),
            })
            regions.append(row)
        regions.sort(key=lambda row: row.get("region_measured_total_ms", 0), reverse=True)
        return {
            "method": "runtime wrappers around real E/ E1 call sites; all elapsed values use perf_counter_ns",
            "total_runtime_ms": round(total_runtime_ms, 3),
            "inclusive_exclusive_definition": "Inclusive includes nested wrapped calls. Exclusive subtracts child wrapped-call intervals; unwrapped work remains in its nearest wrapped caller.",
            "operations": operation_rows,
            "regions": regions,
            "region_scoped_exclusive_ms": round(sum(
                row["exclusive_ns"] for rows in self._rows.values() for row in rows
                if row["region_id"] is not None) / 1_000_000, 3),
        }

    def _sum_for_region(self, label: str, region_key: str, field: str) -> int:
        return sum(row[field] for row in self._rows.get(label, []) if row["region_id"] == region_key)

    def _count(self, label: str, region_key: str, scope: str | None = None) -> int:
        return sum(1 for row in self._rows.get(label, [])
                   if row["region_id"] == region_key and (scope is None or row["scope"] == scope))


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, np.ndarray):
        array = np.ascontiguousarray(value)
        return {"array_sha256": sha256_bytes(array.tobytes()), "shape": list(array.shape), "dtype": str(array.dtype)}
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _fingerprint(result: Any) -> dict[str, Any]:
    arrays = {
        "model_prediction_rgba": result.model_prediction_rgba,
        "geometry_owner": result.geometry_owner,
        "svg_render_rgba": result.svg_render_rgba,
    }
    array_hashes = {
        key: {"sha256": sha256_bytes(np.ascontiguousarray(value).tobytes()),
              "shape": list(value.shape), "dtype": str(value.dtype)}
        for key, value in arrays.items()
    }
    selected = {
        "appearance_models": _jsonable(result.appearance_models),
        "appearance_layers": _jsonable(result.appearance_layers),
        "metrics": _jsonable(result.metrics),
        "baseline_models": _jsonable(result.baseline.appearance_models),
        "baseline_metrics": _jsonable(result.baseline.metrics),
        "arrays": array_hashes,
        "svg_sha256": sha256_bytes(result.svg_text.encode("utf-8")),
    }
    canonical = json.dumps(selected, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return {"sha256": sha256_bytes(canonical), "components": selected}


def _final_svg_and_render(phase_b: Any, geometry: Any, appearance: Any) -> tuple[str, np.ndarray]:
    text_layers, _warnings = production.reconstruct_text_layers(phase_b, mode="outlined")
    composition = production.compose_production_svg(
        geometry, appearance, text_layers, output_size=(geometry.width, geometry.height))
    render = phase_e1.rasterize_svg(composition.svg_text,
                                    expected_size=(geometry.width, geometry.height))
    return composition.svg_text, render


def _feature_summary(phase_c: Any, e1_result: Any) -> dict[str, Any]:
    labels = np.asarray(phase_c.region_labels)
    candidate_counts: dict[str, int] = defaultdict(int)
    for rows in e1_result.direction_search.values():
        candidate_counts[str(len(rows))] += 1
    return {
        "region_count": len(phase_c.graph.regions),
        "region_area_sum_px": int(sum(np.asarray(row.mask, dtype=bool).sum() for row in phase_c.graph.regions)),
        "labeled_pixel_coverage": int(np.count_nonzero(labels > 0)),
        "total_source_sample_count": int(sum(row.source_sample_count for row in e1_result.baseline.debug_samples.values())),
        "total_capped_sample_points": int(sum(len(row.rgb) for row in e1_result.baseline.debug_samples.values())),
        "appearance_models": len(e1_result.appearance_models),
        "selected_gradient_models": sum(model.gradient_type is not None for model in e1_result.appearance_models.values()),
        "appearance_layered_regions": len(e1_result.appearance_layers),
        "appearance_feature_paths": sum(len(layer.get("features", [])) for layer in e1_result.appearance_layers.values()),
        "candidate_search_calls": int(sum(len(rows) for rows in e1_result.direction_search.values())),
        "direction_candidate_distribution": dict(candidate_counts),
    }


def _build_phases(fixture_id: str, category: str, source: Path) -> dict[str, Any]:
    started = time.perf_counter_ns()
    with Image.open(source) as image:
        working = ImageOps.exif_transpose(image).convert("RGBA")
    original_size = list(working.size)
    max_dimension = production._resolve_working_max_dimension("auto", None)
    if max(working.size) > max_dimension:
        ratio = max_dimension / max(working.size)
        working = working.resize((max(1, int(round(working.width * ratio))),
                                  max(1, int(round(working.height * ratio)))), Image.Resampling.LANCZOS)
    working_size = list(working.size)
    phases: dict[str, float] = {}
    stage = time.perf_counter_ns()
    phase_a = production.run_phase_a(working, processing_scale=1, debug_directory=None)
    phases["phase_a_ms"] = (time.perf_counter_ns() - stage) / 1_000_000
    models_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "MediaStudio/models/realesrgan"
    engine = production.get_process_ocr_engine(models_dir)
    stage = time.perf_counter_ns()
    phase_b = production.run_phase_b(phase_a, ocr_engine=engine, debug_directory=None)
    phases["phase_b_ocr_ms"] = (time.perf_counter_ns() - stage) / 1_000_000
    stage = time.perf_counter_ns()
    phase_c_value = production.run_phase_c(phase_b, debug_directory=None)
    phases["phase_c_ms"] = (time.perf_counter_ns() - stage) / 1_000_000
    stage = time.perf_counter_ns()
    geometry = production.run_phase_d1(phase_c_value, debug_directory=None)
    phases["phase_d1_ms"] = (time.perf_counter_ns() - stage) / 1_000_000
    production._require_valid_d1_geometry(geometry.metrics)
    return {
        "fixture_id": fixture_id, "category": category, "source": str(source.resolve()),
        "source_sha256": sha256_file(source), "source_size": original_size,
        "working_size": working_size, "phase_timings_ms": {key: round(value, 3) for key, value in phases.items()},
        "preparation_total_ms": round((time.perf_counter_ns() - started) / 1_000_000, 3),
        "phase_b": phase_b, "phase_c": phase_c_value, "geometry": geometry,
    }


def _json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _worker(pickle_path: Path, output_path: Path, fixture_id: str, *, profiled: bool,
            debug_output: bool = False) -> int:
    with pickle_path.open("rb") as stream:
        phase_b, phase_c_value, geometry = pickle.load(stream)
    if geometry.phase_c is not phase_c_value:
        raise RuntimeError("Pickle round-trip broke Phase C identity required by E1/D1 contract.")
    profiler = E1Profiler() if profiled else None
    if profiler:
        profiler.install()
    debug_timing: dict[str, Any] | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="_camera_e1_debug_run_" if fixture_id == "camera" else "_e1_debug_run_",
                                         dir=ARTIFACTS if debug_output else None) as temp_name:
            debug_directory = Path(temp_name) / "phase_e1" if debug_output else None
            original_writer = original_save = None
            writer_stats = {"writer_ms": 0.0, "image_save_ms": 0.0, "image_save_calls": 0}
            debug_operation_stats: dict[str, dict[str, float | int]] = {}
            debug_operation_patches: list[tuple[Any, str, Any]] = []
            if debug_output:
                from mediastudio.image_tools.vectorization_v2 import phase_e1_debug
                original_writer = phase_e1_debug.write_phase_e1_artifacts
                original_save = Image.Image.save

                def measured_writer(*args: Any, **kwargs: Any) -> Any:
                    started_writer = time.perf_counter_ns()
                    try:
                        return original_writer(*args, **kwargs)
                    finally:
                        writer_stats["writer_ms"] += (time.perf_counter_ns() - started_writer) / 1_000_000

                def measured_save(image: Image.Image, *args: Any, **kwargs: Any) -> Any:
                    started_save = time.perf_counter_ns()
                    try:
                        return original_save(image, *args, **kwargs)
                    finally:
                        writer_stats["image_save_ms"] += (time.perf_counter_ns() - started_save) / 1_000_000
                        writer_stats["image_save_calls"] += 1

                phase_e1_debug.write_phase_e1_artifacts = measured_writer
                Image.Image.save = measured_save
                for owner, attr, label in (
                    (phase_e1_debug, "_write_triptych", "_write_triptych"),
                    (phase_e1_debug, "_render_single_candidate", "_render_single_candidate"),
                    (phase_e1_debug, "_residual_feature_diagnostics", "_residual_feature_diagnostics"),
                    (phase_e1_debug, "_delta_heat", "_delta_heat"),
                    (phase_e1_debug, "render_model_prediction", "render_model_prediction"),
                    (phase_e1, "_render_geometry_rgba", "phase_e1._render_geometry_rgba"),
                ):
                    original_operation = getattr(owner, attr)
                    row = debug_operation_stats.setdefault(label, {"calls": 0, "inclusive_ms": 0.0, "max_ms": 0.0})

                    def measured_operation(*args: Any, _original: Any = original_operation,
                                           _row: dict[str, float | int] = row,
                                           **kwargs: Any) -> Any:
                        started_operation = time.perf_counter_ns()
                        try:
                            return _original(*args, **kwargs)
                        finally:
                            elapsed_operation = (time.perf_counter_ns() - started_operation) / 1_000_000
                            _row["calls"] = int(_row["calls"]) + 1
                            _row["inclusive_ms"] = float(_row["inclusive_ms"]) + elapsed_operation
                            _row["max_ms"] = max(float(_row["max_ms"]), elapsed_operation)

                    setattr(owner, attr, measured_operation)
                    debug_operation_patches.append((owner, attr, original_operation))
            try:
                with ProcessRssSampler(0.05) as memory:
                    started = time.perf_counter_ns()
                    result = phase_e1.run_phase_e1(phase_c_value, geometry,
                                                   debug_directory=debug_directory)
                    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
                memory_result = memory.result
            finally:
                if debug_output:
                    phase_e1_debug.write_phase_e1_artifacts = original_writer
                    Image.Image.save = original_save
                    for owner, attr, original_operation in reversed(debug_operation_patches):
                        setattr(owner, attr, original_operation)
            if debug_output:
                files = [path for path in Path(temp_name).rglob("*") if path.is_file()]
                debug_timing = {
                    "e1_debug_directory_enabled": True,
                    "e1_debug_writer_ms": round(writer_stats["writer_ms"], 3),
                    "all_image_save_calls": int(writer_stats["image_save_calls"]),
                    "all_image_save_total_ms_inclusive": round(writer_stats["image_save_ms"], 3),
                    "operation_timings_inclusive_ms": {
                        key: {item: round(float(value), 3) if item != "calls" else int(value)
                              for item, value in stats.items()}
                        for key, stats in debug_operation_stats.items()
                    },
                    "generated_file_count": len(files),
                    "generated_bytes": sum(path.stat().st_size for path in files),
                    "temporary_debug_outputs_removed": True,
                }
    finally:
        if profiler:
            profiler.restore()

    e1_fingerprint = _fingerprint(result)
    svg_text, final_render = _final_svg_and_render(phase_b, geometry, result)
    final_signature = {
        "svg_sha256": sha256_bytes(svg_text.encode("utf-8")),
        "render_sha256": sha256_bytes(np.ascontiguousarray(final_render).tobytes()),
        "render_shape": list(final_render.shape),
        "visible_pixels": int(np.count_nonzero(final_render[..., 3] > 0)),
        "svg_chars": len(svg_text),
    }
    payload: dict[str, Any] = {
        "schemaVersion": 1, "task": "08B.0.7", "fixture_id": fixture_id,
        "profiled": profiled, "debug_directory_enabled": debug_output,
        "e1_runtime_ms": round(elapsed_ms, 3), "memory": memory_result,
        "input_geometry_signature": result.metrics.get("geometry_signature_before"),
        "geometry_unchanged": result.metrics.get("geometry_unchanged"),
        "e1_fingerprint": e1_fingerprint,
        "final_output": final_signature,
        "fixture_summary": _feature_summary(phase_c_value, result),
    }
    if profiler:
        payload["profile"] = profiler.report(elapsed_ms)
        payload["layer_diagnostics"] = profiler.layer_diagnostics
    if debug_timing is not None:
        payload["debug_output_timing"] = debug_timing

    if fixture_id == "camera" and profiled:
        svg_path = ARTIFACTS / "camera_e1_profiled_final.svg"
        render_path = ARTIFACTS / "camera_e1_profiled_final_render.png"
        svg_path.write_text(svg_text, encoding="utf-8")
        Image.fromarray(final_render, "RGBA").save(render_path)
        payload["final_output"]["svg_path"] = str(svg_path.resolve())
        payload["final_output"]["render_path"] = str(render_path.resolve())
        if os.environ.get("MEDIASTUDIO_08B07_SKIP_DEBUG_PROBE") != "1":
            payload["debug_artifact_probe"] = _measure_debug_artifact_writers(result, geometry)
    _json_write(output_path, payload)
    print(json.dumps({"fixture": fixture_id, "profiled": profiled,
                      "e1_runtime_ms": round(elapsed_ms, 3),
                      "output_sha256": e1_fingerprint["sha256"]}, ensure_ascii=False))
    return 0


def _measure_debug_artifact_writers(result: Any, geometry: Any) -> dict[str, Any]:
    """Time optional Phase E/E1 debug writers on the already-computed result."""
    from mediastudio.image_tools.vectorization_v2.phase_e_debug import _appearance_svg, write_phase_e_artifacts
    from mediastudio.image_tools.vectorization_v2.phase_e1_debug import write_phase_e1_artifacts

    setup_started = time.perf_counter_ns()
    old_model, _old_owner = phase_e1.render_model_prediction(geometry, result.baseline.appearance_models)
    old_svg = phase_e1.rasterize_svg(_appearance_svg(result.baseline),
                                    expected_size=(geometry.width, geometry.height))
    setup_ms = (time.perf_counter_ns() - setup_started) / 1_000_000
    timings: dict[str, float] = {}
    with tempfile.TemporaryDirectory(prefix="mediastudio_08b07_debug_probe_") as temp_dir:
        temp_root = Path(temp_dir)
        started = time.perf_counter_ns()
        write_phase_e_artifacts(result.baseline, temp_root / "phase_e")
        timings["phase_e_debug_writer_ms"] = (time.perf_counter_ns() - started) / 1_000_000
        started = time.perf_counter_ns()
        mask_dir = temp_root / "phase_e1" / "feature_masks"
        mask_dir.mkdir(parents=True, exist_ok=True)
        mask_count = 0
        for region_id, layer in sorted(result.appearance_layers.items()):
            for feature_index, feature in enumerate(layer.get("features", []), 1):
                mask = np.asarray(feature.get("mask"), dtype=bool)
                Image.fromarray(mask.astype(np.uint8) * 255, "L").save(
                    mask_dir / f"R{region_id:02d}_feature_{feature_index:02d}.png")
                mask_count += 1
        timings["e1_feature_mask_writes_ms"] = (time.perf_counter_ns() - started) / 1_000_000
        started = time.perf_counter_ns()
        write_phase_e1_artifacts(result, temp_root / "phase_e1",
                                 old_svg_render=old_svg, old_model_prediction=old_model)
        timings["phase_e1_debug_writer_ms"] = (time.perf_counter_ns() - started) / 1_000_000
        files = [path for path in temp_root.rglob("*") if path.is_file()]
        byte_count = sum(path.stat().st_size for path in files)
    return {
        "enabled_in_task_08b_0_6_camera_run": True,
        "preparation_ms_excluded_from_writer_total": round(setup_ms, 3),
        "writer_timings_ms": {key: round(value, 3) for key, value in timings.items()},
        "total_writer_ms": round(sum(timings.values()), 3),
        "phase_e1_feature_mask_count": mask_count,
        "generated_file_count": len(files), "generated_bytes": byte_count,
        "generated_megabytes": round(byte_count / (1024 * 1024), 3),
        "temporary_outputs_removed_after_measurement": True,
    }


def _source_function(owner: Any, name: str, label: str, role: str, calls: list[str]) -> dict[str, Any]:
    fn = getattr(owner, name)
    try:
        source_file = Path(inspect.getsourcefile(fn) or "").resolve().relative_to(BACKEND).as_posix()
        line = inspect.getsourcelines(fn)[1]
    except Exception:
        source_file, line = "unknown", None
    return {"id": label, "role": role, "source": source_file, "line": line,
            "calls_or_uses": calls}


def _write_call_graph() -> None:
    nodes = [
        _source_function(production, "run_vectorization_v2", "production.entry", "production entry point",
                         ["phase_e1.run_phase_e1"]),
        _source_function(phase_e1, "run_phase_e1", "e1.entry", "E1 orchestrator",
                         ["E.run_phase_e when baseline_result is absent", "_fit_appearance_e1 per region",
                          "_fit_appearance_layers", "render_model_prediction", "_appearance_svg_e1",
                          "rasterize_svg", "_svg_coordinate_audit", "_appearance_metrics twice",
                          "_stop_source_samples", "phase_e1_debug.write_phase_e1_artifacts if debugging"]),
        _source_function(phase_e, "run_phase_e", "e.baseline", "baseline appearance model fitting",
                         ["_sample_region per graph region", "_fit_appearance per region",
                          "_render_geometry_rgba", "_build_metrics", "phase_e_debug writer if debugging"]),
        _source_function(phase_e, "_sample_region", "e.sample", "region mask and color sample creation",
                         ["np.where", "cv2.distanceTransform", "CoordinateMapping", "cv2.remap"]),
        _source_function(phase_e, "_fit_appearance", "e.fit", "flat/linear/radial selection",
                         ["_weighted_median", "_delta_e", "_linear_candidates", "_radial_candidates"]),
        _source_function(phase_e, "_linear_candidates", "e.linear", "baseline linear gradient candidates",
                         ["coarse angle search and local refinement", "_fit_profile for stop counts"]),
        _source_function(phase_e, "_radial_candidates", "e.radial", "baseline radial gradient candidates",
                         ["5x5 centers plus weighted center", "_fit_profile for stop counts"]),
        _source_function(phase_e, "_fit_profile", "e.profile_fit", "candidate profile fitting/scoring",
                         ["_weighted_quantile", "_weighted_median", "_predict_profile", "_delta_e"]),
        _source_function(phase_e1, "_fit_appearance_e1", "e1.fit", "E1 linear refinement and model selection",
                         ["_linear_candidate_e1", "flat/radial score comparison"]),
        _source_function(phase_e1, "_linear_candidate_e1", "e1.linear", "E1 adaptive linear-gradient search",
                         ["_fit_adaptive_stops", "_fit_colors", "_delta_e"]),
        _source_function(phase_e1, "_fit_adaptive_stops", "e1.adaptive", "adaptive stop candidate scoring",
                         ["_profile_bins", "repeated candidate _fit_colors", "_delta_e"]),
        _source_function(phase_e1, "_fit_appearance_layers", "e1.layers", "secondary feature mask and cluster candidates",
                         ["bilateralFilter", "distanceTransform", "kmeans k=2..5", "connected components",
                          "local feature fill/error", "candidate score"]),
        _source_function(phase_e1, "_appearance_metrics", "e1.metrics", "appearance/error map metrics",
                         ["_delta_e", "_ssim_on_mask", "per-region/edge/interior statistics"]),
    ]
    graph = {
        "schemaVersion": 1, "task": "08B.0.7", "generatedAtUtc": utc_now(),
        "entry": "production.run_vectorization_v2 -> phase_e1.run_phase_e1",
        "baseline_result_argument": "production call does not pass baseline_result; run_phase_e1 therefore executes run_phase_e first",
        "flow": [
            "Phase C reference RGBA + region labels/RegionGraph and frozen D1 geometry",
            "run_phase_e1 geometry identity/digest guard",
            "baseline Phase E: for each region sample mask/core/alpha-weighted source pixels, fit flat/linear/radial candidates, render and build metrics",
            "E1 per-region: fit adaptive linear-gradient direction/stops and compare against baseline flat/radial models",
            "E1 secondary features: filter image, construct region supports, cluster colors, extract connected components, score coherent feature candidates",
            "Render selected appearance models over frozen geometry; build SVG definitions/paths; rasterize in browser; coordinate audit",
            "Compute new and baseline appearance metrics, source samples for stops, readiness diagnostics",
            "Optional debug mode: write Phase E and E1 per-region maps, candidate renders, SVGs, masks and metrics"
        ],
        "nodes": nodes,
        "important_scope_note": "E1 wall time includes its internally-created Phase E baseline when production does not supply baseline_result.",
    }
    _json_write(ARTIFACTS / "e1_call_graph.json", graph)


def _prepare_and_run_fixture(fixture_id: str, category: str, source: Path,
                             temp_dir: Path, *, camera_pair: bool) -> dict[str, Any]:
    if not source.is_file():
        return {"fixture_id": fixture_id, "category": category, "status": "missing", "path": str(source)}
    phase_data = _build_phases(fixture_id, category, source)
    pickle_path = temp_dir / f"{fixture_id}.pkl"
    with pickle_path.open("wb") as stream:
        pickle.dump((phase_data["phase_b"], phase_data["phase_c"], phase_data["geometry"]), stream, protocol=5)
    output_plain = ARTIFACTS / f"_{fixture_id}_unprofiled.json"
    output_profiled = ARTIFACTS / f"_{fixture_id}_profiled.json"
    command_base = [sys.executable, str(Path(__file__).resolve()), "--worker",
                    "--input-pickle", str(pickle_path), "--fixture-id", fixture_id]
    worker_rows: dict[str, Any] = {}
    if camera_pair:
        for mode, output in (("off", output_plain), ("on", output_profiled)):
            command = [*command_base, "--profile", mode, "--output", str(output)]
            completed = subprocess.run(command, cwd=BACKEND, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=1800)
            if completed.returncode != 0:
                raise RuntimeError(f"E1 worker {mode} failed ({completed.returncode}):\n{completed.stdout}\n{completed.stderr[-5000:]}")
            worker_rows[mode] = json.loads(output.read_text(encoding="utf-8"))
            output.unlink(missing_ok=True)
            print(completed.stdout.strip(), flush=True)
    else:
        command = [*command_base, "--profile", "on", "--output", str(output_profiled)]
        completed = subprocess.run(command, cwd=BACKEND, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=1800)
        if completed.returncode != 0:
            raise RuntimeError(f"E1 worker failed ({completed.returncode}):\n{completed.stdout}\n{completed.stderr[-5000:]}")
        worker_rows["on"] = json.loads(output_profiled.read_text(encoding="utf-8"))
        output_profiled.unlink(missing_ok=True)
        print(completed.stdout.strip(), flush=True)
    return {
        "fixture_id": fixture_id, "category": category, "status": "completed",
        "path": str(source.resolve()), "sha256": sha256_file(source),
        "source_dimensions": phase_data["source_size"], "working_dimensions": phase_data["working_size"],
        "phase_a_to_d1_timings_ms": phase_data["phase_timings_ms"],
        "preparation_total_ms": phase_data["preparation_total_ms"],
        "e1_runs": worker_rows,
    }


def _run_parent() -> int:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    before = _source_hashes()
    os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
    os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
    _write_call_graph()
    matrix: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mediastudio_08b07_intermediates_") as directory:
        temp_dir = Path(directory)
        fixtures = [("camera", "high-region camera", CAMERA, True),
                    *((fixture_id, category, path, False) for fixture_id, category, path in FIXTURES)]
        for fixture_id, category, source, camera_pair in fixtures:
            print(f"Preparing {fixture_id} ({source})", flush=True)
            row = _prepare_and_run_fixture(fixture_id, category, source, temp_dir,
                                           camera_pair=camera_pair)
            matrix.append(row)
            _json_write(ARTIFACTS / "multi_fixture_e1_comparison.json", {
                "schemaVersion": 1, "task": "08B.0.7", "recordedAtUtc": utc_now(),
                "scope": "E1 only after identical Phase A-D1 preparation; camera paired unprofiled/profiled, other fixture rows profiled",
                "fixtures": matrix,
            })
            if fixture_id == "camera" and row.get("status") == "completed":
                _finalize_camera_artifacts(row)
        after = _source_hashes()
    changes = {
        "schemaVersion": 1, "task": "08B.0.7", "recordedAtUtc": utc_now(),
        "production_algorithm_changed": False, "smart_v2_production_unchanged": before == after,
        "contour_unchanged": {
            "unchanged": all(before.get(key) == value for key, value in after.items() if key.startswith("contour/"))
                         and all(key in before for key in after if key.startswith("contour/")),
            "file_count_before": sum(key.startswith("contour/") for key in before),
            "file_count_after": sum(key.startswith("contour/") for key in after),
        },
        "production_files_changed": [],
        "scope": "diagnostic harness/tests/artifacts only; no Smart V2, Contour, API, SVG Composer or WPF code edits",
        "source_hashes_before": before, "source_hashes_after": after,
    }
    _json_write(ARTIFACTS / "production_changes.json", changes)
    return 0


def _finalize_camera_artifacts(camera_row: dict[str, Any]) -> None:
    off = camera_row["e1_runs"].get("off")
    on = camera_row["e1_runs"].get("on")
    if not off or not on:
        return
    off_fp, on_fp = off["e1_fingerprint"], on["e1_fingerprint"]
    off_final, on_final = off["final_output"], on["final_output"]
    equality = {
        "e1_complete_fingerprint_equal": off_fp["sha256"] == on_fp["sha256"],
        "appearance_models_equal": off_fp["components"]["appearance_models"] == on_fp["components"]["appearance_models"],
        "appearance_layers_and_masks_equal": off_fp["components"]["appearance_layers"] == on_fp["components"]["appearance_layers"],
        "all_metrics_equal": off_fp["components"]["metrics"] == on_fp["components"]["metrics"],
        "model_render_hashes_equal": off_fp["components"]["arrays"] == on_fp["components"]["arrays"],
        "e1_svg_hash_equal": off_fp["components"]["svg_sha256"] == on_fp["components"]["svg_sha256"],
        "final_production_svg_hash_equal": off_final["svg_sha256"] == on_final["svg_sha256"],
        "final_production_render_hash_equal": off_final["render_sha256"] == on_final["render_sha256"],
        "frozen_geometry_signature_equal": off["input_geometry_signature"] == on["input_geometry_signature"],
    }
    _json_write(ARTIFACTS / "e1_output_integrity.json", {
        "schemaVersion": 1, "task": "08B.0.7", "profile_off_sha256": off_fp["sha256"],
        "profile_on_sha256": on_fp["sha256"], "profile_off_final_output": off_final,
        "profile_on_final_output": on_final, "checks": equality,
        "all_checks_pass": all(equality.values()),
        "comparison_method": "Independent worker processes loaded the exact same pickled Phase B/C/D1 inputs. Exact SHA-256 over complete model/layer/mask/metrics/array/SVG structures, plus final composed production SVG and Chromium render.",
    })

    profile_report = on["profile"]
    _json_write(ARTIFACTS / "camera_e1_profile.json", {
        "schemaVersion": 1, "task": "08B.0.7", "recordedAtUtc": utc_now(),
        "fixture": {key: camera_row[key] for key in ("fixture_id", "category", "path", "sha256", "source_dimensions", "working_dimensions")},
        "phase_a_to_d1_preparation_ms": camera_row["phase_a_to_d1_timings_ms"],
        "geometry_signature": on["input_geometry_signature"],
        "profiled_e1_runtime_ms": on["e1_runtime_ms"],
        "unprofiled_e1_runtime_ms": off["e1_runtime_ms"],
        "profile_method": profile_report["method"],
        "inclusive_exclusive_definition": profile_report["inclusive_exclusive_definition"],
        "profiled_memory": on["memory"], "unprofiled_memory": off["memory"],
        "fixture_summary": on["fixture_summary"],
        "region_count": len(profile_report["regions"]),
        "operation_count": len(profile_report["operations"]),
        "operations": profile_report["operations"],
        "top_region_costs": profile_report["regions"][:10],
        "all_regions": profile_report["regions"],
        "layer_diagnostics": on.get("layer_diagnostics", {}),
        "debug_artifact_probe": on.get("debug_artifact_probe"),
    })
    _json_write(ARTIFACTS / "e1_operation_timing.json", {
        "schemaVersion": 1, "task": "08B.0.7", "unit": "milliseconds",
        "denominator_ms": profile_report["total_runtime_ms"],
        "denominator_definition": "Exclusive sum uses nested perf_counter_ns wrappers; inclusive columns are shown for attribution but must not be summed.",
        "operations": profile_report["operations"],
    })
    _json_write(ARTIFACTS / "e1_region_cost_ranking.json", {
        "schemaVersion": 1, "task": "08B.0.7", "ranking": "descending measured region wall time across sequential sample, baseline fit, E1 per-region fit, and feature-layer loop",
        "region_count": len(profile_report["regions"]), "top_10": profile_report["regions"][:10],
        "all_regions": profile_report["regions"],
    })
    _json_write(ARTIFACTS / "profiling_overhead.json", {
        "schemaVersion": 1, "task": "08B.0.7", "comparison": "same camera fixture and exact serialized Phase B/C/D1 input; debug output disabled for both",
        "unprofiled_runtime_ms": off["e1_runtime_ms"], "profiled_runtime_ms": on["e1_runtime_ms"],
        "overhead_ms": round(on["e1_runtime_ms"] - off["e1_runtime_ms"], 3),
        "overhead_percent": round((on["e1_runtime_ms"] / max(1, off["e1_runtime_ms"]) - 1) * 100, 3),
        "unprofiled_memory": off["memory"], "profiled_memory": on["memory"],
        "debug_artifact_cost_measured_separately": on.get("debug_artifact_probe"),
        "interpretation": "Paired runs are one observation each; include runtime variance. The profiler wrappers and 50 ms RSS sampler are active only during the profiled E1 call.",
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--input-pickle", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fixture-id", default="camera")
    parser.add_argument("--profile", choices=("on", "off"), default="on")
    parser.add_argument("--debug-output", action="store_true",
                        help="run E1 with its real debug directory enabled and remove temporary artifacts after measuring")
    args = parser.parse_args()
    if args.worker:
        if not args.input_pickle or not args.output:
            parser.error("--worker requires --input-pickle and --output")
        return _worker(args.input_pickle, args.output, args.fixture_id,
                       profiled=args.profile == "on", debug_output=args.debug_output)
    return _run_parent()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
