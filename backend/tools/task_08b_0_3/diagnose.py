from __future__ import annotations

"""Reproduce Task 08B.0.3 and persist region-level geometry evidence."""

import json
import os
import sys
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

BACKEND = Path(__file__).resolve().parents[2]
REPOSITORY = BACKEND.parent
TARGET = Path(os.environ.get(
    "TASK_08B_0_3_CAPTURE_DIR",
    str(BACKEND / "artifacts" / "contour_preserving" / "task_08b_0_3"),
))
sys.path.insert(0, str(BACKEND))

from tools.task_08a_1.dataset import BASE_MANIFEST, write_json  # noqa: E402


REGION_ID = 12


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _full_mask(segmentation: Any, region_id: int) -> np.ndarray:
    region = next(item for item in segmentation.regions if item.id == region_id)
    mask = np.zeros(segmentation.label_map.shape, dtype=bool)
    x0, y0, x1, y1 = region.bbox
    mask[y0:y1, x0:x1] = segmentation.label_map[y0:y1, x0:x1] == region.label_value
    return mask


def _save_mask(path: Path, mask: np.ndarray) -> None:
    Image.fromarray(mask.astype(np.uint8) * 255, mode="L").save(path)


def _crop_box(mask_a: np.ndarray, mask_b: np.ndarray, pad: int = 4) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask_a | mask_b)
    if not len(xs):
        return 0, 0, mask_a.shape[1], mask_a.shape[0]
    h, w = mask_a.shape
    return (max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad),
            min(w, int(xs.max()) + 1 + pad), min(h, int(ys.max()) + 1 + pad))


def _upscale_mask(mask: np.ndarray, box: tuple[int, int, int, int], factor: int = 20) -> Image.Image:
    x0, y0, x1, y1 = box
    image = Image.fromarray((mask[y0:y1, x0:x1].astype(np.uint8) * 255), mode="L")
    return image.resize((image.width * factor, image.height * factor), Image.Resampling.NEAREST)


def _save_geometry_images(folder: Path, source_mask: np.ndarray, raw_mask: np.ndarray,
                          fitted_mask: np.ndarray, raw_loops: list[list[tuple[float, float]]],
                          fitted_loops: list[list[tuple[float, float]]]) -> dict[str, int]:
    folder.mkdir(parents=True, exist_ok=True)
    box = _crop_box(source_mask, fitted_mask, pad=5)
    _save_mask(folder / "region12_raw_mask.png", source_mask)
    _save_mask(folder / "region12_raw_geometry_raster.png", raw_mask)
    _save_mask(folder / "region12_fitted_geometry_raster.png", fitted_mask)

    overlap = source_mask & fitted_mask
    added = fitted_mask & ~source_mask
    removed = source_mask & ~fitted_mask
    rgb = np.zeros((*source_mask.shape, 3), dtype=np.uint8)
    rgb[:] = (245, 245, 245)
    rgb[overlap] = (78, 178, 105)  # retained source pixels
    rgb[added] = (224, 65, 62)
    rgb[removed] = (53, 121, 215)
    x0, y0, x1, y1 = box
    overlay = Image.fromarray(rgb[y0:y1, x0:x1]).resize(
        ((x1 - x0) * 20, (y1 - y0) * 20), Image.Resampling.NEAREST)
    overlay.save(folder / "added_removed_pixels.png")

    source_panel = _upscale_mask(source_mask, box)
    raw_panel = _upscale_mask(raw_mask, box)
    fitted_panel = _upscale_mask(fitted_mask, box)
    panel_w, panel_h = source_panel.size
    sheet = Image.new("RGB", (panel_w * 3, panel_h + 34), "white")
    draw = ImageDraw.Draw(sheet)
    for x, title, panel in ((0, "Raw segmentation mask", source_panel),
                            (panel_w, "Raw canonical geometry raster", raw_panel),
                            (panel_w * 2, "Bezier fitted raster", fitted_panel)):
        draw.text((x + 5, 8), title, fill=(15, 25, 35))
        sheet.paste(panel.convert("RGB"), (x, 34))
    sheet.save(folder / "region12_raw_vs_fitted.png")

    # Draw the exact contour samples over the zoomed pixels, retaining the
    # pixel-edge coordinate system and offsetting by the crop origin.
    canvas = Image.new("RGB", ((x1 - x0) * 20, (y1 - y0) * 20), (250, 250, 250))
    draw = ImageDraw.Draw(canvas)
    for points, color in ((raw_loops, (35, 115, 190)), (fitted_loops, (220, 75, 55))):
        for loop in points:
            coords = [((x - x0) * 20, (y - y0) * 20) for x, y in loop]
            if len(coords) > 1:
                draw.line(coords, fill=color, width=2, joint="curve")
    canvas.save(folder / "region12_canonical_fitted_contours.png")
    return {"cropX0": x0, "cropY0": y0, "cropX1": x1, "cropY1": y1,
            "zoomFactor": 20, "rawMaskPixels": int(source_mask.sum()),
            "rawGeometryRasterPixels": int(raw_mask.sum()),
            "fittedGeometryRasterPixels": int(fitted_mask.sum()),
            "intersectionPixels": int(overlap.sum()),
            "addedPixels": int(added.sum()), "removedPixels": int(removed.sum()),
            "iou": float(overlap.sum() / max(int((source_mask | fitted_mask).sum()), 1))}


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    baseline = json.loads(BASE_MANIFEST.read_text(encoding="utf-8"))
    item = next(row for row in baseline["items"]
                if row["imageId"] == "synthetic-multiregion_illustration")
    capture: dict[str, Any] = {"imageId": item["imageId"], "sourcePath": item["path"],
                              "sourceSha256Expected": item["sha256"]}
    sys.path.insert(0, str(BACKEND))
    os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
    os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
    os.environ["DEBUG_VECTOR"] = "0"
    from mediastudio.image_tools import contour_backend, vectorization_contour
    from mediastudio.image_tools.vectorization_contour import bezier as bezier_module
    from tools.vectorization_benchmark.worker import run_image

    original_extract = vectorization_contour.extract_contour_topology
    original_fit = vectorization_contour.fit_bezier_topology
    segmentation_holder: dict[str, Any] = {}

    def extract_wrapper(segmentation: Any, *args: Any, **kwargs: Any) -> Any:
        segmentation_holder["value"] = segmentation
        return original_extract(segmentation, *args, **kwargs)

    def fit_wrapper(topology: Any, *args: Any, **kwargs: Any) -> Any:
        graph = original_fit(topology, *args, **kwargs)
        segmentation = segmentation_holder["value"]
        source_mask = _full_mask(segmentation, REGION_ID)
        raw_mask = bezier_module._render_face(graph, REGION_ID, raw=True)
        fitted_mask = bezier_module._render_face(graph, REGION_ID, raw=False)
        face = graph.faces[REGION_ID]
        loops_by_id = {loop.id: loop for loop in graph.loops}
        raw_loops = [list(graph.source_topology.loop_points(loop_id))
                     for loop_id in face.loop_ids]
        fitted_loops = [list(graph.loop_points(loop_id, density=1.6))
                        for loop_id in face.loop_ids]
        visual_counts = _save_geometry_images(
            TARGET, source_mask, raw_mask, fitted_mask, raw_loops, fitted_loops)
        region = next(row for row in segmentation.regions if row.id == REGION_ID)
        loop_rows: list[dict[str, Any]] = []
        interface_rows: dict[int, dict[str, Any]] = {}
        for loop_id in face.loop_ids:
            source_loop = graph.source_topology.loops[loop_id]
            fitted_loop = graph.loops[loop_id]
            uses: list[dict[str, Any]] = []
            for use in fitted_loop.boundary_uses:
                source_interface = graph.source_topology.interfaces[use.interface_id]
                fitted_interface = graph.interfaces[use.interface_id]
                oriented_segments = graph.interface_segments(use.interface_id, forward=use.forward)
                use_row = {
                    "interfaceId": use.interface_id,
                    "forward": use.forward,
                    "shared": source_interface.shared,
                    "regionLeft": source_interface.region_left,
                    "regionRight": source_interface.region_right,
                    "confidence": source_interface.confidence,
                    "classification": fitted_interface.classification,
                    "rollbackReason": fitted_interface.rollback_reason,
                    "fitTolerance": fitted_interface.fit_tolerance,
                    "maxBoundaryError": fitted_interface.max_boundary_error,
                    "sourcePoints": fitted_interface.source_points,
                    "fittedSegmentsCanonicalDirection": fitted_interface.segments,
                    "rawCanonicalPointsProcessingXY": graph.source_topology.interface_points(
                        use.interface_id),
                    "rawCanonicalPointsSourceXY": graph.source_topology.interface_points(
                        use.interface_id, source=True),
                    "fittedSegmentsInFaceDirection": [segment.__dict__ for segment in oriented_segments],
                }
                uses.append(use_row)
                interface_rows[use.interface_id] = use_row
            fitted_points = graph.loop_points(loop_id, density=2.0)
            loop_rows.append({
                "loopId": loop_id,
                "loopType": fitted_loop.loop_type,
                "rawSignedAreaProcessing": source_loop.signed_area_processing,
                "fittedSignedAreaAfter": bezier_module._signed_area(fitted_points),
                "parentLoopId": fitted_loop.parent_loop_id,
                "rawCanonicalContourProcessingXY": graph.source_topology.loop_points(loop_id),
                "rawCanonicalContourSourceXY": graph.source_topology.loop_points(loop_id, source=True),
                "fittedContourProcessingXY": graph.loop_points(loop_id, density=1.6),
                "interfaceUses": uses,
            })
        fitted_row = next(row for row in graph.metrics["regions"] if row["region_id"] == REGION_ID)
        incident_cubic_ids = sorted({use.interface_id for loop_id in face.loop_ids
                                     for use in graph.loops[loop_id].boundary_uses
                                     if any(segment.segment_type == "cubic"
                                            for segment in graph.interfaces[use.interface_id].segments)})
        local_trials: list[dict[str, Any]] = []
        for interface_id in incident_cubic_ids:
            trial = deepcopy(graph)
            bezier_module._rollback_interface(
                trial, interface_id,
                f"thin_feature_coverage_guard:{REGION_ID}")
            trial_raster = bezier_module._raster_metrics(trial)
            trial_validation = bezier_module._validate(trial, trial_raster)
            trial_row = next(row for row in trial.metrics["regions"]
                             if row["region_id"] == REGION_ID)
            per_face = trial_raster["per_face"]
            pre_per_face = graph.metrics["regions"]
            before_by_id = {row["region_id"]: row for row in pre_per_face}
            affected_ids = sorted({trial.interfaces[interface_id].region_left,
                                   trial.interfaces[interface_id].region_right} - {0})
            thin_rows = []
            for region_id in trial_raster["thin_region_ids"]:
                before_iou = float(before_by_id[region_id]["iou"])
                after_iou = float(per_face[str(region_id)]["iou"])
                thin_rows.append({"regionId": region_id, "beforeIoU": before_iou,
                                  "afterIoU": after_iou,
                                  "delta": after_iou - before_iou})
            trial_mask = bezier_module._render_face(trial, REGION_ID, raw=False)
            trial_visual_counts = _save_geometry_images(
                TARGET / "local_rollback_candidate", source_mask, raw_mask,
                trial_mask, raw_loops,
                [list(trial.loop_points(loop_id, density=1.6))
                 for loop_id in face.loop_ids])
            local_trials.append({
                "interfaceId": interface_id,
                "affectedRegions": affected_ids,
                "originalSegments": graph.interfaces[interface_id].segments,
                "candidateRollbackReason": trial.interfaces[interface_id].rollback_reason,
                "thinFeatureRows": thin_rows,
                "region12RasterMeasurements": trial_visual_counts,
                "sharedBoundaryMismatchCount": trial_validation.shared_boundary_mismatch_count,
                "sharedOverlapPixels": trial_validation.shared_overlap_pixels,
                "silhouetteGapPixels": trial_validation.silhouette_gap_pixels,
                "selfIntersectionCount": trial_validation.self_intersection_count,
                "validationErrors": trial_validation.errors,
                "passesRegion12Threshold": float(per_face[str(REGION_ID)]["iou"]) >= 0.80,
            })
        source_scale = list(segmentation.coordinate_mapping.scale)
        diagnostic = {
            "fixture": item["imageId"],
            "sourceSha256": item["sha256"],
            "regionId": REGION_ID,
            "segmentationRegion": {
                "bboxHalfOpenProcessingXY": region.bbox,
                "pixelArea": region.area,
                "labelValue": region.label_value,
                "neighborIds": region.neighbor_ids,
                "classification": region.classification,
                "confidence": region.confidence,
            },
            "coordinateMapping": {
                "referenceSizeWH": segmentation.coordinate_mapping.reference_size,
                "processingSizeWH": segmentation.coordinate_mapping.processing_size,
                "scaleXY": source_scale,
                "pixelEdges": "pixel (x,y) occupies [x,x+1] x [y,y+1]; edge origin is (0,0)",
                "sourceEdgeFormula": "source_edge_xy = processing_edge_xy / scale_xy",
                "fitGraphScaleXY": graph.scale_xy,
            },
            "rasterization": {
                "function": "_render_face",
                "supersample": 2,
                "coordinateQuantization": "round(processing_edge_xy * 2) via numpy.rint",
                "fill": "cv2.fillPoly, LINE_8; outer loops value=255; hole loops value=0",
                "sample": "offset=supersample//2; select [1::2,1::2]",
                "rawMaskConstruction": "SegmentationResult label map == region label value",
            },
            "rasterMeasurements": visual_counts,
            "geometryMeasurements": {
                "rawCanonicalAreaPx2": face.raster_area,
                "fittedSignedAreaPx2FromMetrics": fitted_row["bezier_area"],
                "rawRegionContourAreaPx2": fitted_row["source_area"],
                "fittedGeometryAreaDeltaPx2": fitted_row["bezier_area"] - fitted_row["source_area"],
                "fittedRelativeGeometricAreaDelta": fitted_row["relative_area_difference"],
                "fittedRasterRelativeAreaError": fitted_row["relative_area_error"],
                "selfIntersectionCount": graph.validation.self_intersection_count,
                "sharedBoundaryMismatchCount": graph.validation.shared_boundary_mismatch_count,
                "sharedOverlapPixels": graph.validation.shared_overlap_pixels,
                "silhouetteGapPixels": graph.validation.silhouette_gap_pixels,
            },
            "sourceTopologyValid": graph.source_topology.geometry_valid,
            "fittedGeometryValid": graph.geometry_valid,
            "fittedValidationErrors": graph.validation.errors,
            "regionLoops": loop_rows,
            "uniqueInterfaceIds": sorted(interface_rows),
            "localRollbackTrials": local_trials,
            "fullFitMetrics": graph.metrics,
        }
        write_json(TARGET / "region12_geometry_diagnostic.json", _json_value(diagnostic))
        capture["diagnosticCaptured"] = True
        return graph

    vectorization_contour.extract_contour_topology = extract_wrapper
    vectorization_contour.fit_bezier_topology = fit_wrapper
    try:
        record = run_image(item, TARGET, per_engine_timeout=900, run_id="task08b0_3_baseline")
        capture["workerRecord"] = {"status": record.get("status"),
                                   "engines": record.get("engines", {})}
    finally:
        vectorization_contour.extract_contour_topology = original_extract
        vectorization_contour.fit_bezier_topology = original_fit
    write_json(TARGET / "reproduction.json", capture)
    print(json.dumps({"diagnosticCaptured": capture.get("diagnosticCaptured", False),
                      "workerStatus": capture.get("workerRecord", {}).get("status"),
                      "artifacts": str(TARGET)}, indent=2))
    return 0 if capture.get("diagnosticCaptured") else 2


if __name__ == "__main__":
    raise SystemExit(main())
