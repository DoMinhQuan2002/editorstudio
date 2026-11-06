from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from types import SimpleNamespace

from shapely import from_wkb
from shapely.errors import GEOSException
from shapely.geometry import box

from mediastudio.image_tools.vectorization_v2.phase_d import _measure_shared_polygon_overlap
from mediastudio.image_tools.vectorization_v2 import production


BACKEND = Path(__file__).resolve().parents[1]
ARTIFACTS_0804 = BACKEND / "artifacts/contour_preserving/task_08b_0_4"


class Task08B05GEOSMetricSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.minimal = json.loads(
            (ARTIFACTS_0804 / "minimal_reproduction.json").read_text(encoding="utf-8")
        )

    def test_exact_wkb_pair_is_unavailable_without_aborting_on_invalid_r14(self) -> None:
        operands = self.minimal["operands"]
        r02 = from_wkb(Path(operands["R02"]["wkbPath"]).read_bytes())
        r14 = from_wkb(Path(operands["R14"]["wkbPath"]).read_bytes())

        with self.assertRaises(GEOSException):
            r02.intersection(r14)

        area, failure = _measure_shared_polygon_overlap(
            r02, r14, boundary_id="S19", region_a=2, region_b=14
        )
        self.assertIsNone(area)
        self.assertEqual(failure["status"], "unavailable_invalid_input")
        self.assertEqual(failure["boundary_id"], "S19")
        self.assertEqual(failure["region_a"], 2)
        self.assertEqual(failure["region_b"], 14)
        self.assertEqual(failure["invalid_operands"], [{
            "region_id": 14,
            "reason": operands["R14"]["validityReason"],
        }])
        control_config = self.minimal["validControl"]
        control = box(272.5, 198.5, 274.5, 200.5)
        expected_control_area = float(r02.intersection(control).area)
        control_area, control_failure = _measure_shared_polygon_overlap(
            r02, control, boundary_id="S-control", region_a=2, region_b=-1
        )
        self.assertIsNone(control_failure)
        self.assertEqual(control_area, expected_control_area)
        self.assertEqual(control_area, control_config["resultArea"])

    def test_valid_polygon_metric_is_numerically_unchanged(self) -> None:
        left = box(0.0, 0.0, 2.0, 2.0)
        right = box(1.0, 0.0, 3.0, 2.0)
        expected = float(left.intersection(right).area)

        area, failure = _measure_shared_polygon_overlap(
            left, right, boundary_id="S-test", region_a=1, region_b=2
        )
        self.assertIsNone(failure)
        self.assertEqual(area, expected)
        self.assertEqual(area, 2.0)

    def test_geos_exception_on_valid_operands_is_reported_as_unavailable(self) -> None:
        left = Mock(is_valid=True)
        right = Mock(is_valid=True)
        left.intersection.side_effect = GEOSException("synthetic overlay failure")

        area, failure = _measure_shared_polygon_overlap(
            left, right, boundary_id="S-test", region_a=1, region_b=2
        )
        self.assertIsNone(area)
        self.assertEqual(failure["status"], "unavailable_geos_exception")
        self.assertIn("synthetic overlay failure", failure["reason"])

    def test_missing_metric_operand_is_not_coerced_to_zero(self) -> None:
        area, failure = _measure_shared_polygon_overlap(
            box(0.0, 0.0, 1.0, 1.0), None,
            boundary_id="S-missing", region_a=1, region_b=2,
        )
        self.assertIsNone(area)
        self.assertEqual(failure["status"], "unavailable_missing_operand")

    def test_invalid_or_unavailable_final_geometry_blocks_svg_composition(self) -> None:
        phase_a = SimpleNamespace(warnings=[], metrics={})
        phase_b = SimpleNamespace(warnings=[], metrics={}, ocr_status="OCR_READY")
        phase_c = SimpleNamespace(warnings=[], metrics={})
        cases = (
            {"self_intersection_count": 1, "final_geometry_validation": {
                "valid": False, "invalid_region_ids": [14],
                "invalid_rings": [{"region_id": 14, "ring_kind": "outer",
                                   "reason": "Self-intersection[test]"}],
            }},
            {"self_intersection_count": 0},
        )
        for geometry_metrics in cases:
            with self.subTest(geometry_metrics=geometry_metrics):
                geometry = SimpleNamespace(metrics=geometry_metrics, warnings=[])
                with tempfile.TemporaryDirectory(prefix="task08b05-invalid-geometry-") as temp:
                    output = Path(temp) / "must_not_be_written.svg"
                    output.write_text("stale output from a previous run", encoding="utf-8")
                    with (
                        unittest.mock.patch.dict(os.environ, {"DEBUG_VECTOR": "0"}),
                        unittest.mock.patch.object(production, "run_phase_a", return_value=phase_a),
                        unittest.mock.patch.object(production, "get_process_ocr_engine", return_value=object()),
                        unittest.mock.patch.object(production, "run_phase_b", return_value=phase_b),
                        unittest.mock.patch.object(production, "run_phase_c", return_value=phase_c),
                        unittest.mock.patch.object(production, "run_phase_d1", return_value=geometry),
                        unittest.mock.patch.object(production, "run_phase_e1") as phase_e1,
                        unittest.mock.patch.object(production, "compose_production_svg") as compose_svg,
                    ):
                        with self.assertRaisesRegex(production.VectorizationV2Error,
                                                    "SVG composition was blocked"):
                            production.run_vectorization_v2(
                                ARTIFACTS_0804 / ".." / "task_08a_1" / "acquired" /
                                "scikit_image" / "camera.png",
                                output,
                                models_directory=Path(temp) / "models",
                            )
                    self.assertFalse(output.exists())
                    phase_e1.assert_not_called()
                    compose_svg.assert_not_called()


if __name__ == "__main__":
    unittest.main()
