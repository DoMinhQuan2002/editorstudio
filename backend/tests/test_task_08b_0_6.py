from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND / "tools"))

from task_08b_0_6.profile_performance import (  # noqa: E402
    PerformanceRecorder,
    boundary_ref_transition,
    metric_snapshot,
)


class Task08B06ProfilerTests(unittest.TestCase):
    def test_monotonic_wrapper_records_call_count_and_elapsed_time(self) -> None:
        recorder = PerformanceRecorder()
        recorder.reset("unit")
        owner = SimpleNamespace(add=lambda value: value + 1)
        recorder.wrap(owner, "add", "unit.add")
        self.assertEqual(owner.add(4), 5)
        self.assertEqual(owner.add(8), 9)
        row = recorder.stage_stats["unit.add"]
        self.assertEqual(row["calls"], 2)
        self.assertGreaterEqual(row["total_ms"], 0.0)
        recorder.restore()

    def test_retry_boundary_transition_identifies_persistent_new_and_removed_refs(self) -> None:
        before = [
            {"boundary_id": "S01", "component_index": 0},
            {"boundary_id": "S02", "component_index": 1},
        ]
        after = [
            {"boundary_id": "S01", "component_index": 0},
            {"boundary_id": "S03", "component_index": None},
        ]
        self.assertEqual(boundary_ref_transition(before, after), {
            "persistent": [["S01", 0]],
            "new": [["S03", None]],
            "removed": [["S02", 1]],
        })
        self.assertIsNone(boundary_ref_transition(None, after))

    def test_metric_snapshot_preserves_geometry_and_per_region_counts(self) -> None:
        result = metric_snapshot({
            "self_intersection_count": 3,
            "silhouette_iou": 0.98,
            "shared_boundary_count": 12,
            "shared_boundary_mismatch_count": 0,
            "per_region": {
                "shape-a": {"region_id": 1, "self_intersection_count": 2},
                "shape-b": {"region_id": 2, "self_intersection_count": 1},
            },
            "shared_interface_overlap_area_failures": [{"status": "unavailable"}],
        })
        self.assertEqual(result["self_intersection_count"], 3)
        self.assertEqual(result["per_region_invalid_ring_counts"], {"1": 2, "2": 1})
        self.assertEqual(result["shared_interface_overlap_failure_count"], 1)


if __name__ == "__main__":
    unittest.main()
