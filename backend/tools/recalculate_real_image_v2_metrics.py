"""Recompute the real-image preview comparison using border-estimated matte support."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.qa_vectorization_v2_real_assets import _render_metrics, _source_rgb_and_mask

report_path = ROOT / "artifacts" / "vector_v2_product" / "real_image_qa" / "real_image_qa_report.json"
report = json.loads(report_path.read_text(encoding="utf-8-sig"))
for row in report["results"]:
    source_path = ROOT / row["input"]
    source, source_mask = _source_rgb_and_mask(source_path, int(row["workingWidth"]))
    render_path = ROOT / row["previewPath"]
    with Image.open(render_path) as image:
        rendered = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    row["visualDifferenceMetrics"] = _render_metrics(source, source_mask, rendered)
report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
