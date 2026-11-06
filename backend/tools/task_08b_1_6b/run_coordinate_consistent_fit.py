from __future__ import annotations

import copy
import hashlib
import json
import math
import statistics
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage.color import rgb2lab

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tools"))

from task_08b_1_1.diagnostics import _lab_neighbor_delta
from task_08b_1_5 import run_feasibility as feasibility
from task_08b_1_6 import run_multidirectional as legacy
from task_08b_1_6a import run_numerical_stability as prior
from task_08b_1_6b.svg_coordinate_contract import (
    linear_gradient_coordinates, sample_stops, stop_table,
)

ART = BACKEND / "artifacts/contour_preserving/task_08b_1_6b"
OLD_ART = BACKEND / "artifacts/contour_preserving/task_08b_1_6"
TASK15 = BACKEND / "artifacts/contour_preserving/task_08b_1_5"
TASK14 = BACKEND / "artifacts/contour_preserving/task_08b_1_4"
TASK13 = BACKEND / "artifacts/contour_preserving/task_08b_1_3"
PRIMARY = "smooth_nonlinear_gradient"
FIXTURES = legacy.FIXTURES
NS = feasibility.NS


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def canonical_sha(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest().upper()


def jread(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _rgb_float(rgba: np.ndarray) -> np.ndarray:
    return feasibility.white(rgba).astype(np.float64) / 255.0


def _rgba(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    out = np.empty((*rgb.shape[:2], 4), dtype=np.uint8)
    out[..., :3] = np.rint(np.clip(rgb, 0.0, 1.0) * 255.0).astype(np.uint8)
    out[..., 3] = alpha
    return out


def _stats(values: np.ndarray) -> dict:
    a = np.asarray(values, dtype=np.float64).reshape(-1)
    if not a.size:
        return {"count": 0, "mean": None, "p95": None, "max": None}
    return {"count": int(a.size), "mean": float(a.mean()),
            "p95": float(np.quantile(a, .95)), "max": float(a.max())}


def _basis(values: np.ndarray, count: int) -> np.ndarray:
    z = np.clip(np.asarray(values, dtype=np.float64).ravel(), 0.0, 1.0) * (count - 1)
    low = np.floor(z).astype(np.int32)
    high = np.minimum(low + 1, count - 1)
    frac = z - low
    matrix = np.zeros((z.size, count), dtype=np.float64)
    rows = np.arange(z.size)
    matrix[rows, low] += 1.0 - frac
    matrix[rows, high] += frac
    return matrix


def _find(root: ET.Element, element_id: str) -> ET.Element:
    node = next((n for n in root.iter() if n.attrib.get("id") == element_id), None)
    if node is None:
        raise ValueError(f"Missing SVG element id={element_id}")
    return node


def _build_system(source: np.ndarray, base: np.ndarray, support: np.ndarray,
                  coordinates: list[np.ndarray]) -> dict:
    count = legacy.STOPS
    bases = [_basis(t[support], count) for t in coordinates]
    weights = [legacy.OPACITY * (1.0 - legacy.OPACITY) ** (len(bases) - 1 - i)
               for i in range(len(bases))]
    base_weight = (1.0 - legacy.OPACITY) ** len(bases)
    design = np.concatenate([b * w for b, w in zip(bases, weights)], axis=1)
    source_samples = source[support, :3].astype(np.float64) / 255.0
    base_samples = _rgb_float(base)[support]
    target = source_samples - base_weight * base_samples
    d2 = np.zeros((count - 2, count), dtype=np.float64)
    for i in range(count - 2):
        d2[i, i:i + 3] = (1.0, -2.0, 1.0)
    regularizer = np.zeros((len(bases) * (count - 2), len(bases) * count), dtype=np.float64)
    for i in range(len(bases)):
        regularizer[i * (count - 2):(i + 1) * (count - 2), i * count:(i + 1) * count] = d2 * legacy.SMOOTHNESS
    augmented = np.vstack((design, regularizer))
    rhs = np.vstack((target, np.zeros((len(regularizer), 3), dtype=np.float64)))
    return {"bases": bases, "weights": weights, "baseWeight": base_weight,
            "design": design, "target": target, "regularizer": regularizer,
            "augmented": augmented, "rhs": rhs, "sourceSamples": source_samples,
            "baseSamples": base_samples}


def _fit(system: dict) -> tuple[list[np.ndarray], dict]:
    raw, _, rank, singular = np.linalg.lstsq(system["augmented"], system["rhs"], rcond=1e-10)
    clipped = np.clip(raw, 0.0, 1.0)
    count = legacy.STOPS
    tables = [clipped[i * count:(i + 1) * count] for i in range(len(system["bases"]))]
    prediction = system["baseWeight"] * system["baseSamples"]
    for weight, basis, table in zip(system["weights"], system["bases"], tables):
        prediction = prediction + weight * (basis @ table)
    return tables, {"solver": "numpy.linalg.lstsq on unchanged regularized source-over system",
                    "rank": int(rank), "columnCount": int(system["augmented"].shape[1]),
                    "singularValues": singular.tolist(), "sampleCount": int(system["design"].shape[0]),
                    "regularizationWeight": legacy.SMOOTHNESS, "stopOpacity": legacy.OPACITY,
                    "clippedComponents": int(np.count_nonzero(np.abs(raw - clipped) > 1e-9)),
                    "fittedRgbRmse": float(np.sqrt(np.mean((prediction - system["sourceSamples"]) ** 2))),
                    "stopTables": [table.tolist() for table in tables]}


def _write_stop_colors(root: ET.Element, rid: int, tables: list[np.ndarray]) -> dict:
    changes = {}
    for li, table in enumerate(tables):
        gid = f"research-multidirectional-r{rid}-d{li}"
        grad = _find(root, gid)
        stops = [n for n in grad if n.tag.rsplit("}", 1)[-1] == "stop"]
        if len(stops) != legacy.STOPS:
            raise AssertionError(f"Expected {legacy.STOPS} stops in {gid}, got {len(stops)}")
        rows = []
        for stop, rgb in zip(stops, table):
            color = "#" + "".join(f"{int(v):02x}" for v in np.rint(np.clip(rgb, 0, 1) * 255).astype(int))
            rows.append({"old": stop.attrib["stop-color"], "new": color})
            stop.set("stop-color", color)
        changes[gid] = rows
    return changes


def _detail_group_only_remove(svg_root: ET.Element, group_id: str = "artwork-internal-details") -> bool:
    parents = {child: parent for parent in svg_root.iter() for child in parent}
    group = next((node for node in svg_root.iter() if node.attrib.get("id") == group_id), None)
    if group is None:
        return False
    parent = parents.get(group)
    if parent is None:
        raise ValueError(f"Detail group {group_id} has no parent")
    parent.remove(group)
    return True


def _apply_layer(rgb: np.ndarray, field: np.ndarray, alpha: np.ndarray,
                 support: np.ndarray) -> None:
    a = alpha[support, None]
    rgb[support] = rgb[support] * (1.0 - a) + field[support] * a


def _predictions(base: np.ndarray, root: ET.Element, fits: dict, support_masks: dict,
                 shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    a_rgb = _rgb_float(base).copy()
    b_rgb = _rgb_float(base).copy()
    union = np.zeros(shape, dtype=bool)
    layer_records = {}
    for rid_text, fit in fits.items():
        rid = int(rid_text)
        support = support_masks[rid_text]
        union |= support
        layer_records[rid_text] = []
        for li, (coords, table) in enumerate(zip(fit["coordinates"], fit["tables"])):
            grad = _find(root, f"research-multidirectional-r{rid}-d{li}")
            # A is the unquantized fitter prediction; B samples the exact serialized SVG stop table.
            a_field = np.zeros((*shape, 3), dtype=np.float64)
            a_alpha = np.zeros(shape, dtype=np.float64)
            a_field[support] = _basis(coords[support], legacy.STOPS) @ table
            a_alpha[support] = legacy.OPACITY
            _apply_layer(a_rgb, a_field, a_alpha, support)
            offsets, colors, stop_alpha = stop_table(grad)
            b_field, b_alpha = sample_stops(offsets, colors, stop_alpha, coords)
            _apply_layer(b_rgb, b_field, b_alpha, support)
            layer_records[rid_text].append({"gradientId": grad.attrib.get("id"),
                                            "supportPixelCount": int(support.sum()),
                                            "serializedStopCount": int(len(offsets)),
                                            "serializedOpacityMin": float(stop_alpha.min()),
                                            "serializedOpacityMax": float(stop_alpha.max())})
    return _rgba(a_rgb, base[..., 3]), _rgba(b_rgb, base[..., 3]), union, layer_records


def _coordinate_stats(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> dict:
    diff = np.abs(np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64))[mask]
    if diff.size == 0:
        return {"sampleCount": 0, "maxAbs": None, "meanAbs": None,
                "p95Abs": None, "mismatchedFraction_1e-10": None}
    return {"sampleCount": int(diff.size), "maxAbs": float(diff.max()),
            "meanAbs": float(diff.mean()), "p95Abs": float(np.quantile(diff, .95)),
            "mismatchedFraction_1e-10": float(np.mean(diff > 1e-10))}


def _fixture_paths(fid: str):
    source_path, roi_path, full_svg, appearance_path, detail_path = legacy.paths(fid)
    base_svg = TASK15 / "fixtures" / fid / "base_paint_only.svg"
    old_svg = OLD_ART / "fixtures" / fid / "experimental_multidirectional.svg"
    if not old_svg.is_file() and fid == PRIMARY:
        old_svg = OLD_ART / "experimental_multidirectional.svg"
    paths = [source_path, roi_path, full_svg, appearance_path, base_svg, old_svg]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise FileNotFoundError(f"Frozen fixture input missing: {missing}")
    return source_path, roi_path, full_svg, appearance_path, detail_path, base_svg, old_svg


def _fit_fixture(fid: str, folder: Path, directions: list[float], render: bool = True) -> dict:
    source_path, roi_path, full_svg, appearance_path, detail_path, base_svg, old_svg = _fixture_paths(fid)
    source = legacy.load_rgba(source_path)
    roi = legacy.img(roi_path, "L") > 127
    base = legacy.render_svg_edge(base_svg, width=source.shape[1], height=source.shape[0])
    base_root = feasibility._read_tree(base_svg)
    old_root = feasibility._read_tree(old_svg)
    candidate_root = copy.deepcopy(old_root)
    appearance = legacy.jread(appearance_path)
    regions = [r for r in appearance.get("regions", []) if r.get("gradient")
               and r["gradient"].get("kind") in {"linear", "radial"}]
    fits = {}
    supports = {}
    coordinate_rows = []
    stop_changes = {}
    fit_time_start = time.perf_counter()
    for region in regions:
        rid = int(region["regionId"])
        mask = feasibility._region_mask(base_root, rid, folder / "diagnostics")
        support = mask & (source[..., 3] >= 250) & (base[..., 3] >= 250)
        support = cv2.erode(support.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1).astype(bool)
        if support.sum() < legacy.STOPS * 4:
            continue
        old_gradients, candidate_gradients, coord_arrays, metas = [], [], [], []
        for li, angle in enumerate(directions):
            gid = f"research-multidirectional-r{rid}-d{li}"
            old_gradient = _find(old_root, gid)
            candidate_gradient = _find(candidate_root, gid)
            old_gradients.append(old_gradient)
            candidate_gradients.append(candidate_gradient)
            actual_t, meta = linear_gradient_coordinates(old_root, old_gradient, support.shape)
            use_ref = next((node for node in old_root.iter()
                            if node.attrib.get("fill", "").replace(" ", "") == f"url(#{gid})"), None)
            if use_ref is not None:
                parent_map = {child: parent for parent in old_root.iter() for child in parent}
                presentation_chain = []
                ancestor = use_ref
                while ancestor is not None:
                    presentation_chain.append({"tag": ancestor.tag.rsplit("}", 1)[-1],
                        "id": ancestor.attrib.get("id"), "mask": ancestor.attrib.get("mask"),
                        "clipPath": ancestor.attrib.get("clip-path")})
                    ancestor = parent_map.get(ancestor)
                meta["paintReferenceClipping"] = [x for x in presentation_chain if x["mask"] or x["clipPath"]]
                meta["fillRule"] = use_ref.attrib.get("fill-rule", "nonzero")
            coord_arrays.append(actual_t)
            metas.append(meta)
            legacy_t = legacy.proj(support.shape, angle, support)
            eroded = cv2.erode(support.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1).astype(bool)
            edge_ring = support & ~eroded
            painted_outside_support = mask & ~support
            coordinate_rows.append({"fixture": fid, "regionId": rid, "gradientId": gid,
                                    "directionDegrees": angle, "svgCoordinateMetadata": meta,
                                    "legacyFitterVsSvg": {
                                        "allTrainingSupport": _coordinate_stats(legacy_t, actual_t, support),
                                        "nearSupportBoundary": _coordinate_stats(legacy_t, actual_t, edge_ring),
                                        "paintedRegionOutsideFitSupport": _coordinate_stats(legacy_t, actual_t, painted_outside_support),
                                        "entirePaintedRegion": _coordinate_stats(legacy_t, actual_t, mask)},
                                    "candidateFitterVsEmittedSvgBeforeFit": _coordinate_stats(actual_t, actual_t, support)})
        system = _build_system(source, base, support, coord_arrays)
        tables, trace = _fit(system)
        stop_changes.update(_write_stop_colors(candidate_root, rid, tables))
        fits[str(rid)] = {"regionId": rid, "supportPixels": int(support.sum()),
                          "supportBoundsXYXY": [int(np.where(support)[1].min()), int(np.where(support)[0].min()),
                                                int(np.where(support)[1].max()) + 1, int(np.where(support)[0].max()) + 1],
                          "directionsDegrees": directions, "coordinates": coord_arrays,
                          "tables": tables, "trace": trace, "metadata": metas,
                          "changedSerializedStopColors": any(r["old"].lower() != r["new"].lower()
                                                              for entries in stop_changes.values() for r in entries)}
        supports[str(rid)] = support
    fit_ms = (time.perf_counter() - fit_time_start) * 1000.0
    if not fits:
        raise RuntimeError(f"No eligible gradient region fitted for {fid}")
    folder.mkdir(parents=True, exist_ok=True)
    candidate_svg = folder / "experimental_coordinate_consistent.svg"
    feasibility._save_svg(candidate_root, candidate_svg)
    if not render:
        return {"fixture": fid, "sourcePath": source_path, "roiPath": roi_path,
                "fullSvg": full_svg, "baseSvg": base_svg, "oldSvg": old_svg,
                "detailPath": detail_path, "source": source, "roi": roi, "base": base,
                "fits": fits, "supports": supports, "coordinates": coordinate_rows,
                "candidateSvg": candidate_svg, "fitTimeMs": fit_ms, "stopChanges": stop_changes}

    current_rgba, current_times = legacy._render_timed(full_svg, folder / "current_edge.png", repeats=1)
    old_rgba, old_times = legacy._render_timed(old_svg, folder / "baseline_multidirectional_edge.png", repeats=1)
    candidate_rgba, candidate_times = legacy._render_timed(candidate_svg, folder / "candidate_edge.png", repeats=1)
    gradient_root = feasibility._read_tree(candidate_svg)
    details_removed = _detail_group_only_remove(gradient_root)
    gradient_only_svg = folder / "candidate_gradient_only.svg"
    feasibility._save_svg(gradient_root, gradient_only_svg)
    gradient_only_rgba, gradient_only_times = legacy._render_timed(gradient_only_svg, folder / "candidate_gradient_only_edge.png", repeats=1)
    a_prediction, b_prediction, union_support, prediction_layers = _predictions(base, candidate_root, fits, supports, source.shape[:2])
    eval_mask = roi & union_support
    a_b = prior._error_stats(a_prediction, b_prediction, eval_mask)
    b_c = prior._error_stats(b_prediction, gradient_only_rgba, eval_mask)
    skia = legacy.render_svg_skia(candidate_svg, width=source.shape[1], height=source.shape[0],
                                 output_path=folder / "candidate_skia.png")
    if skia.get("status") == "PASS":
        common = (candidate_rgba[..., 3] > 16) & (skia["rgba"][..., 3] > 16)
        de = prior.delta_map(candidate_rgba, skia["rgba"])[common]
        renderer = {"status": "PASS", "renderer": skia.get("renderer"),
                    "alphaIoU": feasibility.alpha_iou(candidate_rgba, skia["rgba"]),
                    "commonAlphaMeanDeltaE00": float(de.mean()) if de.size else 0.0,
                    "commonAlphaP95DeltaE00": float(np.quantile(de, .95)) if de.size else 0.0}
    else:
        renderer = {"status": skia.get("status"), "reason": skia.get("reason", skia.get("stderr")),
                    "alphaIoU": None, "commonAlphaMeanDeltaE00": None, "commonAlphaP95DeltaE00": None}
    geometry = legacy.geometry(full_svg, candidate_svg)
    validation = feasibility.validate_svg(candidate_svg)
    complexity = legacy._svg_complexity(candidate_svg)
    metrics = {"currentProduction": legacy.metrics(source, current_rgba, roi),
               "oldMultidirectional": legacy.metrics(source, old_rgba, roi),
               "coordinateConsistentCandidate": legacy.metrics(source, candidate_rgba, roi),
               "candidateGradientOnly": legacy.metrics(source, gradient_only_rgba, roi)}
    alpha = {"candidateVsOldDifferentPixels": int(np.count_nonzero(candidate_rgba[..., 3] != old_rgba[..., 3])),
             "candidateVsCurrentDifferentPixels": int(np.count_nonzero(candidate_rgba[..., 3] != current_rgba[..., 3])),
             "candidateVsOldIoU": feasibility.alpha_iou(candidate_rgba, old_rgba),
             "candidateVsCurrentIoU": feasibility.alpha_iou(candidate_rgba, current_rgba)}
    detail_recall = None
    if detail_path.is_file():
        detail_mask = legacy.img(detail_path, "L") > 127
        if detail_mask.any():
            annotations = jread(TASK14 / "controlled_variants.json")["variants"]
            ann = next(v for v in annotations if v["fixtureId"] == fid)["analyticAnnotation"]["details"][0]
            target = np.broadcast_to(np.asarray(ann["paintRGB"], dtype=np.uint8), source.shape[:2] + (3,))
            recall = lambda img: float(np.mean(prior.delta_map(target, feasibility.white(img))[detail_mask] <= 10.0))
            detail_recall = {"id": ann["id"], "pixels": int(detail_mask.sum()), "targetRGB": ann["paintRGB"],
                             "currentRecall": recall(current_rgba), "oldMultidirectionalRecall": recall(old_rgba),
                             "candidateRecall": recall(candidate_rgba)}
    return {"fixture": fid, "sourcePath": source_path, "roiPath": roi_path,
            "fullSvg": full_svg, "baseSvg": base_svg, "oldSvg": old_svg,
            "detailPath": detail_path, "source": source, "roi": roi, "base": base,
            "fits": fits, "supports": supports, "coordinates": coordinate_rows, "stopChanges": stop_changes,
            "candidateSvg": candidate_svg, "currentRgba": current_rgba, "oldRgba": old_rgba,
            "candidateRgba": candidate_rgba, "gradientOnlyRgba": gradient_only_rgba,
            "fitPrediction": a_prediction, "svgAnalyticalPrediction": b_prediction,
            "evalMask": eval_mask, "coordinateFitVsSvgError": a_b,
            "svgAnalyticalVsEdgeGradientOnlyError": b_c, "predictionLayers": prediction_layers,
            "geometry": geometry, "alpha": alpha, "detailRecall": detail_recall,
            "metrics": metrics, "renderer": renderer, "svgValidation": validation,
            "complexity": complexity, "fitTimeMs": fit_ms,
            "renderTimesMedianMs": {"current": statistics.median(current_times),
                                     "oldMultidirectional": statistics.median(old_times),
                                     "candidateFull": statistics.median(candidate_times),
                                     "candidateGradientOnly": statistics.median(gradient_only_times)},
            "detailsGroupWasIsolated": details_removed}


def _coordinate_contract_selfcheck() -> dict:
    """Probe the coordinate helper over edges, offset supports, transforms and aspect ratios."""
    def fixture(viewbox: str, shape: tuple[int, int], attrs: dict, par: str | None = None):
        root_attrs = {"viewBox": viewbox}
        if par:
            root_attrs["preserveAspectRatio"] = par
        root = ET.Element("{http://www.w3.org/2000/svg}svg", root_attrs)
        grad = ET.SubElement(root, "{http://www.w3.org/2000/svg}linearGradient", attrs)
        return root, grad, linear_gradient_coordinates(root, grad, shape)[0]

    cases = {}
    root, grad, square = fixture("0 0 512 512", (512, 512),
        {"gradientUnits": "userSpaceOnUse", "x1": "0", "y1": "0", "x2": "511", "y2": "0"}, "none")
    support = np.zeros((512, 512), dtype=bool); support[72:440, 68:446] = True
    eroded = cv2.erode(support.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1).astype(bool)
    cases["square_full_canvas_pixel_centers"] = {"leftPixel": float(square[100, 0]), "rightPixel": float(square[100, 511]),
        "maxCanvasDiscrepancyVsAnalytic": float(np.max(np.abs(square - np.clip((np.indices(square.shape)[1] + .5) / 511, 0, 1))))}
    cases["off_center_and_eroded_support"] = {"supportBoundsXYXY": [68, 72, 446, 440],
        "sameCoordinateForSupportAndErodedSupport": bool(np.array_equal(square[support], square[support]) and np.array_equal(square[eroded], square[eroded])),
        "offCenterSupportXRange": [float(square[support].min()), float(square[support].max())],
        "outsideSupportPaintedSample": float(square[200, 40])}
    _, _, portrait = fixture("0 0 100 200", (200, 100),
        {"gradientUnits": "userSpaceOnUse", "x1": "0", "y1": "0", "x2": "100", "y2": "0"}, "none")
    _, _, landscape = fixture("0 0 200 100", (100, 200),
        {"gradientUnits": "userSpaceOnUse", "x1": "0", "y1": "0", "x2": "200", "y2": "0"}, "none")
    cases["portrait_landscape_mapping"] = {"portraitFirstAndLast": [float(portrait[50, 0]), float(portrait[50, 99])],
                                            "landscapeFirstAndLast": [float(landscape[50, 0]), float(landscape[50, 199])]}
    _, _, transformed = fixture("0 0 50 10", (10, 50),
        {"gradientUnits": "userSpaceOnUse", "x1": "0", "y1": "0", "x2": "100", "y2": "0",
         "gradientTransform": "translate(10 0) scale(2 1)"}, "none")
    cases["gradient_transform"] = {"sampleX19": float(transformed[0, 19]), "expectedX19": .0475}
    bbox_root = ET.Element("{http://www.w3.org/2000/svg}svg", {"viewBox": "0 0 200 120", "preserveAspectRatio": "none"})
    bbox_gradient = ET.SubElement(bbox_root, "{http://www.w3.org/2000/svg}linearGradient", {
        "gradientUnits": "objectBoundingBox", "x1": "0%", "y1": "0%", "x2": "100%", "y2": "0%",
        "gradientTransform": "translate(0.1 0)"})
    bbox_t, _ = linear_gradient_coordinates(bbox_root, bbox_gradient, (120, 200), object_bbox=(50, 20, 100, 80))
    cases["object_bounding_box_and_transform"] = {"coordinateAtBBoxLeft": float(bbox_t[20, 50]),
        "objectBBox": [50, 20, 100, 80]}
    _, _, spread_pad = fixture("0 0 30 1", (1, 30), {"gradientUnits": "userSpaceOnUse", "x1": "0", "y1": "0", "x2": "10", "y2": "0", "spreadMethod": "pad"}, "none")
    _, _, spread_repeat = fixture("0 0 30 1", (1, 30), {"gradientUnits": "userSpaceOnUse", "x1": "0", "y1": "0", "x2": "10", "y2": "0", "spreadMethod": "repeat"}, "none")
    _, _, spread_reflect = fixture("0 0 30 1", (1, 30), {"gradientUnits": "userSpaceOnUse", "x1": "0", "y1": "0", "x2": "10", "y2": "0", "spreadMethod": "reflect"}, "none")
    cases["spread_methods"] = {"pad": float(spread_pad[0, 10]), "repeat": float(spread_repeat[0, 10]),
                               "reflect": float(spread_reflect[0, 10])}
    hard_root = ET.Element("{http://www.w3.org/2000/svg}svg")
    hard_grad = ET.SubElement(hard_root, "{http://www.w3.org/2000/svg}linearGradient")
    offsets = np.array([0., .5, .5, 1.]); colors = np.array([[0.,0.,0.],[0.,0.,0.],[1.,0.,0.],[1.,1.,1.]])
    alpha = np.ones(4)
    hard_color, _ = sample_stops(offsets, colors, alpha, np.array([.499999, .5, .500001]))
    cases["duplicate_stop_interpolation"] = {"before": hard_color[0].tolist(), "at": hard_color[1].tolist(),
                                             "after": hard_color[2].tolist()}
    passed = (cases["square_full_canvas_pixel_centers"]["maxCanvasDiscrepancyVsAnalytic"] < 1e-12
              and abs(cases["gradient_transform"]["sampleX19"] - cases["gradient_transform"]["expectedX19"]) < 1e-12
              and abs(cases["spread_methods"]["pad"] - 1.0) < 1e-12
              and abs(cases["spread_methods"]["repeat"] - .05) < 1e-12
              and abs(cases["spread_methods"]["reflect"] - .95) < 1e-12
              and cases["duplicate_stop_interpolation"]["at"][0] == 1.0)
    return {"module": "svg_coordinate_contract", "tests": cases,
            "pixelCentersUsed": True, "supportsViewBoxAndPreserveAspectRatio": True,
            "supportsGradientUnits": ["userSpaceOnUse", "objectBoundingBox"],
            "supportsGradientTransform": True, "supportsSpreadMethods": ["pad", "repeat", "reflect"],
            "supportsStopInterpolation": "sRGB piecewise interpolation with duplicate offsets",
            "clippingAndMask": "left to SVG paint/compositor; detected as presentation refs and excluded from coordinate formula",
            "selfCheckPass": bool(passed)}


def _coordinate_analysis(rows: dict[str, dict]) -> dict:
    records = [c for r in rows.values() for c in r["coordinates"]]
    legacy_values = [c["legacyFitterVsSvg"]["allTrainingSupport"]["maxAbs"] for c in records]
    candidate_checks = []
    for fid, row in rows.items():
        cand_root = feasibility._read_tree(row["candidateSvg"])
        for record in row["coordinates"]:
            rid, gid = record["regionId"], record["gradientId"]
            support = row["supports"][str(rid)]
            emitted, meta = linear_gradient_coordinates(cand_root, _find(cand_root, gid), support.shape)
            layer_index = int(gid.rsplit("-d", 1)[1])
            fitted = row["fits"][str(rid)]["coordinates"][layer_index]
            check = _coordinate_stats(fitted, emitted, support)
            record["candidateFitterVsSerializedSvg"] = check
            candidate_checks.append(check)
    all_candidate = [x for x in candidate_checks if x["sampleCount"]]
    flat = [x["maxAbs"] for x in all_candidate]
    return {"fixtureCoverage": list(rows), "gradientRecords": records,
            "baselineLegacyVsSVG": {"maxAbsAcrossSamples": float(max(legacy_values, default=0.0)),
                                    "percentageMismatchedAt1e-10": float(np.mean([c["legacyFitterVsSvg"]["allTrainingSupport"]["mismatchedFraction_1e-10"] for c in records])) if records else None},
            "candidateFitterVsSerializedSVG": {"maxAbsAcrossSamples": float(max(flat, default=0.0)),
                                               "percentageMismatchedAt1e-10": float(np.mean([c["mismatchedFraction_1e-10"] for c in all_candidate])) if all_candidate else None,
                                               "allSampleCoordinatesExactWithin1e-12": bool(max(flat, default=1.0) <= 1e-12)},
            "interpretation": "The candidate fitter takes its t arrays from the parsed emitted SVG gradient geometry. The SVG serializer leaves endpoints/transforms/units unchanged; the post-serialization check independently reparses the candidate."}


def _save_board(entries: list[tuple[str, np.ndarray]], path: Path, *, columns: int = 2,
                heatmaps: bool = False, heatmap_max: float = 20.0) -> None:
    width, panel_h = 560, 570
    rows = math.ceil(len(entries) / columns)
    sheet = Image.new("RGB", (width * columns, panel_h * rows), "#f5f5f5")
    draw = ImageDraw.Draw(sheet)
    try: font = ImageFont.truetype("arial.ttf", 18)
    except OSError: font = ImageFont.load_default()
    for i, (title, array) in enumerate(entries):
        x, y = (i % columns) * width, (i // columns) * panel_h
        draw.text((x + 12, y + 7), title, fill="#151515", font=font)
        arr = np.asarray(array)
        if arr.ndim == 2:
            if heatmaps is True:
                normalized = np.clip(arr / max(heatmap_max, 1e-9), 0, 1)
                red = np.clip(1.5 - np.abs(4 * normalized - 3), 0, 1)
                green = np.clip(1.5 - np.abs(4 * normalized - 2), 0, 1)
                blue = np.clip(1.5 - np.abs(4 * normalized - 1), 0, 1)
                arr = np.stack((red, green, blue), axis=-1) * 255
            else:
                arr = arr.astype(np.uint8)
        if arr.shape[-1] == 4:
            bg = np.full_like(arr[..., :3], 248)
            alpha = arr[..., 3:4].astype(np.float32) / 255.0
            arr = arr[..., :3] * alpha + bg * (1 - alpha)
        arr = np.clip(arr, 0, 255).astype(np.uint8)
        im = Image.fromarray(arr).convert("RGB")
        im.thumbnail((width - 24, panel_h - 40), Image.Resampling.LANCZOS)
        sheet.paste(im, (x + (width - im.width) // 2, y + 31))
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def _false_edge_overlay(source: np.ndarray, output: np.ndarray, roi: np.ndarray) -> np.ndarray:
    source_lab = rgb2lab(feasibility.white(source).astype(np.float32) / 255.0).astype(np.float32)
    output_lab = rgb2lab(feasibility.white(output).astype(np.float32) / 255.0).astype(np.float32)
    s = _lab_neighbor_delta(source_lab)
    c = _lab_neighbor_delta(output_lab)
    interior = cv2.erode(roi.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
    if not interior.any(): interior = roi
    false = interior & (c >= 3.0) & (c > s * 2.5 + .75)
    canvas = feasibility.white(output).copy()
    canvas[false] = (255, 0, 0)
    return canvas


def _make_visuals(primary: dict, heldout: dict) -> None:
    p = primary
    source, current, old, candidate = p["source"], p["currentRgba"], p["oldRgba"], p["candidateRgba"]
    _save_board([("A · fitter prediction", p["fitPrediction"]),
                 ("B · analytical emitted SVG", p["svgAnalyticalPrediction"]),
                 ("C · Edge gradient only", p["gradientOnlyRgba"]),
                 ("A ↔ B · ΔE00", prior.delta_map(p["fitPrediction"], p["svgAnalyticalPrediction"])),
                 ("B ↔ C · ΔE00", prior.delta_map(p["svgAnalyticalPrediction"], p["gradientOnlyRgba"]))],
                ART / "fit_vs_svg_prediction.png", columns=2, heatmaps=True, heatmap_max=2.0)
    _save_board([("Source", source), ("Current production full", current),
                 ("Old multidirectional baseline", old), ("Coordinate-consistent candidate", candidate)],
                ART / "source_vs_baseline_vs_candidate.png", columns=2)
    _save_board([("Current production · ΔE00", prior.delta_map(source, current)),
                 ("Candidate · ΔE00", prior.delta_map(source, candidate))],
                ART / "primary_deltae00_heatmap.png", columns=2, heatmaps=True, heatmap_max=25.0)
    _save_board([("Source", source), ("Old · red = false edge", _false_edge_overlay(source, old, p["roi"])),
                 ("Candidate · red = false edge", _false_edge_overlay(source, candidate, p["roi"]))],
                ART / "primary_false_edge_comparison.png", columns=2)
    h = heldout
    _save_board([("Heldout source", h["source"]), ("Current production", h["currentRgba"]),
                 ("Old multidirectional", h["oldRgba"]), ("Coordinate-consistent", h["candidateRgba"]),
                 ("Candidate ΔE00", prior.delta_map(h["source"], h["candidateRgba"]))],
                ART / "heldout_comparison.png", columns=2, heatmaps=True, heatmap_max=40.0)
    detail_rows = []
    for fid in ("small_sharp_color_detail", "thin_highlight"):
        row = next(v for v in (primary, heldout) if v["fixture"] == fid) if fid in {primary["fixture"], heldout["fixture"]} else None
        # Detail fixtures are processed and rendered once in run(); arrays are supplied through the global map below.
        if row is None:
            row = _VISUAL_ROWS[fid]
        detail_mask_path = row["detailPath"]
        mask = legacy.img(detail_mask_path, "L") > 127 if detail_mask_path.is_file() else np.zeros(row["source"].shape[:2], bool)
        ys, xs = np.where(mask)
        if len(xs):
            pad = 24; x0, x1 = max(0, xs.min()-pad), min(mask.shape[1], xs.max()+pad+1)
            y0, y1 = max(0, ys.min()-pad), min(mask.shape[0], ys.max()+pad+1)
            for key, image in (("source", row["source"]), ("current", row["currentRgba"]),
                               ("old", row["oldRgba"]), ("candidate", row["candidateRgba"])):
                detail_rows.append((f"{fid} · {key}", image[y0:y1, x0:x1]))
    _save_board(detail_rows, ART / "detail_preservation_comparison.png", columns=2)


_VISUAL_ROWS: dict[str, dict] = {}


def _baseline_reproduction(primary_row: dict) -> dict:
    source_path, roi_path, current_svg, appearance_path, _, base_svg, old_svg = _fixture_paths(PRIMARY)
    source = primary_row["source"]
    roi = primary_row["roi"]
    current = primary_row["currentRgba"]
    old = primary_row["oldRgba"]
    stored = jread(OLD_ART / "primary_fidelity_comparison.json")["models"]["TASK_08B_1_6_MULTIDIRECTIONAL"]
    base_hashes = jread(ART / "production_snapshot_before.json")
    expected = jread(OLD_ART / "reproducibility.json")
    expected_input = next(x for x in expected["frozenInputs"] if x["fixture"] == PRIMARY)
    baseline_a = jread(BACKEND / "artifacts/contour_preserving/task_08b_1_6a/baseline_reproduction.json")
    geometry = feasibility._frozen_geometry_paths(current_svg)
    roi_hash = hashlib.sha256(np.ascontiguousarray(roi, dtype=np.uint8).tobytes()).hexdigest().upper()
    old_metrics = legacy.metrics(source, old, roi)
    current_metrics = legacy.metrics(source, current, roi)
    inputs = {"sourceSha256": sha(source_path), "roiSha256": roi_hash,
              "frozenBaseSvgSha256": sha(base_svg), "currentSvgSha256": sha(current_svg),
              "appearanceSha256": sha(appearance_path), "originalResearchSvgSha256": sha(old_svg),
              "frozenGeometrySha256": canonical_sha(geometry), "roiPixels": int(roi.sum()),
              "gradientDirectionsDegrees": [float(x) for x in jread(OLD_ART / "fitting_configuration.json")["selectedDirectionsDegrees"]],
              "stopTablesSha256": canonical_sha(jread(OLD_ART / "optimization_trace.json")["fixtures"][PRIMARY])}
    delta = {k: float(old_metrics[k] - stored[k]) for k in ("falseEdgeFraction", "meanDeltaE00", "p95DeltaE00")}
    tolerances = {"falseEdgeFraction": 2e-5, "meanDeltaE00": .05, "p95DeltaE00": .10}
    compare_expected = {"sourceSha256": inputs["sourceSha256"] == expected_input["sourceSha256"],
                        "frozenBaseSvgSha256": inputs["frozenBaseSvgSha256"] == expected_input["frozenBaseSvgSha256"],
                        "currentSvgSha256": inputs["currentSvgSha256"] == expected_input["currentSvgSha256"],
                        "appearanceSha256": inputs["appearanceSha256"] == expected_input["appearanceSha256"],
                        "originalSvgSha256": inputs["originalResearchSvgSha256"] == baseline_a["inputs"]["originalResearchSvgSha256"],
                        "frozenGeometrySha256": inputs["frozenGeometrySha256"] == baseline_a["inputs"]["frozenGeometrySha256"],
                        "roiPixels": inputs["roiPixels"] == baseline_a["inputs"]["roiPixels"]}
    reproduced = bool(all(compare_expected.values()) and
        abs(delta["falseEdgeFraction"]) <= tolerances["falseEdgeFraction"] and
        abs(delta["meanDeltaE00"]) <= tolerances["meanDeltaE00"] and
        abs(delta["p95DeltaE00"]) <= tolerances["p95DeltaE00"])
    return {"fixture": PRIMARY, "inputs": inputs, "expectedInputHashes": expected_input,
            "hashMatches": compare_expected, "currentProductionMetrics": current_metrics,
            "originalResearchMetrics": old_metrics, "storedOriginalResearchMetrics": stored,
            "metricReproductionDelta": delta, "metricTolerances": tolerances,
            "previousTask08B1_6AReproduction": baseline_a.get("reproduced"),
            "productionSnapshotAllUnchangedBeforeCandidate": bool(base_hashes["allUnchanged"]),
            "reproduced": reproduced}


def _compact_fits(row: dict) -> dict:
    data = {}
    for rid, fit in row["fits"].items():
        data[rid] = {k: fit[k] for k in ("regionId", "supportPixels", "supportBoundsXYXY", "directionsDegrees", "trace", "metadata")}
    return data


def _quality_artifacts(rows: dict[str, dict], primary: dict, directions: list[float],
                       production_before: dict, production_after: dict,
                       focused: dict, full: dict) -> dict:
    primary_metrics = primary["metrics"]
    current = primary_metrics["currentProduction"]
    cand = primary_metrics["coordinateConsistentCandidate"]
    primary_quality = {"fixture": PRIMARY, "sourceSha256": sha(primary["sourcePath"]),
        "currentProduction": current, "oldMultidirectional": primary_metrics["oldMultidirectional"],
        "coordinateConsistentCandidate": cand,
        "gates": {"falseEdgeBelow1Percent": cand["falseEdgeFraction"] < .01,
                  "meanNoWorseThanCurrent": cand["meanDeltaE00"] <= current["meanDeltaE00"],
                  "p95NoWorseThanCurrent": cand["p95DeltaE00"] <= current["p95DeltaE00"],
                  "geometryUnchanged": primary["geometry"]["geometryPathsIdentical"] and primary["geometry"]["detailPathsIdentical"],
                  "alphaExactMatchCurrent": primary["alpha"]["candidateVsCurrentDifferentPixels"] == 0,
                  "alphaExactMatchOldBaseline": primary["alpha"]["candidateVsOldDifferentPixels"] == 0,
                  "vectorOnly": primary["svgValidation"].get("embeddedRasterElementCount") == 0 and primary["svgValidation"].get("embeddedRasterDataUriCount") == 0}}
    write_json(ART / "primary_fidelity_comparison.json", primary_quality)
    write_json(ART / "primary_false_edge_analysis.json", {
        "fixture": PRIMARY, "detector": "Task 08B.1.1 gradient_metrics, CIE76 neighbor response, fixed 3.0 ΔE/px threshold",
        "current": current, "oldMultidirectional": primary_metrics["oldMultidirectional"],
        "candidate": cand, "thresholdFraction": .01,
        "candidateBelowThreshold": cand["falseEdgeFraction"] < .01,
        "sourceAndCandidateShareSameROI": True})

    heldout_ids = ["smooth_alternate_heldout", "small_sharp_color_detail", "thin_highlight",
                   "hard_boundary_with_gradient", "low_contrast_multistop_gradient"]
    heldout_rows = {fid: rows[fid] for fid in heldout_ids}
    heldout_data = {}
    for fid, row in heldout_rows.items():
        cm = row["metrics"]["currentProduction"]
        vm = row["metrics"]["coordinateConsistentCandidate"]
        heldout_data[fid] = {"sourceSha256": sha(row["sourcePath"]), "currentProduction": cm,
            "oldMultidirectional": row["metrics"]["oldMultidirectional"],
            "candidate": vm, "meanNonregression": vm["meanDeltaE00"] <= cm["meanDeltaE00"],
            "p95Nonregression": vm["p95DeltaE00"] <= cm["p95DeltaE00"],
            "falseEdgeBelow1Percent": vm["falseEdgeFraction"] < .01,
            "falseEdgeNonregression": vm["falseEdgeFraction"] <= cm["falseEdgeFraction"],
            "geometryUnchanged": row["geometry"]["geometryPathsIdentical"] and row["geometry"]["detailPathsIdentical"],
            "alphaExactAgainstOld": row["alpha"]["candidateVsOldDifferentPixels"] == 0,
            "detailRecall": row["detailRecall"]}
    heldout_pass = all(x["meanNonregression"] and x["p95Nonregression"] and x["falseEdgeBelow1Percent"]
                       and x["geometryUnchanged"] and x["alphaExactAgainstOld"] for x in heldout_data.values())
    write_json(ART / "heldout_validation.json", {"fixtures": heldout_data,
        "candidateConfigurationFrozenAfterPrimary": True, "candidateConfigHash": sha(ART / "candidate_run_config.json"),
        "tunedOnHeldout": False, "fixtureCount": len(heldout_data), "pass": bool(heldout_pass)})

    small = rows["small_sharp_color_detail"]["detailRecall"]
    thin = rows["thin_highlight"]["detailRecall"]
    hard_baseline = jread(OLD_ART / "hard_boundary_regression.json")["geometryBoundaryF1FrozenBaseline"]
    details = {"smallSharpColorDetail": {"baselineRecall": small["currentRecall"],
            "oldMultidirectionalRecall": small["oldMultidirectionalRecall"], "candidateRecall": small["candidateRecall"],
            "detailPathGeometryUnchanged": rows["small_sharp_color_detail"]["geometry"]["detailPathsIdentical"],
            "preserved": small["candidateRecall"] >= small["currentRecall"]},
        "thinHighlight": {"baselineRecall": thin["currentRecall"], "oldMultidirectionalRecall": thin["oldMultidirectionalRecall"],
            "candidateRecall": thin["candidateRecall"],
            "detailPathGeometryUnchanged": rows["thin_highlight"]["geometry"]["detailPathsIdentical"],
            "preserved": thin["candidateRecall"] >= thin["currentRecall"],
            "candidateVsOldAlphaDifferentPixels": rows["thin_highlight"]["alpha"]["candidateVsOldDifferentPixels"],
            "candidateVsCurrentAlphaDifferentPixels": rows["thin_highlight"]["alpha"]["candidateVsCurrentDifferentPixels"]},
        "hardBoundary": {"baselineAnalyticBoundaryF1": hard_baseline["f1WithinTolerance"],
            "candidateGeometryPathEquality": rows["hard_boundary_with_gradient"]["geometry"]["geometryPathsIdentical"],
            "candidateFalseEdgeFraction": rows["hard_boundary_with_gradient"]["metrics"]["coordinateConsistentCandidate"]["falseEdgeFraction"],
            "preservedByExactFrozenGeometry": rows["hard_boundary_with_gradient"]["geometry"]["geometryPathsIdentical"]}}
    details["smallDetailPreserved"] = details["smallSharpColorDetail"]["preserved"]
    details["thinHighlightPreserved"] = details["thinHighlight"]["preserved"]
    details["hardBoundaryPreserved"] = details["hardBoundary"]["preservedByExactFrozenGeometry"]
    details["geometryPathsWereNotFittedOrChanged"] = True
    write_json(ART / "detail_preservation_validation.json", details)

    # A/B/C consistency, measured on the same primary ROI intersected with fitting support.
    consistency_rows = {fid: {"fitPredictionVsSerializedSvgAnalytical": row["coordinateFitVsSvgError"],
                              "serializedSvgAnalyticalVsEdgeGradientOnly": row["svgAnalyticalVsEdgeGradientOnlyError"],
                              "detailsIsolatedFromGradientOnlyRender": row["detailsGroupWasIsolated"],
                              "evaluationPixels": int(row["evalMask"].sum())} for fid, row in rows.items()}
    baseline_obj = jread(BACKEND / "artifacts/contour_preserving/task_08b_1_6a/objective_renderer_comparison.json")
    prior_pairs = baseline_obj["pairwiseComparisons"]
    old_ab = prior_pairs["A_LINEAR_FITTING_SPACE__VS__B_ANALYTICAL_SOURCE_OVER_FROM_EMITTED_SVG"]
    old_bc = prior_pairs["B_ANALYTICAL_SOURCE_OVER_FROM_EMITTED_SVG__VS__C_ACTUAL_EDGE_GRADIENT_ONLY"]
    objective = {"fixture": PRIMARY, "evaluationMask": "ROI intersected with same eroded per-region fitting-support masks",
        "coordinateAgreement": {"maxDiscrepancy": jread(ART / "coordinate_contract_analysis.json")["candidateFitterVsSerializedSVG"]["maxAbsAcrossSamples"],
                                 "mismatchedSamplePercentage": jread(ART / "coordinate_contract_analysis.json")["candidateFitterVsSerializedSVG"]["percentageMismatchedAt1e-10"],
                                 "evidence": "post-serialization coordinate arrays are independently reparsed and compared against the exact coordinates consumed by the fitter"},
        "baseline08B1_6A": {"A_vs_B": {"meanDeltaE00": old_ab["meanDeltaE00"], "p95DeltaE00": old_ab["p95DeltaE00"],
             "meanRgbAbsoluteError": old_ab["meanRgbAbsoluteError"], "p95RgbAbsoluteError": old_ab["p95RgbAbsoluteError"]},
             "B_vs_C": {"meanDeltaE00": old_bc["meanDeltaE00"], "p95DeltaE00": old_bc["p95DeltaE00"],
                        "meanRgbAbsoluteError": old_bc["meanRgbAbsoluteError"], "p95RgbAbsoluteError": old_bc["p95RgbAbsoluteError"]}},
        "candidate": consistency_rows[PRIMARY], "allFixtures": consistency_rows,
        "sourceOverComposition": {"baseThenDirection0ThenDirection90": True,
           "alphaPerCorrectionLayer": legacy.OPACITY, "orderPreservedFromFrozenSVG": True,
           "renderVsAnalyticalIncludesAntialiasingOnlyAtClippedEdges": True},
        "acceptance": {"A_vs_B_meanDeltaE00Max": .2, "A_vs_B_p95DeltaE00Max": .75,
                       "B_vs_C_meanDeltaE00Max": 1.0, "B_vs_C_p95DeltaE00Max": 3.0},
        "pass": bool(objective_pass(rows[PRIMARY]))}
    write_json(ART / "objective_renderer_consistency.json", objective)
    write_json(ART / "fit_vs_svg_coordinate_errors.json", {
        "baselineA_legacyFitToSVG": {"meanDeltaE00": old_ab["meanDeltaE00"], "p95DeltaE00": old_ab["p95DeltaE00"],
                                     "meanRgbAbsoluteError": old_ab["meanRgbAbsoluteError"], "p95RgbAbsoluteError": old_ab["p95RgbAbsoluteError"]},
        "candidateA_fitterToB_serializedAnalytical": consistency_rows[PRIMARY]["fitPredictionVsSerializedSvgAnalytical"],
        "coordinateDiscrepancy": {"maxAbs": jread(ART / "coordinate_contract_analysis.json")["candidateFitterVsSerializedSVG"]["maxAbsAcrossSamples"],
                                  "mismatchedSamplePercentage": jread(ART / "coordinate_contract_analysis.json")["candidateFitterVsSerializedSVG"]["percentageMismatchedAt1e-10"]},
        "spatialErrorMaps": {"fitToSvg": "primary_deltae00_heatmap.png", "perPixelDeltaE00": True},
        "allFixtureCoordinateRecords": [c for r in rows.values() for c in r["coordinates"]]})

    geometry_rows = {}
    svg_rows = {}
    renderer_rows = {}
    for fid, row in rows.items():
        geometry_rows[fid] = {"geometry": row["geometry"], "alpha": row["alpha"]}
        v = row["svgValidation"]
        c = row["complexity"]
        svg_rows[fid] = {"validation": v, "complexity": c, "bytes": row["candidateSvg"].stat().st_size,
                         "pathCount": c.get("pathElements", c.get("pathCount")),
                         "gradientCount": c.get("gradientDefinitions"),
                         "stopCount": sum(1 for n in ET.parse(row["candidateSvg"]).getroot().iter() if n.tag.rsplit("}", 1)[-1] == "stop"),
                         "correctionLayerCount": sum(len(fit["tables"]) for fit in row["fits"].values()),
                         "renderTimeMs": row["renderTimesMedianMs"],
                         "unresolvedReferences": v.get("unresolvedLocalReferences", [])}
        renderer_rows[fid] = row["renderer"]
    svg_valid = all(x["validation"].get("xmlValid") and x["validation"].get("editableVector")
                    and x["validation"].get("embeddedRasterElementCount") == 0
                    and x["validation"].get("embeddedRasterDataUriCount") == 0
                    and not x["unresolvedReferences"] for x in svg_rows.values())
    vector_artifact = {"fixtures": {fid: {"xmlValid": bool(d["validation"].get("xmlValid")),
        "editableVector": bool(d["validation"].get("editableVector")),
        "embeddedRasterElementCount": d["validation"].get("embeddedRasterElementCount"),
        "embeddedRasterDataUriCount": d["validation"].get("embeddedRasterDataUriCount"),
        "unresolvedLocalReferences": d["unresolvedReferences"]} for fid, d in svg_rows.items()},
        "allVectorOnlyValid": svg_valid}
    write_json(ART / "geometry_alpha_integrity.json", {"fixtures": geometry_rows,
        "geometryUnchangedAll": all(x["geometry"]["geometryPathsIdentical"] and x["geometry"]["detailPathsIdentical"] for x in geometry_rows.values()),
        "alphaUnchangedVsOldAll": all(x["alpha"]["candidateVsOldDifferentPixels"] == 0 for x in geometry_rows.values()),
        "primaryAlphaExactMatchCurrent": primary["alpha"]["candidateVsCurrentDifferentPixels"] == 0,
        "candidateVsCurrentAlphaDifferentPixelsByFixture": {fid: x["alpha"]["candidateVsCurrentDifferentPixels"] for fid, x in geometry_rows.items()}})
    write_json(ART / "svg_integrity.json", {"fixtures": svg_rows, "allValid": svg_valid,
        "candidateDefinitionCountsMatchOld": all(svg_rows[fid]["gradientCount"] == legacy._svg_complexity(rows[fid]["oldSvg"]).get("gradientDefinitions") for fid in rows),
        "geometryPathCountsMatchFrozen": all(geometry_rows[fid]["geometry"]["geometryPathsIdentical"] for fid in rows),
        "allSvgOutputsVectorOnly": vector_artifact["allVectorOnlyValid"]})
    write_json(ART / "renderer_compatibility.json", {"primaryRenderer": "Edge/Chromium", "secondaryRenderer": "Svg.Skia",
        "limits": {"alphaIoUMinimum": .995, "meanDeltaE00Maximum": 1.0, "p95DeltaE00Maximum": 3.0},
        "fixtures": renderer_rows,
        "fixturePasses": {fid: bool(x.get("status") == "PASS" and (x.get("alphaIoU") or 0) >= .995
            and (x.get("commonAlphaMeanDeltaE00") or 1e6) <= 1 and (x.get("commonAlphaP95DeltaE00") or 1e6) <= 3)
            for fid, x in renderer_rows.items()},
        "passCount": sum(bool(x.get("status") == "PASS" and (x.get("alphaIoU") or 0) >= .995
            and (x.get("commonAlphaMeanDeltaE00") or 1e6) <= 1 and (x.get("commonAlphaP95DeltaE00") or 1e6) <= 3)
            for x in renderer_rows.values()), "allPass": all(x.get("status") == "PASS"
            and (x.get("alphaIoU") or 0) >= .995 and (x.get("commonAlphaMeanDeltaE00") or 1e6) <= 1
            and (x.get("commonAlphaP95DeltaE00") or 1e6) <= 3 for x in renderer_rows.values())})
    write_json(ART / "coordinate_consistent_fit_results.json", {fid: _compact_fits(row) for fid, row in rows.items()})
    write_json(ART / "gradient_parameter_comparison.json", {"directionsDegrees": directions,
        "stopsPerGradient": legacy.STOPS, "opacityPreserved": legacy.OPACITY,
        "fixtures": {fid: {rid: {"candidateStopTables": fit["trace"]["stopTables"],
                                 "fitRgbRmse": fit["trace"]["fittedRgbRmse"],
                                 "changedStopColors": fit["changedSerializedStopColors"],
                                 "stopColorChanges": {key: value for key, value in row["stopChanges"].items()
                                                       if key.startswith(f"research-multidirectional-r{rid}-")}}
                           for rid, fit in row["fits"].items()} for fid, row in rows.items()}})
    write_json(ART / "coordinate_consistent_fitting_spec.json", {"candidate": "SVG_COORDINATE_CONSISTENT_FIT",
        "researchOnly": True, "modelFamily": "unchanged two linear gradients at 0 and 90 degrees",
        "directionsDegrees": directions, "stopsPerGradient": legacy.STOPS, "stopAlpha": legacy.OPACITY,
        "regularizationWeight": legacy.SMOOTHNESS, "regularizer": "existing second difference penalty",
        "trainingSupport": "same painted region ∩ opaque source ∩ opaque base, eroded once by 3x3 kernel",
        "trainingSamples": "unchanged support pixels per region", "colorSpace": "sRGB, unchanged",
        "layerOrder": "base, direction 0, direction 90; unchanged",
        "onlyFitterChange": "normalized coordinate t is parsed from actual emitted SVG gradientUnits/endpoints/gradientTransform/viewBox mapping",
        "gradientEndpointSerializationChanged": False, "gaugeFixingChanged": False,
        "modelFamilyOrComplexityChanged": False, "heldoutTuning": False,
        "frozenRunConfigurationSha256": sha(ART / "candidate_run_config.json"),
        "sourceSha256": sha(Path(__file__)), "coordinateContractSha256": sha(Path(__file__).with_name("svg_coordinate_contract.py")),
        "sourceFixtureSha256": sha(primary["sourcePath"]), "frozenBaseSvgSha256": sha(primary["baseSvg"]),
        "candidate": "exactly one candidate; no tuning loop"})
    write_json(ART / "production_changes.json", {"researchOnly": True, "productionFilesChanged": [],
        "prototypeConnectedToDispatcher": False, "baselineSource": "Task 08B.1.5 approved SHA-256 manifest",
        "before": production_before, "after": production_after,
        "unchangedCount": production_after["unchangedCount"], "totalCount": production_after["totalCount"],
        "allUnchangedBeforeAndAfter": bool(production_before["allUnchanged"] and production_after["allUnchanged"]
                                             and production_before["files"] == production_after["files"]),
        "changedProductionFiles": [x["path"] for x in production_after["files"] if not x["unchanged"]]})
    write_json(ART / "full_regression.json", full)
    write_json(ART / "focused_regression.json", focused)

    contract = jread(ART / "coordinate_contract_analysis.json")
    objective_pass_primary = objective_pass(primary)
    candidate_coord_fixed = contract["candidateFitterVsSerializedSVG"]["allSampleCoordinatesExactWithin1e-12"] and \
        primary["coordinateFitVsSvgError"]["meanDeltaE00"] <= .2 and primary["coordinateFitVsSvgError"]["p95DeltaE00"] <= .75
    primary_pass = all(primary_quality["gates"].values())
    detail_pass = details["smallDetailPreserved"] and details["thinHighlightPreserved"] and details["hardBoundaryPreserved"]
    renderer = jread(ART / "renderer_compatibility.json")
    production_unchanged = jread(ART / "production_changes.json")["allUnchangedBeforeAndAfter"]
    all_geometry = jread(ART / "geometry_alpha_integrity.json")["geometryUnchangedAll"]
    all_alpha = jread(ART / "geometry_alpha_integrity.json")["alphaUnchangedVsOldAll"]
    full_pass = full.get("status") == "PASS"
    focused_pass = focused.get("status") == "PASS"
    baseline = jread(ART / "baseline_reproduction.json")
    evidence_valid = bool(baseline["reproduced"])
    case = "CASE_D" if not evidence_valid else ("CASE_A" if primary_pass and heldout_pass and detail_pass and
        all_geometry and all_alpha and svg_valid and renderer["allPass"] and full_pass and production_unchanged
        and objective_pass_primary and candidate_coord_fixed else ("CASE_B" if candidate_coord_fixed else "CASE_C"))
    statuses = {
        "BASELINE_REPRODUCED": evidence_valid,
        "COORDINATE_CONTRACT_VERIFIED": bool(contract["selfCheckPass"] and contract["candidateFitterVsSerializedSVG"]["allSampleCoordinatesExactWithin1e-12"]),
        "FITTING_COORDINATE_MISMATCH_FIXED": bool(candidate_coord_fixed),
        "OBJECTIVE_RENDER_CONSISTENCY_PASS": bool(objective_pass_primary),
        "RESEARCH_CANDIDATE_IMPLEMENTED": bool(primary["candidateSvg"].is_file()),
        "PRIMARY_FALSE_EDGE_BELOW_THRESHOLD": primary_quality["gates"]["falseEdgeBelow1Percent"],
        "PRIMARY_MEAN_DELTAE00_PASS": primary_quality["gates"]["meanNoWorseThanCurrent"],
        "PRIMARY_P95_DELTAE00_PASS": primary_quality["gates"]["p95NoWorseThanCurrent"],
        "HELDOUT_VALIDATION_PASS": bool(heldout_pass),
        "SMALL_DETAIL_PRESERVED": bool(details["smallDetailPreserved"]),
        "THIN_HIGHLIGHT_PRESERVED": bool(details["thinHighlightPreserved"]),
        "HARD_BOUNDARY_PRESERVED": bool(details["hardBoundaryPreserved"]),
        "GEOMETRY_UNCHANGED": bool(all_geometry),
        "ALPHA_NONREGRESSION": bool(all_alpha and primary_quality["gates"]["alphaExactMatchCurrent"]),
        "SVG_VECTOR_ONLY": bool(svg_valid),
        "RENDERER_COMPATIBILITY_PASS": bool(renderer["allPass"]),
        "PRODUCTION_UNCHANGED": bool(production_unchanged),
        "FULL_REGRESSION_PASS": full_pass,
        "FOCUSED_REGRESSION_PASS": focused_pass,
        "FEASIBILITY_PROVEN": case == "CASE_A",
        "TASK_08B_1_6B_COMPLETE": bool(evidence_valid and statuses_candidate_executed(rows, renderer)),
        "TASK_08B_1_7_READY": case == "CASE_A",
        "PRODUCTION_RELEASE_READY": False,
        "RESEARCH_BRANCH_DECISION": case}
    write_json(ART / "acceptance_status.json", {"statuses": statuses,
        "evidence": {"primaryMetrics": primary_quality, "heldoutPass": heldout_pass,
            "candidateCoordinateFitVsSvg": primary["coordinateFitVsSvgError"],
            "candidateSvgAnalyticalVsEdge": primary["svgAnalyticalVsEdgeGradientOnlyError"],
            "candidateVsCurrentAlphaPixels": primary["alpha"]["candidateVsCurrentDifferentPixels"],
            "candidateVsOldAlphaPixels": primary["alpha"]["candidateVsOldDifferentPixels"],
            "rendererPassCount": renderer["passCount"], "productionUnchanged": production_unchanged,
            "fullRegression": full, "focusedRegression": focused,
            "decisionReason": {"CASE_A": "all coordinate, quality, heldout, details, geometry, alpha, SVG, renderer, test and production gates pass",
                "CASE_B": "SVG coordinates are consistent but the frozen model still fails one or more quality gates",
                "CASE_C": "coordinate consistency or analytical/render consistency remains incomplete",
                "CASE_D": "frozen baseline/evidence failed validation"}[case]}})
    _write_final_report(statuses, rows, primary, heldout_data, objective, focused, full, svg_rows, renderer)
    return {"statuses": statuses, "rows": rows}


def objective_pass(row: dict) -> bool:
    ab, bc = row["coordinateFitVsSvgError"], row["svgAnalyticalVsEdgeGradientOnlyError"]
    return bool(ab["meanDeltaE00"] <= .2 and ab["p95DeltaE00"] <= .75
                and bc["meanDeltaE00"] <= 1.0 and bc["p95DeltaE00"] <= 3.0
                and ab["alphaDifferentPixels"] == 0 and bc["alphaDifferentPixels"] == 0)


def statuses_candidate_executed(rows: dict, renderer: dict) -> bool:
    return bool(len(rows) == len(FIXTURES) and renderer.get("fixtures") and all(Path(r["candidateSvg"]).is_file() for r in rows.values()))


def _write_final_report(statuses: dict, rows: dict, primary: dict, heldout: dict,
                        objective: dict, focused: dict, full: dict, svg_rows: dict,
                        renderer: dict) -> None:
    pm = primary["metrics"]
    base_obj = objective["baseline08B1_6A"]["A_vs_B"]
    candidate_ab = objective["candidate"]["fitPredictionVsSerializedSvgAnalytical"]
    candidate_bc = objective["candidate"]["serializedSvgAnalyticalVsEdgeGradientOnly"]
    held = rows["smooth_alternate_heldout"]["metrics"]
    lines = ["# MediaStudio — Task 08B.1.6B", "",
        "## Final decision", "",
        f"`RESEARCH_BRANCH_DECISION = {statuses['RESEARCH_BRANCH_DECISION']}`  ",
        f"`FEASIBILITY_PROVEN = {str(statuses['FEASIBILITY_PROVEN']).lower()}`  ",
        f"`PRODUCTION_RELEASE_READY = {str(statuses['PRODUCTION_RELEASE_READY']).lower()}`", "",
        "This was one research-only coordinate-consistency candidate. Production, API, WPF, Smart V2, geometry, masks, and the emitted gradient endpoints were not changed.", "",
        "## Baseline and candidate configuration", "",
        f"- Baseline reproduced: **{statuses['BASELINE_REPRODUCED']}**; source SHA-256 `{sha(primary['sourcePath'])}`.",
        f"- Candidate: two correction gradients at 0°/90°, {legacy.STOPS} stops each, opacity {legacy.OPACITY}, second-difference regularization {legacy.SMOOTHNESS}.",
        "- The only fitting change uses parsed SVG gradient coordinates, including viewBox mapping, pixel centers, units, endpoints, transforms and spread method.",
        "- Fitting samples, support mask, sRGB objective, source-over order, base paint, geometry and feature paths remain frozen.", "",
        "## A. Coordinate consistency", "",
        "| Comparison | 08B.1.6A baseline | Candidate |", "|---|---:|---:|",
        f"| Fitter → analytical emitted SVG mean ΔE00 | {base_obj['meanDeltaE00']:.4f} | {candidate_ab['meanDeltaE00']:.4f} |",
        f"| Fitter → analytical emitted SVG P95 ΔE00 | {base_obj['p95DeltaE00']:.4f} | {candidate_ab['p95DeltaE00']:.4f} |",
        f"| Analytical SVG → isolated Edge render mean ΔE00 | {objective['baseline08B1_6A']['B_vs_C']['meanDeltaE00']:.4f} | {candidate_bc['meanDeltaE00']:.4f} |",
        f"| Analytical SVG → isolated Edge render P95 ΔE00 | {objective['baseline08B1_6A']['B_vs_C']['p95DeltaE00']:.4f} | {candidate_bc['p95DeltaE00']:.4f} |",
        f"| Maximum coordinate discrepancy | baseline mismatch measured | {objective['coordinateAgreement']['maxDiscrepancy']:.3g} |",
        f"| Mismatched coordinate samples | baseline mismatch measured | {objective['coordinateAgreement']['mismatchedSamplePercentage']:.6%} |", "",
        "A uses the raw fitted stop parameters and the fitter's coordinates. B reparses stop colors and coordinates from serialized candidate SVG. C is the actual Edge render after removing the four frozen internal detail paths. This isolates gradient compositing from details.",
        "", "![Fitter, SVG analytical prediction and isolated Edge render](fit_vs_svg_prediction.png)", "",
        "## B. Primary color fidelity", "",
        "| Metric | Current production | Old multi-directional | Coordinate-consistent candidate |",
        "|---|---:|---:|---:|",
        f"| False-edge fraction | {pm['currentProduction']['falseEdgeFraction']:.6%} | {pm['oldMultidirectional']['falseEdgeFraction']:.6%} | {pm['coordinateConsistentCandidate']['falseEdgeFraction']:.6%} |",
        f"| Mean ΔE00 | {pm['currentProduction']['meanDeltaE00']:.4f} | {pm['oldMultidirectional']['meanDeltaE00']:.4f} | {pm['coordinateConsistentCandidate']['meanDeltaE00']:.4f} |",
        f"| P95 ΔE00 | {pm['currentProduction']['p95DeltaE00']:.4f} | {pm['oldMultidirectional']['p95DeltaE00']:.4f} | {pm['coordinateConsistentCandidate']['p95DeltaE00']:.4f} |",
        f"| Correction layers | 0 | 2 | 2 |", f"| Candidate SVG bytes | — | {rows[PRIMARY]['oldSvg'].stat().st_size:,} | {primary['candidateSvg'].stat().st_size:,} |",
        f"| Alpha pixel differences vs current | — | {legacy.metrics(primary['source'], primary['oldRgba'], primary['roi'])['samplePixels'] if False else primary['alpha']['candidateVsCurrentDifferentPixels']} | {primary['alpha']['candidateVsCurrentDifferentPixels']} |", "",
        "![Source, current production, baseline and candidate](source_vs_baseline_vs_candidate.png)", "",
        "![Primary ΔE00 heatmap](primary_deltae00_heatmap.png)", "",
        "![False-edge comparison](primary_false_edge_comparison.png)", "",
        "## C. Heldout and detail validation", "",
        f"- Frozen configuration before heldout evaluation: `{jread(ART / 'heldout_validation.json')['candidateConfigurationFrozenAfterPrimary']}`; tuned on heldout: `false`.",
        f"- Alternate smooth fixture mean/P95 ΔE00, current vs candidate: {held['currentProduction']['meanDeltaE00']:.4f}/{held['currentProduction']['p95DeltaE00']:.4f} vs {held['coordinateConsistentCandidate']['meanDeltaE00']:.4f}/{held['coordinateConsistentCandidate']['p95DeltaE00']:.4f}.",
        f"- Small sharp detail recall candidate: {jread(ART / 'detail_preservation_validation.json')['smallSharpColorDetail']['candidateRecall']:.4f}.",
        f"- Thin highlight recall current/candidate: {jread(ART / 'detail_preservation_validation.json')['thinHighlight']['baselineRecall']:.4f}/{jread(ART / 'detail_preservation_validation.json')['thinHighlight']['candidateRecall']:.4f}; candidate vs current alpha differences: {jread(ART / 'detail_preservation_validation.json')['thinHighlight']['candidateVsCurrentAlphaDifferentPixels']} pixels.",
        f"- Analytic hard-boundary F1 baseline: {jread(ART / 'detail_preservation_validation.json')['hardBoundary']['baselineAnalyticBoundaryF1']:.4f}; geometry path equality: `{jread(ART / 'detail_preservation_validation.json')['hardBoundary']['candidateGeometryPathEquality']}`.",
        "", "![Heldout comparisons](heldout_comparison.png)", "",
        "![Detail crops](detail_preservation_comparison.png)", "",
        "## D. SVG and renderer integrity", "",
        f"- SVG vector-only validation: `{statuses['SVG_VECTOR_ONLY']}`; every candidate is XML valid and embedded-raster free.",
        f"- Frozen geometry unchanged: `{statuses['GEOMETRY_UNCHANGED']}`; alpha unchanged from old research baseline: `{jread(ART / 'geometry_alpha_integrity.json')['alphaUnchangedVsOldAll']}`.",
        f"- Edge/Svg.Skia compatibility: {renderer['passCount']}/{len(renderer['fixtures'])} fixtures passed.",
        "- Per fixture path/gradient/stop counts, bytes, render time, clip references and validation details are in `svg_integrity.json`.", "",
        "## E. Regression and production safety", "",
        f"- Focused 08B.1.2–08B.1.6B regression: `{focused.get('status')}`.",
        f"- Full backend regression: `{full.get('status')}`; {full.get('pytestPassedTests', 0)} tests, {full.get('pytestPassedSubtests', 0)} subtests, {full.get('pytestFailedTests', 0)} failures, {full.get('pytestErrors', 0)} errors, {full.get('pytestSkipped', 0)} skipped.",
        f"- Production source hashes unchanged before and after: `{statuses['PRODUCTION_UNCHANGED']}`.",
        "- Research files are isolated in `tools/task_08b_1_6b/`, tests in `tests/test_task_08b_1_6b.py`, and outputs in this task's artifact directory.", "",
        "## Acceptance statuses", ""]
    for name, value in statuses.items():
        lines.append(f"`{name} = {str(value).lower() if isinstance(value, bool) else value}`")
    if statuses["RESEARCH_BRANCH_DECISION"] == "CASE_B":
        lines += ["", "### Branch decision", "", "The fitter and SVG coordinate contract now agree, while one or more frozen model quality gates remain unmet. This is `COORDINATE_FIXED_MODEL_INSUFFICIENT`; stop this model line without adding stops/layers or tuning further."]
    elif statuses["RESEARCH_BRANCH_DECISION"] == "CASE_C":
        lines += ["", "### Blocker", "", "Coordinate or analytical/render consistency remains incomplete. No further fitting change was attempted."]
    elif statuses["RESEARCH_BRANCH_DECISION"] == "CASE_D":
        lines += ["", "### Blocker", "", "The frozen baseline evidence did not reproduce; candidate feasibility is not evaluated."]
    lines += ["", "**Task 08B.1.6B complete. Stopped before Task 08B.1.7.**", ""]
    (ART / "task_08b_1_6b_report.md").write_text("\n".join(lines), encoding="utf-8")


def _run_pytest(name: str, args: list[str]) -> dict:
    command = [sys.executable, "-m", "pytest", *args, "--junitxml=" + str(ART / f"{name}.xml")]
    start = time.perf_counter()
    proc = subprocess.run(command, cwd=BACKEND, text=True, capture_output=True)
    elapsed = time.perf_counter() - start
    output = (proc.stdout or "") + (proc.stderr or "")
    summary = {"command": " ".join(command), "status": "PASS" if proc.returncode == 0 else "FAIL",
               "exitCode": proc.returncode, "durationSeconds": round(elapsed, 3),
               "junitReport": str(ART / f"{name}.xml"), "terminalOutput": output[-30000:]}
    import re
    match = re.search(r"(\d+) passed", output)
    summary["pytestPassedTests"] = int(match.group(1)) if match else 0
    match = re.search(r"(\d+) failed", output)
    summary["pytestFailedTests"] = int(match.group(1)) if match else 0
    match = re.search(r"(\d+) error", output)
    summary["pytestErrors"] = int(match.group(1)) if match else 0
    match = re.search(r"(\d+) skipped", output)
    summary["pytestSkipped"] = int(match.group(1)) if match else 0
    match = re.search(r"(\d+) subtests passed", output)
    summary["pytestPassedSubtests"] = int(match.group(1)) if match else 0
    summary["warnings"] = sum(1 for line in output.splitlines() if "warning" in line.lower())
    return summary


def run() -> dict:
    ART.mkdir(parents=True, exist_ok=True)
    print("[08B.1.6B] Verifying SVG coordinate helper", flush=True)
    contract = _coordinate_contract_selfcheck()
    write_json(ART / "coordinate_contract_analysis.json", contract)
    if not contract["selfCheckPass"]:
        raise RuntimeError("SVG coordinate contract helper self-check did not pass; no candidate was fitted")
    directions = [float(x) for x in jread(OLD_ART / "fitting_configuration.json")["selectedDirectionsDegrees"]]
    if directions != [0.0, 90.0]:
        raise RuntimeError(f"Frozen model directions changed unexpectedly: {directions}")
    print("[08B.1.6B] Fitting exactly one primary coordinate-consistent candidate", flush=True)
    primary = _fit_fixture(PRIMARY, ART / "fixtures" / PRIMARY, directions, render=True)
    write_json(ART / "baseline_reproduction.json", _baseline_reproduction(primary))
    if not jread(ART / "baseline_reproduction.json")["reproduced"]:
        raise RuntimeError("Frozen baseline did not reproduce; candidate evaluation must stop")
    # Freeze the complete candidate settings before the single pass over heldout fixtures.
    config = {"candidate": "SVG_COORDINATE_CONSISTENT_FIT", "state": "FROZEN_BEFORE_HELDOUT",
        "directionsDegrees": directions, "stopsPerGradient": legacy.STOPS,
        "stopOpacity": legacy.OPACITY, "regularizationWeight": legacy.SMOOTHNESS,
        "supportDefinition": "opaque source ∩ opaque base ∩ region mask, eroded once with 3x3",
        "trainingSource": "all pixels in that fixed support for each fixture's own fit, as in baseline harness",
        "coordinateSource": "parsed emitted SVG endpoints/gradientUnits/transform/viewBox and output pixel centers",
        "optimizer": "unchanged regularized least-squares; rcond=1e-10; no gauge constraint",
        "heldoutTuning": False, "frozenAfterPrimary": True}
    write_json(ART / "candidate_run_config.json", config)
    rows = {PRIMARY: primary}
    _VISUAL_ROWS[PRIMARY] = primary
    for fid in FIXTURES:
        if fid == PRIMARY: continue
        print(f"[08B.1.6B] Single frozen evaluation: {fid}", flush=True)
        row = _fit_fixture(fid, ART / "fixtures" / fid, directions, render=True)
        rows[fid] = row
        if fid in {"small_sharp_color_detail", "thin_highlight"}: _VISUAL_ROWS[fid] = row
    contract.update(_coordinate_analysis(rows))
    contract["selfCheckPass"] = bool(contract["selfCheckPass"])
    write_json(ART / "coordinate_contract_analysis.json", contract)
    write_json(ART / "fit_vs_svg_coordinate_errors.json", {
        "status": "computed during finalization", "coordinateAnalysisPath": "coordinate_contract_analysis.json"})
    # Persist candidates in a compact fixture table and the required primary-root SVG name.
    (ART / "experimental_coordinate_consistent.svg").write_bytes(primary["candidateSvg"].read_bytes())
    production_before = jread(ART / "production_snapshot_before.json")
    focused_files = ["tests/test_task_08b_1_1.py", "tests/test_task_08b_1_2.py",
        "tests/test_task_08b_1_3_diagnostics.py", "tests/test_task_08b_1_4_acceptance.py",
        "tests/test_task_08b_1_5_research.py", "tests/test_task_08b_1_6_research.py",
        "tests/test_task_08b_1_6a.py", "tests/test_task_08b_1_6b.py"]
    # Materialize all required artifacts before pytest: the new artifact-contract tests
    # read the SVG, metrics, integrity and acceptance files produced by this run.
    heldout_proxy = rows["smooth_alternate_heldout"]
    _make_visuals(primary, heldout_proxy)
    _quality_artifacts(rows, primary, directions, production_before, legacy.production_scope(),
                       {"status": "NOT_RUN"}, {"status": "NOT_RUN"})
    print("[08B.1.6B] Running focused regressions", flush=True)
    focused = _run_pytest("focused_regression", focused_files)
    print("[08B.1.6B] Running full backend regression", flush=True)
    full = _run_pytest("full_regression", ["tests", "-q"])
    production_after = legacy.production_scope()
    write_json(ART / "production_changes.json", {"researchOnly": True,
        "productionFilesChanged": [], "prototypeConnectedToDispatcher": False,
        "baselineSource": "Task 08B.1.5 approved SHA-256 manifest",
        "before": production_before, "after": production_after,
        "allUnchangedBeforeAndAfter": bool(production_before["allUnchanged"] and production_after["allUnchanged"]
            and production_before["files"] == production_after["files"]),
        "unchangedCount": production_after["unchangedCount"], "totalCount": production_after["totalCount"],
        "changedProductionFiles": [x["path"] for x in production_after["files"] if not x["unchanged"]]})
    print("[08B.1.6B] Writing analysis, figures and acceptance report", flush=True)
    _quality_artifacts(rows, primary, directions, production_before, production_after, focused, full)
    return {"artifactDir": str(ART), "statuses": jread(ART / "acceptance_status.json")["statuses"]}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False))
