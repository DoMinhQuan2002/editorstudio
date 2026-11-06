from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw
from skimage.color import deltaE_ciede2000, rgb2lab

from .dataset import write_json
from .metrics import composite_rgba


def _heatmap(values: np.ndarray, *, scale: float = 18.0) -> np.ndarray:
    normalized = np.clip(np.asarray(values, dtype=np.float32) * (255.0 / max(scale, 1e-6)), 0, 255).astype(np.uint8)
    return cv2.applyColorMap(normalized, cv2.COLORMAP_INFERNO)[..., ::-1]


def _mask_iou(box_a: tuple[int, int, int, int], box_b: tuple[int, int, int, int]) -> float:
    ax0, ay0, ax1, ay1 = box_a
    bx0, by0, bx1, by1 = box_b
    ix0, iy0, ix1, iy1 = max(ax0, bx0), max(ay0, by0), min(ax1, bx1), min(ay1, by1)
    intersection = max(0, ix1 - ix0) * max(0, iy1 - iy0)
    area_a = max(0, ax1 - ax0) * max(0, ay1 - ay0)
    area_b = max(0, bx1 - bx0) * max(0, by1 - by0)
    return intersection / max(area_a + area_b - intersection, 1)


def _risk_map(analysis: dict[str, np.ndarray]) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    delta = np.asarray(analysis["deltaE00"], dtype=np.float32)
    edge = np.asarray(analysis["edgeMismatch"], dtype=np.float32)
    displacement = np.asarray(analysis.get("boundaryDisplacementPx", np.zeros_like(edge)), dtype=np.float32)
    edge = np.maximum(edge, np.clip(displacement / 3.0, 0, 1))
    alpha = np.asarray(analysis["alphaAbsoluteDifference"], dtype=np.float32) / 255.0
    gradient = np.asarray(analysis["sourceGradientMagnitude"], dtype=np.float32)
    foreground = np.asarray(analysis["sourceForegroundMask"], dtype=bool)
    p95 = float(np.quantile(gradient[foreground], 0.95)) if foreground.any() else 1.0
    salience = np.clip(gradient / max(p95, 1e-4), 0, 2) / 2
    delta_term = np.clip(delta / 15.0, 0, 1)
    # Edge and alpha terms keep thin, high-impact defects visible even when their area is small.
    risk = 0.42 * delta_term + 0.32 * edge + 0.20 * alpha + 0.06 * salience
    return np.clip(risk, 0, 1), {
        "deltaE": delta_term,
        "edgeDisagreement": edge,
        "alphaMismatch": alpha,
        "sourceGradientSalience": salience,
    }


def select_error_rois(analysis: dict[str, np.ndarray], *, max_rois: int = 4) -> list[dict[str, Any]]:
    risk, components = _risk_map(analysis)
    height, width = risk.shape
    window_w = min(width, max(64, int(round(width * 0.16))))
    window_h = min(height, max(64, int(round(height * 0.16))))
    stride_x, stride_y = max(24, window_w // 2), max(24, window_h // 2)
    candidates: list[tuple[float, tuple[int, int, int, int], dict[str, float]]] = []
    xs = list(range(0, max(1, width - window_w + 1), stride_x))
    ys = list(range(0, max(1, height - window_h + 1), stride_y))
    if not xs or xs[-1] != width - window_w:
        xs.append(max(0, width - window_w))
    if not ys or ys[-1] != height - window_h:
        ys.append(max(0, height - window_h))
    for y0 in ys:
        for x0 in xs:
            box = (x0, y0, x0 + window_w, y0 + window_h)
            patch = risk[y0:y0 + window_h, x0:x0 + window_w]
            # The upper-tail term makes a small bright or thin-feature defect rank above a broad low-contrast color shift.
            mean = float(patch.mean())
            # A percentile threshold can still miss a region occupying slightly
            # less than the chosen tail. Average the top 5% instead, so narrow
            # highlights and small glyph/details contribute to the ROI score.
            flat = patch.reshape(-1)
            top_count = max(1, int(np.ceil(flat.size * 0.05)))
            upper_tail = float(np.partition(flat, flat.size - top_count)[-top_count:].mean())
            score = 0.45 * mean + 0.55 * upper_tail
            term_scores = {
                name: float(values[y0:y0 + window_h, x0:x0 + window_w].mean())
                for name, values in components.items()
            }
            candidates.append((score, box, term_scores))
    candidates.sort(key=lambda row: row[0], reverse=True)
    selected: list[dict[str, Any]] = []
    for score, box, terms in candidates:
        if score < 0.035:
            break
        if any(_mask_iou(box, tuple(row["bboxPx"])) > 0.25 for row in selected):
            continue
        dominant = max(terms, key=terms.get) if terms else "unknown"
        category = {
            "deltaE": "COLOR_OR_APPEARANCE_DIFFERENCE",
            "edgeDisagreement": "BOUNDARY_OR_GEOMETRY_DIFFERENCE",
            "alphaMismatch": "ALPHA_OR_SILHOUETTE_DIFFERENCE",
            "sourceGradientSalience": "HIGH_GRADIENT_DETAIL_REVIEW",
        }.get(dominant, "UNKNOWN")
        selected.append({
            "bboxPx": list(box),
            "bboxNormalized": [box[0] / width, box[1] / height, box[2] / width, box[3] / height],
            "combinedRiskScore": score,
            "componentScores": terms,
            "errorCategory": category,
            "confidence": "high" if score >= 0.20 else "medium" if score >= 0.09 else "low",
            "reviewStatus": "pending_human_review",
        })
        if len(selected) >= max_rois:
            break
    return selected


def _source_output_edges(source: np.ndarray, output: np.ndarray, color: tuple[int, int, int]) -> np.ndarray:
    source_gray = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY)
    output_gray = cv2.cvtColor(output, cv2.COLOR_RGB2GRAY)
    se = cv2.Canny(source_gray, 40, 130) > 0
    oe = cv2.Canny(output_gray, 40, 130) > 0
    canvas = output.copy()
    canvas[se] = (235, 48, 63)
    canvas[oe] = color
    canvas[se & oe] = (252, 208, 52)
    return canvas


def _contact_sheet(image_id: str, source: np.ndarray, smart: np.ndarray, contour: np.ndarray,
                   smart_delta: np.ndarray, contour_delta: np.ndarray, path: Path) -> None:
    panels = [
        ("SOURCE", source),
        ("SMART V2 · white", composite_rgba(smart, "white")),
        ("CONTOUR · white", composite_rgba(contour, "white")),
        ("MAX SOURCE ΔE00", _heatmap(np.maximum(smart_delta, contour_delta), scale=20)),
    ]
    cell = 280
    header = 32
    canvas = Image.new("RGB", (cell * 4, cell + header), "#f0f1f4")
    draw = ImageDraw.Draw(canvas)
    for index, (label, array) in enumerate(panels):
        x = index * cell
        draw.text((x + 8, 9), f"{image_id} · {label}", fill=(28, 34, 45))
        image = Image.fromarray(np.asarray(array, dtype=np.uint8), "RGB")
        image.thumbnail((cell, cell), Image.Resampling.LANCZOS)
        tile = Image.new("RGB", (cell, cell), "white")
        tile.paste(image, ((cell - image.width) // 2, (cell - image.height) // 2))
        canvas.paste(tile, (x, header))
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def persist_visual_diagnostics(
    *,
    image_id: str,
    artifact_root: Path,
    source_rgba: np.ndarray,
    smart_rgba: np.ndarray,
    contour_rgba: np.ndarray,
    smart_bundle: dict[str, Any],
    contour_bundle: dict[str, Any],
    has_typography: bool = False,
) -> dict[str, Any]:
    root = artifact_root / "source_vs_smart_vs_contour" / image_id
    root.mkdir(parents=True, exist_ok=True)
    source = smart_bundle["sourceWhite"]
    smart = smart_bundle["candidateRgba"]
    contour = contour_bundle["candidateRgba"]
    width, height = source.shape[1], source.shape[0]
    source_preview = source
    smart_white = composite_rgba(smart_rgba, "white")
    contour_white = composite_rgba(contour_rgba, "white")
    if smart_white.shape[:2] != (height, width):
        smart_white = cv2.resize(smart_white, (width, height), interpolation=cv2.INTER_AREA)
    if contour_white.shape[:2] != (height, width):
        contour_white = cv2.resize(contour_white, (width, height), interpolation=cv2.INTER_AREA)

    source_path = root / "source.png"
    Image.fromarray(source_rgba, "RGBA").save(source_path)
    output_refs: dict[str, dict[str, str]] = {}
    for engine, rgba in (("smart_reconstruction", smart_rgba), ("contour_preserving", contour_rgba)):
        output_refs[engine] = {}
        for background in ("white", "black", "checkerboard"):
            target = root / f"{engine}_{background}.png"
            Image.fromarray(composite_rgba(rgba, background), "RGB").save(target)
            output_refs[engine][background] = str(target)
            if background != "white":
                alpha_root = artifact_root / "alpha_comparisons" / image_id
                alpha_root.mkdir(parents=True, exist_ok=True)
                Image.fromarray(composite_rgba(rgba, background), "RGB").save(alpha_root / f"{engine}_{background}.png")
    source_alpha_root = artifact_root / "alpha_comparisons" / image_id
    source_alpha_root.mkdir(parents=True, exist_ok=True)
    for background in ("white", "black", "checkerboard"):
        Image.fromarray(composite_rgba(source_rgba, background), "RGB").save(source_alpha_root / f"source_{background}.png")

    smart_delta = smart_bundle["deltaE00"]
    contour_delta = contour_bundle["deltaE00"]
    color_root = artifact_root / "color_error_heatmaps"
    color_root.mkdir(parents=True, exist_ok=True)
    Image.fromarray(_heatmap(smart_delta), "RGB").save(color_root / f"{image_id}_smart.png")
    Image.fromarray(_heatmap(contour_delta), "RGB").save(color_root / f"{image_id}_contour.png")
    for engine, bundle in (("smart", smart_bundle), ("contour", contour_bundle)):
        displacement = bundle.get("boundaryDisplacementPx", np.zeros_like(bundle["deltaE00"]))
        Image.fromarray(_heatmap(np.asarray(displacement), scale=4.0), "RGB").save(color_root / f"{image_id}_{engine}_boundary_displacement.png")
    boundary_root = artifact_root / "boundary_overlays"
    boundary_root.mkdir(parents=True, exist_ok=True)
    Image.fromarray(_source_output_edges(source_preview, smart_white, (35, 180, 92)), "RGB").save(boundary_root / f"{image_id}_smart.png")
    Image.fromarray(_source_output_edges(source_preview, contour_white, (32, 125, 220)), "RGB").save(boundary_root / f"{image_id}_contour.png")
    _contact_sheet(image_id, source_preview, smart_rgba, contour_rgba, smart_delta, contour_delta, artifact_root / "contact_sheets" / f"{image_id}.png")

    roi_rows = []
    roi_dir = artifact_root / "detail_crops" / image_id
    for engine, bundle in (("smart_reconstruction", smart_bundle), ("contour_preserving", contour_bundle)):
        for roi_index, roi in enumerate(select_error_rois(bundle, max_rois=4)):
            x0, y0, x1, y1 = roi["bboxPx"]
            crop_dir = roi_dir / f"{engine}_roi_{roi_index:02d}"
            crop_dir.mkdir(parents=True, exist_ok=True)
            source_crop = source_preview[y0:y1, x0:x1]
            smart_crop = smart_white[y0:y1, x0:x1]
            contour_crop = contour_white[y0:y1, x0:x1]
            delta_crop = bundle["deltaE00"][y0:y1, x0:x1]
            Image.fromarray(source_crop, "RGB").save(crop_dir / "source_crop.png")
            Image.fromarray(smart_crop, "RGB").save(crop_dir / "smart_crop.png")
            Image.fromarray(contour_crop, "RGB").save(crop_dir / "contour_crop.png")
            Image.fromarray(_heatmap(delta_crop), "RGB").save(crop_dir / "difference_heatmap.png")
            smart_edges = _source_output_edges(source_crop, smart_crop, (35, 180, 92))
            contour_edges = _source_output_edges(source_crop, contour_crop, (32, 125, 220))
            Image.fromarray(smart_edges, "RGB").save(crop_dir / "smart_boundary_overlay.png")
            Image.fromarray(contour_edges, "RGB").save(crop_dir / "contour_boundary_overlay.png")
            row = {**roi, "engine": engine, "sourceCrop": str(crop_dir / "source_crop.png"),
                   "smartRenderCrop": str(crop_dir / "smart_crop.png"),
                   "contourRenderCrop": str(crop_dir / "contour_crop.png"),
                   "differenceHeatmap": str(crop_dir / "difference_heatmap.png"),
                   "smartBoundaryOverlay": str(crop_dir / "smart_boundary_overlay.png"),
                   "contourBoundaryOverlay": str(crop_dir / "contour_boundary_overlay.png"),
                   "metrics": {
                       "meanDeltaE00": float(delta_crop.mean()) if delta_crop.size else None,
                       "p95DeltaE00": float(np.quantile(delta_crop, 0.95)) if delta_crop.size else None,
                       "edgeMismatchFraction": float(bundle["edgeMismatch"][y0:y1, x0:x1].mean()),
                       "meanBoundaryDisplacementPx": float(bundle.get("boundaryDisplacementPx", np.zeros_like(bundle["deltaE00"]))[y0:y1, x0:x1].mean()),
                       "p95BoundaryDisplacementPx": float(np.quantile(bundle.get("boundaryDisplacementPx", np.zeros_like(bundle["deltaE00"]))[y0:y1, x0:x1], 0.95)),
                       "alphaMismatchMean": float(bundle["alphaAbsoluteDifference"][y0:y1, x0:x1].mean()),
                       "sourceGradientMean": float(bundle["sourceGradientMagnitude"][y0:y1, x0:x1].mean()),
                       "localSsimMean": float(bundle.get("ssimMap", np.ones_like(bundle["deltaE00"]))[y0:y1, x0:x1].mean()),
                   }}
            roi_rows.append(row)
    write_json(roi_dir / "roi_manifest.json", {"imageId": image_id, "reviewStatus": "pending_human_review", "rois": roi_rows})
    typography_dir = artifact_root / "typography_crops" / image_id
    typography_dir.mkdir(parents=True, exist_ok=True)
    write_json(typography_dir / "review_manifest.json", {
        "imageId": image_id,
        "sourceHasTypographyByManifest": bool(has_typography),
        "status": "pending_annotation" if has_typography else "not_applicable_by_manifest",
        "ocrOrGlyphGroundTruthAvailable": False,
        "reason": "No source transcription or independently validated glyph mask is available; no text ROI is inferred from engine output.",
        "generalErrorRois": str(roi_dir / "roi_manifest.json"),
    })
    return {
        "contactSheet": str(artifact_root / "contact_sheets" / f"{image_id}.png"),
        "sourceImage": str(source_path),
        "renderedComparisons": output_refs,
        "smartColorErrorHeatmap": str(color_root / f"{image_id}_smart.png"),
        "contourColorErrorHeatmap": str(color_root / f"{image_id}_contour.png"),
        "smartBoundaryOverlay": str(boundary_root / f"{image_id}_smart.png"),
        "contourBoundaryOverlay": str(boundary_root / f"{image_id}_contour.png"),
        "roiManifest": str(roi_dir / "roi_manifest.json"),
        "typographyReviewManifest": str(typography_dir / "review_manifest.json"),
        "rois": roi_rows,
        "reviewStatus": "pending_human_review",
    }


def build_category_contact_sheets(items: list[dict[str, Any]], artifact_root: Path) -> list[str]:
    outputs: list[str] = []
    directory = artifact_root / "contact_sheets"
    directory.mkdir(parents=True, exist_ok=True)
    for category in sorted({category for item in items for category in item.get("categories", [])}):
        category_items = [item for item in items if category in item.get("categories", []) and item.get("contactSheet")]
        if not category_items:
            continue
        images = []
        for item in category_items:
            path = Path(item["contactSheet"])
            if path.is_file():
                images.append((item["imageId"], Image.open(path).convert("RGB")))
        if not images:
            continue
        width = max(image.width for _, image in images)
        height = max(image.height for _, image in images)
        canvas = Image.new("RGB", (width, height * len(images)), "#e9ebf0")
        for index, (_, image) in enumerate(images):
            canvas.paste(image, (0, index * height))
        path = directory / f"category_{category}.png"
        canvas.save(path)
        outputs.append(str(path))
    return outputs
