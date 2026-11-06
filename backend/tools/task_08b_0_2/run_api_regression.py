from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw

BACKEND = Path(__file__).resolve().parents[2]
TARGET = BACKEND / "artifacts" / "contour_preserving" / "task_08b_0_2"
PREVIOUS = BACKEND / "artifacts" / "contour_preserving" / "task_08b_0_1"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402
from mediastudio.api import create_app  # noqa: E402
from mediastudio.desktop_capabilities import install_desktop_capabilities  # noqa: E402
from mediastudio.image_tools import contour_backend  # noqa: E402
from mediastudio.image_tools.vectorization_v2 import production  # noqa: E402
from mediastudio.image_tools.vectorization_v2.phase_e1 import rasterize_svg  # noqa: E402
from tools.task_08a_1.dataset import MANIFEST, write_json  # noqa: E402
from tools.task_08a_1.runner import sha256 as file_sha256  # noqa: E402
from tools.vectorization_benchmark.dataset import resolve_path  # noqa: E402
from tools.vectorization_benchmark.svg import render_svg_skia, validate_svg  # noqa: E402

TOKEN = "task08b-0-2-direct-api-token"
FAILURE_IDS = ("chelsea", "clock", "coffee", "eagle", "horse", "text")
ENGINE_NAMES = ("smart_reconstruction", "contour_preserving")


def _alpha_summary(rgba: np.ndarray) -> dict[str, Any]:
    alpha = rgba[..., 3]
    ys, xs = np.nonzero(alpha > 16)
    return {
        "shape": list(rgba.shape),
        "alphaNonzeroPixels": int(np.count_nonzero(alpha)),
        "alphaAbove16Pixels": int(np.count_nonzero(alpha > 16)),
        "alphaBBoxXYXY": ([int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
                           if len(xs) else None),
    }


def _compare_rgba(before: np.ndarray, after: np.ndarray) -> dict[str, Any]:
    result: dict[str, Any] = {"sameShape": before.shape == after.shape,
                              "beforeShape": list(before.shape), "afterShape": list(after.shape)}
    if before.shape != after.shape:
        return result
    alpha_a, alpha_b = before[..., 3] > 16, after[..., 3] > 16
    union = int(np.count_nonzero(alpha_a | alpha_b))
    intersection = int(np.count_nonzero(alpha_a & alpha_b))
    bbox_a, bbox_b = _alpha_summary(before)["alphaBBoxXYXY"], _alpha_summary(after)["alphaBBoxXYXY"]
    result.update({
        "pixelMaeRgba": float(np.abs(before.astype(np.int16) - after.astype(np.int16)).mean()),
        "alphaIoU": intersection / max(union, 1),
        "beforeAlphaBBoxXYXY": bbox_a,
        "afterAlphaBBoxXYXY": bbox_b,
        "sameAlphaBBox": bbox_a == bbox_b,
    })
    return result


def _svg_dimensions(svg_path: Path, width: int, height: int) -> dict[str, Any]:
    root = ET.parse(svg_path).getroot()
    declared_width = float(root.attrib.get("width", "0").removesuffix("px"))
    declared_height = float(root.attrib.get("height", "0").removesuffix("px"))
    viewbox = [float(value) for value in root.attrib.get("viewBox", "").replace(",", " ").split()]
    ratio_error = None
    if len(viewbox) == 4 and viewbox[2] > 0 and viewbox[3] > 0:
        ratio_error = abs((viewbox[2] / viewbox[3]) - (width / height)) / (width / height)
    return {
        "declaredWidth": declared_width,
        "declaredHeight": declared_height,
        "viewBox": viewbox,
        "declaredSizeMatchesSource": declared_width == width and declared_height == height,
        "viewBoxValid": len(viewbox) == 4 and viewbox[2] > 0 and viewbox[3] > 0,
        "viewBoxOriginIsZero": len(viewbox) == 4 and abs(viewbox[0]) < 1e-6 and abs(viewbox[1]) < 1e-6,
        "viewBoxAspectRatioRelativeError": ratio_error,
        "viewBoxAspectRatioMatchesSource": ratio_error is not None and ratio_error <= 0.001,
    }


def _baseline_dir_for_engine(image_id: str, engine: str) -> Path:
    expected_label = ("Vectorized image" if engine == "smart_reconstruction"
                      else "Contour-preserving vectorized image")
    matches: list[Path] = []
    for candidate_engine in ENGINE_NAMES:
        candidate = PREVIOUS / "reruns" / image_id / candidate_engine
        svg_path = candidate / "output.svg"
        if svg_path.is_file() and ET.parse(svg_path).getroot().attrib.get("aria-label") == expected_label:
            matches.append(candidate)
    if len(matches) != 1:
        raise RuntimeError(f"Cannot uniquely map Task 08B.0.1 SVG to {engine} for {image_id}: {matches}")
    return matches[0]


def _wait_for_job(client: TestClient, job_id: str, headers: dict[str, str],
                  timeout_seconds: int) -> tuple[dict[str, Any], bytes, str, list[dict[str, Any]]]:
    started = time.perf_counter()
    deadline = started + timeout_seconds
    history: list[dict[str, Any]] = []
    while time.perf_counter() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
        response.raise_for_status()
        job = response.json()
        history.append({"state": job.get("state"), "stage": job.get("stage"),
                        "progress": job.get("progress")})
        if job.get("state") == "failed":
            return job, b"", "", history
        if job.get("state") == "succeeded":
            result = client.get(f"/api/v1/jobs/{job_id}/result", headers=headers)
            result.raise_for_status()
            content_type = result.headers.get("content-type", "").split(";", 1)[0]
            return job, result.content, content_type, history
        time.sleep(0.25)
    raise TimeoutError(f"API job {job_id} exceeded {timeout_seconds}s")


def _comparison_sheet(rows: list[dict[str, Any]]) -> None:
    cell_w, cell_h, left_w, row_label = 300, 210, 260, 30
    width = left_w + cell_w * 3
    height = row_label + len(rows) * (cell_h + row_label)
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    for text, x in (("Fixture / engine", 6), ("Source raster", left_w),
                    ("Task 08B.0.1 SVG", left_w + cell_w),
                    ("Task 08B.0.2 API SVG", left_w + 2 * cell_w)):
        draw.text((x + 8, 8), text, fill=(25, 32, 46))
    y = row_label
    for row in rows:
        draw.rectangle((0, y, left_w - 1, y + cell_h - 1), fill=(247, 248, 251))
        draw.text((8, y + 10), f"{row['imageId']} · {row['engine']}", fill=(30, 40, 58))
        for index, key in enumerate(("sourcePath", "beforePng", "afterPng")):
            with Image.open(row[key]) as image:
                foreground = image.convert("RGBA")
                foreground.thumbnail((cell_w - 12, cell_h - 12), Image.Resampling.LANCZOS)
                canvas = Image.new("RGBA", (cell_w, cell_h), (246, 246, 249, 255))
                canvas.alpha_composite(foreground, ((cell_w - foreground.width) // 2,
                                                    (cell_h - foreground.height) // 2))
                sheet.paste(canvas.convert("RGB"), (left_w + index * cell_w, y))
        y += cell_h
        draw.line((0, y, width, y), fill=(217, 220, 228), width=1)
        y += row_label
    sheet.save(TARGET / "before_after_comparison.png")


def _api_fixture(item: dict[str, Any], run_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    image_id = str(item["imageId"])
    source_path = resolve_path(str(item["path"]))
    source_bytes = source_path.read_bytes()
    if file_sha256(source_path) != item.get("sha256"):
        raise RuntimeError(f"Source hash mismatch for {image_id}")
    with Image.open(source_path) as source:
        width, height = source.size
    output_root = run_root / "outputs" / image_id
    output_root.mkdir(parents=True, exist_ok=True)
    (run_root / "temp").mkdir(parents=True, exist_ok=True)
    models_directory = (Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) /
                        "MediaStudio" / "models" / "realesrgan")
    expected_calls: dict[str, list[dict[str, Any]]] = {name: [] for name in ENGINE_NAMES}
    native_rgba: dict[str, np.ndarray] = {}
    original_smart, original_contour = production.rasterize_svg, contour_backend.rasterize_svg

    def wrap(engine: str, original):
        def captured(svg_text: str, *, expected_size: tuple[int, int], browser: str | None = None):
            record = {"expectedSizeWidthHeight": list(expected_size),
                      "svgSha256": hashlib.sha256(svg_text.encode("utf-8")).hexdigest(),
                      "browser": browser}
            expected_calls[engine].append(record)
            rgba = original(svg_text, expected_size=expected_size, browser=browser)
            if rgba.shape == (height, width, 4) and np.any(rgba[..., 3] > 16):
                native_rgba[engine] = rgba
            return rgba
        return captured

    production.rasterize_svg = wrap("smart_reconstruction", original_smart)
    contour_backend.rasterize_svg = wrap("contour_preserving", original_contour)
    engine_rows: dict[str, Any] = {}
    renderer_rows: list[dict[str, Any]] = []
    comparison_rows: list[dict[str, Any]] = []
    try:
        with tempfile.TemporaryDirectory(prefix=f"task08b02-{image_id}-", dir=run_root / "temp") as temp_name:
            temp = Path(temp_name)
            app = create_app(TOKEN, temp / "workspace", models_directory)
            install_desktop_capabilities(app)
            app.state.output_directory = output_root / "api_output"
            headers = {"X-Media-Studio-Token": TOKEN}
            with TestClient(app) as client:
                client.get("/api/v1/health", headers=headers).raise_for_status()
                capabilities = client.get("/api/v1/desktop/contour-capabilities", headers=headers)
                capabilities.raise_for_status()
                capability_data = capabilities.json()
                if not capability_data.get("ready"):
                    raise RuntimeError(f"Contour capability is not ready: {capability_data}")
                uploaded = client.post("/api/v1/assets", headers=headers,
                                       files={"file": (source_path.name, source_bytes, "application/octet-stream")})
                uploaded.raise_for_status()
                asset_id = uploaded.json()["assetId"]
                for engine in ENGINE_NAMES:
                    expected_calls[engine].clear()
                    native_rgba.pop(engine, None)
                    engine_dir = output_root / engine
                    engine_dir.mkdir(parents=True, exist_ok=True)
                    request = {
                        "asset_id": asset_id, "engine": "auto", "mode": "auto",
                        "color_count": None, "simplification": None, "smooth_paths": True,
                        "transparent_background": True, "text_mode": "outlined",
                        "vector_method": engine,
                    }
                    queued_response = client.post("/api/v1/vectorize/jobs", headers=headers, json=request)
                    if queued_response.status_code != 202:
                        engine_rows[engine] = {
                            "jobStatus": "QUEUE_FAILED", "httpStatus": queued_response.status_code,
                            "responseText": queued_response.text,
                            "expectedSizeCalls": list(expected_calls[engine]),
                        }
                        continue
                    queued = queued_response.json()
                    job, svg_bytes, content_type, history = _wait_for_job(
                        client, queued["jobId"], headers, timeout_seconds=1200
                    )
                    row: dict[str, Any] = {
                        "jobId": queued["jobId"], "assetId": asset_id,
                        "jobStatus": job.get("state"),
                        "failureCode": job.get("errorCode"), "failureReason": job.get("error"),
                        "contentType": content_type,
                        "actualEngine": job.get("resultVectorMethod"),
                        "actualEngineName": job.get("resultEngine"),
                        "actualPipeline": job.get("resultPipeline"),
                        "engineMetadata": job.get("resultEngineMetadata"),
                        "expectedSizeCalls": list(expected_calls[engine]),
                        "progressHistory": history,
                    }
                    if job.get("state") == "succeeded" and content_type == "image/svg+xml":
                        svg_path = engine_dir / "output.svg"
                        svg_path.write_bytes(svg_bytes)
                        row["svgPath"] = str(svg_path)
                        row["svgSha256"] = file_sha256(svg_path)
                        validation = validate_svg(svg_path)
                        dimensions = _svg_dimensions(svg_path, width, height)
                        embedded = (validation.get("embeddedRasterElementCount", 0) +
                                    validation.get("embeddedRasterDataUriCount", 0))
                        row["svgValidation"] = validation
                        row["dimensionValidation"] = dimensions
                        row["noEmbeddedRaster"] = embedded == 0
                        row["actualEngineMatchesRequest"] = job.get("resultVectorMethod") == engine
                        expected_pipeline = ("vectorization_v2" if engine == "smart_reconstruction"
                                             else "contour_preserving")
                        row["pipelineMatchesEngine"] = job.get("resultPipeline") == expected_pipeline
                        row["sourceWidthHeightPassedToProductionRenderer"] = any(
                            call["expectedSizeWidthHeight"] == [width, height]
                            for call in expected_calls[engine]
                        )
                        rgba = native_rgba.get(engine)
                        if rgba is not None:
                            edge_path = engine_dir / "render_edge_native.png"
                            Image.fromarray(rgba, "RGBA").save(edge_path)
                            baseline_dir = _baseline_dir_for_engine(image_id, engine)
                            old_edge_path = baseline_dir / "edge_render_correct_canvas.png"
                            with Image.open(old_edge_path) as old_image:
                                old_edge = np.asarray(old_image.convert("RGBA"), dtype=np.uint8)
                            edge_comparison = _compare_rgba(old_edge, rgba)
                            row["edgeNative"] = {**_alpha_summary(rgba),
                                                  "shapeValid": rgba.shape == (height, width, 4),
                                                  "visible": bool(np.any(rgba[..., 3] > 16)),
                                                  "path": str(edge_path)}
                            row["edgeBeforeAfterComparison"] = edge_comparison
                            comparison_rows.append({"imageId": image_id, "engine": engine,
                                                    "sourcePath": str(source_path),
                                                    "beforePng": str(old_edge_path),
                                                    "afterPng": str(edge_path)})
                        else:
                            edge_comparison = {"sameShape": False, "error": "No visible native-size Edge raster captured from API validation."}
                            row["edgeNative"] = {"shapeValid": False, "visible": False}
                            row["edgeBeforeAfterComparison"] = edge_comparison

                        skia_path = engine_dir / "render_skia_native.png"
                        skia = render_svg_skia(svg_path, width=width, height=height, output_path=skia_path)
                        skia_row: dict[str, Any] = {"status": skia.get("status"), "error": skia.get("error"),
                                                    "path": str(skia_path)}
                        if skia.get("status") == "PASS":
                            skia_rgba = np.asarray(skia["rgba"], dtype=np.uint8)
                            baseline_dir = _baseline_dir_for_engine(image_id, engine)
                            old_skia_path = baseline_dir / "skia_render_correct_canvas.png"
                            with Image.open(old_skia_path) as old_image:
                                old_skia = np.asarray(old_image.convert("RGBA"), dtype=np.uint8)
                            skia_row.update(_alpha_summary(skia_rgba))
                            skia_row["shapeValid"] = skia_rgba.shape == (height, width, 4)
                            skia_row["visible"] = bool(np.any(skia_rgba[..., 3] > 16))
                            skia_row["beforeAfterComparison"] = _compare_rgba(old_skia, skia_rgba)
                            if rgba is not None:
                                edge_alpha, skia_alpha = rgba[..., 3] > 16, skia_rgba[..., 3] > 16
                                skia_row["alphaIoUAgainstEdge"] = float(np.count_nonzero(edge_alpha & skia_alpha) /
                                                                        max(np.count_nonzero(edge_alpha | skia_alpha), 1))
                        row["skiaNative"] = skia_row
                        row["rendererConsistency"] = (
                            skia_row.get("alphaIoUAgainstEdge", 0) >= 0.98
                            if skia_row.get("status") == "PASS" else None
                        )
                        row["caseAccepted"] = all((
                            row["actualEngineMatchesRequest"], row["pipelineMatchesEngine"],
                            row["sourceWidthHeightPassedToProductionRenderer"],
                            row["noEmbeddedRaster"], dimensions["declaredSizeMatchesSource"],
                            dimensions["viewBoxValid"], dimensions["viewBoxOriginIsZero"],
                            dimensions["viewBoxAspectRatioMatchesSource"],
                            row["edgeNative"]["shapeValid"], row["edgeNative"]["visible"],
                            row["edgeBeforeAfterComparison"].get("sameShape"),
                            row["edgeBeforeAfterComparison"].get("alphaIoU", 0) >= 0.999,
                            skia_row.get("status") != "PASS" or (
                                skia_row.get("shapeValid") and skia_row.get("visible") and
                                row["rendererConsistency"]
                            ),
                        ))
                        renderer_rows.append({
                            "imageId": image_id, "engine": engine, "sourceSize": [width, height],
                            "edgeNative": row["edgeNative"],
                            "edgeBeforeAfterComparison": row["edgeBeforeAfterComparison"],
                            "skiaNative": skia_row,
                            "rendererConsistency": row["rendererConsistency"],
                            "svgValidation": validation,
                            "dimensionValidation": dimensions,
                            "noEmbeddedRaster": row["noEmbeddedRaster"],
                        })
                    engine_rows[engine] = row
        return ({"imageId": image_id, "sourcePath": str(source_path),
                 "sourceSize": [width, height],
                 "sameAssetIdUsedByBothEngines": len({row.get("assetId") for row in engine_rows.values()
                                                      if row.get("assetId")}) == 1,
                 "engines": engine_rows}, renderer_rows, comparison_rows)
    finally:
        production.rasterize_svg = original_smart
        contour_backend.rasterize_svg = original_contour


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    run_root = TARGET / "runs" / "task08b0_2_api_direct"
    run_root.mkdir(parents=True, exist_ok=True)
    os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
    os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
    os.environ["DEBUG_VECTOR"] = "0"
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    items = {str(item["imageId"]): item for item in manifest["items"]}
    api_rows: list[dict[str, Any]] = []
    renderer_rows: list[dict[str, Any]] = []
    comparison_rows: list[dict[str, Any]] = []
    for image_id in FAILURE_IDS:
        try:
            api_row, render_rows, compare_rows = _api_fixture(items[image_id], run_root)
            api_rows.append(api_row)
            renderer_rows.extend(render_rows)
            comparison_rows.extend(compare_rows)
            statuses = ", ".join(f"{engine}={api_row['engines'].get(engine, {}).get('jobStatus')}"
                                  for engine in ENGINE_NAMES)
            print(f"{image_id} {api_row['sourceSize'][0]}x{api_row['sourceSize'][1]}: {statuses}", flush=True)
        except BaseException as error:
            api_rows.append({"imageId": image_id, "error": f"{type(error).__name__}: {error}",
                             "traceback": traceback.format_exc(), "engines": {}})
            print(f"{image_id}: ERROR {type(error).__name__}: {error}", flush=True)
    _comparison_sheet(comparison_rows)
    all_cases = [row.get("engines", {}).get(engine, {}).get("caseAccepted") is True
                 for row in api_rows for engine in ENGINE_NAMES]
    api_pass = len(all_cases) == len(FAILURE_IDS) * len(ENGINE_NAMES) and all(all_cases)
    renderer_pass = len(renderer_rows) == len(FAILURE_IDS) * len(ENGINE_NAMES) and all(
        row.get("edgeNative", {}).get("shapeValid") and row.get("edgeNative", {}).get("visible") and
        row.get("edgeBeforeAfterComparison", {}).get("alphaIoU", 0) >= 0.999 and
        (row.get("skiaNative", {}).get("status") != "PASS" or
         (row.get("skiaNative", {}).get("shapeValid") and row.get("skiaNative", {}).get("visible") and
          row.get("rendererConsistency"))) for row in renderer_rows
    )
    write_json(TARGET / "api_job_validation.json", {
        "schemaVersion": 1, "finishedAtUtc": datetime.now(timezone.utc).isoformat(),
        "fixtureIds": list(FAILURE_IDS), "engineNames": list(ENGINE_NAMES),
        "engineCaseCount": len(FAILURE_IDS) * len(ENGINE_NAMES),
        "allCasesAccepted": api_pass, "items": api_rows,
    })
    write_json(TARGET / "renderer_validation.json", {
        "schemaVersion": 1, "finishedAtUtc": datetime.now(timezone.utc).isoformat(),
        "edgeExpectedCanvas": "native source (width,height); ndarray shape (height,width,4)",
        "skiaExpectedCanvas": "native source (width,height)",
        "rendererConsistencyThresholdAlphaIoU": 0.98,
        "allNativeRendererChecksPassed": renderer_pass,
        "rendererCaseCount": len(renderer_rows), "items": renderer_rows,
    })
    write_json(TARGET / "nonsquare_regression_results.json", {
        "schemaVersion": 1,
        "landscape451x300": "Smart V2 and Contour direct caller tests; chelsea real API is 451x300",
        "portrait300x451": "Smart V2 and Contour direct caller tests; eagle real API is 1826x2019 portrait",
        "square512x512": "Smart V2 and Contour direct caller tests",
        "realApiFixtureIds": list(FAILURE_IDS),
        "realApiTwoEngineCaseCount": len(FAILURE_IDS) * len(ENGINE_NAMES),
        "apiAllCasesAccepted": api_pass,
        "nativeRendererChecksPassed": renderer_pass,
    })
    return 0 if api_pass and renderer_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
