from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path
from typing import Any

from .dataset import ARTIFACTS, CATEGORY_NAMES, write_json


def _read_checkpoint(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return {row["imageId"]: row for row in value.get("items", []) if row.get("imageId")}


def _metric(row: dict[str, Any] | None, dotted_path: tuple[str, ...]) -> float | None:
    current: Any = row
    for key in dotted_path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    try:
        return float(current) if current is not None else None
    except (TypeError, ValueError):
        return None


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def summarize_records(records: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    manifest_by_id = {item["imageId"]: item for item in manifest.get("items", [])}
    per_image = []
    for record in records:
        engines = record.get("engines", {})
        selected = {}
        for method in ("smart_reconstruction", "contour_preserving"):
            run = engines.get(method, {})
            quality = run.get("qualityMetrics", {})
            selected[method] = {
                "status": run.get("status", "NOT_RUN"),
                "geometryIoU": _metric(quality, ("geometry", "foregroundIoU")),
                "boundaryP95Px": _metric(quality, ("geometry", "p95SymmetricBoundaryDistancePx")),
                "meanDeltaE00": _metric(quality, ("color", "foregroundOrContent", "meanDeltaE00")),
                "p95DeltaE00": _metric(quality, ("color", "foregroundOrContent", "p95DeltaE00")),
                "maskedSsim": _metric(quality, ("color", "foregroundOrContent", "maskedSsim")),
                "gradientDirectionCosine": _metric(quality, ("gradient", "directionCosineMean")),
                "gradientFalseBoundaryFraction": _metric(quality, ("gradient", "falseHardBoundaryFractionInSourceSmoothGradient")),
                "analyticDetailMacroIoU": _metric(quality, ("details", "macroFeatureIoU")),
                "analyticDetailMacroRecall": _metric(quality, ("details", "macroFeatureRecall")),
                "alphaIoU": _metric(quality, ("transparency", "alphaIoU")),
                "svgBytes": run.get("svgBytes"),
                "pathCount": _metric(run, ("svgValidation", "visiblePathElementCount")),
                "wallSeconds": run.get("wallSeconds"),
                "peakCombinedWorkingSetBytes": _metric(run, ("memory", "peakCombinedWorkingSetBytes")),
                "rendererConsistency": run.get("skiaRendererCheck", {}).get("status"),
                "svgValidation": run.get("svgValidation", {}).get("status"),
            }
        item = manifest_by_id.get(record.get("imageId"), {})
        per_image.append({
            "imageId": record.get("imageId"), "sourceFamilyId": record.get("sourceFamilyId"),
            "sourceType": record.get("sourceType"), "categories": record.get("categories", []),
            "datasetSplit": record.get("datasetSplit"), "sourceSha256": record.get("sourceSha256"),
            "referenceType": record.get("referenceType"), "recordStatus": record.get("status"),
            "engines": selected,
            "preferredResult": "inconclusive",
            "preferenceReason": "No human review is attached; metric trade-offs are reported independently and no single metric selects a winner.",
            "contactSheet": (record.get("visualDiagnostics") or {}).get("contactSheet"),
            "itemDimensions": [item.get("width"), item.get("height")],
        })

    categories = {}
    for category in CATEGORY_NAMES:
        rows = [row for row in per_image if category in row["categories"]]
        cat_result: dict[str, Any] = {
            "imageVariantCount": len(rows),
            "independentRealSourceFamilyCount": len({row["sourceFamilyId"] for row in rows if str(row.get("sourceType", "")).startswith("real_")}),
            "syntheticFixtureCount": sum(str(row.get("sourceType", "")).startswith("synthetic_") for row in rows),
            "humanReviewStatus": "pending",
            "engineSummaries": {},
            "conclusion": "inconclusive_due_to_coverage_or_pending_human_review",
        }
        for method in ("smart_reconstruction", "contour_preserving"):
            keys = ("geometryIoU", "boundaryP95Px", "meanDeltaE00", "p95DeltaE00", "maskedSsim", "gradientDirectionCosine", "gradientFalseBoundaryFraction", "analyticDetailMacroIoU", "analyticDetailMacroRecall", "alphaIoU", "wallSeconds", "peakCombinedWorkingSetBytes", "svgBytes")
            summary: dict[str, Any] = {"successfulImageCount": sum(row["engines"][method]["status"] == "SUCCEEDED" for row in rows)}
            for key in keys:
                values = [float(row["engines"][method][key]) for row in rows if row["engines"][method][key] is not None]
                summary[f"median_{key}"] = _median(values)
                summary[f"measuredCount_{key}"] = len(values)
            cat_result["engineSummaries"][method] = summary
        cat_result["byEvidenceType"] = {}
        for evidence_type, predicate in (("real_raster", lambda row: str(row.get("sourceType", "")).startswith("real_")),
                                         ("synthetic_analytical", lambda row: str(row.get("sourceType", "")).startswith("synthetic_"))):
            evidence_rows = [row for row in rows if predicate(row)]
            evidence_summary: dict[str, Any] = {"imageVariantCount": len(evidence_rows),
                "independentSourceFamilyCount": len({row["sourceFamilyId"] for row in evidence_rows}),
                "humanReviewStatus": "pending"}
            for method in ("smart_reconstruction", "contour_preserving"):
                engine_summary: dict[str, Any] = {"successfulImageCount": sum(row["engines"][method]["status"] == "SUCCEEDED" for row in evidence_rows)}
                for key in ("geometryIoU", "boundaryP95Px", "meanDeltaE00", "p95DeltaE00", "maskedSsim", "gradientDirectionCosine", "gradientFalseBoundaryFraction", "analyticDetailMacroIoU", "analyticDetailMacroRecall", "alphaIoU", "wallSeconds", "peakCombinedWorkingSetBytes", "svgBytes"):
                    values = [float(row["engines"][method][key]) for row in evidence_rows if row["engines"][method][key] is not None]
                    engine_summary[f"median_{key}"] = _median(values)
                    engine_summary[f"measuredCount_{key}"] = len(values)
                evidence_summary[method] = engine_summary
            cat_result["byEvidenceType"][evidence_type] = evidence_summary
        categories[category] = cat_result

    return {"schemaVersion": 1, "imageCount": len(per_image), "perImage": per_image, "perCategory": categories,
            "aggregateInterpretation": "Descriptive benchmark only. Synthetic analytical evidence and user-provided raster-reference evidence are tracked separately; no engine-wide winner is claimed from the current dataset."}


def build_cross_engine_comparison(summary: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for item in summary.get("perImage", []):
        smart, contour = item["engines"]["smart_reconstruction"], item["engines"]["contour_preserving"]
        deltas: dict[str, float | None] = {}
        for metric in ("geometryIoU", "meanDeltaE00", "p95DeltaE00", "maskedSsim", "analyticDetailMacroIoU", "gradientDirectionCosine", "wallSeconds", "svgBytes"):
            left, right = smart.get(metric), contour.get(metric)
            deltas[metric] = (float(right) - float(left)) if left is not None and right is not None else None
        rows.append({**{key: item.get(key) for key in ("imageId", "sourceFamilyId", "sourceType", "categories", "datasetSplit", "recordStatus", "contactSheet")},
                     "smartReconstruction": smart, "contourPreserving": contour, "contourMinusSmart": deltas,
                     "mainDefects": _defect_labels(smart, contour), "preferredResult": "inconclusive"})
    return {"schemaVersion": 1, "items": rows,
            "categorySummary": summary.get("perCategory", {}),
            "crossEngineConclusions": {
                "smartUsuallyBetterCategories": "inconclusive",
                "contourUsuallyBetterCategories": "inconclusive",
                "bothEnginesWeakCategories": "inconclusive",
                "sharedDefects": "Only assessable as repeated evidence after multiple independent real families and human review; current coverage is insufficient.",
                "contourOnlyDefects": "See per-image metrics and API/validation failures; no broad generalization.",
                "smartOnlyDefects": "See per-image metrics and API/validation failures; no broad generalization.",
            }}


def _defect_labels(smart: dict[str, Any], contour: dict[str, Any]) -> list[str]:
    result = []
    for name, row in (("SMART", smart), ("CONTOUR", contour)):
        if row.get("status") != "SUCCEEDED":
            result.append(f"{name}_ENGINE_RUN_FAILURE")
            continue
        if row.get("svgValidation") != "PASS":
            result.append(f"{name}_SVG_VALIDATION_FAILURE")
        if row.get("rendererConsistency") in {"FAIL", "TIMEOUT"}:
            result.append(f"{name}_RENDERER_INCONSISTENCY")
        if row.get("analyticDetailMacroRecall") is not None and row["analyticDetailMacroRecall"] < 0.75:
            result.append(f"{name}_SYNTHETIC_DETAIL_RECALL_LOW")
        if row.get("geometryIoU") is not None and row["geometryIoU"] < 0.90:
            result.append(f"{name}_FOREGROUND_MASK_IOU_LOW")
        if row.get("meanDeltaE00") is not None and row["meanDeltaE00"] > 8.0:
            result.append(f"{name}_RASTER_REFERENCE_COLOR_ERROR_HIGH")
    return result


def build_failures(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    failures = []
    for record in records:
        failed_engine_count = 0
        for method, run in (record.get("engines") or {}).items():
            if run.get("status") != "SUCCEEDED":
                failed_engine_count += 1
                failures.append({"imageId": record.get("imageId"), "sourceSha256": record.get("sourceSha256"),
                                 "engine": method, "failureType": run.get("failureType") or run.get("failureCode") or "ENGINE_RUN_FAILURE",
                                 "failureCode": run.get("failureCode"),
                                 "reason": run.get("failureReason") or run.get("failureDetails"), "stage": "UNKNOWN",
                                 "evidence": run.get("progressHistory", [])})
            elif run.get("svgValidation", {}).get("status") != "PASS":
                failures.append({"imageId": record.get("imageId"), "engine": method, "failureType": "SVG_VALIDATION_FAILURE",
                                 "reason": run.get("svgValidation", {}).get("checks"), "stage": "SVG_COMPOSITION_OR_VALIDATION",
                                 "confidence": "high", "svgPath": run.get("svgPath")})
        if record.get("status") != "PASS" and failed_engine_count == 0:
            failures.append({"imageId": record.get("imageId"), "sourceSha256": record.get("sourceSha256"),
                             "failureType": record.get("failureType") or "IMAGE_WORKER_FAILURE",
                             "reason": record.get("failureReason"), "stage": "UNKNOWN",
                             "evidence": record.get("stdoutLog") or record.get("stderrLog")})
    return failures


def build_stage_analysis(records: list[dict[str, Any]]) -> dict[str, Any]:
    items = []
    for record in records:
        for method, run in (record.get("engines") or {}).items():
            if run.get("status") != "SUCCEEDED":
                failure_text = f"{run.get('failureCode') or ''} {run.get('failureReason') or ''}".casefold()
                if "geometry" in failure_text or "bézier" in failure_text or "bezier" in failure_text:
                    first_stage, confidence = "GEOMETRY_FITTING", "high"
                elif "segment" in failure_text or "region" in failure_text:
                    first_stage, confidence = "REGION_SEGMENTATION", "medium"
                elif "svg" in failure_text or "compose" in failure_text:
                    first_stage, confidence = "SVG_COMPOSITION_OR_VALIDATION", "medium"
                else:
                    first_stage, confidence = "UNKNOWN", "low"
                items.append({"imageId": record.get("imageId"), "engine": method, "firstFailingStage": first_stage,
                              "confidence": confidence, "status": "job_failed_before_validated_render",
                              "evidence": {"failureCode": run.get("failureCode"), "progressHistory": run.get("progressHistory", []), "failureReason": run.get("failureReason")}})
                continue
            quality = run.get("qualityMetrics", {})
            details = quality.get("details", {})
            geometry = quality.get("geometry", {})
            stage_evidence = run.get("debugArtifactFiles", [])
            items.append({
                "imageId": record.get("imageId"), "engine": method,
                "firstFailingStage": "UNKNOWN",
                "confidence": "low",
                "status": "raster_reference_comparison; stage attribution requires inspection of saved stage artifacts or annotated ground truth",
                "evidence": {
                    "analyticDetailMacroRecall": details.get("macroFeatureRecall"),
                    "geometryIoU": geometry.get("foregroundIoU"),
                    "stageArtifactCount": len(stage_evidence),
                    "stageArtifactPaths": stage_evidence,
                    "phaseTimingsMs": (run.get("actualConfiguration") or {}).get("phaseTimingsMs", {}),
                },
                "limitation": "A final-render mismatch alone does not establish the earliest responsible phase. No stage is assigned without source-versus-intermediate evidence.",
            })
    return {"schemaVersion": 1, "items": items,
            "status": "partial" if any(row["firstFailingStage"] == "UNKNOWN" for row in items) else "complete",
            "summary": "Runner preserves phase diagnostics and reports candidate signals, but final-render aggregate metrics cannot prove causality. Human review and intermediate-stage comparisons remain required for first-failure attribution."}


def build_issue_ranking(summary: dict[str, Any], failures: list[dict[str, Any]], stage_analysis: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, dict[str, Any]] = {}
    for row in summary.get("perImage", []):
        for label in _defect_labels(row["engines"]["smart_reconstruction"], row["engines"]["contour_preserving"]):
            value = counts.setdefault(label, {"affectedImageIds": [], "engines": set(), "categories": set(), "severity": "P2", "evidence": []})
            value["affectedImageIds"].append(row["imageId"])
            value["engines"].add("smart_reconstruction" if label.startswith("SMART") else "contour_preserving")
            value["categories"].update(row.get("categories", []))
            value["evidence"].append(row.get("contactSheet"))
    for failure in failures:
        label = failure.get("failureType") or "ENGINE_RUN_FAILURE"
        value = counts.setdefault(label, {"affectedImageIds": [], "engines": set(), "categories": set(), "severity": "P0" if "SVG_VALIDATION" in label else "P1", "evidence": []})
        if failure.get("imageId") not in value["affectedImageIds"]:
            value["affectedImageIds"].append(failure.get("imageId"))
        value["engines"].add(failure.get("engine"))
        value["evidence"].append(failure.get("svgPath") or failure.get("reason"))
    ranked = []
    stage_by_item = {(row.get("imageId"), row.get("engine")): row for row in stage_analysis.get("items", [])}
    family_by_image = {row["imageId"]: row.get("sourceFamilyId") for row in summary.get("perImage", [])}
    source_type_by_image = {row["imageId"]: row.get("sourceType") for row in summary.get("perImage", [])}
    for index, (issue_id, value) in enumerate(sorted(counts.items(), key=lambda pair: (-len(set(pair[1]["affectedImageIds"])), pair[0])), 1):
        affected_ids = sorted(set(value["affectedImageIds"]))
        affected_families = {family_by_image.get(image_id) for image_id in affected_ids if family_by_image.get(image_id)}
        affected_real = {family_by_image.get(image_id) for image_id in affected_ids if str(source_type_by_image.get(image_id, "")).startswith("real_")}
        affected_synthetic = {family_by_image.get(image_id) for image_id in affected_ids if str(source_type_by_image.get(image_id, "")).startswith("synthetic_")}
        affected_engine_set = {item for item in value["engines"] if item}
        stage_rows = [stage_by_item.get((image_id, engine)) for image_id in affected_ids for engine in affected_engine_set]
        known_stages = {row.get("firstFailingStage") for row in stage_rows if row and row.get("firstFailingStage") != "UNKNOWN"}
        attributed_confidence = "high" if known_stages == {"GEOMETRY_FITTING"} else "medium" if len(known_stages) == 1 else "low_pending_stage_artifact_and_human_review"
        ranked.append({"issueId": f"Q{index:02d}_{issue_id.casefold()}", "issueType": issue_id,
                       "affectedEngines": sorted(item for item in value["engines"] if item),
                       "imageCategories": sorted(value["categories"]),
                       "affectedImageCount": len(set(value["affectedImageIds"])),
                       "affectedIndependentImageCount": len(affected_families),
                       "affectedRealSourceFamilyCount": len(affected_real),
                       "affectedSyntheticSourceFamilyCount": len(affected_synthetic),
                       "affectedImageIds": affected_ids,
                       "severity": value["severity"],
                       "visualImpact": "quantified by associated per-image metrics; not human-rated",
                       "firstFailingStage": next(iter(known_stages)) if len(known_stages) == 1 else "UNKNOWN",
                       "rootCauseConfidence": attributed_confidence,
                       "reproducibility": "repeatable for the pinned source/config if checkpoint rerun reproduces the same output hashes",
                       "exampleArtifacts": [path for path in value["evidence"] if path][:8],
                       "recommendedFix": "Investigate only after Task 08A evidence review; no algorithm changes are made here.",
                       "estimatedImplementationRisk": "unknown_until_root_cause_confirmed",
                       "regressionRisk": "unknown_until_root_cause_confirmed",
                       "suggestedTask08BScope": "Candidate investigation; do not implement in Task 08A"})
    return {"schemaVersion": 1, "issues": ranked[:3], "allObservedIssueCount": len(ranked),
            "selectionRule": "Top three by affected benchmark record count (not independent real image count); this is provisional because real coverage is insufficient.",
            "limitation": "Current records include synthetic analytical fixtures; they cannot establish real-world issue prevalence."}


def write_human_review_templates(records: list[dict[str, Any]], artifact_root: Path = ARTIFACTS) -> None:
    template = artifact_root / "human_review_template.csv"
    results = artifact_root / "human_review_results.csv"
    fields = ["image_id", "source_family_id", "engine", "contact_sheet", "roi_manifest", "shape_fidelity_1_5", "color_fidelity_1_5", "gradient_fidelity_1_5", "small_detail_fidelity_1_5", "typography_fidelity_1_5", "overall_fidelity_1_5", "defect", "severity", "suspected_first_failing_stage", "confidence", "reviewer_notes", "reviewer", "reviewed_at_utc"]
    artifact_root.mkdir(parents=True, exist_ok=True)
    with template.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for record in records:
            visuals = record.get("visualDiagnostics") or {}
            for engine in ("smart_reconstruction", "contour_preserving"):
                writer.writerow({"image_id": record.get("imageId"), "source_family_id": record.get("sourceFamilyId"),
                                 "engine": engine, "contact_sheet": visuals.get("contactSheet"),
                                 "roi_manifest": visuals.get("roiManifest")})
    if not results.exists():
        results.write_text(",".join(fields) + "\n", encoding="utf-8-sig")


def write_all_reports(records: list[dict[str, Any]], manifest: dict[str, Any], artifact_root: Path = ARTIFACTS) -> dict[str, Any]:
    summary = summarize_records(records, manifest)
    cross = build_cross_engine_comparison(summary)
    failures = build_failures(records)
    stages = build_stage_analysis(records)
    ranking = build_issue_ranking(summary, failures, stages)
    performance = {
        "schemaVersion": 1,
        "measurementScope": "per-engine API wall and root CPU time; sampled root+descendant simultaneous working set; Edge rasterization and SVG validation separately timed",
        "items": [{"imageId": row.get("imageId"), "engines": {engine: {key: value for key, value in run.items() if key in {"startCondition", "wallSeconds", "endToEndSeconds", "renderValidationSeconds", "edgeRenderSeconds", "skiaRenderSeconds", "cpuSecondsRootProcess", "memory", "renderMemory", "svgBytes", "svgPath"}} for engine, run in row.get("engines", {}).items()}} for row in records],
        "wpfMemory": {"status": "NOT_MEASURED", "reason": "No live WPF GUI process was attached to the backend-only reproducible API benchmark."},
    }
    write_json(artifact_root / "per_image_results.json", {"schemaVersion": 1, "items": records})
    write_json(artifact_root / "per_category_summary.json", {"schemaVersion": 1, "categories": summary["perCategory"]})
    write_json(artifact_root / "cross_engine_comparison.json", cross)
    write_json(artifact_root / "performance_summary.json", performance)
    write_json(artifact_root / "quality_metrics.json", {"schemaVersion": 1, "perImage": summary["perImage"], "perCategory": summary["perCategory"]})
    write_json(artifact_root / "svg_validation_results.json", [{"imageId": row.get("imageId"), "engine": engine, "validation": run.get("svgValidation")} for row in records for engine, run in row.get("engines", {}).items() if run.get("svgValidation")])
    write_json(artifact_root / "first_failing_stage_analysis.json", stages)
    write_json(artifact_root / "quality_issue_ranking.json", ranking)
    write_json(artifact_root / "benchmark_failures.json", failures)
    write_human_review_templates(records, artifact_root)
    validation_path = artifact_root / "dataset_validation.json"
    validation = json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.is_file() else {}
    run_manifest_path = artifact_root / "benchmark_run_manifest.json"
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8")) if run_manifest_path.is_file() else {}
    regression_path = artifact_root / "backend_regression.json"
    regression = json.loads(regression_path.read_text(encoding="utf-8")) if regression_path.is_file() else {}
    benchmark_tests_path = artifact_root / "benchmark_test_results.json"
    benchmark_tests = json.loads(benchmark_tests_path.read_text(encoding="utf-8")) if benchmark_tests_path.is_file() else {}
    successful = [run for row in records for run in (row.get("engines") or {}).values() if run.get("status") == "SUCCEEDED"]
    same_source_valid = bool(records) and all(
        row.get("sameAssetIdUsedByBothEngines") is True and
        set((row.get("engines") or {}).keys()) == {"smart_reconstruction", "contour_preserving"}
        for row in records
    )
    edge_render_valid = bool(successful) and all(Path(run.get("edgeRenderPath", "")).is_file() and run.get("svgValidation", {}).get("status") == "PASS" for run in successful)
    skia_checked = [run.get("skiaRendererCheck", {}).get("status") for run in successful]
    svg_render_valid = edge_render_valid and all(status in {"PASS", "NOT_AVAILABLE"} for status in skia_checked)
    geometry_metric_rows = [run.get("qualityMetrics", {}).get("geometry", {}) for run in successful]
    geometry_metrics_valid = bool(geometry_metric_rows) and all(
        (row.get("status") in {"analytic_ground_truth", "raster_reference_proxy", "unavailable_no_foreground_reference"})
        for row in geometry_metric_rows
    )
    color_metrics_valid = bool(successful) and all("meanDeltaE00" in (run.get("qualityMetrics", {}).get("color", {}).get("foregroundOrContent") or {}) for run in successful)
    detail_metrics_valid = any(record.get("sourceType", "").startswith("synthetic_") and run.get("qualityMetrics", {}).get("details", {}).get("referenceStatus") == "analytic_semantic_label_sidecar" for record in records for run in (record.get("engines") or {}).values())
    typography_valid = False  # OCR text/glyph ground truth is absent; output recognition telemetry is not a truth metric.
    performance_measured = bool(successful) and all(run.get("memory", {}).get("status") == "MEASURED" and run.get("cpuSecondsRootProcess") is not None for run in successful)
    production_unchanged = bool(run_manifest.get("productionSourcesUnchangedDuringRun")) and run_manifest.get("productionSourceSha256Before") == run_manifest.get("productionSourceSha256After")
    regression_pass = regression.get("status") == "PASS"
    benchmark_tests_pass = benchmark_tests.get("status") == "PASS"
    statuses = {
        "DATASET_MANIFEST_IMPLEMENTED": bool(manifest.get("items")),
        "DATASET_PROVENANCE_VALID": bool(validation.get("provenanceValid")),
        "DATASET_COVERAGE_SUFFICIENT": bool(validation.get("independentRealImageCount", 0) >= 24 and all(row.get("coverageSufficient") for row in validation.get("categoryCoverage", {}).values())),
        "INDEPENDENT_REAL_IMAGE_COUNT": int(validation.get("independentRealImageCount", 0)),
        "BENCHMARK_RUNNER_IMPLEMENTED": True,
        "SAME_SOURCE_COMPARISON_VALID": same_source_valid,
        "SVG_RENDER_COMPARISON_VALID": svg_render_valid,
        "GEOMETRY_METRICS_VALID": geometry_metrics_valid,
        "COLOR_METRICS_VALID": color_metrics_valid,
        "DETAIL_METRICS_VALID": detail_metrics_valid,
        "TYPOGRAPHY_METRICS_VALID": typography_valid,
        "PERFORMANCE_MEASURED": performance_measured,
        "HUMAN_VISUAL_REVIEW_COMPLETE": False,
        "MULTI_IMAGE_EVALUATION_COMPLETE": False,
        "FIRST_FAILING_STAGES_IDENTIFIED": "partial" if stages["status"] == "partial" else True,
        "QUALITY_ISSUES_PRIORITIZED": bool(ranking.get("issues") is not None),
        "SMART_V2_UNCHANGED": production_unchanged,
        "CONTOUR_DEFAULT_UNCHANGED": production_unchanged,
        "FULL_REGRESSION_PASS": regression_pass,
        "BENCHMARK_TESTS_PASS": benchmark_tests_pass,
        "TASK_08A_INFRASTRUCTURE_COMPLETE": bool(validation.get("provenanceValid") and records and same_source_valid and svg_render_valid and geometry_metrics_valid and color_metrics_valid and benchmark_tests_pass and regression_pass and production_unchanged),
        "TASK_08A_EVALUATION_COMPLETE": False,
        "TASK_08B_READY": False,
        "PRODUCTION_RELEASE_READY": False,
    }
    write_json(artifact_root / "task_08a_acceptance_status.json", statuses)
    write_task_report(records, summary, ranking, failures, stages, validation, run_manifest, statuses, artifact_root)
    return {"summary": summary, "cross": cross, "failures": failures, "stages": stages, "ranking": ranking, "performance": performance}


def write_task_report(records: list[dict[str, Any]], summary: dict[str, Any], ranking: dict[str, Any], failures: list[dict[str, Any]],
                      stages: dict[str, Any], validation: dict[str, Any], run_manifest: dict[str, Any],
                      statuses: dict[str, Any], artifact_root: Path) -> None:
    lines = [
        "# MediaStudio Vectorization — Task 08A Benchmark & Failure Analysis",
        "",
        "## Scope and guardrails",
        "",
        "This task adds local dataset management, API-level Smart Reconstruction V2 vs Contour-Preserving benchmarking, SVG validation/render comparison, metrics, performance sampling, ROI localization, reporting, and tests. It does not change either vectorization algorithm or production default. The Contour opt-in is enabled only in benchmark worker processes.",
        "",
        f"Run ID: `{run_manifest.get('runId', 'not recorded')}`. Result records in this report: **{len(records)}**. Human review remains pending.",
        "",
        "## Dataset and coverage",
        "",
        f"- Real independent source families: **{validation.get('independentRealImageCount', 0)}**. ACTIVE FOX native and upscaled variants remain in the same family.",
        f"- Synthetic analytical fixture variants: **{validation.get('syntheticFixtureCount', 0)}**. These do not count toward real-image coverage.",
        f"- Manifest variants: **{validation.get('imageVariantCount', 0)}**; source families: **{validation.get('sourceFamilyCount', 0)}**.",
        f"- Provenance/hash/split validation: **{validation.get('status', 'not run')}**; split lock matches manifest: **{validation.get('splitLockMatchesManifest', False)}**.",
        f"- License caveat: {validation.get('licenseCaveat', 'not recorded')}",
        "- Per-category real coverage: " + "; ".join(f"`{name}` {row.get('independentRealSourceFamilyCount', 0)}/{row.get('targetIndependentRealFamilies', 4)}" for name, row in validation.get("categoryCoverage", {}).items()),
        "- Coverage is insufficient for conclusions about general real-world performance; the 18 synthetic fixtures are analytical measurement checks only.",
        "",
        "## Method and reproducibility",
        "",
        "- Each image is uploaded once, then processed sequentially by both API routes using the same `assetId` and request values: `engine=auto`, `mode=auto`, outlined text, transparent background, automatic colors/simplification, smooth paths.",
        "- The runner checks actual engine identity and Smart V2 pipeline metadata; it never accepts a silent method substitution.",
        "- Render comparison uses the existing Edge/Chromium renderer on a shared canvas capped at a 1600 px long edge. Svg.Skia is a secondary render check when the local diagnostics binary is present.",
        "- SVGs are saved per image and engine; API/job identity, source and SVG hashes, phase timings, warnings, dimensions, complexity, render validity, runtime, CPU, and sampled process-tree working set are recorded.",
        "- Resume only skips a successful image when run ID, source hash, SVG hashes, and render files still match.",
        "- The existing Smart V2 debug writer was left disabled because it can fail on simple inputs when it assumes an `R04_reference.png` diagnostic exists. This benchmark records API phase timings instead; the debug hook was not modified.",
        "- RSS reports are sampled every 0.2 seconds as root plus live descendants at the same timestamp. Brief child peaks may be missed. WPF GUI memory was not measured.",
        "",
        "## Per-image cross-engine results",
        "",
        "`ΔE00` and SSIM are raster-reference measures; geometry masks and semantic detail scores are ground truth only where the manifest has analytic/source-alpha references. `Inconclusive` means no human preference is recorded.",
        "",
        "| Image | Evidence | Group(s) | Smart IoU | Contour IoU | Smart mean ΔE00 | Contour mean ΔE00 | Smart detail recall | Contour detail recall | Smart sec | Contour sec | Preference |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in summary.get("perImage", []):
        smart, contour = row["engines"]["smart_reconstruction"], row["engines"]["contour_preserving"]
        def fmt(value: Any, digits: int = 3) -> str:
            return "—" if value is None else f"{float(value):.{digits}f}"
        lines.append(f"| {row['imageId']} | {row.get('sourceType')} | {', '.join(row.get('categories', []))} | {fmt(smart.get('geometryIoU'))} | {fmt(contour.get('geometryIoU'))} | {fmt(smart.get('meanDeltaE00'))} | {fmt(contour.get('meanDeltaE00'))} | {fmt(smart.get('analyticDetailMacroRecall'))} | {fmt(contour.get('analyticDetailMacroRecall'))} | {fmt(smart.get('wallSeconds'))} | {fmt(contour.get('wallSeconds'))} | inconclusive |")
    lines += ["", "## Category summaries (evidence types kept separate)", "", "Metrics below are medians and are descriptive; synthetic and real raster evidence are not combined.", ""]
    for category, values in summary.get("perCategory", {}).items():
        lines += [f"### {category}", "", "| Evidence type | Families | Images | Engine | IoU median | ΔE00 median | SSIM median | Detail recall median | Runtime median (s) |", "|---|---:|---:|---|---:|---:|---:|---:|---:|"]
        for evidence_type, evidence in values.get("byEvidenceType", {}).items():
            for method in ("smart_reconstruction", "contour_preserving"):
                engine = evidence.get(method, {})
                lines.append(f"| {evidence_type} | {evidence.get('independentSourceFamilyCount', 0)} | {evidence.get('imageVariantCount', 0)} | {method} | {engine.get('median_geometryIoU')} | {engine.get('median_meanDeltaE00')} | {engine.get('median_maskedSsim')} | {engine.get('median_analyticDetailMacroRecall')} | {engine.get('median_wallSeconds')} |")
        lines.append("")
    lines += [
        "## Failure and first-stage analysis",
        "",
        f"Structured engine/SVG failures: **{len(failures)}**. First-stage attribution status: **{stages.get('status', 'partial')}**.",
        "",
        "A final-render metric does not prove which upstream phase first introduced an error. Smart V2 exposes phase timings in the API but intentionally has its debug writer disabled for this run; Contour supplies phase summaries in API metadata. Stage labels remain `UNKNOWN` unless a specific source/intermediate comparison proves causality. Synthetic analytic masks help score final geometry/details, not automatically assign the responsible phase.",
        "",
    ]
    if failures:
        lines += ["| Image | Engine | Failure type | Reason |", "|---|---|---|---|"]
        for failure in failures:
            reason = str(failure.get("reason", "")).replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {failure.get('imageId')} | {', '.join(failure.get('engines', [])) or failure.get('engine')} | {failure.get('issueType', failure.get('failureType'))} | {reason[:300]} |")
        lines.append("")
    lines += [
        "## Task 08B recommendations (provisional, evidence-limited)",
        "",
        "The ranking below prioritizes observed benchmark issues, not a claim of real-world prevalence. Review per-image SVGs, contact sheets, ROI crops, and structured failures before selecting a production fix.",
        "",
    ]
    if ranking.get("issues"):
        lines += ["| Rank | Issue | Engine(s) | Affected families (real / synthetic) | Severity | Evidence |", "|---:|---|---|---:|---|---|"]
        for index, issue in enumerate(ranking["issues"], 1):
            lines.append(f"| {index} | {issue['issueType']} | {', '.join(issue['affectedEngines'])} | {issue['affectedRealSourceFamilyCount']} / {issue['affectedSyntheticSourceFamilyCount']} | {issue['severity']} | {', '.join(issue['affectedImageIds'])} |")
        lines.append("")
    else:
        lines += ["No ranked issue crossed the current automated flags. This is not evidence of engine perfection; coverage and manual review are insufficient.", ""]
    lines += [
        "For any Task 08B proposal: first confirm the implicated stage with a source/intermediate crop; constrain the edit to that module; retain current API defaults; and rerun both analytical fixtures and a newly supplied independent real image from the affected category. No Task 08B implementation is included.",
        "",
        "## Human review package",
        "",
        "Contact sheets use `SOURCE | SMART V2 | CONTOUR | MAX SOURCE ΔE00`. ROI folders contain source/output crops, color heatmaps, boundary overlays, local SSIM, ΔE00, boundary displacement, alpha, and gradient metrics. Review rows are blank in `human_review_template.csv`; no human scores were fabricated.",
        "",
        "## Regression and final status",
        "",
        f"Backend regression: **{statuses.get('FULL_REGRESSION_PASS')}** (see `backend_regression.json`). Benchmark tests: **{statuses.get('BENCHMARK_TESTS_PASS')}** (see `benchmark_test_results.json`). Production source hashes unchanged during run: **{statuses.get('SMART_V2_UNCHANGED')} / {statuses.get('CONTOUR_DEFAULT_UNCHANGED')}**.",
        "",
        "```text",
    ]
    lines += [f"{key} = {str(value).lower() if isinstance(value, bool) else value}" for key, value in statuses.items()]
    lines += ["```", "", "## Artifact map", "",
              "- Dataset: `benchmark_manifest.json`, `dataset_inventory.json`, `dataset_coverage.json`, `dataset_split.json`, `dataset_validation.json`.",
              "- Results: `per_image_results.json`, `per_category_summary.json`, `cross_engine_comparison.json`, `performance_summary.json`, `quality_metrics.json`, `svg_validation_results.json`.",
              "- Visuals: `contact_sheets/`, `source_vs_smart_vs_contour/`, `color_error_heatmaps/`, `boundary_overlays/`, `detail_crops/`, `alpha_comparisons/`.",
              "- Triage: `first_failing_stage_analysis.json`, `quality_issue_ranking.json`, `benchmark_failures.json`, `human_review_template.csv`.",
              "- Reproduction: `benchmark_run_manifest.json`, `logs/`, `outputs/`, `backend_regression.json`, `benchmark_test_results.json`.", ""]
    (artifact_root / "task_08a_report.md").write_text("\n".join(lines), encoding="utf-8")

