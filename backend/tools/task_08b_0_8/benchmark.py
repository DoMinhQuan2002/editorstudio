from __future__ import annotations

"""Frozen-input E1 and feature-path benchmark for Task 08B.0.8.

This script is diagnostic only. It persists the Phase B/C/D1 snapshot so the
baseline and candidate workers consume byte-identical serialized inputs.
"""

import argparse
import cProfile
import hashlib
import importlib
import io
import json
import os
import pickle
import pstats
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image

BACKEND = Path(__file__).resolve().parents[2]
ARTIFACTS = BACKEND / "artifacts/contour_preserving/task_08b_0_8"
FROZEN = ARTIFACTS / "frozen_inputs"
MASKS = ARTIFACTS / "feature_masks"
OUTPUTS = ARTIFACTS / "runs"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tools" / "task_08b_0_7"))

from mediastudio.image_tools.vectorization_v2 import phase_e1, production  # noqa: E402
from mediastudio.image_tools.vectorization_v2 import appearance_feature_geometry as fg  # noqa: E402
from profile_e1 import (  # noqa: E402
    ProcessRssSampler,
    _build_phases,
    _feature_summary,
    _final_svg_and_render,
    _fingerprint,
    _jsonable,
    sha256_bytes,
    sha256_file,
)

CAMERA = BACKEND / "artifacts/contour_preserving/task_08a_1/acquired/scikit_image/camera.png"
ACTIVE_FOX = BACKEND / "tests/fixtures/active_fox.jpg"
THIN = BACKEND / "artifacts/contour_preserving/task_07_2/synthetic_sources/thin_line.png"
GRADIENT = BACKEND / "artifacts/contour_preserving/task_07_2/synthetic_sources/linear_gradient.png"
FIXTURES = [
    ("camera", "camera", CAMERA),
    ("active_fox_native_jpeg", "native_jpeg", ACTIVE_FOX),
    ("synthetic_thin_feature", "thin_feature", THIN),
    ("synthetic_gradient", "gradient", GRADIENT),
]


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n",
                    encoding="utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _feature_records(result: Any, fixture_id: str, version: str) -> tuple[list[dict[str, Any]], list[np.ndarray]]:
    records: list[dict[str, Any]] = []
    arrays: list[np.ndarray] = []
    for region_id, layer in sorted(result.appearance_layers.items()):
        for index, feature in enumerate(layer.get("features", []), 1):
            mask = np.ascontiguousarray(np.asarray(feature["mask"], dtype=bool))
            arrays.append(mask)
            path_data = str(feature["svg_d"])
            commands: dict[str, int] = {}
            for command in "MLCQZ":
                commands[command] = len(re.findall(rf"(?<![A-Za-z]){command}(?=\s)", path_data))
            path_bytes = path_data.encode("utf-8")
            records.append({
                "feature_id": f"R{int(region_id):02d}_feature_{index:02d}",
                "region_id": int(region_id),
                "order_in_region": index,
                "feature_area_px": int(mask.sum()),
                "mask_shape": list(mask.shape),
                "mask_dtype": str(mask.dtype),
                "mask_sha256": sha256_bytes(mask.tobytes()),
                "path_sha256": sha256_bytes(path_bytes),
                "path_data": path_data,
                "path_commands": commands,
                "fit_metrics": _jsonable(feature.get("path_metrics", {})),
                "fill_model": _jsonable(feature.get("fill_model", {})),
                "source_median_rgb": feature.get("source_median_rgb"),
            })
    return records, arrays


def _summarize_svg(svg_text: str, render: np.ndarray) -> dict[str, Any]:
    alpha = np.ascontiguousarray(render[..., 3])
    return {
        "svg_sha256": sha256_bytes(svg_text.encode("utf-8")),
        "svg_bytes": len(svg_text.encode("utf-8")),
        "svg_chars": len(svg_text),
        "path_element_count": len(re.findall(r"<path(?:\s|>)", svg_text)),
        "linear_gradient_count": len(re.findall(r"<linearGradient(?:\s|>)", svg_text)),
        "radial_gradient_count": len(re.findall(r"<radialGradient(?:\s|>)", svg_text)),
        "clip_path_count": len(re.findall(r"<clipPath(?:\s|>)", svg_text)),
        "render_sha256": sha256_bytes(np.ascontiguousarray(render).tobytes()),
        "render_shape": list(render.shape),
        "alpha_sha256": sha256_bytes(alpha.tobytes()),
        "alpha_nonzero_pixels": int(np.count_nonzero(alpha)),
        "alpha_values": sorted(int(v) for v in np.unique(alpha)),
    }


def _run_e1(fixture_id: str, version: str, snapshot: Path) -> dict[str, Any]:
    os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
    os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
    with snapshot.open("rb") as stream:
        data = pickle.load(stream)
    phase_b, phase_c, geometry = data["phase_b"], data["phase_c"], data["geometry"]
    if geometry.phase_c is not phase_c:
        raise RuntimeError("Frozen snapshot lost Phase C identity required by D1/E1.")
    geometry_signature = phase_e1._geometry_digest(geometry)
    started = time.perf_counter_ns()
    result = phase_e1.run_phase_e1(phase_c, geometry, debug_directory=None)
    runtime_ms = (time.perf_counter_ns() - started) / 1_000_000
    fingerprint = _fingerprint(result)
    final_svg, final_render = _final_svg_and_render(phase_b, geometry, result)
    features, feature_masks = _feature_records(result, fixture_id, version)
    final_output = _summarize_svg(final_svg, final_render)
    record = {
        "fixture_id": fixture_id,
        "version": version,
        "debug_enabled": False,
        "profiled": False,
        "e1_runtime_ms": round(runtime_ms, 3),
        "source_sha256": sha256_file(Path(next(row[2] for row in FIXTURES if row[0] == fixture_id))),
        "frozen_snapshot_sha256": sha256_file(snapshot),
        "input_geometry_signature": geometry_signature,
        "geometry_signature_before": result.metrics.get("geometry_signature_before"),
        "geometry_signature_after": result.metrics.get("geometry_signature_after"),
        "geometry_unchanged": bool(result.metrics.get("geometry_unchanged")),
        "e1_fingerprint": fingerprint,
        "fixture_summary": _feature_summary(phase_c, result),
        "feature_paths": features,
        "appearance_layers_order": [
            {"region_id": int(region_id), "feature_ids": [
                f"R{int(region_id):02d}_feature_{i:02d}"
                for i, _ in enumerate(layer.get("features", []), 1)]}
            for region_id, layer in sorted(result.appearance_layers.items())
        ],
        "final_output": final_output,
        "e1_svg_sha256": sha256_bytes(result.svg_text.encode("utf-8")),
        "e1_svg_bytes": len(result.svg_text.encode("utf-8")),
        "e1_render_sha256": sha256_bytes(np.ascontiguousarray(result.svg_render_rgba).tobytes()),
        "e1_render_alpha_sha256": sha256_bytes(np.ascontiguousarray(result.svg_render_rgba[..., 3]).tobytes()),
    }
    run_dir = OUTPUTS / fixture_id / version
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "production.svg").write_text(final_svg, encoding="utf-8")
    Image.fromarray(final_render, "RGBA").save(run_dir / "production_render.png")
    if feature_masks:
        np.savez_compressed(MASKS / f"{fixture_id}_{version}.npz", *feature_masks)
    _write(run_dir / "run.json", record)
    return record


def _prepare_baseline() -> None:
    FROZEN.mkdir(parents=True, exist_ok=True)
    MASKS.mkdir(parents=True, exist_ok=True)
    for fixture_id, category, source in FIXTURES:
        if not source.is_file():
            raise FileNotFoundError(source)
        snapshot = FROZEN / f"{fixture_id}.pkl"
        expected_camera_signature = "006a94fd807aacbcbcbb63f510fdeebaad9e74892d7ea6ef875ec3b41c3cc15f"
        frozen_meta = FROZEN / f"{fixture_id}.json"
        if snapshot.is_file() and frozen_meta.is_file():
            with snapshot.open("rb") as stream:
                frozen = pickle.load(stream)
            phase_b, phase_c, geometry = frozen["phase_b"], frozen["phase_c"], frozen["geometry"]
            signature = phase_e1._geometry_digest(geometry)
            if geometry.phase_c is not phase_c:
                raise RuntimeError(f"Frozen snapshot lost Phase C identity: {fixture_id}")
            source_hash = sha256_file(source)
            metadata = json.loads(frozen_meta.read_text(encoding="utf-8"))
            if metadata.get("source_sha256") != source_hash:
                raise RuntimeError(f"Frozen source image changed for {fixture_id}")
            if metadata.get("geometry_signature") != signature:
                raise RuntimeError(f"Frozen geometry signature changed for {fixture_id}")
        else:
            print(f"Preparing frozen input: {fixture_id}", flush=True)
            phase_data = _build_phases(fixture_id, category, source)
            with snapshot.open("wb") as stream:
                pickle.dump({key: phase_data[key] for key in ("phase_b", "phase_c", "geometry")},
                            stream, protocol=5)
            phase_b, phase_c, geometry = phase_data["phase_b"], phase_data["phase_c"], phase_data["geometry"]
            signature = phase_e1._geometry_digest(geometry)
        if fixture_id == "camera" and signature != expected_camera_signature:
            raise RuntimeError(f"Camera frozen geometry differs from Task 08B.0.7: {signature}")
        if not frozen_meta.is_file():
            _write(frozen_meta, {
                "fixture_id": fixture_id,
                "category": category,
                "source_path": str(source.resolve()),
                "source_sha256": sha256_file(source),
                "source_size": list(phase_data["source_size"]),
                "working_size": list(phase_data["working_size"]),
                "preparation_phase_timings_ms": phase_data["phase_timings_ms"],
                "preparation_total_ms": phase_data["preparation_total_ms"],
                "snapshot_sha256": sha256_file(snapshot),
                "geometry_signature": signature,
                "geometry_identity_preserved_after_pickle": geometry.phase_c is phase_c,
            })
        baseline_run = OUTPUTS / fixture_id / "baseline" / "run.json"
        baseline_masks = MASKS / f"{fixture_id}_baseline.npz"
        if baseline_run.is_file() and baseline_masks.is_file():
            print(f"Baseline already recorded: {fixture_id}", flush=True)
            continue
        print(f"Baseline E1: {fixture_id}", flush=True)
        _run_e1(fixture_id, "baseline", snapshot)


def _run_optimized() -> None:
    for fixture_id, _, _ in FIXTURES:
        snapshot = FROZEN / f"{fixture_id}.pkl"
        if not snapshot.is_file():
            raise FileNotFoundError(f"Frozen baseline input missing: {snapshot}")
        run_manifest = OUTPUTS / fixture_id / "optimized" / "run.json"
        if run_manifest.is_file():
            print(f"Optimized E1 already recorded: {fixture_id}", flush=True)
            continue
        print(f"Optimized E1: {fixture_id}", flush=True)
        _run_e1(fixture_id, "optimized", snapshot)


def _install_timers() -> tuple[dict[str, dict[str, float | int]], list[tuple[Any, str, Any]]]:
    stats: dict[str, dict[str, float | int]] = defaultdict(lambda: {"calls": 0, "inclusive_ms": 0.0, "exclusive_ms": 0.0})
    patches: list[tuple[Any, str, Any]] = []
    stack: list[dict[str, Any]] = []

    def instrument(owner: Any, attr: str, label: str) -> None:
        original = getattr(owner, attr)

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            frame = {"label": label, "started": time.perf_counter_ns(), "children": 0}
            stack.append(frame)
            try:
                return original(*args, **kwargs)
            finally:
                elapsed = time.perf_counter_ns() - frame["started"]
                stack.pop()
                row = stats[label]
                row["calls"] = int(row["calls"]) + 1
                row["inclusive_ms"] = float(row["inclusive_ms"]) + elapsed / 1_000_000
                row["exclusive_ms"] = float(row["exclusive_ms"]) + max(0, elapsed - frame["children"]) / 1_000_000
                if stack:
                    stack[-1]["children"] += elapsed
        setattr(owner, attr, wrapped)
        patches.append((owner, attr, original))

    from mediastudio.image_tools.vectorization_v2 import phase_d1
    for attr in ("_pixel_cell_loops", "_signed_area", "_sample_fit", "_closed_ring_is_simple",
                 "_render_cell_space", "_count_holes", "_mask_boundary_metrics", "_legacy_topology_fallback"):
        instrument(fg, attr, f"feature_geometry.{attr}")
    instrument(phase_d1, "_fit_regularized_polyline", "phase_d1._fit_regularized_polyline")
    instrument(fg.cv2, "findContours", "OpenCV.findContours")
    instrument(fg.cv2, "approxPolyDP", "OpenCV.approxPolyDP")
    instrument(fg.cv2, "fillPoly", "OpenCV.fillPoly")
    return stats, patches


def _profile_feature_masks(fixture_id: str, version: str) -> dict[str, Any]:
    snapshot = FROZEN / f"{fixture_id}.pkl"
    with snapshot.open("rb") as stream:
        phase_b, phase_c, geometry = pickle.load(stream).values()
    del phase_b
    run_path = OUTPUTS / fixture_id / version / "run.json"
    run_data = json.loads(run_path.read_text(encoding="utf-8"))
    masks_path = MASKS / f"{fixture_id}_{version}.npz"
    if not masks_path.is_file():
        return {"fixture_id": fixture_id, "version": version, "feature_count": 0,
                "status": "no E1-selected feature masks", "operations": {}}
    with np.load(masks_path) as data:
        masks = [np.asarray(data[key], dtype=bool) for key in sorted(data.files, key=lambda x: int(x.split("_")[-1]))]
    stats, patches = _install_timers()
    outputs = []
    try:
        started = time.perf_counter_ns()
        for mask in masks:
            svg_d, metrics = fg.fit_mask_contours_to_svg_d(
                mask, threshold=1, tolerance=0.35, minimum_area=0.0, fallback_epsilon=0.9)
            outputs.append({"path_sha256": _sha(svg_d.encode("utf-8")), "metrics": _jsonable(metrics)})
        total_ms = (time.perf_counter_ns() - started) / 1_000_000
    finally:
        for owner, attr, original in reversed(patches):
            setattr(owner, attr, original)
    calls = int(stats.get("feature_geometry._closed_ring_is_simple", {}).get("calls", 0))
    return {
        "fixture_id": fixture_id,
        "version": version,
        "feature_count": len(masks),
        "unprofiled_wall_time_ms_for_one_mask_set": round(total_ms, 3),
        "outputs_match_e1_paths": [row["path_sha256"] for row in outputs] == [row["path_sha256"] for row in run_data["feature_paths"]],
        "output_path_hashes": [row["path_sha256"] for row in outputs],
        "output_metrics": [row["metrics"] for row in outputs],
        "closed_ring_simple_validation_calls": calls,
        "operations": {key: {k: round(float(v), 3) if k != "calls" else int(v) for k, v in value.items()}
                       for key, value in stats.items()},
        "geometry_signature": run_data["input_geometry_signature"],
        "memory_note": "This instrumented pass includes benchmark timers; use performance_comparison.json for paired unprofiled timing.",
    }


def _direct_timing(fixture_id: str, version: str, repeats: int) -> dict[str, Any]:
    masks_path = MASKS / f"{fixture_id}_{version}.npz"
    if not masks_path.is_file():
        return {"fixture_id": fixture_id, "version": version, "feature_count": 0,
                "repeats": repeats, "per_repeat_ms": [], "median_ms": 0.0,
                "status": "no E1-selected feature masks"}
    with np.load(masks_path) as data:
        masks = [np.asarray(data[key], dtype=bool) for key in sorted(data.files, key=lambda x: int(x.split("_")[-1]))]
    # Warm the imports/native libraries on a small shape, outside measured repeats.
    warmup = np.zeros((24, 24), dtype=bool)
    warmup[5:19, 6:18] = True
    fg.fit_mask_contours_to_svg_d(warmup, threshold=1, tolerance=0.35,
                                 minimum_area=0.0, fallback_epsilon=0.9)
    per_repeat = []
    expected_hashes = None
    for repeat in range(repeats):
        rows = []
        started = time.perf_counter_ns()
        for mask in masks:
            svg_d, metrics = fg.fit_mask_contours_to_svg_d(
                mask, threshold=1, tolerance=0.35, minimum_area=0.0, fallback_epsilon=0.9)
            rows.append({"path_sha256": _sha(svg_d.encode("utf-8")), "metrics_sha256": _sha(
                json.dumps(_jsonable(metrics), sort_keys=True, separators=(",", ":")).encode("utf-8"))})
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        per_repeat.append(round(elapsed_ms, 3))
        if expected_hashes is None:
            expected_hashes = rows
        elif rows != expected_hashes:
            raise RuntimeError(f"Non-deterministic fitter output for {fixture_id} {version} repeat {repeat}")
    return {
        "fixture_id": fixture_id,
        "version": version,
        "feature_count": len(masks),
        "repeats": repeats,
        "per_repeat_ms": per_repeat,
        "median_ms": round(float(np.median(per_repeat)), 3),
        "min_ms": min(per_repeat),
        "max_ms": max(per_repeat),
        "repeat_output_identical": True,
        "outputs_match_e1_paths": expected_hashes is not None and
            [row["path_sha256"] for row in expected_hashes] == [row["path_sha256"] for row in json.loads(
                (OUTPUTS / fixture_id / version / "run.json").read_text(encoding="utf-8"))["feature_paths"]],
    }


def _memory_fitter(fixture_id: str, version: str) -> dict[str, Any]:
    masks_path = MASKS / f"{fixture_id}_{version}.npz"
    if not masks_path.is_file():
        return {"fixture_id": fixture_id, "version": version, "feature_count": 0,
                "status": "no E1-selected feature masks", "memory": {"available": False}}
    with np.load(masks_path) as data:
        masks = [np.asarray(data[key], dtype=bool) for key in sorted(data.files, key=lambda x: int(x.split("_")[-1]))]
    warmup = np.zeros((24, 24), dtype=bool)
    warmup[5:19, 6:18] = True
    fg.fit_mask_contours_to_svg_d(warmup, threshold=1, tolerance=0.35,
                                 minimum_area=0.0, fallback_epsilon=0.9)
    outputs = []
    started = time.perf_counter_ns()
    with ProcessRssSampler(interval_seconds=0.02) as sampler:
        for mask in masks:
            svg_d, metrics = fg.fit_mask_contours_to_svg_d(
                mask, threshold=1, tolerance=0.35, minimum_area=0.0, fallback_epsilon=0.9)
            outputs.append({"path_sha256": _sha(svg_d.encode("utf-8")), "metrics": _jsonable(metrics)})
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    run_data = json.loads((OUTPUTS / fixture_id / version / "run.json").read_text(encoding="utf-8"))
    return {
        "fixture_id": fixture_id,
        "version": version,
        "feature_count": len(masks),
        "wall_time_ms": round(elapsed_ms, 3),
        "outputs_match_e1_paths": [row["path_sha256"] for row in outputs] ==
            [row["path_sha256"] for row in run_data["feature_paths"]],
        "output_metrics_match_e1": [row["metrics"] for row in outputs] ==
            [row["fit_metrics"] for row in run_data["feature_paths"]],
        "memory": sampler.result,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare-baseline", "run-optimized", "profile", "time-fitter", "memory-fitter"))
    parser.add_argument("--fixture", default="camera")
    parser.add_argument("--version", choices=("baseline", "optimized"), default="baseline")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.mode == "prepare-baseline":
        _prepare_baseline()
    elif args.mode == "run-optimized":
        _run_optimized()
    elif args.mode == "profile":
        print(json.dumps(_profile_feature_masks(args.fixture, args.version), ensure_ascii=False, indent=2))
    elif args.mode == "memory-fitter":
        print(json.dumps(_memory_fitter(args.fixture, args.version), ensure_ascii=False, indent=2))
    else:
        value = _direct_timing(args.fixture, args.version, args.repeats)
        _write(ARTIFACTS / "runs" / args.fixture / args.version / "direct_fitter_timing.json", value)
        print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
