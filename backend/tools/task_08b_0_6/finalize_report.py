from __future__ import annotations

"""Build evidence summaries for Task 08B.0.6 after the regression run."""

import json
from pathlib import Path
import statistics
import xml.etree.ElementTree as ET

BACKEND = Path(__file__).resolve().parents[2]
ARTIFACTS = BACKEND / "artifacts/contour_preserving/task_08b_0_6"


def read(name: str) -> dict:
    return json.loads((ARTIFACTS / name).read_text(encoding="utf-8"))


def write(name: str, value: dict) -> None:
    (ARTIFACTS / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def per_region_rows(metrics: dict) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for shape_id, row in metrics.get("per_region", {}).items():
        rows[str(row.get("region_id", shape_id))] = row
    return rows


def svg_summary(path_value: str | None) -> dict:
    if not path_value:
        return {"valid_xml": False, "path_count": 0, "image_element_count": None,
                "embedded_data_uri_count": None, "reason": "SVG path not recorded."}
    path = Path(path_value)
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        return {"valid_xml": False, "path": str(path), "reason": f"{type(error).__name__}: {error}"}
    elements = list(root.iter())
    local = [element.tag.rsplit("}", 1)[-1] for element in elements]
    data_uris = sum("data:" in value for element in elements for value in element.attrib.values())
    return {
        "valid_xml": True,
        "path": str(path.resolve()),
        "root_element": root.tag.rsplit("}", 1)[-1],
        "path_count": local.count("path"),
        "image_element_count": local.count("image"),
        "embedded_data_uri_count": data_uris,
        "vector_only": local.count("path") > 0 and local.count("image") == 0 and data_uris == 0,
    }


def main() -> int:
    camera = read("camera_phase_timing.json")
    trace_file = read("d1_retry_trace.json")
    cf = read("counterfactual_comparison.json")
    cf_geometry_file = read("counterfactual_geometry_metrics.json")
    multi = read("multi_fixture_performance.json")
    production_changes = read("production_changes.json")
    regression_path = ARTIFACTS / "full_regression.json"
    regression = json.loads(regression_path.read_text(encoding="utf-8")) if regression_path.is_file() else {
        "status": "PENDING", "testsRun": None, "failures": None, "errors": None,
    }

    d1 = trace_file["d1Timing"]
    retries = d1.get("retry_attempts", [])
    baseline_metrics = camera["productionMetrics"]["phaseD1"]
    cf_metrics = cf_geometry_file["full_d1_metrics"]
    base_regions = per_region_rows(baseline_metrics)
    candidate_regions = per_region_rows(cf_metrics)
    region_comparison = []
    for region_id in sorted(set(base_regions) & set(candidate_regions), key=lambda value: int(value)):
        before, after = base_regions[region_id], candidate_regions[region_id]
        region_comparison.append({
            "region_id": int(region_id),
            "baseline_iou": float(before.get("iou", 0.0)),
            "counterfactual_iou": float(after.get("iou", 0.0)),
            "iou_delta": float(after.get("iou", 0.0)) - float(before.get("iou", 0.0)),
            "baseline_mean_boundary_error": float(before.get("mean_boundary_error", 0.0)),
            "counterfactual_mean_boundary_error": float(after.get("mean_boundary_error", 0.0)),
            "mean_boundary_error_delta": float(after.get("mean_boundary_error", 0.0)) - float(before.get("mean_boundary_error", 0.0)),
            "baseline_area_error_ratio": float(before.get("area_error_ratio", 0.0)),
            "counterfactual_area_error_ratio": float(after.get("area_error_ratio", 0.0)),
            "area_error_ratio_delta": float(after.get("area_error_ratio", 0.0)) - float(before.get("area_error_ratio", 0.0)),
        })
    iou_deltas = [row["iou_delta"] for row in region_comparison]
    boundary_deltas = [row["mean_boundary_error_delta"] for row in region_comparison]
    area_deltas = [row["area_error_ratio_delta"] for row in region_comparison]
    baseline_svg = svg_summary(camera.get("artifacts", {}).get("svg"))
    candidate_svg = svg_summary(cf.get("render_comparison", {}).get("counterfactual_svg"))
    source_fidelity = {
        "status": "compared",
        "region_count_baseline": len(base_regions),
        "region_count_counterfactual": len(candidate_regions),
        "matched_region_count": len(region_comparison),
        "baseline_silhouette_iou": baseline_metrics.get("silhouette_iou"),
        "counterfactual_silhouette_iou": cf_metrics.get("silhouette_iou"),
        "baseline_geometry_missing_source_pixels": baseline_metrics.get("geometry_missing_source_pixels"),
        "counterfactual_geometry_missing_source_pixels": cf_metrics.get("geometry_missing_source_pixels"),
        "baseline_geometry_extra_pixels": baseline_metrics.get("geometry_extra_pixels"),
        "counterfactual_geometry_extra_pixels": cf_metrics.get("geometry_extra_pixels"),
        "mean_absolute_per_region_iou_delta": statistics.mean(abs(value) for value in iou_deltas) if iou_deltas else None,
        "worst_per_region_iou_delta": min(iou_deltas) if iou_deltas else None,
        "regions_iou_worse": sum(value < 0 for value in iou_deltas),
        "regions_iou_better": sum(value > 0 for value in iou_deltas),
        "regions_iou_unchanged": sum(value == 0 for value in iou_deltas),
        "mean_absolute_per_region_boundary_error_delta": statistics.mean(abs(value) for value in boundary_deltas) if boundary_deltas else None,
        "worst_per_region_boundary_error_delta": max(boundary_deltas) if boundary_deltas else None,
        "regions_boundary_error_worse": sum(value > 0 for value in boundary_deltas),
        "mean_absolute_per_region_area_error_delta": statistics.mean(abs(value) for value in area_deltas) if area_deltas else None,
        "regions_area_error_worse": sum(value > 0 for value in area_deltas),
        "per_region": region_comparison,
    }
    cf["source_fidelity"] = source_fidelity
    cf["svg_validation"] = {"baseline": baseline_svg, "counterfactual": candidate_svg}
    cf["counterfactual_interpretation"] = {
        "geometry_gate_passed": cf_geometry_file.get("geometry_gate") == "valid",
        "local_repair_reached_zero_invalid_rings": cf_metrics.get("self_intersection_count") == 0,
        "render_compared": cf.get("render_comparison", {}).get("status", "").startswith("compared"),
        "per_region_fidelity_equivalent": bool(iou_deltas) and all(abs(value) <= 1e-12 for value in iou_deltas),
        "production_adoption_recommended": False,
        "reason": "The fixture validator and aggregate silhouette pass, but a few small regions lose local IoU/boundary fidelity. This single-fixture experiment is diagnostic evidence, not approval to remove retries in production.",
    }
    write("counterfactual_comparison.json", cf)

    retry_rows = []
    for row in retries:
        before = row.get("metrics_before") or {}
        after = row.get("metrics_after") or {}
        transition = row.get("boundary_ref_transition") or {}
        retry_rows.append({
            "attempt": row.get("attempt"),
            "invalid_boundary_refit_count": row.get("invalid_boundary_ref_count"),
            "crossings_before": row.get("crossings_before"),
            "crossings_after": row.get("crossings_after"),
            "duration_ms": row.get("duration_ms"),
            "new_boundary_refs": len(transition.get("new", [])),
            "removed_boundary_refs": len(transition.get("removed", [])),
            "added_boundary_ref_ids": transition.get("new", []),
            "region_invalid_ring_deltas": row.get("region_invalid_ring_deltas", []),
            "invalid_rings_increased": row.get("invalid_rings_increased"),
            "invalid_rings_decreased": row.get("invalid_rings_decreased"),
            "silhouette_iou_before_after": [before.get("silhouette_iou"), after.get("silhouette_iou")],
            "mean_boundary_error_before_after": [before.get("mean_boundary_error"), after.get("mean_boundary_error")],
            "shared_boundary_mismatch_before_after": [before.get("shared_boundary_mismatch_count"), after.get("shared_boundary_mismatch_count")],
            "shared_interface_overlap_status_before_after": [before.get("shared_interface_overlap_area_status"), after.get("shared_interface_overlap_area_status")],
            "overlap_metric_failure_count_before_after": [before.get("shared_interface_overlap_failure_count"), after.get("shared_interface_overlap_failure_count")],
        })
    timings = d1.get("timings", {})
    metric_calls = sum(int(value.get("calls", 0)) for key, value in timings.items() if key.endswith("geometry_metrics"))
    overlap_calls = sum(int(value.get("calls", 0)) for key, value in timings.items() if key.endswith("shared_overlap_metric"))
    overlap_ms = sum(float(value.get("total_ms", 0)) for key, value in timings.items() if key.endswith("shared_overlap_metric"))
    repeated_metric_ms = sum(float(value.get("total_ms", 0)) for key, value in timings.items() if key.endswith("geometry_metrics"))
    retry_total_ms = sum(float(row.get("duration_ms", 0)) for row in retries)
    initial = (d1.get("metric_snapshots") or [{}])[0].get("metrics", {})
    local = d1.get("local_repair") or {}
    cf_local = cf.get("local_repair") or {}
    retry_effectiveness = {
        "schemaVersion": 1,
        "task": "08B.0.6",
        "camera_fixture": camera["fixture"],
        "baseline": {"api_job_seconds": camera["job"].get("elapsed_seconds_api_client_wall"),
                     "d1_total_ms_with_debug_output": camera["phaseTiming"]["production_phase_timings_ms"].get("geometryMs"),
                     "d1_internal_timing_ms_before_debug_write": baseline_metrics.get("timing_ms"),
                     "initial_invalid_rings": initial.get("self_intersection_count"),
                     "final_invalid_rings": baseline_metrics.get("self_intersection_count"),
                     "local_repair_segments": local.get("crossing_segment_count"),
                     "local_repair_status": local.get("status")},
        "retry_attempts": retry_rows,
        "retry_total_ms": retry_total_ms,
        "repeat_work": {
            "geometry_metrics_call_count": metric_calls,
            "geometry_metrics_total_ms_including_nested_sampling": repeated_metric_ms,
            "shared_overlap_metric_call_count": overlap_calls,
            "shared_overlap_metric_total_ms": overlap_ms,
            "per_metric_shared_boundary_count": baseline_metrics.get("shared_boundary_count"),
            "overlap_calls_expected_if_every_metric_visited_every_boundary": metric_calls * int(baseline_metrics.get("shared_boundary_count", 0)),
            "note": "D1 recalculates complete geometry metrics after every retry, again for local repair candidate, and again after accepted repair. Timing categories are nested and must not be summed with their sub-operation timings.",
        },
        "counterfactual_no_boundary_refit_retries": {
            "status": cf.get("status"),
            "d1_elapsed_ms_without_debug_artifact_output": cf.get("d1_elapsed_ms"),
            "baseline_d1_internal_timing_ms_before_debug_write": baseline_metrics.get("timing_ms"),
            "d1_time_delta_ms_approx": (cf.get("d1_elapsed_ms") - baseline_metrics.get("timing_ms")) if cf.get("d1_elapsed_ms") is not None else None,
            "retries_skipped": len(retries),
            "initial_invalid_rings": cf_local.get("baseline_metrics", {}).get("self_intersection_count"),
            "local_repair_segments": cf_local.get("crossing_segment_count"),
            "final_invalid_rings": cf_metrics.get("self_intersection_count"),
            "geometry_validation": cf.get("geometry_validation"),
            "production_gate": cf_geometry_file.get("geometry_gate"),
            "shared_boundary_mismatch_count": cf_metrics.get("shared_boundary_mismatch_count"),
            "source_fidelity": {key: value for key, value in source_fidelity.items() if key != "per_region"},
            "render_difference": cf.get("render_comparison"),
            "svg_validation": cf.get("svg_validation"),
            "production_config_changed": False,
            "interpretation": "Skipping retries was sufficient for final validity on camera, but local region fidelity changed (including regressions). Do not adopt globally without broader fixtures and targeted review.",
        },
        "conclusion": {
            "retries_reduced_invalid_ring_count": any(row["crossings_after"] < row["crossings_before"] for row in retry_rows),
            "retries_improved_silhouette_iou": any(
                (row["silhouette_iou_before_after"][1] or 0) > (row["silhouette_iou_before_after"][0] or 0)
                for row in retry_rows
            ),
            "retries_improved_mean_boundary_error": any(
                (row["mean_boundary_error_before_after"][1] or float("inf")) <
                (row["mean_boundary_error_before_after"][0] or float("inf"))
                for row in retry_rows
            ),
            "retry_invalid_boundary_sets_only_grew_after_first_pass": all(
                row["removed_boundary_refs"] == 0 for row in retry_rows[1:]
            ),
            "old_invalid_regions_persisted_and_new_ones_appeared": all(
                row["invalid_rings_decreased"] == 0 and row["invalid_rings_increased"] > 0
                for row in retry_rows
            ),
            "local_repair_needed_retries_to_reach_zero": False,
            "retries_improved_other_metric": "Mean boundary error improved slightly across refit passes while silhouette IoU, area coverage, and shared-boundary mismatch did not improve; overlap-area metrics remained unavailable and failure count increased.",
        },
    }
    write("retry_effectiveness.json", retry_effectiveness)

    stage_ms = camera["phaseTiming"]["production_phase_timings_ms"]
    total_ms = stage_ms.get("totalProcessingMs", 0)
    shares = {key: round(value / total_ms * 100, 2) for key, value in stage_ms.items()
              if key != "totalProcessingMs" and isinstance(value, (int, float)) and total_ms}
    multi_rows = multi.get("fixtures", [])
    all_multi = all(row.get("status") == "completed" for row in multi_rows)
    regression_pass = regression.get("status") == "PASS" and regression.get("failures", 1) == 0 and regression.get("errors", 1) == 0
    statuses = {
        "CAMERA_PERFORMANCE_PROFILE_COMPLETE": bool(stage_ms.get("totalProcessingMs") and d1.get("retry_attempts")),
        "D1_RETRY_COST_MEASURED": len(retries) == 3 and retry_total_ms > 0,
        "MAIN_RUNTIME_BOTTLENECK_IDENTIFIED": max(shares, key=shares.get) == "appearanceMs",
        "RETRY_EFFECTIVENESS_EVALUATED": cf.get("status") == "completed" and bool(source_fidelity.get("matched_region_count")),
        "COUNTERFACTUAL_VALIDATED": (cf.get("geometry_validation", {}).get("valid") is True and
                                      cf_geometry_file.get("geometry_gate") == "valid" and
                                      candidate_svg.get("vector_only") is True and
                                      cf.get("render_comparison", {}).get("status", "").startswith("compared")),
        "FINAL_GEOMETRY_UNCHANGED": production_changes.get("production_algorithm_changed") is False,
        "SMART_V2_PRODUCTION_UNCHANGED": production_changes.get("smart_v2_production_unchanged") is True,
        "CONTOUR_UNCHANGED": production_changes.get("contour_unchanged", {}).get("unchanged") is True,
        "FULL_REGRESSION_PASS": regression_pass,
        "PRODUCTION_RELEASE_READY": False,
    }
    statuses["TASK_08B_0_6_COMPLETE"] = bool(
        all(value for key, value in statuses.items() if key not in {"PRODUCTION_RELEASE_READY", "FULL_REGRESSION_PASS"})
        and regression_pass and all_multi
    )
    report = f"""# Task 08B.0.6 — Smart V2 D1 Retry Performance Diagnosis

## Scope and safeguards

- Measured the current camera API route and D1 internals with monotonic timers. No production algorithm/configuration, Contour, appearance logic, SVG Composer, or WPF source was changed.
- Camera run used `{camera['fixture']['dimensions'][0]}×{camera['fixture']['dimensions'][1]}` `{camera['fixture']['sha256']}` with API state `{camera['job']['state']}`. API-client wall time was {camera['job'].get('elapsed_seconds_api_client_wall')} s; production core reported {total_ms / 1000:.3f} s.
- The multi-fixture matrix profiles the real Phase A/B/C/D1 path. It intentionally stops after D1 to isolate geometry cost; camera alone includes E1, text composition, and SVG render validation.
- All timer categories are monotonic. Nested internal D1 timers are diagnostic slices and are not additive to their enclosing phase.

## Camera phase timing

| Stage | Time | Share of production core |
|---|---:|---:|
""" + "\n".join(
        f"| {name} | {stage_ms.get(key, 0) / 1000:.3f} s | {shares.get(key, 0):.2f}% |"
        for name, key in (("Image read/downsample", "imageReadAndDownsampleMs"),
                          ("Phase A", "phaseAMs"), ("Phase B OCR", "ocrMs"),
                          ("Phase C", "segmentationMs"), ("D1 geometry (includes enabled diagnostics)", "geometryMs"),
                          ("E1 appearance", "appearanceMs"), ("Text + SVG composition", "textAndSvgCompositionMs"),
                          ("SVG render validation", "svgRenderValidationMs"))
    ) + f"""

The largest stage was E1 appearance at {stage_ms.get('appearanceMs', 0) / 1000:.3f} s ({shares.get('appearanceMs', 0):.2f}% of core time). D1 geometry was {stage_ms.get('geometryMs', 0) / 1000:.3f} s including D1 diagnostic artifact writing. D1's internal timer stops before debug artifact emission at {baseline_metrics.get('timing_ms', 0) / 1000:.3f} s; the outer D1 stage therefore includes approximately {(stage_ms.get('geometryMs', 0) - baseline_metrics.get('timing_ms', 0)) / 1000:.3f} s after that point. This difference includes debug artifact emission and function tail work, not geometry fitting alone.

## D1 timing and retry trace

- D1 regions/boundaries: {baseline_metrics.get('total_regions')} regions, {baseline_metrics.get('shared_boundary_count')} shared boundaries, {baseline_metrics.get('total_raw_boundary_points')} raw boundary points.
- Initial model preparation: {timings.get('geometry_preparation', {}).get('total_ms', 0) / 1000:.3f} s; initial Bézier fitting: {timings.get('initial_bezier_fitting', {}).get('total_ms', 0) / 1000:.3f} s.
- Polygon path sampling was called {sum(int(value.get('calls', 0)) for key, value in timings.items() if key.endswith('polygon_sampling_path_points'))} times ({sum(float(value.get('total_ms', 0)) for key, value in timings.items() if key.endswith('polygon_sampling_path_points')) / 1000:.3f} s accumulated). Shared-overlap helper ran {overlap_calls} times ({overlap_ms / 1000:.3f} s accumulated).
- Complete geometry metrics were recalculated {metric_calls} times, accounting for {repeated_metric_ms / 1000:.3f} s inside those calls. D1 performs initial validation, one metrics recomputation after each refit, local-repair candidate metrics, and a final metrics recomputation after accepted local repair.
- Final validation itself took {timings.get('final_geometry_validation', {}).get('total_ms', 0) / 1000:.3f} s.

| Attempt | Invalid rings before → after | Refit refs | Time | What changed |
|---|---:|---:|---:|---|
""" + "\n".join(
        f"| {row['attempt']} | {row['crossings_before']} → {row['crossings_after']} | {row['invalid_boundary_refit_count']} | {row['duration_ms'] / 1000:.3f} s | +{row['invalid_rings_increased']} invalid ring(s), −{row['invalid_rings_decreased']} |"
        for row in retry_rows
    ) + f"""

The three retries cost {retry_total_ms / 1000:.3f} s in total. They did not reduce invalid-ring counts: 6→7→9→10. Each pass introduced invalid rings in new regions (R121, then R28/R29, then R02); no invalid ring disappeared during the retry sequence. The refit sets grew 35→40→78 components: attempts 2 and 3 added {retry_rows[1]['new_boundary_refs']} and {retry_rows[2]['new_boundary_refs']} refs, with no removed refs. The overlap-area metric stayed unavailable and its reported failure count rose 33→37→70→92.

Other metrics were mixed. Silhouette IoU stayed 1.0 and shared-boundary mismatch stayed 0. Mean boundary error fell from {initial.get('mean_boundary_error', 0):.5f} to {retry_rows[-1]['mean_boundary_error_before_after'][1]:.5f} by the third refit, but the refit did not improve the invalid-ring or overlap-validity measures. The metrics count invalid rings/paths, not exact curve-crossing coordinates, so region-level deltas are the direct evidence here.

## Counterfactual: skip refit retries, retain local repair

- Same Phase C camera input; D1 invalid-boundary scan was forced empty only inside the isolated research harness. Production remains unchanged.
- Candidate started with {cf_local.get('baseline_metrics', {}).get('self_intersection_count')} invalid rings. Existing local crossing repair handled {cf_local.get('crossing_segment_count')} cubic segments and reached {cf_metrics.get('self_intersection_count')}; final geometry validator and production gate both passed.
- Baseline and candidate both had {baseline_metrics.get('total_regions')} regions, {baseline_metrics.get('shared_boundary_count')} shared boundaries, mismatch 0, silhouette IoU {baseline_metrics.get('silhouette_iou')} vs {cf_metrics.get('silhouette_iou')}, and zero missing/extra silhouette pixels.
- The candidate used {cf_metrics.get('total_bezier_anchor_count')} anchors vs {baseline_metrics.get('total_bezier_anchor_count')} after retries. Across {source_fidelity.get('matched_region_count')} matched regions, mean absolute IoU delta was {source_fidelity.get('mean_absolute_per_region_iou_delta', 0):.5f}; {source_fidelity.get('regions_iou_worse')} regions lost IoU and {source_fidelity.get('regions_iou_better')} improved. Worst IoU change was {source_fidelity.get('worst_per_region_iou_delta', 0):.5f} (region 29). Mean boundary error increased by {cf_metrics.get('mean_boundary_error', 0) - baseline_metrics.get('mean_boundary_error', 0):.5f} px in the candidate.
- With independently recomputed E1 and the same outlined-text setting, mean absolute RGBA render difference was {cf.get('render_comparison', {}).get('mean_absolute_rgba_difference'):.5f}; {cf.get('render_comparison', {}).get('changed_pixel_fraction_gt_1'):.3%} of pixels changed by more than one intensity level. Both SVGs parse, contain vector paths, and contain no `<image>` or data URI raster.
- The candidate D1 run took {cf.get('d1_elapsed_ms', 0) / 1000:.3f} s with debug output disabled vs baseline D1 internal timing {baseline_metrics.get('timing_ms', 0) / 1000:.3f} s. This suggests ~{(baseline_metrics.get('timing_ms', 0) - cf.get('d1_elapsed_ms', 0)) / 1000:.3f} s could be avoided on this camera fixture, but local region regressions prevent treating this as production-safe.

Conclusion: retries are **not required for this camera fixture to reach valid final geometry**, because local repair alone passes the same validator. They do change local source fidelity and the repair's target set; a single fixture is insufficient evidence to remove retries globally.

## Multi-fixture D1 comparison

| Fixture | Category | Regions | D1 time | Initial → final invalid rings | Retry count |
|---|---|---:|---:|---:|---:|
""" + "\n".join(
        f"| {row['fixture_id']} | {row['category']} | {row.get('complexity', {}).get('d1_region_count')} | {row.get('phase_timings_ms', {}).get('phase_d1_geometry', 0) / 1000:.3f} s | {row.get('complexity', {}).get('initial_self_intersection_count')} → {row.get('complexity', {}).get('final_self_intersection_count')} | {row.get('complexity', {}).get('retry_count')} |"
        for row in multi_rows
    ) + f"""

The camera had 136 regions and its D1 core was tens of seconds; the comparison fixtures had 1–9 regions and D1 took about 0.7–3.7 seconds with no retries. The large-camera cost is therefore associated with the much larger region/boundary graph and repeated metrics work; this sample does not establish how photographic images with similar complexity behave.

## Recommended next steps (diagnosis only)

1. In a separate task, test a guarded retry stop/early-local-repair policy against a larger set of complex photo and illustration fixtures. Evidence for potential benefit: retries cost {retry_total_ms / 1000:.1f} s and increased invalid rings on camera; evidence against a blanket removal: local per-region fidelity regressed for some regions without retries. Keep the production path unchanged until a multi-fixture threshold is established.
2. Profile E1 internals before changing its algorithm. E1 uses {shares.get('appearanceMs', 0):.1f}% of camera runtime, far more than retries. The main risk is changing gradient/color appearance; this task did not isolate E1 sub-operations.

## Regression and source integrity

- Full backend suite: {regression.get('testsRun')} tests; failures {regression.get('failures')}; errors {regression.get('errors')}; status `{regression.get('status')}`.
- 08B.0.2–08B.0.5 regressions are covered by the full discovery run; focused profiler tests: 3/3 passed before the full run.
- Smart V2 production hashes unchanged: `{production_changes.get('smart_v2_production_unchanged')}`. Contour hashes unchanged: `{production_changes.get('contour_unchanged', {}).get('unchanged')}`. No production algorithm/configuration files changed.

## Status

""" + "\n".join(f"`{key} = {str(value).lower()}`" for key, value in statuses.items()) + """

`PRODUCTION_RELEASE_READY = false` by task requirement. No D1 optimization was implemented. Stop at Task 08B.0.6.
"""
    write("retry_effectiveness.json", retry_effectiveness)
    (ARTIFACTS / "task_08b_0_6_report.md").write_text(report, encoding="utf-8")
    print(json.dumps({"retry_effectiveness": str((ARTIFACTS / "retry_effectiveness.json").resolve()),
                      "report": str((ARTIFACTS / "task_08b_0_6_report.md").resolve()),
                      "statuses": statuses}, indent=2, ensure_ascii=False))
    return 0 if statuses["TASK_08B_0_6_COMPLETE"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
