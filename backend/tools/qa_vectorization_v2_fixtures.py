"""Run the production V2 stack over small, deterministic fixture categories.

This is product QA, not a new model or a semantic test set. The inputs are
synthetic representatives for the categories required in the release checklist.
Run from backend/ with the project venv Python.
"""
from __future__ import annotations

import json
import argparse
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mediastudio.image_tools.vectorization_v2.phase_e1 import rasterize_svg
from mediastudio.image_tools.vectorization_v2.production import run_vectorization_v2

SVG_NS = "http://www.w3.org/2000/svg"
SIZE = 320
OUT = ROOT / "artifacts" / "vector_v2_product" / "fixture_matrix"


def _font(bold: bool, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidate = Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf")
    try:
        return ImageFont.truetype(str(candidate), size)
    except OSError:
        return ImageFont.load_default()


def _gradient(size: tuple[int, int], start: tuple[int, int, int],
              end: tuple[int, int, int]) -> Image.Image:
    width, height = size
    top = np.asarray(start, dtype=np.float32)
    bottom = np.asarray(end, dtype=np.float32)
    values = np.linspace(0, 1, height, dtype=np.float32)[:, None, None]
    row = top[None, None, :] * (1 - values) + bottom[None, None, :] * values
    arr = np.broadcast_to(row, (height, width, 3)).astype(np.uint8).copy()
    return Image.fromarray(arr, "RGB")


def _make_fixtures() -> list[tuple[str, Path, str]]:
    OUT.mkdir(parents=True, exist_ok=True)
    fixtures: list[tuple[str, Path, str]] = []

    # Flat-color logo with a simple two-piece mark and wordmark.
    image = Image.new("RGB", (SIZE, SIZE), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((94, 34, 226, 166), fill="#4B3DB8")
    draw.polygon([(134, 55), (191, 101), (134, 145), (149, 101)], fill="#FFD34D")
    draw.text((160, 218), "FLAT", font=_font(True, 34), fill="#241431", anchor="mm")
    path = OUT / "flat_color_logo.png"
    image.save(path)
    fixtures.append(("flat_color_logo", path, "flat-color logo"))

    # Per-pixel gradient clipped to an emblem, with a clean background.
    image = Image.new("RGB", (SIZE, SIZE), "white")
    gradient = _gradient((154, 142), (255, 214, 40), (242, 57, 24)).convert("RGBA")
    mask = Image.new("L", gradient.size, 0)
    ImageDraw.Draw(mask).ellipse((2, 2, 151, 139), fill=255)
    image.paste(gradient, (83, 30), mask)
    ImageDraw.Draw(image).polygon([(136, 66), (207, 103), (138, 138), (158, 103)], fill="white")
    path = OUT / "gradient_logo.png"
    image.save(path)
    fixtures.append(("gradient_logo", path, "gradient logo"))

    # Logo with two high-contrast text lines to exercise OCR/text reconstruction.
    image = Image.new("RGB", (SIZE, SIZE), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((113, 28, 207, 122), radius=22, fill="#EF6C2F")
    draw.polygon([(160, 43), (188, 76), (160, 108), (132, 76)], fill="#FFE28A")
    draw.text((160, 184), "VECTOR", font=_font(True, 31), fill="#32133F", anchor="mm")
    draw.text((160, 223), "IMAGE STUDIO", font=_font(False, 17), fill="#32133F", anchor="mm")
    path = OUT / "logo_with_text.png"
    image.save(path)
    fixtures.append(("logo_with_text", path, "logo with text"))

    # Icon-only artwork; no expected typography.
    image = Image.new("RGB", (SIZE, SIZE), "#FAFAF8")
    draw = ImageDraw.Draw(image)
    draw.ellipse((205, 34, 260, 89), fill="#F6C744")
    draw.polygon([(38, 210), (126, 83), (210, 210)], fill="#286D62")
    draw.polygon([(105, 210), (196, 108), (278, 210)], fill="#55927C")
    draw.rectangle((142, 178, 173, 234), fill="#F4EEE2")
    path = OUT / "icon_no_text.png"
    image.save(path)
    fixtures.append(("icon_no_text", path, "icon without text"))

    # Transparent PNG with anti-aliased overlapping colored vector-like shapes.
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((70, 47, 250, 227), fill=(43, 148, 92, 255))
    draw.polygon([(103, 180), (156, 87), (218, 180)], fill=(242, 194, 58, 255))
    draw.ellipse((140, 136, 190, 186), fill=(255, 255, 255, 255))
    path = OUT / "transparent_png.png"
    image.save(path)
    fixtures.append(("transparent_png", path, "transparent PNG"))

    # JPG with deliberately visible compression ringing around high-contrast edges.
    jpeg_source = Image.new("RGB", (SIZE, SIZE), "white")
    draw = ImageDraw.Draw(jpeg_source)
    draw.ellipse((68, 48, 250, 230), fill="#F47920")
    draw.polygon([(83, 198), (168, 67), (236, 198)], fill="#322044")
    draw.rectangle((110, 145, 215, 164), fill="#F9D758")
    jpg_path = OUT / "jpg_artifacts.jpg"
    jpeg_source.save(jpg_path, quality=28, subsampling=2)
    fixtures.append(("jpg_artifacts", jpg_path, "JPEG artifacts"))

    # Higher-detail illustrative scene: multiple layered contours and gradients.
    sky = _gradient((SIZE, SIZE), (128, 197, 231), (239, 246, 239)).convert("RGBA")
    draw = ImageDraw.Draw(sky)
    draw.ellipse((224, 32, 277, 85), fill="#FFD566")
    draw.polygon([(0, 209), (68, 111), (133, 206), (205, 105), (320, 218), (320, 320), (0, 320)],
                 fill="#477A79")
    draw.polygon([(0, 246), (81, 174), (148, 240), (237, 152), (320, 250), (320, 320), (0, 320)],
                 fill="#2F5E59")
    draw.polygon([(0, 272), (97, 222), (170, 268), (262, 211), (320, 265), (320, 320), (0, 320)],
                 fill="#6B9B78")
    draw.rectangle((36, 218, 43, 269), fill="#614A35")
    draw.polygon([(19, 228), (40, 181), (62, 228)], fill="#1E5746")
    draw.polygon([(23, 209), (40, 169), (57, 209)], fill="#32724F")
    scene_path = OUT / "complex_illustration.png"
    sky.save(scene_path)
    fixtures.append(("complex_illustration", scene_path, "complex illustration"))
    return fixtures


def _check_svg(svg_text: str) -> dict[str, int | bool]:
    root = ET.fromstring(svg_text)
    if root.tag != f"{{{SVG_NS}}}svg":
        raise ValueError("SVG root or namespace is invalid")
    paths = root.findall(f".//{{{SVG_NS}}}path")
    images = root.findall(f".//{{{SVG_NS}}}image")
    if not paths or images:
        raise ValueError(f"expected real vector paths and no raster image embed (paths={len(paths)}, images={len(images)})")
    for path in paths:
        if not path.attrib.get("d", "").strip():
            raise ValueError("empty SVG path")
    return {
        "validXml": True,
        "hasVectorPaths": bool(paths),
        "embeddedRasterCount": len(images),
        "pathCount": len(paths),
        "gradientCount": len(root.findall(f".//{{{SVG_NS}}}linearGradient") +
                                 root.findall(f".//{{{SVG_NS}}}radialGradient")),
        "textElementCount": len(root.findall(f".//{{{SVG_NS}}}text")),
    }


def _compare_render_to_source(source_path: Path, rendered: np.ndarray) -> dict[str, float | int]:
    with Image.open(source_path) as image:
        source = image.convert("RGBA")
    source_rgba = np.asarray(source, dtype=np.uint8)
    source_rgb = source_rgba[..., :3].astype(np.float32)
    source_alpha = source_rgba[..., 3]
    rendered_rgba = np.asarray(rendered, dtype=np.uint8)
    white = np.full_like(source_rgb, 255)
    source_composite = source_rgb * (source_alpha[..., None] / 255.0) + white * (1 - source_alpha[..., None] / 255.0)
    rendered_composite = (rendered_rgba[..., :3].astype(np.float32) *
                          (rendered_rgba[..., 3:4].astype(np.float32) / 255.0) +
                          white * (1 - rendered_rgba[..., 3:4].astype(np.float32) / 255.0))
    difference = np.linalg.norm(source_composite - rendered_composite, axis=2)
    if np.any(source_alpha < 250):
        source_foreground = source_alpha > 24
    else:
        source_foreground = np.linalg.norm(source_rgb - 255.0, axis=2) > 18.0
    output_foreground = rendered_rgba[..., 3] > 24
    union = int(np.count_nonzero(source_foreground | output_foreground))
    intersection = int(np.count_nonzero(source_foreground & output_foreground))
    foreground_delta = difference[source_foreground | output_foreground]
    return {
        "meanRgbDeltaForeground": round(float(foreground_delta.mean()) if foreground_delta.size else 0.0, 4),
        "p95RgbDeltaForeground": round(float(np.quantile(foreground_delta, 0.95)) if foreground_delta.size else 0.0, 4),
        "foregroundIoU": round(intersection / max(1, union), 6),
        "sourceForegroundPixels": int(source_foreground.sum()),
        "outputForegroundPixels": int(output_foreground.sum()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", nargs="+", choices=("auto", "fast", "quality"), default=["fast"])
    args = parser.parse_args()
    fixtures = _make_fixtures()
    model_dir = Path(__import__("os").environ.get("LOCALAPPDATA", str(Path.home()))) / "MediaStudio" / "models" / "easyocr"
    exit_code = 0
    combined: dict[str, object] = {"suite": "Vectorization V2 synthetic fixture matrix",
                                  "note": "All fixtures in this matrix are synthetic; they validate functional, geometry, and source-difference metrics but are not real-artwork quality evidence.",
                                  "modes": {}}
    for mode in args.modes:
        mode_out = OUT / "modes" / mode
        mode_out.mkdir(parents=True, exist_ok=True)
        records: list[dict[str, object]] = []
        for name, input_path, category in fixtures:
            output_path = mode_out / f"{name}_v2.svg"
            started = time.perf_counter()
            metrics, output_size = run_vectorization_v2(
                input_path, output_path, models_directory=model_dir,
                mode=mode, text_mode="outlined",
            )
            svg_text = output_path.read_text(encoding="utf-8")
            checks = _check_svg(svg_text)
            with Image.open(input_path) as image:
                width, height = image.size
            root = ET.fromstring(svg_text)
            if root.attrib.get("viewBox") != f"0 0 {width} {height}":
                raise ValueError(f"{name}: SVG viewBox does not match source canvas")
            rendered = rasterize_svg(svg_text, expected_size=(height, width))
            if rendered.shape != (height, width, 4) or not np.any(rendered[..., 3] > 0):
                raise ValueError(f"{name}: final SVG preview is blank or has the wrong size")
            Image.fromarray(rendered, "RGBA").save(mode_out / f"{name}_render.png")
            comparison = _compare_render_to_source(input_path, rendered)
            phase_d1 = metrics.get("phaseD1", {})
            self_intersections = int(phase_d1.get("self_intersection_count", 0))
            details = metrics.get("warningDetails", [])
            functional_pass = bool(checks["validXml"] and checks["hasVectorPaths"] and
                                   checks["embeddedRasterCount"] == 0 and
                                   metrics.get("pipeline") == "vectorization_v2" and
                                   metrics.get("renderValidated"))
            geometry_pass = self_intersections == 0
            record = {
                "fixture": name, "category": category,
                "input": str(input_path.relative_to(ROOT)),
                "outputSvg": str(output_path.relative_to(ROOT)),
                "renderPng": str((mode_out / f"{name}_render.png").relative_to(ROOT)),
                "mode": mode, "inputWidth": width, "inputHeight": height,
                "inputBytes": input_path.stat().st_size, "outputBytes": output_size,
                **checks, "pipeline": metrics.get("pipeline"),
                "ocrStatus": metrics.get("ocrStatus"),
                "textMode": metrics.get("textMode"),
                "textLayerCount": metrics.get("textLayerCount"),
                "outlinedTextPathCount": metrics.get("outlinedTextPathCount"),
                "textElementCount": metrics.get("textElementCount"),
                "embeddedRasterCount": metrics.get("embeddedRasterCount"),
                "geometrySelfIntersectionCount": self_intersections,
                "geometryStatus": "PASS" if geometry_pass else "ISSUES",
                "visualDifferenceMetrics": comparison,
                "processingTimeMs": metrics.get("processingTimeMs"),
                "phaseTimingsMs": metrics.get("phaseTimingsMs"),
                "warningDetails": details,
                "warningCount": sum(item.get("level") in {"WARNING", "ERROR"} for item in details),
                "infoCount": sum(item.get("level") == "INFO" for item in details),
                "previewValidated": True,
                "elapsedWallMs": round((time.perf_counter() - started) * 1000),
                "functionalStatus": "PASS" if functional_pass else "FAIL",
                "visualQualityStatus": "METRICS_RECORDED_NOT_RELEASE_VALIDATED",
            }
            records.append(record)
            print(json.dumps(record, ensure_ascii=True), flush=True)
        report = {
            "mode": mode, "fixtureCount": len(records),
            "functionalPassCount": sum(record["functionalStatus"] == "PASS" for record in records),
            "functionalFailCount": sum(record["functionalStatus"] != "PASS" for record in records),
            "geometryValidCount": sum(record["geometryStatus"] == "PASS" for record in records),
            "visualQualityValidated": False,
            "results": records,
        }
        (OUT / f"fixture_matrix_report_{mode}.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        combined["modes"][mode] = report
        if report["functionalFailCount"]:
            exit_code = 1
    combined_path = OUT / "fixture_matrix_report_auto_quality.json"
    combined_path.write_text(json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"REPORT {combined_path}", flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
