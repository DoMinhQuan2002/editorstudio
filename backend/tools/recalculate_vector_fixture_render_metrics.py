"""Recompute source-vs-render metrics from saved V2 fixture renders."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.qa_vectorization_v2_fixtures import _compare_render_to_source

OUT = ROOT / "artifacts" / "vector_v2_product" / "fixture_matrix"


def main() -> None:
    combined = {"suite": "Vectorization V2 synthetic fixture matrix",
                "note": "All fixtures in this matrix are synthetic; they validate functional, geometry, and source-difference metrics but are not real-artwork quality evidence.",
                "modes": {}}
    for mode in ("auto", "quality"):
        path = OUT / f"fixture_matrix_report_{mode}.json"
        report = json.loads(path.read_text(encoding="utf-8-sig"))
        for record in report["results"]:
            source = ROOT / record["input"]
            render = ROOT / record["renderPng"]
            with Image.open(render) as image:
                rendered = np.asarray(image.convert("RGBA"), dtype=np.uint8)
            record["visualDifferenceMetrics"] = _compare_render_to_source(source, rendered)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        combined["modes"][mode] = report
    (OUT / "fixture_matrix_report_auto_quality.json").write_text(
        json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
