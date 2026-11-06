from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mediastudio.image_tools import contour_backend
from mediastudio.image_tools.vectorization_v2 import production

SVG_NS = "http://www.w3.org/2000/svg"
DIMENSIONS = ((451, 300), (300, 451), (512, 512))


def _svg(width: int, height: int) -> str:
    return (f'<svg xmlns="{SVG_NS}" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}"><rect width="{width}" '
            f'height="{height}" fill="#f28c18"/></svg>')


class SmartV2DimensionOrderTests(unittest.TestCase):
    def test_landscape_portrait_and_square_use_width_height_contract(self) -> None:
        for width, height in DIMENSIONS:
            with self.subTest(width=width, height=height), tempfile.TemporaryDirectory() as temp:
                source = Path(temp) / "source.png"
                output = Path(temp) / "result.svg"
                Image.new("RGBA", (width, height), (255, 255, 255, 255)).save(source)
                expected_sizes: list[tuple[int, int]] = []
                phase_a = SimpleNamespace(warnings=[], metrics={})
                phase_b = SimpleNamespace(warnings=[], metrics={}, ocr_status="OCR_READY")
                phase_c = SimpleNamespace(warnings=[], metrics={"final_region_count": 1})
                geometry = SimpleNamespace(
                    warnings=[],
                    metrics={"self_intersection_count": 0,
                             "final_geometry_validation": {"valid": True}},
                    width=width, height=height,
                )
                appearance = SimpleNamespace(metrics={})
                composition = SimpleNamespace(
                    svg_text=_svg(width, height), metadata={}, text_element_count=0,
                    outlined_text_count=0, path_count=1, gradient_count=0,
                )

                def rasterizer(_svg_text: str, *, expected_size: tuple[int, int], browser=None):
                    expected_sizes.append(expected_size)
                    w, h = expected_size
                    rendered = np.zeros((h, w, 4), dtype=np.uint8)
                    rendered[0, 0] = (242, 140, 24, 255)
                    return rendered

                with (patch.object(production, "run_phase_a", return_value=phase_a),
                      patch.object(production, "get_process_ocr_engine", return_value=SimpleNamespace(initialization_count=1)),
                      patch.object(production, "run_phase_b", return_value=phase_b),
                      patch.object(production, "run_phase_c", return_value=phase_c),
                      patch.object(production, "run_phase_d1", return_value=geometry),
                      patch.object(production, "run_phase_e1", return_value=appearance),
                      patch.object(production, "reconstruct_text_layers", return_value=([], [])),
                      patch.object(production, "compose_production_svg", return_value=composition),
                      patch.object(production, "rasterize_svg", side_effect=rasterizer)):
                    metrics, _ = production.run_vectorization_v2(source, output)

                self.assertEqual(expected_sizes, [(width, height)])
                self.assertEqual(metrics["width"], width)
                self.assertEqual(metrics["height"], height)
                self.assertEqual(output.read_text(encoding="utf-8"), _svg(width, height))


class ContourDimensionOrderTests(unittest.TestCase):
    def test_landscape_portrait_and_square_use_width_height_contract(self) -> None:
        for width, height in DIMENSIONS:
            with self.subTest(width=width, height=height), tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / "result.svg"
                expected_sizes: list[tuple[int, int]] = []

                def rasterizer(_svg_text: str, *, expected_size: tuple[int, int], browser=None):
                    expected_sizes.append(expected_size)
                    w, h = expected_size
                    rendered = np.zeros((h, w, 4), dtype=np.uint8)
                    rendered[..., 3] = 255
                    return rendered

                with patch.object(contour_backend, "rasterize_svg", side_effect=rasterizer):
                    rendered, visual = contour_backend._render_validate_publish(
                        _svg(width, height), output, (width, height),
                        np.full((height, width), 255, dtype=np.uint8), browser="test-browser",
                    )

                self.assertEqual(expected_sizes, [(width, height)])
                self.assertEqual(rendered.shape, (height, width, 4))
                self.assertEqual(visual["foregroundAlphaIoU"], 1.0)
                self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
