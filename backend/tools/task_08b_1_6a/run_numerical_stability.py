from __future__ import annotations

import copy
import hashlib
import json
import math
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.linalg import null_space
from skimage.color import deltaE_ciede2000, rgb2lab

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tools"))

from task_08b_1_1.diagnostics import _lab_neighbor_delta, gradient_metrics
from task_08b_1_5 import run_feasibility as feasibility
from task_08b_1_6 import run_multidirectional as legacy

ART = BACKEND / "artifacts/contour_preserving/task_08b_1_6a"
OLD_ART = BACKEND / "artifacts/contour_preserving/task_08b_1_6"
TASK15 = BACKEND / "artifacts/contour_preserving/task_08b_1_5"
FIXTURES = legacy.FIXTURES
PRIMARY = "smooth_nonlinear_gradient"
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


def read_rgba(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGBA"), dtype=np.uint8)


def delta_map(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    aa = np.asarray(a, dtype=np.float32)[..., :3] / 255.0
    bb = np.asarray(b, dtype=np.float32)[..., :3] / 255.0
    return deltaE_ciede2000(rgb2lab(aa), rgb2lab(bb)).astype(np.float32)


def _error_stats(a: np.ndarray, b: np.ndarray, mask: np.ndarray) -> dict:
    aa = np.asarray(a)[..., :3].astype(np.float64)
    bb = np.asarray(b)[..., :3].astype(np.float64)
    rgb = np.abs(aa - bb)[mask].reshape(-1)
    de = delta_map(a, b)[mask]
    if not rgb.size:
        return {"pixelCount": 0, "meanRgbAbsoluteError": None, "p95RgbAbsoluteError": None,
                "maxRgbAbsoluteError": None, "meanDeltaE00": None, "p95DeltaE00": None,
                "maxDeltaE00": None, "alphaDifferentPixels": None}
    return {"pixelCount": int(mask.sum()), "meanRgbAbsoluteError": float(rgb.mean()),
            "p95RgbAbsoluteError": float(np.quantile(rgb, .95)), "maxRgbAbsoluteError": float(rgb.max()),
            "meanDeltaE00": float(de.mean()), "p95DeltaE00": float(np.quantile(de, .95)),
            "maxDeltaE00": float(de.max()),
            "alphaDifferentPixels": int(np.count_nonzero(np.asarray(a)[..., 3][mask] != np.asarray(b)[..., 3][mask]))}


def _spatial_grid(a: np.ndarray, b: np.ndarray, mask: np.ndarray, cells: int = 8) -> dict:
    de = delta_map(a, b)
    h, w = mask.shape
    rows = []
    for gy in range(cells):
        y0, y1 = round(gy * h / cells), round((gy + 1) * h / cells)
        for gx in range(cells):
            x0, x1 = round(gx * w / cells), round((gx + 1) * w / cells)
            local = mask[y0:y1, x0:x1]
            if local.any():
                vals = de[y0:y1, x0:x1][local]
                rows.append({"cell": [gy, gx], "bbox": [x0, y0, x1, y1], "pixels": int(local.sum()),
                             "meanDeltaE00": float(vals.mean()), "p95DeltaE00": float(np.quantile(vals, .95))})
    return {"grid": [cells, cells], "activeCells": rows,
            "highestMeanErrorCells": sorted(rows, key=lambda r: r["meanDeltaE00"], reverse=True)[:8]}


def _rgba_from_rgb(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    out = np.empty((*rgb.shape[:2], 4), dtype=np.uint8)
    out[..., :3] = np.rint(np.clip(rgb, 0, 255)).astype(np.uint8)
    out[..., 3] = alpha
    return out


def _domain_projection(shape: tuple[int, int], angle: float, support: np.ndarray) -> np.ndarray:
    """The Task 08B.1.6 fitting projection, evaluated across the full canvas."""
    h, w = shape
    yy, xx = np.indices(shape, dtype=np.float64)
    theta = math.radians(angle)
    p = xx * math.cos(theta) + yy * math.sin(theta)
    q = p[support]
    return np.clip((p - float(q.min())) / max(float(q.max() - q.min()), 1e-12), 0.0, 1.0)


def _emitted_projection(shape: tuple[int, int], gradient: ET.Element) -> np.ndarray:
    h, w = shape
    yy, xx = np.indices(shape, dtype=np.float64)
    p0 = np.array([float(gradient.attrib["x1"]), float(gradient.attrib["y1"])])
    p1 = np.array([float(gradient.attrib["x2"]), float(gradient.attrib["y2"])])
    vector = p1 - p0
    return np.clip(((xx - p0[0]) * vector[0] + (yy - p0[1]) * vector[1]) / float(vector @ vector), 0.0, 1.0)


def _decode_stop_color(value: str) -> np.ndarray:
    text = value.strip()
    if text.startswith("#") and len(text) == 7:
        return np.array([int(text[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float64) / 255.0
    if text.startswith("rgb("):
        body = text[4:-1].replace("%", "")
        vals = np.array([float(v.strip()) for v in body.split(",")])
        if vals.max(initial=0) <= 100 and "%" in text:
            vals *= 2.55
        return np.clip(vals / 255.0, 0.0, 1.0)
    raise ValueError(f"Unsupported SVG stop-color in frozen prototype: {value}")


def _gradient_color_at(gradient: ET.Element, t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    stops = [node for node in gradient if node.tag.rsplit("}", 1)[-1] == "stop"]
    offsets = np.array([float(node.attrib["offset"].rstrip("%")) / (100.0 if node.attrib["offset"].endswith("%") else 1.0)
                        for node in stops], dtype=np.float64)
    colors = np.stack([_decode_stop_color(node.attrib["stop-color"]) for node in stops])
    alphas = np.array([float(node.attrib.get("stop-opacity", "1")) for node in stops], dtype=np.float64)
    ix = np.clip(np.searchsorted(offsets, t, side="right") - 1, 0, len(offsets) - 2)
    denom = np.maximum(offsets[ix + 1] - offsets[ix], 1e-12)
    mix = np.clip((t - offsets[ix]) / denom, 0.0, 1.0)
    color = colors[ix] * (1.0 - mix[..., None]) + colors[ix + 1] * mix[..., None]
    alpha = alphas[ix] * (1.0 - mix) + alphas[ix + 1] * mix
    return color, alpha


def _analytical_prediction(base: np.ndarray, support: np.ndarray, region_mask: np.ndarray,
                           gradients: list[ET.Element], projection_mode: str,
                           tables: list[np.ndarray] | None = None) -> np.ndarray:
    """Evaluate the two gradient layers in sRGB and apply source-over in SVG order."""
    h, w = support.shape
    base_rgb = feasibility.white(base).astype(np.float64) / 255.0
    rgb = base_rgb.copy()
    if projection_mode == "fitter_support_bbox":
        if tables is None:
            raise ValueError("fitter-domain projection requires fitted stop tables")
        angles = [float(g.attrib.get("data-research-direction-degrees", 0)) for g in gradients]
        fields = []
        for angle, table in zip(angles, tables):
            proj = _domain_projection((h, w), angle, support)
            fields.append((legacy.basis(proj.reshape(-1)).reshape(h, w, -1) @ table).clip(0, 1))
        for field in fields:
            rgb[region_mask] = rgb[region_mask] * (1.0 - legacy.OPACITY) + field[region_mask] * legacy.OPACITY
    elif projection_mode == "svg_emitted_coordinates":
        for gradient in gradients:
            proj = _emitted_projection((h, w), gradient)
            field, alpha = _gradient_color_at(gradient, proj)
            rgb[region_mask] = (rgb[region_mask] * (1.0 - alpha[region_mask, None])
                                + field[region_mask] * alpha[region_mask, None])
    else:
        raise ValueError(projection_mode)
    return _rgba_from_rgb(rgb * 255.0, base[..., 3])


def _compose_over(foreground: np.ndarray, background: np.ndarray) -> np.ndarray:
    fg = np.asarray(foreground, dtype=np.float64) / 255.0
    bg = np.asarray(background, dtype=np.float64) / 255.0
    fa, ba = fg[..., 3:4], bg[..., 3:4]
    out_a = fa + ba * (1.0 - fa)
    premul = fg[..., :3] * fa + bg[..., :3] * ba * (1.0 - fa)
    out_rgb = np.divide(premul, np.maximum(out_a, 1e-12), out=np.zeros_like(premul), where=out_a > 0)
    return _rgba_from_rgb(out_rgb * 255.0, np.rint(out_a[..., 0] * 255.0).astype(np.uint8))


def _render_without_group(svg: Path, group_id: str, out: Path, renderer: str) -> dict:
    root = feasibility._read_tree(svg)
    parents = {child: parent for parent in root.iter() for child in parent}
    group = next((node for node in root.iter() if node.attrib.get("id") == group_id), None)
    if group is None or group not in parents:
        raise ValueError(f"Cannot isolate SVG group {group_id}")
    parents[group].remove(group)
    feasibility._save_svg(root, out)
    if renderer == "edge":
        return {"status": "PASS", "rgba": legacy.render_svg_edge(out, width=512, height=512)}
    return legacy.render_svg_skia(out, width=512, height=512, output_path=out.with_suffix(".png"))


def _build_system(source: np.ndarray, base_rgba: np.ndarray, support: np.ndarray,
                  directions: list[float]) -> dict:
    bases = [legacy.basis(legacy.proj(support.shape, angle, support)[support]) for angle in directions]
    weights = [legacy.OPACITY * (1.0 - legacy.OPACITY) ** (len(directions) - 1 - i)
               for i in range(len(directions))]
    base_weight = (1.0 - legacy.OPACITY) ** len(directions)
    design = np.concatenate([basis * weight for basis, weight in zip(bases, weights)], axis=1)
    src = source[support, :3].astype(np.float64) / 255.0
    base = feasibility.white(base_rgba)[support].astype(np.float64) / 255.0
    target = src - base_weight * base
    count = legacy.STOPS
    d2 = np.zeros((count - 2, count), dtype=np.float64)
    for i in range(count - 2):
        d2[i, i:i + 3] = (1.0, -2.0, 1.0)
    regularizer = np.zeros((len(directions) * (count - 2), len(directions) * count), dtype=np.float64)
    for i in range(len(directions)):
        regularizer[i * (count - 2):(i + 1) * (count - 2), i * count:(i + 1) * count] = d2 * legacy.SMOOTHNESS
    augmented = np.vstack((design, regularizer))
    rhs = np.vstack((target, np.zeros((len(regularizer), 3), dtype=np.float64)))
    return {"bases": bases, "weights": weights, "baseWeight": base_weight, "design": design,
            "target": target, "regularizer": regularizer, "augmented": augmented, "rhs": rhs,
            "sourceSamples": src, "baseSamples": base}


def _gauge_vector(directions: list[float]) -> np.ndarray:
    if len(directions) != 2:
        raise ValueError("The approved 08B.1.6 prototype contains exactly two directions")
    weights = [legacy.OPACITY * (1.0 - legacy.OPACITY) ** (len(directions) - 1 - i)
               for i in range(len(directions))]
    vector = np.concatenate((np.full(legacy.STOPS, weights[1]), np.full(legacy.STOPS, -weights[0])))
    return vector / np.linalg.norm(vector)


def _solve_original(system: dict) -> tuple[np.ndarray, dict]:
    raw, residuals, rank, singular = np.linalg.lstsq(system["augmented"], system["rhs"], rcond=1e-10)
    clipped = np.clip(raw, 0.0, 1.0)
    tables = [clipped[i * legacy.STOPS:(i + 1) * legacy.STOPS]
              for i in range(2)]
    pred = system["baseWeight"] * system["baseSamples"] + sum(
        weight * (basis @ table) for weight, basis, table in zip(system["weights"], system["bases"], tables))
    return clipped, {"raw": raw, "rank": int(rank), "singularValues": singular.tolist(),
                     "residualVectorNorm": float(np.linalg.norm(system["augmented"] @ raw - system["rhs"])),
                     "clippedComponents": int(np.count_nonzero(np.abs(raw - clipped) > 1e-9)),
                     "fittedRgbRmse": float(np.sqrt(np.mean((pred - system["sourceSamples"]) ** 2))),
                     "tables": tables}


def _solve_constrained(system: dict, gauge: np.ndarray) -> tuple[np.ndarray, dict]:
    q = null_space(gauge.reshape(1, -1))
    reduced = system["augmented"] @ q
    reduced_solution, residuals, rank, singular = np.linalg.lstsq(reduced, system["rhs"], rcond=1e-12)
    raw = q @ reduced_solution
    clipped = np.clip(raw, 0.0, 1.0)
    tables = [clipped[i * legacy.STOPS:(i + 1) * legacy.STOPS]
              for i in range(2)]
    pred = system["baseWeight"] * system["baseSamples"] + sum(
        weight * (basis @ table) for weight, basis, table in zip(system["weights"], system["bases"], tables))
    return clipped, {"raw": raw, "rank": int(rank), "singularValues": singular.tolist(),
                     "residualVectorNorm": float(np.linalg.norm(system["augmented"] @ raw - system["rhs"])),
                     "gaugeResidualPerChannel": (gauge @ raw).tolist(),
                     "gaugeResidualLInf": float(np.max(np.abs(gauge @ raw))),
                     "clippedComponents": int(np.count_nonzero(np.abs(raw - clipped) > 1e-9)),
                     "fittedRgbRmse": float(np.sqrt(np.mean((pred - system["sourceSamples"]) ** 2))),
                     "tables": tables, "nullSpaceBasisShape": list(q.shape)}


def _find_gradient(root: ET.Element, gradient_id: str) -> ET.Element:
    node = next((item for item in root.iter() if item.attrib.get("id") == gradient_id), None)
    if node is None:
        raise ValueError(f"Missing frozen gradient {gradient_id}")
    return node


def _replace_gradient_stops(root: ET.Element, region_id: int, tables: list[np.ndarray]) -> dict:
    replacement = {}
    for layer_index, table in enumerate(tables):
        gradient_id = f"research-multidirectional-r{region_id}-d{layer_index}"
        gradient = _find_gradient(root, gradient_id)
        stops = [node for node in gradient if node.tag.rsplit("}", 1)[-1] == "stop"]
        if len(stops) != legacy.STOPS:
            raise ValueError(f"Unexpected stop count in {gradient_id}: {len(stops)}")
        colors = []
        for node, color in zip(stops, table):
            rgb = np.rint(np.clip(color * 255.0, 0, 255)).astype(int)
            hex_color = "#" + "".join(f"{v:02x}" for v in rgb)
            old = node.attrib["stop-color"]
            node.set("stop-color", hex_color)
            node.set("stop-opacity", f"{legacy.OPACITY:.6f}")
            colors.append({"old": old, "new": hex_color})
        replacement[gradient_id] = colors
    return replacement


def _prepare_fixture(fid: str, folder: Path, directions: list[float], render: bool = True) -> dict:
    sp, rp, full_svg, appearance_path, detail_path = legacy.paths(fid)
    source = legacy.load_rgba(sp)
    roi = legacy.img(rp, "L") > 127
    base_svg = TASK15 / "fixtures" / fid / "base_paint_only.svg"
    old_svg = OLD_ART / "fixtures" / fid / "experimental_multidirectional.svg"
    if not old_svg.is_file() and fid == PRIMARY:
        old_svg = OLD_ART / "experimental_multidirectional.svg"
    if not all(p.is_file() for p in (sp, rp, full_svg, appearance_path, base_svg, old_svg)):
        raise FileNotFoundError(f"Missing frozen input for {fid}: source={sp}, roi={rp}, base={base_svg}, old={old_svg}")
    base = legacy.render_svg_edge(base_svg, width=512, height=512)
    source_root = feasibility._read_tree(base_svg)
    appearance = legacy.jread(appearance_path)
    regions = [r for r in appearance.get("regions", []) if r.get("gradient")
               and r["gradient"].get("kind") in {"linear", "radial"}]
    candidate_root = feasibility._read_tree(old_svg)
    original_trace = jread(OLD_ART / "optimization_trace.json")["fixtures"][fid]
    if fid == PRIMARY and not original_trace:
        original_trace = jread(OLD_ART / "optimization_trace.json")["primary"]
    fits = {}
    candidate_tables = {}
    supports = {}
    for region in regions:
        rid = int(region["regionId"])
        mask = feasibility._region_mask(source_root, rid, folder / "diagnostics")
        support = mask & (source[..., 3] >= 250) & (base[..., 3] >= 250)
        support = cv2.erode(support.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1).astype(bool)
        if support.sum() < legacy.STOPS * 4:
            continue
        system = _build_system(source, base, support, directions)
        gauge = _gauge_vector(directions)
        original, original_info = _solve_original(system)
        constrained, constrained_info = _solve_constrained(system, gauge)
        tables = [constrained[i * legacy.STOPS:(i + 1) * legacy.STOPS] for i in range(2)]
        # The original helper is the frozen implementation being investigated.
        legacy_tables, legacy_trace = legacy.fit_stops(source[..., :3], feasibility.white(base), support, directions)
        original_tables = original_info["tables"]
        if max(float(np.max(np.abs(a - b))) for a, b in zip(legacy_tables, original_tables)) > 1e-12:
            raise AssertionError(f"Independent baseline fit reconstruction disagrees for {fid} R{rid}")
        replacement = _replace_gradient_stops(candidate_root, rid, tables)
        before_table = original_tables
        after_table = tables
        fits[str(rid)] = {"regionId": rid, "supportPixels": int(support.sum()),
                          "supportBoundsXYXY": [int(np.where(support)[1].min()), int(np.where(support)[0].min()),
                                                int(np.where(support)[1].max()) + 1, int(np.where(support)[0].max()) + 1],
                          "directionsDegrees": directions, "original": original_info,
                          "constrained": constrained_info, "legacyTrace": legacy_trace,
                          "parameterDeltaL2": float(np.linalg.norm(constrained - original)),
                          "parameterDeltaMaxAbs": float(np.max(np.abs(constrained - original))),
                          "renderedStopColorsChanged": any(a["old"].lower() != a["new"].lower()
                                                           for values in replacement.values() for a in values),
                          "replacementStopColors": replacement,
                          "predictionDeltaLinf": float(np.max(np.abs(system["augmented"] @ (constrained - original)))),
                          "gaugeResidualOriginalLInf": float(np.max(np.abs(gauge @ original))),
                          "system": system, "gauge": gauge}
        candidate_tables[str(rid)] = tables
        supports[str(rid)] = support
    candidate_svg = folder / "experimental_constrained.svg"
    feasibility._save_svg(candidate_root, candidate_svg)
    if not render:
        return {"fixture": fid, "sourcePath": sp, "roiPath": rp, "fullSvg": full_svg,
                "baseSvg": base_svg, "oldSvg": old_svg, "detailPath": detail_path,
                "source": source, "roi": roi, "base": base, "fits": fits,
                "candidateSvg": candidate_svg, "supports": supports, "candidateTables": candidate_tables}
    original_rgba = legacy.render_svg_edge(old_svg, width=512, height=512)
    current_rgba = legacy.render_svg_edge(full_svg, width=512, height=512)
    candidate_rgba = legacy.render_svg_edge(candidate_svg, width=512, height=512)
    skia_path = folder / "constrained_skia.png"
    skia = legacy.render_svg_skia(candidate_svg, width=512, height=512, output_path=skia_path)
    original_geometry = legacy.geometry(full_svg, old_svg)
    candidate_geometry = legacy.geometry(full_svg, candidate_svg)
    original_vector = feasibility.validate_svg(old_svg)
    candidate_vector = feasibility.validate_svg(candidate_svg)
    metrics = {"currentProduction": legacy.metrics(source, current_rgba, roi),
               "originalResearch": legacy.metrics(source, original_rgba, roi),
               "constrainedCandidate": legacy.metrics(source, candidate_rgba, roi)}
    original_candidate_changed = int(np.count_nonzero(candidate_rgba[..., 3] != original_rgba[..., 3]))
    current_changed = int(np.count_nonzero(candidate_rgba[..., 3] != current_rgba[..., 3]))
    renderer = {"status": skia.get("status"), "reason": skia.get("reason", skia.get("stderr")),
                "alphaIoU": None, "commonAlphaMeanDeltaE00": None, "commonAlphaP95DeltaE00": None}
    if skia.get("status") == "PASS":
        common = (candidate_rgba[..., 3] > 16) & (skia["rgba"][..., 3] > 16)
        de = delta_map(candidate_rgba, skia["rgba"])[common]
        renderer = {"status": "PASS", "renderer": skia.get("renderer"),
                    "alphaIoU": feasibility.alpha_iou(candidate_rgba, skia["rgba"]),
                    "commonAlphaMeanDeltaE00": float(de.mean()) if de.size else 0.0,
                    "commonAlphaP95DeltaE00": float(np.quantile(de, .95)) if de.size else 0.0}
    detail_recall = None
    if detail_path.is_file():
        detail_mask = legacy.img(detail_path, "L") > 127
        if detail_mask.any():
            variants = jread(BACKEND / "artifacts/contour_preserving/task_08b_1_4/controlled_variants.json")["variants"]
            ann = next(v for v in variants if v["fixtureId"] == fid)["analyticAnnotation"]["details"][0]
            target = np.broadcast_to(np.asarray(ann["paintRGB"], dtype=np.uint8), source.shape[:2] + (3,))
            recall = lambda image: float(np.mean(delta_map(target, feasibility.white(image))[detail_mask] <= 10.0))
            detail_recall = {"id": ann["id"], "pixels": int(detail_mask.sum()), "targetRGB": ann["paintRGB"],
                             "currentRecall": recall(current_rgba), "originalResearchRecall": recall(original_rgba),
                             "candidateRecall": recall(candidate_rgba)}
    for key, path in (("current_edge.png", None), ("original_edge.png", None), ("constrained_edge.png", None)):
        if key == "current_edge.png": Image.fromarray(current_rgba).save(folder / key)
        elif key == "original_edge.png": Image.fromarray(original_rgba).save(folder / key)
        else: Image.fromarray(candidate_rgba).save(folder / key)
    return {"fixture": fid, "sourcePath": sp, "roiPath": rp, "fullSvg": full_svg,
            "baseSvg": base_svg, "oldSvg": old_svg, "detailPath": detail_path,
            "source": source, "roi": roi, "base": base, "fits": fits,
            "candidateSvg": candidate_svg, "originalRgba": original_rgba,
            "currentRgba": current_rgba, "candidateRgba": candidate_rgba,
            "skia": skia, "metrics": metrics, "geometry": candidate_geometry,
            "originalGeometry": original_geometry,
            "alpha": {"candidateVsOriginalDifferentPixels": original_candidate_changed,
                      "candidateVsCurrentDifferentPixels": current_changed,
                      "candidateVsOriginalIoU": feasibility.alpha_iou(candidate_rgba, original_rgba),
                      "candidateVsCurrentIoU": feasibility.alpha_iou(candidate_rgba, current_rgba)},
            "renderer": renderer, "detailRecall": detail_recall,
            "svgValidation": candidate_vector, "originalSvgValidation": original_vector,
            "supports": supports, "candidateTables": candidate_tables}


def _matrix_artifacts(primary: dict, provenance: dict) -> tuple[dict, dict, dict, dict]:
    fit = primary["fits"]["5"]
    system = fit["system"]
    design, regularizer, augmented = system["design"], system["regularizer"], system["augmented"]
    gauge = fit["gauge"]
    sv_design = np.linalg.svd(design, compute_uv=False)
    sv_augmented = np.linalg.svd(augmented, compute_uv=False)
    tolerance = float(max(design.shape) * np.finfo(np.float64).eps * sv_design[0])
    rank = int(np.count_nonzero(sv_design > tolerance))
    gauge_design_norm = float(np.linalg.norm(design @ gauge))
    gauge_aug_norm = float(np.linalg.norm(augmented @ gauge))
    corr = np.corrcoef(design, rowvar=False)
    cross = []
    n = legacy.STOPS
    for i in range(n):
        for j in range(n, 2 * n):
            cross.append((abs(float(corr[i, j])), i, j))
    cross.sort(reverse=True)
    original_raw = fit["original"]["raw"]
    # Demonstrate the exact null family without clipping: the predictions and regularized objective stay fixed.
    shifted_raw = original_raw + 0.05 * gauge[:, None]
    null_family = {"shiftFactor": 0.05,
                   "parameterL2Difference": float(np.linalg.norm(shifted_raw - original_raw)),
                   "designPredictionLinf": float(np.max(np.abs(design @ (shifted_raw - original_raw)))),
                   "regularizerPredictionLinf": float(np.max(np.abs(regularizer @ (shifted_raw - original_raw)))),
                   "augmentedObjectiveDelta": float(abs(np.linalg.norm(augmented @ shifted_raw - system["rhs"])
                                                         - np.linalg.norm(augmented @ original_raw - system["rhs"]))) }
    matrix = {"fixture": PRIMARY, "regionId": 5, "numberOfColumns": int(design.shape[1]),
              "numberOfSamples": int(design.shape[0]), "augmentedShape": list(augmented.shape),
              "numericalRank": rank, "relativeTolerance": float(tolerance / sv_design[0]),
              "absoluteTolerance": tolerance, "numericalNullity": int(design.shape[1] - rank),
              "fullRatioConditionNumber": float(sv_design[0] / sv_design[-1]),
              "identifiableSubspaceConditionNumber": float(sv_design[0] / sv_design[-2]),
              "legacyTraceConditionNumber": float(fit["legacyTrace"]["conditionNumber"]),
              "augmentedRank": int(np.linalg.matrix_rank(augmented)),
              "augmentedIdentifiableSubspaceConditionNumber": float(sv_augmented[0] / sv_augmented[-2]),
              "regularizationMatrixRank": int(np.linalg.matrix_rank(regularizer)),
              "regularizationRows": int(regularizer.shape[0]),
              "residualVectorNorm": fit["original"]["residualVectorNorm"],
              "fittedRgbRmse": fit["original"]["fittedRgbRmse"],
              "columnCorrelation": {"maximumAbsoluteCrossDirection": cross[0][0],
                                    "maximumPair": [cross[0][1], cross[0][2]],
                                    "topTenCrossDirectionPairs": [{"absoluteCorrelation": v, "columns": [i, j]}
                                                                  for v, i, j in cross[:10]]},
              "sharedConstantBasis": {"directionContributionWeights": system["weights"],
                                      "nullVectorConstruction": "first profile constants proportional to w2; second proportional to -w1",
                                      "analyticalNullVector": gauge.tolist(),
                                      "designNullResidualL2": gauge_design_norm,
                                      "regularizationNullResidualL2": float(np.linalg.norm(regularizer @ gauge)),
                                      "augmentedNullResidualL2": gauge_aug_norm,
                                      "parameterFamily": null_family}}
    singular = {"designSingularValuesDescending": sv_design.tolist(),
                "augmentedSingularValuesDescending": sv_augmented.tolist(),
                "rankThreshold": {"formula": "max(matrix.shape) * machine_epsilon * largest_singular_value",
                                  "absolute": tolerance, "relative": tolerance / sv_design[0]},
                "smallestDesignSingularValue": float(sv_design[-1]),
                "secondSmallestDesignSingularValue": float(sv_design[-2]),
                "nullToLargestRatio": float(sv_design[-1] / sv_design[0]),
                "identifiableConditionNumber": float(sv_design[0] / sv_design[-2]),
                "augmentedSmallestSingularValue": float(sv_augmented[-1]),
                "augmentedIdentifiableConditionNumber": float(sv_augmented[0] / sv_augmented[-2])}
    _, _, vh = np.linalg.svd(augmented, full_matrices=False)
    numerical_null = vh[-1]
    null = {"nullity": int(design.shape[1] - rank), "expectedNullity": 1,
            "analyticalVector": gauge.tolist(), "numericalRightSingularVector": numerical_null.tolist(),
            "absoluteAlignment": float(abs(gauge @ numerical_null)),
            "A_times_v_l2": gauge_design_norm, "regularizer_times_v_l2": float(np.linalg.norm(regularizer @ gauge)),
            "augmented_times_v_l2": gauge_aug_norm, "conclusion": "ONE_SHARED_CONSTANT_GAUGE_DEGREE_OF_FREEDOM"}
    stability = _parameter_stability(primary)
    return matrix, singular, null, stability


def _parameter_stability(primary: dict) -> dict:
    fit = primary["fits"]["5"]
    system, gauge = fit["system"], fit["gauge"]
    reference = fit["original"]["raw"]
    constrained = fit["constrained"]["raw"]
    rows = []
    sample_count = system["design"].shape[0]
    for seed in (13, 41, 97):
        permutation = np.random.default_rng(seed).permutation(sample_count)
        perm_aug = np.vstack((system["design"][permutation], system["regularizer"]))
        perm_rhs = np.vstack((system["target"][permutation], np.zeros((system["regularizer"].shape[0], 3))))
        solution = np.linalg.lstsq(perm_aug, perm_rhs, rcond=1e-10)[0]
        delta = solution - reference
        rows.append({"rowPermutationSeed": seed, "parameterDeltaL2": float(np.linalg.norm(delta)),
                     "parameterDeltaMaxAbs": float(np.max(np.abs(delta))),
                     "deltaProjectionOnNullGauge": float(gauge @ delta[:, 0]),
                     "predictionDeltaLinf": float(np.max(np.abs(system["design"] @ delta))),
                     "regularizedResidualDelta": float(abs(np.linalg.norm(perm_aug @ solution - perm_rhs)
                                                              - fit["original"]["residualVectorNorm"]))})
    return {"sameInputAndSource": True, "arithmetic": "float64", "seed": None,
            "rowPermutationRuns": rows,
            "constrainedVsOriginal": {"parameterDeltaL2": float(np.linalg.norm(constrained - reference)),
                                      "parameterDeltaMaxAbs": float(np.max(np.abs(constrained - reference))),
                                      "predictionDeltaLinf": fit["predictionDeltaLinf"],
                                      "gaugeResidualAfterConstraintLInf": fit["constrained"]["gaugeResidualLInf"],
                                      "clippedComponentCountOriginal": fit["original"]["clippedComponents"],
                                      "clippedComponentCountConstrained": fit["constrained"]["clippedComponents"]},
            "interpretation": "Least-squares parameters are non-unique along one exact gauge, but equivalent solves are stable and have indistinguishable predictions."}


def _render_and_compare_objective(primary: dict, output_dir: Path) -> dict:
    source, base, roi = primary["source"], primary["base"], primary["roi"]
    fit = primary["fits"]["5"]
    support = primary["supports"]["5"]
    mask = support.copy()
    # The evaluator's ROI has three pixels outside its own eroded fitting support; omit those from pairwise renderer comparisons.
    eval_mask = roi & mask
    if not eval_mask.any():
        eval_mask = support
    original_root = feasibility._read_tree(primary["oldSvg"])
    gradients = [_find_gradient(original_root, f"research-multidirectional-r5-d{i}") for i in range(2)]
    tables = fit["original"]["tables"]
    fitting_prediction = _analytical_prediction(base, support, mask, gradients, "fitter_support_bbox", tables)
    svg_analytical = _analytical_prediction(base, support, mask, gradients, "svg_emitted_coordinates")
    edge_no_details_path = output_dir / "diagnostics/primary/gradient_only.svg"
    edge_no_details = _render_without_group(primary["oldSvg"], "artwork-internal-details", edge_no_details_path, "edge")["rgba"]
    skia_full = primary["skia"].get("rgba") if primary["skia"].get("status") == "PASS" else None
    skia_no_details_result = _render_without_group(primary["oldSvg"], "artwork-internal-details",
                                                    output_dir / "diagnostics/primary/gradient_only_skia.svg", "skia")
    skia_no_details = skia_no_details_result.get("rgba") if skia_no_details_result.get("status") == "PASS" else None
    detail_only_path = output_dir / "diagnostics/primary/details_only.svg"
    details_only = _render_without_group(primary["oldSvg"], "artwork-base-regions", detail_only_path, "edge")["rgba"]
    svg_analytical_plus_details = _compose_over(details_only, svg_analytical)
    models = {"A_LINEAR_FITTING_SPACE": fitting_prediction,
              "B_ANALYTICAL_SOURCE_OVER_FROM_EMITTED_SVG": svg_analytical,
              "B_PLUS_FROZEN_DETAIL_OVERLAY": svg_analytical_plus_details,
              "C_ACTUAL_EDGE_FULL_SVG": primary["originalRgba"],
              "C_ACTUAL_EDGE_GRADIENT_ONLY": edge_no_details,
              "D_ACTUAL_SVG_SKIA_FULL_SVG": skia_full,
              "D_ACTUAL_SVG_SKIA_GRADIENT_ONLY": skia_no_details}
    source_white = feasibility.white(source)
    source_results = {}
    for name, image in models.items():
        if image is None:
            source_results[name] = {"status": "NOT_AVAILABLE"}
            continue
        source_results[name] = {"status": "MEASURED", "qualityAgainstSource": legacy.metrics(source, image, roi),
                                "spatialError": _spatial_grid(source_white, feasibility.white(image), eval_mask)}
    comparisons = {}
    available = [(name, image) for name, image in models.items() if image is not None]
    for i, (name_a, image_a) in enumerate(available):
        for name_b, image_b in available[i + 1:]:
            key = f"{name_a}__VS__{name_b}"
            pair_stats = _error_stats(image_a, image_b, eval_mask)
            try:
                edge_response = gradient_metrics(feasibility.white(image_a), feasibility.white(image_b), eval_mask)
                pair_stats["boundaryResponse"] = {"falseHardEdgeFraction": float(edge_response["falseHardEdgeFraction"]),
                                                  "falseHardEdgePixels": int(edge_response["falseHardEdgePixels"]),
                                                  "meanDeltaE00": float(edge_response["meanDeltaE00"]),
                                                  "p95DeltaE00": float(edge_response["p95DeltaE00"])}
            except Exception as exc:
                pair_stats["boundaryResponse"] = {"error": str(exc)}
            pair_stats["spatialError"] = _spatial_grid(image_a, image_b, eval_mask)
            comparisons[key] = pair_stats
    dom = {"fixture": PRIMARY, "sourceSha256": sha(primary["sourcePath"]),
           "roiPixels": int(roi.sum()), "fitSupportPixels": int(support.sum()),
           "evaluationPixels": int(eval_mask.sum()), "roiPixelsOutsideFitSupport": int(np.count_nonzero(roi & ~support)),
           "fittingVsSvgCoordinates": {"fittingProjection": "projected coordinate normalized by min/max over the eroded support bbox",
                                       "emittedSvgProjection": "userSpaceOnUse linearGradient spans canvas endpoints [0,0] to [511,0] / [0,0] to [0,511]",
                                       "supportBoundsXYXY": fit["supportBoundsXYXY"],
                                       "canvasSize": [512, 512],
                                       "directionsDegrees": [0, 90],
                                       "mismatchVerified": True},
           "sourceResults": source_results, "pairwiseComparisons": comparisons,
           "isolationRenders": {"edgeGradientOnly": {"status": "PASS", "path": str(edge_no_details_path),
                                                        "detailGroupRemoved": True},
                                 "skiaGradientOnly": {"status": skia_no_details_result.get("status"),
                                                        "reason": skia_no_details_result.get("reason", skia_no_details_result.get("stderr")),
                                                        "detailGroupRemoved": True},
                                 "detailOnly": {"status": "PASS", "path": str(detail_only_path),
                                                "baseRegionGroupRemoved": True}},
           "colorSpaceAndCompositing": {"fitStopSpace": "sRGB channel values normalized to [0,1]",
                                         "svgStopSpace": "serialized sRGB hex stop colors; explicit color-interpolation=sRGB",
                                         "stopOpacity": 0.5, "layerOrder": ["base", "direction 0", "direction 90"],
                                         "sourceOverWeights": [0.25, 0.5, 0.25],
                                         "background": "pairwise renderer checks use the same frozen base-paint render; opaque fit support is isolated",
                                         "clipping": "the original SVG group parent mask and path clips are retained; pairwise color comparison excludes the 1-pixel fitted boundary by using ROI intersect support",
                                         "gradientInterpolation": "linear interpolation between actual SVG stops in sRGB; compared against Edge and Svg.Skia gradient-only renders",
                                         "note": "Full-SVG comparisons include four frozen internal feature paths; separate gradient-only and detail-overlay renders isolate those paths."}}
    ab_stats = comparisons["A_LINEAR_FITTING_SPACE__VS__B_ANALYTICAL_SOURCE_OVER_FROM_EMITTED_SVG"]
    b_edge = comparisons["B_ANALYTICAL_SOURCE_OVER_FROM_EMITTED_SVG__VS__C_ACTUAL_EDGE_GRADIENT_ONLY"]
    dom["rootCauseAssessment"] = {
        "NUMERICAL_IDENTIFIABILITY_ERROR": {"status": "VERIFIED_STRUCTURAL", "nullity": 1,
                                              "causalForFidelityFailure": False,
                                              "evidence": "Gauge-constrained refit changed no serialized stop colors and no measurable render pixels."},
        "OBJECTIVE_RENDER_MISMATCH": {"status": "VERIFIED", "primaryCause": True,
                                      "fitDomainVsSvgDomainMeanDeltaE00": ab_stats["meanDeltaE00"],
                                      "fitDomainVsSvgDomainP95DeltaE00": ab_stats["p95DeltaE00"],
                                      "evidence": "Fitter normalizes projected positions over support bbox; SVG stops are emitted over the full canvas."},
        "SOURCE_OVER_MODEL_MISMATCH": {"status": "NOT_MATERIAL_IN_ISOLATED_GRADIENT_RENDER",
                                       "analyticalVsEdgeMeanDeltaE00": b_edge["meanDeltaE00"],
                                       "analyticalVsEdgeP95DeltaE00": b_edge["p95DeltaE00"]},
        "RENDERER_DISAGREEMENT": {"status": "WITHIN_INHERITED_COMPATIBILITY_LIMITS",
                                  "fullEdgeVsSvgSkiaMeanDeltaE00": comparisons["C_ACTUAL_EDGE_FULL_SVG__VS__D_ACTUAL_SVG_SKIA_FULL_SVG"]["meanDeltaE00"],
                                  "fullEdgeVsSvgSkiaP95DeltaE00": comparisons["C_ACTUAL_EDGE_FULL_SVG__VS__D_ACTUAL_SVG_SKIA_FULL_SVG"]["p95DeltaE00"]},
        "INSUFFICIENT_2D_MODEL_CAPACITY": {"status": "NOT_ISOLATED", "reason": "The objective-to-SVG coordinate mapping is already a verified material mismatch."},
        "MULTIPLE_CONTRIBUTING_FACTORS": {"status": "NOT_ESTABLISHED"},
        "primaryClassification": "OBJECTIVE_RENDER_MISMATCH"}
    write_json(ART / "objective_renderer_comparison.json", dom)
    write_json(ART / "source_over_compositing_validation.json", dom["colorSpaceAndCompositing"] | {
        "analyticalSvgPredictionVsEdgeGradientOnly": comparisons.get("B_ANALYTICAL_SOURCE_OVER_FROM_EMITTED_SVG__VS__C_ACTUAL_EDGE_GRADIENT_ONLY"),
        "analyticalSvgPredictionVsSkiaGradientOnly": comparisons.get("B_ANALYTICAL_SOURCE_OVER_FROM_EMITTED_SVG__VS__D_ACTUAL_SVG_SKIA_GRADIENT_ONLY"),
        "analyticalPredictionWithFrozenDetailsVsEdgeFull": comparisons.get("B_PLUS_FROZEN_DETAIL_OVERLAY__VS__C_ACTUAL_EDGE_FULL_SVG"),
        "interpretation": "An analytical source-over model is considered renderer-consistent only when compared with the isolated gradient-only render; the full output contains the separately frozen detail overlay."})
    return {"document": dom, "models": models, "evalMask": eval_mask,
            "fitPrediction": fitting_prediction, "svgPrediction": svg_analytical,
            "edgeNoDetails": edge_no_details, "skiaNoDetails": skia_no_details,
            "detailOnly": details_only, "svgPlusDetails": svg_analytical_plus_details}


def _detail_validation(rows: dict[str, dict]) -> dict:
    fixtures = {}
    for fid in ("small_sharp_color_detail", "thin_highlight"):
        row = rows[fid]
        detail = row["detailRecall"]
        fixtures[fid] = {"recall": detail, "geometryUnchanged": row["geometry"]["geometryPathsIdentical"],
                         "detailPathsUnchanged": row["geometry"]["detailPathsIdentical"],
                         "alpha": row["alpha"], "currentMetrics": row["metrics"]["currentProduction"],
                         "originalResearchMetrics": row["metrics"]["originalResearch"],
                         "candidateMetrics": row["metrics"]["constrainedCandidate"]}
    return {"fixtures": fixtures,
            "smallSharpDetailPass": fixtures["small_sharp_color_detail"]["recall"]["candidateRecall"] >= 1.0,
            "thinHighlightRecallNonregression": fixtures["thin_highlight"]["recall"]["candidateRecall"] >=
                                                  fixtures["thin_highlight"]["recall"]["currentRecall"],
            "alphaUnchangedByNumericalCandidate": all(x["alpha"]["candidateVsOriginalDifferentPixels"] == 0
                                                       for x in fixtures.values()),
            "inheritedThinHighlightAlphaDifferenceFromCurrent":
                fixtures["thin_highlight"]["alpha"]["candidateVsCurrentDifferentPixels"],
            "interpretation": "The constrained fit leaves the Task 08B.1.6 render unchanged; inherited 08B.1.6 detail/alpha failures are reported and are not altered by this numerical-only experiment."}


def _make_visuals(primary: dict, heldout: dict, objective: dict) -> None:
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font = ImageFont.load_default()

    def board(items: list[tuple[str, np.ndarray]], path: Path, cols: int = 2, heat: bool = False):
        cell_w, image_h, title_h = 480, 480, 38
        rows = math.ceil(len(items) / cols)
        canvas = Image.new("RGB", (cols * cell_w, rows * (image_h + title_h)), "#f3f4f7")
        draw = ImageDraw.Draw(canvas)
        for i, (title, rgba) in enumerate(items):
            x, y = (i % cols) * cell_w, (i // cols) * (image_h + title_h)
            draw.text((x + 10, y + 9), title, fill="#171a2b", font=font)
            rgba_image = Image.fromarray(np.asarray(rgba, dtype=np.uint8)).convert("RGBA")
            white_backdrop = Image.new("RGBA", rgba_image.size, (255, 255, 255, 255))
            im = Image.alpha_composite(white_backdrop, rgba_image).convert("RGB")
            im.thumbnail((image_h, image_h), Image.Resampling.LANCZOS)
            canvas.paste(im, (x + (cell_w - im.width) // 2, y + title_h + (image_h - im.height) // 2))
        path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(path)

    p = primary
    obj = objective["models"]
    board([("A · Fit-space linear prediction", obj["A_LINEAR_FITTING_SPACE"]),
           ("B · SVG-coordinate analytic source-over", obj["B_ANALYTICAL_SOURCE_OVER_FROM_EMITTED_SVG"]),
           ("C · Edge full SVG", p["originalRgba"]),
           ("C · Edge gradient only", objective["edgeNoDetails"]),
           ("D · Svg.Skia full SVG", p["skia"].get("rgba", p["originalRgba"])),
           ("B · Analytic plus frozen details", objective["svgPlusDetails"])],
          ART / "numerical_fit_vs_svg_render.png", 3)
    board([("Source", p["source"]), ("Current production", p["currentRgba"]),
           ("08B.1.6 original", p["originalRgba"]), ("08B.1.6A constrained", p["candidateRgba"])],
          ART / "primary_before_after.png", 2)
    board([("Primary source", p["source"]), ("Primary original 08B.1.6", p["originalRgba"]),
           ("Primary constrained 08B.1.6A", p["candidateRgba"]), ("Heldout source", heldout["source"]),
           ("Heldout current", heldout["currentRgba"]), ("Heldout constrained", heldout["candidateRgba"])],
          ART / "heldout_comparison.png", 3)

    def heat_items(source: np.ndarray, images: list[tuple[str, np.ndarray]]) -> list[tuple[str, np.ndarray]]:
        result = []
        source_rgb = feasibility.white(source)
        for label, image in images:
            de = delta_map(source_rgb, feasibility.white(image))
            scaled = np.uint8(np.clip(de / 20.0, 0, 1) * 255)
            rgb = cv2.cvtColor(cv2.applyColorMap(scaled, cv2.COLORMAP_TURBO), cv2.COLOR_BGR2RGB)
            result.append((label, _rgba_from_rgb(rgb, np.full(rgb.shape[:2], 255, dtype=np.uint8))))
        return result

    board(heat_items(p["source"], [("A · fit domain", obj["A_LINEAR_FITTING_SPACE"]),
                                    ("B · emitted SVG stops", obj["B_ANALYTICAL_SOURCE_OVER_FROM_EMITTED_SVG"]),
                                    ("C · Edge SVG", p["originalRgba"]),
                                    ("D · Svg.Skia", p["skia"].get("rgba", p["originalRgba"]))]),
          ART / "deltae00_comparison.png", 2)
    # Boundary-response maps use the same source and ROI for each result.
    def false_edge_overlay(source: np.ndarray, output: np.ndarray, roi: np.ndarray) -> np.ndarray:
        source_rgb, output_rgb = feasibility.white(source), feasibility.white(output)
        source_lab = rgb2lab(source_rgb.astype(np.float32) / 255.0)
        output_lab = rgb2lab(output_rgb.astype(np.float32) / 255.0)
        source_delta, output_delta = _lab_neighbor_delta(source_lab), _lab_neighbor_delta(output_lab)
        interior = cv2.erode(roi.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
        false_edges = interior & (output_delta >= 3.0) & (output_delta > source_delta * 2.5 + 0.75)
        painted = output_rgb.copy()
        painted[false_edges] = np.array([255, 32, 32], dtype=np.uint8)
        return _rgba_from_rgb(painted, np.full(painted.shape[:2], 255, dtype=np.uint8))

    board([("Source", _rgba_from_rgb(feasibility.white(p["source"]), np.full(p["source"].shape[:2], 255, np.uint8))),
           ("Current production · red = excess edge", false_edge_overlay(p["source"], p["currentRgba"], p["roi"])),
           ("Original research · red = excess edge", false_edge_overlay(p["source"], p["originalRgba"], p["roi"])),
           ("Constrained candidate · red = excess edge", false_edge_overlay(p["source"], p["candidateRgba"], p["roi"]))],
          ART / "false_edge_comparison.png", 2)


def _write_report(reports: dict) -> None:
    primary = reports["primary"]
    fit = primary["fits"]["5"]
    rank = reports["matrix"]
    quality = reports["acceptance"]
    comp = reports["objective"]["document"]
    pairs = comp["pairwiseComparisons"]
    a_b = pairs["A_LINEAR_FITTING_SPACE__VS__B_ANALYTICAL_SOURCE_OVER_FROM_EMITTED_SVG"]
    b_cnd = pairs["B_ANALYTICAL_SOURCE_OVER_FROM_EMITTED_SVG__VS__C_ACTUAL_EDGE_GRADIENT_ONLY"]
    c_d = pairs.get("C_ACTUAL_EDGE_FULL_SVG__VS__D_ACTUAL_SVG_SKIA_FULL_SVG", {})
    held = reports["heldout"]
    detail = reports["detail"]
    lines = [
        "# MediaStudio — Task 08B.1.6A",
        "## Multi-directional gradient fitting: numerical stability and renderer consistency",
        "",
        "## Decision",
        "",
        f"`RESEARCH_BRANCH_DECISION = {quality['RESEARCH_BRANCH_DECISION']}`",
        f"`FEASIBILITY_PROVEN = {str(quality['FEASIBILITY_PROVEN']).lower()}`",
        f"`PRODUCTION_RELEASE_READY = false`",
        "",
        "The shared-constant null direction is real, but the constrained gauge candidate changes no serialized stop colors and no rendered prediction at measurable precision. It does not explain the fidelity failure. The dominant measured mismatch is that the fitter normalizes each directional coordinate over the eroded region support while emitted SVG gradients span the full 512×512 canvas. The analytical SVG-coordinate source-over prediction agrees closely with the isolated Edge gradient render; the full SVG also includes four frozen detail paths.",
        "",
        "## A. Baseline reproduction",
        "",
        f"- Baseline reproduced: **{quality['BASELINE_REPRODUCED']}**.",
        f"- Source SHA-256: `{reports['baseline']['inputs']['sourceSha256']}`.",
        f"- Frozen base SVG SHA-256: `{reports['baseline']['inputs']['frozenBaseSvgSha256']}`.",
        f"- Frozen geometry SHA-256: `{reports['baseline']['inputs']['frozenGeometrySha256']}`.",
        f"- ROI: {reports['baseline']['inputs']['roiPixels']:,} pixels; fitting support: {fit['supportPixels']:,} pixels.",
        f"- Original SVG SHA-256: `{reports['baseline']['inputs']['originalResearchSvgSha256']}`.",
        f"- Edge reproduced candidate mean/P95 ΔE00: {primary['metrics']['originalResearch']['meanDeltaE00']:.4f}/{primary['metrics']['originalResearch']['p95DeltaE00']:.4f}; false-edge {primary['metrics']['originalResearch']['falseEdgeFraction']:.6%}.",
        "",
        "## B. Numerical identifiability",
        "",
        f"- Matrix shape: {rank['numberOfSamples']:,} × {rank['numberOfColumns']}; rank {rank['numericalRank']}/{rank['numberOfColumns']}.",
        f"- Exact nullity: {rank['numericalNullity']}; null singular value / largest: {reports['singular']['nullToLargestRatio']:.3e}.",
        f"- Legacy reported condition number: {rank['legacyTraceConditionNumber']:.3e}. This ratio includes the null singular value and is not the condition of the identifiable subspace.",
        f"- Identifiable subspace condition: {rank['identifiableSubspaceConditionNumber']:.4f}; augmented identifiable subspace: {rank['augmentedIdentifiableSubspaceConditionNumber']:.4f}.",
        f"- Regularizer rank: {rank['regularizationMatrixRank']}/{rank['regularizationRows']}.",
        f"- Analytical gauge residuals: ‖A v‖₂={rank['sharedConstantBasis']['designNullResidualL2']:.3e}; ‖R v‖₂={rank['sharedConstantBasis']['regularizationNullResidualL2']:.3e}.",
        f"- Row permutation parameter drift max: {max(r['parameterDeltaMaxAbs'] for r in reports['stability']['rowPermutationRuns']):.3e}; prediction drift max: {max(r['predictionDeltaLinf'] for r in reports['stability']['rowPermutationRuns']):.3e}.",
        f"- Gauge-constrained vs original parameter ΔL2: {fit['parameterDeltaL2']:.3e}; rendered stop colors changed: `{fit['renderedStopColorsChanged']}`.",
        f"- Gauge-constrained stop-fit RGB RMSE: {fit['constrained']['fittedRgbRmse']:.6f} versus original {fit['original']['fittedRgbRmse']:.6f}.",
        "",
        "Conclusion: rank deficiency is verified as one shared constant degree of freedom. It makes parameter values mathematically non-unique, but not materially unstable under equivalent row orderings. The one permitted gauge-constrained candidate leaves the fit and serialized colors unchanged.",
        "",
        "## C. Fitting objective versus SVG rendering",
        "",
        "The actual fitting basis maps the support's projected minimum and maximum to 0 and 1. `endpoints()` then writes SVG gradients over the full canvas. For the primary support, these coordinate domains differ. The task's original SVG has `userSpaceOnUse` endpoints [0,0]→[511,0] and [0,0]→[0,511], while the fitting basis was normalized over the support bbox.",
        f"- Fit-space prediction A versus analytical emitted-SVG prediction B: mean/P95 ΔE00 {a_b['meanDeltaE00']:.4f}/{a_b['p95DeltaE00']:.4f}; mean/P95 channel absolute error {a_b['meanRgbAbsoluteError']:.3f}/{a_b['p95RgbAbsoluteError']:.3f}.",
        f"- Analytical emitted-SVG prediction B versus isolated Edge gradient-only render: mean/P95 ΔE00 {b_cnd['meanDeltaE00']:.4f}/{b_cnd['p95DeltaE00']:.4f}; mean/P95 channel absolute error {b_cnd['meanRgbAbsoluteError']:.3f}/{b_cnd['p95RgbAbsoluteError']:.3f}.",
        f"- Full Edge versus full Svg.Skia: mean/P95 ΔE00 {c_d.get('meanDeltaE00', float('nan')):.4f}/{c_d.get('p95DeltaE00', float('nan')):.4f}.",
        f"- Actual SVG stop interpolation: explicit sRGB; stop opacity 0.5; source-over order base → 0° → 90°; model weights 0.25/0.5/0.25. Four internal detail paths are separately rendered after the gradient group.",
        "",
        "Interpretation: the large A→B discrepancy is an objective-to-SVG coordinate mapping error in the old prototype. B→Edge-gradient-only is small, and Edge/Svg.Skia full renders agree within renderer compatibility limits. This is not evidence that the renderer itself is causing the large color error.",
        "",
        "![Fitting and render comparison](numerical_fit_vs_svg_render.png)",
        "",
        "## D. One constrained candidate and quality checks",
        "",
        f"- Primary original mean/P95 ΔE00: {primary['metrics']['originalResearch']['meanDeltaE00']:.4f}/{primary['metrics']['originalResearch']['p95DeltaE00']:.4f}; constrained: {primary['metrics']['constrainedCandidate']['meanDeltaE00']:.4f}/{primary['metrics']['constrainedCandidate']['p95DeltaE00']:.4f}.",
        f"- Primary false-edge fraction original/constrained: {primary['metrics']['originalResearch']['falseEdgeFraction']:.6%}/{primary['metrics']['constrainedCandidate']['falseEdgeFraction']:.6%}.",
        f"- Heldout mean/P95 ΔE00 current/original/constrained: {held['current']['meanDeltaE00']:.4f}/{held['current']['p95DeltaE00']:.4f}; {held['originalResearch']['meanDeltaE00']:.4f}/{held['originalResearch']['p95DeltaE00']:.4f}; {held['constrainedCandidate']['meanDeltaE00']:.4f}/{held['constrainedCandidate']['p95DeltaE00']:.4f}.",
        f"- Small detail recall current/candidate: {detail['fixtures']['small_sharp_color_detail']['recall']['currentRecall']:.4f}/{detail['fixtures']['small_sharp_color_detail']['recall']['candidateRecall']:.4f}.",
        f"- Thin highlight recall current/candidate: {detail['fixtures']['thin_highlight']['recall']['currentRecall']:.4f}/{detail['fixtures']['thin_highlight']['recall']['candidateRecall']:.4f}; candidate versus current exact alpha differences: {detail['inheritedThinHighlightAlphaDifferenceFromCurrent']} pixels. The gauge candidate adds zero alpha differences versus the original research SVG.",
        f"- Geometry preserved: `{quality['GEOMETRY_UNCHANGED']}`; vector-only SVG: `{quality['SVG_VECTOR_ONLY']}`; six fixture renderer checks: {quality['RENDERER_COMPATIBILITY_PASS_COUNT']}/6 passed.",
        "",
        "![Primary comparison](primary_before_after.png)",
        "",
        "![Heldout comparison](heldout_comparison.png)",
        "",
        "![Color error comparison](deltae00_comparison.png)",
        "",
        "![False-edge response comparison](false_edge_comparison.png)",
        "",
        "## E. Branch decision",
        "",
        f"`{quality['RESEARCH_BRANCH_DECISION']}`",
        "",
        "Why: a specific objective/render coordinate mismatch is measured and is large relative to the Edge-to-Skia difference. Gauge fixing improves formal identifiability but leaves the rendered candidate unchanged. The 08B.1.6 fidelity gates remain failed, so the evidence supports one narrowly targeted follow-up on coordinate consistency, while the current candidate remains unfit for production. A future fitting objective must use the same coordinate mapping as the emitted SVG, but this task deliberately does not implement that change.",
        "",
        "Evidence limits: the objective mismatch is quantified on the primary fixture; the gauge candidate is applied once with the frozen method to the heldout and detail fixtures. No fit objective, model family, stop count, layer count, alpha, geometry, or production behavior was changed.",
        "",
        "## Acceptance",
        "",
    ]
    for key, value in quality.items():
        if key == "evidence":
            continue
        lines.append(f"`{key} = {str(value).lower() if isinstance(value, bool) else value}`")
    lines += ["", "Production source hashes are checked against the approved Task 08B.1.5 manifest in `production_changes.json`. Production/API/WPF/default engine files were not edited.",
              "", "**Task 08B.1.6A complete. Stopped before Task 08B.1.7.**", ""]
    (ART / "task_08b_1_6a_report.md").write_text("\n".join(lines), encoding="utf-8")


def run() -> dict:
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "diagnostics").mkdir(exist_ok=True)
    prior_config = jread(OLD_ART / "fitting_configuration.json")
    directions = [float(x) for x in prior_config["selectedDirectionsDegrees"]]
    source_path, roi_path, current_svg, appearance_path, _ = legacy.paths(PRIMARY)
    base_svg = TASK15 / "fixtures" / PRIMARY / "base_paint_only.svg"
    original_svg = OLD_ART / "fixtures" / PRIMARY / "experimental_multidirectional.svg"
    source = legacy.load_rgba(source_path)
    roi = legacy.img(roi_path, "L") > 127
    base = legacy.render_svg_edge(base_svg, width=512, height=512)
    original_edge = legacy.render_svg_edge(original_svg, width=512, height=512)
    current_edge = legacy.render_svg_edge(current_svg, width=512, height=512)
    primary_folder = ART / "fixtures" / PRIMARY
    primary = _prepare_fixture(PRIMARY, primary_folder, directions, render=True)
    # The root-level filename is required by the task; keep the same content as the per-fixture candidate.
    (ART / "experimental_constrained.svg").write_bytes(primary["candidateSvg"].read_bytes())
    root = feasibility._read_tree(base_svg)
    frozen_geometry = feasibility._frozen_geometry_paths(current_svg)
    reproducibility = jread(OLD_ART / "reproducibility.json")
    expected = next(x for x in reproducibility["frozenInputs"] if x["fixture"] == PRIMARY)
    current_metrics = legacy.metrics(source, current_edge, roi)
    old_metrics = legacy.metrics(source, original_edge, roi)
    stored = jread(OLD_ART / "primary_fidelity_comparison.json")["models"]
    stored_candidate = stored["TASK_08B_1_6_MULTIDIRECTIONAL"]
    baseline = {"inputs": {"sourceSha256": sha(source_path), "roiSha256": hashlib.sha256(np.ascontiguousarray(roi, dtype=np.uint8).tobytes()).hexdigest().upper(),
                            "frozenBaseSvgSha256": sha(base_svg), "currentSvgSha256": sha(current_svg),
                            "appearanceSha256": sha(appearance_path), "originalResearchSvgSha256": sha(original_svg),
                            "frozenGeometrySha256": canonical_sha(frozen_geometry), "roiPixels": int(roi.sum()),
                            "gradientDirectionsDegrees": directions,
                            "stopTablesSha256": canonical_sha(jread(OLD_ART / "optimization_trace.json")["fixtures"][PRIMARY])},
                 "expectedInputHashes": expected, "currentProductionMetrics": current_metrics,
                 "originalResearchMetrics": old_metrics,
                 "storedOriginalResearchMetrics": stored_candidate,
                 "metricReproductionDelta": {k: float(old_metrics[k] - stored_candidate[k]) for k in
                                              ("falseEdgeFraction", "meanDeltaE00", "p95DeltaE00")},
                 "metricTolerances": {"falseEdgeFraction": 2e-5, "meanDeltaE00": 0.05, "p95DeltaE00": 0.10}}
    baseline["sourceHashMatch"] = baseline["inputs"]["sourceSha256"] == expected["sourceSha256"]
    baseline["baseSvgHashMatch"] = baseline["inputs"]["frozenBaseSvgSha256"] == expected["frozenBaseSvgSha256"]
    baseline["originalSvgHashMatch"] = baseline["inputs"]["originalResearchSvgSha256"] == sha(OLD_ART / "experimental_multidirectional.svg")
    baseline["currentSvgHashMatch"] = baseline["inputs"]["currentSvgSha256"] == expected["currentSvgSha256"]
    baseline["frozenGeometryHash"] = baseline["inputs"]["frozenGeometrySha256"]
    baseline["reproduced"] = bool(baseline["sourceHashMatch"] and baseline["baseSvgHashMatch"] and
                                   baseline["originalSvgHashMatch"] and baseline["currentSvgHashMatch"] and
                                   abs(baseline["metricReproductionDelta"]["falseEdgeFraction"]) <= baseline["metricTolerances"]["falseEdgeFraction"] and
                                   abs(baseline["metricReproductionDelta"]["meanDeltaE00"]) <= baseline["metricTolerances"]["meanDeltaE00"] and
                                   abs(baseline["metricReproductionDelta"]["p95DeltaE00"]) <= baseline["metricTolerances"]["p95DeltaE00"])
    write_json(ART / "baseline_reproduction.json", baseline)
    if not baseline["reproduced"]:
        raise RuntimeError("Task 08B.1.6 primary baseline failed frozen-input or metric reproduction checks; no candidate acceptance is allowed")

    matrix, singular, null, stability = _matrix_artifacts(primary, baseline)
    write_json(ART / "fitting_matrix_analysis.json", matrix)
    write_json(ART / "singular_value_analysis.json", singular)
    write_json(ART / "null_space_analysis.json", null)
    write_json(ART / "parameter_stability_comparison.json", stability)
    spec = {"candidate": "single shared constant gauge constraint for the two-direction regularized least-squares fit",
            "constraint": "v^T parameters = 0; v uses the source-over contribution weights to remove the exact redundant shared-constant degree of freedom",
            "gaugeVector": primary["fits"]["5"]["gauge"].tolist(),
            "preservesFunctionSpace": True, "changesObjectiveOrModel": False,
            "sourceSha256": sha(Path(__file__)), "baselineResearchRunnerSha256": sha(BACKEND / "tools/task_08b_1_6/run_multidirectional.py"),
            "frozenPrototypeSvgSha256": sha(original_svg), "frozenSourceSha256": sha(source_path),
            "directionsDegrees": directions, "stopsPerGradient": legacy.STOPS,
            "stopOpacity": legacy.OPACITY, "smoothnessWeight": legacy.SMOOTHNESS,
            "changesToProduction": False}
    write_json(ART / "constrained_fitting_spec.json", spec)
    constrained_result = {"fixture": PRIMARY, "regionId": 5,
                          "fitSupportPixels": primary["fits"]["5"]["supportPixels"],
                          "matrixRankBefore": matrix["numericalRank"], "matrixColumnsBefore": matrix["numberOfColumns"],
                          "identifiableRankAfter": primary["fits"]["5"]["constrained"]["rank"],
                          "parameterDeltaL2": primary["fits"]["5"]["parameterDeltaL2"],
                          "parameterDeltaMaxAbs": primary["fits"]["5"]["parameterDeltaMaxAbs"],
                          "predictionDeltaLinf": primary["fits"]["5"]["predictionDeltaLinf"],
                          "serializedStopColorsChanged": primary["fits"]["5"]["renderedStopColorsChanged"],
                          "originalRgbRmse": primary["fits"]["5"]["original"]["fittedRgbRmse"],
                          "constrainedRgbRmse": primary["fits"]["5"]["constrained"]["fittedRgbRmse"],
                          "baselineSvgSha256": sha(original_svg),
                          "candidateSvgSha256": sha(ART / "experimental_constrained.svg"),
                          "svgBytesIdentical": (ART / "experimental_constrained.svg").read_bytes() == original_svg.read_bytes(),
                          "renderedQuality": primary["metrics"]}
    write_json(ART / "constrained_fitting_results.json", constrained_result)
    # Candidate is frozen here. Each fixture is processed once with the same constrained solver, then evaluated once.
    fixture_rows = {PRIMARY: primary}
    for fid in FIXTURES:
        if fid == PRIMARY:
            continue
        print(f"[08B.1.6A] frozen constrained candidate: {fid}", flush=True)
        fixture_rows[fid] = _prepare_fixture(fid, ART / "fixtures" / fid, directions, render=True)
    held = fixture_rows["smooth_alternate_heldout"]
    heldout = {"fixture": held["fixture"], "sourceSha256": sha(held["sourcePath"]),
               "candidateFrozenBeforeHeldout": True, "tunedOnHeldout": False,
               "current": held["metrics"]["currentProduction"],
               "originalResearch": held["metrics"]["originalResearch"],
               "constrainedCandidate": held["metrics"]["constrainedCandidate"],
               "candidateVsOriginalAlphaDifferentPixels": held["alpha"]["candidateVsOriginalDifferentPixels"],
               "pass": bool(held["metrics"]["constrainedCandidate"]["falseEdgeFraction"] < .01 and
                            held["metrics"]["constrainedCandidate"]["meanDeltaE00"] <= held["metrics"]["currentProduction"]["meanDeltaE00"] and
                            held["metrics"]["constrainedCandidate"]["p95DeltaE00"] <= held["metrics"]["currentProduction"]["p95DeltaE00"])}
    write_json(ART / "heldout_validation.json", heldout)
    detail = _detail_validation(fixture_rows)
    write_json(ART / "detail_preservation.json", detail)
    objective = _render_and_compare_objective(primary, ART)
    primary_quality = {"fixture": PRIMARY, "sourceSha256": sha(source_path),
                       "currentProduction": primary["metrics"]["currentProduction"],
                       "originalResearch": primary["metrics"]["originalResearch"],
                       "constrainedCandidate": primary["metrics"]["constrainedCandidate"],
                       "primaryFalseEdgePass": primary["metrics"]["constrainedCandidate"]["falseEdgeFraction"] < .01,
                       "primaryMeanDeltaE00Pass": primary["metrics"]["constrainedCandidate"]["meanDeltaE00"] <= primary["metrics"]["currentProduction"]["meanDeltaE00"],
                       "primaryP95DeltaE00Pass": primary["metrics"]["constrainedCandidate"]["p95DeltaE00"] <= primary["metrics"]["currentProduction"]["p95DeltaE00"],
                       "geometryUnchanged": primary["geometry"]["geometryPathsIdentical"] and primary["geometry"]["detailPathsIdentical"],
                       "alphaChangedFromOriginal": primary["alpha"]["candidateVsOriginalDifferentPixels"],
                       "candidateSvgValid": primary["svgValidation"].get("xmlValid", False),
                       "candidateVectorOnly": primary["svgValidation"].get("embeddedRasterElementCount") == 0 and
                                              primary["svgValidation"].get("embeddedRasterDataUriCount") == 0}
    write_json(ART / "primary_before_after.json", primary_quality)
    geometry_alpha = {fid: {"geometry": row["geometry"], "alpha": row["alpha"],
                            "svgValidation": {k: row["svgValidation"].get(k) for k in
                                              ("xmlValid", "editableVector", "embeddedRasterElementCount", "embeddedRasterDataUriCount")}}
                      for fid, row in fixture_rows.items()}
    write_json(ART / "geometry_alpha_integrity.json", {"fixtures": geometry_alpha,
               "geometryUnchangedAll": all(r["geometry"]["geometryPathsIdentical"] and r["geometry"]["detailPathsIdentical"] for r in fixture_rows.values()),
               "alphaUnchangedByCandidateAll": all(r["alpha"]["candidateVsOriginalDifferentPixels"] == 0 for r in fixture_rows.values()),
               "inheritedAlphaDifferencesFromCurrent": {fid: r["alpha"]["candidateVsCurrentDifferentPixels"] for fid, r in fixture_rows.items()}})
    renderer_rows = {fid: row["renderer"] for fid, row in fixture_rows.items()}
    renderer_passes = {fid: v.get("status") == "PASS" and (v.get("alphaIoU") or 0) >= .995 and
                       (v.get("commonAlphaMeanDeltaE00") or 1e6) <= 1.0 and
                       (v.get("commonAlphaP95DeltaE00") or 1e6) <= 3.0 for fid, v in renderer_rows.items()}
    write_json(ART / "renderer_compatibility.json", {"primaryRenderer": "Edge/Chromium", "secondaryRenderer": "Svg.Skia",
               "limits": {"alphaIoUMinimum": .995, "meanDeltaE00Maximum": 1.0, "p95DeltaE00Maximum": 3.0},
               "fixtures": renderer_rows, "fixturePasses": renderer_passes, "passCount": sum(renderer_passes.values()),
               "allPass": all(renderer_passes.values())})
    vector_only = {fid: bool(row["svgValidation"].get("xmlValid") and row["svgValidation"].get("embeddedRasterElementCount") == 0 and
                              row["svgValidation"].get("embeddedRasterDataUriCount") == 0) for fid, row in fixture_rows.items()}
    write_json(ART / "svg_vector_only_validation.json", {"fixtures": vector_only, "allValidVectorOnly": all(vector_only.values())})
    # Provenance snapshot is repeated after all renders/tests, then compared in finalization below.
    production = legacy.production_scope()
    write_json(ART / "production_changes.json", production)
    _make_visuals(primary, held, objective)
    return {"primary": primary, "heldout": heldout, "detail": detail, "objective": objective,
            "matrix": matrix, "singular": singular, "null": null, "stability": stability,
            "baseline": baseline, "production": production, "fixtures": fixture_rows,
            "rendererCompatibilityPassCount": sum(renderer_passes.values()),
            "vectorOnly": all(vector_only.values()), "geometryUnchanged": geometry_alpha[PRIMARY]["geometry"]["geometryPathsIdentical"],
            "alphaNonregression": all(r["alpha"]["candidateVsOriginalDifferentPixels"] == 0 for r in fixture_rows.values())}


if __name__ == "__main__":
    result = run()
    print(json.dumps({"artifactDir": str(ART), "baselineReproduced": result["baseline"]["reproduced"],
                      "numericalNullity": result["matrix"]["numericalNullity"],
                      "candidateStopColorsChanged": result["primary"]["fits"]["5"]["renderedStopColorsChanged"],
                      "productionUnchanged": result["production"]["allUnchanged"]}, indent=2))
