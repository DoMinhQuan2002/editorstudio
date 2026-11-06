from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from tools.task_08b_1_1.diagnostics import (  # noqa: E402
    FIXTURE_IDS, assert_native_alignment, boundary_map, ground_truth_label,
    gradient_metrics, matched_boundary_metrics,
)


class Task08B11DiagnosticRunnerTests(unittest.TestCase):
    def test_declared_fixture_set_covers_required_categories(self) -> None:
        self.assertIn("synthetic-circle", FIXTURE_IDS)
        self.assertIn("synthetic-linear_gradient", FIXTURE_IDS)
        self.assertIn("synthetic-radial_gradient", FIXTURE_IDS)
        self.assertIn("synthetic-multiregion_illustration", FIXTURE_IDS)
        self.assertIn("active-fox-native-jpeg", FIXTURE_IDS)

    def test_boundary_precision_recall_on_analytic_edge(self) -> None:
        labels = np.zeros((32, 32), np.uint8)
        labels[:, 16:] = 1
        metrics = matched_boundary_metrics(boundary_map(labels), boundary_map(labels), 2)
        self.assertAlmostEqual(metrics["precisionWithinTolerance"], 1.0)
        self.assertAlmostEqual(metrics["recallWithinTolerance"], 1.0)
        self.assertEqual(metrics["missingBoundaryPixels"], 0)
        self.assertEqual(metrics["falseBoundaryPixels"], 0)
        self.assertEqual(metrics["groundTruthClass"], "ANALYTIC_GROUND_TRUTH")

    def test_proxy_boundary_metric_is_never_labeled_ground_truth(self) -> None:
        labels = np.zeros((20, 20), np.uint8)
        labels[5:15, 5:15] = 1
        metric = matched_boundary_metrics(
            boundary_map(labels), boundary_map(labels), ground_truth_class="REAL_IMAGE_PROXY_NOT_GROUND_TRUTH")
        self.assertEqual(metric["groundTruthClass"], "REAL_IMAGE_PROXY_NOT_GROUND_TRUTH")

    def test_soft_gradient_detects_injected_hard_band_edge(self) -> None:
        x = np.linspace(20, 230, 128, dtype=np.uint8)
        source = np.tile(x[None, :, None], (64, 1, 3))
        roi = np.ones((64, 128), bool)
        smooth = gradient_metrics(source, source.copy(), roi)
        banded = source.copy()
        banded[:, 64:] = np.clip(banded[:, 64:].astype(np.int16) + 36, 0, 255).astype(np.uint8)
        band = gradient_metrics(source, banded, roi)
        self.assertEqual(smooth["falseHardEdgePixels"], 0)
        self.assertGreater(band["falseHardEdgePixels"], 0)

    def test_ground_truth_vs_proxy_labels_are_explicit(self) -> None:
        self.assertTrue(ground_truth_label("synthetic-circle")["isGroundTruth"])
        active = ground_truth_label("active-fox-native-jpeg")
        self.assertFalse(active["isGroundTruth"])
        self.assertEqual(active["humanReview"], "NEEDS_HUMAN_REVIEW")

    def test_native_coordinate_alignment_rejects_resized_render(self) -> None:
        source = np.zeros((20, 30, 4), np.uint8)
        render = np.zeros_like(source)
        assert_native_alignment(source, render)
        with self.assertRaises(ValueError):
            assert_native_alignment(source, np.zeros((30, 20, 4), np.uint8))

    def test_task_implementation_files_stay_outside_production_packages(self) -> None:
        diagnostic = (BACKEND / "tools" / "task_08b_1_1" / "diagnostics.py").resolve()
        test_file = Path(__file__).resolve()
        self.assertTrue(diagnostic.is_relative_to(BACKEND / "tools" / "task_08b_1_1"))
        self.assertTrue(test_file.is_relative_to(BACKEND / "tests"))
        self.assertFalse((BACKEND / "mediastudio" / "image_tools" / "vectorization_v2" / "diagnostics.py").exists())


if __name__ == "__main__":
    unittest.main()
