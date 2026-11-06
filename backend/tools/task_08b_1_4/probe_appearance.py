from __future__ import annotations

import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import cv2
import numpy as np
from PIL import Image
from skimage.color import deltaE_ciede2000, rgb2lab

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
TASK13 = BACKEND / "artifacts/contour_preserving/task_08b_1_3"
TASK14 = BACKEND / "artifacts/contour_preserving/task_08b_1_4"
SVG = TASK13 / "stage_captures/smooth_nonlinear_gradient/contour_preserving/appearance_diagnostic.svg"
SOURCE = TASK13 / "fixtures/smooth_nonlinear_gradient/source.png"
ROI_PATH = TASK13 / "fixtures/smooth_nonlinear_gradient/ground_truth_soft_gradient_roi.png"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tools"))

from task_08b_1_1.diagnostics import gradient_metrics, _lab_neighbor_delta
from vectorization_benchmark.svg import render_svg_edge

ET.register_namespace("", "http://www.w3.org/2000/svg")
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
NS = "{http://www.w3.org/2000/svg}"


def write_variant(root: ET.Element, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def visible_paths(root: ET.Element) -> list[ET.Element]:
    result = []
    for node in root.iter(f"{NS}path"):
        if "detail" in node.attrib.get("id", ""):
            result.append(node)
    return result


def _remove_non_detail(root: ET.Element, keep: set[str], *, as_mask: bool = False) -> None:
    for parent in root.iter():
        for child in list(parent):
            if as_mask and child.tag == f"{NS}use" and parent is root:
                parent.remove(child)
                continue
            if child.tag != f"{NS}path":
                continue
            identifier = child.attrib.get("id", "")
            if "detail" in identifier:
                if identifier not in keep:
                    parent.remove(child)
                elif as_mask:
                    child.set("fill", "#ffffff")
                    child.set("fill-opacity", "1")
                    child.set("opacity", "1")
            elif as_mask and parent.tag != f"{NS}defs":
                parent.remove(child)
    if as_mask:
        # Force a black backdrop so the rasterizer's opaque screenshot alpha
        # cannot be mistaken for the feature mask.
        rect = ET.Element(f"{NS}rect", {"x": "0", "y": "0", "width": "512",
                                        "height": "512", "fill": "#000000"})
        defs_index = next((i + 1 for i, child in enumerate(list(root)) if child.tag == f"{NS}defs"), 0)
        root.insert(defs_index, rect)


def render_variant(source_root: ET.Element, path: Path, *, keep: set[str] | None,
                   mask: bool = False) -> np.ndarray:
    root = ET.fromstring(ET.tostring(source_root))
    if keep is not None:
        _remove_non_detail(root, keep, as_mask=mask)
    write_variant(root, path)
    return render_svg_edge(path, width=512, height=512)


def white(rgb_or_rgba: np.ndarray) -> np.ndarray:
    a = np.asarray(rgb_or_rgba, dtype=np.float32)
    if a.shape[-1] == 4:
        alpha = a[..., 3:4] / 255.0
        a = a[..., :3] * alpha + 255.0 * (1 - alpha)
    return np.rint(a).clip(0, 255).astype(np.uint8)


def de00(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return deltaE_ciede2000(rgb2lab(a.astype(np.float32) / 255.0),
                            rgb2lab(b.astype(np.float32) / 255.0)).astype(np.float32)


def false_mask(source: np.ndarray, output: np.ndarray, roi: np.ndarray) -> tuple[np.ndarray, dict]:
    metric = gradient_metrics(source, output, roi)
    sl = rgb2lab(source.astype(np.float32) / 255.0)
    ol = rgb2lab(output.astype(np.float32) / 255.0)
    sd, od = _lab_neighbor_delta(sl), _lab_neighbor_delta(ol)
    core = cv2.erode(roi.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
    if not core.any():
        core = roi
    return core & (od >= 3.0) & (od > sd * 2.5 + 0.75), metric


def summary(values: np.ndarray) -> dict[str, float | int]:
    values = np.asarray(values)
    return {"count": int(values.size), "mean": float(values.mean()) if values.size else 0.0,
            "p95": float(np.quantile(values, .95)) if values.size else 0.0,
            "median": float(np.median(values)) if values.size else 0.0}


def rgb_summary(rgb: np.ndarray) -> dict[str, object]:
    values = np.asarray(rgb, dtype=np.float32).reshape(-1, 3)
    return {"count": int(len(values)),
            "meanRGB": [float(x) for x in values.mean(axis=0)] if len(values) else [0.0] * 3,
            "stdRGB": [float(x) for x in values.std(axis=0)] if len(values) else [0.0] * 3,
            "p05RGB": [float(x) for x in np.quantile(values, .05, axis=0)] if len(values) else [0.0] * 3,
            "p95RGB": [float(x) for x in np.quantile(values, .95, axis=0)] if len(values) else [0.0] * 3}


def crossing_edge_summary(rgb: np.ndarray, mask: np.ndarray, roi: np.ndarray) -> dict[str, object]:
    lab = rgb2lab(rgb.astype(np.float32) / 255.0)
    values = []
    for first, second, valid in (
        (lab[:, :-1], lab[:, 1:], roi[:, :-1] & roi[:, 1:] & (mask[:, :-1] != mask[:, 1:])),
        (lab[:-1, :], lab[1:, :], roi[:-1, :] & roi[1:, :] & (mask[:-1, :] != mask[1:, :])),
    ):
        if valid.any():
            values.extend(np.linalg.norm(first[valid] - second[valid], axis=1).tolist())
    return summary(np.asarray(values, dtype=np.float32))


def main() -> None:
    source_rgba = np.asarray(Image.open(SOURCE).convert("RGBA"), dtype=np.uint8)
    source = white(source_rgba)
    roi = np.asarray(Image.open(ROI_PATH).convert("L"), dtype=np.uint8) > 127
    roi_core = cv2.erode(roi.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
    root = ET.parse(SVG).getroot()
    paths = sorted(visible_paths(root), key=lambda node: node.attrib.get("id", ""))
    ids = [node.attrib["id"] for node in paths]
    tmp = TASK14 / "root_cause_probe"
    tmp.mkdir(parents=True, exist_ok=True)
    base_rgba = render_variant(root, tmp / "base_only.svg", keep=set())
    full_rgba = render_variant(root, tmp / "all_features.svg", keep=set(ids))
    base, full = white(base_rgba), white(full_rgba)
    base_de, full_de = de00(source, base), de00(source, full)
    base_false, base_fm = false_mask(source, base, roi)
    full_false, full_fm = false_mask(source, full, roi)
    feature_rows = []
    for node in paths:
        fid = node.attrib["id"]
        mask_rgba = render_variant(root, tmp / f"{fid}_mask.svg", keep={fid}, mask=True)
        feature_mask = mask_rgba[..., :3].mean(axis=2) > 128
        ys, xs = np.nonzero(feature_mask)
        local = feature_mask & roi_core
        boundary = feature_mask ^ (cv2.erode(feature_mask.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0)
        near = cv2.dilate(boundary.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
        near &= roi_core
        Image.fromarray(np.where(feature_mask, 255, 0).astype(np.uint8)).save(tmp / f"{fid}_mask.png")
        only_rgba = render_variant(root, tmp / f"{fid}_only.svg", keep={fid})
        only = white(only_rgba)
        before_local = summary(base_de[local])
        after_local = summary(de00(source, only)[local])
        before_near = summary(base_de[near])
        after_near = summary(de00(source, only)[near])
        all_near = cv2.dilate(boundary.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
        all_near &= roi_core
        row = {
            "featureId": fid, "parentRegion": "r5", "bbox": [int(xs.min()), int(ys.min()), int(xs.max()+1), int(ys.max()+1)] if len(xs) else None,
            "featureMaskAreaPixels": int(feature_mask.sum()), "featureMaskAreaInROI": int(local.sum()),
            "boundaryPixels": int((boundary & roi_core).sum()),
            "featurePaint": {"fill": node.get("fill"), "opacity": node.get("fill-opacity")},
            "sourceRGB": rgb_summary(source[local]) if local.any() else None,
            "basePredictionDeltaE00": before_local, "predictionAfterFeatureDeltaE00": after_local,
            "baseResidualWithinBoundaryNeighborhoodDeltaE00": before_near,
            "residualAfterFeatureWithinBoundaryNeighborhoodDeltaE00": after_near,
            "falseEdgePixelsNearFeatureBoundary": int((full_false & all_near).sum()),
            "featureOnlyFalseEdgePixelsNearBoundary": int((false_mask(source, only, roi)[0] & all_near).sum()),
            "sourceBoundaryResponseCIE76": summary(_lab_neighbor_delta(rgb2lab(source.astype(np.float32)/255.0))[boundary & roi_core]),
            "sourceCrossingBoundaryResponseCIE76": crossing_edge_summary(source, local, roi_core),
            "baseBoundaryResponseCIE76": summary(_lab_neighbor_delta(rgb2lab(base.astype(np.float32)/255.0))[boundary & roi_core]),
            "baseCrossingBoundaryResponseCIE76": crossing_edge_summary(base, local, roi_core),
            "featureOnlyBoundaryResponseCIE76": summary(_lab_neighbor_delta(rgb2lab(only.astype(np.float32)/255.0))[boundary & roi_core]),
            "meanLocalDeltaE00Change": float(after_local["mean"] - before_local["mean"]),
            "meanBoundaryNeighborhoodDeltaE00Change": float(after_near["mean"] - before_near["mean"]),
        }
        feature_rows.append(row)

    result = {
        "baselineSource": "Task 08B.1.3 captured appearance diagnostic SVG and source fixture",
        "renderer": "Edge/Chromium at native 512x512",
        "colorMetric": "CIEDE2000 (ΔE00)",
        "edgeMetric": "Task 08B.1.3 exact CIE76 adjacent-pixel detector; threshold >=3 and > source*2.5+0.75",
        "roiPixels": int(roi.sum()), "metricInteriorPixels": int(roi_core.sum()),
        "basePaintOnly": {"meanDeltaE00": summary(base_de[roi_core]), "falseEdgeFraction": float(base_false.sum()/max(roi_core.sum(),1)), "falseEdgePixels": int(base_false.sum())},
        "appearanceWithFeatures": {"meanDeltaE00": summary(full_de[roi_core]), "falseEdgeFraction": float(full_false.sum()/max(roi_core.sum(),1)), "falseEdgePixels": int(full_false.sum())},
        "featureRows": feature_rows,
    }
    out = TASK14 / "internal_feature_diagnostics_preliminary.json"
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    Image.fromarray(base_rgba).save(tmp / "base_only.png")
    Image.fromarray(full_rgba).save(tmp / "all_features.png")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
