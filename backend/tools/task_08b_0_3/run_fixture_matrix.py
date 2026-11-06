from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[2]
TARGET = BACKEND / "artifacts" / "contour_preserving" / "task_08b_0_3"
sys.path.insert(0, str(BACKEND))
os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
os.environ["DEBUG_VECTOR"] = "0"

from mediastudio.image_tools import vectorization_contour  # noqa: E402
from tools.task_08a_1.dataset import BASE_MANIFEST, write_json  # noqa: E402
from tools.vectorization_benchmark.worker import run_image  # noqa: E402


FIXTURES = (
    "synthetic-multiregion_illustration",
    "synthetic-thin_line",
    "synthetic-tapered_curve",
    "synthetic-narrow_highlight_near_boundary",
    "synthetic-small_colored_island",
    "active-fox-native-jpeg",
)


def main() -> int:
    manifest = json.loads(BASE_MANIFEST.read_text(encoding="utf-8"))
    items = {row["imageId"]: row for row in manifest["items"]}
    results: list[dict[str, Any]] = []
    original_fit = vectorization_contour.fit_bezier_topology

    for image_id in FIXTURES:
        graphs = []

        def fit_capture(*args: Any, **kwargs: Any):
            graph = original_fit(*args, **kwargs)
            graphs.append(graph)
            return graph

        run_id = f"task08b0_3_{image_id.replace('-', '_')}"
        with patch.object(vectorization_contour, "fit_bezier_topology",
                          side_effect=fit_capture):
            record = run_image(items[image_id], TARGET, per_engine_timeout=900,
                               run_id=run_id)

        contour = record.get("engines", {}).get("contour_preserving", {})
        smart = record.get("engines", {}).get("smart_reconstruction", {})
        graph = graphs[0] if graphs else None
        thin_rows = []
        if graph is not None:
            thin_rows = [
                {key: row[key] for key in
                 ("region_id", "estimated_width_px", "raw_raster_area",
                  "bezier_raster_area", "iou", "relative_area_error")}
                for row in graph.metrics.get("regions", [])
                if row.get("estimated_width_px", float("inf")) <= 2.0
            ]
        metadata = contour.get("actualConfiguration", {}).get("engineMetadata", {})
        geometry_summary = metadata.get("geometry", {})
        results.append({
            "imageId": image_id,
            "sourceSha256": record.get("sourceSha256"),
            "contourJobStatus": contour.get("status", "FAILED"),
            "contourFailureCode": contour.get("failureCode"),
            "contourFailureReason": contour.get("failureReason"),
            "contourSvgValidation": contour.get("svgValidation"),
            "contourRendererStatus": contour.get("skiaRendererCheck", {}).get("status"),
            "contourGeometryValid": bool(graph and graph.geometry_valid),
            "contourValidation": (graph.validation.__dict__ if graph else None),
            "thinFeatures": thin_rows,
            "thinFeatureMinIoU": geometry_summary.get("thin_feature_min_iou"),
            "smartV2JobStatus": smart.get("status", "FAILED"),
            "smartV2FailureCode": smart.get("failureCode"),
            "workerOverallStatus": record.get("status"),
            "runId": run_id,
        })
        write_json(TARGET / "thin_feature_regression.json", {
            "schemaVersion": 1,
            "fixtureIds": list(FIXTURES),
            "itemsCompleted": len(results),
            "items": results,
        })
        print(f"{image_id}: contour={contour.get('status')} "
              f"thinMinIoU={geometry_summary.get('thin_feature_min_iou')}")

    all_contour_pass = all(row["contourJobStatus"] == "SUCCEEDED" and
                           row["contourGeometryValid"] and
                           (row["thinFeatureMinIoU"] is None or
                            row["thinFeatureMinIoU"] >= 0.80) and
                           row["contourSvgValidation"] and
                           row["contourSvgValidation"].get("status") == "PASS" and
                           row["contourRendererStatus"] == "PASS"
                           for row in results)
    return 0 if all_contour_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
