from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .dataset import ARTIFACTS, MANIFEST, write_json
from .review import load_records

DEFECTS = {"MISSING_STRUCTURAL_DETAIL", "INCORRECT_INTERNAL_REGION", "HARD_BOUNDARY_MISMATCH",
           "FALSE_HARD_BOUNDARY", "GRADIENT_FRAGMENTATION", "GRADIENT_COLOR_MISMATCH",
           "THIN_FEATURE_LOSS", "EDGE_STAIRCASE", "CORNER_ROUNDING_ERROR",
           "TEXT_GLYPH_DISTORTION", "TEXT_SPACING_ERROR", "ALPHA_HALO",
           "LAYER_OCCLUSION_ERROR", "SVG_RENDERER_MISMATCH", "SOURCE_LIMITATION", "UNKNOWN"}


def _labels(roi: dict[str, Any]) -> list[str]:
    m = roi.get("metrics", {})
    labels = []
    if m.get("meanDeltaE00", 0) >= 5 or m.get("p95DeltaE00", 0) >= 20:
        labels.append("GRADIENT_COLOR_MISMATCH")
    if m.get("edgeMismatchFraction", 0) >= 0.08 or m.get("p95BoundaryDisplacementPx", 0) >= 2.5:
        labels.append("HARD_BOUNDARY_MISMATCH")
    if m.get("alphaMismatchMean", 0) >= 24:
        labels.append("THIN_FEATURE_LOSS" if m.get("sourceGradientMean", 0) > 32 else "ALPHA_HALO")
    if not labels:
        labels.append("UNKNOWN")
    return labels


def _failure_class(code: str, reason: str) -> str:
    text = (code + " " + reason).casefold()
    if "thin_feature_coverage_low" in text or "contour_geometry_invalid" in text:
        return "CONTOUR_GEOMETRY_INVALID"
    if "geosexception" in text or "topologyexception" in text:
        return "GEOS_TOPOLOGY_EXCEPTION"
    if ("render_empty" in text or "no visible vector" in text or "empty or at an unexpected size" in text
            or "không tạo được ảnh vector nhìn thấy" in text):
        return "EMPTY_VISIBLE_SVG_OUTPUT"
    if "svg" in text and ("malformed" in text or "validation" in text):
        return "SVG_VALIDATION_OR_RENDER_FAILURE"
    return code or "ENGINE_RUN_FAILURE"


def build_defects() -> dict[str, Any]:
    records = load_records()
    visual = []
    engine_failures = []
    dedupe: dict[str, dict[str, Any]] = {}
    failure_groups: dict[str, dict[str, Any]] = {}
    for record in records:
        image_id = record.get("imageId")
        family = record.get("sourceFamilyId")
        # One underlying geometry validator failure is kept once, even if API status also calls it an engine failure.
        for engine, run in record.get("engines", {}).items():
            if run.get("status") in {"FAILED", "FAIL"}:
                code = run.get("failureCode") or run.get("failureType") or "ENGINE_RUN_FAILURE"
                reason = str(run.get("failureReason") or run.get("failureDetails") or "")
                failure_class = _failure_class(str(code), reason)
                key = f"{engine}:{image_id}:{failure_class}"
                history = run.get("progressHistory", [])
                last_stage = history[-1].get("stage") if history else None
                stage_confidence = "PROBABLE" if last_stage and ("Phase D1" in last_stage or "SVG" in last_stage) and failure_class in {"GEOS_TOPOLOGY_EXCEPTION", "EMPTY_VISIBLE_SVG_OUTPUT"} else "UNKNOWN"
                issue = dedupe.setdefault(key, {"defectId": "ENG-" + str(len(dedupe) + 1).zfill(3),
                    "rootIssueKey": key, "engine": engine, "imageIds": [], "sourceFamilyIds": [],
                    "failureTypes": [], "failureClass": failure_class, "evidence": [], "firstFailingStage": last_stage or "UNKNOWN", "confidence": stage_confidence})
                if image_id not in issue["imageIds"]: issue["imageIds"].append(image_id)
                if family and family not in issue["sourceFamilyIds"]: issue["sourceFamilyIds"].append(family)
                if code not in issue["failureTypes"]: issue["failureTypes"].append(code)
                issue["evidence"].append({"failureCode": code, "failureReason": reason,
                                          "failureDetails": run.get("failureDetails"),
                                          "progressHistory": run.get("progressHistory", [])})
                group_key = f"{engine}:{failure_class}"
                group = failure_groups.setdefault(group_key, {"engine": engine, "failureClass": failure_class,
                    "affectedImageIds": [], "affectedSourceFamilies": set(), "evidence": [],
                    "firstFailingStage": "UNKNOWN", "confidence": "UNKNOWN"})
                if image_id not in group["affectedImageIds"]: group["affectedImageIds"].append(image_id)
                if family: group["affectedSourceFamilies"].add(family)
                group["evidence"].append({"imageId": image_id, "reason": reason, "progressLastStage": last_stage})
                if stage_confidence == "PROBABLE": group["firstFailingStage"] = last_stage; group["confidence"] = "PROBABLE"
            validation = run.get("svgValidation", {})
            if validation.get("status") == "FAIL":
                key = f"{engine}:{image_id}:SVG_VALIDATION_FAILURE"
                dedupe[key] = {"defectId": "ENG-" + str(len(dedupe) + 1).zfill(3), "rootIssueKey": key,
                    "engine": engine, "imageIds": [image_id], "sourceFamilyIds": [family] if family else [],
                    "failureTypes": ["SVG_VALIDATION_FAILURE"], "evidence": [validation],
                    "firstFailingStage": "svg_validation", "confidence": "VERIFIED"}
        for roi_index, roi in enumerate(record.get("visualDiagnostics", {}).get("rois", [])):
            labels = _labels(roi)
            visual.append({"defectId": f"VIS-{len(visual)+1:04d}", "issueKey": "+".join(labels),
                "engine": roi.get("engine", "unknown"), "imageId": image_id, "sourceFamilyId": family,
                "categories": record.get("categories", []), "roiIndex": roi_index,
                "roiCoordinates": roi.get("bboxPx"), "candidateLabels": labels, "reviewStatus": "pending_human_review",
                "severity": "provisional_high" if roi.get("combinedRiskScore", 0) >= 0.25 else "provisional_medium" if roi.get("combinedRiskScore", 0) >= 0.1 else "provisional_low",
                "visualImpactScore": roi.get("combinedRiskScore"), "metricEvidence": roi.get("metrics", {}),
                "firstSuspectedPhase": "UNKNOWN", "rootCauseConfidence": "UNKNOWN",
                "reviewerNote": "Machine-localized candidate; category/severity require human review.",
                "assets": {key: roi.get(key) for key in ("sourceCrop", "smartRenderCrop", "contourRenderCrop", "differenceHeatmap", "smartBoundaryOverlay", "contourBoundaryOverlay")}})
    issue_rows = list(dedupe.values())
    visual_groups: dict[str, dict[str, Any]] = {}
    for item in visual:
        key = item["issueKey"] + ":" + item["engine"]
        row = visual_groups.setdefault(key, {"issueKey": item["issueKey"], "engine": item["engine"],
             "affectedImageIds": [], "affectedSourceFamilies": set(), "roiCount": 0,
             "provisionalSeverity": "provisional_low", "rootCauseConfidence": "UNKNOWN", "examples": []})
        if item["imageId"] not in row["affectedImageIds"]: row["affectedImageIds"].append(item["imageId"])
        if item["sourceFamilyId"]: row["affectedSourceFamilies"].add(item["sourceFamilyId"])
        row["roiCount"] += 1
        if item["severity"] == "provisional_high": row["provisionalSeverity"] = "provisional_high"
        elif item["severity"] == "provisional_medium" and row["provisionalSeverity"] == "provisional_low": row["provisionalSeverity"] = "provisional_medium"
        row["examples"].append({"imageId": item["imageId"], "roiIndex": item["roiIndex"], "roi": item["roiCoordinates"], "metricEvidence": item["metricEvidence"]})
    visual_ranking = []
    for row in visual_groups.values():
        row["affectedSourceFamilies"] = sorted(row["affectedSourceFamilies"])
        row["recurrence"] = "isolated" if len(row["affectedSourceFamilies"]) <= 1 else "recurring_in_dataset"
        row["rootCauseConfidence"] = "UNKNOWN"; row["firstFailingStage"] = "UNKNOWN"
        row["proposedModuleToInvestigate"] = "benchmark-localized; human/intermediate artifact review required"
        row["regressionRisk"] = "unknown until a targeted change is proposed"
        visual_ranking.append(row)
    visual_ranking.sort(key=lambda r: (-len(r["affectedSourceFamilies"]), -r["roiCount"], r["issueKey"]))
    engine_ranking = []
    for row in failure_groups.values():
        row["affectedSourceFamilies"] = sorted(row["affectedSourceFamilies"])
        row["severity"] = "P1" if row["failureClass"] in {"CONTOUR_GEOMETRY_INVALID", "EMPTY_VISIBLE_SVG_OUTPUT", "GEOS_TOPOLOGY_EXCEPTION"} else "P2"
        row["rootCauseConfidence"] = row.pop("confidence")
        row["recurrence"] = "isolated" if len(row["affectedSourceFamilies"]) <= 1 else "recurring_symptom_in_dataset"
        row["rootCauseNote"] = "Symptom group only; common root cause is unverified unless direct diagnostic evidence is attached."
        engine_ranking.append(row)
    engine_ranking.sort(key=lambda r: (r["severity"] != "P1", -len(r["affectedSourceFamilies"]), r["failureClass"]))
    write_json(ARTIFACTS / "visual_defects.json", {"schemaVersion": 1, "status": "pending_human_review", "allowedCategories": sorted(DEFECTS), "items": visual})
    write_json(ARTIFACTS / "visual_defect_ranking.json", {"ranking": visual_ranking, "severityIsProvisional": True,
        "syntheticAndRealEvidenceNotCombined": True, "generalizationClaim": False})
    write_json(ARTIFACTS / "engine_failures.json", {"items": issue_rows, "issueCount": len(issue_rows), "rankedSymptoms": engine_ranking,
        "deduplicationRule": "same engine + image + underlying geometry-validator code is one issue; wrapper/API failure is evidence, not separate root cause"})
    write_json(ARTIFACTS / "engine_failure_ranking.json", {"ranking": engine_ranking,
        "note": "Grouped by failure symptom and engine; grouping does not assert common root cause.", "syntheticAndRealEvidenceSeparate": True})
    write_json(ARTIFACTS / "issue_family_deduplication.json", {"engineRootIssueCount": len(issue_rows),
        "visualCandidateCount": len(visual), "note": "Visual candidates remain ROI-level; no human-confirmed root-cause merging."})
    return {"visualCandidateCount": len(visual), "visualRankedIssueCount": len(visual_ranking), "engineRootIssueCount": len(issue_rows),
            "engineRankedSymptomCount": len(engine_ranking),
            "humanReviewComplete": False}


def build_summaries() -> dict[str, Any]:
    records = load_records()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    families = {item["sourceFamilyId"] for item in manifest["items"] if item["sourceType"].startswith("real_")}
    synthetic = [item for item in manifest["items"] if item["sourceType"] == "synthetic_analytical_fixture"]
    per_image = []
    category_rows: dict[str, Any] = {}
    for record in records:
        engine_rows = {}
        for name, engine in record.get("engines", {}).items():
            qm = engine.get("qualityMetrics", {})
            engine_rows[name] = {"status": engine.get("status"), "runtimeSeconds": engine.get("wallSeconds"),
                "svgBytes": engine.get("svgBytes"), "pathCount": engine.get("pathCount"),
                "geometry": qm.get("geometry"), "color": qm.get("color"), "gradient": qm.get("gradient"),
                "typography": qm.get("typography"), "alpha": qm.get("transparency"),
                "rendererWarnings": engine.get("warnings", []),
                "groundTruthStatus": record.get("referenceType", "unknown")}
        per_image.append({"imageId": record.get("imageId"), "sourceFamilyId": record.get("sourceFamilyId"),
            "sourceType": record.get("sourceType"), "categories": record.get("categories", []),
            "inputDimensions": record.get("inputDimensions"), "status": record.get("status"), "engines": engine_rows,
            "roiCount": len(record.get("visualDiagnostics", {}).get("rois", [])), "humanReviewStatus": "pending"})
        for category in record.get("categories", []):
            cat = category_rows.setdefault(category, {"real": {"sourceFamilies": set(), "imageIds": []}, "synthetic": {"sourceFamilies": set(), "imageIds": []}})
            bucket = "synthetic" if str(record.get("sourceType", "")).startswith("synthetic") else "real"
            cat[bucket]["sourceFamilies"].add(record.get("sourceFamilyId")); cat[bucket]["imageIds"].append(record.get("imageId"))
    for cat in category_rows.values():
        for group in cat.values(): group["sourceFamilies"] = sorted(x for x in group["sourceFamilies"] if x)
    write_json(ARTIFACTS / "per_image_review_summary.json", {"items": per_image, "humanReviewComplete": False})
    write_json(ARTIFACTS / "per_category_quality_summary.json", {"categories": category_rows,
        "syntheticAndRealSeparated": True, "noPreferredEngine": True,
        "assessment": "descriptive only; no human preference or ground-truth vector for real inputs"})
    return {"realFamilies": len(families), "syntheticVariants": len(synthetic), "perImageCount": len(per_image), "categoryCount": len(category_rows)}
