from __future__ import annotations

"""Task 08B.1.3 controlled analytic-gradient reproduction.

All hooks in this tool run in-process around the real API; production source
files are not changed. Captured model snapshots are diagnostic artifacts.
"""

import hashlib
import json
import os
from pathlib import Path
import sys
import traceback
from typing import Any

import cv2
import numpy as np
from PIL import Image

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
ARTIFACTS = BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_3"
FIXTURE_DIR = ARTIFACTS / "fixtures"
CAPTURE_DIR = ARTIFACTS / "stage_captures"
RUN_ID = "task08b1_3_controlled"
SIZE = 512
SSAA = 4
SEED = 81313
CURRENT: dict[str, Any] = {"fixture": None, "method": None}

sys.path.insert(0, str(BACKEND))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True,
                               allow_nan=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _lab_neighbor_delta(lab: np.ndarray) -> np.ndarray:
    h_delta = np.linalg.norm(lab[:, 1:] - lab[:, :-1], axis=2)
    v_delta = np.linalg.norm(lab[1:] - lab[:-1], axis=2)
    out = np.zeros(lab.shape[:2], dtype=np.float32)
    out[:, 1:] = np.maximum(out[:, 1:], h_delta)
    out[:, :-1] = np.maximum(out[:, :-1], h_delta)
    out[1:, :] = np.maximum(out[1:, :], v_delta)
    out[:-1, :] = np.maximum(out[:-1, :], v_delta)
    return out


def _mask_boundary(mask: np.ndarray) -> np.ndarray:
    value = np.asarray(mask, dtype=bool)
    result = np.zeros(value.shape, dtype=bool)
    result[:, 1:] |= value[:, 1:] != value[:, :-1]
    result[:, :-1] |= value[:, 1:] != value[:, :-1]
    result[1:, :] |= value[1:, :] != value[:-1, :]
    result[:-1, :] |= value[1:, :] != value[:-1, :]
    return result


def _label_boundary(labels: np.ndarray, *, internal_only: bool = True) -> np.ndarray:
    labels = np.asarray(labels)
    result = np.zeros(labels.shape, dtype=bool)
    for axis, first, second in ((1, (slice(None), slice(1, None)), (slice(None), slice(None, -1))),
                                (0, (slice(1, None), slice(None)), (slice(None, -1), slice(None)))):
        a, b = labels[first], labels[second]
        valid = (a != b)
        if internal_only:
            valid &= (a > 0) & (b > 0)
        result[first] |= valid
        result[second] |= valid
    return result


def _ellipse(x: np.ndarray, y: np.ndarray, cx: float, cy: float,
             rx: float, ry: float) -> np.ndarray:
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0


def _interp_stops(t: np.ndarray, stops: list[tuple[float, tuple[int, int, int]]]) -> np.ndarray:
    positions = np.asarray([row[0] for row in stops], dtype=np.float64)
    colors = np.asarray([row[1] for row in stops], dtype=np.float64)
    return np.stack([np.interp(t, positions, colors[:, channel]) for channel in range(3)], axis=-1)


def _sample_grid() -> tuple[np.ndarray, np.ndarray]:
    y, x = np.indices((SIZE * SSAA, SIZE * SSAA), dtype=np.float64)
    return (x + 0.5) / SSAA, (y + 0.5) / SSAA


def _render_family(fixture_id: str) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    x, y = _sample_grid()
    rng = np.random.default_rng(SEED)
    # Seed is incorporated into analytic phase; no stochastic pixel noise is used.
    phase = float(rng.uniform(-np.pi, np.pi))
    xx, yy = x - SIZE / 2, y - SIZE / 2
    labels_hi = np.zeros(x.shape, dtype=np.uint8)
    alpha_hi = np.zeros(x.shape, dtype=np.uint8)
    rgb = np.zeros((*x.shape, 3), dtype=np.float64)

    if fixture_id == "smooth_nonlinear_gradient":
        radius = np.sqrt((xx / 192.0) ** 2 + (yy / 192.0) ** 2)
        inside = radius <= 1.0
        theta = np.arctan2(yy, xx)
        t = np.clip(0.76 * radius ** 1.72 +
                    0.24 * radius * (0.5 + 0.5 * np.cos(2.0 * theta + phase)), 0.0, 1.0)
        t = t ** 1.24
        rgb = _interp_stops(t, [
            (0.0, (25, 63, 126)), (0.42, (31, 151, 183)), (1.0, (244, 187, 85))])
        labels_hi[inside] = 1
        formula = {
            "shape": "circle, center=(256,256), radius=192 px",
            "colorField": "t=clip(0.76*r^1.72 + 0.24*r*(0.5+0.5*cos(2*theta+phase)),0,1)^1.24; RGB is piecewise-linear between the listed color knots",
            "normalizedRadius": "r=sqrt(((x-256)/192)^2+((y-256)/192)^2)",
            "colorKnots": [[0.0, [25, 63, 126]], [0.42, [31, 151, 183]], [1.0, [244, 187, 85]]],
            "phaseRadians": phase,
            "internalHardBoundary": False,
        }
    elif fixture_id == "hard_boundary_with_gradient":
        inside = _ellipse(x, y, 256.0, 256.0, 205.0, 170.0)
        left = inside & (x < 256.0)
        right = inside & ~left
        local_x = np.clip(x / 256.0, 0, 1)
        local_y = np.clip(y / SIZE, 0, 1)
        t_left = np.clip(0.18 + 0.67 * local_x ** 1.65 + 0.15 * local_y ** 1.35, 0, 1)
        t_right = np.clip(0.12 + 0.72 * (1.0 - local_x) ** 1.5 + 0.16 * local_y ** 1.2, 0, 1)
        left_rgb = _interp_stops(t_left, [(0.0, (26, 98, 149)), (1.0, (90, 191, 195))])
        right_rgb = _interp_stops(t_right, [(0.0, (167, 83, 51)), (1.0, (234, 165, 92))])
        rgb[left] = left_rgb[left]
        rgb[right] = right_rgb[right]
        labels_hi[left] = 1
        labels_hi[right] = 2
        formula = {
            "shape": "ellipse center=(256,256), radii=(205,170) px",
            "partition": "x<256 is region 1, x>=256 is region 2, clipped to ellipse",
            "region1ColorField": "t=clip(0.18+0.67*(x/256)^1.65+0.15*(y/512)^1.35,0,1); linear RGB interpolation from [26,98,149] to [90,191,195]",
            "region2ColorField": "t=clip(0.12+0.72*(1-x/256)^1.5+0.16*(y/512)^1.2,0,1); linear RGB interpolation from [167,83,51] to [234,165,92]",
            "phaseRadians": phase,
            "internalHardBoundary": "analytic vertical divider x=256 within the ellipse",
        }
    elif fixture_id == "low_contrast_multistop_gradient":
        inside = _ellipse(x, y, 256.0, 256.0, 208.0, 174.0)
        t0 = np.clip((x - 52.0) / 408.0, 0.0, 1.0)
        t = 0.18 + 0.64 * (0.5 - 0.5 * np.cos(np.pi * t0)) ** 0.82
        t += 0.035 * np.sin(2 * np.pi * t0 + phase) * np.sin(np.pi * np.clip(y / SIZE, 0, 1))
        t = np.clip(t, 0.0, 1.0)
        rgb = _interp_stops(t, [
            (0.0, (119, 151, 154)), (0.28, (133, 163, 157)),
            (0.62, (153, 174, 161)), (1.0, (177, 184, 165))])
        labels_hi[inside] = 1
        formula = {
            "shape": "ellipse center=(256,256), radii=(208,174) px",
            "colorField": "u=clip((x-52)/408,0,1); t=0.18+0.64*(0.5-0.5*cos(pi*u))^0.82+0.035*sin(2*pi*u+phase)*sin(pi*y/512); RGB is piecewise-linear across four knots",
            "colorKnots": [[0.0, [119, 151, 154]], [0.28, [133, 163, 157]], [0.62, [153, 174, 161]], [1.0, [177, 184, 165]]],
            "phaseRadians": phase,
            "internalHardBoundary": False,
        }
    else:
        raise ValueError(f"Unknown fixture: {fixture_id}")

    alpha_hi[inside] = 255
    rgba_hi = np.dstack([np.rint(rgb).clip(0, 255).astype(np.uint8), alpha_hi])
    rgba = np.asarray(Image.fromarray(rgba_hi, "RGBA").resize((SIZE, SIZE), Image.Resampling.LANCZOS), dtype=np.uint8)
    labels = cv2.resize(labels_hi, (SIZE, SIZE), interpolation=cv2.INTER_NEAREST)
    alpha = rgba[..., 3]
    labels[alpha < 250] = 0
    content = alpha >= 250
    hard = _label_boundary(labels, internal_only=True)
    silhouette = _mask_boundary(alpha >= 16)
    soft = content.copy()
    # Remove antialiased silhouette and a fixed 16 px band around true internal edges.
    soft = cv2.erode(soft.astype(np.uint8), np.ones((9, 9), np.uint8), iterations=1).astype(bool)
    if hard.any():
        near_hard = cv2.dilate(hard.astype(np.uint8), np.ones((33, 33), np.uint8), iterations=1) > 0
        soft &= ~near_hard
    return rgba, labels, {"formula": formula, "phaseRadians": phase,
                          "alpha": alpha, "hard": hard, "silhouette": silhouette,
                          "soft": soft}


def generate_fixtures() -> dict[str, Any]:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    fixture_ids = ("smooth_nonlinear_gradient", "hard_boundary_with_gradient",
                   "low_contrast_multistop_gradient")
    entries: list[dict[str, Any]] = []
    for fixture_id in fixture_ids:
        rgba, labels, masks = _render_family(fixture_id)
        folder = FIXTURE_DIR / fixture_id
        folder.mkdir(parents=True, exist_ok=True)
        paths = {
            "source": folder / "source.png",
            "labels": folder / "ground_truth_region_labels.png",
            "alpha": folder / "ground_truth_alpha.png",
            "hard": folder / "ground_truth_hard_boundary.png",
            "silhouette": folder / "ground_truth_silhouette_boundary.png",
            "soft": folder / "ground_truth_soft_gradient_roi.png",
        }
        Image.fromarray(rgba, "RGBA").save(paths["source"])
        Image.fromarray(labels.astype(np.uint8), "L").save(paths["labels"])
        Image.fromarray(masks["alpha"], "L").save(paths["alpha"])
        Image.fromarray(masks["hard"].astype(np.uint8) * 255, "L").save(paths["hard"])
        Image.fromarray(masks["silhouette"].astype(np.uint8) * 255, "L").save(paths["silhouette"])
        Image.fromarray(masks["soft"].astype(np.uint8) * 255, "L").save(paths["soft"])
        content = masks["alpha"] >= 250
        lab = cv2.cvtColor(rgba[..., :3], cv2.COLOR_RGB2LAB).astype(np.float32)
        gradients = np.gradient(lab, axis=(0, 1))
        grad_mag = np.sqrt(np.sum(gradients[0] ** 2 + gradients[1] ** 2, axis=2))
        interior_grad = grad_mag[masks["soft"]]
        validation = {
            "dimensions": [SIZE, SIZE], "seed": SEED, "supersampling": SSAA,
            "antialiasing": "analytic high-resolution 4x coverage and color field, Lanczos downsample to native RGBA; labels use nearest center sampling",
            "sourceSha256": sha256(paths["source"]),
            "fileSha256": {key: sha256(value) for key, value in paths.items()},
            "alphaPixelCount": int(content.sum()),
            "hardBoundaryPixelCount": int(masks["hard"].sum()),
            "softGradientRoiPixelCount": int(masks["soft"].sum()),
            "softGradientDeltaE76PerPixel": {
                "p50": float(np.quantile(interior_grad, .5)) if len(interior_grad) else 0.0,
                "p95": float(np.quantile(interior_grad, .95)) if len(interior_grad) else 0.0,
            },
            "hardMaskOverlapsSoftRoi": bool(np.any(masks["hard"] & masks["soft"])),
            "formula": masks["formula"],
        }
        checks = [
            rgba.shape == (SIZE, SIZE, 4), labels.shape == (SIZE, SIZE),
            masks["soft"].any(), not validation["hardMaskOverlapsSoftRoi"],
            (masks["hard"].any() == (fixture_id == "hard_boundary_with_gradient")),
            int(content.sum()) > 10000,
            np.all(labels[~content] == 0),
        ]
        validation["valid"] = all(checks)
        if not validation["valid"]:
            raise RuntimeError(f"Analytic fixture validation failed: {fixture_id}: {validation}")
        entries.append({
            "fixtureId": fixture_id, "sourceFamilyId": fixture_id,
            "variant": "native_rgba_png", "independentSourceFamily": True,
            "sourceType": "synthetic_analytic", "size": [SIZE, SIZE],
            "seed": SEED, "supersampling": SSAA,
            "formula": masks["formula"], "files": {k: v.relative_to(ARTIFACTS).as_posix() for k, v in paths.items()},
            "validation": validation,
        })
    result = {
        "schemaVersion": 1,
        "task": "08B.1.3",
        "fixtureGroups": entries,
        "fixtureGroupCount": len(entries),
        "jpegVariants": [],
        "jpegVariantNote": "No JPEG variant was added; compression is not needed to answer the primary analytic reproduction question.",
        "allValid": all(item["validation"]["valid"] for item in entries),
    }
    write_json(ARTIFACTS / "analytic_gradient_fixtures.json", result)
    return result


def _native_label_map(labels: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    return cv2.resize(np.asarray(labels, dtype=np.int32), size, interpolation=cv2.INTER_NEAREST)


def _save_label_capture(stage: str, result: Any, *, metric_attr: str = "metrics") -> None:
    fixture = CURRENT.get("fixture")
    if not fixture:
        return
    target = CAPTURE_DIR / fixture / "smart_reconstruction"
    target.mkdir(parents=True, exist_ok=True)
    field = "region_labels" if hasattr(result, "region_labels") else "label_map"
    labels = np.asarray(getattr(result, field), dtype=np.int32)
    np.save(target / f"{stage}_labels_native.npy", labels)
    rgb = np.zeros((*labels.shape, 3), dtype=np.uint8)
    ids = np.unique(labels)
    for value in ids:
        if value <= 0:
            continue
        c = tuple(int(v) for v in np.random.default_rng(int(value) + 2026).integers(40, 240, size=3))
        rgb[labels == value] = c
    Image.fromarray(rgb).save(target / f"{stage}_regions.png")
    Image.fromarray(_label_boundary(labels).astype(np.uint8) * 255).save(target / f"{stage}_internal_boundaries.png")
    write_json(target / f"{stage}_metrics.json", getattr(result, metric_attr, {}) or {})


def _bezier_points(segment: Any, steps: int = 48) -> np.ndarray:
    t = np.linspace(0.0, 1.0, steps, dtype=np.float64)[:, None]
    p0 = np.asarray(segment.p0, dtype=np.float64)
    p1 = np.asarray(segment.c1, dtype=np.float64)
    p2 = np.asarray(segment.c2, dtype=np.float64)
    p3 = np.asarray(segment.p3, dtype=np.float64)
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3


def _draw_curves(curves: list[np.ndarray], size: tuple[int, int]) -> np.ndarray:
    width, height = size
    mask = np.zeros((height, width), dtype=np.uint8)
    for curve in curves:
        if len(curve) < 2:
            continue
        points = np.rint(curve).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(mask, [points], False, 255, 1, cv2.LINE_8)
    return mask > 0


def _capture_smart_geometry(geometry: Any) -> None:
    fixture = CURRENT.get("fixture")
    if not fixture:
        return
    target = CAPTURE_DIR / fixture / "smart_reconstruction"
    curves: list[np.ndarray] = []
    pair_rows = []
    for boundary in geometry.shared_boundaries:
        components = boundary.components or [boundary.segments]
        for component_index, segments in enumerate(components):
            curve = np.vstack([_bezier_points(segment, 20)[:-1] for segment in segments]) if segments else np.empty((0, 2))
            if len(curve):
                curves.append(curve)
            pair_rows.append({"boundaryId": boundary.id, "regionA": boundary.region_a,
                              "regionB": boundary.region_b, "componentIndex": component_index,
                              "sampledPointCount": int(len(curve)), "confidence": boundary.confidence})
    width, height = int(geometry.width), int(geometry.height)
    boundary_map = _draw_curves(curves, (width, height))
    Image.fromarray(boundary_map.astype(np.uint8) * 255).save(target / "d1_geometry_boundaries.png")
    write_json(target / "d1_geometry.json", {"metrics": geometry.metrics,
        "sharedBoundaryCount": len(geometry.shared_boundaries), "internalGeometryBoundaryPixels": int(boundary_map.sum()),
        "boundaries": pair_rows})


def _capture_smart_appearance(result: Any) -> None:
    fixture = CURRENT.get("fixture")
    if not fixture:
        return
    target = CAPTURE_DIR / fixture / "smart_reconstruction"
    for name in ("model_prediction_rgba", "svg_render_rgba"):
        value = getattr(result, name, None)
        if isinstance(value, np.ndarray):
            Image.fromarray(np.asarray(value, dtype=np.uint8), "RGBA").save(target / f"e1_{name}.png")
    appearance = {}
    for region_id, model in getattr(result, "appearance_models", {}).items():
        values = {}
        for name in getattr(model, "__dataclass_fields__", {}):
            value = getattr(model, name)
            if isinstance(value, np.ndarray):
                continue
            if hasattr(value, "tolist"):
                value = value.tolist()
            if isinstance(value, (str, int, float, bool)) or value is None:
                values[name] = value
            elif isinstance(value, (tuple, list)):
                values[name] = value
        appearance[str(region_id)] = values
    write_json(target / "e1_appearance_models.json", {"metrics": result.metrics,
        "regions": appearance, "layeredRegionCount": len(result.appearance_layers)})


def install_smart_hooks() -> None:
    from mediastudio.image_tools.vectorization_v2 import production
    original_c = production.run_phase_c
    original_d1 = production.run_phase_d1
    original_e1 = production.run_phase_e1

    def phase_c_hook(phase_b: Any, *, debug_directory: Path | None = None) -> Any:
        # Capture exact model data without invoking optional debug writers.
        result = original_c(phase_b, debug_directory=None)
        _save_label_capture("phase_c", result)
        return result

    def phase_d1_hook(phase_c: Any, *, debug_directory: Path | None = None,
                      baseline_geometry: Any | None = None) -> Any:
        result = original_d1(phase_c, debug_directory=None, baseline_geometry=baseline_geometry)
        _capture_smart_geometry(result)
        return result

    def phase_e1_hook(phase_c: Any, geometry: Any, *, baseline_result: Any | None = None,
                      debug_directory: Path | None = None,
                      evaluation_annotations: Any | None = None) -> Any:
        result = original_e1(phase_c, geometry, baseline_result=baseline_result,
                             debug_directory=None, evaluation_annotations=evaluation_annotations)
        _capture_smart_appearance(result)
        return result

    production.run_phase_c = phase_c_hook
    production.run_phase_d1 = phase_d1_hook
    production.run_phase_e1 = phase_e1_hook


def _contour_capture_segmentation(result: Any) -> None:
    fixture = CURRENT.get("fixture")
    if not fixture:
        return
    target = CAPTURE_DIR / fixture / "contour_preserving"
    target.mkdir(parents=True, exist_ok=True)
    labels = np.asarray(result.label_map, dtype=np.int32)
    np.save(target / "segmentation_labels_working.npy", labels)
    Image.fromarray(_label_boundary(labels).astype(np.uint8) * 255).save(target / "segmentation_boundaries_working.png")
    region_rows = []
    for region in result.regions:
        region_rows.append({"id": region.id, "area": region.area, "bbox": list(region.bbox),
                            "classification": region.classification, "confidence": region.confidence,
                            "localContrast": region.local_contrast, "edgeSupport": region.edge_support,
                            "gradientScore": region.gradient_score, "gradientLikelihood": region.gradient_likelihood,
                            "noiseLikelihood": region.noise_likelihood, "parentRegionId": region.parent_region_id,
                            "neighborIds": region.neighbor_ids})
    write_json(target / "segmentation.json", {"metrics": result.metrics,
        "coordinateMapping": {"referenceSize": list(result.coordinate_mapping.reference_size),
                              "processingSize": list(result.coordinate_mapping.processing_size),
                              "scale": list(result.coordinate_mapping.scale)},
        "regions": region_rows})


def _capture_contour_topology(graph: Any) -> None:
    fixture = CURRENT.get("fixture")
    if not fixture:
        return
    target = CAPTURE_DIR / fixture / "contour_preserving"
    size = graph.source_size
    curves: list[np.ndarray] = []
    rows = []
    for interface in graph.interfaces:
        if interface.region_left <= 0 or interface.region_right <= 0:
            continue
        pts = np.asarray(graph.interface_points(interface.id, source=True), dtype=np.float64)
        if len(pts) > 1:
            curves.append(pts)
        rows.append({"interfaceId": interface.id, "regionLeft": interface.region_left,
                     "regionRight": interface.region_right, "shared": interface.shared,
                     "confidence": interface.confidence, "pointCount": interface.unit_segment_count})
    mask = _draw_curves(curves, size)
    Image.fromarray(mask.astype(np.uint8) * 255).save(target / "canonical_geometry_boundaries.png")
    write_json(target / "topology.json", {"metrics": graph.metrics, "validation": graph.validation.__dict__,
        "sourceSize": list(graph.source_size), "processingSize": list(graph.processing_size),
        "sharedInterfaceCount": graph.shared_interface_count, "boundaries": rows})


def _capture_contour_bezier(graph: Any) -> None:
    fixture = CURRENT.get("fixture")
    if not fixture:
        return
    target = CAPTURE_DIR / fixture / "contour_preserving"
    curves: list[np.ndarray] = []
    rows = []
    for interface in graph.interfaces:
        if interface.region_left <= 0 or interface.region_right <= 0:
            continue
        sampled: list[np.ndarray] = []
        for segment in interface.segments:
            pts = _bezier_points(segment, 40)
            pts = np.asarray([graph.to_source_xy(tuple(p)) for p in pts], dtype=np.float64)
            sampled.append(pts[:-1])
        curve = np.vstack(sampled) if sampled else np.empty((0, 2))
        if len(curve):
            curves.append(curve)
        rows.append({"interfaceId": interface.id, "regionLeft": interface.region_left,
                     "regionRight": interface.region_right, "shared": interface.shared,
                     "confidence": interface.confidence, "segmentCount": len(interface.segments),
                     "fitTolerance": interface.fit_tolerance,
                     "meanBoundaryError": interface.mean_boundary_error,
                     "p95BoundaryError": interface.p95_boundary_error,
                     "rollbackReason": interface.rollback_reason})
    mask = _draw_curves(curves, graph.source_size)
    Image.fromarray(mask.astype(np.uint8) * 255).save(target / "bezier_geometry_boundaries.png")
    write_json(target / "bezier_geometry.json", {"metrics": graph.metrics,
        "validation": graph.validation.__dict__, "boundaries": rows})


def _capture_contour_appearance(graph: Any) -> None:
    fixture = CURRENT.get("fixture")
    if not fixture:
        return
    target = CAPTURE_DIR / fixture / "contour_preserving"
    rows = []
    feature_boundary_curves: list[np.ndarray] = []
    for region in graph.regions:
        row = {
            "regionId": region.region_id, "sourceRegionId": region.source_region_id,
            "paintKind": region.paint_kind, "colorRGB": list(region.color_rgb),
            "opacity": region.opacity, "sampleCount": region.sample_count,
            "robustInlierFraction": region.robust_inlier_fraction,
            "flatMeanDeltaE00": region.flat_mean_delta_e00,
            "selectedMeanDeltaE00": region.selected_mean_delta_e00,
            "selectedP95DeltaE00": region.selected_p95_delta_e00,
            "confidence": region.confidence,
            "gradient": None if region.gradient is None else {
                "kind": region.gradient.kind,
                "geometrySourceXY": list(region.gradient.geometry_source_xy),
                "stops": [{"offset": stop.offset, "colorRGB": list(stop.color_rgb), "opacity": stop.opacity}
                          for stop in region.gradient.stops],
                "validationMeanDeltaE00": region.gradient.validation_mean_delta_e00,
                "validationP95DeltaE00": region.gradient.validation_p95_delta_e00,
            },
            "internalFeatureCount": len(region.internal_features),
            "internalFeatures": [],
            "metrics": region.metrics,
        }
        sx, sy = graph.scale_xy
        for feature in region.internal_features:
            feature_row = {
                "id": feature.id, "colorRGB": list(feature.color_rgb), "opacity": feature.opacity,
                "areaPx": feature.area_px, "localContrastDeltaE00": feature.local_contrast_delta_e00,
                "edgeSupport": feature.edge_support, "confidence": feature.confidence,
                "sourceRegionId": feature.source_region_id,
                "clippedToRegionId": feature.clipped_to_region_id,
                "contoursSourceXY": [],
            }
            for ring in feature.contours_processing:
                source_ring = np.asarray([(point[0] / sx, point[1] / sy) for point in ring], dtype=np.float64)
                feature_row["contoursSourceXY"].append(source_ring.tolist())
                if len(source_ring) > 1:
                    feature_boundary_curves.append(source_ring)
            row["internalFeatures"].append(feature_row)
        rows.append(row)
    write_json(target / "appearance.json", {"metrics": graph.metrics,
        "softAlphaEdge": None if graph.soft_alpha_edge is None else {
            "sigmaProcessingPx": graph.soft_alpha_edge.sigma_processing_px,
            "coreOpacity": graph.soft_alpha_edge.core_opacity},
        "regions": rows})
    feature_boundary_mask = _draw_curves(feature_boundary_curves, graph.source_size)
    Image.fromarray(feature_boundary_mask.astype(np.uint8) * 255).save(target / "internal_feature_boundaries.png")
    # This diagnostic serializer consumes the exact fitted appearance graph,
    # including its internal feature paths. It is not the production composer;
    # the actual production SVG and final raster are captured separately below.
    try:
        from mediastudio.image_tools.vectorization_contour.appearance import write_diagnostic_svg
        diagnostic_svg = target / "appearance_diagnostic.svg"
        diagnostic_metadata = write_diagnostic_svg(graph, str(diagnostic_svg))
        from tools.vectorization_benchmark.svg import render_svg_edge
        width, height = graph.source_size
        diagnostic_rgba = render_svg_edge(diagnostic_svg, width=width, height=height)
        Image.fromarray(diagnostic_rgba, "RGBA").save(target / "appearance_diagnostic_render.png")
        write_json(target / "appearance_diagnostic.json", {
            "metadata": diagnostic_metadata,
            "renderer": "Edge/Chromium through Task 08B.1.1 benchmark rasterizer",
            "scope": "Appearance graph diagnostic; exact production SVG is composer_output.svg",
        })
    except Exception as error:
        write_json(target / "appearance_diagnostic.json", {
            "status": "FAILED", "errorType": type(error).__name__, "error": str(error),
            "scope": "Appearance graph diagnostic; production API continues unchanged",
        })
    # Diagnostic paint-only prediction from the actual fitted RegionAppearance models.
    labels = _native_label_map(graph.segmentation.label_map, graph.source_size)
    h, w = labels.shape
    yy, xx = np.indices((h, w), dtype=np.float64)
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    for region in graph.regions:
        mask = labels == region.region_id
        if not np.any(mask):
            continue
        if region.gradient is None:
            paint = np.broadcast_to(np.asarray(region.color_rgb, dtype=np.float64), (h, w, 3))
        else:
            gradient = region.gradient
            x0, y0, a, b = gradient.geometry_source_xy
            if gradient.kind == "linear":
                vx, vy = a - x0, b - y0
                den = max(vx * vx + vy * vy, 1e-8)
                t = ((xx + 0.5 - x0) * vx + (yy + 0.5 - y0) * vy) / den
            else:
                rx, ry = max(a, 1e-6), max(b, 1e-6)
                t = np.sqrt(((xx + 0.5 - x0) / rx) ** 2 + ((yy + 0.5 - y0) / ry) ** 2)
            stops = gradient.stops
            positions = np.asarray([stop.offset for stop in stops], dtype=np.float64)
            colors = np.asarray([stop.color_rgb for stop in stops], dtype=np.float64)
            paint = np.stack([np.interp(np.clip(t, positions[0], positions[-1]), positions, colors[:, c])
                              for c in range(3)], axis=-1)
        rgb[mask] = np.rint(np.clip(paint[mask], 0, 255)).astype(np.uint8)
    Image.fromarray(rgb).save(target / "appearance_paint_prediction.png")


def _capture_composition(composition: Any) -> None:
    fixture = CURRENT.get("fixture")
    if not fixture:
        return
    target = CAPTURE_DIR / fixture / "contour_preserving"
    (target / "composer_output.svg").write_text(composition.svg_text, encoding="utf-8")
    write_json(target / "composer.json", composition.metadata)


def install_contour_hooks() -> None:
    import mediastudio.image_tools.vectorization_contour as contour
    import mediastudio.image_tools.contour_svg_composer as composer
    original_seg = contour.run_contour_segmentation
    original_top = contour.extract_contour_topology
    original_bezier = contour.fit_bezier_topology
    original_appearance = contour.build_contour_appearance_graph
    original_compose = composer.compose_contour_svg

    def seg_hook(*args: Any, **kwargs: Any) -> Any:
        result = original_seg(*args, **kwargs)
        _contour_capture_segmentation(result)
        return result

    def top_hook(*args: Any, **kwargs: Any) -> Any:
        result = original_top(*args, **kwargs)
        _capture_contour_topology(result)
        return result

    def bezier_hook(*args: Any, **kwargs: Any) -> Any:
        result = original_bezier(*args, **kwargs)
        _capture_contour_bezier(result)
        return result

    def appearance_hook(*args: Any, **kwargs: Any) -> Any:
        result = original_appearance(*args, **kwargs)
        _capture_contour_appearance(result)
        return result

    def compose_hook(*args: Any, **kwargs: Any) -> Any:
        result = original_compose(*args, **kwargs)
        _capture_composition(result)
        return result

    contour.run_contour_segmentation = seg_hook
    contour.extract_contour_topology = top_hook
    contour.fit_bezier_topology = bezier_hook
    contour.build_contour_appearance_graph = appearance_hook
    composer.compose_contour_svg = compose_hook


def run_api(fixtures: dict[str, Any]) -> list[dict[str, Any]]:
    os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
    os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
    # We capture exact intermediates in memory; disable optional debug writers.
    os.environ["DEBUG_VECTOR"] = "0"
    install_smart_hooks()
    install_contour_hooks()
    from tools.vectorization_benchmark.worker import run_image
    records = []
    for index, entry in enumerate(fixtures["fixtureGroups"]):
        fixture_id = entry["fixtureId"]
        CURRENT["fixture"] = fixture_id
        source = ARTIFACTS / entry["files"]["source"]
        item = {
            "imageId": fixture_id,
            "sourceFamilyId": entry["sourceFamilyId"],
            "sourceType": "synthetic_analytic",
            "path": str(source.resolve()), "sha256": entry["validation"]["sourceSha256"],
            "benchmarkOrderIndex": index,
            "datasetSplit": "diagnostic_only", "categories": ["analytic_gradient_fixture"],
            "referenceType": "analytic_ground_truth", "hasTypography": False,
            "referenceFiles": {
                "analyticAlphaMaskPath": str((ARTIFACTS / entry["files"]["alpha"]).resolve()),
                "semanticLabelMapPath": str((ARTIFACTS / entry["files"]["labels"]).resolve()),
            },
        }
        write_json(ARTIFACTS / f"item_{fixture_id}.json", item)
        try:
            record = run_image(item, ARTIFACTS, per_engine_timeout=1200, run_id=RUN_ID)
        except BaseException as error:
            record = {"imageId": fixture_id, "status": "FAILED", "failureType": type(error).__name__,
                      "failureReason": str(error), "traceback": traceback.format_exc()}
        write_json(ARTIFACTS / f"api_result_{fixture_id}.json", record)
        records.append(record)
        print(json.dumps({"fixture": fixture_id, "status": record.get("status"),
                          "engines": {k: v.get("status") for k, v in record.get("engines", {}).items()}},
                         ensure_ascii=False), flush=True)
    CURRENT["fixture"] = None
    write_json(ARTIFACTS / "api_runs.json", {"runId": RUN_ID, "results": records,
        "allPass": all(row.get("status") == "PASS" for row in records)})
    return records


if __name__ == "__main__":
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    fixture_record = generate_fixtures()
    if not fixture_record["allValid"]:
        raise SystemExit("Fixture validation failed")
    api_records = run_api(fixture_record)
    raise SystemExit(0 if all(row.get("status") == "PASS" for row in api_records) else 2)
