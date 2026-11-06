from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from mediastudio.image_tools.vectorization_v2.phase_e import (  # noqa: E402
    _delta_e, _predict_model_rgb, _radial_candidates, _weighted_quantile,
)


RADIAL_FIXTURE = (BACKEND / "artifacts" / "contour_preserving" / "task_07_2" /
                  "synthetic_sources" / "radial_gradient.png")


class SmartV2RadialGradientRepairTests(unittest.TestCase):
    def test_radial_first_stop_keeps_its_fitted_profile_position(self) -> None:
        with Image.open(RADIAL_FIXTURE) as opened:
            rgba = np.asarray(opened.convert("RGBA"), dtype=np.uint8)
        mask = rgba[..., 3] > 16
        ys, xs = np.where(mask)
        xy = np.column_stack((xs.astype(np.float64), ys.astype(np.float64)))
        rgb = rgba[ys, xs, :3].astype(np.float64)
        weights = np.ones(len(xs), dtype=np.float64)

        candidate, _ = _radial_candidates(xy, rgb, weights, (119, 119, 393, 393))
        self.assertIsNotNone(candidate)
        assert candidate is not None
        coords = candidate["coordinates"]
        center = np.asarray((coords["cx"], coords["cy"]), dtype=np.float64)
        radii = np.linalg.norm(xy - center, axis=1)
        expected_first = float(_weighted_quantile(
            radii, weights, np.asarray([0.015, 0.985]))[0] / coords["r"])

        # The stop's color is sampled at this quantile, so moving only its
        # coordinate toward the center makes the recorded score optimistic.
        self.assertAlmostEqual(float(candidate["stops"][0]["position"]), expected_first, places=7)
        self.assertGreater(float(candidate["stops"][0]["position"]), 0.02)

    def test_radial_candidate_score_matches_serialized_model_prediction(self) -> None:
        with Image.open(RADIAL_FIXTURE) as opened:
            rgba = np.asarray(opened.convert("RGBA"), dtype=np.uint8)
        mask = rgba[..., 3] > 16
        ys, xs = np.where(mask)
        xy = np.column_stack((xs.astype(np.float64), ys.astype(np.float64)))
        rgb = rgba[ys, xs, :3].astype(np.float64)
        weights = np.ones(len(xs), dtype=np.float64)
        candidate, _ = _radial_candidates(xy, rgb, weights, (119, 119, 393, 393))
        self.assertIsNotNone(candidate)
        assert candidate is not None
        model = {"appearance_type": "RADIAL_GRADIENT", "gradient_type": "radial",
                 "flat_color_rgb": [0, 0, 0],
                 "gradient_coordinates": candidate["coordinates"],
                 "gradient_stops": candidate["stops"]}
        predicted = _predict_model_rgb(model, xy)
        replay_error = float(np.average(_delta_e(rgb, predicted), weights=weights))
        self.assertAlmostEqual(float(candidate["error"]), replay_error, places=6)

    def test_offcenter_multistop_and_heldout_radials_keep_radial_model(self) -> None:
        variants = (
            (192, (73.0, 116.0), 49.0,
             ((0.0, (250, 240, 218)), (1.0, (28, 74, 188)))),
            (192, (96.0, 96.0), 57.0,
             ((0.0, (250, 235, 192)), (0.31, (253, 155, 47)),
              (0.68, (209, 63, 89)), (1.0, (36, 35, 126)))),
            (224, (139.0, 91.0), 61.0,
             ((0.0, (230, 248, 255)), (0.57, (51, 165, 207)),
              (1.0, (146, 25, 83)))),
        )
        for size, center, radius, stops in variants:
            with self.subTest(center=center, radius=radius, stops=len(stops)):
                yy, xx = np.mgrid[:size, :size]
                distance = np.sqrt((xx - center[0]) ** 2 + (yy - center[1]) ** 2)
                t = np.clip(distance / radius, 0.0, 1.0)
                positions = np.asarray([row[0] for row in stops], dtype=np.float64)
                colors = np.asarray([row[1] for row in stops], dtype=np.float64)
                rgb_grid = np.stack([
                    np.interp(t, positions, colors[:, channel]) for channel in range(3)
                ], axis=2)
                mask = distance <= radius - 2.0
                ys, xs = np.where(mask)
                xy = np.column_stack((xs.astype(np.float64), ys.astype(np.float64)))
                rgb = rgb_grid[ys, xs]
                weights = np.ones(len(xs), dtype=np.float64)
                x0, y0 = np.floor(np.asarray(center) - radius).astype(int)
                x1, y1 = np.ceil(np.asarray(center) + radius + 1).astype(int)
                bbox = (int(x0), int(y0), int(x1), int(y1))
                candidate, _ = _radial_candidates(xy, rgb, weights, bbox)
                self.assertIsNotNone(candidate)
                assert candidate is not None
                model = {"appearance_type": "RADIAL_GRADIENT", "gradient_type": "radial",
                         "flat_color_rgb": [0, 0, 0],
                         "gradient_coordinates": candidate["coordinates"],
                         "gradient_stops": candidate["stops"]}
                predicted = _predict_model_rgb(model, xy)
                replay_error = float(np.average(_delta_e(rgb, predicted), weights=weights))
                # SVG stop colors are serialized as 8-bit RGB, while the fit
                # score uses floating-point colors; allow only that rounding.
                self.assertLessEqual(abs(float(candidate["error"]) - replay_error), 0.30)


if __name__ == "__main__":
    unittest.main()
