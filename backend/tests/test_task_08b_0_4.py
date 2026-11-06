from __future__ import annotations

import json
from pathlib import Path
import unittest

from shapely import from_wkb
from shapely.errors import GEOSException
from shapely.geometry import box
from shapely.validation import explain_validity

BACKEND = Path(__file__).resolve().parents[1]
ARTIFACTS = BACKEND / "artifacts/contour_preserving/task_08b_0_4"


class Task08B04GEOSTopologyIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.reproduction = json.loads((ARTIFACTS / "geos_exception_reproduction.json").read_text(
            encoding="utf-8"))
        cls.minimal = json.loads((ARTIFACTS / "minimal_reproduction.json").read_text(
            encoding="utf-8"))

    def test_three_identical_api_jobs_reproduce_same_geos_failure(self) -> None:
        attempts = self.reproduction["attempts"]
        self.assertEqual(len(attempts), 3)
        self.assertEqual([attempt["state"] for attempt in attempts], ["failed"] * 3)
        errors = [attempt["error"] for attempt in attempts]
        self.assertEqual(len(set(errors)), 1)
        self.assertIn("TopologyException: side location conflict at 273.3869747027037 199.02301419964235",
                      errors[0])
        self.assertEqual(self.reproduction["fixture"]["sha256Expected"],
                         "b0793d2adda0fa6ae899c03989482bff9a42d3d5690fc7e3648f2795d730c23a")
        self.assertTrue(self.reproduction["fixture"]["hashMatchesManifest"])

    def test_failure_is_polygon_intersection_with_invalid_r14(self) -> None:
        self.assertEqual(self.minimal["operation"], "Polygon.intersection(R02, R14)")
        self.assertEqual(self.minimal["regionPair"]["regionA"], 2)
        self.assertEqual(self.minimal["regionPair"]["regionB"], 14)
        self.assertEqual(self.minimal["regionPair"]["sharedBoundary"]["id"], "S19")
        self.assertEqual(self.minimal["operands"]["R02"]["isValid"], True)
        self.assertEqual(self.minimal["operands"]["R14"]["isValid"], False)
        self.assertIn("Self-intersection", self.minimal["operands"]["R14"]["validityReason"])
        crossings = self.minimal["operands"]["R14"]["selfIntersectionNearReportedPoint"]
        self.assertEqual(len(crossings), 1)
        self.assertTrue(crossings[0]["interiorToBothSegments"])

    def test_exact_wkb_reproduces_exception_and_valid_control_succeeds(self) -> None:
        r02 = from_wkb(Path(self.minimal["operands"]["R02"]["wkbPath"]).read_bytes())
        r14 = from_wkb(Path(self.minimal["operands"]["R14"]["wkbPath"]).read_bytes())
        with self.assertRaisesRegex(GEOSException, "side location conflict"):
            r02.intersection(r14)
        control = box(272.5, 198.5, 274.5, 200.5)
        result = r02.intersection(control)
        self.assertTrue(control.is_valid)
        self.assertTrue(result.is_valid)
        self.assertTrue(self.minimal["validControl"]["succeeded"])
        self.assertEqual(explain_validity(r14), self.minimal["operands"]["R14"]["validityReason"])


if __name__ == "__main__":
    unittest.main()
