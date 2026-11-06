from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from .dataset import ARTIFACTS, BACKEND, BASE_MANIFEST, REPOSITORY, write_json


def main() -> int:
    sys.path.insert(0, str(BACKEND))
    os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
    os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
    os.environ["DEBUG_VECTOR"] = "0"
    from mediastudio.image_tools import contour_backend, vectorization_contour
    from mediastudio.image_tools.vectorization_contour import bezier as bezier_module
    from tools.vectorization_benchmark.worker import run_image

    old = json.loads(BASE_MANIFEST.read_text(encoding="utf-8"))
    item = next(i for i in old["items"] if i["imageId"] == "synthetic-multiregion_illustration")
    capture: dict[str, Any] = {"imageId": item["imageId"], "requestedMethod": "contour_preserving",
        "sourceSha256": item["sha256"], "runConfig": {"engine": "auto", "mode": "auto", "text_mode": "outlined",
        "transparent_background": True, "smooth_paths": True, "color_count": None, "simplification": None,
        "vector_method": "contour_preserving"}}
    original_fit = vectorization_contour.fit_bezier_topology
    original_error = contour_backend.ContourBackendError

    def fit_wrapper(*args: Any, **kwargs: Any) -> Any:
        graph = original_fit(*args, **kwargs)
        if not graph.geometry_valid:
            raster = bezier_module._raster_metrics(graph)
            capture["bezierResult"] = {"valid": graph.geometry_valid, "validation": {
                "checks": graph.validation.checks, "errors": graph.validation.errors,
                "invalidLoopIds": graph.validation.invalid_loop_ids,
                "selfIntersectionCount": graph.validation.self_intersection_count,
                "sharedBoundaryMismatchCount": graph.validation.shared_boundary_mismatch_count,
                "sharedOverlapPixels": graph.validation.shared_overlap_pixels,
                "silhouetteGapPixels": graph.validation.silhouette_gap_pixels},
                "metrics": graph.metrics, "interfaceCount": len(graph.interfaces),
                "regionIds": sorted(graph.faces), "fitCallStack": traceback.format_stack(limit=12),
                "thinFeatureRasterMetrics": {"thinRegionIds": raster["thin_region_ids"],
                    "thinFeatureMinIoU": raster["thin_feature_min_iou"],
                    "perFace": raster["per_face"]}}
        return graph

    class CapturedContourError(original_error):
        def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
            capture.setdefault("raisedError", {"code": code, "message": message,
                "details": details or {}, "raiseStack": traceback.format_stack(limit=16)})
            super().__init__(code, message, details=details)

    vectorization_contour.fit_bezier_topology = fit_wrapper
    contour_backend.ContourBackendError = CapturedContourError
    run_id = "task08a1-geometry-repro"
    try:
        record = run_image(item, ARTIFACTS, per_engine_timeout=900, run_id=run_id)
        capture["workerRecord"] = {"status": record.get("status"), "engines": record.get("engines", {})}
    except BaseException as exc:
        capture["uncaught"] = {"type": type(exc).__name__, "message": str(exc), "stack": traceback.format_exc()}
    finally:
        vectorization_contour.fit_bezier_topology = original_fit
        contour_backend.ContourBackendError = original_error
    error = capture.get("raisedError", {})
    details = error.get("details", {})
    codes = {row.get("code") for row in details.get("errors", []) if isinstance(row, dict)}
    # Task08A stored the same API validation code; exact reproduction must still be backed by this run's capture.
    reproduced = error.get("code") == "CONTOUR_GEOMETRY_INVALID" or "CONTOUR_GEOMETRY_INVALID" in str(capture.get("workerRecord", {}))
    stage = "bezier_geometry_validation" if reproduced else "UNKNOWN"
    result = {"status": "PASS" if reproduced else "NOT_REPRODUCED", "reproduced": reproduced,
        "firstFailingStage": stage, "firstFailingStageVerified": bool(reproduced and capture.get("bezierResult")),
        "confidence": "VERIFIED" if reproduced and capture.get("bezierResult") else "UNKNOWN",
        "underlyingIssue": "CONTOUR_GEOMETRY_INVALID", "deduplicatedWrapperFailure": True,
        "sourceFamily": item.get("sourceFamilyId"), "sourceSha256": item.get("sha256"),
        "errorCodes": sorted(codes), "capture": capture,
        "proposedMinimalRepair": "Use the captured thin-region/face evidence to constrain any future Task 08B change to the offending local interface or validator condition; do not implement here.",
        "productionCodeChanged": False}
    path = ARTIFACTS / "geometry_failure_reproduction.json"
    result["artifactPath"] = path.relative_to(ARTIFACTS).as_posix()
    write_json(path, result)
    (ARTIFACTS / "phase_diagnostics").mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "phase_diagnostics" / "geometry_reproduction_stack.txt").write_text(
        "\n".join(capture.get("raisedError", {}).get("raiseStack", [])) or "No geometry exception stack captured.\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "reproduced": reproduced, "stage": stage,
                      "errorCodes": result["errorCodes"], "artifact": str(path)}, indent=2))
    return 0 if reproduced else 2


if __name__ == "__main__":
    raise SystemExit(main())
