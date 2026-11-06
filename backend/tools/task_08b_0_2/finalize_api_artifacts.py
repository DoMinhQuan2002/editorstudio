from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
from PIL import Image

BACKEND = Path(__file__).resolve().parents[2]
TARGET = BACKEND / "artifacts" / "contour_preserving" / "task_08b_0_2"
sys.path.insert(0, str(BACKEND))
from tools.task_08a_1.dataset import write_json  # noqa: E402
from tools.vectorization_benchmark.svg import render_svg_skia  # noqa: E402
from tools.task_08b_0_2.run_api_regression import (  # noqa: E402
    ENGINE_NAMES, FAILURE_IDS, PREVIOUS, TARGET as API_TARGET, _alpha_summary,
    _baseline_dir_for_engine, _compare_rgba, _comparison_sheet,
)


def _read_rgba(path: str | Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"), dtype=np.uint8)


def main() -> int:
    api_path = TARGET / "api_job_validation.json"
    renderer_path = TARGET / "renderer_validation.json"
    api = json.loads(api_path.read_text(encoding="utf-8"))
    renderer = json.loads(renderer_path.read_text(encoding="utf-8"))
    renderer_by_key = {(row["imageId"], row["engine"]): row for row in renderer.get("items", [])}
    compare_rows: list[dict[str, Any]] = []
    for item in api.get("items", []):
        image_id = item.get("imageId")
        for engine in ENGINE_NAMES:
            record = item.get("engines", {}).get(engine, {})
            if record.get("jobStatus") != "succeeded" or not record.get("svgPath"):
                record["caseAccepted"] = False
                continue
            current_edge_path = record.get("edgeNative", {}).get("path")
            current_skia_path = record.get("skiaNative", {}).get("path")
            if not current_edge_path or not Path(current_edge_path).is_file():
                record["caseAccepted"] = False
                continue
            baseline_dir = _baseline_dir_for_engine(image_id, engine)
            before_edge_path = baseline_dir / "edge_render_correct_canvas.png"
            edge_comparison = _compare_rgba(_read_rgba(before_edge_path), _read_rgba(current_edge_path))
            record["baselineEngineArtifactDirectory"] = str(baseline_dir)
            record["edgeBeforeAfterComparison"] = edge_comparison
            skia_record = record.get("skiaNative", {})
            if skia_record.get("status") == "PASS" and current_skia_path and Path(current_skia_path).is_file():
                source_width, source_height = item["sourceSize"]
                before_skia_path = Path(current_skia_path).with_name("render_skia_before_native.png")
                baseline_skia = render_svg_skia(
                    baseline_dir / "output.svg", width=source_width, height=source_height,
                    output_path=before_skia_path,
                )
                if baseline_skia.get("status") != "PASS":
                    raise RuntimeError(f"Same-renderer baseline Svg.Skia render failed for {image_id}/{engine}: {baseline_skia}")
                skia_comparison = _compare_rgba(_read_rgba(before_skia_path), _read_rgba(current_skia_path))
                skia_record["beforeRenderPathSameRenderer"] = str(before_skia_path)
                skia_record["beforeAfterComparison"] = skia_comparison
                edge_alpha, skia_alpha = (_read_rgba(current_edge_path)[..., 3] > 16,
                                          _read_rgba(current_skia_path)[..., 3] > 16)
                skia_record["alphaIoUAgainstEdge"] = float(np.count_nonzero(edge_alpha & skia_alpha) /
                                                            max(np.count_nonzero(edge_alpha | skia_alpha), 1))
                renderer_consistency = skia_record["alphaIoUAgainstEdge"] >= 0.98
            else:
                renderer_consistency = None
            record["rendererConsistency"] = renderer_consistency
            record["caseAccepted"] = all((
                record.get("actualEngineMatchesRequest"),
                record.get("pipelineMatchesEngine"),
                record.get("sourceWidthHeightPassedToProductionRenderer"),
                record.get("noEmbeddedRaster"),
                record.get("dimensionValidation", {}).get("declaredSizeMatchesSource"),
                record.get("dimensionValidation", {}).get("viewBoxValid"),
                record.get("dimensionValidation", {}).get("viewBoxOriginIsZero"),
                record.get("dimensionValidation", {}).get("viewBoxAspectRatioMatchesSource"),
                record.get("edgeNative", {}).get("shapeValid"),
                record.get("edgeNative", {}).get("visible"),
                edge_comparison.get("sameShape"),
                edge_comparison.get("alphaIoU", 0) >= 0.999,
                edge_comparison.get("pixelMaeRgba", float("inf")) <= 0.1,
                skia_record.get("status") != "PASS" or (
                    skia_record.get("shapeValid") and skia_record.get("visible") and
                    skia_record.get("beforeAfterComparison", {}).get("sameShape") and
                    skia_record.get("beforeAfterComparison", {}).get("pixelMaeRgba", float("inf")) <= 0.1 and
                    renderer_consistency
                ),
            ))
            renderer_row = renderer_by_key.get((image_id, engine))
            if renderer_row is not None:
                renderer_row["baselineEngineArtifactDirectory"] = str(baseline_dir)
                renderer_row["edgeBeforeAfterComparison"] = edge_comparison
                renderer_row["skiaNative"] = skia_record
                renderer_row["rendererConsistency"] = renderer_consistency
            compare_rows.append({"imageId": image_id, "engine": engine,
                                 "sourcePath": item["sourcePath"],
                                 "beforePng": str(before_edge_path),
                                 "afterPng": current_edge_path})
    api_cases = [item.get("engines", {}).get(engine, {}).get("caseAccepted") is True
                 for item in api.get("items", []) for engine in ENGINE_NAMES]
    api["allCasesAccepted"] = len(api_cases) == len(FAILURE_IDS) * len(ENGINE_NAMES) and all(api_cases)
    api["comparisonBaselineMatching"] = "SVG aria-label identifies actual engine because 08B.0.1 capture-folder labels were misassigned for several reversed-order fixtures."
    renderer_rows = renderer.get("items", [])
    renderer["allNativeRendererChecksPassed"] = (
        len(renderer_rows) == len(FAILURE_IDS) * len(ENGINE_NAMES) and all(
            row.get("edgeNative", {}).get("shapeValid") and row.get("edgeNative", {}).get("visible") and
            row.get("edgeBeforeAfterComparison", {}).get("alphaIoU", 0) >= 0.999 and
            row.get("edgeBeforeAfterComparison", {}).get("pixelMaeRgba", float("inf")) <= 0.1 and
            (row.get("skiaNative", {}).get("status") != "PASS" or
             (row.get("skiaNative", {}).get("shapeValid") and row.get("skiaNative", {}).get("visible") and
              row.get("skiaNative", {}).get("beforeAfterComparison", {}).get("pixelMaeRgba", float("inf")) <= 0.1 and
              row.get("rendererConsistency"))) for row in renderer_rows
        )
    )
    write_json(api_path, api)
    write_json(renderer_path, renderer)
    write_json(TARGET / "nonsquare_regression_results.json", {
        "schemaVersion": 1,
        "landscape451x300": "Smart V2 and Contour caller tests; chelsea direct API case is 451x300",
        "portrait300x451": "Smart V2 and Contour caller tests; eagle direct API case is 1826x2019",
        "square512x512": "Smart V2 and Contour caller tests",
        "realApiFixtureIds": list(FAILURE_IDS),
        "realApiTwoEngineCaseCount": len(FAILURE_IDS) * len(ENGINE_NAMES),
        "allDimensionCallArgumentsAreWidthHeight": all(
            record.get("sourceWidthHeightPassedToProductionRenderer")
            for item in api.get("items", []) for record in item.get("engines", {}).values()
            if record.get("jobStatus") == "succeeded"
        ),
        "apiAllCasesAccepted": api["allCasesAccepted"],
        "nativeRendererChecksPassed": renderer["allNativeRendererChecksPassed"],
    })
    _comparison_sheet(compare_rows)
    print(json.dumps({"apiAllCasesAccepted": api["allCasesAccepted"],
                      "rendererValidationPassed": renderer["allNativeRendererChecksPassed"],
                      "caseCount": len(api_cases)}, ensure_ascii=False, indent=2))
    return 0 if api["allCasesAccepted"] and renderer["allNativeRendererChecksPassed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
