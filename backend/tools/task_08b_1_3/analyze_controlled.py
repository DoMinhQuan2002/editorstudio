from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage.color import deltaE_ciede2000, rgb2lab
import re
import xml.etree.ElementTree as ET

BACKEND = Path(__file__).resolve().parents[2]
ARTIFACTS = BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_3"
sys.path.insert(0, str(BACKEND))
from tools.task_08b_1_1.diagnostics import (  # noqa: E402
    _lab_neighbor_delta,
    gradient_metrics,
    matched_boundary_metrics,
)

ENGINE_DIR = {
    "smart_reconstruction": "smart_reconstruction",
    "contour_preserving": "contour_preserving",
}
SOFT_FALSE_EDGE_THRESHOLD = 0.01
PAIR_RESPONSE_THRESHOLD = 3.0


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                               allow_nan=False) + "\n", encoding="utf-8")


def load_rgba(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)


def composite_white(rgba: np.ndarray) -> np.ndarray:
    value = np.asarray(rgba, dtype=np.float32)
    alpha = value[..., 3:4] / 255.0
    return np.rint(value[..., :3] * alpha + 255.0 * (1.0 - alpha)).clip(0, 255).astype(np.uint8)


def load_mask(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"), dtype=np.uint8) > 127


def resize_mask(mask: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    h, w = shape
    if mask.shape == (h, w):
        return np.asarray(mask, dtype=bool)
    return cv2.resize(np.asarray(mask, dtype=np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0


def load_labels(path: Path, shape: tuple[int, int]) -> np.ndarray | None:
    if not path.is_file():
        return None
    arr = np.load(path).astype(np.int32)
    if arr.shape != shape:
        arr = cv2.resize(arr, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    return arr


def svg_path_boundary(path: Path, id_prefix: str, shape: tuple[int, int]) -> tuple[np.ndarray, int]:
    mask = np.zeros(shape, dtype=np.uint8)
    if not path.is_file():
        return mask.astype(bool), 0
    root = ET.parse(path).getroot()
    drawn = 0
    number = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?")
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].casefold() != "path" or not node.attrib.get("id", "").startswith(id_prefix):
            continue
        values = [float(value) for value in number.findall(node.attrib.get("d", ""))]
        if len(values) < 4 or len(values) % 2:
            continue
        points = np.rint(np.asarray(values, dtype=np.float64).reshape(-1, 2)).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(mask, [points], True, 255, 1, cv2.LINE_8)
        drawn += 1
    return mask > 0, drawn


def label_boundary(labels: np.ndarray) -> np.ndarray:
    values = np.asarray(labels)
    out = np.zeros(values.shape, bool)
    h = (values[:, 1:] != values[:, :-1]) & (values[:, 1:] > 0) & (values[:, :-1] > 0)
    v = (values[1:, :] != values[:-1, :]) & (values[1:, :] > 0) & (values[:-1, :] > 0)
    out[:, 1:] |= h
    out[:, :-1] |= h
    out[1:, :] |= v
    out[:-1, :] |= v
    return out


def safe_boundary_metrics(truth: np.ndarray, candidate: np.ndarray,
                          tolerance_px: float = 2.0) -> dict[str, Any]:
    truth = np.asarray(truth, dtype=bool)
    candidate = np.asarray(candidate, dtype=bool)
    if not truth.any() and not candidate.any():
        return {"tolerancePx": tolerance_px, "precisionWithinTolerance": 1.0,
                "recallWithinTolerance": 1.0, "f1WithinTolerance": 1.0,
                "truthBoundaryPixels": 0, "candidateBoundaryPixels": 0,
                "missingBoundaryPixels": 0, "falseBoundaryPixels": 0,
                "meanSymmetricDistancePx": 0.0, "p95SymmetricDistancePx": 0.0,
                "groundTruthClass": "empty_analytic_ground_truth"}
    if not truth.any() or not candidate.any():
        return {"tolerancePx": tolerance_px, "precisionWithinTolerance": 0.0,
                "recallWithinTolerance": 0.0, "f1WithinTolerance": 0.0,
                "truthBoundaryPixels": int(truth.sum()), "candidateBoundaryPixels": int(candidate.sum()),
                "missingBoundaryPixels": int(truth.sum()), "falseBoundaryPixels": int(candidate.sum()),
                "meanSymmetricDistancePx": None, "p95SymmetricDistancePx": None,
                "groundTruthClass": "analytic_ground_truth" if truth.any() else "empty_analytic_ground_truth"}
    return matched_boundary_metrics(truth, candidate, tolerance_px)


def fragmentation(labels: np.ndarray | None, roi: np.ndarray) -> dict[str, Any]:
    if labels is None:
        return {"available": False, "uniqueRegionCount": None, "connectedFragmentCount": None,
                "regions": []}
    selected = np.unique(labels[roi & (labels > 0)])
    rows = []
    fragments_total = 0
    for region_id in selected:
        mask = (labels == int(region_id)) & roi
        count, _ = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
        fragments = max(0, int(count) - 1)
        fragments_total += fragments
        rows.append({"regionId": int(region_id), "connectedFragmentsInSoftRoi": fragments})
    return {"available": True, "uniqueRegionCount": int(len(selected)),
            "connectedFragmentCount": fragments_total, "regions": rows}


def exact_false_edge_map(source_rgb: np.ndarray, candidate_rgb: np.ndarray,
                         roi: np.ndarray) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    # Reuse Task 08B.1.1's exact CIE76-neighbor response and CIEDE2000 color metrics.
    metrics = gradient_metrics(source_rgb, candidate_rgb, roi)
    source_lab = rgb2lab(source_rgb.astype(np.float32) / 255.0)
    candidate_lab = rgb2lab(candidate_rgb.astype(np.float32) / 255.0)
    source_delta = _lab_neighbor_delta(source_lab)
    candidate_delta = _lab_neighbor_delta(candidate_lab)
    interior = cv2.erode(roi.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
    if not interior.any():
        interior = roi
    false_mask = interior & (candidate_delta >= PAIR_RESPONSE_THRESHOLD) & (
        candidate_delta > source_delta * 2.5 + 0.75)
    return metrics, false_mask, interior


def edge_pair_side_errors(source_rgb: np.ndarray, candidate_rgb: np.ndarray,
                          interior: np.ndarray) -> dict[str, Any]:
    source_lab = rgb2lab(source_rgb.astype(np.float32) / 255.0)
    candidate_lab = rgb2lab(candidate_rgb.astype(np.float32) / 255.0)
    source_de00 = deltaE_ciede2000(source_lab, candidate_lab)
    pair_rows = []
    source_cross, candidate_cross = [], []
    side_a_errors, side_b_errors = [], []
    h_src = np.linalg.norm(source_lab[:, 1:] - source_lab[:, :-1], axis=2)
    h_cand = np.linalg.norm(candidate_lab[:, 1:] - candidate_lab[:, :-1], axis=2)
    h_valid = interior[:, 1:] & interior[:, :-1]
    h_false = h_valid & (h_cand >= PAIR_RESPONSE_THRESHOLD) & (h_cand > h_src * 2.5 + 0.75)
    v_src = np.linalg.norm(source_lab[1:] - source_lab[:-1], axis=2)
    v_cand = np.linalg.norm(candidate_lab[1:] - candidate_lab[:-1], axis=2)
    v_valid = interior[1:] & interior[:-1]
    v_false = v_valid & (v_cand >= PAIR_RESPONSE_THRESHOLD) & (v_cand > v_src * 2.5 + 0.75)
    for y, x in zip(*np.where(h_false)):
        a, b = (int(y), int(x)), (int(y), int(x + 1))
        source_cross.append(float(h_src[y, x])); candidate_cross.append(float(h_cand[y, x]))
        side_a_errors.append(float(source_de00[a])); side_b_errors.append(float(source_de00[b]))
        if len(pair_rows) < 10:
            pair_rows.append({"orientation": "horizontal", "pixelA_xy": [a[1], a[0]],
                              "pixelB_xy": [b[1], b[0]], "sourceCrossEdgeCIE76": float(h_src[y, x]),
                              "outputCrossEdgeCIE76": float(h_cand[y, x]),
                              "sideAErrorCIEDE2000": float(source_de00[a]),
                              "sideBErrorCIEDE2000": float(source_de00[b])})
    for y, x in zip(*np.where(v_false)):
        a, b = (int(y), int(x)), (int(y + 1), int(x))
        source_cross.append(float(v_src[y, x])); candidate_cross.append(float(v_cand[y, x]))
        side_a_errors.append(float(source_de00[a])); side_b_errors.append(float(source_de00[b]))
        if len(pair_rows) < 10:
            pair_rows.append({"orientation": "vertical", "pixelA_xy": [a[1], a[0]],
                              "pixelB_xy": [b[1], b[0]], "sourceCrossEdgeCIE76": float(v_src[y, x]),
                              "outputCrossEdgeCIE76": float(v_cand[y, x]),
                              "sideAErrorCIEDE2000": float(source_de00[a]),
                              "sideBErrorCIEDE2000": float(source_de00[b])})
    def summary(values: list[float]) -> dict[str, Any]:
        return {"mean": float(np.mean(values)) if values else None,
                "p95": float(np.quantile(values, .95)) if values else None,
                "count": len(values)}
    return {"falsePairCount": len(source_cross), "sourceCrossEdgeCIE76": summary(source_cross),
            "outputCrossEdgeCIE76": summary(candidate_cross),
            "sideAColorErrorCIEDE2000": summary(side_a_errors),
            "sideBColorErrorCIEDE2000": summary(side_b_errors),
            "samplePairs": pair_rows,
            "sideConvention": "A is left for horizontal pairs and upper for vertical pairs; B is the adjacent right/lower pixel."}


def overlay(image: np.ndarray, masks: list[tuple[np.ndarray, tuple[int, int, int], int]]) -> np.ndarray:
    base = np.asarray(image, dtype=np.uint8).copy()
    for mask, color, alpha in masks:
        selected = np.asarray(mask, dtype=bool)
        if selected.shape != base.shape[:2]:
            selected = resize_mask(selected, base.shape[:2])
        base[selected] = np.rint(base[selected] * (1.0 - alpha / 255.0) +
                                 np.asarray(color, np.float64) * (alpha / 255.0)).astype(np.uint8)
    return base


def _appearance_metrics_from_png(source: np.ndarray, path: Path, roi: np.ndarray) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    rgba = load_rgba(path) if path.suffix.lower() == ".png" and Image.open(path).mode == "RGBA" else None
    if rgba is None:
        raw = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)
        rgba = np.dstack([raw, np.full(raw.shape[:2], 255, np.uint8)])
    return exact_false_edge_map(source, composite_white(rgba), roi)[0]


def analyze() -> dict[str, Any]:
    fixture_record = read_json(ARTIFACTS / "analytic_gradient_fixtures.json")
    run_record = read_json(ARTIFACTS / "api_runs.json")
    run_by_id = {row["imageId"]: row for row in run_record["results"]}
    matrix_rows: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []
    false_analysis: dict[str, Any] = {"edgeResponseColorSpace": "CIE76 Euclidean distance in CIELAB per adjacent pixel; threshold=3 and > source_response*2.5+0.75",
        "colorFidelityColorSpace": "CIEDE2000 (ΔE00)", "falseEdgeFractionReportThreshold": SOFT_FALSE_EDGE_THRESHOLD,
        "fixtures": {}}
    causes: list[dict[str, Any]] = []
    all_alignment_pass = True

    for fixture in fixture_record["fixtureGroups"]:
        fid = fixture["fixtureId"]
        fixture_root = ARTIFACTS / fixture["files"]["source"]
        src_rgba = load_rgba(fixture_root)
        source_rgb = composite_white(src_rgba)
        source_size = [src_rgba.shape[1], src_rgba.shape[0]]
        soft_roi = load_mask(ARTIFACTS / fixture["files"]["soft"])
        hard_truth = load_mask(ARTIFACTS / fixture["files"]["hard"])
        soft_interior = cv2.erode(soft_roi.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
        fixture_result: dict[str, Any] = {
            "sourceFamilyId": fixture["sourceFamilyId"], "size": source_size,
            "hardBoundaryTruthPixels": int(hard_truth.sum()),
            "softGradientRoiPixels": int(soft_roi.sum()),
            "engines": {},
        }
        contact_tiles: list[tuple[str, np.ndarray]] = [("Source", source_rgb)]
        record = run_by_id[fid]
        for engine in ("smart_reconstruction", "contour_preserving"):
            engine_run = record.get("engines", {}).get(engine, {})
            engine_dir = ARTIFACTS / "runs" / "task08b1_3_controlled" / "outputs" / fid / engine
            capture_dir = ARTIFACTS / "stage_captures" / fid / engine
            render_path = Path(engine_run.get("edgeRenderPath", engine_dir / "render_edge.png"))
            svg_path = engine_dir / "output.svg"
            render_rgba = load_rgba(render_path) if render_path.is_file() else None
            if render_rgba is None:
                row = {"status": engine_run.get("status", "MISSING"), "error": "native Edge render missing"}
                fixture_result["engines"][engine] = row
                matrix_rows.append({"fixture": fid, "engine": engine, "falseEdgeFractionPercent": None,
                                    "fragmentation": None, "firstFailingStage": "UNKNOWN", "confidence": "UNKNOWN"})
                all_alignment_pass = False
                continue
            rendered_rgb = composite_white(render_rgba)
            render_dimensions = [render_rgba.shape[1], render_rgba.shape[0]]
            svg_validation = read_json(engine_dir / "svg_validation.json") if (engine_dir / "svg_validation.json").is_file() else {}
            try:
                view_box = [float(value) for value in re.split(r"[\s,]+", str(svg_validation.get("viewBox", "")).strip())]
            except ValueError:
                view_box = []
            exact_view_box = view_box == [0.0, 0.0, float(source_size[0]), float(source_size[1])]
            coordinate_ok = render_dimensions == source_size and svg_validation.get("viewBoxValid") is True and exact_view_box
            no_raster = svg_validation.get("embeddedRasterElementCount", 0) == 0 and svg_validation.get("embeddedRasterDataUriCount", 0) == 0
            all_alignment_pass &= bool(coordinate_ok and no_raster)
            run_detail = read_json(engine_dir / "run_record.json") if (engine_dir / "run_record.json").is_file() else {}
            skia_check = run_detail.get("skiaRendererCheck", {})

            label_path = capture_dir / ("phase_c_labels_native.npy" if engine == "smart_reconstruction" else "segmentation_labels_working.npy")
            labels = load_labels(label_path, src_rgba.shape[:2])
            if engine == "contour_preserving" and labels is not None:
                seg_mapping = read_json(capture_dir / "segmentation.json").get("coordinateMapping", {})
                mapping = {"referenceSize": seg_mapping.get("referenceSize"),
                           "processingSize": seg_mapping.get("processingSize"),
                           "scale": seg_mapping.get("scale")}
            else:
                sm = read_json(capture_dir / "phase_c_metrics.json") if (capture_dir / "phase_c_metrics.json").exists() else {}
                mapping = {"referenceSize": source_size, "processingSize": list(labels.shape[::-1]) if labels is not None else None,
                           "scale": None, "basis": "Smart Phase C working canvas; native source dimensions captured from same API job"}
            seg_boundary = label_boundary(labels) if labels is not None else np.zeros(soft_roi.shape, bool)
            seg_boundary = resize_mask(seg_boundary, soft_roi.shape)
            seg_fp = seg_boundary & soft_interior
            fragment = fragmentation(labels, soft_interior)

            if engine == "smart_reconstruction":
                canonical = np.zeros(soft_roi.shape, bool)
                geometry_path = capture_dir / "d1_geometry_boundaries.png"
                geometry_boundary = load_mask(geometry_path) if geometry_path.is_file() else canonical
                appearance_path = capture_dir / "e1_model_prediction_rgba.png"
                serialized_path = capture_dir / "e1_svg_render_rgba.png"
                appearance_metrics = _appearance_metrics_from_png(source_rgb, appearance_path, soft_roi)
                serialized_metrics = _appearance_metrics_from_png(source_rgb, serialized_path, soft_roi)
                appearance_base_metrics = None
                feature_boundary = np.zeros(soft_roi.shape, bool)
                feature_path_count = 0
                canonical_status = "not_separately_materialized; D1 shared fitted boundaries capture actual vector geometry"
            else:
                canonical_path = capture_dir / "canonical_geometry_boundaries.png"
                canonical = load_mask(canonical_path) if canonical_path.is_file() else np.zeros(soft_roi.shape, bool)
                geometry_path = capture_dir / "bezier_geometry_boundaries.png"
                geometry_boundary = load_mask(geometry_path) if geometry_path.is_file() else canonical
                appearance_path = capture_dir / "appearance_diagnostic_render.png"
                appearance_base_metrics = _appearance_metrics_from_png(
                    source_rgb, capture_dir / "appearance_paint_prediction.png", soft_roi)
                appearance_metrics = _appearance_metrics_from_png(source_rgb, appearance_path, soft_roi)
                serialized_metrics = None
                feature_boundary, feature_path_count = svg_path_boundary(
                    capture_dir / "composer_output.svg", "contour-detail-", soft_roi.shape)
                canonical_status = "captured from actual canonical shared interfaces"

            geometry_boundary = resize_mask(geometry_boundary, soft_roi.shape)
            canonical = resize_mask(canonical, soft_roi.shape)
            geometry_fp = geometry_boundary & soft_interior
            canonical_fp = canonical & soft_interior
            final_metric, false_map, interior = exact_false_edge_map(source_rgb, rendered_rgb, soft_roi)
            appearance_false_map = np.zeros(soft_roi.shape, bool)
            appearance_vs_final = {"falseEdgeMaskIoU": None, "meanDeltaE00InSoftROI": None,
                                   "p95DeltaE00InSoftROI": None}
            if appearance_path.is_file():
                appearance_rgba = load_rgba(appearance_path)
                appearance_rgb = composite_white(appearance_rgba)
                _, appearance_false_map, _ = exact_false_edge_map(source_rgb, appearance_rgb, soft_roi)
                union = int(np.count_nonzero(appearance_false_map | false_map))
                appearance_vs_final["falseEdgeMaskIoU"] = float(np.count_nonzero(appearance_false_map & false_map) / max(union, 1))
                appearance_de00 = deltaE_ciede2000(
                    rgb2lab(appearance_rgb.astype(np.float32) / 255.0),
                    rgb2lab(rendered_rgb.astype(np.float32) / 255.0))
                appearance_vs_final["meanDeltaE00InSoftROI"] = float(appearance_de00[soft_interior].mean())
                appearance_vs_final["p95DeltaE00InSoftROI"] = float(np.quantile(appearance_de00[soft_interior], .95))
            false_count = int(false_map.sum())
            feature_boundary = resize_mask(feature_boundary, soft_roi.shape)
            feature_near = cv2.dilate(feature_boundary.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
            feature_overlap = float((false_map & feature_near).sum() / false_count) if false_count else 0.0
            near = cv2.dilate(seg_boundary.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
            near_fraction = float((false_map & near).sum() / false_count) if false_count else 0.0
            boundary_metrics = {
                "segmentationVsGroundTruth": safe_boundary_metrics(hard_truth, seg_boundary, 2.0),
                "canonicalGeometryVsGroundTruth": safe_boundary_metrics(hard_truth, canonical, 2.0),
                "fittedGeometryVsGroundTruth": safe_boundary_metrics(hard_truth, geometry_boundary, 2.0),
                "segmentationBoundaryPixelsInSoftGradientROI": int(seg_fp.sum()),
                "canonicalBoundaryPixelsInSoftGradientROI": int(canonical_fp.sum()),
                "fittedGeometryBoundaryPixelsInSoftGradientROI": int(geometry_fp.sum()),
                "falseVisualEdgePixelsNearSegmentationBoundary": int((false_map & near).sum()),
                "falseVisualEdgePixels": false_count,
                "falseVisualEdgeNearSegmentationFraction": near_fraction,
                "geometryBoundaryOverlapWithFalseVisualEdges": float((false_map & cv2.dilate(geometry_boundary.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1).astype(bool)).sum() / false_count) if false_count else 0.0,
                "internalAppearanceFeaturePathCount": feature_path_count,
                "falseVisualEdgeOverlapWithInternalAppearanceFeatures": feature_overlap,
            }
            side_errors = edge_pair_side_errors(source_rgb, rendered_rgb, interior)
            output_alpha_iou = None
            ref_alpha = src_rgba[..., 3] > 16
            out_alpha = render_rgba[..., 3] > 16
            if ref_alpha.shape == out_alpha.shape:
                output_alpha_iou = float(np.count_nonzero(ref_alpha & out_alpha) / max(np.count_nonzero(ref_alpha | out_alpha), 1))
            first_stage = "NO_DEFECT_REPRODUCED"
            confidence = "VERIFIED"
            reproduced = final_metric["falseHardEdgeFraction"] >= SOFT_FALSE_EDGE_THRESHOLD
            if reproduced:
                app_fraction = None if appearance_metrics is None else appearance_metrics["falseHardEdgeFraction"]
                serialized_fraction = None if serialized_metrics is None else serialized_metrics["falseHardEdgeFraction"]
                if (app_fraction is not None and app_fraction >= SOFT_FALSE_EDGE_THRESHOLD and
                        appearance_vs_final["falseEdgeMaskIoU"] is not None and
                        appearance_vs_final["falseEdgeMaskIoU"] >= .70 and
                        fragment["uniqueRegionCount"] == 1 and engine == "contour_preserving" and
                        feature_overlap >= .70):
                    first_stage = "GRADIENT_FITTING_ERROR"
                    confidence = "VERIFIED"
                elif near_fraction >= 0.70 and app_fraction is not None and app_fraction >= SOFT_FALSE_EDGE_THRESHOLD:
                    first_stage = "APPEARANCE_CROSS_REGION_DISCONTINUITY"
                    confidence = "VERIFIED" if appearance_vs_final["falseEdgeMaskIoU"] is not None and appearance_vs_final["falseEdgeMaskIoU"] >= .70 else "PROBABLE"
                elif (near_fraction >= 0.70 and serialized_fraction is not None and
                      serialized_fraction >= SOFT_FALSE_EDGE_THRESHOLD and
                      (appearance_metrics is None or appearance_metrics["falseHardEdgeFraction"] < SOFT_FALSE_EDGE_THRESHOLD)):
                    first_stage = "SVG_COMPOSITING_SEAM"
                    confidence = "VERIFIED"
                elif boundary_metrics["geometryBoundaryOverlapWithFalseVisualEdges"] >= 0.70 and near_fraction < 0.50:
                    first_stage = "GEOMETRY_BOUNDARY_ARTIFACT"
                    confidence = "PROBABLE"
                elif fragment["uniqueRegionCount"] == 1 and app_fraction is not None and app_fraction >= SOFT_FALSE_EDGE_THRESHOLD:
                    first_stage = "GRADIENT_FITTING_ERROR"
                    confidence = "VERIFIED" if appearance_vs_final["falseEdgeMaskIoU"] is not None and appearance_vs_final["falseEdgeMaskIoU"] >= .70 else "PROBABLE"
                else:
                    first_stage = "UNKNOWN"
                    confidence = "UNKNOWN"
            final_causes = {"stage": first_stage, "confidence": confidence,
                            "visualThresholdExceeded": bool(reproduced),
                            "segmentationCausalityProven": bool(reproduced and near_fraction >= .70 and seg_fp.any()),
                            "appearanceCausalityProven": bool(
                                reproduced and appearance_metrics is not None and
                                appearance_metrics["falseHardEdgeFraction"] >= SOFT_FALSE_EDGE_THRESHOLD and
                                appearance_vs_final["falseEdgeMaskIoU"] is not None and
                                appearance_vs_final["falseEdgeMaskIoU"] >= .70),
                            "explanation": "No segmentation boundary is treated as a visible defect unless the final raster has a measured false edge in the analytic soft ROI."}
            causes.append({"fixture": fid, "engine": engine, **final_causes})
            row = {
                "status": engine_run.get("status"),
                "nativeRenderDimensions": render_dimensions,
                "coordinateAlignmentValid": coordinate_ok,
                "svgViewBox": svg_validation.get("viewBox"),
                "svgViewBoxMatchesNativeCanvas": exact_view_box,
                "svgNoEmbeddedRaster": no_raster,
                "outputAlphaIoU": output_alpha_iou,
                "edgeVsSvgSkia": {"status": skia_check.get("status"),
                                   "alphaIoU": skia_check.get("alphaIoUAgainstEdge"),
                                   "commonAlphaRgbMae": skia_check.get("commonAlphaRgbMaeAgainstEdge"),
                                   "dimensions": skia_check.get("dimensions")},
                "regionFragmentation": fragment,
                "gradientMetrics": final_metric,
                "softGradientFalseEdgePercent": 100.0 * final_metric["falseHardEdgeFraction"],
                "segmentation": {"uniqueRegionCountInSoftROI": fragment.get("uniqueRegionCount"),
                                 "internalBoundaryPixelCountInSoftROI": int(seg_fp.sum()),
                                 "workingMapping": mapping},
                "boundaryStageComparison": boundary_metrics,
                "appearanceStageMetrics": appearance_metrics,
                "appearanceBasePaintOnlyMetrics": appearance_base_metrics,
                "appearanceDiagnosticVsProductionRender": appearance_vs_final,
                "serializedSvgStageMetrics": serialized_metrics,
                "falseBoundaryColorErrorBothSides": side_errors,
                "firstFailingStage": first_stage,
                "confidence": confidence,
                "actualEngineRunRecord": str((engine_dir / "run_record.json").relative_to(ARTIFACTS).as_posix()),
                "svgPath": str(svg_path.relative_to(ARTIFACTS).as_posix()),
            }
            fixture_result["engines"][engine] = row
            matrix_rows.append({"fixture": fid, "engine": engine,
                "falseEdgeFractionPercent": round(100.0 * final_metric["falseHardEdgeFraction"], 6),
                "fragmentation": fragment.get("uniqueRegionCount"),
                "firstFailingStage": first_stage, "confidence": confidence})
            contact_tiles.append((f"{engine} final", rendered_rgb))
            if labels is not None:
                contact_tiles.append((f"{engine} segmentation", overlay(source_rgb, [(seg_boundary, (255, 30, 40), 220)])))
            if geometry_boundary.any():
                contact_tiles.append((f"{engine} geometry", overlay(source_rgb, [(geometry_boundary, (36, 87, 255), 220)])))
            # Save boundary overlays for all analytic cases; visible false pixels are highlighted yellow.
            overlay_dir = ARTIFACTS / "visuals" / "boundary_overlays"
            overlay_dir.mkdir(parents=True, exist_ok=True)
            Image.fromarray(overlay(source_rgb, [
                (seg_boundary, (30, 110, 255), 220),
                (geometry_boundary, (0, 200, 255), 220),
                (feature_boundary, (210, 25, 220), 220),
                (false_map, (255, 0, 35), 245),
            ])).save(overlay_dir / f"{fid}_{engine}.png")
        false_analysis["fixtures"][fid] = fixture_result
        _save_contact_sheet(fid, contact_tiles)

    matrix = {
        "schemaVersion": 1,
        "thresholds": {"hardBoundaryTolerancePx": 2.0,
                       "falseEdgeThresholdDeltaE76PerPx": PAIR_RESPONSE_THRESHOLD,
                       "falseEdgeSourceMultiplier": 2.5, "falseEdgeSourceAdditive": 0.75,
                       "falseEdgeFractionReportThreshold": SOFT_FALSE_EDGE_THRESHOLD},
        "edgeResponseSpace": "CIE76 Euclidean distance in Lab per adjacent pixel",
        "colorFidelitySpace": "CIEDE2000 (ΔE00)",
        "rows": matrix_rows,
        "allApiRunsSucceeded": bool(run_record.get("allPass")),
        "nativeCoordinateAlignmentPass": bool(all_alignment_pass),
    }
    write_json(ARTIFACTS / "gradient_banding_matrix.json", matrix)
    write_json(ARTIFACTS / "boundary_stage_comparison.json", {
        "hardBoundaryTolerancePx": 2.0,
        "boundaryMetricMethod": "Task 08B.1.1 symmetric distance-transform precision/recall",
        "fixtures": {fid: {engine: row.get("boundaryStageComparison") for engine, row in data["engines"].items()}
                     for fid, data in false_analysis["fixtures"].items()},
    })
    write_json(ARTIFACTS / "false_edge_analysis.json", false_analysis)
    reproduced_contour = any(row["engine"] == "contour_preserving" and row["falseEdgeFractionPercent"] is not None and row["falseEdgeFractionPercent"] >= 1.0 for row in matrix_rows)
    seg_cause = any(item["engine"] == "contour_preserving" and item["segmentationCausalityProven"]
                    for item in causes)
    app_cause = any(item["engine"] == "contour_preserving" and item["appearanceCausalityProven"]
                    for item in causes)
    all_stages_verified = all(item["confidence"] == "VERIFIED" for item in causes if item["visualThresholdExceeded"])
    first_stage_status = "true" if reproduced_contour and all_stages_verified else ("partial" if reproduced_contour else "false")
    write_json(ARTIFACTS / "first_failing_stage.json", {
        "classificationVocabulary": ["SEGMENTATION_FALSE_SPLIT", "GEOMETRY_BOUNDARY_ARTIFACT",
            "APPEARANCE_CROSS_REGION_DISCONTINUITY", "GRADIENT_FITTING_ERROR", "SVG_COMPOSITING_SEAM",
            "SOURCE_COMPRESSION_ARTIFACT", "NO_DEFECT_REPRODUCED", "UNKNOWN"],
        "results": causes,
        "firstFailingStageVerified": first_stage_status,
        "segmentationCausalityProven": bool(seg_cause),
        "appearanceCausalityProven": bool(app_cause),
        "interpretation": "Segmentation fragmentation is reported independently. A visible defect requires final-render false-edge fraction >=1% of the eroded analytic soft ROI.",
    })
    return {"matrix": matrix, "causes": causes, "falseAnalysis": false_analysis,
            "segmentationCausalityProven": bool(seg_cause),
            "appearanceCausalityProven": bool(app_cause),
            "firstFailingStageVerified": first_stage_status,
            "contourFalseBoundaryReproduced": bool(reproduced_contour),
            "coordinateAlignmentPass": bool(all_alignment_pass)}


def _font(size: int = 18) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _save_contact_sheet(fixture_id: str, tiles: list[tuple[str, np.ndarray]]) -> None:
    if not tiles:
        return
    tile_w, tile_h, header_h = 320, 350, 36
    cols = min(4, len(tiles))
    rows = int(np.ceil(len(tiles) / cols))
    sheet = Image.new("RGB", (cols * tile_w, rows * (tile_h + header_h)), "#f1f1f4")
    draw = ImageDraw.Draw(sheet)
    font = _font(16)
    for index, (label, image) in enumerate(tiles):
        x0 = (index % cols) * tile_w
        y0 = (index // cols) * (tile_h + header_h)
        draw.rectangle((x0, y0, x0 + tile_w - 1, y0 + header_h - 1), fill="white")
        draw.text((x0 + 10, y0 + 8), label, fill="#172033", font=font)
        thumb = Image.fromarray(np.asarray(image, dtype=np.uint8), "RGB")
        thumb.thumbnail((tile_w - 14, tile_h - 14), Image.Resampling.LANCZOS)
        sheet.paste(thumb, (x0 + (tile_w - thumb.width) // 2,
                            y0 + header_h + (tile_h - thumb.height) // 2))
    out = ARTIFACTS / "visuals" / "contact_sheets" / f"{fixture_id}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)


def detector_controls() -> dict[str, Any]:
    source = np.full((128, 128, 3), 120, dtype=np.uint8)
    yy, xx = np.indices((128, 128))
    soft = (xx > 8) & (xx < 120) & (yy > 8) & (yy < 120)
    # A gentle continuous ramp is the negative control.
    ramp = np.repeat((np.clip(110 + xx * .2, 0, 255).astype(np.uint8))[..., None], 3, axis=2)
    neg = gradient_metrics(ramp, ramp, soft)
    # A high-contrast line inside the ROI is the positive detector control.
    positive = ramp.copy()
    positive[:, 63:] = np.clip(positive[:, 63:].astype(np.int16) + 40, 0, 255).astype(np.uint8)
    pos = gradient_metrics(ramp, positive, soft)
    return {"negativeControl": {"candidateIsSource": True, "falseEdgeFraction": neg["falseHardEdgeFraction"],
                                "expected": "0"},
            "positiveControl": {"insertedHardStep": "40 sRGB levels at x=63 inside the ROI",
                                "falseEdgeFraction": pos["falseHardEdgeFraction"],
                                "expected": ">1%"},
            "pass": neg["falseHardEdgeFraction"] == 0.0 and pos["falseHardEdgeFraction"] > .01,
            "detectorDefinition": "Exact Task 08B.1.1 CIE76 Lab-neighbor rule; color error metrics remain CIEDE2000."}


if __name__ == "__main__":
    result = analyze()
    controls = detector_controls()
    write_json(ARTIFACTS / "false_edge_detector_controls.json", controls)
    print(json.dumps({"contourFalseBoundaryReproduced": result["contourFalseBoundaryReproduced"],
                      "firstFailingStageVerified": result["firstFailingStageVerified"],
                      "segmentationCausalityProven": result["segmentationCausalityProven"],
                      "appearanceCausalityProven": result["appearanceCausalityProven"],
                      "coordinateAlignmentPass": result["coordinateAlignmentPass"],
                      "detectorControlsPass": controls["pass"],
                      "rows": result["matrix"]["rows"]}, ensure_ascii=False, indent=2))
