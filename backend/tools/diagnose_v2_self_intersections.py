"""Reproduce D1 self-intersection diagnostics for release QA fixtures."""
from __future__ import annotations

import json
import math
import copy
from pathlib import Path
import re
import sys
import time

import numpy as np
import cv2
from PIL import Image, ImageDraw, ImageOps
from shapely.geometry import LinearRing, Polygon
from shapely.validation import make_valid
from shapely.validation import explain_validity

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mediastudio.image_tools.vectorization_v2.phase_b import get_process_ocr_engine, run_phase_b
from mediastudio.image_tools.vectorization_v2.phase_c import run_phase_c
from mediastudio.image_tools.vectorization_v2.phase_d import path_points
from mediastudio.image_tools.vectorization_v2.phase_d1 import (
    _DEFAULT_TOLERANCE_SCALE,
    _boundary_tolerance,
    _compute_metrics,
    _fit_boundary_component,
    _invalid_boundary_refs,
    run_phase_d1,
)
from mediastudio.image_tools.vectorization_v2.phase_d1_debug import write_phase_d1_artifacts
from mediastudio.image_tools.vectorization_v2.phase_d_debug import _svg_path
from mediastudio.image_tools.vectorization_v2.phase_e1 import rasterize_svg
from mediastudio.image_tools.vectorization_v2.pipeline import run_phase_a


def _work_image(path: Path, max_dimension: int) -> tuple[Image.Image, tuple[int, int]]:
    with Image.open(path) as image:
        rgba = ImageOps.exif_transpose(image).convert("RGBA")
    source_size = rgba.size
    if max(rgba.size) > max_dimension:
        scale = max_dimension / max(rgba.size)
        rgba = rgba.resize((max(1, round(rgba.width * scale)),
                            max(1, round(rgba.height * scale))), Image.Resampling.LANCZOS)
    return rgba, source_size


def _sample_visit_groups(points: list[tuple[float, float]], xy: list[float],
                         tolerance: float = 0.10) -> list[list[int]]:
    values = np.asarray(points, dtype=np.float64)
    point = np.asarray(xy, dtype=np.float64)
    starts = values[:-1]
    vectors = values[1:] - starts
    lengths2 = np.sum(vectors * vectors, axis=1)
    factors = np.divide(np.sum((point - starts) * vectors, axis=1), lengths2,
                        out=np.zeros(len(starts), dtype=np.float64), where=lengths2 > 1e-12)
    factors = np.clip(factors, 0, 1)
    projections = starts + factors[:, None] * vectors
    close = np.flatnonzero(np.linalg.norm(projections - point, axis=1) <= tolerance).tolist()
    groups: list[list[int]] = []
    for index in close:
        if not groups or index > groups[-1][-1] + 1:
            groups.append([index])
        else:
            groups[-1].append(index)
    return groups


def _hole_areas(mask: np.ndarray) -> list[int]:
    background = (~mask).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(background, 8)
    border_labels = set(np.unique(np.concatenate((labels[0], labels[-1],
                                                   labels[:, 0], labels[:, -1]))).tolist())
    return sorted(int(stats[index, cv2.CC_STAT_AREA]) for index in range(1, count)
                  if index not in border_labels)


def diagnose(name: str, source_path: Path, mode: str, output_dir: Path,
             ocr_engine) -> dict:
    max_dimension = 554 if mode == "fast" else 800
    work, source_size = _work_image(source_path, max_dimension)
    timings: dict[str, float] = {}
    started = time.perf_counter()
    t = time.perf_counter()
    phase_a = run_phase_a(work, processing_scale=1)
    timings["phaseA_ms"] = round((time.perf_counter() - t) * 1000, 2)
    t = time.perf_counter()
    phase_b = run_phase_b(phase_a, ocr_engine=ocr_engine)
    timings["phaseB_ms"] = round((time.perf_counter() - t) * 1000, 2)
    t = time.perf_counter()
    phase_c = run_phase_c(phase_b)
    timings["phaseC_ms"] = round((time.perf_counter() - t) * 1000, 2)
    t = time.perf_counter()
    geometry = run_phase_d1(phase_c)
    timings["phaseD1_ms"] = round((time.perf_counter() - t) * 1000, 2)

    sweep_rows = []
    referenced = _invalid_boundary_refs(geometry)
    regions_by_id = {region.id: region for region in phase_c.graph.regions}
    diagonal = math.hypot(geometry.width, geometry.height)
    spacing = float(np.clip(diagonal * 0.0028, 1.5, 3.0))
    original_boundary_state = {}
    for boundary_id, component_index in referenced:
        boundary = geometry.boundary_by_id[boundary_id]
        original_boundary_state[(boundary_id, component_index)] = copy.deepcopy(boundary)
    for tolerance_scale in (0.45, 0.30, 0.20, 0.10):
        for boundary_id, component_index in referenced:
            boundary = geometry.boundary_by_id[boundary_id]
            baseline = original_boundary_state[(boundary_id, component_index)]
            if hasattr(boundary, "components") and boundary.components and component_index is not None:
                boundary.components[component_index] = copy.deepcopy(baseline.components[component_index])
                boundary.segments = [segment for component in boundary.components for segment in component]
            else:
                boundary.segments = copy.deepcopy(baseline.segments)
            if hasattr(boundary, "components") and boundary.components and component_index is not None:
                boundary.component_fallback_reasons[component_index] = None
            else:
                boundary.fallback_reason = None
            tol = _boundary_tolerance(boundary, regions_by_id, diagonal,
                                      _DEFAULT_TOLERANCE_SCALE)
            tol = max(0.10, tol * tolerance_scale / _DEFAULT_TOLERANCE_SCALE)
            _fit_boundary_component(boundary, component_index, tol, spacing)
        sweep_metrics = _compute_metrics(geometry)
        sweep_rows.append({
            "toleranceScale": tolerance_scale,
            "selfIntersectionCount": sweep_metrics["self_intersection_count"],
            "silhouetteIoU": sweep_metrics["silhouette_iou"],
            "anchorCount": sweep_metrics["total_bezier_anchor_count"],
            "maxBoundaryError": sweep_metrics["max_boundary_error"],
        })
    for key, baseline in original_boundary_state.items():
        boundary = geometry.boundary_by_id[key[0]]
        if hasattr(boundary, "components") and boundary.components and key[1] is not None:
            boundary.components[key[1]] = copy.deepcopy(baseline.components[key[1]])
            boundary.segments = [segment for component in boundary.components for segment in component]
        else:
            boundary.segments = copy.deepcopy(baseline.segments)
    geometry.metrics = _compute_metrics(geometry)
    timings["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)

    invalid = []
    output_dir.mkdir(parents=True, exist_ok=True)
    overlay = work.convert("RGB")
    draw = ImageDraw.Draw(overlay)
    index = 0
    by_id = geometry.boundary_by_id
    for shape in geometry.shapes:
        for kind, paths in (("outer", shape.outer_paths), ("hole", shape.hole_paths)):
            for path_index, vector_path in enumerate(paths, 1):
                points = path_points(vector_path, by_id, density=9.0)
                if len(points) < 4:
                    reason = "too few points"
                    intersection = None
                else:
                    ring = LinearRing(points)
                    if ring.is_simple and ring.is_valid:
                        continue
                    polygon = Polygon(points)
                    reason = explain_validity(polygon)
                    match = re.search(r"\[\s*([-+\d.eE]+)\s+([-+\d.eE]+)\s*\]", reason)
                    intersection = [float(match.group(1)), float(match.group(2))] if match else None
                index += 1
                refs = [{"boundaryId": ref.boundary_id, "reversed": ref.reversed,
                         "componentIndex": ref.component_index} for ref in vector_path.refs]
                row = {
                    "index": index,
                    "regionId": f"R{shape.region_id:02d}",
                    "region_id": shape.region_id,
                    "pathKind": kind,
                    "pathIndex": path_index,
                    "pointCount": len(points),
                    "refs": refs,
                    "reason": reason,
                    "intersectionWorkCanvas": intersection,
                }
                if intersection:
                    xy = np.asarray(points, dtype=np.float64)
                    distances = np.linalg.norm(xy - np.asarray(intersection), axis=1)
                    nearest = np.argsort(distances)[:12]
                    visits = sorted(int(i) for i in nearest if distances[i] <= 0.22)
                    row["nearestPathSampleIndices"] = visits
                    groups = _sample_visit_groups(points, intersection)
                    group_tangents: list[list[float]] = []
                    for group in groups:
                        center = round(sum(group) / len(group))
                        before = xy[max(0, center - 4)]
                        after = xy[min(len(xy) - 1, center + 5)]
                        tangent = after - before
                        norm = float(np.linalg.norm(tangent))
                        group_tangents.append((tangent / max(norm, 1e-12)).tolist())
                    angles = []
                    for left_index in range(len(group_tangents)):
                        for right_index in range(left_index + 1, len(group_tangents)):
                            left, right = group_tangents[left_index], group_tangents[right_index]
                            dot = float(np.clip(np.dot(left, right), -1, 1))
                            cross = left[0] * right[1] - left[1] * right[0]
                            angles.append(round(abs(math.degrees(math.atan2(cross, dot))), 3))
                    row["visitGroups"] = groups
                    row["crossingAnglesDeg"] = angles
                    repaired = make_valid(polygon)
                    row["makeValidType"] = repaired.geom_type
                    row["makeValidComponentCount"] = (len(repaired.geoms)
                                                       if hasattr(repaired, "geoms") else 1)
                    row["makeValidAreaDeltaPx2"] = round(float(repaired.area - polygon.area), 5)
                invalid.append(row)
                if intersection:
                    x, y = intersection
                    draw.line(points, fill=(0, 92, 255), width=2, joint="curve")
                    radius = 9
                    draw.ellipse((x-radius, y-radius, x+radius, y+radius),
                                 outline=(255, 0, 0), width=3)
                    draw.line((x-radius-4, y, x+radius+4, y), fill=(255, 0, 0), width=2)
                    draw.line((x, y-radius-4, x, y+radius+4), fill=(255, 0, 0), width=2)
                    draw.text((x+11, y-10), f"{index} {row['regionId']} {kind}",
                              fill=(170, 0, 0), stroke_width=2, stroke_fill=(255, 255, 255))
                    extent = 36
                    crop = overlay.crop((max(0, int(x-extent)), max(0, int(y-extent)),
                                         min(overlay.width, int(x+extent)),
                                         min(overlay.height, int(y+extent))))
                    crop = crop.resize((crop.width * 7, crop.height * 7), Image.Resampling.NEAREST)
                    crop.save(output_dir / f"{name}_intersection_{index}_zoom.png")
    # Compare browser-rendered current fill with the Phase C source label and
    # Shapely's minimal make_valid interpretation around each flagged point.
    for row in invalid:
        shape = next(item for item in geometry.shapes if item.region_id == row["region_id"])
        paths = shape.outer_paths if row["pathKind"] == "outer" else shape.hole_paths
        vector_path = paths[row["pathIndex"] - 1]
        x, y = row["intersectionWorkCanvas"]
        x0, x1 = max(0, int(x) - 20), min(geometry.width, int(x) + 21)
        y0, y1 = max(0, int(y) - 20), min(geometry.height, int(y) + 21)
        source_mask = (phase_c.region_labels == shape.region_id)
        svg_d = _svg_path(vector_path, by_id)
        svg_text = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{geometry.width}" '
                    f'height="{geometry.height}" viewBox="0 0 {geometry.width} {geometry.height}">'
                    f'<path d="{svg_d}" fill="#FFFFFF" fill-rule="evenodd"/></svg>')
        svg_mask = rasterize_svg(svg_text, expected_size=(geometry.height, geometry.width))[..., 3] > 127
        pts = path_points(vector_path, by_id, density=9.0)
        repaired = make_valid(Polygon(pts))
        repaired_mask = np.zeros((geometry.height, geometry.width), dtype=np.uint8)
        geometries = list(repaired.geoms) if hasattr(repaired, "geoms") else [repaired]
        for polygon_part in geometries:
            if polygon_part.geom_type != "Polygon":
                continue
            exterior = np.rint(np.asarray(polygon_part.exterior.coords)).astype(np.int32)
            cv2.fillPoly(repaired_mask, [exterior], 255)
            for interior in polygon_part.interiors:
                hole = np.rint(np.asarray(interior.coords)).astype(np.int32)
                cv2.fillPoly(repaired_mask, [hole], 0)
        repaired_bool = repaired_mask > 127
        roi_source = source_mask[y0:y1, x0:x1]
        roi_svg = svg_mask[y0:y1, x0:x1]
        roi_repaired = repaired_bool[y0:y1, x0:x1]
        row["localRoi"] = [x0, y0, x1, y1]
        row["localSvgSourceDifferencePixels"] = int(np.count_nonzero(roi_svg != roi_source))
        row["localMakeValidSourceDifferencePixels"] = int(np.count_nonzero(roi_repaired != roi_source))
        row["localMakeValidSvgDifferencePixels"] = int(np.count_nonzero(roi_repaired != roi_svg))
        source_holes = _hole_areas(roi_source)
        svg_holes = _hole_areas(roi_svg)
        row["sourceRoiHoleAreasPx"] = source_holes
        row["svgRoiHoleAreasPx"] = svg_holes
        row["sourceSmallHoleCountLe16Px"] = sum(area <= 16 for area in source_holes)
        row["svgSmallHoleCountLe16Px"] = sum(area <= 16 for area in svg_holes)
        row["newSvgSmallHolesLe16Px"] = max(0, row["svgSmallHoleCountLe16Px"] -
                                           row["sourceSmallHoleCountLe16Px"])
        panels = []
        for title, mask in (("Phase C", roi_source), ("Current SVG", roi_svg),
                            ("make_valid", roi_repaired)):
            panel_pixels = np.full((*mask.shape, 3), 255, dtype=np.uint8)
            panel_pixels[mask] = (246, 125, 31)
            panel = Image.fromarray(panel_pixels)
            pen = ImageDraw.Draw(panel)
            pen.text((2, 2), title, fill=(20, 20, 20), stroke_width=1, stroke_fill=(255, 255, 255))
            pen.ellipse((x-x0-2, y-y0-2, x-x0+2, y-y0+2), outline=(230, 20, 30), width=1)
            panels.append(panel.resize((mask.shape[1] * 8, mask.shape[0] * 8), Image.Resampling.NEAREST))
        collage = Image.new("RGB", (sum(panel.width for panel in panels), panels[0].height), "white")
        cursor = 0
        for panel in panels:
            collage.paste(panel, (cursor, 0))
            cursor += panel.width
        collage.save(output_dir / f"{name}_intersection_{row['index']}_fill_comparison.png")
    annotated_path = output_dir / f"{name}_intersections.png"
    overlay.save(annotated_path)
    json_path = output_dir / f"{name}_intersections.json"
    report = {
        "fixture": name,
        "source": str(source_path),
        "mode": mode,
        "sourceSize": list(source_size),
        "workSize": list(work.size),
        "reportedSelfIntersectionCount": geometry.metrics.get("self_intersection_count"),
        "directClosedRingInvalidCount": len(invalid),
        "invalidPaths": invalid,
        "targetedToleranceSweep": sweep_rows,
        "phaseTimingsMs": timings,
        "phaseCRegionCount": phase_c.metrics.get("final_region_count"),
        "phaseD1Metrics": geometry.metrics,
        "annotatedImage": str(annotated_path),
    }
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "fixture", "mode", "sourceSize", "workSize", "reportedSelfIntersectionCount",
        "directClosedRingInvalidCount", "invalidPaths", "phaseTimingsMs", "annotatedImage")},
        indent=2, ensure_ascii=False))
    return report


def main() -> None:
    artifacts = ROOT / "artifacts" / "vector_v2_product"
    fixtures = ROOT / "tests" / "fixtures"
    output = artifacts / "intersections"
    engine = get_process_ocr_engine()
    results = [
        diagnose("active_fox_8x_auto", fixtures / "active_fox_upscaled_8x.png", "auto", output, engine),
        diagnose("jpg_artifacts_fast", artifacts / "fixture_matrix" / "jpg_artifacts.jpg", "fast", output, engine),
    ]
    (output / "diagnostic_report.json").write_text(
        json.dumps({"results": [{k: v for k, v in result.items() if k != "phaseD1Metrics"}
                                for result in results]}, indent=2, ensure_ascii=False),
        encoding="utf-8")


if __name__ == "__main__":
    main()
