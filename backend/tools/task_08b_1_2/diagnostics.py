from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw
from skimage.color import deltaE_ciede2000, rgb2lab

BACKEND = Path(__file__).resolve().parents[2]
REPOSITORY = BACKEND.parent
sys.path.insert(0, str(BACKEND))
ARTIFACTS = BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_2"
SOURCE = BACKEND / "artifacts" / "contour_preserving" / "task_07_2" / "synthetic_sources" / "radial_gradient.png"
BASELINE_RENDER = BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_1" / "stages" / "synthetic-radial_gradient" / "smart_reconstruction" / "phase_e1_svg_render.png"
BASELINE_LABELS = BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_1" / "stages" / "synthetic-radial_gradient" / "smart_reconstruction" / "phase_c_region_labels.npy"
BASELINE_REPLAY = ARTIFACTS / "baseline_replay_summary.json"
TASK_0811_METRICS = BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_1" / "stages" / "synthetic-radial_gradient" / "smart_reconstruction" / "phase_e1_metrics.json"
TASK_0811_SOFT = BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_1" / "soft_gradient_analysis.json"

VARIANT_SPECS: tuple[dict[str, Any], ...] = (
    {"id": "radial_offcenter_two_stop", "split": "train", "size": 192,
     "center": [73.0, 116.0], "radius": 49.0,
     "stops": [[0.0, [250, 240, 218]], [1.0, [28, 74, 188]]]},
    {"id": "radial_multistop_warm_cool", "split": "train", "size": 192,
     "center": [96.0, 96.0], "radius": 57.0,
     "stops": [[0.0, [250, 235, 192]], [0.31, [253, 155, 47]],
               [0.68, [209, 63, 89]], [1.0, [36, 35, 126]]]},
    {"id": "radial_heldout_cyan_magenta", "split": "heldout", "size": 224,
     "center": [139.0, 91.0], "radius": 61.0,
     "stops": [[0.0, [230, 248, 255]], [0.57, [51, 165, 207]],
               [1.0, [146, 25, 83]]]},
)


class _NoOCR:
    warnings: list[str] = []
    status = "OCR_FALLBACK"
    initialization_count = 0

    def detect_and_recognize(self, _image: np.ndarray) -> list[Any]:
        return []


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8")


def _delta00(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a_lab = rgb2lab(np.asarray(a, dtype=np.float32) / 255.0)
    b_lab = rgb2lab(np.asarray(b, dtype=np.float32) / 255.0)
    return deltaE_ciede2000(a_lab, b_lab)


def _dist(values: np.ndarray) -> dict[str, float]:
    values = np.asarray(values, dtype=np.float64)
    if not values.size:
        return {"mean": 0.0, "p95": 0.0}
    return {"mean": float(values.mean()), "p95": float(np.quantile(values, .95))}


def _roi_mask(shape: tuple[int, int]) -> np.ndarray:
    height, width = shape
    yy, xx = np.indices(shape)
    radius = min(width, height) * 136.0 / 512.0
    roi = ((xx - width / 2.0) ** 2 + (yy - height / 2.0) ** 2) <= radius ** 2
    return cv2.erode(roi.astype(np.uint8), np.ones((17, 17), np.uint8), iterations=1) > 0


def _primary_pipeline() -> tuple[Any, Any, Any, Any]:
    from mediastudio.image_tools.vectorization_v2.pipeline import run_phase_a
    from mediastudio.image_tools.vectorization_v2.phase_b import run_phase_b
    from mediastudio.image_tools.vectorization_v2.phase_c import run_phase_c
    from mediastudio.image_tools.vectorization_v2.phase_d1 import run_phase_d1

    with Image.open(SOURCE) as image:
        phase_a = run_phase_a(image.convert("RGBA"), processing_scale=1)
    phase_b = run_phase_b(phase_a, ocr_engine=_NoOCR())
    phase_c = run_phase_c(phase_b)
    geometry = run_phase_d1(phase_c)
    return phase_c, geometry, phase_a, phase_b


def _run_primary() -> dict[str, Any]:
    from mediastudio.image_tools.vectorization_v2.phase_e import (
        _delta_e, _predict_model_rgb, run_phase_e,
    )
    from mediastudio.image_tools.vectorization_v2.phase_e1 import run_phase_e1

    phase_c, geometry, _phase_a, _phase_b = _primary_pipeline()
    phase_e = run_phase_e(phase_c, geometry)
    phase_e1 = run_phase_e1(phase_c, geometry, baseline_result=phase_e)
    with Image.open(SOURCE) as image:
        source = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    candidate = np.asarray(phase_e1.svg_render_rgba, dtype=np.uint8)
    baseline = np.asarray(Image.open(BASELINE_RENDER).convert("RGBA"), dtype=np.uint8)
    baseline_metrics = json.loads(TASK_0811_METRICS.read_text(encoding="utf-8"))
    baseline_soft_metrics = json.loads(TASK_0811_SOFT.read_text(encoding="utf-8"))[
        "fixtures"]["synthetic-radial_gradient"]["engines"]["smart_reconstruction"]
    if source.shape != candidate.shape or source.shape != baseline.shape:
        raise ValueError("Primary radial renders must share the source native canvas")

    roi = _roi_mask(source.shape[:2])
    from tools.task_08b_1_1.diagnostics import gradient_metrics
    candidate_roi_metric = gradient_metrics(source[..., :3], candidate[..., :3], roi)
    roi_metrics = {
        "source": "synthetic-radial_gradient source; 17x17-eroded analytic circle ROI from Task 08B.1.1",
        "pixel_count": int(roi.sum()),
        "metric": "CIEDE2000; native source RGB and identical 17x17-eroded analytic circle ROI",
        "baseline": {"mean": float(baseline_soft_metrics["meanDeltaE00"]),
                     "p95": float(baseline_soft_metrics["p95DeltaE00"]),
                     "false_hard_edge_fraction": float(baseline_soft_metrics["falseHardEdgeFraction"])},
        "candidate": {"mean": float(candidate_roi_metric["meanDeltaE00"]),
                      "p95": float(candidate_roi_metric["p95DeltaE00"]),
                      "false_hard_edge_fraction": float(candidate_roi_metric["falseHardEdgeFraction"])},
    }

    labels = np.asarray(phase_c.region_labels)
    source_alpha = np.asarray(phase_c.phase_b.graphic_only_rgba)[..., 3] > 16
    output_alpha = candidate[..., 3] > 16
    owner = np.asarray(phase_e1.geometry_owner)
    matched = source_alpha & output_alpha & (owner == labels) & (labels > 0)
    geometry_mask = (owner == 1) & output_alpha
    distance = cv2.distanceTransform(geometry_mask.astype(np.uint8), cv2.DIST_L2, 5)
    interior = matched & (distance >= 2.0)
    direct_model = np.asarray(phase_e1.model_prediction_rgba, dtype=np.uint8)
    e1_metrics = {
        "pixel_count": int(interior.sum()),
        "baseline": {
            "CIE76": baseline_metrics["new_phase_e1"]["interior_only"],
            "CIEDE2000": _dist(_delta00(source[interior, :3], baseline[interior, :3])),
        },
        "candidate": {
            "CIE76": phase_e1.metrics["new_phase_e1"]["interior_only"],
            "CIEDE2000": _dist(_delta00(source[interior, :3], candidate[interior, :3])),
            "direct_model_CIEDE2000": _dist(_delta00(source[interior, :3], direct_model[interior, :3])),
        },
        "metric_note": "Phase E1's legacy _delta_e is CIE76, not CIEDE2000; both are reported on this same mask.",
    }

    model = phase_e1.appearance_models[1]
    samples = phase_e1.baseline.debug_samples[1]
    fit_prediction = _predict_model_rgb(model, samples.xy)
    fit_errors = _delta_e(samples.rgb, fit_prediction)
    weights = np.asarray(samples.weights, dtype=np.float64)
    fit_mean = float(np.average(fit_errors, weights=weights))
    radial = model.radial_candidate or {}
    fitted = {
        "selected_model": model.appearance_type,
        "center": [float(model.gradient_coordinates.get("cx", 0)),
                   float(model.gradient_coordinates.get("cy", 0))],
        "radius": float(model.gradient_coordinates.get("r", 0)),
        "stops": model.gradient_stops,
        "candidate_score_error_CIE76": float(radial.get("error", 0)),
        "replayed_sample_error_CIE76_weighted_mean": fit_mean,
        "score_to_replay_error_gap_CIE76": float(radial.get("error", 0)) - fit_mean,
        "region_bbox": list(next(r.bbox for r in phase_c.graph.regions if int(r.id) == 1)),
        "region_count": int(phase_c.metrics.get("final_region_count", len(phase_c.graph.regions))),
    }

    analytic_stops = []
    for stop in model.gradient_stops:
        radius_at_stop = float(stop["position"]) * float(model.gradient_coordinates["r"])
        t = float(np.clip(radius_at_stop / 136.0, 0.0, 1.0))
        expected = np.rint(np.array([255, 160, 45]) * (1.0 - t) + np.array([30, 80, 220]) * t).astype(int)
        analytic_stops.append({"position": float(stop["position"]),
                               "fitted_rgb": stop["rgb"],
                               "analytic_rgb_at_fitted_stop": expected.tolist(),
                               "delta_rgb_l2": float(np.linalg.norm(np.asarray(stop["rgb"]) - expected))})
    fitted["analytic_stop_audit"] = analytic_stops

    _write_json(ARTIFACTS / "candidate_primary_metrics.json", {
        "fixture": "synthetic-radial_gradient", "engine": "smart_reconstruction",
        "quality_mode": "auto", "text_mode": "outlined", "transparent_background": True,
        "native_canvas": list(source.shape[1::-1]), "source_sha256": _sha256(SOURCE),
        "phase_e": {"selected": phase_e.appearance_models[1].appearance_type,
                    "metrics": phase_e.metrics},
        "phase_e1": phase_e1.metrics,
        "gradient_roi_CIEDE2000": roi_metrics,
        "direct_e1_interior": e1_metrics,
        "fitted_parameters_and_internal_score_audit": fitted,
        "geometry_signature": phase_e1.metrics["geometry_signature_after"],
    })
    (ARTIFACTS / "radial_candidate.svg").write_text(phase_e1.svg_text, encoding="utf-8")
    Image.fromarray(candidate, "RGBA").save(ARTIFACTS / "radial_candidate_render.png")
    return {"source": source, "baseline": baseline, "candidate": candidate,
            "roi_metrics": roi_metrics, "e1_metrics": e1_metrics, "fit": fitted,
            "phase_e": phase_e, "phase_e1": phase_e1, "phase_c": phase_c,
            "geometry": geometry}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _variant_evaluation() -> dict[str, Any]:
    from mediastudio.image_tools.vectorization_v2.phase_e import (
        _RegionSamples, _delta_e, _fit_appearance, _predict_model_rgb,
    )

    rows = []
    for spec in VARIANT_SPECS:
        size = int(spec["size"])
        yy, xx = np.mgrid[:size, :size]
        center = np.asarray(spec["center"], dtype=np.float64)
        radius = float(spec["radius"])
        distance = np.sqrt((xx - center[0]) ** 2 + (yy - center[1]) ** 2)
        t = np.clip(distance / radius, 0.0, 1.0)
        stop_t = np.asarray([row[0] for row in spec["stops"]], dtype=np.float64)
        stop_rgb = np.asarray([row[1] for row in spec["stops"]], dtype=np.float64)
        source_rgb = np.stack([np.interp(t, stop_t, stop_rgb[:, channel])
                               for channel in range(3)], axis=2).astype(np.uint8)
        mask = distance <= radius - 2.0
        ys, xs = np.where(mask)
        xy = np.column_stack((xs.astype(np.float64), ys.astype(np.float64)))
        rgb = source_rgb[ys, xs].astype(np.float64)
        weights = np.ones(len(xs), dtype=np.float64)
        samples = _RegionSamples(xy, rgb, weights, len(xs), mask,
                                 np.ones(mask.shape, dtype=np.float32), 1.0)
        x0, y0 = np.floor(center - radius).astype(int)
        x1, y1 = np.ceil(center + radius + 1).astype(int)
        region = SimpleNamespace(id=1, confidence=.99, bbox=(int(x0), int(y0), int(x1), int(y1)),
                                 dominant_color=np.median(rgb, axis=0).round().astype(int).tolist())
        model = _fit_appearance(region, samples)
        prediction = _predict_model_rgb(model, xy)
        error76 = _delta_e(rgb, prediction)
        error00 = _delta00(rgb, prediction)
        rows.append({
            "id": spec["id"], "split": spec["split"], "spec": spec,
            "selected_type": model.appearance_type,
            "fitted_center_radius": model.gradient_coordinates,
            "fitted_stops": model.gradient_stops,
            "candidate_score_error_CIE76": model.radial_error,
            "actual_prediction_error_CIE76": _dist(error76),
            "actual_prediction_error_CIEDE2000": _dist(error00),
            "sample_count": int(len(xs)),
            "source_rgba_sha256": hashlib.sha256(
                np.dstack((source_rgb, np.where(mask, 255, 0).astype(np.uint8))).tobytes()).hexdigest(),
        })
    return {"seed": 812012, "deterministic": True,
            "evaluation": "Direct Phase E production fitter on three distinct analytic radial fields; no resizing; heldout is inspected only after the one-line fix is frozen.",
            "fixtures": rows}


def _write_visuals(primary: dict[str, Any]) -> None:
    panels = [("SOURCE", primary["source"]), ("BASELINE", primary["baseline"]),
              ("CANDIDATE", primary["candidate"])]
    tile = 512
    sheet = Image.new("RGB", (tile * len(panels), tile + 28), "white")
    draw = ImageDraw.Draw(sheet)
    for index, (label, rgba) in enumerate(panels):
        draw.text((index * tile + 8, 7), label, fill="#172033")
        image = Image.fromarray(rgba, "RGBA")
        bg = Image.new("RGBA", image.size, "white")
        bg.alpha_composite(image)
        sheet.paste(bg.convert("RGB"), (index * tile, 28))
    sheet.resize((sheet.width * 2, sheet.height * 2), Image.Resampling.NEAREST).save(
        ARTIFACTS / "radial_before_after.png")

    source = primary["source"][..., :3]
    baseline = primary["baseline"][..., :3]
    candidate = primary["candidate"][..., :3]
    mask = _roi_mask(source.shape[:2])
    errors = [_delta00(source, baseline), _delta00(source, candidate)]
    heat_tiles = []
    for name, error in zip(("BASELINE ΔE00", "CANDIDATE ΔE00"), errors):
        normalized = np.clip(error / 24.0 * 255.0, 0, 255).astype(np.uint8)
        colored = cv2.applyColorMap(normalized, cv2.COLORMAP_INFERNO)
        colored[~mask] = (40, 40, 40)
        colored = cv2.cvtColor(colored, cv2.COLOR_BGR2RGB)
        panel = Image.fromarray(colored, "RGB")
        draw = ImageDraw.Draw(panel)
        draw.rectangle((0, 0, 170, 22), fill="white")
        draw.text((5, 5), name, fill="black")
        heat_tiles.append(panel)
    combined = Image.new("RGB", (1024, 512), "white")
    combined.paste(heat_tiles[0], (0, 0))
    combined.paste(heat_tiles[1], (512, 0))
    combined.resize((combined.width * 2, combined.height * 2), Image.Resampling.NEAREST).save(
        ARTIFACTS / "radial_deltae_heatmap.png")


def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    primary = _run_primary()
    variants = _variant_evaluation()
    _write_json(ARTIFACTS / "radial_variant_candidate.json", variants)
    _write_visuals(primary)

    baseline = json.loads(BASELINE_REPLAY.read_text(encoding="utf-8"))
    phase_e_vs_e1 = {
        "metric_definition": "Phase E and E1 compare on identical geometry and ROI; legacy Phase E1 fitting fields are CIE76. CIEDE2000 is recomputed separately.",
        "baseline": {
            "phase_e": baseline["old_phase_e"],
            "phase_e1": baseline["phaseE1"],
            "selected_model": baseline["selected"]["R01"],
        },
        "candidate": {
            "phase_e": primary["phase_e"].metrics,
            "phase_e1": primary["phase_e1"].metrics,
            "selected_model": primary["fit"],
        },
    }
    _write_json(ARTIFACTS / "phase_e_vs_e1_comparison.json", phase_e_vs_e1)
    _write_json(ARTIFACTS / "radial_gradient_before_after.json", {
        "baseline_source": "Task 08B.1.1 controlled API replay plus the frozen Phase E1 SVG render",
        "candidate_source": "direct Smart V2 Phase A/B/C/D1/E/E1 replay from the same source SHA-256",
        "primary_fixture": "synthetic-radial_gradient",
        "same_native_canvas": True,
        "candidate_gradient_roi": primary["roi_metrics"],
        "direct_e1_interior": primary["e1_metrics"],
        "candidate_fit_audit": primary["fit"],
        "phase_e1_baseline_vs_candidate": {
            "CIE76_interior": {
                "baseline": primary["e1_metrics"]["baseline"]["CIE76"],
                "candidate": primary["e1_metrics"]["candidate"]["CIE76"],
            },
            "CIEDE2000_interior": {
                "baseline": primary["e1_metrics"]["baseline"]["CIEDE2000"],
                "candidate": primary["e1_metrics"]["candidate"]["CIEDE2000"],
            },
        },
    })

    labels_after = np.asarray(primary["phase_c"].region_labels)
    labels_before = np.load(BASELINE_LABELS)
    baseline_geometry = baseline["geometry_signature"]
    candidate_geometry = primary["phase_e1"].metrics["geometry_signature_after"]
    _write_json(ARTIFACTS / "geometry_integrity.json", {
        "phase_a_b_c_d1_source_changes": "none",
        "phase_c_labels_equal_baseline": bool(np.array_equal(labels_before, labels_after)),
        "phase_c_label_sha256_baseline": hashlib.sha256(labels_before.tobytes()).hexdigest(),
        "phase_c_label_sha256_candidate": hashlib.sha256(labels_after.tobytes()).hexdigest(),
        "geometry_signature_baseline": baseline_geometry,
        "geometry_signature_candidate": candidate_geometry,
        "geometry_unchanged": baseline_geometry == candidate_geometry and
                              primary["phase_e1"].metrics["geometry_unchanged"],
        "region_count_baseline": 1,
        "region_count_candidate": int(primary["phase_c"].metrics.get("final_region_count", len(primary["phase_c"].graph.regions))),
        "shared_boundary_count_baseline": 0,
        "shared_boundary_count_candidate": int(primary["geometry"].metrics.get("shared_boundary_count", 0)),
        "text_reconstruction_modified": False,
    })
    print(json.dumps({
        "primary": primary["roi_metrics"],
        "direct_e1_interior": primary["e1_metrics"],
        "fit_audit": primary["fit"],
        "variants": [{"id": row["id"], "split": row["split"], "selected_type": row["selected_type"],
                      "CIEDE2000": row["actual_prediction_error_CIEDE2000"],
                      "CIE76": row["actual_prediction_error_CIE76"]}
                     for row in variants["fixtures"]],
        "geometry_unchanged": baseline_geometry == candidate_geometry,
    }, indent=2))


if __name__ == "__main__":
    main()
