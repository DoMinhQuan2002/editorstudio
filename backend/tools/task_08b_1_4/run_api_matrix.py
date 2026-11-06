from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

BACKEND = Path(__file__).resolve().parents[2]
ARTIFACTS = BACKEND / "artifacts/contour_preserving/task_08b_1_4"
TASK13 = BACKEND / "artifacts/contour_preserving/task_08b_1_3"
sys.path.insert(0, str(BACKEND))

CURRENT = {"runId": None, "imageId": None}


def _json_write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _hash_json(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _feature_row(feature: object) -> dict:
    rings = []
    for ring in getattr(feature, "contours_processing", ()):
        rings.append([[float(x), float(y)] for x, y in ring])
    xs = [point[0] for ring in rings for point in ring]
    ys = [point[1] for ring in rings for point in ring]
    return {
        "id": feature.id, "parentRegionId": int(feature.parent_region_id),
        "bboxProcessing": [min(xs), min(ys), max(xs), max(ys)] if xs else None,
        "maskAreaPixels": int(feature.area_px), "paintModel": "flat fill",
        "colorRGB": list(feature.color_rgb), "opacity": float(feature.opacity),
        "localContrastDeltaE00": float(feature.local_contrast_delta_e00),
        "edgeSupport": float(feature.edge_support), "confidence": float(feature.confidence),
        "sourceRegionId": int(feature.source_region_id), "clippedToRegionId": int(feature.clipped_to_region_id),
        "contoursProcessing": rings,
    }


def _capture_segmentation(result: object) -> None:
    import numpy as np
    labels = np.asarray(result.label_map)
    summary = {"labelMapSha256": hashlib.sha256(labels.tobytes()).hexdigest(),
               "shape": list(labels.shape), "regions": [
                   {"id": int(r.id), "area": int(r.area), "bbox": list(r.bbox),
                    "classification": str(r.classification), "confidence": float(r.confidence),
                    "gradientLikelihood": float(r.gradient_likelihood)} for r in result.regions],
               "metrics": result.metrics}
    summary["snapshotSha256"] = _hash_json(summary)
    _json_write(_capture_dir() / "segmentation.json", summary)


def _capture_topology(graph: object) -> None:
    rows = []
    for item in graph.interfaces:
        rows.append({"id": str(item.id), "left": int(item.region_left), "right": int(item.region_right),
                     "shared": bool(item.shared), "unitSegmentCount": int(item.unit_segment_count),
                     "confidence": float(item.confidence),
                     "pointsSource": [[float(x), float(y)] for x, y in graph.interface_points(item.id, source=True)]})
    data = {"sourceSize": list(graph.source_size), "processingSize": list(graph.processing_size),
            "valid": bool(graph.geometry_valid), "sharedInterfaceCount": int(graph.shared_interface_count),
            "interfaces": rows, "metrics": graph.metrics}
    data["snapshotSha256"] = _hash_json(data)
    _json_write(_capture_dir() / "topology.json", data)


def _capture_geometry(graph: object) -> None:
    rows = []
    for item in graph.interfaces:
        segments = []
        for segment in item.segments:
            segments.append({name: [float(x) for x in getattr(segment, name)]
                             for name in ("p0", "c1", "c2", "p3")})
        rows.append({"id": str(item.id), "left": int(item.region_left), "right": int(item.region_right),
                     "segments": segments, "fitTolerance": float(item.fit_tolerance),
                     "meanBoundaryError": float(item.mean_boundary_error),
                     "p95BoundaryError": float(item.p95_boundary_error)})
    data = {"sourceSize": list(graph.source_size), "processingSize": list(graph.processing_size),
            "valid": bool(graph.geometry_valid), "interfaces": rows, "metrics": graph.metrics,
            "validation": graph.validation.__dict__}
    data["snapshotSha256"] = _hash_json(data)
    _json_write(_capture_dir() / "bezier_geometry.json", data)


def _capture_appearance(graph: object) -> None:
    rows = []
    for region in graph.regions:
        gradient = region.gradient
        rows.append({"regionId": int(region.region_id), "paintKind": region.paint_kind,
            "colorRGB": list(region.color_rgb), "opacity": float(region.opacity),
            "selectedMeanDeltaE00": float(region.selected_mean_delta_e00),
            "selectedP95DeltaE00": float(region.selected_p95_delta_e00),
            "gradient": None if gradient is None else {
                "kind": gradient.kind, "geometrySourceXY": list(gradient.geometry_source_xy),
                "stops": [{"offset": float(stop.offset), "colorRGB": list(stop.color_rgb), "opacity": float(stop.opacity)} for stop in gradient.stops]},
            "internalFeatures": [_feature_row(feature) for feature in region.internal_features]})
    data = {"metrics": graph.metrics, "regions": rows}
    data["snapshotSha256"] = _hash_json(data)
    _json_write(_capture_dir() / "appearance.json", data)


def _capture_dir() -> Path:
    return ARTIFACTS / "stage_captures" / str(CURRENT["runId"]) / str(CURRENT["imageId"])


def install_hooks() -> None:
    import mediastudio.image_tools.vectorization_contour as contour
    for name, capture in (("run_contour_segmentation", _capture_segmentation),
                          ("extract_contour_topology", _capture_topology),
                          ("fit_bezier_topology", _capture_geometry),
                          ("build_contour_appearance_graph", _capture_appearance)):
        original = getattr(contour, name)
        if getattr(original, "_task_0814_wrapper", False):
            continue
        def make_wrapper(fn, cap):
            def wrapper(*args, **kwargs):
                result = fn(*args, **kwargs)
                cap(result)
                return result
            wrapper._task_0814_wrapper = True
            return wrapper
        setattr(contour, name, make_wrapper(original, capture))


def _items() -> dict[str, dict]:
    from tools.vectorization_benchmark.dataset import MANIFEST_PATH
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    result = {item["imageId"]: dict(item) for item in manifest["items"]}
    for fid in ("smooth_nonlinear_gradient", "hard_boundary_with_gradient", "low_contrast_multistop_gradient"):
        path = TASK13 / f"item_{fid}.json"
        item = json.loads(path.read_text(encoding="utf-8"))
        item["path"] = str((TASK13 / item["path"]).resolve()) if not Path(item["path"]).is_absolute() else item["path"]
        result[fid] = item
    variants = json.loads((ARTIFACTS / "controlled_variants.json").read_text(encoding="utf-8"))
    for row in variants["variants"]:
        base = ARTIFACTS / row["paths"]["source"]
        item = {"imageId": row["fixtureId"], "sourceFamilyId": row["fixtureId"],
                "path": str(base.resolve()), "sha256": row["sourceSha256"],
                "sourceType": "synthetic_analytic", "categories": ["analytic_gradient_fixture"],
                "referenceType": "analytic_ground_truth", "hasTypography": False,
                "referenceFiles": {"analyticAlphaMaskPath": str((ARTIFACTS / row["paths"]["alpha"]).resolve()),
                    "semanticLabelMapPath": str((ARTIFACTS / row["paths"]["semanticLabels"]).resolve())}}
        result[row["fixtureId"]] = item
    return result


def run(stage: str, ids: list[str]) -> dict:
    os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
    os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
    os.environ["DEBUG_VECTOR"] = "0"
    install_hooks()
    from tools.vectorization_benchmark.dataset import write_json
    from tools.vectorization_benchmark.worker import run_image
    items = _items()
    run_id = f"task08b1_4_{stage}"
    results = []
    for index, image_id in enumerate(ids):
        if image_id not in items:
            raise ValueError(f"unknown regression fixture id: {image_id}")
        item = dict(items[image_id])
        item["benchmarkOrderIndex"] = index
        CURRENT.update({"runId": run_id, "imageId": image_id})
        print(f"[{stage}] API {image_id}", flush=True)
        result = run_image(item, ARTIFACTS, per_engine_timeout=900, run_id=run_id)
        results.append({"imageId": image_id, "sourceSha256": item["sha256"], "result": result})
        print(json.dumps({"imageId": image_id, "status": result.get("status"),
            "contour": result.get("engines", {}).get("contour_preserving", {}).get("status"),
            "smart": result.get("engines", {}).get("smart_reconstruction", {}).get("status")}, ensure_ascii=False), flush=True)
    output = {"task": "08B.1.4", "stage": stage, "runId": run_id, "results": results,
              "allApiRunsPassed": all(row["result"].get("status") == "PASS" for row in results)}
    write_json(ARTIFACTS / f"api_{stage}.json", output)
    CURRENT.update({"runId": None, "imageId": None})
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("baseline", "candidate"))
    parser.add_argument("ids", nargs="+")
    args = parser.parse_args()
    run(args.stage, args.ids)
