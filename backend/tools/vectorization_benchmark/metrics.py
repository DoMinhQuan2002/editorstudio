from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from PIL import Image
from skimage.color import deltaE_ciede2000, rgb2lab
from skimage.metrics import structural_similarity


def _resize_rgb(array: np.ndarray, width: int, height: int) -> np.ndarray:
    interpolation = cv2.INTER_AREA if width < array.shape[1] or height < array.shape[0] else cv2.INTER_LANCZOS4
    return cv2.resize(array, (width, height), interpolation=interpolation)


def resize_source_rgba(image: Image.Image, width: int, height: int) -> np.ndarray:
    rgba = image.convert("RGBA")
    if rgba.size != (width, height):
        rgba = rgba.resize((width, height), Image.Resampling.LANCZOS)
    return np.asarray(rgba, dtype=np.uint8)


def composite_rgba(rgba: np.ndarray, background: str) -> np.ndarray:
    height, width = rgba.shape[:2]
    if background == "white":
        color = np.full((height, width, 3), 255, dtype=np.uint8)
    elif background == "black":
        color = np.zeros((height, width, 3), dtype=np.uint8)
    elif background == "checkerboard":
        yy, xx = np.indices((height, width))
        gray = np.where(((xx // 24 + yy // 24) % 2) == 0, 226, 186).astype(np.uint8)
        color = np.repeat(gray[..., None], 3, axis=2)
    else:
        raise ValueError(f"Unsupported background: {background}")
    alpha = rgba[..., 3:4].astype(np.float32) / 255.0
    return np.rint(rgba[..., :3].astype(np.float32) * alpha + color.astype(np.float32) * (1.0 - alpha)).clip(0, 255).astype(np.uint8)


def estimate_foreground_reference(source_rgba: np.ndarray, analytic_alpha: np.ndarray | None = None) -> tuple[np.ndarray | None, dict[str, Any]]:
    if analytic_alpha is not None:
        mask = np.asarray(analytic_alpha) > 16
        return mask, {"kind": "analytic_alpha_sidecar", "confidence": 1.0, "groundTruth": True}
    alpha = source_rgba[..., 3]
    if np.min(alpha) < 255:
        return alpha > 16, {"kind": "source_alpha_channel", "confidence": 1.0, "groundTruth": True}

    rgb = source_rgba[..., :3]
    border = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]), axis=0)
    border_lab = rgb2lab(border.reshape(1, -1, 3).astype(np.float32) / 255.0).reshape(-1, 3)
    center = np.median(border_lab, axis=0)
    distance = np.linalg.norm(border_lab - center[None, :], axis=1)
    border_p90 = float(np.quantile(distance, 0.90))
    if border_p90 > 9.0:
        return None, {"kind": "unavailable_complex_opaque_boundary", "confidence": 0.0, "groundTruth": False, "borderLabP90": border_p90}
    lab = rgb2lab(rgb.astype(np.float32) / 255.0)
    near_background = (np.linalg.norm(lab - center[None, None, :], axis=2) <= max(12.0, border_p90 + 5.0)).astype(np.uint8)
    count, labels, _, _ = cv2.connectedComponentsWithStats(near_background, connectivity=8)
    border_labels = np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
    border_labels = border_labels[(border_labels > 0) & (border_labels < count)]
    background = np.isin(labels, border_labels)
    foreground = ~background
    occupancy = float(foreground.mean())
    confidence = max(0.35, min(0.75, 1.0 - border_p90 / 25.0))
    if occupancy <= 0.002 or occupancy >= 0.998:
        return None, {"kind": "ambiguous_opaque_border_estimate", "confidence": 0.0, "groundTruth": False, "foregroundOccupancy": occupancy, "borderLabP90": border_p90}
    return foreground, {
        "kind": "perimeter_connected_flat_background_proxy",
        "confidence": confidence,
        "groundTruth": False,
        "foregroundOccupancy": occupancy,
        "borderLabP90": border_p90,
        "thresholdLabDelta": max(12.0, border_p90 + 5.0),
        "warning": "Estimated silhouette for opaque input; raster-reference proxy, not a manually validated mask.",
    }


def _edge_map(mask: np.ndarray) -> np.ndarray:
    mask = mask.astype(bool)
    if not mask.any():
        return np.zeros(mask.shape, dtype=bool)
    eroded = cv2.erode(mask.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
    return mask & ~eroded


def silhouette_metrics(reference_mask: np.ndarray, candidate_mask: np.ndarray) -> dict[str, Any]:
    ref = reference_mask.astype(bool)
    cand = candidate_mask.astype(bool)
    if ref.shape != cand.shape:
        raise ValueError("Silhouette masks must have identical dimensions")
    intersection = int(np.count_nonzero(ref & cand))
    union = int(np.count_nonzero(ref | cand))
    ref_edge, cand_edge = _edge_map(ref), _edge_map(cand)
    distance_to_candidate = cv2.distanceTransform((~cand_edge).astype(np.uint8), cv2.DIST_L2, 3)
    distance_to_reference = cv2.distanceTransform((~ref_edge).astype(np.uint8), cv2.DIST_L2, 3)
    d1 = distance_to_candidate[ref_edge]
    d2 = distance_to_reference[cand_edge]
    distances = np.concatenate([d1, d2]) if d1.size and d2.size else np.asarray([], np.float32)
    return {
        "foregroundIoU": intersection / max(union, 1),
        "intersectionPixels": intersection,
        "referenceForegroundPixels": int(ref.sum()),
        "candidateForegroundPixels": int(cand.sum()),
        "meanSymmetricBoundaryDistancePx": float(distances.mean()) if distances.size else 0.0,
        "p95SymmetricBoundaryDistancePx": float(np.quantile(distances, 0.95)) if distances.size else 0.0,
        "approxHausdorffBoundaryDistancePx": float(distances.max()) if distances.size else 0.0,
    }


def _lab(rgb: np.ndarray) -> np.ndarray:
    return rgb2lab(rgb.astype(np.float32) / 255.0)


def _boundary_f1(reference_edge: np.ndarray, candidate_edge: np.ndarray, *, tolerance_px: float) -> dict[str, Any]:
    reference = reference_edge.astype(bool)
    candidate = candidate_edge.astype(bool)
    dist_ref = cv2.distanceTransform((~reference).astype(np.uint8), cv2.DIST_L2, 3)
    dist_candidate = cv2.distanceTransform((~candidate).astype(np.uint8), cv2.DIST_L2, 3)
    precision = float(np.mean(dist_ref[candidate] <= tolerance_px)) if candidate.any() else (1.0 if not reference.any() else 0.0)
    recall = float(np.mean(dist_candidate[reference] <= tolerance_px)) if reference.any() else (1.0 if not candidate.any() else 0.0)
    f1 = 2.0 * precision * recall / max(precision + recall, 1e-12)
    return {
        "precisionWithinTolerance": precision,
        "recallWithinTolerance": recall,
        "f1WithinTolerance": f1,
        "tolerancePx": tolerance_px,
        "referenceBoundaryPixels": int(reference.sum()),
        "candidateBoundaryPixels": int(candidate.sum()),
    }


def _label_boundary(labels: np.ndarray, content_mask: np.ndarray) -> np.ndarray:
    labels = labels.astype(np.int32)
    content = content_mask.astype(bool)
    edge = np.zeros(labels.shape, dtype=bool)
    edge[:, 1:] |= (labels[:, 1:] != labels[:, :-1]) & content[:, 1:] & content[:, :-1]
    edge[1:, :] |= (labels[1:, :] != labels[:-1, :]) & content[1:, :] & content[:-1, :]
    return edge


def _semantic_metrics(
    source_rgb: np.ndarray,
    candidate_rgb: np.ndarray,
    candidate_alpha: np.ndarray,
    source_mask: np.ndarray,
    label_map: np.ndarray,
) -> dict[str, Any]:
    height, width = source_mask.shape
    labels = cv2.resize(label_map.astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST)
    source_lab, candidate_lab = _lab(source_rgb), _lab(candidate_rgb)
    palette: dict[int, np.ndarray] = {}
    source_alpha = source_mask.astype(bool)
    for label in np.unique(labels):
        if label == 0:
            continue
        selected = (labels == label) & source_alpha
        if selected.any():
            palette[int(label)] = np.median(source_lab[selected], axis=0)
    predicted = np.zeros((height, width), dtype=np.uint8)
    visible = candidate_alpha > 16
    if palette and visible.any():
        label_ids = list(palette)
        swatches = np.stack([palette[label] for label in label_ids])
        pixels = candidate_lab[visible]
        distances = np.linalg.norm(pixels[:, None, :] - swatches[None, :, :], axis=2)
        nearest = np.argmin(distances, axis=1)
        predicted[visible] = np.asarray(label_ids, dtype=np.uint8)[nearest]
    features = []
    for label in sorted(palette):
        truth = (labels == label) & source_alpha
        guess = predicted == label
        intersection = int(np.count_nonzero(truth & guess))
        union = int(np.count_nonzero(truth | guess))
        truth_count = int(truth.sum())
        guess_count = int(guess.sum())
        features.append({
            "semanticLabel": label,
            "referencePixels": truth_count,
            "candidatePixels": guess_count,
            "precision": intersection / max(guess_count, 1),
            "recall": intersection / max(truth_count, 1),
            "iou": intersection / max(union, 1),
        })
    eroded_content = cv2.erode(source_mask.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=2) > 0
    reference_edges = _label_boundary(labels, eroded_content)
    candidate_edges = _label_boundary(predicted, eroded_content & visible)
    return {
        "referenceStatus": "analytic_semantic_label_sidecar",
        "featureCount": len(features),
        "features": features,
        "macroFeatureIoU": float(np.mean([row["iou"] for row in features])) if features else None,
        "macroFeatureRecall": float(np.mean([row["recall"] for row in features])) if features else None,
        "internalBoundary": _boundary_f1(reference_edges, candidate_edges, tolerance_px=2.0),
        "candidateSemanticAssignment": "Nearest source-label median CIELAB swatch over visible SVG pixels; joint spatial/color fidelity indicator, not color-blind shape-only ground truth.",
    }


def _sobel_magnitude(lab: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    channel = lab[..., 0].astype(np.float32)
    gx = cv2.Sobel(channel, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(channel, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    return gx, gy, mag


def _gradient_metrics(source_rgb: np.ndarray, candidate_rgb: np.ndarray, foreground: np.ndarray) -> dict[str, Any]:
    source_lab, candidate_lab = _lab(source_rgb), _lab(candidate_rgb)
    sx, sy, smag = _sobel_magnitude(source_lab)
    cx, cy, cmag = _sobel_magnitude(candidate_lab)
    values = smag[foreground]
    if values.size < 32:
        return {"status": "insufficient_source_gradient_pixels", "directionCosineMean": None, "magnitudeRatioMean": None, "falseHardBoundaryFraction": None, "bandingProxy": None}
    low = float(np.quantile(values, 0.45))
    high = float(np.quantile(values, 0.92))
    smooth_gradient = foreground & (smag >= max(low, 0.15)) & (smag <= max(high, low + 0.1))
    denom = np.sqrt(sx * sx + sy * sy) * np.sqrt(cx * cx + cy * cy)
    cosine = np.divide(sx * cx + sy * cy, denom, out=np.zeros_like(smag), where=denom > 1e-4)
    ratio = np.divide(cmag, smag, out=np.zeros_like(smag), where=smag > 1e-4)
    candidate_high_edges = cmag > max(8.0, float(np.quantile(cmag[foreground], 0.92)))
    false_hard = smooth_gradient & candidate_high_edges
    # Estimate banding as excess candidate edge peaks in regions with a smooth source gradient.
    candidate_peaks = cv2.dilate(cmag, np.ones((3, 3), np.uint8)) >= cmag - 1e-5
    band_candidates = candidate_peaks & smooth_gradient & (cmag > 4.0)
    smooth_count = max(int(smooth_gradient.sum()), 1)
    return {
        "status": "raster_gradient_proxy",
        "directionCosineMean": float(cosine[smooth_gradient].mean()) if smooth_gradient.any() else None,
        "gradientMagnitudeRatioMean": float(np.clip(ratio[smooth_gradient], 0, 8).mean()) if smooth_gradient.any() else None,
        "falseHardBoundaryFractionInSourceSmoothGradient": float(false_hard.sum() / smooth_count),
        "bandingPeakDensityProxy": float(band_candidates.sum() / smooth_count),
        "sourceSmoothGradientPixels": int(smooth_gradient.sum()),
        "sourceGradientQuantileBounds": [low, high],
        "warning": "Raster-reference indicators; not a ground-truth analytic gradient fit unless a parameterized synthetic reference is supplied.",
    }


def _count_holes(mask: np.ndarray) -> int:
    background = (~mask.astype(bool)).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(background, connectivity=8)
    border_ids = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])).tolist())
    return sum(1 for label in range(1, count) if label not in border_ids and stats[label, cv2.CC_STAT_AREA] > 0)


def evaluate_render(
    source_full_rgba: np.ndarray,
    candidate_full_rgba: np.ndarray,
    *,
    width: int,
    height: int,
    reference_mask_kind: dict[str, Any],
    analytic_alpha: np.ndarray | None = None,
    semantic_label_map: np.ndarray | None = None,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    source_rgba = _resize_rgb(source_full_rgba, width, height)
    candidate_rgba = candidate_full_rgba
    if candidate_rgba.shape[:2] != (height, width):
        candidate_rgba = cv2.resize(candidate_rgba, (width, height), interpolation=cv2.INTER_AREA)
    source_white = composite_rgba(source_rgba, "white")
    candidate_white = composite_rgba(candidate_rgba, "white")
    source_lab, candidate_lab = _lab(source_white), _lab(candidate_white)
    delta = deltaE_ciede2000(source_lab, candidate_lab).astype(np.float32)

    analytic_alpha_resized = None
    if analytic_alpha is not None:
        analytic_alpha_resized = cv2.resize(analytic_alpha.astype(np.uint8), (width, height), interpolation=cv2.INTER_AREA).astype(np.uint8)
    elif int(source_rgba[..., 3].min()) < 255:
        analytic_alpha_resized = source_rgba[..., 3]
    mask_source, mask_info = estimate_foreground_reference(source_rgba, analytic_alpha_resized)
    geometry_reference_available = mask_source is not None
    if mask_source is None:
        # Full-canvas color/reference comparisons remain useful for opaque photos,
        # but the canvas must never be mislabeled as a foreground silhouette GT.
        mask_source = np.ones((height, width), dtype=bool)
        mask_info = {**mask_info, "metricMaskFallback": "full_canvas_for_raster_comparison_only", "confidence": 0.0}

    edge = _edge_map(mask_source)
    dilated = cv2.dilate(mask_source.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    eroded = cv2.erode(mask_source.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    edge_band = dilated & ~eroded
    interior = eroded if eroded.any() else mask_source
    source_luminance = cv2.cvtColor(source_white, cv2.COLOR_RGB2GRAY).astype(np.float32)
    source_edge_rgb = cv2.Canny(source_luminance.astype(np.uint8), 40, 130) > 0
    transition = mask_source & ~edge_band & (np.linalg.norm(cv2.Sobel(source_lab, cv2.CV_32F, 1, 0, 1), axis=2) > 0)
    if int(transition.sum()) < 16:
        transition = interior

    ssim_score, ssim_map = structural_similarity(source_white, candidate_white, channel_axis=2, data_range=255, full=True, gaussian_weights=True)
    if ssim_map.ndim == 3:
        ssim_map = ssim_map.mean(axis=2)
    saturation_source = cv2.cvtColor(source_white, cv2.COLOR_RGB2HSV)[..., 1].astype(np.float32)
    saturation_candidate = cv2.cvtColor(candidate_white, cv2.COLOR_RGB2HSV)[..., 1].astype(np.float32)

    def color_stats(selected: np.ndarray) -> dict[str, Any]:
        values = delta[selected]
        return {
            "pixelCount": int(selected.sum()),
            "meanDeltaE00": float(values.mean()) if values.size else None,
            "p95DeltaE00": float(np.quantile(values, 0.95)) if values.size else None,
            "maskedSsim": float(ssim_map[selected].mean()) if selected.any() else None,
            "meanAbsoluteSaturationDifference": float(np.abs(saturation_source[selected] - saturation_candidate[selected]).mean()) if selected.any() else None,
        }

    candidate_mask = candidate_rgba[..., 3] > 16
    geometry = silhouette_metrics(mask_source, candidate_mask) if geometry_reference_available else {
        "foregroundIoU": None,
        "intersectionPixels": None,
        "referenceForegroundPixels": None,
        "candidateForegroundPixels": int(candidate_mask.sum()),
        "meanSymmetricBoundaryDistancePx": None,
        "p95SymmetricBoundaryDistancePx": None,
        "approxHausdorffBoundaryDistancePx": None,
        "boundaryAlignmentOfRasterEdges": {"status": "not_measurable_without_foreground_reference"},
        "sourceHoleCount": None,
        "candidateHoleCount": _count_holes(candidate_mask),
        "holeCountDifference": None,
        "status": "unavailable_no_foreground_reference",
    }
    alpha_metrics: dict[str, Any]
    if analytic_alpha_resized is None:
        alpha_metrics = {"status": "not_measurable_source_is_opaque_or_no_alpha_reference", "alphaIoU": None, "meanAbsoluteAlphaError": None, "boundaryDistancePx": None}
    else:
        ref_alpha_mask = analytic_alpha_resized > 16
        output_alpha = candidate_rgba[..., 3].astype(np.float32)
        alpha_metrics = {
            "status": "analytic_alpha_reference" if reference_mask_kind.get("groundTruth") else "source_alpha_reference",
            "alphaIoU": silhouette_metrics(ref_alpha_mask, candidate_mask)["foregroundIoU"],
            "meanAbsoluteAlphaError": float(np.abs(analytic_alpha_resized.astype(np.float32) - output_alpha).mean()),
            "referenceAlphaCoverage": float((analytic_alpha_resized > 16).mean()),
            "candidateAlphaCoverage": float(candidate_mask.mean()),
            "boundaryDistancePx": silhouette_metrics(ref_alpha_mask, candidate_mask)["meanSymmetricBoundaryDistancePx"],
        }

    edge_domain = cv2.dilate(mask_source.astype(np.uint8), np.ones((11, 11), np.uint8)) > 0
    source_edge = source_edge_rgb & edge_domain
    candidate_edge = (cv2.Canny(cv2.cvtColor(candidate_white, cv2.COLOR_RGB2GRAY), 40, 130) > 0) & edge_domain
    edge_fidelity = _boundary_f1(source_edge, candidate_edge, tolerance_px=2.0)
    distance_to_source_edge = cv2.distanceTransform((~source_edge).astype(np.uint8), cv2.DIST_L2, 3)
    distance_to_candidate_edge = cv2.distanceTransform((~candidate_edge).astype(np.uint8), cv2.DIST_L2, 3)
    boundary_displacement = np.zeros((height, width), dtype=np.float32)
    boundary_displacement[source_edge] = distance_to_candidate_edge[source_edge]
    boundary_displacement[candidate_edge] = np.maximum(
        boundary_displacement[candidate_edge], distance_to_source_edge[candidate_edge]
    )
    semantic = _semantic_metrics(source_white, candidate_white, candidate_rgba[..., 3], mask_source, semantic_label_map) if semantic_label_map is not None else {
        "referenceStatus": "no_analytic_semantic_labels",
        "featureCount": None,
        "features": [],
        "macroFeatureIoU": None,
        "macroFeatureRecall": None,
        "internalBoundary": {"status": "not_measurable_without_ground_truth_label_map"},
    }
    gradients = _gradient_metrics(source_white, candidate_white, mask_source)
    # Low-resolution RGB is not an OCR reference. OCR text recognition and glyph-mask comparisons remain separate/unavailable unless annotations exist.
    metrics = {
        "metricCanvas": [width, height],
        "referenceMask": mask_info,
        "geometry": {
            **geometry,
            **({
                "boundaryAlignmentOfRasterEdges": edge_fidelity,
                "sourceHoleCount": _count_holes(mask_source),
                "candidateHoleCount": _count_holes(candidate_mask),
                "holeCountDifference": _count_holes(candidate_mask) - _count_holes(mask_source),
                "status": "analytic_ground_truth" if reference_mask_kind.get("groundTruth") else "raster_reference_proxy",
            } if geometry_reference_available else {}),
        },
        "color": {
            "referenceComposite": "white",
            "foregroundOrContent": color_stats(mask_source),
            "regionInterior": color_stats(interior),
            "edgeBand": color_stats(edge_band & dilated),
            "colorTransitionRegion": color_stats(transition),
            "edgeColorContaminationDeltaE00": (color_stats(edge_band & dilated)["meanDeltaE00"] - color_stats(interior)["meanDeltaE00"]) if color_stats(edge_band & dilated)["meanDeltaE00"] is not None and color_stats(interior)["meanDeltaE00"] is not None else None,
        },
        "gradient": gradients,
        "details": semantic,
        "transparency": alpha_metrics,
        "typography": {
            "status": "visual raster crop metrics available; OCR/glyph truth unavailable without source transcription or glyph mask",
            "fullContentMaskedSsim": color_stats(mask_source)["maskedSsim"],
        },
        "errorMap": {
            "deltaE00": delta,
            "edgeMismatch": np.logical_xor(source_edge, candidate_edge),
            "boundaryDisplacementPx": boundary_displacement,
            "alphaAbsoluteDifference": np.abs(source_rgba[..., 3].astype(np.int16) - candidate_rgba[..., 3].astype(np.int16)).astype(np.uint8),
            "sourceGradientMagnitude": _sobel_magnitude(source_lab)[2],
            "foregroundMask": mask_source,
            "ssimMap": ssim_map.astype(np.float32),
        },
    }
    return metrics, {
        "sourceRgba": source_rgba,
        "sourceWhite": source_white,
        "candidateRgba": candidate_rgba,
        "candidateWhite": candidate_white,
        "deltaE00": delta,
        "sourceForegroundMask": mask_source,
        "candidateForegroundMask": candidate_mask,
        "edgeMismatch": np.logical_xor(source_edge, candidate_edge),
        "boundaryDisplacementPx": boundary_displacement,
        "alphaAbsoluteDifference": metrics["errorMap"]["alphaAbsoluteDifference"],
        "sourceGradientMagnitude": metrics["errorMap"]["sourceGradientMagnitude"],
        "ssimMap": metrics["errorMap"]["ssimMap"],
    }
