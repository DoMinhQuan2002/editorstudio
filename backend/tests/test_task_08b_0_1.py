from __future__ import annotations

import numpy as np

from tools.task_08b_0_1.svg_diagnostics import has_visible_artwork


def test_transparent_background_with_visible_art_is_not_empty() -> None:
    rgba = np.zeros((12, 12, 4), dtype=np.uint8)
    rgba[3:9, 4:8, :3] = (220, 30, 55)
    rgba[3:9, 4:8, 3] = 255
    assert has_visible_artwork(rgba)
    assert np.any(rgba[..., 3] == 0)


def test_fully_transparent_raster_has_no_visible_art() -> None:
    rgba = np.zeros((12, 12, 4), dtype=np.uint8)
    assert not has_visible_artwork(rgba)


def test_low_alpha_artwork_is_still_visible() -> None:
    rgba = np.zeros((12, 12, 4), dtype=np.uint8)
    rgba[5, 5] = (220, 30, 55, 1)
    assert has_visible_artwork(rgba)
