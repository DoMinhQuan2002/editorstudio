from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any
import xml.etree.ElementTree as ET

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage.color import deltaE_ciede2000, rgb2lab
from skimage.metrics import structural_similarity

BACKEND = Path(__file__).resolve().parents[2]
REPOSITORY = BACKEND.parent
ARTIFACT_ROOT = BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_1"
SOURCE_MANIFEST = BACKEND / "artifacts" / "contour_preserving" / "task_08a" / "benchmark_manifest.json"
FIXTURE_IDS = (
    "synthetic-circle",  # flat-color analytic geometry
    "synthetic-linear_gradient",
    "synthetic-radial_gradient",
    "synthetic-multiregion_illustration",
    "active-fox-native-jpeg",
)
ENGINE_IDS = ("smart_reconstruction", "contour_preserving")
BOUNDARY_TOLERANCE_PX = 2.0
GRADIENT_FALSE_EDGE_DELTA_E_PER_PX = 3.0
APPEARANCE_MEAN_DELTA_E_THRESHOLD = 3.0
APPEARANCE_P95_DELTA_E_THRESHOLD = 5.0
SVG_NS = "http://www.w3.org/2000/svg"
_PATH_COMMAND = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_rgba(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"), dtype=np.uint8)


def boundary_map(labels: np.ndarray, *, content: np.ndarray | None = None) -> np.ndarray:
    """Mark pixel interfaces; labels may be a binary mask or semantic label map."""
    value = np.asarray(labels)
    if value.ndim != 2:
        raise ValueError("Boundary labels must be a 2D array")
    edge = np.zeros(value.shape, dtype=bool)
    edge[:, 1:] |= value[:, 1:] != value[:, :-1]
    edge[1:, :] |= value[1:, :] != value[:-1, :]
    if content is not None:
        valid = np.asarray(content, dtype=bool)
        if valid.shape != value.shape:
            raise ValueError("Boundary content mask must match labels")
        pair_valid = np.zeros(value.shape, dtype=bool)
        pair_valid[:, 1:] |= valid[:, 1:] & valid[:, :-1]
        pair_valid[1:, :] |= valid[1:, :] & valid[:-1, :]
        edge &= pair_valid
    return edge


def matched_boundary_metrics(truth: np.ndarray, candidate: np.ndarray,
                             tolerance_px: float = BOUNDARY_TOLERANCE_PX,
                             ground_truth_class: str = "ANALYTIC_GROUND_TRUTH") -> dict[str, Any]:
    """Symmetric boundary precision/recall and distances at one fixed tolerance."""
    a, b = np.asarray(truth, dtype=bool), np.asarray(candidate, dtype=bool)
    if a.shape != b.shape:
        raise ValueError(f"Boundary maps must share coordinates: {a.shape} vs {b.shape}")
    da = cv2.distanceTransform((~a).astype(np.uint8), cv2.DIST_L2, 3)
    db = cv2.distanceTransform((~b).astype(np.uint8), cv2.DIST_L2, 3)
    d_a_to_b, d_b_to_a = db[a], da[b]
    precision = float(np.mean(da[b] <= tolerance_px)) if b.any() else (1.0 if not a.any() else 0.0)
    recall = float(np.mean(db[a] <= tolerance_px)) if a.any() else (1.0 if not b.any() else 0.0)
    distances = np.concatenate([d_a_to_b, d_b_to_a])
    return {
        "tolerancePx": float(tolerance_px),
        "precisionWithinTolerance": precision,
        "recallWithinTolerance": recall,
        "f1WithinTolerance": 2 * precision * recall / max(precision + recall, 1e-12),
        "truthBoundaryPixels": int(a.sum()),
        "candidateBoundaryPixels": int(b.sum()),
        "missingBoundaryPixels": int((a & (db > tolerance_px)).sum()),
        "falseBoundaryPixels": int((b & (da > tolerance_px)).sum()),
        "meanSymmetricDistancePx": float(distances.mean()) if distances.size else 0.0,
        "p95SymmetricDistancePx": float(np.quantile(distances, .95)) if distances.size else 0.0,
        "groundTruthClass": ground_truth_class if a.any() else f"empty_{ground_truth_class.lower()}",
    }


def gradient_metrics(source_rgb: np.ndarray, candidate_rgb: np.ndarray,
                     roi_mask: np.ndarray) -> dict[str, Any]:
    """Measure excess hard edges in a known continuous-gradient ROI."""
    source = np.asarray(source_rgb, dtype=np.uint8)
    candidate = np.asarray(candidate_rgb, dtype=np.uint8)
    roi = np.asarray(roi_mask, dtype=bool)
    if source.shape != candidate.shape or roi.shape != source.shape[:2]:
        raise ValueError("Source, candidate, and ROI must use identical native coordinates")
    source_lab = rgb2lab(source.astype(np.float32) / 255.0)
    candidate_lab = rgb2lab(candidate.astype(np.float32) / 255.0)
    source_delta = _lab_neighbor_delta(source_lab)
    candidate_delta = _lab_neighbor_delta(candidate_lab)
    # Fixed threshold across both engines; sub-pixel anti-aliasing is excluded by a 1px ROI erosion.
    interior = cv2.erode(roi.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
    if not interior.any():
        interior = roi
    false_edges = interior & (candidate_delta >= GRADIENT_FALSE_EDGE_DELTA_E_PER_PX) & (
        candidate_delta > source_delta * 2.5 + 0.75)
    source_gradient = source_delta[interior]
    candidate_gradient = candidate_delta[interior]
    ssim_value = float(structural_similarity(source, candidate, channel_axis=2, data_range=255))
    de = deltaE_ciede2000(source_lab, candidate_lab)
    return {
        "roiPixels": int(interior.sum()),
        "falseHardEdgeThresholdDeltaEPerPx": GRADIENT_FALSE_EDGE_DELTA_E_PER_PX,
        "falseHardEdgePixels": int(false_edges.sum()),
        "falseHardEdgeFraction": float(false_edges.sum() / max(int(interior.sum()), 1)),
        "falseHardEdgeLengthPxApprox": int(false_edges.sum()),
        "sourceNeighborDeltaEPerPxP95": float(np.quantile(source_gradient, .95)) if source_gradient.size else None,
        "renderNeighborDeltaEPerPxP95": float(np.quantile(candidate_gradient, .95)) if candidate_gradient.size else None,
        "meanDeltaE00": float(de[interior].mean()) if interior.any() else None,
        "p95DeltaE00": float(np.quantile(de[interior], .95)) if interior.any() else None,
        "ssimWholeCanvas": ssim_value,
        "falseHardBoundaryInterpretation": "render-only excess color edge response within analytically continuous gradient ROI; diagnostic proxy, not semantic edge annotation",
    }


def _lab_neighbor_delta(lab: np.ndarray) -> np.ndarray:
    h_delta = np.linalg.norm(lab[:, 1:] - lab[:, :-1], axis=2)
    v_delta = np.linalg.norm(lab[1:] - lab[:-1], axis=2)
    out = np.zeros(lab.shape[:2], dtype=np.float32)
    out[:, 1:] = np.maximum(out[:, 1:], h_delta)
    out[:, :-1] = np.maximum(out[:, :-1], h_delta)
    out[1:, :] = np.maximum(out[1:, :], v_delta)
    out[:-1, :] = np.maximum(out[:-1, :], v_delta)
    return out


def ground_truth_label(image_id: str) -> dict[str, Any]:
    if image_id.startswith("synthetic-"):
        return {"class": "ANALYTIC_FIXTURE", "isGroundTruth": True,
                "basis": "Task 07.2 generated source plus Task 08A analytic alpha/semantic label sidecars"}
    if image_id == "active-fox-native-jpeg":
        return {"class": "REAL_IMAGE_PROXY", "isGroundTruth": False,
                "basis": "native user JPEG and existing Task 07/08A ROI annotations",
                "humanReview": "NEEDS_HUMAN_REVIEW"}
    return {"class": "UNKNOWN", "isGroundTruth": False, "humanReview": "NEEDS_HUMAN_REVIEW"}


def assert_native_alignment(source: np.ndarray, render: np.ndarray) -> None:
    if source.shape[:2] != render.shape[:2]:
        raise ValueError(f"Coordinate alignment failed: source={source.shape[:2]}, render={render.shape[:2]}")


def inspect_svg(path: Path, expected_size: tuple[int, int]) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    if root.tag != f"{{{SVG_NS}}}svg":
        raise ValueError(f"Invalid SVG root namespace in {path}")
    vb = [float(v) for v in re.split(r"[\s,]+", root.attrib.get("viewBox", "").strip())]
    if len(vb) != 4 or vb[2] <= 0 or vb[3] <= 0:
        raise ValueError(f"Invalid SVG viewBox in {path}")
    elements = [node.tag.rsplit("}", 1)[-1].casefold() for node in root.iter()]
    images = elements.count("image")
    embedded = b"data:image/" in path.read_bytes().lower()
    return {
        "xmlValid": True,
        "viewBox": vb,
        "declaredSize": [root.attrib.get("width"), root.attrib.get("height")],
        "nativeViewBoxMatchesSource": vb == [0.0, 0.0, float(expected_size[0]), float(expected_size[1])],
        "pathCount": elements.count("path"),
        "gradientCount": elements.count("lineargradient") + elements.count("radialgradient"),
        "imageElementCount": images,
        "embeddedRasterDataUri": embedded,
        "noEmbeddedRaster": images == 0 and not embedded,
        "renderDimensions": [expected_size[0], expected_size[1]],
        "status": "PASS" if images == 0 and not embedded and vb == [0.0, 0.0, float(expected_size[0]), float(expected_size[1])] else "FAIL",
    }


def _fixture_roi(image_id: str, source: np.ndarray, semantic: np.ndarray | None) -> dict[str, Any]:
    h, w = source.shape[:2]
    if image_id in {"synthetic-linear_gradient", "synthetic-radial_gradient"}:
        # Existing generated gradient occupies the analytic circle centered at (256,256), radius 136.
        yy, xx = np.indices((h, w))
        mask = ((xx - w / 2) ** 2 + (yy - h / 2) ** 2) <= (min(w, h) * (136 / 512)) ** 2
        mask = cv2.erode(mask.astype(np.uint8), np.ones((17, 17), np.uint8), iterations=1) > 0
        return {"kind": "analytic_soft_gradient_roi", "mask": mask,
                "annotation": "circle interior inferred from Task 07.2 fixture generator geometry; gradient itself is continuous"}
    if image_id == "active-fox-native-jpeg":
        annotations = json.loads((BACKEND / "tests/fixtures/active_fox_phase_c_annotations.json").read_text(encoding="utf-8"))
        x0, y0, x1, y1 = annotations["tail_body_gradient_roi_xyxy"]
        mask = np.zeros((h, w), bool)
        mask[y0:y1, x0:x1] = True
        return {"kind": "annotated_real_image_proxy_roi", "mask": mask,
                "annotation": "Task 07/08A tail_body_gradient_roi_xyxy; proxy; NEEDS_HUMAN_REVIEW"}
    return {"kind": "none", "mask": np.zeros((h, w), bool), "annotation": "no soft gradient ROI"}


def _source_truth_edges(image_id: str, source: np.ndarray, semantic: np.ndarray | None,
                        alpha_truth: np.ndarray | None) -> tuple[np.ndarray, np.ndarray | None, dict[str, Any]]:
    if alpha_truth is not None:
        content = alpha_truth
        silhouette_source = "Task 08A analytic alpha sidecar"
    elif image_id.startswith("synthetic-"):
        yy, xx = np.indices(source.shape[:2])
        content = (xx - source.shape[1] / 2) ** 2 + (yy - source.shape[0] / 2) ** 2 <= (source.shape[1] * (136 / 512)) ** 2
        silhouette_source = "analytic fixture geometry"
    elif source[..., 3].min() < 255:
        content = source[..., 3] > 16
        silhouette_source = "source alpha channel"
    else:
        from tools.vectorization_benchmark.metrics import estimate_foreground_reference
        content, _proxy = estimate_foreground_reference(source, analytic_alpha=None)
        if content is None:
            content = np.zeros(source.shape[:2], dtype=bool)
            silhouette_source = "unavailable_opaque_background_proxy"
        else:
            silhouette_source = "perimeter-connected flat-background proxy"
    content = np.asarray(content, dtype=bool)
    silhouette = boundary_map(content)
    semantic_edge = None
    if semantic is not None and np.unique(semantic).size > 2:
        semantic_edge = boundary_map(semantic, content=content)
    return silhouette, semantic_edge, {"truthClass": ground_truth_label(image_id),
        "silhouetteSource": silhouette_source,
        "internalSemanticBoundaryAvailable": semantic_edge is not None}


def _load_sidecars(image_id: str) -> tuple[np.ndarray | None, np.ndarray | None]:
    if not image_id.startswith("synthetic-"):
        return None, None
    base = BACKEND / "artifacts/contour_preserving/task_08a/dataset_references/synthetic"
    name = image_id.removeprefix("synthetic-")
    alpha_path, labels_path = base / f"{name}_analytic_alpha.png", base / f"{name}_semantic_labels.png"
    alpha = np.asarray(Image.open(alpha_path).convert("L"), dtype=np.uint8) > 16 if alpha_path.exists() else None
    labels = np.asarray(Image.open(labels_path).convert("L"), dtype=np.uint8) if labels_path.exists() else None
    return alpha, labels


def _read_engine_records(run_root: Path, image_id: str) -> dict[str, dict[str, Any]]:
    folder = run_root / "outputs" / image_id
    rows = {}
    for engine in ENGINE_IDS:
        path = folder / engine / "run_record.json"
        rows[engine] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"status": "MISSING", "recordPath": str(path)}
    return rows


def run_comparison(*, timeout: int = 900) -> dict[str, Any]:
    """Run the five controlled fixtures through the real API, isolated per source image."""
    from tools.task_08a_1.dataset import BASE_MANIFEST
    from tools.vectorization_benchmark.worker import run_image

    manifest = json.loads(BASE_MANIFEST.read_text(encoding="utf-8"))
    items = {row["imageId"]: row for row in manifest["items"]}
    missing = [key for key in FIXTURE_IDS if key not in items]
    if missing:
        raise FileNotFoundError(f"Required benchmark source missing: {missing}")
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
    os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
    os.environ["DEBUG_VECTOR"] = "0"  # debug writers have separate known constraints; stage metrics are captured in API metadata.
    run_id = "task08b1_1_controlled"
    run_root = ARTIFACT_ROOT / "runs" / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    results = []
    for index, image_id in enumerate(FIXTURE_IDS):
        item = dict(items[image_id])
        item["benchmarkOrderIndex"] = index
        record = run_image(item, ARTIFACT_ROOT, per_engine_timeout=timeout, run_id=run_id)
        results.append({"imageId": image_id, "status": record.get("status"),
                        "sourceSha256": record.get("sourceSha256"), "sourcePath": record.get("sourcePath"),
                        "renderDimensions": record.get("renderDimensions"), "sameAssetIdUsedByBothEngines": record.get("sameAssetIdUsedByBothEngines"),
                        "engines": {name: record.get("engines", {}).get(name, {}) for name in ENGINE_IDS}})
    summary = {"schemaVersion": 1, "runId": run_id, "fixtureIds": list(FIXTURE_IDS),
               "engineIds": list(ENGINE_IDS), "configuration": {"qualityMode": "auto", "textMode": "outlined",
               "transparentBackground": True, "nativeSourceCanvas": True},
               "startedFromCurrentProductionApi": True,
               "elapsedSeconds": round(time.perf_counter() - started, 3), "fixtures": results}
    write_json(ARTIFACT_ROOT / "comparison_run.json", summary)
    return summary


def _save_label_preview(labels: np.ndarray, foreground: np.ndarray, path: Path) -> None:
    labels = np.asarray(labels, dtype=np.int32)
    foreground = np.asarray(foreground, dtype=bool)
    preview = np.full((*labels.shape, 3), 246, dtype=np.uint8)
    for label in np.unique(labels[foreground]):
        hue = (int(label) * 67 + 11) % 180
        color = cv2.cvtColor(np.uint8([[[hue, 170, 220]]]), cv2.COLOR_HSV2RGB)[0, 0]
        preview[(labels == label) & foreground] = color
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(preview, "RGB").save(path)


def _save_boundary_preview(base_rgba: np.ndarray, labels: np.ndarray, path: Path) -> None:
    base = Image.fromarray(base_rgba, "RGBA")
    white = Image.new("RGBA", base.size, "white")
    white.alpha_composite(base)
    rgb = white.convert("RGB")
    edge = boundary_map(labels, content=np.asarray(labels) > 0)
    overlay = np.asarray(rgb).copy()
    overlay[edge] = (247, 37, 87)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(overlay, "RGB").save(path)


def export_intermediates() -> dict[str, Any]:
    """Re-run production stage functions without debug-only API hooks and save the actual labels."""
    from mediastudio.image_tools.vectorization_v2.phase_b import get_process_ocr_engine, run_phase_b
    from mediastudio.image_tools.vectorization_v2.phase_c import run_phase_c
    from mediastudio.image_tools.vectorization_v2.phase_d1 import run_phase_d1
    from mediastudio.image_tools.vectorization_v2.phase_e1 import run_phase_e1
    from mediastudio.image_tools.vectorization_v2.pipeline import run_phase_a
    from mediastudio.image_tools.vectorization_contour import (
        ContourConfig, extract_contour_topology, prepare_processing_image, run_contour_segmentation,
    )
    from mediastudio.image_tools import contour_backend
    from PIL import ImageOps

    result_rows: dict[str, Any] = {}
    source_items = {row["imageId"]: row for row in json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))["items"]}
    for image_id in FIXTURE_IDS:
        source_path = REPOSITORY / source_items[image_id]["path"]
        source = load_rgba(source_path)
        stage_root = ARTIFACT_ROOT / "stages" / image_id
        with Image.open(source_path) as opened:
            normalized = ImageOps.exif_transpose(opened).convert("RGBA")
        max_dim = 800
        if max(normalized.size) > max_dim:
            scale = max_dim / max(normalized.size)
            normalized = normalized.resize((max(1, round(normalized.width * scale)),
                                             max(1, round(normalized.height * scale))), Image.Resampling.LANCZOS)
        smart_a = run_phase_a(normalized, processing_scale=1)
        smart_b = run_phase_b(smart_a, ocr_engine=get_process_ocr_engine())
        smart_c = run_phase_c(smart_b)
        smart_d = run_phase_d1(smart_c)
        smart_dir = stage_root / "smart_reconstruction"
        smart_dir.mkdir(parents=True, exist_ok=True)
        # Phase E1 is rerun only as diagnostic evidence: no product/source code changes.
        # The Active Fox debug bundle is captured because it is the real-image candidate ROI.
        e1_debug = smart_dir / "phase_e1_debug" if image_id == "active-fox-native-jpeg" else None
        smart_e1 = run_phase_e1(smart_c, smart_d, debug_directory=e1_debug)
        Image.fromarray(np.asarray(smart_e1.svg_render_rgba, dtype=np.uint8), "RGBA").save(smart_dir / "phase_e1_svg_render.png")
        write_json(smart_dir / "phase_e1_metrics.json", smart_e1.metrics)
        np.save(smart_dir / "phase_c_region_labels.npy", np.asarray(smart_c.region_labels, dtype=np.int32))
        Image.fromarray(np.asarray(smart_a.foreground_rgba, dtype=np.uint8), "RGBA").save(smart_dir / "phase_a_foreground.png")
        Image.fromarray(np.asarray(smart_b.graphic_only_rgba, dtype=np.uint8), "RGBA").save(smart_dir / "phase_b_graphic_only.png")
        _save_label_preview(smart_c.region_labels, smart_c.region_labels > 0, smart_dir / "phase_c_regions.png")
        _save_boundary_preview(smart_c.input_rgba, smart_c.region_labels, smart_dir / "phase_c_boundaries.png")
        write_json(smart_dir / "phase_metrics.json", {"phaseA": smart_a.metrics, "phaseB": smart_b.metrics,
                    "phaseC": smart_c.metrics, "phaseD1": smart_d.metrics, "phaseE1": smart_e1.metrics,
                    "stageEvidenceSource": "direct production phase functions; current source tree"})

        source_rgba = contour_backend._normalized_source(source_path)
        contour_a_image, source_to_a = contour_backend._phase_a_work_image(source_rgba)
        contour_a = run_phase_a(contour_a_image, processing_scale=1)
        contour_b = run_phase_b(contour_a, ocr_engine=get_process_ocr_engine())
        config = ContourConfig(working_max_dimension=800)
        processing, mapping = prepare_processing_image(source_rgba, 800)
        processing, foreground, excluded_text = contour_backend._build_graphic_processing(
            source_rgba, processing, contour_b, mapping.processing_size, mapping, config.alpha_threshold)
        contour_seg = run_contour_segmentation(source_rgba, processing_rgba=processing,
                                               foreground_mask=foreground, coordinate_mapping=mapping, config=config)
        contour_top = extract_contour_topology(contour_seg)
        api_contour_record = _read_engine_records(ARTIFACT_ROOT / "runs" / "task08b1_1_controlled", image_id)["contour_preserving"]
        api_contour_appearance = api_contour_record.get("actualConfiguration", {}).get("engineMetadata", {}).get("appearance", {})
        contour_dir = stage_root / "contour_preserving"
        contour_dir.mkdir(parents=True, exist_ok=True)
        np.save(contour_dir / "segmentation_label_map.npy", np.asarray(contour_seg.label_map, dtype=np.int32))
        Image.fromarray(np.asarray(contour_a.foreground_rgba, dtype=np.uint8), "RGBA").save(contour_dir / "phase_a_foreground.png")
        Image.fromarray(np.asarray(contour_b.graphic_only_rgba, dtype=np.uint8), "RGBA").save(contour_dir / "phase_b_graphic_only.png")
        _save_label_preview(contour_seg.label_map, foreground, contour_dir / "segmentation_regions.png")
        _save_boundary_preview(processing, contour_seg.label_map, contour_dir / "segmentation_boundaries.png")
        topo_overlay = np.asarray(Image.fromarray(processing, "RGBA").convert("RGB")).copy()
        for interface in contour_top.interfaces:
            for point in contour_top.interface_points(interface.id):
                x, y = int(round(point[0])), int(round(point[1]))
                if 0 <= y < topo_overlay.shape[0] and 0 <= x < topo_overlay.shape[1]:
                    topo_overlay[y, x] = (247, 37, 87)
        Image.fromarray(topo_overlay, "RGB").save(contour_dir / "canonical_topology_boundaries.png")
        write_json(contour_dir / "phase_metrics.json", {"phaseA": contour_a.metrics, "phaseB": contour_b.metrics,
                    "segmentation": contour_seg.metrics, "topology": contour_top.metrics,
                    "topologyValidation": {"geometryValid": contour_top.geometry_valid,
                                           "sharedInterfaceCount": contour_top.shared_interface_count,
                                           "errors": [str(error) for error in contour_top.validation.errors]},
                    "productionApiAppearanceTelemetry": api_contour_appearance,
                    "mapping": {"sourceSize": list(mapping.reference_size), "processingSize": list(mapping.processing_size),
                                "scaleXY": list(mapping.scale), "phaseASize": list(source_to_a.processing_size)},
                    "excludedTextPixels": int(excluded_text.sum()),
                    "stageEvidenceSource": "direct production phase functions; current source tree"})
        result_rows[image_id] = {
            "smart": {"phaseCRegions": int(smart_c.metrics["final_region_count"]),
                      "phaseD1SilhouetteIoU": smart_d.metrics.get("silhouette_iou"),
                      "phaseCFiles": [str(p) for p in sorted(smart_dir.iterdir())]},
            "contour": {"regions": len(contour_seg.regions), "topologyValid": contour_top.geometry_valid,
                        "sharedInterfaces": contour_top.shared_interface_count,
                        "files": [str(p) for p in sorted(contour_dir.iterdir())]},
        }
        # Compare direct stage replay with production API identity/configuration. The Smart API
        # deliberately omits the Phase C region count, so do not turn absent telemetry into a mismatch.
        api = _read_engine_records(ARTIFACT_ROOT / "runs" / "task08b1_1_controlled", image_id)
        api_smart_record = api["smart_reconstruction"]
        api_contour_record = api["contour_preserving"]
        api_smart_cfg = api_smart_record.get("actualConfiguration", {})
        api_contour_cfg = api_contour_record.get("actualConfiguration", {})
        expected_size = (source.shape[1], source.shape[0])

        def replay_matches(record: dict[str, Any], config: dict[str, Any], method: str, pipeline: str) -> bool:
            return bool(
                record.get("status") == "SUCCEEDED" and record.get("actualMethod") == method and
                record.get("sourceSha256") == source_items[image_id].get("sha256") and
                config.get("actualPipeline") == pipeline and config.get("actualQualityMode") == "auto" and
                config.get("actualTextMode") == "outlined" and
                (config.get("inputWidth"), config.get("inputHeight")) == expected_size
            )

        contour_api_seg = api_contour_cfg.get("engineMetadata", {}).get("segmentation", {})
        result_rows[image_id]["apiReplayParity"] = {
            "smartReplaySameSourceAndConfiguration": replay_matches(api_smart_record, api_smart_cfg, "smart_reconstruction", "vectorization_v2"),
            "contourReplaySameSourceAndConfiguration": replay_matches(api_contour_record, api_contour_cfg, "contour_preserving", "contour_preserving"),
            "smartApiRegionCountTelemetry": "not_exposed",
            "smartDirectPhaseCRegionCount": int(smart_c.metrics["final_region_count"]),
            "contourApiRegionCount": contour_api_seg.get("final_region_count"),
            "contourDirectRegionCount": int(contour_seg.metrics["final_region_count"]),
            "contourRegionCountMatchesApi": contour_api_seg.get("final_region_count") == contour_seg.metrics.get("final_region_count"),
        }
    write_json(ARTIFACT_ROOT / "intermediate_evidence_index.json", result_rows)
    return result_rows


def _phase_payload(record: dict[str, Any], engine: str) -> dict[str, Any]:
    metadata = record.get("actualConfiguration", {}).get("engineMetadata", {})
    if engine == "smart_reconstruction":
        return {"phase_a": metadata.get("phaseA", {}), "phase_b": metadata.get("phaseB", {}),
                "segmentation": metadata.get("phaseC", {}), "geometry": metadata.get("phaseD1", {}),
                "appearance": metadata.get("phaseE1", {}), "svg": metadata}
    return {"phase_a": metadata.get("phaseA", {}), "phase_b": metadata.get("phaseB", {}),
            "segmentation": metadata.get("segmentation", {}), "topology": metadata.get("topology", {}),
            "geometry": metadata.get("geometry", {}), "appearance": metadata.get("appearance", {}),
            "svg": metadata}


def _region_edge_from_engine(engine: str, stages: dict[str, Any], shape: tuple[int, int]) -> np.ndarray | None:
    # API phase telemetry is evidence for counts and first-failing stage; actual masks are exported
    # by export_intermediates() for the two fixtures used in root-cause adjudication.
    return None


def _write_contact_sheet(image_id: str, source: np.ndarray, render_paths: dict[str, Path],
                         out_path: Path, *, annotation_boxes: list[tuple[str, tuple[int, int, int, int]]] | None = None) -> None:
    panels = [("SOURCE", source)] + [(engine.upper(), load_rgba(path)) for engine, path in render_paths.items()]
    candidates = [rgba for _, rgba in panels[1:]]
    if candidates:
        source_rgb = source[..., :3].astype(np.float32)
        differences = []
        for rgba in candidates:
            alpha = rgba[..., 3:4].astype(np.float32) / 255.0
            composite = rgba[..., :3].astype(np.float32) * alpha + 255.0 * (1.0 - alpha)
            differences.append(np.linalg.norm(composite - source_rgb, axis=2))
        strength = np.clip(np.max(differences, axis=0) * 2.2, 0, 255).astype(np.uint8)
        heat = np.zeros_like(source[..., :3])
        heat[..., 0] = strength
        heat[..., 1] = np.clip(40 + strength * .20, 0, 255).astype(np.uint8)
        panels.append(("MAX RGB ERROR", np.dstack([heat, np.full(strength.shape, 255, np.uint8)])))
    width, height = source.shape[1], source.shape[0]
    scale = max(1, min(1, 1600 // max(width, height)))
    panel_width, panel_height = width * scale, height * scale
    header_h = 30
    sheet = Image.new("RGB", (panel_width * len(panels), panel_height + header_h), "#f5f5f5")
    draw = ImageDraw.Draw(sheet)
    for i, (label, rgba) in enumerate(panels):
        draw.text((i * panel_width + 8, 8), label, fill="#1f2937")
        rgb = Image.fromarray(rgba[..., :3], "RGB")
        if rgba.shape[2] == 4:
            bg = Image.new("RGB", rgb.size, "white")
            bg.paste(rgb, mask=Image.fromarray(rgba[..., 3], "L"))
            rgb = bg
        sheet.paste(rgb.resize((panel_width, panel_height)), (i * panel_width, header_h))
        if annotation_boxes:
            d = ImageDraw.Draw(sheet)
            for name, (x0, y0, x1, y1) in annotation_boxes:
                d.rectangle((i * panel_width + x0, header_h + y0, i * panel_width + x1, header_h + y1), outline="#ff2677", width=2)
                if i == 0:
                    d.text((i * panel_width + x0 + 2, header_h + y0 + 2), name, fill="#ff2677")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)


def _save_roi_artifacts(image_id: str, source: np.ndarray, renders: dict[str, np.ndarray],
                        name: str, box: tuple[int, int, int, int], target: Path,
                        overlay_paths: dict[str, Path] | None = None) -> None:
    x0, y0, x1, y1 = box
    crops: list[tuple[str, np.ndarray]] = [("SRC", source[y0:y1, x0:x1, :3])]
    for engine, render in renders.items():
        rgba = render[y0:y1, x0:x1]
        alpha = rgba[..., 3:4].astype(np.float32) / 255.0
        rgb = np.rint(rgba[..., :3] * alpha + 255.0 * (1.0 - alpha)).astype(np.uint8)
        crops.append(("SMART" if engine == "smart_reconstruction" else "CONTOUR", rgb))
    for engine, overlay_path in (overlay_paths or {}).items():
        if overlay_path.is_file():
            overlay = np.asarray(Image.open(overlay_path).convert("RGB"))
            crops.append(("S_ERR" if engine == "smart_reconstruction" else "C_ERR", overlay[y0:y1, x0:x1]))
    panel_w = max(crop.shape[1] for _, crop in crops)
    panel_h = max(crop.shape[0] for _, crop in crops)
    canvas = Image.new("RGB", (panel_w * len(crops), panel_h + 26), "white")
    for idx, (label, crop) in enumerate(crops):
        canvas.paste(Image.fromarray(crop, "RGB"), (idx * panel_w, 26))
        ImageDraw.Draw(canvas).text((idx * panel_w + 4, 5), label, fill="#111827")
    target.mkdir(parents=True, exist_ok=True)
    canvas.resize((canvas.width * 4, canvas.height * 4), Image.Resampling.NEAREST).save(target / f"{image_id}_{name}_4x.png")


def analyze_run() -> dict[str, Any]:
    run_root = ARTIFACT_ROOT / "runs" / "task08b1_1_controlled"
    matrix: list[dict[str, Any]] = []
    boundary_analysis: dict[str, Any] = {"tolerancePx": BOUNDARY_TOLERANCE_PX, "fixtures": {}}
    gradient_analysis: dict[str, Any] = {"fixedFalseEdgeThresholdDeltaEPerPx": GRADIENT_FALSE_EDGE_DELTA_E_PER_PX, "fixtures": {}}
    first_stage: list[dict[str, Any]] = []
    all_visual_paths: dict[str, dict[str, Path]] = {}
    for image_id in FIXTURE_IDS:
        run_folder = run_root / "outputs" / image_id
        source_path = REPOSITORY / next(row["path"] for row in json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))["items"] if row["imageId"] == image_id)
        source = load_rgba(source_path)
        alpha_truth, semantic = _load_sidecars(image_id)
        truth_silhouette, truth_semantic_edge, truth_info = _source_truth_edges(image_id, source, semantic, alpha_truth)
        engines = _read_engine_records(run_root, image_id)
        renders: dict[str, np.ndarray] = {}
        render_paths = {}
        fixture_rows = []
        for engine in ENGINE_IDS:
            record = engines[engine]
            if record.get("status") != "SUCCEEDED":
                matrix.append({"fixture": image_id, "engine": engine, "status": record.get("status", "MISSING"),
                               "groundTruth": truth_info["truthClass"]})
                continue
            svg_path = run_folder / engine / "output.svg"
            render_path = run_folder / engine / "render_edge.png"
            render = load_rgba(render_path)
            assert_native_alignment(source, render)
            renders[engine] = render
            render_paths[engine] = render_path
            svg = inspect_svg(svg_path, (source.shape[1], source.shape[0]))
            qa = record.get("qualityMetrics", {})
            stages = _phase_payload(record, engine)
            direct_metrics_path = ARTIFACT_ROOT / "stages" / image_id / engine / "phase_metrics.json"
            if direct_metrics_path.is_file():
                direct_metrics = json.loads(direct_metrics_path.read_text(encoding="utf-8"))
                if engine == "smart_reconstruction":
                    stages["segmentation"] = direct_metrics.get("phaseC", {})
                    stages["geometry"] = direct_metrics.get("phaseD1", {})
                else:
                    stages["segmentation"] = direct_metrics.get("segmentation", {})
                    stages["topology"] = direct_metrics.get("topology", {})
            silhouette_candidate = boundary_map(render[..., 3] > 16)
            truth_metric_class = "ANALYTIC_GROUND_TRUTH" if truth_info["truthClass"]["isGroundTruth"] else "REAL_IMAGE_PROXY_NOT_GROUND_TRUTH"
            silhouette = matched_boundary_metrics(truth_silhouette, silhouette_candidate,
                                                  ground_truth_class=truth_metric_class)
            color = qa.get("color", {}).get("foregroundOrContent", {})
            semantic_report = qa.get("semantic", {})
            g_roi = _fixture_roi(image_id, source, semantic)
            grad = gradient_metrics(source[..., :3], render[..., :3], g_roi["mask"]) if g_roi["mask"].any() else {"status": "NO_GRADIENT_ROI"}
            seg_meta = stages.get("segmentation", {})
            geom_meta = stages.get("geometry", {})
            appearance_meta = stages.get("appearance", {})
            internal = None
            if truth_semantic_edge is not None:
                # Nearest source-label swatch assignment on the final render; analytic fixture metric.
                internal = semantic_report.get("internalBoundary") or qa.get("details", {}).get("internalBoundary")
            row = {
                "fixture": image_id, "engine": engine, "status": record.get("status"),
                "groundTruth": truth_info["truthClass"], "svg": svg,
                "hardBoundary": {"finalSilhouette": silhouette,
                                 "finalInternalSemanticBoundary": internal,
                                 "topologyRegionCount": seg_meta.get("final_region_count", seg_meta.get("finalRegionCount")),
                                 "sourceHardBoundaryCount": int(truth_semantic_edge.sum()) if truth_semantic_edge is not None else int(truth_silhouette.sum())},
                "softGradient": {"roi": {k: v for k, v in g_roi.items() if k != "mask"}, **grad,
                                 "segmentationRegionCount": seg_meta.get("gradient_region_count", seg_meta.get("gradientRegionCount"))},
                "qualityProxy": {"meanDeltaE00": color.get("meanDeltaE00"), "p95DeltaE00": color.get("p95DeltaE00"),
                                 "ssim": color.get("maskedSsim"), "silhouetteIoU": qa.get("geometry", {}).get("foregroundIoU"),
                                 "semanticInternalBoundary": internal},
                "stageMetrics": stages,
                "sourceEvidence": truth_info,
            }
            if not truth_info["truthClass"]["isGroundTruth"]:
                row["boundaryAppearanceClassification"] = "REAL_IMAGE_PROXY_ONLY"
            else:
                hard_boundary_ok = (
                    silhouette["recallWithinTolerance"] >= .95 and
                    silhouette["precisionWithinTolerance"] >= .95 and
                    (internal is None or (internal.get("recallWithinTolerance", 0) >= .95 and
                                          internal.get("precisionWithinTolerance", 0) >= .95))
                )
                if grad.get("falseHardEdgeFraction", 0) > .01:
                    classification = "FALSE_HARD_BOUNDARY"
                elif not hard_boundary_ok:
                    classification = "MISSING_HARD_BOUNDARY"
                elif ((color.get("meanDeltaE00") or 0) >= APPEARANCE_MEAN_DELTA_E_THRESHOLD or
                      (color.get("p95DeltaE00") or 0) >= APPEARANCE_P95_DELTA_E_THRESHOLD or
                      (grad.get("meanDeltaE00") or 0) >= APPEARANCE_MEAN_DELTA_E_THRESHOLD or
                      (grad.get("p95DeltaE00") or 0) >= APPEARANCE_P95_DELTA_E_THRESHOLD):
                    classification = "BOUNDARY_CORRECT_APPEARANCE_WRONG"
                else:
                    classification = "NO_TARGET_DEFECT_MEASURED"
                row["boundaryAppearanceClassification"] = classification
            row["appearanceThresholds"] = {
                "meanDeltaE00": APPEARANCE_MEAN_DELTA_E_THRESHOLD,
                "p95DeltaE00": APPEARANCE_P95_DELTA_E_THRESHOLD,
                "hardBoundaryTolerancePx": BOUNDARY_TOLERANCE_PX,
                "falseHardEdgeFraction": 0.01,
            }
            matrix.append(row)
            fixture_rows.append(row)
            # Stage attribution uses actual returned engine stage metrics; a synthetic GT boundary miss
            # at segmentation is assigned there only when stage label boundary stats are available.
            if image_id.startswith("synthetic-"):
                if svg["status"] != "PASS":
                    stage, confidence, evidence = "SVG_COMPOSITION_OR_COORDINATE_MAPPING", "VERIFIED", svg
                elif silhouette["recallWithinTolerance"] < .95 or silhouette["precisionWithinTolerance"] < .95:
                    stage, confidence = "GEOMETRY_OR_PHASE_A", "PROBABLE"
                    evidence = {"finalNativeBoundaryMetrics": silhouette,
                                "reason": "final SVG silhouette diverges from analytic alpha; intermediate mask evidence decides whether Phase A or geometry is first"}
                elif grad.get("falseHardEdgeFraction", 0) > .01:
                    stage, confidence = "APPEARANCE_OR_SVG_COMPOSITING", "PROBABLE"
                    evidence = {"finalGradientROI": grad, "reason": "visible render has excess high-gradient edges; segmentation and geometry stage masks are needed to promote confidence"}
                else:
                    stage, confidence, evidence = "NO_BOUNDARY_DEFECT_OBSERVED", "VERIFIED", {"silhouette": silhouette, "gradient": grad}
                first_stage.append({"fixture": image_id, "engine": engine, "firstFailingStage": stage,
                                    "confidence": confidence, "evidence": evidence,
                                    "directIntermediateArtifacts": False})
            else:
                first_stage.append({"fixture": image_id, "engine": engine, "firstFailingStage": "UNKNOWN",
                                    "confidence": "UNKNOWN", "evidence": {"note": "ACTIVE FOX source has no analytic geometry/color ground truth; Task 07/08A ROI evidence is proxy only."},
                                    "directIntermediateArtifacts": False})
            # Source-to-output error overlay. Green = analytic silhouette, yellow = analytic
            # internal semantic boundary, magenta = rendered silhouette; red = ΔE00 > 5.
            overlay = _make_boundary_error_overlay(source, render, truth_silhouette,
                                                    truth_semantic_edge)
            overlay_path = ARTIFACT_ROOT / "visuals" / "boundary_overlays" / f"{image_id}_{engine}.png"
            overlay_path.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(overlay, "RGB").save(overlay_path)
        boundary_analysis["fixtures"][image_id] = {"groundTruth": truth_info, "engines": {
            row["engine"]: row["hardBoundary"] for row in fixture_rows}}
        gradient_analysis["fixtures"][image_id] = {"roi": {k: v for k, v in g_roi.items() if k != "mask"}, "engines": {
            row["engine"]: row["softGradient"] for row in fixture_rows}}
        if renders:
            boxes = []
            if image_id == "active-fox-native-jpeg":
                ann = json.loads((BACKEND / "tests/fixtures/active_fox_phase_c_annotations.json").read_text(encoding="utf-8"))
                boxes.extend((f"text_{i}", tuple(b)) for i, b in enumerate(ann["text_rois_xyxy"]))
                boxes.append(("tail_body_gradient", tuple(ann["tail_body_gradient_roi_xyxy"])))
                boxes.append(("inner_ear", tuple(ann["inner_ear_roi_xyxy"])))
            else:
                boxes.append(("analytic_content", (0, 0, source.shape[1], source.shape[0])))
            _write_contact_sheet(image_id, source, render_paths, ARTIFACT_ROOT / "visuals" / "contact_sheets" / f"{image_id}.png", annotation_boxes=boxes)
            if image_id == "active-fox-native-jpeg":
                for name, box in boxes:
                    _save_roi_artifacts(image_id, source, renders, name, box,
                                        ARTIFACT_ROOT / "visuals" / "rois",
                                        {engine: ARTIFACT_ROOT / "visuals" / "boundary_overlays" / f"{image_id}_{engine}.png"
                                         for engine in ENGINE_IDS})
            elif image_id in {"synthetic-linear_gradient", "synthetic-radial_gradient", "synthetic-multiregion_illustration"}:
                # Whole-frame analytical ROI is retained at 4x as the source/engine/error comparison.
                _save_roi_artifacts(image_id, source, renders, "analytic_full", (0, 0, source.shape[1], source.shape[0]),
                                    ARTIFACT_ROOT / "visuals" / "rois",
                                    {engine: ARTIFACT_ROOT / "visuals" / "boundary_overlays" / f"{image_id}_{engine}.png"
                                     for engine in ENGINE_IDS})

    compare = json.loads((ARTIFACT_ROOT / "comparison_run.json").read_text(encoding="utf-8"))
    artifacts = {"runRoot": str(run_root), "sourceManifest": str(SOURCE_MANIFEST),
                 "sourceChanged": False, "fixtureCount": len(FIXTURE_IDS), "engineCount": len(ENGINE_IDS),
                 "engineStatuses": {fixture["imageId"]: {engine: fixture.get("engines", {}).get(engine, {}).get("status")
                                                            for engine in ENGINE_IDS} for fixture in compare["fixtures"]}}
    write_json(ARTIFACT_ROOT / "boundary_fidelity_matrix.json", {"schemaVersion": 1, "tolerancePx": BOUNDARY_TOLERANCE_PX,
               "coordinateSpace": "native source pixel coordinates", "rows": matrix})
    write_json(ARTIFACT_ROOT / "hard_boundary_analysis.json", boundary_analysis)
    write_json(ARTIFACT_ROOT / "soft_gradient_analysis.json", gradient_analysis)
    direct_rows = _stage_root_cause_rows()
    write_json(ARTIFACT_ROOT / "first_failing_stage_analysis.json", {"schemaVersion": 1, "rows": direct_rows,
               "confidencePolicy": "VERIFIED requires direct stage evidence; PROBABLE is final-render inference only; UNKNOWN for proxy without stage defect evidence."})
    _make_top_defects(matrix, direct_rows)
    write_json(ARTIFACT_ROOT / "production_changes.json", {"productionFilesChanged": [], "productionAlgorithmsChanged": False,
               "diagnosticFilesAdded": ["backend/tools/task_08b_1_1/__init__.py", "backend/tools/task_08b_1_1/diagnostics.py",
                                        "backend/tests/test_task_08b_1_1.py"],
               "sourceScopeVerification": "No production source write was made by Task 08B.1.1; tested task code is confined to tools/task_08b_1_1 and tests/test_task_08b_1_1.py.",
               "repositoryBaselineCaveat": "The repository was untracked at task entry, so Git diff cannot provide a tracked pre-task byte baseline; this limitation is recorded in production_source_scope.json.",
               "note": "No Smart V2 or Contour production implementation modified."})
    return {"matrix": matrix, "firstFailingStages": direct_rows, "artifacts": artifacts}


def _make_boundary_error_overlay(source: np.ndarray, render: np.ndarray,
                                 truth_silhouette: np.ndarray,
                                 truth_semantic_edge: np.ndarray | None) -> np.ndarray:
    base = source[..., :3].copy()
    # Render color on white; use an alpha-aware comparison for transparent output.
    candidate_rgb = render[..., :3].astype(np.float32)
    candidate_rgb = candidate_rgb * (render[..., 3:4].astype(np.float32) / 255.0) + 255.0 * (1.0 - render[..., 3:4].astype(np.float32) / 255.0)
    source_rgb = source[..., :3].astype(np.float32)
    source_lab = rgb2lab(source_rgb / 255.0)
    candidate_lab = rgb2lab(candidate_rgb / 255.0)
    delta = deltaE_ciede2000(source_lab, candidate_lab)
    error = delta > 5.0
    base[error] = np.rint(base[error].astype(np.float32) * .35 + np.array([255, 45, 35]) * .65).astype(np.uint8)
    output = boundary_map(render[..., 3] > 16)
    base[truth_silhouette] = (31, 191, 101)
    if truth_semantic_edge is not None:
        base[truth_semantic_edge] = (242, 198, 36)
    base[output] = (222, 39, 192)
    return base


def _stage_root_cause_rows() -> list[dict[str, Any]]:
    stage_root = ARTIFACT_ROOT / "stages"
    rows: list[dict[str, Any]] = []
    run_root = ARTIFACT_ROOT / "runs" / "task08b1_1_controlled"
    items = {row["imageId"]: row for row in json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))["items"]}
    for image_id in FIXTURE_IDS:
        source = load_rgba(REPOSITORY / items[image_id]["path"])
        alpha_truth, semantic = _load_sidecars(image_id)
        truth_silhouette, truth_semantic, truth_info = _source_truth_edges(image_id, source, semantic, alpha_truth)
        roi = _fixture_roi(image_id, source, semantic)
        for engine in ENGINE_IDS:
            stage_dir = stage_root / image_id / engine
            metrics_path = stage_dir / "phase_metrics.json"
            label_path = stage_dir / ("phase_c_region_labels.npy" if engine == "smart_reconstruction" else "segmentation_label_map.npy")
            if not metrics_path.is_file() or not label_path.is_file():
                rows.append({"fixture": image_id, "engine": engine, "firstFailingStage": "UNKNOWN",
                             "confidence": "UNKNOWN", "evidence": {"missingIntermediate": str(label_path)}})
                continue
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            labels = np.load(label_path).astype(np.int32)
            if labels.shape != truth_silhouette.shape:
                labels = cv2.resize(labels, (source.shape[1], source.shape[0]), interpolation=cv2.INTER_NEAREST)
            phase_a_path = stage_dir / "phase_a_foreground.png"
            phase_a_rgba = load_rgba(phase_a_path)
            phase_a_mask = phase_a_rgba[..., 3] > 16
            truth_metric_class = "ANALYTIC_GROUND_TRUTH" if truth_info["truthClass"]["isGroundTruth"] else "REAL_IMAGE_PROXY_NOT_GROUND_TRUTH"
            phase_a_boundary = matched_boundary_metrics(truth_silhouette, boundary_map(phase_a_mask),
                                                        ground_truth_class=truth_metric_class)
            seg_silhouette = labels > 0
            seg_silhouette_edge = boundary_map(seg_silhouette)
            segmentation_silhouette_score = matched_boundary_metrics(truth_silhouette, seg_silhouette_edge,
                                                                     ground_truth_class=truth_metric_class)
            internal_boundary_score = None
            if truth_semantic is not None:
                internal_boundary_score = matched_boundary_metrics(truth_semantic,
                    boundary_map(labels, content=seg_silhouette))
            api_record = _read_engine_records(run_root, image_id)[engine]
            final_rgba = load_rgba(run_root / "outputs" / image_id / engine / "render_edge.png")
            assert_native_alignment(source, final_rgba)
            final_edge_metrics = matched_boundary_metrics(truth_silhouette, boundary_map(final_rgba[..., 3] > 16),
                                                          ground_truth_class=truth_metric_class)
            phase_e1_evidence: dict[str, Any] | None = None
            if engine == "smart_reconstruction":
                e1_render_path = stage_dir / "phase_e1_svg_render.png"
                e1_metrics_path = stage_dir / "phase_e1_metrics.json"
                if e1_render_path.is_file() and e1_metrics_path.is_file():
                    e1_render = load_rgba(e1_render_path)
                    assert_native_alignment(source, e1_render)
                    e1_metrics = json.loads(e1_metrics_path.read_text(encoding="utf-8"))
                    e1_gradient = gradient_metrics(source[..., :3], e1_render[..., :3], roi["mask"]) if roi["mask"].any() else {"status": "NO_GRADIENT_ROI"}
                    roi_pixels = roi["mask"]
                    phase_e1_equals_api = bool(
                        np.array_equal(e1_render[roi_pixels], final_rgba[roi_pixels]) if roi_pixels.any()
                        else np.array_equal(e1_render, final_rgba)
                    )
                    phase_e1_evidence = {
                        "source": "direct production run_phase_e1 replay",
                        "sameNativeCanvasAsApi": True,
                        "phaseE1RenderMatchesProductionApiInDiagnosticRoi": phase_e1_equals_api,
                        "roi": {key: value for key, value in roi.items() if key != "mask"},
                        "softGradient": e1_gradient,
                        "appearanceMetrics": {
                            "rootCause": e1_metrics.get("root_cause"),
                            "newPhaseE1FullGraphic": e1_metrics.get("new_phase_e1", {}).get("full_graphic"),
                            "newPhaseE1Interior": e1_metrics.get("new_phase_e1", {}).get("interior_only"),
                            "geometryUnchanged": e1_metrics.get("geometry_unchanged"),
                            "svgCoordinateMappingOk": e1_metrics.get("coordinate_audit", {}).get("mapping_ok"),
                        },
                        "renderPath": str(e1_render_path),
                    }
            segmentation_gradient_edge_count = 0
            render_gradient = {"falseHardEdgePixels": 0, "falseHardEdgeFraction": 0.0,
                               "falseEdgeAlignedWithSegmentationFraction": 0.0}
            if roi["mask"].any():
                stage_roi = cv2.resize(roi["mask"].astype(np.uint8), (labels.shape[1], labels.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
                seg_edge = boundary_map(labels, content=labels > 0)
                segmentation_gradient_edge_count = int((seg_edge & stage_roi).sum())
                source_lab = rgb2lab(source[..., :3].astype(np.float32) / 255.0)
                render_lab = rgb2lab(final_rgba[..., :3].astype(np.float32) / 255.0)
                source_delta, render_delta = _lab_neighbor_delta(source_lab), _lab_neighbor_delta(render_lab)
                inner_roi = cv2.erode(roi["mask"].astype(np.uint8), np.ones((3, 3), np.uint8), 1) > 0
                render_false_edge = inner_roi & (render_delta >= GRADIENT_FALSE_EDGE_DELTA_E_PER_PX) & (render_delta > source_delta * 2.5 + .75)
                seg_edge_native = cv2.resize(seg_edge.astype(np.uint8), (source.shape[1], source.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
                supported_by_seg = cv2.dilate(seg_edge_native.astype(np.uint8), np.ones((3, 3), np.uint8), 1) > 0
                render_gradient = {"falseHardEdgePixels": int(render_false_edge.sum()),
                                   "falseHardEdgeFraction": float(render_false_edge.sum() / max(int(inner_roi.sum()), 1)),
                                   "falseEdgeAlignedWithSegmentationFraction": float((render_false_edge & supported_by_seg).sum() / max(int(render_false_edge.sum()), 1))}
            # Confirm same source hash, requested engine, production pipeline and output canvas.
            payload = _phase_payload(api_record, engine)
            api_seg = payload.get("segmentation", {})
            direct_seg = metrics.get("phaseC", {}) if engine == "smart_reconstruction" else metrics.get("segmentation", {})
            count_key = "final_region_count"
            api_cfg = api_record.get("actualConfiguration", {})
            expected_pipeline = "vectorization_v2" if engine == "smart_reconstruction" else "contour_preserving"
            stage_replay_compatible = (
                api_record.get("status") == "SUCCEEDED" and api_record.get("actualMethod") == engine and
                api_cfg.get("actualPipeline") == expected_pipeline and
                api_cfg.get("actualQualityMode") == "auto" and api_cfg.get("actualTextMode") == "outlined" and
                api_cfg.get("inputWidth") == source.shape[1] and api_cfg.get("inputHeight") == source.shape[0] and
                api_record.get("sourceSha256") == items[image_id].get("sha256")
            )
            api_region_count_matches = api_seg.get(count_key) == direct_seg.get(count_key) if api_seg.get(count_key) is not None else None
            e1_directly_reproduces_final = bool(phase_e1_evidence and phase_e1_evidence["phaseE1RenderMatchesProductionApiInDiagnosticRoi"])
            e1_gradient_false_edge = (phase_e1_evidence or {}).get("softGradient", {}).get("falseHardEdgeFraction", 0)
            if not stage_replay_compatible:
                stage, confidence = "UNKNOWN", "UNKNOWN"
            elif engine == "smart_reconstruction" and e1_directly_reproduces_final and truth_info["truthClass"]["isGroundTruth"] and (
                    e1_gradient_false_edge > .01 or
                    (e1_metrics.get("new_phase_e1", {}).get("full_graphic", {}).get("p95", 0) >= APPEARANCE_P95_DELTA_E_THRESHOLD and
                     truth_info["truthClass"]["isGroundTruth"])):
                stage, confidence = "PHASE_E1_APPEARANCE", "VERIFIED"
            elif engine == "smart_reconstruction" and e1_directly_reproduces_final and e1_gradient_false_edge > .01:
                stage, confidence = "PHASE_E1_APPEARANCE", "PROBABLE"
            elif image_id == "synthetic-multiregion_illustration" and internal_boundary_score and (
                    internal_boundary_score["recallWithinTolerance"] < .95 or internal_boundary_score["precisionWithinTolerance"] < .95):
                stage, confidence = "PHASE_C_SEGMENTATION", "VERIFIED"
            elif image_id in {"synthetic-linear_gradient", "synthetic-radial_gradient", "active-fox-native-jpeg"} and (
                    render_gradient["falseHardEdgeFraction"] > .01 and render_gradient["falseEdgeAlignedWithSegmentationFraction"] > .50):
                stage = "SEGMENTATION_TOPOLOGY_WITH_VISIBLE_RENDER_BANDING"
                confidence = "VERIFIED" if truth_info["truthClass"]["isGroundTruth"] else "PROBABLE"
            elif image_id in {"synthetic-linear_gradient", "synthetic-radial_gradient", "active-fox-native-jpeg"} and render_gradient["falseHardEdgeFraction"] > .01:
                stage, confidence = "APPEARANCE_OR_SVG_COMPOSITING", "PROBABLE"
            elif (phase_a_boundary["recallWithinTolerance"] < .95 or phase_a_boundary["precisionWithinTolerance"] < .95) and truth_info["truthClass"]["isGroundTruth"]:
                stage, confidence = "PHASE_A_BACKGROUND_MATTE", "VERIFIED"
            elif (segmentation_silhouette_score["recallWithinTolerance"] < .95 or segmentation_silhouette_score["precisionWithinTolerance"] < .95) and truth_info["truthClass"]["isGroundTruth"]:
                stage, confidence = "PHASE_B_OR_SEGMENTATION_DOMAIN", "VERIFIED"
            elif final_edge_metrics["recallWithinTolerance"] < .95 or final_edge_metrics["precisionWithinTolerance"] < .95:
                stage, confidence = "PHASE_A_OR_GEOMETRY", "PROBABLE"
            else:
                stage, confidence = "NO_HARD_BOUNDARY_FAILURE_MEASURED", "VERIFIED"
            rows.append({
                "fixture": image_id, "engine": engine, "firstFailingStage": stage, "confidence": confidence,
                "directIntermediateArtifacts": True, "sameSourceAndProductionConfigurationAsApi": stage_replay_compatible,
                "apiRegionCountMatch": api_region_count_matches,
                "groundTruth": truth_info["truthClass"],
                "phaseA": {"analyticSilhouetteBoundary": phase_a_boundary},
                "segmentation": {"regionCount": direct_seg.get(count_key),
                                 "boundaryPrecisionRecall": internal_boundary_score,
                                 "analyticSilhouetteBoundary": segmentation_silhouette_score,
                                 "gradientInternalBoundaryPixels": segmentation_gradient_edge_count},
                "finalRender": {"analyticSilhouetteBoundary": final_edge_metrics, "softGradient": render_gradient},
                "phaseE1": phase_e1_evidence,
                "evidencePaths": [str(label_path), str(metrics_path),
                                  str(stage_dir / ("phase_c_boundaries.png" if engine == "smart_reconstruction" else "segmentation_boundaries.png"))],
                "attributionNote": "Phase outputs were replayed with production functions using the same source hash, method, mode, text mode and native canvas. Smart API telemetry strips phase region counts, so API region-count parity is null rather than inferred.",
            })
    return rows


def _make_top_defects(matrix: list[dict[str, Any]], direct_rows: list[dict[str, Any]]) -> None:
    direct_by_key = {(row["fixture"], row["engine"]): row for row in direct_rows}
    candidates: list[dict[str, Any]] = []
    for row in matrix:
        if row.get("status") != "SUCCEEDED":
            continue
        direct = direct_by_key.get((row["fixture"], row["engine"]), {})
        hard = row.get("hardBoundary", {})
        final_silhouette = hard.get("finalSilhouette", {})
        gradient = row.get("softGradient", {})
        internal = hard.get("finalInternalSemanticBoundary") or {}
        is_analytic_ground_truth = row.get("groundTruth", {}).get("isGroundTruth", False)
        defect = None
        severity = 0.0
        if gradient.get("falseHardEdgeFraction", 0) > .01:
            defect = "FALSE_HARD_BOUNDARY"
            severity = float(gradient["falseHardEdgeFraction"])
        if is_analytic_ground_truth and (final_silhouette.get("recallWithinTolerance", 1) < .95 or final_silhouette.get("precisionWithinTolerance", 1) < .95):
            silhouette_severity = 1 - min(float(final_silhouette.get("recallWithinTolerance", 1)),
                                          float(final_silhouette.get("precisionWithinTolerance", 1)))
            if defect is None or silhouette_severity > severity:
                defect, severity = "MISSING_HARD_BOUNDARY", silhouette_severity
        elif not is_analytic_ground_truth and (final_silhouette.get("recallWithinTolerance", 1) < .95 or final_silhouette.get("precisionWithinTolerance", 1) < .95):
            # An estimated foreground mask is not truth. Keep its divergence visible without
            # presenting it as a confirmed missing boundary or allowing it to outrank a measured ROI defect.
            if defect is None:
                proxy_severity = 1 - min(float(final_silhouette.get("recallWithinTolerance", 1)),
                                         float(final_silhouette.get("precisionWithinTolerance", 1)))
                defect, severity = "PROXY_SILHOUETTE_DIVERGENCE", proxy_severity
        if internal and (internal.get("recallWithinTolerance", 1) < .95 or internal.get("precisionWithinTolerance", 1) < .95):
            internal_severity = 1 - min(float(internal.get("recallWithinTolerance", 1)),
                                        float(internal.get("precisionWithinTolerance", 1)))
            if defect is None or internal_severity > severity:
                defect, severity = "MISSING_HARD_BOUNDARY", internal_severity
        if row.get("boundaryAppearanceClassification") == "BOUNDARY_CORRECT_APPEARANCE_WRONG":
            color = row.get("qualityProxy", {})
            gradient_color = gradient
            mean_delta = max(float(color.get("meanDeltaE00") or 0), float(gradient_color.get("meanDeltaE00") or 0))
            p95_delta = max(float(color.get("p95DeltaE00") or 0), float(gradient_color.get("p95DeltaE00") or 0))
            appearance_severity = max(mean_delta / APPEARANCE_MEAN_DELTA_E_THRESHOLD,
                                      p95_delta / APPEARANCE_P95_DELTA_E_THRESHOLD) - 1.0
            if defect is None or appearance_severity > severity:
                defect, severity = "BOUNDARY_CORRECT_APPEARANCE_WRONG", appearance_severity
        if defect is None:
            continue
        roi_name = "tail_body_gradient" if row["fixture"] == "active-fox-native-jpeg" else "analytic_full"
        candidates.append({
            "fixture": row["fixture"], "engine": row["engine"], "defect": defect,
            "roi": gradient.get("roi", {}).get("annotation", "full source"),
            "severityProxy": round(severity, 5), "sourceEvidence": {"groundTruth": row.get("groundTruth"), "hardBoundary": hard},
            "svgEvidence": {"svg": row.get("svg"), "softGradient": gradient},
            "intermediateEvidence": direct.get("segmentation", {}),
            "firstFailingStage": direct.get("firstFailingStage", "UNKNOWN"),
            "confidence": direct.get("confidence", "UNKNOWN"),
            "evidenceClassification": "analytic ground truth" if is_analytic_ground_truth else "proxy only; not a ground-truth defect",
            "impact": ("Color/gradient fidelity crosses the fixed ΔE00 threshold while measured hard boundaries pass."
                       if defect == "BOUNDARY_CORRECT_APPEARANCE_WRONG" else
                       "Final render has excess hard-edge response inside the tested soft-gradient ROI."
                       if defect == "FALSE_HARD_BOUNDARY" else
                       "Boundary divergence candidate; interpret against the stated ground-truth class."),
            "visualEvidence": {
                "contactSheet": str(ARTIFACT_ROOT / "visuals" / "contact_sheets" / f"{row['fixture']}.png"),
                "sourceSmartContourRoi": str(ARTIFACT_ROOT / "visuals" / "rois" / f"{row['fixture']}_{roi_name}_4x.png"),
                "boundaryAndColorErrorOverlays": {
                    engine: str(ARTIFACT_ROOT / "visuals" / "boundary_overlays" / f"{row['fixture']}_{engine}.png")
                    for engine in ENGINE_IDS
                },
            },
            "repairProposalOnly": "In 08B.1.2 inspect the reported first failing stage and constrain any repair to that stage; this task made no algorithm changes.",
            "humanReview": row.get("groundTruth", {}).get("humanReview"),
        })
    candidates.sort(key=lambda row: (-row["severityProxy"], row["fixture"], row["engine"]))
    write_json(ARTIFACT_ROOT / "top_three_defects.json", {
        "schemaVersion": 1, "selectionPolicy": "Evidence-based with fixed thresholds; maximum 3; real-image evidence stays proxy.",
        "candidateCountBeforeCap": len(candidates), "defects": candidates[:3],
        "noCandidateMeaning": "No tested row crossed fixed diagnostic thresholds; this does not prove general fidelity." if not candidates else None,
    })


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import argparse
    parser = argparse.ArgumentParser(description="Task 08B.1.1 controlled vectorization diagnostics")
    parser.add_argument("command", choices=("run", "intermediates", "analyze"))
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    if args.command == "run":
        result = run_comparison(timeout=args.timeout)
    elif args.command == "intermediates":
        result = export_intermediates()
    else:
        result = analyze_run()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
