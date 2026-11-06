from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from tools.task_08a_1.dataset import ARTIFACTS, MANIFEST, build_manifest, hamming, validate_manifest
from tools.task_08a_1.review import SCORES, validate_review_csv
from tools.task_08a_1.typography import typography_metrics
from tools.task_08a_1.defects import _failure_class, _labels


class DatasetWorkflowTests(unittest.TestCase):
    def test_task08a_1_dataset_hash_provenance_and_families_validate(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.is_file() else build_manifest()
        report = validate_manifest(manifest)
        self.assertEqual(report["status"], "PASS", report)
        self.assertGreaterEqual(report["independentRealImageCount"], 8)
        self.assertFalse(report["DATASET_COVERAGE_SUFFICIENT"])

    def test_near_duplicate_distance_is_stable(self) -> None:
        self.assertEqual(hamming("0000000000000000", "0000000000000001"), 1)
        self.assertEqual(hamming("ffffffffffffffff", "0000000000000000"), 64)

    def test_same_source_family_variants_do_not_inflate_family_count(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.is_file() else build_manifest()
        fox = [x for x in manifest["items"] if x["sourceFamilyId"] == "active-fox-family"]
        self.assertGreaterEqual(len(fox), 2)
        self.assertEqual(len({x["datasetSplit"] for x in fox}), 1)
        self.assertEqual(len({x["sourceFamilyId"] for x in fox}), 1)


class TypographyMetricTests(unittest.TestCase):
    def test_identical_masks_score_perfect_iou_and_zero_cer(self) -> None:
        mask = np.zeros((50, 100), dtype=np.uint8); mask[10:40, 20:80] = 255
        metrics = typography_metrics(mask, mask, "ACTIVE FOX", "ACTIVE FOX")
        self.assertEqual(metrics["glyphMaskIoU"], 1.0)
        self.assertEqual(metrics["characterErrorRate"], 0.0)

    def test_missing_glyph_and_shift_are_measured(self) -> None:
        ref = np.zeros((80, 120), dtype=np.uint8); ref[10:70, 20:100] = 255
        shifted = np.zeros_like(ref); shifted[:, 3:] = ref[:, :-3]; shifted[10:70, 80:100] = 0
        metrics = typography_metrics(ref, shifted, "FOX", "FO")
        self.assertLess(metrics["glyphMaskIoU"], 1.0)
        self.assertGreater(metrics["glyphBoundaryMeanSymmetricDistancePx"], 0)
        self.assertAlmostEqual(metrics["characterErrorRate"], 1 / 3)

    def test_counter_preservation_detects_hole_difference(self) -> None:
        ref = np.zeros((60, 60), dtype=np.uint8); ref[5:55, 5:55] = 255; ref[20:40, 20:40] = 0
        no_counter = ref.copy(); no_counter[20:40, 20:40] = 255
        metrics = typography_metrics(ref, no_counter, "O", "O")
        self.assertEqual(metrics["counterCountReference"], 1)
        self.assertEqual(metrics["counterCountCandidate"], 0)

    def test_layout_and_stroke_metrics_are_present(self) -> None:
        mask = np.zeros((50, 100), dtype=np.uint8); mask[10:40, 20:80] = 255
        metrics = typography_metrics(mask, mask, "X", "X")
        self.assertEqual(metrics["layout"]["baselineDeltaPx"], 0)
        self.assertEqual(metrics["layout"]["referenceGlyphBBox"], [20, 10, 80, 40])
        self.assertIsNotNone(metrics["referenceStrokeWidthMedianPx"])


class ReviewSchemaTests(unittest.TestCase):
    def test_blank_template_schema_has_score_fields(self) -> None:
        self.assertEqual(len(SCORES), 7)

    def test_review_import_requires_scores_in_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.csv"
            fields = ["image_id", "source_family_id", "output_alias", *SCORES, "defect_labels", "reviewer_id", "reviewer_comment", "reviewed_at_utc"]
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
                row = {key: "" for key in fields}; row.update({"image_id": "x", "source_family_id": "f", "output_alias": "A", "reviewer_id": "r", "shape_fidelity": "6"}); writer.writerow(row)
            result = validate_review_csv(path)
            self.assertEqual(result["status"], "FAIL")
            self.assertFalse(result["HUMAN_VISUAL_REVIEW_COMPLETE"])

    def test_not_applicable_is_allowed_without_fake_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.csv"
            fields = ["image_id", "source_family_id", "output_alias", *SCORES, "defect_labels", "reviewer_id", "reviewer_comment", "reviewed_at_utc"]
            with path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
                row = {key: "" for key in fields}; row.update({"image_id": "x", "source_family_id": "f", "output_alias": "A", "reviewer_id": "r", "shape_fidelity": "4", "gradient_fidelity": "not_applicable"}); writer.writerow(row)
            result = validate_review_csv(path)
            self.assertEqual(result["status"], "PASS")
            self.assertFalse(result["HUMAN_VISUAL_REVIEW_COMPLETE"])  # needs the full requested set/real reviewer metadata

    def test_visual_defect_labels_need_numeric_evidence_and_allow_multiple(self) -> None:
        labels = _labels({"metrics": {"meanDeltaE00": 8, "p95DeltaE00": 24,
                                      "edgeMismatchFraction": 0.1, "alphaMismatchMean": 0}})
        self.assertIn("GRADIENT_COLOR_MISMATCH", labels)
        self.assertIn("HARD_BOUNDARY_MISMATCH", labels)
        self.assertEqual(_labels({"metrics": {}}), ["UNKNOWN"])

    def test_smart_empty_vector_message_is_classified_as_empty_output(self) -> None:
        self.assertEqual(_failure_class("ENGINE_RUN_FAILURE", "SVG hợp lệ về cú pháp nhưng không tạo được ảnh vector nhìn thấy."),
                         "EMPTY_VISIBLE_SVG_OUTPUT")


if __name__ == "__main__":
    unittest.main()
