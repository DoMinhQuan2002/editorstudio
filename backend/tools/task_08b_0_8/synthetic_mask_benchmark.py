from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))
from mediastudio.image_tools.vectorization_v2 import appearance_feature_geometry as fg  # noqa: E402

SOURCE = BACKEND / "artifacts/contour_preserving/task_07_2/synthetic_sources/thin_line.png"
ARTIFACTS = BACKEND / "artifacts/contour_preserving/task_08b_0_8"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(version: str) -> None:
    image = np.asarray(Image.open(SOURCE).convert("RGBA"))
    mask = np.ascontiguousarray(image[:, :, 3] >= 128, dtype=bool)
    mask_path = ARTIFACTS / "feature_masks" / f"synthetic_thin_direct_{version}.npz"
    mask_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(mask_path, mask)
    warmup = np.zeros((24, 24), dtype=bool)
    warmup[5:19, 6:18] = True
    fg.fit_mask_contours_to_svg_d(warmup, threshold=1, tolerance=0.35,
                                 minimum_area=0.0, fallback_epsilon=0.9)
    timings: list[float] = []
    output_hashes: list[str] = []
    metric_hashes: list[str] = []
    path_data = ""
    metrics: dict[str, object] = {}
    for _ in range(7):
        started = time.perf_counter_ns()
        path_data, raw_metrics = fg.fit_mask_contours_to_svg_d(
            mask, threshold=1, tolerance=0.35, minimum_area=0.0, fallback_epsilon=0.9)
        timings.append(round((time.perf_counter_ns() - started) / 1_000_000, 3))
        metrics = raw_metrics
        output_hashes.append(sha(path_data.encode("utf-8")))
        metric_hashes.append(sha(json.dumps(metrics, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")))
    result = {
        "fixture_id": "synthetic_thin_direct",
        "version": version,
        "source_image": str(SOURCE.relative_to(BACKEND)),
        "mask_rule": "RGBA alpha >= 128",
        "mask_shape": list(mask.shape),
        "mask_area_px": int(mask.sum()),
        "mask_sha256": sha(mask.tobytes()),
        "repeat_count": len(timings),
        "per_repeat_ms": timings,
        "median_ms": round(float(np.median(timings)), 3),
        "output_hashes": output_hashes,
        "metric_hashes": metric_hashes,
        "repeat_output_identical": len(set(output_hashes)) == 1 and len(set(metric_hashes)) == 1,
        "path_sha256": sha(path_data.encode("utf-8")),
        "path_data": path_data,
        "metrics": metrics,
    }
    out = ARTIFACTS / "runs" / "synthetic_thin_direct" / version / "direct_mask_timing.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in {"path_data", "metrics", "output_hashes", "metric_hashes"}}, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"baseline", "optimized"}:
        raise SystemExit("Usage: synthetic_mask_benchmark.py baseline|optimized")
    run(sys.argv[1])
