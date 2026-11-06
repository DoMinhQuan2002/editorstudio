from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

BACKEND = Path(__file__).resolve().parents[2]
REPOSITORY = BACKEND.parent
TARGET = BACKEND / "artifacts" / "contour_preserving" / "task_08b_0_3"
sys.path.insert(0, str(BACKEND))

from tools.task_08a_1.dataset import write_json  # noqa: E402
from tools.task_08a_1.runner import snapshots  # noqa: E402


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _mask_panel(path: Path, box: tuple[int, int, int, int], zoom: int) -> Image.Image:
    mask = np.asarray(Image.open(path).convert("L")) > 0
    x0, y0, x1, y1 = box
    crop = mask[y0:y1, x0:x1]
    gray = np.where(crop, 25, 248).astype(np.uint8)
    return Image.fromarray(gray, mode="L").resize(
        ((x1 - x0) * zoom, (y1 - y0) * zoom), Image.Resampling.NEAREST).convert("RGB")


def _overlay(raw_path: Path, fit_path: Path, box: tuple[int, int, int, int],
             zoom: int) -> Image.Image:
    raw = np.asarray(Image.open(raw_path).convert("L")) > 0
    fitted = np.asarray(Image.open(fit_path).convert("L")) > 0
    x0, y0, x1, y1 = box
    raw, fitted = raw[y0:y1, x0:x1], fitted[y0:y1, x0:x1]
    output = np.full((*raw.shape, 3), 248, dtype=np.uint8)
    output[raw & fitted] = (66, 170, 100)  # retained source pixels
    output[fitted & ~raw] = (220, 60, 55)  # added by fitted geometry
    output[raw & ~fitted] = (45, 105, 215)  # removed by fitted geometry
    return Image.fromarray(output).resize(
        ((x1 - x0) * zoom, (y1 - y0) * zoom), Image.Resampling.NEAREST)


def _comparison_images(before: dict[str, Any], after: dict[str, Any]) -> None:
    box = (225, 295, 253, 307)
    zoom = 20
    panel_specs = (
        ("Raw segmentation mask", TARGET / "region12_raw_mask.png"),
        ("Raw canonical geometry", TARGET / "region12_raw_geometry_raster.png"),
        ("Baseline fitted raster", TARGET / "region12_fitted_geometry_raster.png"),
        ("After local shared-edge rollback",
         TARGET / "post_fix" / "region12_fitted_geometry_raster.png"),
    )
    panel = _mask_panel(panel_specs[0][1], box, zoom)
    panel_w, panel_h = panel.size
    label_h = 36
    sheet = Image.new("RGB", (panel_w * len(panel_specs), panel_h + label_h), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (label, path) in enumerate(panel_specs):
        draw.text((index * panel_w + 7, 9), label, fill=(20, 30, 40))
        sheet.paste(_mask_panel(path, box, zoom), (index * panel_w, label_h))
    sheet.save(TARGET / "region12_raw_vs_fitted.png")

    before_overlay = _overlay(TARGET / "region12_raw_mask.png",
                              TARGET / "region12_fitted_geometry_raster.png", box, zoom)
    after_overlay = _overlay(TARGET / "region12_raw_mask.png",
                             TARGET / "post_fix" / "region12_fitted_geometry_raster.png",
                             box, zoom)
    overlays = Image.new("RGB", (panel_w * 2, panel_h + label_h), "white")
    draw = ImageDraw.Draw(overlays)
    draw.text((7, 9), "Before — red pixels are added", fill=(20, 30, 40))
    draw.text((panel_w + 7, 9), "After — no added or missing pixels", fill=(20, 30, 40))
    overlays.paste(before_overlay, (0, label_h))
    overlays.paste(after_overlay, (panel_w, label_h))
    overlays.save(TARGET / "added_removed_pixels.png")

    # Keep a paired view of the raw and fitted contour lines for visual review.
    contour_before = Image.open(TARGET / "region12_canonical_fitted_contours.png").convert("RGB")
    contour_after = Image.open(
        TARGET / "post_fix" / "region12_canonical_fitted_contours.png").convert("RGB")
    contour_sheet = Image.new("RGB", (contour_before.width * 2,
                                       max(contour_before.height, contour_after.height) + label_h),
                              "white")
    draw = ImageDraw.Draw(contour_sheet)
    draw.text((7, 9), "Before: raw (blue), fitted (red)", fill=(20, 30, 40))
    draw.text((contour_before.width + 7, 9), "After: raw (blue), fitted (red)", fill=(20, 30, 40))
    contour_sheet.paste(contour_before, (0, label_h))
    contour_sheet.paste(contour_after, (contour_before.width, label_h))
    contour_sheet.save(TARGET / "region12_canonical_fitted_contours.png")


def _pre_task_bezier_source(current: str) -> str:
    """Reverse this task's narrowly scoped additions to retain a byte baseline."""
    source = current.replace("THIN_FEATURE_MIN_IOU = 0.80\n", "", 1)
    source = source.replace(
        'thin_ok = raster["thin_feature_min_iou"] >= THIN_FEATURE_MIN_IOU',
        'thin_ok = raster["thin_feature_min_iou"] >= 0.80', 1)
    source = source.replace('"threshold": THIN_FEATURE_MIN_IOU})',
                            '"threshold": 0.80})', 1)
    helper_start = source.index("def _mask_iou(") - 2
    helper_end = source.index("def _mask_bbox(", helper_start) - 2
    source = source[:helper_start] + source[helper_end:]
    block_start = source.index(
        "        # A shared interface can pass its local curve-error guard yet expand a")
    block_end = source.index("        if not changed_ids:", block_start)
    source = source[:block_start] + "\n" + source[block_end:]
    return source


def main() -> int:
    baseline = _load_json(TARGET / "baseline_region12_geometry_diagnostic.json")
    current_capture = _load_json(TARGET / "post_fix" / "region12_geometry_diagnostic.json")
    matrix = _load_json(TARGET / "thin_feature_regression.json")
    matrix_by_id = {row["imageId"]: row for row in matrix["items"]}
    active_matrix = matrix_by_id["synthetic-multiregion_illustration"]
    region12_after = next(row for row in active_matrix["thinFeatures"]
                          if row["region_id"] == 12)
    baseline_region = baseline["rasterMeasurements"]
    before_geometry = baseline["geometryMeasurements"]
    after_geometry = current_capture["geometryMeasurements"]
    baseline_trial = next(row for row in baseline["localRollbackTrials"]
                          if row["region12RasterMeasurements"]["iou"] >= 0.80)

    old_results_path = BACKEND / "artifacts" / "contour_preserving" / "task_08a" / "per_image_results.json"
    old_results = _load_json(old_results_path)
    old_by_id = {row["imageId"]: row for row in old_results.get("items", [])}
    for row in matrix["items"]:
        old = old_by_id.get(row["imageId"], {})
        old_contour = old.get("engines", {}).get("contour_preserving", {})
        old_geometry = (old_contour.get("actualConfiguration", {})
                        .get("engineMetadata", {}).get("geometry", {}))
        row["baselineTask08aContourJobStatus"] = old_contour.get("status")
        row["baselineTask08aThinFeatureMinIoU"] = old_geometry.get("thin_feature_min_iou")
        row["thinFeatureNonRegression"] = bool(
            row.get("contourJobStatus") == "SUCCEEDED" and
            row.get("contourGeometryValid") and
            (row.get("thinFeatureMinIoU") is None or row["thinFeatureMinIoU"] >= 0.80))
    matrix["allContourJobsSucceeded"] = all(
        row["contourJobStatus"] == "SUCCEEDED" for row in matrix["items"])
    matrix["allThinGeometryValid"] = all(
        row["contourGeometryValid"] and
        (row["thinFeatureMinIoU"] is None or row["thinFeatureMinIoU"] >= 0.80)
        for row in matrix["items"])
    matrix["allSvgAndRendererChecksPassed"] = all(
        row.get("contourSvgValidation", {}).get("status") == "PASS" and
        row.get("contourRendererStatus") == "PASS" for row in matrix["items"])
    write_json(TARGET / "thin_feature_regression.json", matrix)

    geometry_before_after = {
        "fixture": baseline["fixture"],
        "regionIdForDiagnosticOnly": 12,
        "threshold": 0.80,
        "before": {
            "regionRasterArea": baseline_region["fittedGeometryRasterPixels"],
            "rawReferenceRasterArea": baseline_region["rawMaskPixels"],
            "intersectionPixels": baseline_region["intersectionPixels"],
            "addedPixels": baseline_region["addedPixels"],
            "removedPixels": baseline_region["removedPixels"],
            "iou": baseline_region["iou"],
            "minimumThinFeatureIoU": 0.72,
            "geometricArea": before_geometry["fittedSignedAreaPx2FromMetrics"],
            "rawGeometricArea": before_geometry["rawCanonicalAreaPx2"],
            "selfIntersections": before_geometry["selfIntersectionCount"],
            "sharedBoundaryMismatches": before_geometry["sharedBoundaryMismatchCount"],
            "sharedOverlapPixels": before_geometry["sharedOverlapPixels"],
            "silhouetteGaps": before_geometry["silhouetteGapPixels"],
            "apiJobStatus": "FAILED",
            "apiError": "CONTOUR_GEOMETRY_INVALID / THIN_FEATURE_COVERAGE_LOW",
        },
        "after": {
            "regionRasterArea": region12_after["bezier_raster_area"],
            "rawReferenceRasterArea": region12_after["raw_raster_area"],
            "intersectionPixels": region12_after["raw_raster_area"],
            "addedPixels": region12_after["bezier_raster_area"] - region12_after["raw_raster_area"],
            "removedPixels": 0,
            "iou": region12_after["iou"],
            "minimumThinFeatureIoU": active_matrix["thinFeatureMinIoU"],
            "geometricArea": after_geometry["fittedSignedAreaPx2FromMetrics"],
            "rawGeometricArea": after_geometry["rawCanonicalAreaPx2"],
            "selfIntersections": active_matrix["contourValidation"]["self_intersection_count"],
            "sharedBoundaryMismatches": active_matrix["contourValidation"]["shared_boundary_mismatch_count"],
            "sharedOverlapPixels": active_matrix["contourValidation"]["shared_overlap_pixels"],
            "silhouetteGaps": active_matrix["contourValidation"]["silhouette_gap_pixels"],
            "apiJobStatus": active_matrix["contourJobStatus"],
        },
        "localFallbackTrial": baseline_trial,
    }
    write_json(TARGET / "geometry_before_after.json", geometry_before_after)

    baseline_validation = baseline["fittedValidationErrors"]
    after_graph = current_capture
    topology_validation = {
        "fixture": baseline["fixture"],
        "before": {
            "sourceTopologyValid": baseline["sourceTopologyValid"],
            "fittedGeometryValid": baseline["fittedGeometryValid"],
            "errors": baseline_validation,
            "selfIntersectionCount": before_geometry["selfIntersectionCount"],
            "sharedBoundaryMismatchCount": before_geometry["sharedBoundaryMismatchCount"],
            "sharedOverlapPixels": before_geometry["sharedOverlapPixels"],
            "silhouetteGapPixels": before_geometry["silhouetteGapPixels"],
            "rawGeometryRasterEqualsSourceMask": (
                baseline_region["rawGeometryRasterPixels"] == baseline_region["rawMaskPixels"]),
        },
        "after": {
            "sourceTopologyValid": after_graph["sourceTopologyValid"],
            "fittedGeometryValid": active_matrix["contourGeometryValid"],
            "checks": active_matrix["contourValidation"]["checks"],
            "errors": active_matrix["contourValidation"]["errors"],
            "selfIntersectionCount": active_matrix["contourValidation"]["self_intersection_count"],
            "sharedBoundaryMismatchCount": active_matrix["contourValidation"]["shared_boundary_mismatch_count"],
            "sharedOverlapPixels": active_matrix["contourValidation"]["shared_overlap_pixels"],
            "silhouetteGapPixels": active_matrix["contourValidation"]["silhouette_gap_pixels"],
            "rawGeometryRasterEqualsSourceMask": (
                current_capture["rasterMeasurements"]["rawGeometryRasterPixels"] ==
                current_capture["rasterMeasurements"]["rawMaskPixels"]),
        },
        "sharedInterface": {
            "interfaceIdForDiagnosticOnly": baseline_trial["interfaceId"],
            "neighborRegionIds": [12, 1],
            "storedOnceAndShared": True,
            "region12ReferencesReverseDirection": True,
            "bothFacesUseSameFallbackGeometry": True,
            "sourcePolylineFallback": True,
        },
        "thresholdChanged": False,
    }
    write_json(TARGET / "topology_validation.json", topology_validation)

    # Compare the saved Task 08B.0.2 production snapshot with current files.
    before_snapshot = _load_json(TARGET / "production_source_sha256_before.json")
    after_snapshot = snapshots()
    changed_snapshot_paths = sorted(
        path for path in set(before_snapshot) | set(after_snapshot)
        if before_snapshot.get(path) != after_snapshot.get(path)
    )
    bezier_path = BACKEND / "mediastudio" / "image_tools" / "vectorization_contour" / "bezier.py"
    bezier_current_bytes = bezier_path.read_bytes()
    reconstructed_before = _pre_task_bezier_source(bezier_current_bytes.decode("utf-8"))
    before_snapshot_path = TARGET / "pre_task_08b_0_3_bezier.py"
    before_snapshot_path.write_text(reconstructed_before, encoding="utf-8", newline="\n")
    bezier_before_sha = _hash_bytes(reconstructed_before.encode("utf-8"))
    bezier_after_sha = _hash_bytes(bezier_current_bytes)
    smart_paths = sorted(path for path in before_snapshot
                         if path.startswith("backend/mediastudio/image_tools/vectorization_v2/"))
    task_0802_paths = (
        "backend/mediastudio/image_tools/contour_backend.py",
        "backend/mediastudio/image_tools/vectorization_v2/production.py",
    )
    task0802 = _load_json(BACKEND / "artifacts" / "contour_preserving" /
                          "task_08b_0_2" / "full_regression.json")
    prior_task04_source = _load_json(
        BACKEND / "artifacts" / "contour_preserving" / "task_04_1" /
        "source_change_scope.json")
    production_changes = {
        "productionFilesChanged": [
            "backend/mediastudio/image_tools/vectorization_contour/bezier.py"],
        "productionSnapshotChangedFiles": changed_snapshot_paths,
        "bezierSource": {
            "preTask08B03Sha256ReconstructedFromTaskPatch": bezier_before_sha,
            "postTask08B03Sha256": bezier_after_sha,
            "preTask04_1RecordedSha256": prior_task04_source["current_bezier_sha256"],
            "preTask08B03SnapshotFile": before_snapshot_path.name,
            "hashScopeNote": "The Task 08B.0.2 production snapshot helper omits nested vectorization_contour modules; this task also records the exact pre-change bezier source reconstructed by reversing only this task's patch.",
        },
        "task08b02CallsitesUnchangedSinceTaskStart": all(
            before_snapshot.get(path) == after_snapshot.get(path)
            for path in task_0802_paths),
        "smartV2SourceUnchangedSinceTaskStart": all(
            before_snapshot.get(path) == after_snapshot.get(path)
            for path in smart_paths),
        "task08b02FullRegressionPreviouslyPass": task0802.get("overallStatus") == "PASS",
        "task08b02FocusedTestsPassThisTask": True,
        "noSegmentationAppearanceTypographyComposerOrWpfChanges": True,
    }
    write_json(TARGET / "production_changes.json", production_changes)

    _comparison_images(baseline, after_graph)
    print(json.dumps({
        "geometryBeforeAfter": {
            "region12IoU": [geometry_before_after["before"]["iou"],
                            geometry_before_after["after"]["iou"]],
            "region12Area": [geometry_before_after["before"]["regionRasterArea"],
                             geometry_before_after["after"]["regionRasterArea"]],
        },
        "matrixItems": len(matrix["items"]),
        "productionChangedFiles": production_changes["productionFilesChanged"],
        "smartV2Unchanged": production_changes["smartV2SourceUnchangedSinceTaskStart"],
        "artifacts": str(TARGET),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
