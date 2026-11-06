from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from mediastudio.image_tools import vectorization_contour  # noqa: E402
from tools.task_08a_1.dataset import BASE_MANIFEST  # noqa: E402
from tools.vectorization_benchmark.worker import run_image  # noqa: E402


class Task08B03ThinFeatureRegressionTests(unittest.TestCase):
    def test_multiregion_thin_face_uses_shared_local_fallback_and_api_succeeds(self) -> None:
        manifest = json.loads(BASE_MANIFEST.read_text(encoding="utf-8"))
        item = next(row for row in manifest["items"]
                    if row["imageId"] == "synthetic-multiregion_illustration")
        original_fit = vectorization_contour.fit_bezier_topology
        fitted_graphs = []

        def fit_capture(*args, **kwargs):
            graph = original_fit(*args, **kwargs)
            fitted_graphs.append(graph)
            return graph

        with tempfile.TemporaryDirectory(prefix="task08b03-") as temp:
            with patch.dict(os.environ, {
                    "MEDIASTUDIO_CONTOUR_EXPERIMENTAL": "1",
                    "MEDIASTUDIO_VECTORIZE_PIPELINE": "v2",
                    "DEBUG_VECTOR": "0",
            }), patch.object(vectorization_contour, "fit_bezier_topology",
                             side_effect=fit_capture):
                record = run_image(item, Path(temp), per_engine_timeout=900,
                                   run_id="task08b0_3_thin_feature")

        contour = record["engines"]["contour_preserving"]
        self.assertEqual(contour["status"], "SUCCEEDED")
        self.assertEqual(contour["actualMethod"], "contour_preserving")
        self.assertTrue(contour["svgValidation"]["checks"]["noEmbeddedRaster"])
        self.assertEqual(contour["svgValidation"]["status"], "PASS")

        self.assertEqual(len(fitted_graphs), 1)
        graph = fitted_graphs[0]
        self.assertTrue(graph.geometry_valid, graph.validation.errors)
        self.assertEqual(graph.validation.self_intersection_count, 0)
        self.assertEqual(graph.validation.shared_boundary_mismatch_count, 0)
        self.assertEqual(graph.validation.shared_overlap_pixels, 0)
        self.assertEqual(graph.validation.silhouette_gap_pixels, 0)

        regions = {row["region_id"]: row for row in graph.metrics["regions"]}
        self.assertGreaterEqual(regions[12]["iou"], 0.80)
        self.assertEqual(regions[12]["raw_raster_area"], 18)
        self.assertEqual(regions[12]["bezier_raster_area"], 18)
        self.assertEqual(regions[12]["iou"], 1.0)
        for region_id in (9, 10, 11, 13, 14, 15):
            self.assertGreaterEqual(regions[region_id]["iou"], 1.0)

        repaired_interfaces = [interface for interface in graph.interfaces
                               if interface.rollback_reason == "thin_feature_coverage_guard"]
        self.assertEqual(len(repaired_interfaces), 1)
        interface = repaired_interfaces[0]
        self.assertTrue(interface.shared)
        self.assertIn(12, (interface.region_left, interface.region_right))
        self.assertEqual(interface.rollback_reason, "thin_feature_coverage_guard")
        self.assertTrue(all(segment.segment_type == "line"
                            for segment in interface.segments))

    def test_production_geometry_source_matches_scoped_task_patch(self) -> None:
        import hashlib

        artifact_root = BACKEND / "artifacts" / "contour_preserving" / "task_08b_0_3"
        production = json.loads((artifact_root / "production_changes.json").read_text(
            encoding="utf-8"))
        source_path = BACKEND / "mediastudio" / "image_tools" / "vectorization_contour" / "bezier.py"
        source = source_path.read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(),
                         production["bezierSource"]["postTask08B03Sha256"])

        # The Task 07.2 frozen manifest predates intervening approved contour
        # geometry work. This task keeps its own reconstructed task-start source
        # snapshot so later edits to this actively maintained module are caught.
        reconstructed = (artifact_root / production["bezierSource"][
            "preTask08B03SnapshotFile"]).read_bytes()
        self.assertEqual(hashlib.sha256(reconstructed).hexdigest(),
                         production["bezierSource"][
                             "preTask08B03Sha256ReconstructedFromTaskPatch"])
        from tools.task_08b_0_3.finalize_artifacts import _pre_task_bezier_source
        normalized = _pre_task_bezier_source(source.decode("utf-8")).encode("utf-8")
        self.assertEqual(normalized, reconstructed)


if __name__ == "__main__":
    unittest.main()
