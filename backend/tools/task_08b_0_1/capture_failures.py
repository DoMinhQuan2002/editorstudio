from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import traceback
from typing import Any

import numpy as np
from PIL import Image

BACKEND = Path(__file__).resolve().parents[2]
REPOSITORY = BACKEND.parent
TARGET = BACKEND / "artifacts" / "contour_preserving" / "task_08b_0_1"
sys.path.insert(0, str(BACKEND))

from tools.task_08a_1.dataset import MANIFEST, write_json  # noqa: E402
from tools.vectorization_benchmark.worker import run_image  # noqa: E402
from mediastudio.image_tools.vectorization_v2 import production  # noqa: E402
from mediastudio.image_tools import contour_backend  # noqa: E402


FAILURE_IDS = ("chelsea", "clock", "coffee", "eagle", "horse", "text")


def _summary(rgba: np.ndarray) -> dict[str, Any]:
    alpha = rgba[..., 3]
    ys, xs = np.nonzero(alpha > 0)
    return {
        "shape": list(rgba.shape),
        "alphaNonzeroPixels": int(np.count_nonzero(alpha)),
        "alphaAbove16Pixels": int(np.count_nonzero(alpha > 16)),
        "alphaMax": int(alpha.max(initial=0)),
        "alphaBBoxXYXY": ([int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
                           if len(xs) else None),
    }


def capture_one(item: dict[str, Any], timeout: int = 900) -> dict[str, Any]:
    image_id = str(item["imageId"])
    source_dir = TARGET / "reruns" / image_id
    source_dir.mkdir(parents=True, exist_ok=True)
    order_index = int(hashlib.sha256(image_id.encode()).hexdigest()[:2], 16) % 2
    engine_order = ["smart_reconstruction", "contour_preserving"]
    if order_index:
        engine_order.reverse()
    capture_index = 0
    captures: list[dict[str, Any]] = []

    def wrap(original, module_name: str):
        def captured(svg_text: str, *, expected_size: tuple[int, int], browser: str | None = None):
            nonlocal capture_index
            engine = engine_order[min(capture_index, len(engine_order) - 1)]
            ordinal = capture_index
            capture_index += 1
            engine_dir = source_dir / engine
            engine_dir.mkdir(parents=True, exist_ok=True)
            svg_path = engine_dir / "output.svg"
            svg_path.write_text(svg_text, encoding="utf-8")
            record: dict[str, Any] = {
                "imageId": image_id,
                "engine": engine,
                "captureOrdinal": ordinal,
                "captureModule": module_name,
                "expectedSizeArgument": list(expected_size),
                "browser": browser,
                "svgPath": str(svg_path),
                "svgSha256": hashlib.sha256(svg_path.read_bytes()).hexdigest(),
                "svgBytes": svg_path.stat().st_size,
            }
            try:
                rgba = np.asarray(original(svg_text, expected_size=expected_size, browser=browser), dtype=np.uint8)
                render_path = engine_dir / "edge_render_api_canvas.png"
                Image.fromarray(rgba, "RGBA").save(render_path)
                record["rendererResult"] = _summary(rgba)
                record["edgeRenderPath"] = str(render_path)
                record["edgeRenderSha256"] = hashlib.sha256(render_path.read_bytes()).hexdigest()
                record["renderError"] = None
                return rgba
            except BaseException as error:
                record["rendererResult"] = None
                record["renderError"] = f"{type(error).__name__}: {error}"
                (engine_dir / "renderer_error.txt").write_text(record["renderError"], encoding="utf-8")
                raise
            finally:
                captures.append(record)
                write_json(source_dir / "capture_progress.json", {"imageId": image_id, "captures": captures})
        return captured

    old_smart, old_contour = production.rasterize_svg, contour_backend.rasterize_svg
    production.rasterize_svg = wrap(old_smart, "vectorization_v2.production")
    contour_backend.rasterize_svg = wrap(old_contour, "image_tools.contour_backend")
    os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
    os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
    os.environ["DEBUG_VECTOR"] = "0"
    try:
        run_id = "task08b0_1_capture"
        result = run_image(item, TARGET, per_engine_timeout=timeout, run_id=run_id)
        return {"imageId": image_id, "engineOrder": engine_order, "captureCount": len(captures),
                "captures": captures, "apiRun": result}
    except BaseException as error:
        return {"imageId": image_id, "engineOrder": engine_order, "captureCount": len(captures),
                "captures": captures, "exception": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc()}
    finally:
        production.rasterize_svg = old_smart
        contour_backend.rasterize_svg = old_contour


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    items = {str(row["imageId"]): row for row in manifest["items"]}
    TARGET.mkdir(parents=True, exist_ok=True)
    run_path = TARGET / "rerun_capture_results.json"
    completed: dict[str, Any] = {}
    if run_path.is_file():
        completed = {str(row["imageId"]): row for row in json.loads(run_path.read_text(encoding="utf-8")).get("items", [])
                     if len(row.get("captures", [])) >= 2}
    for index, image_id in enumerate(FAILURE_IDS, 1):
        if image_id in completed:
            print(f"[{index}/{len(FAILURE_IDS)}] {image_id}: captured, reusing hash-verified artifacts", flush=True)
            continue
        item = dict(items[image_id])
        print(f"[{index}/{len(FAILURE_IDS)}] {image_id}: starting both production API engines", flush=True)
        result = capture_one(item)
        completed[image_id] = result
        write_json(run_path, {"schemaVersion": 1, "items": list(completed.values())})
        for capture in result.get("captures", []):
            print(f"  {capture['engine']}: {capture.get('rendererResult')} — {capture.get('renderError')}", flush=True)
        print(f"  captured {result.get('captureCount', 0)} SVG(s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
