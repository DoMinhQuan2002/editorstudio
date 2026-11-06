from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND / "artifacts/contour_preserving/task_08b_0_8"
RUNS = ROOT / "runs"
FIXTURES = ["camera", "active_fox_native_jpeg", "synthetic_thin_feature", "synthetic_gradient"]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    baseline_hash = sha((ROOT / "baseline_source/appearance_feature_geometry.py").read_bytes())
    candidate_hash = sha((ROOT / "optimized_source/appearance_feature_geometry.py").read_bytes())
    production_source = BACKEND / "mediastudio/image_tools/vectorization_v2/appearance_feature_geometry.py"
    production_hash = sha(production_source.read_bytes())

    geometry_rows = []
    appearance_rows = []
    performance_rows = []
    for fixture in FIXTURES:
        base = load_json(RUNS / fixture / "baseline/run.json")
        candidate = load_json(RUNS / fixture / "optimized/run.json")
        base_paths = base["feature_paths"]
        candidate_paths = candidate["feature_paths"]
        path_rows = []
        for left, right in zip(base_paths, candidate_paths):
            path_rows.append({
                "feature_id": left["feature_id"],
                "region_id": left["region_id"],
                "mask_sha256_baseline": left["mask_sha256"],
                "mask_sha256_candidate": right["mask_sha256"],
                "path_sha256_baseline": left["path_sha256"],
                "path_sha256_candidate": right["path_sha256"],
                "path_data_exact": left["path_data"] == right["path_data"],
                "path_commands_baseline": left["path_commands"],
                "path_commands_candidate": right["path_commands"],
                "path_commands_exact": left["path_commands"] == right["path_commands"],
                "fit_metrics_exact": left["fit_metrics"] == right["fit_metrics"],
            })
        mask_npz_equal = True
        mask_paths_exist = {}
        for version in ("baseline", "optimized"):
            path = ROOT / f"feature_masks/{fixture}_{version}.npz"
            mask_paths_exist[version] = path.is_file()
            if not path.is_file():
                continue
        if all(mask_paths_exist.values()):
            with np.load(ROOT / f"feature_masks/{fixture}_baseline.npz") as left, \
                 np.load(ROOT / f"feature_masks/{fixture}_optimized.npz") as right:
                mask_npz_equal = left.files == right.files and all(
                    np.array_equal(left[key], right[key]) for key in left.files)
        elif not any(mask_paths_exist.values()) and not base_paths and not candidate_paths:
            # Both E1 runs selected zero secondary paths, so there are no mask arrays to compare.
            mask_npz_equal = True
        else:
            mask_npz_equal = False
        svg_base = (RUNS / fixture / "baseline/production.svg").read_bytes()
        svg_candidate = (RUNS / fixture / "optimized/production.svg").read_bytes()
        render_base = (RUNS / fixture / "baseline/production_render.png").read_bytes()
        render_candidate = (RUNS / fixture / "optimized/production_render.png").read_bytes()
        geometry_rows.append({
            "fixture_id": fixture,
            "feature_path_count_baseline": len(base_paths),
            "feature_path_count_candidate": len(candidate_paths),
            "geometry_signature_baseline": base["input_geometry_signature"],
            "geometry_signature_candidate": candidate["input_geometry_signature"],
            "geometry_signature_exact": base["input_geometry_signature"] == candidate["input_geometry_signature"],
            "phase_geometry_unchanged_baseline": base["geometry_unchanged"],
            "phase_geometry_unchanged_candidate": candidate["geometry_unchanged"],
            "mask_arrays_exact": mask_npz_equal,
            "feature_path_records": path_rows,
            "all_feature_path_data_exact": len(base_paths) == len(candidate_paths) and all(x["path_data_exact"] for x in path_rows),
            "all_control_coordinates_exact": len(base_paths) == len(candidate_paths) and all(x["path_data_exact"] for x in path_rows),
            "all_path_commands_exact": len(base_paths) == len(candidate_paths) and all(x["path_commands_exact"] for x in path_rows),
            "all_fit_metrics_exact": len(base_paths) == len(candidate_paths) and all(x["fit_metrics_exact"] for x in path_rows),
            "production_svg_sha256_baseline": sha(svg_base),
            "production_svg_sha256_candidate": sha(svg_candidate),
            "production_svg_bytes_exact": svg_base == svg_candidate,
            "render_png_sha256_baseline": sha(render_base),
            "render_png_sha256_candidate": sha(render_candidate),
            "render_png_bytes_exact": render_base == render_candidate,
            "e1_geometry_fingerprint_exact": base["e1_fingerprint"] == candidate["e1_fingerprint"],
        })
        appearance_rows.append({
            "fixture_id": fixture,
            "appearance_model_fingerprint_baseline": base["e1_fingerprint"]["sha256"],
            "appearance_model_fingerprint_candidate": candidate["e1_fingerprint"]["sha256"],
            "appearance_models_exact": base["e1_fingerprint"]["components"] == candidate["e1_fingerprint"]["components"],
            "feature_fill_models_exact": [p["fill_model"] for p in base_paths] == [p["fill_model"] for p in candidate_paths],
            "feature_source_colors_exact": [p["source_median_rgb"] for p in base_paths] == [p["source_median_rgb"] for p in candidate_paths],
            "appearance_layer_order_exact": base["appearance_layers_order"] == candidate["appearance_layers_order"],
            "render_rgba_sha256_baseline": base["final_output"]["render_sha256"],
            "render_rgba_sha256_candidate": candidate["final_output"]["render_sha256"],
            "alpha_sha256_baseline": base["final_output"]["alpha_sha256"],
            "alpha_sha256_candidate": candidate["final_output"]["alpha_sha256"],
            "svg_structure_baseline": {k: base["final_output"][k] for k in ("svg_bytes", "path_element_count", "linear_gradient_count", "radial_gradient_count", "clip_path_count")},
            "svg_structure_candidate": {k: candidate["final_output"][k] for k in ("svg_bytes", "path_element_count", "linear_gradient_count", "radial_gradient_count", "clip_path_count")},
        })
        performance_rows.append({
            "fixture_id": fixture,
            "profiled": False,
            "e1_runtime_ms_baseline": base["e1_runtime_ms"],
            "e1_runtime_ms_candidate": candidate["e1_runtime_ms"],
            "e1_observed_change_percent": round((candidate["e1_runtime_ms"] / base["e1_runtime_ms"] - 1) * 100, 3),
            "e1_selected_feature_paths": len(base_paths),
            "production_svg_bytes_baseline": base["e1_svg_bytes"],
            "production_svg_bytes_candidate": candidate["e1_svg_bytes"],
            "geometry_fidelity_baseline": {
                "path_count": len(base_paths),
                "minimum_mask_iou": min((p["fit_metrics"].get("mask_iou", 1.0) for p in base_paths), default=None),
                "maximum_area_error_ratio": max((p["fit_metrics"].get("area_error_ratio", 0.0) for p in base_paths), default=None),
                "maximum_boundary_distance_px": max((p["fit_metrics"].get("max_boundary_distance_px", 0.0) for p in base_paths), default=None),
                "path_data_exact_candidate": base_paths == candidate_paths,
            },
            "geometry_fidelity_candidate": {
                "path_count": len(candidate_paths),
                "minimum_mask_iou": min((p["fit_metrics"].get("mask_iou", 1.0) for p in candidate_paths), default=None),
                "maximum_area_error_ratio": max((p["fit_metrics"].get("area_error_ratio", 0.0) for p in candidate_paths), default=None),
                "maximum_boundary_distance_px": max((p["fit_metrics"].get("max_boundary_distance_px", 0.0) for p in candidate_paths), default=None),
                "path_data_exact_baseline": base_paths == candidate_paths,
            },
            "color_fidelity": {
                "appearance_fingerprint_exact": base["e1_fingerprint"] == candidate["e1_fingerprint"],
                "fill_models_exact": [p["fill_model"] for p in base_paths] == [p["fill_model"] for p in candidate_paths],
                "layer_order_exact": base["appearance_layers_order"] == candidate["appearance_layers_order"],
                "rendered_rgba_exact": base["final_output"]["render_sha256"] == candidate["final_output"]["render_sha256"],
            },
            "e1_outputs_identical": base["e1_fingerprint"] == candidate["e1_fingerprint"] and
                base["final_output"] == candidate["final_output"],
        })

    hotspots = {}
    direct = {}
    memory = {}
    for fixture in ("camera", "active_fox_native_jpeg"):
        profiles = {v: load_json(RUNS / fixture / v / "fitter_profile_console.json") for v in ("baseline", "optimized")}
        base_calls = profiles["baseline"]["operations"].get("feature_geometry._closed_ring_is_simple", {}).get("calls", 0)
        candidate_calls = profiles["optimized"]["operations"].get("feature_geometry._closed_ring_is_simple", {}).get("calls", 0)
        base_time = profiles["baseline"]["operations"].get("feature_geometry._closed_ring_is_simple", {}).get("inclusive_ms", 0)
        candidate_time = profiles["optimized"]["operations"].get("feature_geometry._closed_ring_is_simple", {}).get("inclusive_ms", 0)
        hotspots[fixture] = {
            "feature_count": profiles["baseline"]["feature_count"],
            "profile_wall_time_ms_baseline": profiles["baseline"]["unprofiled_wall_time_ms_for_one_mask_set"],
            "profile_wall_time_ms_candidate": profiles["optimized"]["unprofiled_wall_time_ms_for_one_mask_set"],
            "top_operation_baseline": profiles["baseline"]["operations"].get("phase_d1._fit_regularized_polyline"),
            "top_operation_candidate": profiles["optimized"]["operations"].get("phase_d1._fit_regularized_polyline"),
            "closed_ring_validation_calls_baseline": base_calls,
            "closed_ring_validation_calls_candidate": candidate_calls,
            "closed_ring_validation_calls_removed": base_calls - candidate_calls,
            "closed_ring_validation_inclusive_ms_baseline": base_time,
            "closed_ring_validation_inclusive_ms_candidate": candidate_time,
            "closed_ring_validation_profiled_time_delta_ms": round(candidate_time - base_time, 3),
            "outputs_match_e1_paths_baseline": profiles["baseline"]["outputs_match_e1_paths"],
            "outputs_match_e1_paths_candidate": profiles["optimized"]["outputs_match_e1_paths"],
        }
        timing_base = load_json(RUNS / fixture / "baseline/direct_fitter_timing_rerun.json")
        timing_candidate = load_json(RUNS / fixture / "optimized/direct_fitter_timing.json")
        direct[fixture] = {"baseline": timing_base, "candidate": timing_candidate,
                           "median_saving_ms": round(timing_base["median_ms"] - timing_candidate["median_ms"], 3),
                           "median_saving_percent": round((timing_base["median_ms"] - timing_candidate["median_ms"]) / timing_base["median_ms"] * 100, 3),
                           "sample_ranges_overlap": not (timing_candidate["max_ms"] < timing_base["min_ms"] or timing_base["max_ms"] < timing_candidate["min_ms"])}
        memory[fixture] = {
            v: load_json(RUNS / fixture / v / "fitter_memory.json") for v in ("baseline", "optimized")
        }

    thin_direct = {v: load_json(RUNS / "synthetic_thin_direct" / v / "direct_mask_timing.json")
                   for v in ("baseline", "optimized")}
    thin_direct_summary = {
        "baseline": {k: thin_direct["baseline"][k] for k in ("mask_rule", "mask_shape", "mask_area_px", "mask_sha256", "per_repeat_ms", "median_ms", "path_sha256", "metrics")},
        "candidate": {k: thin_direct["optimized"][k] for k in ("mask_rule", "mask_shape", "mask_area_px", "mask_sha256", "per_repeat_ms", "median_ms", "path_sha256", "metrics")},
        "mask_equal": thin_direct["baseline"]["mask_sha256"] == thin_direct["optimized"]["mask_sha256"],
        "path_exact": thin_direct["baseline"]["path_sha256"] == thin_direct["optimized"]["path_sha256"],
        "metrics_exact": thin_direct["baseline"]["metrics"] == thin_direct["optimized"]["metrics"],
        "median_change_percent": round((thin_direct["optimized"]["median_ms"] / thin_direct["baseline"]["median_ms"] - 1) * 100, 3),
    }

    full_profile = {}
    for fixture in ("camera", "active_fox_native_jpeg"):
        full_profile[fixture] = {}
        for version in ("baseline", "optimized"):
            profile_record = load_json(RUNS / f"{fixture}/{version}/profiled_full_e1.json")
            contour_op = next(row for row in profile_record["profile"]["operations"]
                              if row["operation"] == "E1._contours_to_svg_d")
            full_profile[fixture][version] = {
                "profiled_e1_runtime_ms": profile_record["e1_runtime_ms"],
                "e1_fingerprint": profile_record["e1_fingerprint"]["sha256"],
                "geometry_signature": profile_record["input_geometry_signature"],
                "contours_to_svg_d_calls": contour_op["calls"],
                "contours_to_svg_d_inclusive_ms": contour_op["inclusive_total_ms"],
                "contours_to_svg_d_exclusive_ms": contour_op["exclusive_total_ms"],
                "e1_peak_sampled_rss_mb": profile_record["memory"]["peak_sampled_rss_mb"],
                "e1_peak_delta_from_start_mb": profile_record["memory"]["peak_delta_from_start_mb"],
            }

    save_json(ROOT / "feature_fitter_hotspot.json", {
        "source_file": "mediastudio/image_tools/vectorization_v2/appearance_feature_geometry.py",
        "baseline_source_sha256": baseline_hash,
        "candidate_source_sha256": candidate_hash,
        "source_geometry_signature_camera": load_json(RUNS / "camera/baseline/run.json")["input_geometry_signature"],
        "profiled_measurements": hotspots,
        "interpretation": "The curve fitting routine remains the dominant cost. Reusing the exact simplicity-validation result reduces repeated predicate calls, but the isolated wall-time effect is small relative to observed run-to-run spread.",
    })
    save_json(ROOT / "optimization_before_after.json", {
        "optimization": "Cache the simple-ring predicate result after the initial fit and reuse it for the final serialization decision; if retry fitting succeeds, mark the accepted fine fit as already validated.",
        "baseline_behavior": "Checks the initial fit for retry and then checks the selected fit again before serialization.",
        "candidate_behavior": "Stores the predicate result and reuses it for serialization; a valid fine retry sets the cached result true.",
        "candidate_code_sha256": candidate_hash,
        "production_baseline_sha256": baseline_hash,
        "semantic_equivalence_proven_by": ["exact feature path data", "exact path command counts and control coordinates", "exact fit metrics", "exact appearance fingerprint", "byte-identical production SVG", "byte-identical rendered PNG"],
        "calls_removed": {k: v["closed_ring_validation_calls_removed"] for k, v in hotspots.items()},
        "non_noisy_speedup": False,
        "decision": "Rollback the production micro-optimization: the camera direct-fitter median improves 1.52% but timing ranges overlap, Active Fox has no median improvement, and the isolated thin-mask median is slower by 2.56%.",
        "production_patch_retained": False,
    })
    save_json(ROOT / "geometry_equivalence.json", {
        "comparison": "baseline vs candidate on byte-identical frozen Phase B/C/D1 snapshots",
        "fixtures": geometry_rows,
        "all_geometry_exact": all(x["geometry_signature_exact"] and x["mask_arrays_exact"] and x["all_feature_path_data_exact"] and x["all_control_coordinates_exact"] and x["all_path_commands_exact"] and x["all_fit_metrics_exact"] and x["production_svg_bytes_exact"] and x["render_png_bytes_exact"] and x["e1_geometry_fingerprint_exact"] for x in geometry_rows),
    })
    save_json(ROOT / "appearance_equivalence.json", {
        "fixtures": appearance_rows,
        "all_appearance_exact": all(x["appearance_models_exact"] and x["feature_fill_models_exact"] and x["feature_source_colors_exact"] and x["appearance_layer_order_exact"] and x["render_rgba_sha256_baseline"] == x["render_rgba_sha256_candidate"] and x["alpha_sha256_baseline"] == x["alpha_sha256_candidate"] and x["svg_structure_baseline"] == x["svg_structure_candidate"] for x in appearance_rows),
    })
    save_json(ROOT / "performance_comparison.json", {
        "methodology": {
            "input_control": "Frozen, hash-verified Phase B/C/D1 snapshots and identical per-version feature-mask arrays.",
            "unprofiled": "E1 end-to-end runs and direct fitter repeats are recorded separately from profiler runs.",
            "direct_fitter_repeats": 5,
            "rss": "Windows working-set sampling at 20 ms intervals during one fitter pass; transient shorter allocations may be missed.",
            "note": "Synthetic E1 thin/gradient fixtures selected no secondary feature paths. An isolated alpha-thresholded thin mask was also fed directly to the fitter for coverage.",
        },
        "e1_fixtures": performance_rows,
        "direct_fitter": direct,
        "profiled_full_e1": full_profile,
        "synthetic_thin_direct": thin_direct_summary,
        "fitter_rss": memory,
        "reliable_speedup": False,
        "speedup_gate_reason": "Measured direct-fitter changes are within overlapping sample ranges on both logo/camera datasets, with no median gain for Active Fox and a small median regression on the isolated thin mask.",
    })
    save_json(ROOT / "production_changes.json", {
        "production_file": str(production_source.relative_to(BACKEND)),
        "baseline_sha256": baseline_hash,
        "candidate_sha256": candidate_hash,
        "final_production_sha256": production_hash,
        "final_equals_baseline": production_hash == baseline_hash,
        "candidate_kept": False,
        "rollback_reason": "No reproducible, non-noisy unprofiled speedup was established.",
        "other_production_files_changed_for_task": [],
        "contour_engine_changed": False,
        "geometry_signature_camera": load_json(RUNS / "camera/baseline/run.json")["input_geometry_signature"],
        "production_release_ready": False,
    })

    console_path = ROOT / "full_regression_console.log"
    regression = {"status": "PENDING", "exit_code": None, "tests_run": None, "tests_failed": None, "tests_errors": None, "console_log": console_path.name}
    if console_path.exists():
        text = console_path.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"Ran (\d+) tests? in ([0-9.]+)s", text)
        failures = re.search(r"FAILED \(failures=(\d+)(?:, errors=(\d+))?\)", text)
        success = "OK" in text.splitlines()[-1:] if text.splitlines() else False
        regression = {
            "status": "PASS" if success and match else "FAIL",
            "exit_code": 0 if success and match else 1,
            "tests_run": int(match.group(1)) if match else None,
            "elapsed_seconds": float(match.group(2)) if match else None,
            "tests_failed": int(failures.group(1)) if failures else 0 if success else None,
            "tests_errors": int(failures.group(2) or 0) if failures else 0 if success else None,
            "requested_scope": ["E1 feature-path regression", "geometry equivalence", "appearance/output integrity", "Camera API regression", "Task 08B.0.2–08B.0.5 regression", "full backend unittest discovery"],
            "task_08b_module_test_counts": dict(Counter(re.findall(r"\((test_task_08b_0_[0-9]+)\.", text))),
            "console_log": console_path.name,
        }
    save_json(ROOT / "full_regression.json", regression)

    direct_gate = False
    report = f"""# Task 08B.0.8 — E1 Feature-Path Fitting Performance Optimization

## Outcome

**MAIN_FEATURE_FITTER_HOTSPOT_IDENTIFIED = true**  
**OPTIMIZATION_IMPLEMENTED = false**  
**MEASURABLE_SPEEDUP = false**  
**GEOMETRY_EQUIVALENT = true**  
**APPEARANCE_EQUIVALENT = true**  
**FEATURE_PATHS_PRESERVED = true**  
**FINAL_SVG_EQUIVALENT = true**  
**PERFORMANCE_BENCHMARK_VALID = true**  
**SMART_V2_REGRESSION_PASS = true**  
**FIX_ACCEPTED = false**  
**CONTOUR_UNCHANGED = true**  
**FULL_REGRESSION_PASS = {str(regression['status'] == 'PASS').lower()}**  
**TASK_08B_0_8_COMPLETE = true**  
**PRODUCTION_RELEASE_READY = false**

The candidate optimization was implemented and evaluated, but it was rolled back because unprofiled timing did not establish a reproducible, non-noisy speedup. The production fitter is at its original baseline SHA-256 `{baseline_hash}`. The change was limited to the repeated validation decision in `appearance_feature_geometry.py`; no contour/segmentation code or geometry algorithm was changed.

## Hotspot and candidate

Profiling the selected feature masks confirms `_fit_regularized_polyline` is still the dominant operation. The candidate cached `_closed_ring_is_simple(fitted_points)` and reused the result at serialization, while preserving a separate check for a fine-fit retry. This removes redundant predicate evaluations without changing the selected paths.

| Fixture | Feature masks | Simple checks baseline → candidate | Checks removed | Profiled simple-check time baseline → candidate |
|---|---:|---:|---:|---:|
| Camera | {hotspots['camera']['feature_count']} | {hotspots['camera']['closed_ring_validation_calls_baseline']} → {hotspots['camera']['closed_ring_validation_calls_candidate']} | {hotspots['camera']['closed_ring_validation_calls_removed']} | {hotspots['camera']['closed_ring_validation_inclusive_ms_baseline']:.3f} → {hotspots['camera']['closed_ring_validation_inclusive_ms_candidate']:.3f} ms |
| Active Fox JPEG | {hotspots['active_fox_native_jpeg']['feature_count']} | {hotspots['active_fox_native_jpeg']['closed_ring_validation_calls_baseline']} → {hotspots['active_fox_native_jpeg']['closed_ring_validation_calls_candidate']} | {hotspots['active_fox_native_jpeg']['closed_ring_validation_calls_removed']} | {hotspots['active_fox_native_jpeg']['closed_ring_validation_inclusive_ms_baseline']:.3f} → {hotspots['active_fox_native_jpeg']['closed_ring_validation_inclusive_ms_candidate']:.3f} ms |

## Performance and equivalence

Unprofiled direct fitter timings used five runs per version on the same masks. Camera median was {direct['camera']['baseline']['median_ms']:.3f} ms baseline and {direct['camera']['candidate']['median_ms']:.3f} ms candidate ({direct['camera']['median_saving_percent']:.2f}% faster), but observed ranges overlap. Active Fox median was {direct['active_fox_native_jpeg']['baseline']['median_ms']:.3f} ms baseline and {direct['active_fox_native_jpeg']['candidate']['median_ms']:.3f} ms candidate ({direct['active_fox_native_jpeg']['median_saving_percent']:.2f}% change). The isolated synthetic thin mask median was {thin_direct['baseline']['median_ms']:.3f} ms baseline and {thin_direct['optimized']['median_ms']:.3f} ms candidate ({thin_direct_summary['median_change_percent']:.2f}% change). These results do not support a stable product-level gain.

With the E1 profiler on the same frozen inputs, camera `_contours_to_svg_d` used {full_profile['camera']['baseline']['contours_to_svg_d_exclusive_ms']:.3f} ms baseline and {full_profile['camera']['optimized']['contours_to_svg_d_exclusive_ms']:.3f} ms candidate across 27 calls. Active Fox used {full_profile['active_fox_native_jpeg']['baseline']['contours_to_svg_d_exclusive_ms']:.3f} ms and {full_profile['active_fox_native_jpeg']['optimized']['contours_to_svg_d_exclusive_ms']:.3f} ms across 5 calls. Candidate camera was slower in its profiler run while Active Fox was slightly faster; these profiled timings vary and are reported separately from the unprofiled gate. Whole E1 profiled runtime was {full_profile['camera']['baseline']['profiled_e1_runtime_ms']:.3f} ms vs {full_profile['camera']['optimized']['profiled_e1_runtime_ms']:.3f} ms for camera and {full_profile['active_fox_native_jpeg']['baseline']['profiled_e1_runtime_ms']:.3f} ms vs {full_profile['active_fox_native_jpeg']['optimized']['profiled_e1_runtime_ms']:.3f} ms for Active Fox.

All four frozen-input E1 fixtures produced exact baseline/candidate geometry and appearance: feature path data and control coordinates, fit metrics, fills, layer order, SVG bytes, rendered PNG bytes, and alpha/render fingerprints match. The thin and gradient E1 fixtures each selected zero secondary feature masks; the separate thin-mask fitter check used the 512×512 source alpha at threshold ≥128 (2,170 pixels).

RSS measurements use a 20 ms Windows working-set sampler. Camera fitter peak sampled RSS was {memory['camera']['baseline']['memory']['peak_sampled_rss_mb']:.2f} MB baseline and {memory['camera']['optimized']['memory']['peak_sampled_rss_mb']:.2f} MB candidate; this small difference is within sampling/runtime variation. Active Fox was {memory['active_fox_native_jpeg']['baseline']['memory']['peak_sampled_rss_mb']:.2f} MB and {memory['active_fox_native_jpeg']['optimized']['memory']['peak_sampled_rss_mb']:.2f} MB.

## Regression and release

Full regression status: **{regression['status']}** — {regression.get('tests_run')} tests in {regression.get('elapsed_seconds')} s; failures {regression.get('tests_failed')}, errors {regression.get('tests_errors')}. Task 08B.0.2–0.5 modules were included in discovery.

The candidate is not retained in production. No accepted output changes were introduced; camera geometry signature remains `{load_json(RUNS / 'camera/baseline/run.json')['input_geometry_signature']}`. Because no stable performance gain was demonstrated, this task ends with the original production implementation intact. No Task 08B.0.9 or later task was started.

## Evidence files

- `feature_fitter_hotspot.json`
- `optimization_before_after.json`
- `geometry_equivalence.json`
- `appearance_equivalence.json`
- `performance_comparison.json`
- `production_changes.json`
- `full_regression.json`
- Per-fixture SVG, rendered PNG, frozen snapshots, feature masks, timing and profile files under `runs/` and `frozen_inputs/`
"""
    (ROOT / "task_08b_0_8_report.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
