from __future__ import annotations

import time
import unittest

import numpy as np

from mediastudio.image_tools.vectorization_v2 import phase_e1
from tools.task_08b_0_7.profile_e1 import E1Profiler, _jsonable


class Task0807ProfilerTests(unittest.TestCase):
    def test_monotonic_timer_reports_calls_and_nested_exclusive_time(self):
        class TimedOperations:
            def inner(self):
                time.sleep(0.008)
                return "unchanged"

            def outer(self):
                time.sleep(0.003)
                return self.inner()

        operations = TimedOperations()
        profiler = E1Profiler()
        profiler.instrument_function(operations, "inner", "inner")
        profiler.instrument_function(operations, "outer", "outer")
        started = time.perf_counter_ns()
        value = operations.outer()
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        profiler.restore()
        report = profiler.report(elapsed_ms)
        by_name = {row["operation"]: row for row in report["operations"]}
        self.assertEqual(value, "unchanged")
        self.assertEqual(by_name["outer"]["calls"], 1)
        self.assertEqual(by_name["inner"]["calls"], 1)
        self.assertGreaterEqual(by_name["inner"]["inclusive_total_ms"], 6)
        self.assertGreater(by_name["outer"]["exclusive_total_ms"], 1)
        self.assertLess(by_name["outer"]["exclusive_total_ms"], by_name["outer"]["inclusive_total_ms"])
        self.assertLessEqual(by_name["outer"]["inclusive_total_ms"], elapsed_ms + 2)

    def test_profiler_smoke_counts_real_e1_gradient_search_calls(self):
        t = np.linspace(0.0, 1.0, 48, dtype=np.float64)
        xy = np.column_stack((t * 30.0, np.sin(t * np.pi) * 4.0))
        rgb = np.column_stack((30 + t * 190, 210 - t * 110, 60 + t * 120))
        weights = np.linspace(0.5, 1.0, len(t), dtype=np.float64)
        profiler = E1Profiler()
        profiler.install()
        try:
            candidate, error, search = phase_e1._linear_candidate_e1(xy, rgb, weights)
            report = profiler.report(1000.0)
        finally:
            profiler.restore()
        rows = {row["operation"]: row for row in report["operations"]}
        self.assertIsNotNone(candidate)
        self.assertIsNotNone(error)
        self.assertGreater(len(search), 0)
        self.assertEqual(rows["E1._linear_candidate_e1"]["calls"], 1)
        self.assertGreater(rows["E1._fit_adaptive_stops"]["calls"], 0)
        self.assertGreater(rows["E1._fit_colors"]["calls"], 0)

    def test_runtime_instrumentation_preserves_e1_candidate_output(self):
        t = np.linspace(0.0, 1.0, 56, dtype=np.float64)
        xy = np.column_stack((t * 45.0, np.cos(t * np.pi) * 6.0))
        rgb = np.column_stack((20 + t * 215, 235 - t * 150, 45 + t * 175))
        weights = np.ones(len(t), dtype=np.float64)
        baseline = phase_e1._linear_candidate_e1(xy, rgb, weights)
        profiler = E1Profiler()
        profiler.install()
        try:
            measured = phase_e1._linear_candidate_e1(xy, rgb, weights)
        finally:
            profiler.restore()
        self.assertEqual(_jsonable(baseline), _jsonable(measured))


if __name__ == "__main__":
    unittest.main()
