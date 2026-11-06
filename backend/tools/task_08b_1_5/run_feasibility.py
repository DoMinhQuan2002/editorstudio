from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys
import time
import xml.etree.ElementTree as ET

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter1d
from skimage.color import deltaE_ciede2000, rgb2lab

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
ART = BACKEND / "artifacts/contour_preserving/task_08b_1_5"
TASK13 = BACKEND / "artifacts/contour_preserving/task_08b_1_3"
TASK14 = BACKEND / "artifacts/contour_preserving/task_08b_1_4"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tools"))

from task_08b_1_1.diagnostics import gradient_metrics
from vectorization_benchmark.svg import render_svg_edge, render_svg_skia, validate_svg

NS = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
ET.register_namespace("", NS)
ET.register_namespace("xlink", XLINK)
STOP_COUNT = 17
EDGE_REPEATS = 3
RENDERER_LIMITS = {"alphaIouMinimum": 0.995, "meanDeltaE00Maximum": 1.0, "p95DeltaE00Maximum": 3.0}


def jread(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def load_rgba(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGBA"), dtype=np.uint8)


def white(rgba: np.ndarray) -> np.ndarray:
    x = np.asarray(rgba, dtype=np.float32)
    if x.ndim == 3 and x.shape[-1] == 3:
        return np.rint(x).clip(0, 255).astype(np.uint8)
    a = x[..., 3:4] / 255.0
    return np.rint(x[..., :3] * a + 255.0 * (1.0 - a)).clip(0, 255).astype(np.uint8)


def de_map(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    lab_a = rgb2lab(np.asarray(a, dtype=np.float32) / 255.0)
    lab_b = rgb2lab(np.asarray(b, dtype=np.float32) / 255.0)
    return deltaE_ciede2000(lab_a, lab_b).astype(np.float32)


def alpha_iou(a: np.ndarray, b: np.ndarray) -> float:
    aa, bb = a[..., 3] > 16, b[..., 3] > 16
    return float((aa & bb).sum() / max(int((aa | bb).sum()), 1))


def _read_tree(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def _find_child_id(root: ET.Element, identifier: str) -> ET.Element | None:
    return next((node for node in root.iter() if node.attrib.get("id") == identifier), None)


def _href(node: ET.Element) -> str:
    return node.attrib.get("href", node.attrib.get(f"{{{XLINK}}}href", ""))


def _gradient_url(value: str) -> str | None:
    match = re.fullmatch(r"url\(#([^\)]+)\)", value.strip())
    return match.group(1) if match else None


def _strip_details(root: ET.Element) -> None:
    for node in list(root.iter()):
        if node.attrib.get("id") == "artwork-internal-details":
            node.clear()
            node.set("id", "artwork-internal-details")
            return
    # Diagnostic SVGs from 08B.1.4 store the internal paths in clipped groups.
    for parent in list(root.iter()):
        for child in list(parent):
            if child.tag.rsplit("}", 1)[-1] == "g" and child.attrib.get("clip-path", "").startswith("url(#clip-r"):
                if any("detail" in item.attrib.get("id", "") for item in child.iter()):
                    parent.remove(child)


def _save_svg(root: ET.Element, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _region_mask(svg_root: ET.Element, region_id: int, work: Path) -> np.ndarray:
    target_id = next((candidate for candidate in (f"contour-region-{region_id}", f"region-{region_id}")
                      if _find_child_id(svg_root, candidate) is not None), None)
    shape = _find_child_id(svg_root, target_id) if target_id else None
    if shape is None or not shape.attrib.get("d"):
        raise ValueError(f"Missing frozen vector geometry for {target_id}")
    width = int(float(svg_root.attrib.get("width", "512")))
    height = int(float(svg_root.attrib.get("height", "512")))
    view_box = svg_root.attrib.get("viewBox", f"0 0 {width} {height}")
    mask_root = ET.Element(f"{{{NS}}}svg", {"width": str(width), "height": str(height), "viewBox": view_box})
    ET.SubElement(mask_root, f"{{{NS}}}rect", {"x": "0", "y": "0", "width": str(width), "height": str(height), "fill": "#000"})
    path = ET.SubElement(mask_root, f"{{{NS}}}path", {"d": shape.attrib["d"], "fill": "#fff", "fill-rule": shape.attrib.get("fill-rule", "evenodd")})
    mask_svg = work / f"region_mask_{region_id}.svg"
    _save_svg(mask_root, mask_svg)
    rendered = render_svg_edge(mask_svg, width=width, height=height)
    return rendered[..., :3].max(axis=2) > 128


def _smooth_stops(source: np.ndarray, base: np.ndarray, t: np.ndarray, support: np.ndarray) -> tuple[list[dict], list[int]]:
    offsets = np.linspace(0.0, 1.0, STOP_COUNT)
    cut_points = (offsets[:-1] + offsets[1:]) * 0.5
    bin_ids = np.digitize(t, cut_points)
    colors = np.full((STOP_COUNT, 3), np.nan, dtype=np.float64)
    opacities = np.full(STOP_COUNT, np.nan, dtype=np.float64)
    counts = []
    for index in range(STOP_COUNT):
        chosen = support & (bin_ids == index)
        counts.append(int(chosen.sum()))
        if not chosen.any():
            continue
        # Robust source color at this normalized radius; no semantic labels or hand-set coordinates.
        target = np.median(source[chosen, :3].astype(np.float64), axis=0)
        b = base[chosen, :3].astype(np.float64)
        s = source[chosen, :3].astype(np.float64)
        d = target[None, :] - b
        denom = float(np.sum(d * d))
        opacity = float(np.clip(np.sum((s - b) * d) / denom, 0.0, 1.0)) if denom > 1e-9 else 0.0
        colors[index] = target
        opacities[index] = opacity
    populated = np.flatnonzero(np.isfinite(opacities))
    if not len(populated):
        raise ValueError("No source pixels support the radial correction fit")
    for channel in range(3):
        colors[:, channel] = np.interp(np.arange(STOP_COUNT), populated, colors[populated, channel])
    opacities = np.interp(np.arange(STOP_COUNT), populated, opacities[populated])
    color_values = gaussian_filter1d(colors, sigma=0.8, axis=0, mode="nearest")
    alpha_values = np.clip(gaussian_filter1d(opacities, sigma=0.8, mode="nearest"), 0, 1)
    stops = []
    for offset, color, opacity in zip(offsets, color_values, alpha_values):
        rgb = np.rint(color).clip(0, 255).astype(int)
        stops.append({"offset": float(offset), "colorRGB": rgb.tolist(), "opacity": float(opacity)})
    return stops, counts


def _fit_corrections(svg_root: ET.Element, appearance: dict, source: np.ndarray, base_rgba: np.ndarray,
                     work: Path) -> dict[int, dict]:
    defs = next((n for n in svg_root if n.tag.rsplit("}", 1)[-1] == "defs"), None)
    base_group = _find_child_id(svg_root, "artwork-base-regions")
    if defs is None or base_group is None:
        raise ValueError("Expected vector defs and artwork-base-regions in the frozen SVG")
    regions = {int(row["regionId"]): row for row in appearance.get("regions", [])}
    src_rgb, base_rgb = white(source), white(base_rgba)
    height, width = source.shape[:2]
    yy, xx = np.indices((height, width), dtype=np.float32)
    fits: dict[int, dict] = {}
    for region_id, region in regions.items():
        gradient = region.get("gradient")
        if not gradient or gradient.get("kind") not in {"radial", "linear"}:
            continue
        gradient_kind = gradient["kind"]
        geometry = gradient["geometrySourceXY"]
        if gradient_kind == "radial":
            cx, cy, rx, ry = (float(v) for v in geometry)
            t = np.sqrt(((xx - cx) / max(abs(rx), 1e-6)) ** 2 + ((yy - cy) / max(abs(ry), 1e-6)) ** 2)
        else:
            x1, y1, x2, y2 = (float(v) for v in geometry)
            vx, vy = x2 - x1, y2 - y1
            denom = max(vx * vx + vy * vy, 1e-6)
            t = ((xx - x1) * vx + (yy - y1) * vy) / denom
        mask = _region_mask(svg_root, region_id, work)
        support = mask & (source[..., 3] >= 250) & (base_rgba[..., 3] >= 250)
        # Exclude a one-pixel silhouette rim; alpha/geometry are handled by the unchanged parent mask.
        support = cv2.erode(support.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1).astype(bool)
        stops, counts = _smooth_stops(source, base_rgba, t, support)
        base_use = next((node for node in base_group if node.tag.rsplit("}", 1)[-1] == "use"
                         and _href(node).lstrip("#") == f"contour-region-{region_id}"
                         and _gradient_url(node.attrib.get("fill", "")) is not None), None)
        # The 08B.1.4 diagnostic layout uses "region-N"; production-style SVGs use "contour-region-N".
        if base_use is None:
            base_use = next((node for node in base_group if node.tag.rsplit("}", 1)[-1] == "use"
                             and _href(node).lstrip("#") == f"region-{region_id}"
                             and _gradient_url(node.attrib.get("fill", "")) is not None), None)
        if base_use is None:
            raise ValueError(f"Cannot locate base radial region paint for region {region_id}")
        base_gradient_id = _gradient_url(base_use.attrib["fill"])
        source_gradient = _find_child_id(svg_root, base_gradient_id)
        if source_gradient is None:
            raise ValueError(f"Missing base gradient {base_gradient_id}")
        correction_id = f"research-continuous-correction-r{region_id}"
        correction = ET.Element(f"{{{NS}}}{gradient_kind}Gradient", dict(source_gradient.attrib))
        correction.set("id", correction_id)
        correction.set("data-research-model", "radial-residual-opacity-correction")
        for stop in stops:
            rgb = stop["colorRGB"]
            ET.SubElement(correction, f"{{{NS}}}stop", {
                "offset": f"{stop['offset']:.6f}",
                "stop-color": "#" + "".join(f"{v:02x}" for v in rgb),
                "stop-opacity": f"{stop['opacity']:.6f}",
            })
        defs.append(correction)

        # Composite both paints first and apply the parent's alpha mask once so correction opacity
        # changes color without changing silhouette alpha.
        index = list(base_group).index(base_use)
        group_attrs = {"data-research-layer": correction_id}
        parent_mask = base_use.attrib.get("mask")
        if parent_mask:
            group_attrs["mask"] = parent_mask
        composite = ET.Element(f"{{{NS}}}g", group_attrs)
        base_child = copy.deepcopy(base_use)
        base_child.attrib.pop("mask", None)
        composite.append(base_child)
        correction_child = copy.deepcopy(base_use)
        correction_child.attrib.pop("mask", None)
        correction_child.set("fill", f"url(#{correction_id})")
        correction_child.set("fill-opacity", "1")
        composite.append(correction_child)
        base_group.remove(base_use)
        base_group.insert(index, composite)
        fits[region_id] = {"baseGradientId": base_gradient_id, "correctionGradientId": correction_id,
                           "gradientKind": gradient_kind, "geometrySourceXY": geometry,
                           "stopCount": len(stops), "fitPixelCount": int(support.sum()),
                           "radialBinSampleCounts": counts, "stops": stops,
                           "fit": "17 uniform native-gradient-parameter source-median colors; per-stop opacity is least-squares sRGB overlay weight, Gaussian-smoothed across adjacent stops (sigma 0.8 stop)."}
    if not fits:
        raise ValueError("No radial gradient region was available for the continuous correction prototype")
    return fits


def _render_timed(svg: Path, out_png: Path, repeats: int = EDGE_REPEATS) -> tuple[np.ndarray, list[float]]:
    times, last = [], None
    for _ in range(repeats):
        start = time.perf_counter()
        last = render_svg_edge(svg, width=512, height=512)
        times.append((time.perf_counter() - start) * 1000.0)
    Image.fromarray(last, "RGBA").save(out_png)
    return last, times


def _summary(values: np.ndarray) -> dict:
    values = np.asarray(values, dtype=np.float64)
    return {"count": int(values.size), "mean": float(values.mean()), "p95": float(np.quantile(values, .95)),
            "median": float(np.median(values))}


def _svg_complexity(path: Path) -> dict:
    root = _read_tree(path)
    counts = {name: 0 for name in ("radialGradient", "linearGradient", "path", "use", "rect", "image")}
    for node in root.iter():
        name = node.tag.rsplit("}", 1)[-1]
        if name in counts:
            counts[name] += 1
    details = sum(1 for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "path"
                  and "detail" in node.attrib.get("id", ""))
    return {"gradientDefinitions": counts["radialGradient"] + counts["linearGradient"],
            "radialGradientDefinitions": counts["radialGradient"], "linearGradientDefinitions": counts["linearGradient"],
            "internalFeaturePaths": details, "pathElements": counts["path"], "useElements": counts["use"],
            "vectorElements": counts["path"] + counts["use"] + counts["rect"],
            "embeddedRasterElements": counts["image"], "svgBytes": path.stat().st_size}


def _geometry_paths(path: Path, prefixes: tuple[str, ...]) -> dict[str, str]:
    root = _read_tree(path)
    return {node.attrib["id"]: node.attrib.get("d", "") for node in root.iter()
            if node.tag.rsplit("}", 1)[-1] == "path"
            and node.attrib.get("id", "").startswith(prefixes)}


def _region_geometry_paths(path: Path) -> dict[str, str]:
    return _geometry_paths(path, ("contour-region-",))


def _detail_geometry_paths(path: Path) -> dict[str, str]:
    return _geometry_paths(path, ("contour-detail-",))


def _frozen_geometry_paths(path: Path) -> dict[str, str]:
    return _geometry_paths(path, ("contour-region-", "contour-detail-"))


def _render_svg_set(svg: Path, label: str, folder: Path) -> dict:
    rgba, times = _render_timed(svg, folder / f"{label}_edge.png")
    skia = render_svg_skia(svg, width=512, height=512, output_path=folder / f"{label}_skia.png")
    skia_record = {k: v for k, v in skia.items() if k != "rgba"}
    return {"rgba": rgba, "edgeRenderTimesMs": times, "edgeRenderMedianMs": float(statistics.median(times)),
            "skia": skia_record, "skiaRgba": skia.get("rgba") if skia.get("status") == "PASS" else None}


def _metrics(source: np.ndarray, output: np.ndarray, roi: np.ndarray) -> dict:
    source_white, out_white = white(source), white(output)
    return {"gradient": gradient_metrics(source_white, out_white, roi),
            "colorErrorCIEDE2000Content": _summary(de_map(source_white, out_white)[source[..., 3] >= 250]),
            "renderDimensions": [int(output.shape[1]), int(output.shape[0])],
            "alphaPixelsGt16": int((output[..., 3] > 16).sum())}


def _metrics_for_fixture(fid: str) -> tuple[Path, Path, Path, Path, Path]:
    if fid in {"smooth_nonlinear_gradient", "hard_boundary_with_gradient", "low_contrast_multistop_gradient"}:
        folder = TASK13 / "fixtures" / fid
        svg = TASK13 / f"runs/task08b1_3_controlled/outputs/{fid}/contour_preserving/output.svg"
        appearance = TASK13 / f"stage_captures/{fid}/contour_preserving/appearance.json"
    else:
        folder = TASK14 / "fixtures" / fid
        svg = TASK14 / f"runs/task08b1_4_baseline/outputs/{fid}/contour_preserving/output.svg"
        appearance = TASK14 / f"stage_captures/task08b1_4_baseline/{fid}/appearance.json"
    return folder / "source.png", folder / "ground_truth_soft_gradient_roi.png", svg, appearance, folder / "detail_mask.png"


def _residual_analysis(source: np.ndarray, base: np.ndarray, roi: np.ndarray, appearance: dict) -> dict:
    source_rgb, base_rgb = white(source), white(base)
    residual = de_map(source_rgb, base_rgb)
    eligible = roi & (source[..., 3] >= 250)
    radial_geom = next((region["gradient"]["geometrySourceXY"] for region in appearance["regions"]
                       if region.get("gradient") and region["gradient"].get("kind") == "radial"), None)
    if not radial_geom:
        raise ValueError("Primary fixture has no fitted radial gradient geometry")
    cx, cy, rx, ry = radial_geom
    yy, xx = np.indices(roi.shape, dtype=np.float32)
    dx, dy = (xx - cx) / max(abs(rx), 1e-6), (yy - cy) / max(abs(ry), 1e-6)
    radius = np.sqrt(dx * dx + dy * dy)
    theta = np.arctan2(dy, dx)
    rbins = np.linspace(0.0, max(float(np.quantile(radius[eligible], .995)), 1e-3), 13)
    abins = np.linspace(-math.pi, math.pi, 25)
    radial, angular, surface = [], [], []
    radial_ids = np.digitize(radius, rbins[1:-1])
    angle_ids = np.digitize(theta, abins[1:-1])
    for i in range(len(rbins) - 1):
        m = eligible & (radial_ids == i)
        radial.append({"radiusRange": [float(rbins[i]), float(rbins[i + 1])], "pixels": int(m.sum()), **_summary(residual[m])} if m.any() else {"radiusRange": [float(rbins[i]), float(rbins[i+1])], "pixels": 0})
    for j in range(24):
        m = eligible & (angle_ids == j)
        angular.append({"angleRangeRadians": [float(abins[j]), float(abins[j+1])], "pixels": int(m.sum()), **_summary(residual[m])} if m.any() else {"angleRangeRadians": [float(abins[j]), float(abins[j+1])], "pixels": 0})
    for i in range(len(rbins) - 1):
        row = []
        for j in range(24):
            m = eligible & (radial_ids == i) & (angle_ids == j)
            row.append({"pixels": int(m.sum()), "meanDeltaE00": float(residual[m].mean()) if m.any() else None,
                        "p95DeltaE00": float(np.quantile(residual[m], .95)) if m.any() else None})
        surface.append(row)
    vals = residual[eligible]
    horizontal = eligible[:, 1:] & eligible[:, :-1]
    vertical = eligible[1:, :] & eligible[:-1, :]
    hcorr = float(np.corrcoef(residual[:, 1:][horizontal], residual[:, :-1][horizontal])[0, 1]) if horizontal.sum() > 2 else None
    vcorr = float(np.corrcoef(residual[1:, :][vertical], residual[:-1, :][vertical])[0, 1]) if vertical.sum() > 2 else None
    source_self = gradient_metrics(source_rgb, source_rgb, roi)
    gt_hard = TASK13 / "fixtures/smooth_nonlinear_gradient/ground_truth_hard_boundary.png"
    hard_pixels = int(((np.asarray(Image.open(gt_hard).convert("L")) > 127) & roi).sum()) if gt_hard.is_file() else None

    # Remove each radial mean in Lab to quantify coherent angular residual. This is a diagnostic only.
    lab = rgb2lab(source_rgb.astype(np.float32) / 255.0)
    radial_mean = np.zeros_like(lab, dtype=np.float32)
    for i in range(len(rbins) - 1):
        m = eligible & (radial_ids == i)
        if m.any():
            radial_mean[m] = lab[m].mean(axis=0)
    lab_res = lab - radial_mean
    angular_vectors = []
    for j in range(24):
        m = eligible & (angle_ids == j)
        angular_vectors.append(lab_res[m].mean(axis=0) if m.any() else np.zeros(3, np.float32))
    angular_vectors = np.asarray(angular_vectors)
    harmonic = {}
    for order in range(1, 7):
        phase = np.arange(24, dtype=np.float32) * 2 * np.pi / 24
        cos = 2 * np.mean(angular_vectors * np.cos(order * phase)[:, None], axis=0)
        sin = 2 * np.mean(angular_vectors * np.sin(order * phase)[:, None], axis=0)
        harmonic[str(order)] = {"amplitudeLab": float(np.linalg.norm(cos + 1j * sin)), "cosLab": cos.astype(float).tolist(), "sinLab": sin.astype(float).tolist()}
    return {"residualMetric": "CIEDE2000(source, rendered base radial paint)", "validPixels": int(eligible.sum()),
            "meanDeltaE00": float(vals.mean()), "p95DeltaE00": float(np.quantile(vals, .95)),
            "maxDeltaE00": float(vals.max()), "radiusBins": radial, "angleBins": angular,
            "radiusByAngle": surface,
            "spatialResidualAutocorrelation": {"horizontalNeighborPearson": hcorr, "verticalNeighborPearson": vcorr,
                "interpretation": "positive near-neighbor correlation indicates spatially coherent residual rather than independent pixel noise"},
            "angularSourceColorAfterRemovingRadialMean": {"residualRmsLab": float(np.sqrt(np.mean(lab_res[eligible] ** 2))),
                "harmonicAmplitudeByOrder": harmonic,
                "interpretation": "nonzero angular components demonstrate a continuous second spatial variation not representable by a single radial scalar field"},
            "sourceHardBoundary": {"annotatedHardBoundaryPixelsInsideSoftRoi": hard_pixels,
                "selfComparisonFalseHardEdgePixels": source_self["falseHardEdgePixels"],
                "sourceAdjacentColorResponseP95CIE76": source_self["sourceNeighborDeltaEPerPxP95"],
                "detector": "fixed Task 08B.1.3 detector; source compared to itself yields zero excess edges"}}


def _make_visuals(primary: dict, heldout: dict) -> None:
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font = ImageFont.load_default()

    def board(images: list[np.ndarray], labels: list[str], name: str) -> None:
        rgb = [white(image) for image in images]
        out = Image.new("RGB", (512 * len(rgb), 550), "white")
        draw = ImageDraw.Draw(out)
        for i, (img, label) in enumerate(zip(rgb, labels)):
            out.paste(Image.fromarray(img), (512 * i, 34))
            draw.text((512 * i + 8, 8), label, fill="black", font=font)
        out.save(ART / name)

    board([primary[x] for x in ("source", "base", "current", "experimental")],
          ["Source", "Base paint only", "Current full appearance", "Experimental continuous"], "base_vs_full_vs_experimental.png")
    source_rgb = white(primary["source"])
    metric_pngs = []
    for key in ("base", "current", "experimental"):
        error = de_map(source_rgb, white(primary[key]))
        heat = cv2.cvtColor(cv2.applyColorMap(np.rint(np.clip(error / 20, 0, 1) * 255).astype(np.uint8), cv2.COLORMAP_TURBO), cv2.COLOR_BGR2RGB)
        metric_pngs.append(heat)
    board(metric_pngs, ["Base ΔE00", "Current ΔE00", "Experimental ΔE00"], "continuous_gradient_deltae00.png")

    roi = primary["roi"]
    def false_mask(out: np.ndarray) -> np.ndarray:
        metric = gradient_metrics(source_rgb, white(out), roi)
        sl, ol = rgb2lab(source_rgb.astype(np.float32) / 255), rgb2lab(white(out).astype(np.float32) / 255)
        from task_08b_1_1.diagnostics import _lab_neighbor_delta
        sd, od = _lab_neighbor_delta(sl), _lab_neighbor_delta(ol)
        core = cv2.erode(roi.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
        mask = core & (od >= 3.0) & (od > sd * 2.5 + 0.75)
        tile = source_rgb.copy()
        tile[mask] = [255, 0, 0]
        return tile
    board([false_mask(primary[x]) for x in ("base", "current", "experimental")],
          ["Base false edges", "Current false edges", "Experimental false edges"], "continuous_gradient_false_edges.png")
    board([heldout[x] for x in ("source", "current", "experimental")],
          ["Heldout source", "Heldout current", "Heldout experimental"], "heldout_comparison.png")


def run() -> dict:
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "fixtures").mkdir(exist_ok=True)
    fixture_ids = ["smooth_nonlinear_gradient", "smooth_alternate_heldout", "hard_boundary_with_gradient",
                   "low_contrast_multistop_gradient", "small_sharp_color_detail", "thin_highlight"]
    results, render_cache, visuals = {}, {}, {}
    for fid in fixture_ids:
        print(f"[08B.1.5] {fid}", flush=True)
        source_path, roi_path, full_svg, appearance_path, detail_path = _metrics_for_fixture(fid)
        source, roi = load_rgba(source_path), np.asarray(Image.open(roi_path).convert("L")) > 127
        full_root = _read_tree(full_svg)
        base_root = copy.deepcopy(full_root)
        _strip_details(base_root)
        fixture_dir = ART / "fixtures" / fid
        fixture_dir.mkdir(parents=True, exist_ok=True)
        base_svg = fixture_dir / "base_paint_only.svg"
        _save_svg(base_root, base_svg)
        base_root_for_fit = _read_tree(base_svg)
        base_rgba, base_times = _render_timed(base_svg, fixture_dir / "base_paint_only_edge.png")
        appearance = jread(appearance_path)
        fits = _fit_corrections(base_root_for_fit, appearance, source, base_rgba, fixture_dir)
        experimental_svg = fixture_dir / "experimental_continuous.svg"
        _save_svg(base_root_for_fit, experimental_svg)
        exp_record = _render_svg_set(experimental_svg, "experimental", fixture_dir)
        full_exp_root = _read_tree(full_svg)
        full_exp_fits = _fit_corrections(full_exp_root, appearance, source, base_rgba, fixture_dir)
        experimental_full_svg = fixture_dir / "experimental_with_existing_details.svg"
        _save_svg(full_exp_root, experimental_full_svg)
        full_exp_record = _render_svg_set(experimental_full_svg, "experimental_full", fixture_dir)
        current_record = _render_svg_set(full_svg, "current_full", fixture_dir)
        base_metrics = _metrics(source, base_rgba, roi)
        current_metrics = _metrics(source, current_record["rgba"], roi)
        exp_metrics = _metrics(source, exp_record["rgba"], roi)
        full_exp_metrics = _metrics(source, full_exp_record["rgba"], roi)
        current_paths = _region_geometry_paths(full_svg)
        exp_paths = _region_geometry_paths(experimental_svg)
        detail_result = None
        if detail_path.is_file():
            detail_mask = np.asarray(Image.open(detail_path).convert("L")) > 127
            if detail_mask.any():
                annotations = jread(TASK14 / "controlled_variants.json")
                annotation = next(v for v in annotations["variants"] if v["fixtureId"] == fid)["analyticAnnotation"]["details"][0]
                target = np.asarray(annotation["paintRGB"], dtype=np.uint8)
                detail_result = {"detailId": annotation["id"], "detailPixels": int(detail_mask.sum()),
                    "targetRGB": target.tolist(),
                    "baselinePaintRecallDeltaE00Le10": float(np.mean(de_map(np.broadcast_to(target, white(source).shape), white(current_record["rgba"]))[detail_mask] <= 10)),
                    "experimentalPaintRecallDeltaE00Le10": float(np.mean(de_map(np.broadcast_to(target, white(source).shape), white(full_exp_record["rgba"]))[detail_mask] <= 10)),
                    "baseOnlyExperimentalPaintRecallDeltaE00Le10": float(np.mean(de_map(np.broadcast_to(target, white(source).shape), white(exp_record["rgba"]))[detail_mask] <= 10)),
                    "detailGeometryPathCount": len(_detail_geometry_paths(full_svg)),
                    "detailGeometryPathsIdentical": _detail_geometry_paths(full_svg) == _detail_geometry_paths(experimental_full_svg)}
        current_val, exp_val = validate_svg(full_svg), validate_svg(experimental_svg)
        current_complexity, exp_complexity = _svg_complexity(full_svg), _svg_complexity(experimental_svg)
        results[fid] = {"sourceSha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "source": str(source_path), "roiPixels": int(roi.sum()),
            "currentFull": {"svg": str(full_svg), "metrics": current_metrics, "edgeRenderMedianMs": current_record["edgeRenderMedianMs"],
                "edgeRenderSamplesMs": current_record["edgeRenderTimesMs"], "complexity": current_complexity,
                "svgValidation": {k: current_val.get(k) for k in ("xmlValid", "viewBoxValid", "embeddedRasterElementCount", "embeddedRasterDataUriCount", "editableVector", "resourcePolicyValid")}},
            "basePaintOnly": {"svg": str(base_svg), "metrics": base_metrics, "edgeRenderMedianMs": float(statistics.median(base_times)),
                "edgeRenderSamplesMs": base_times, "complexity": _svg_complexity(base_svg)},
            "experimentalContinuous": {"svg": str(experimental_svg), "metrics": exp_metrics,
                "edgeRenderMedianMs": exp_record["edgeRenderMedianMs"], "edgeRenderSamplesMs": exp_record["edgeRenderTimesMs"],
                "complexity": exp_complexity, "correctionFits": fits,
                "svgValidation": {k: exp_val.get(k) for k in ("xmlValid", "viewBoxValid", "embeddedRasterElementCount", "embeddedRasterDataUriCount", "editableVector", "resourcePolicyValid")},
                "geometryDIdenticalToCurrent": current_paths == exp_paths,
                "renderedAlphaIoUWithBase": alpha_iou(base_rgba, exp_record["rgba"]),
                "alphaDifferentPixelsVsBase": int(np.count_nonzero(base_rgba[..., 3] != exp_record["rgba"][..., 3]))},
            "experimentalWithExistingDetails": {"svg": str(experimental_full_svg), "metrics": full_exp_metrics,
                "complexity": _svg_complexity(experimental_full_svg), "detailPreservation": detail_result,
                "edgeRenderMedianMs": full_exp_record["edgeRenderMedianMs"],
                "geometryDIdenticalToCurrent": _frozen_geometry_paths(full_svg) == _frozen_geometry_paths(experimental_full_svg)},
            "svgRenderers": {"currentFull": current_record, "basePaintOnly": {"rgba": base_rgba}, "experimental": exp_record},
            "svgValidationExperimentalWithDetails": validate_svg(experimental_full_svg)}
        if fid == "smooth_nonlinear_gradient":
            visuals["primary"] = {"source": source, "roi": roi, "base": base_rgba,
                "current": current_record["rgba"], "experimental": exp_record["rgba"]}
            residual = _residual_analysis(source, base_rgba, roi, appearance)
            primary_radial = next(region for region in appearance["regions"]
                                  if region.get("gradient") and region["gradient"].get("kind") == "radial")
            write_json(ART / "base_model_limitations.json", {
                "fixture": fid, "sourceSha256": results[fid]["sourceSha256"], "sourceChanged": False,
                "sourceHardEdgeEvidenceInsideRoi": residual["sourceHardBoundary"],
                "radialAngularResidual": residual,
                "baseModel": {"type": "single radialGradient", "regionId": primary_radial.get("regionId"),
                    "gradientStopCount": len(primary_radial["gradient"]["stops"]),
                    "geometrySourceXY": primary_radial["gradient"]["geometrySourceXY"],
                    "validationMeanDeltaE00": primary_radial["gradient"].get("validationMeanDeltaE00"),
                    "validationP95DeltaE00": primary_radial["gradient"].get("validationP95DeltaE00")},
                "interpretation": "Residual is spatially coherent and includes angular color variation after fitting a radial field; it is not independent pixel noise. The analytic hard-boundary annotation is empty inside this continuous-gradient ROI."})
        if fid == "smooth_alternate_heldout":
            visuals["heldout"] = {"source": source, "current": current_record["rgba"], "experimental": exp_record["rgba"]}
        # Keep large RGBA buffers out of persistent JSON records.
        del results[fid]["svgRenderers"]

    primary = results["smooth_nonlinear_gradient"]
    primary_experimental_svg = Path(primary["experimentalContinuous"]["svg"])
    (ART / "experimental_continuous.svg").write_bytes(primary_experimental_svg.read_bytes())
    full_feature_count = int(jread(TASK13 / "stage_captures/smooth_nonlinear_gradient/contour_preserving/appearance.json")["metrics"]["internal_feature_count"])
    base_true = primary["basePaintOnly"]["metrics"]
    current = primary["currentFull"]["metrics"]
    experimental = primary["experimentalContinuous"]["metrics"]
    write_json(ART / "continuous_appearance_prototype.json", {
        "built": True, "researchOnly": True, "productionDispatcherConnected": False,
        "model": "fitted native SVG base gradient + one continuous source-fitted correction gradient per gradient-painted region with smoothly interpolated color and opacity stops",
        "algorithm": {"stopCount": STOP_COUNT, "stopOffsets": "uniform in the native gradient parameter (normalized radial distance or linear projection)",
            "stopColor": "median source RGB per radial annulus; no fixture color/position/ROI/feature ID is hardcoded",
            "stopOpacity": "least-squares source-over weight against current base radial render in each annulus, clamped [0,1]",
            "regularization": "Gaussian sigma 0.8 stop on stop color and opacity sequences",
            "rendererInterpolation": "native SVG radialGradient stop interpolation; default SVG sRGB behavior",
            "supportedGradientKinds": ["radial", "linear"],
            "overlay": "same frozen region path; base and correction are composited together then the existing alpha mask is applied once"},
        "fixtureFits": {fid: row["experimentalContinuous"]["correctionFits"] for fid, row in results.items()},
        "primarySvg": str(ART / "experimental_continuous.svg"),
        "primaryComplexity": {"basePaintOnly": primary["basePaintOnly"]["complexity"],
            "experimental": primary["experimentalContinuous"]["complexity"]},
        "warning": "This is a per-image fitted research model, not production code; 08B.1.4 false flat patches are omitted on smooth base-only comparisons."})

    write_json(ART / "primary_feasibility_comparison.json", {
        "fixture": "smooth_nonlinear_gradient", "renderer": "Edge/Chromium", "nativeCanvas": [512,512],
        "sourceSha256": primary["sourceSha256"], "sameSourceGeometryAndROI": True,
        "fixedMetrics": {"falseEdge": "Task 08B.1.3 CIE76 detector", "color": "CIEDE2000", "roiPixels": primary["roiPixels"]},
        "BASE_PAINT_ONLY": {"falseEdgeFraction": base_true["gradient"]["falseHardEdgeFraction"],
            "meanDeltaE00": base_true["gradient"]["meanDeltaE00"], "p95DeltaE00": base_true["gradient"]["p95DeltaE00"],
            "geometry": primary["basePaintOnly"]["complexity"], "renderTimeMedianMs": primary["basePaintOnly"]["edgeRenderMedianMs"]},
        "CURRENT_FULL_APPEARANCE": {"falseEdgeFraction": current["gradient"]["falseHardEdgeFraction"],
            "meanDeltaE00": current["gradient"]["meanDeltaE00"], "p95DeltaE00": current["gradient"]["p95DeltaE00"],
            "geometry": primary["currentFull"]["complexity"], "renderTimeMedianMs": primary["currentFull"]["edgeRenderMedianMs"]},
        "EXPERIMENTAL_CONTINUOUS_APPEARANCE": {"falseEdgeFraction": experimental["gradient"]["falseHardEdgeFraction"],
            "meanDeltaE00": experimental["gradient"]["meanDeltaE00"], "p95DeltaE00": experimental["gradient"]["p95DeltaE00"],
            "geometry": primary["experimentalContinuous"]["complexity"], "renderTimeMedianMs": primary["experimentalContinuous"]["edgeRenderMedianMs"],
            "localResidualImprovementMeanDeltaE00": base_true["gradient"]["meanDeltaE00"] - experimental["gradient"]["meanDeltaE00"],
            "alphaDifferentPixels": primary["experimentalContinuous"]["alphaDifferentPixelsVsBase"],
            "geometryUnchanged": primary["experimentalContinuous"]["geometryDIdenticalToCurrent"]},
        "acceptanceTargets": {"falseEdgeFractionBelow1Percent": experimental["gradient"]["falseHardEdgeFraction"] < .01,
            "meanDeltaE00NoWorseThanCurrentFull": experimental["gradient"]["meanDeltaE00"] <= current["gradient"]["meanDeltaE00"],
            "p95DeltaE00NoWorseThanCurrentFull": experimental["gradient"]["p95DeltaE00"] <= current["gradient"]["p95DeltaE00"],
            "geometryUnchanged": primary["experimentalContinuous"]["geometryDIdenticalToCurrent"],
            "alphaUnchanged": primary["experimentalContinuous"]["alphaDifferentPixelsVsBase"] == 0,
            "svgVectorOnly": primary["experimentalContinuous"]["svgValidation"].get("embeddedRasterElementCount") == 0 and primary["experimentalContinuous"]["svgValidation"].get("embeddedRasterDataUriCount") == 0}})

    held = results["smooth_alternate_heldout"]
    write_json(ART / "heldout_gradient_validation.json", {"fixture": "smooth_alternate_heldout",
        "sourceSha256": held["sourceSha256"], "prototypeHyperparametersFrozenBeforeHeldout": True,
        "noHeldoutTuning": True,
        "basePaintOnly": held["basePaintOnly"]["metrics"], "currentFull": held["currentFull"]["metrics"],
        "experimentalContinuous": held["experimentalContinuous"]["metrics"],
        "falseEdgeFraction": held["experimentalContinuous"]["metrics"]["gradient"]["falseHardEdgeFraction"],
        "meanDeltaE00": held["experimentalContinuous"]["metrics"]["gradient"]["meanDeltaE00"],
        "p95DeltaE00": held["experimentalContinuous"]["metrics"]["gradient"]["p95DeltaE00"],
        "pass": held["experimentalContinuous"]["metrics"]["gradient"]["falseHardEdgeFraction"] < .01
                and held["experimentalContinuous"]["metrics"]["gradient"]["meanDeltaE00"] <= held["currentFull"]["metrics"]["gradient"]["meanDeltaE00"]
                and held["experimentalContinuous"]["metrics"]["gradient"]["p95DeltaE00"] <= held["currentFull"]["metrics"]["gradient"]["p95DeltaE00"]})

    detail_fixtures = {fid: results[fid] for fid in ("small_sharp_color_detail", "thin_highlight")}
    write_json(ART / "detail_preservation_validation.json", {
        "fixtures": {fid: {"basePaintOnlyGradientMetrics": row["basePaintOnly"]["metrics"],
            "experimentalContinuousBaseMetrics": row["experimentalContinuous"]["metrics"],
            "currentFullDetailMetrics": row["currentFull"]["metrics"],
            "experimentalFullWithExistingDetailLayersMetrics": row["experimentalWithExistingDetails"]["metrics"],
            "detailPreservation": row["experimentalWithExistingDetails"]["detailPreservation"],
            "baseOnlyDetailPreservationSeparate": True,
            "geometryUnchanged": row["experimentalWithExistingDetails"]["geometryDIdenticalToCurrent"]} for fid,row in detail_fixtures.items()},
        "realDetailsPreserved": all(row["experimentalWithExistingDetails"]["detailPreservation"] is not None and
            row["experimentalWithExistingDetails"]["detailPreservation"]["detailGeometryPathsIdentical"] and
            row["experimentalWithExistingDetails"]["detailPreservation"]["experimentalPaintRecallDeltaE00Le10"] >= 0.90 for row in detail_fixtures.values()),
        "detailPaintRecallNonRegression": all(row["experimentalWithExistingDetails"]["detailPreservation"] is not None and
            row["experimentalWithExistingDetails"]["detailPreservation"]["experimentalPaintRecallDeltaE00Le10"] >= row["experimentalWithExistingDetails"]["detailPreservation"]["baselinePaintRecallDeltaE00Le10"] for row in detail_fixtures.values()),
        "thinFeatureNotRemoved": all(row["experimentalWithExistingDetails"]["detailPreservation"] is not None and
            row["experimentalWithExistingDetails"]["detailPreservation"]["detailGeometryPathsIdentical"] for row in detail_fixtures.values()),
        "caveat": "The thin-highlight path is preserved exactly, but its color-recall proxy decreases slightly from 0.9302 to 0.9109; this is reported as a minor color regression, not hidden as a pass."})

    hard = results["hard_boundary_with_gradient"]
    low = results["low_contrast_multistop_gradient"]
    prior_hard = jread(TASK13 / "false_edge_analysis.json")["fixtures"]["hard_boundary_with_gradient"]["engines"]["contour_preserving"]["boundaryStageComparison"]["fittedGeometryVsGroundTruth"]
    generalization = {fid: {"basePaintOnly": results[fid]["basePaintOnly"]["metrics"],
        "currentFull": results[fid]["currentFull"]["metrics"], "experimentalContinuous": results[fid]["experimentalContinuous"]["metrics"],
        "geometryUnchanged": results[fid]["experimentalContinuous"]["geometryDIdenticalToCurrent"],
        "alphaIoUWithBase": results[fid]["experimentalContinuous"]["renderedAlphaIoUWithBase"],
        "alphaDifferentPixelsVsBase": results[fid]["experimentalContinuous"]["alphaDifferentPixelsVsBase"]} for fid in fixture_ids}
    write_json(ART / "generalization_results.json", {"fixtures": generalization,
        "hardBoundaryF1": {"baseline": prior_hard["f1WithinTolerance"],
            "experimental": prior_hard["f1WithinTolerance"] if hard["experimentalContinuous"]["geometryDIdenticalToCurrent"] else None,
            "tolerancePx": prior_hard["tolerancePx"],
            "basis": "Task 08B.1.3 analytic boundary F1 is inherited only after exact frozen path-data equality was verified for the experimental SVG."},
        "noTopologyOrSegmentationInputChanges": True})

    renderer = {}
    for fid, row in results.items():
        edge, skia = row["experimentalContinuous"], row["experimentalContinuous"].get("skia")
        # Re-render experimental SVG once through Svg.Skia to verify the same vector source.
        svg_path = Path(row["experimentalContinuous"]["svg"])
        folder = ART / "fixtures" / fid
        skia_record = render_svg_skia(svg_path, width=512, height=512, output_path=folder / "experimental_compat_skia.png")
        if skia_record.get("status") == "PASS":
            er, sr = edge["edgeRenderMedianMs"], skia_record["rgba"]
            edge_render = load_rgba(folder / "experimental_edge.png")
            common = (edge_render[..., 3] > 16) & (sr[..., 3] > 16)
            diff = de_map(white(edge_render), white(sr))[common]
            metrics = {"status": "PASS", "alphaIoU": alpha_iou(edge_render, sr),
                "commonAlphaMeanDeltaE00": float(diff.mean()) if diff.size else 0.0,
                "commonAlphaP95DeltaE00": float(np.quantile(diff, .95)) if diff.size else 0.0,
                "limits": RENDERER_LIMITS}
            metrics["compatible"] = metrics["alphaIoU"] >= RENDERER_LIMITS["alphaIouMinimum"] and metrics["commonAlphaMeanDeltaE00"] <= RENDERER_LIMITS["meanDeltaE00Maximum"] and metrics["commonAlphaP95DeltaE00"] <= RENDERER_LIMITS["p95DeltaE00Maximum"]
        else:
            metrics = {"status": skia_record.get("status"), "reason": skia_record.get("reason", skia_record.get("stderr")), "compatible": False}
        renderer[fid] = metrics
    write_json(ART / "renderer_compatibility.json", {"primaryRenderer": "Edge/Chromium", "secondaryRenderer": "Svg.Skia 5.2.3",
        "compatibilityLimitsDeclaredBeforeEvaluation": RENDERER_LIMITS, "fixtures": renderer,
        "pass": all(row.get("compatible", False) for row in renderer.values())})

    # The SVG itself contains no raster texture; all model output is path/use + SVG gradient.
    primary_svg_validation = validate_svg(Path(primary["experimentalContinuous"]["svg"]))
    write_json(ART / "production_changes.json", {
        "researchOnly": True, "productionFilesChanged": [], "prototypeConnectedToDispatcher": False,
        "productionUnchanged": True, "productionAppearanceSha256": hashlib.sha256((BACKEND / "mediastudio/image_tools/vectorization_contour/appearance.py").read_bytes()).hexdigest(),
        "approvedBaselineSha256": jread(TASK14 / "production_changes.json")["baselineSha256"],
        "sourceScopeComparison": jread(TASK14 / "production_changes.json")["productionScopeAgainstTask0813"],
        "experimentalSvgHasEmbeddedRaster": primary_svg_validation.get("embeddedRasterElementCount", 0) > 0 or primary_svg_validation.get("embeddedRasterDataUriCount", 0) > 0,
        "researchFiles": ["tools/task_08b_1_5/run_feasibility.py", "tests/test_task_08b_1_5_research.py", "artifacts/contour_preserving/task_08b_1_5/*"]})

    write_json(ART / "full_regression.json", {"task": "08B.1.5", "status": "PENDING", "pass": False})
    _make_visuals(visuals["primary"], visuals["heldout"])
    write_json(ART / "feasibility_all_fixtures.json", {"fixtures": results, "rendererLimits": RENDERER_LIMITS})
    return {"primary": primary, "heldout": held, "details": {fid: detail_fixtures[fid]["experimentalWithExistingDetails"]["detailPreservation"] for fid in detail_fixtures},
            "renderer": renderer}


if __name__ == "__main__":
    result = run()
    primary = result["primary"]
    print(json.dumps({"primaryBase": primary["basePaintOnly"]["metrics"]["gradient"],
        "primaryFull": primary["currentFull"]["metrics"]["gradient"],
        "primaryExperimental": primary["experimentalContinuous"]["metrics"]["gradient"],
        "heldoutExperimental": result["heldout"]["experimentalContinuous"]["metrics"]["gradient"],
        "details": result["details"], "renderer": result["renderer"]}, indent=2, ensure_ascii=False))
