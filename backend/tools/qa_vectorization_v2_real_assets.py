"""Run release AUTO/QUALITY checks against the repository's real Active Fox assets."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import time
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mediastudio.image_tools.vectorization_v2.phase_e1 import rasterize_svg
from mediastudio.image_tools.vectorization_v2.production import run_vectorization_v2

ASSETS = {
    "active_fox_low_res_jpg": ROOT / "tests" / "fixtures" / "active_fox.jpg",
    "active_fox_user_8x_png": ROOT / "tests" / "fixtures" / "active_fox_upscaled_8x.png",
}
OUT = ROOT / "artifacts" / "vector_v2_product" / "real_image_qa"
SVG_NS = "http://www.w3.org/2000/svg"


def _source_rgb_and_mask(path: Path, work_size: int) -> tuple[np.ndarray, np.ndarray]:
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert("RGBA")
    if image.size != (work_size, work_size):
        image = image.resize((work_size, work_size), Image.Resampling.LANCZOS)
    array = np.asarray(image, dtype=np.uint8)
    rgb = array[..., :3].astype(np.float32)
    if np.any(array[..., 3] < 250):
        mask = array[..., 3] > 24
    else:
        border = np.concatenate((rgb[:4].reshape(-1, 3), rgb[-4:].reshape(-1, 3),
                                 rgb[:, :4].reshape(-1, 3), rgb[:, -4:].reshape(-1, 3)), axis=0)
        estimated_background = np.median(border, axis=0)
        mask = np.linalg.norm(rgb - estimated_background[None, None, :], axis=2) > 12.0
    return rgb, mask


def _render_metrics(source: np.ndarray, source_mask: np.ndarray,
                    render: np.ndarray) -> dict[str, float | int]:
    rgba = np.asarray(render, dtype=np.uint8)
    alpha = rgba[..., 3:4].astype(np.float32) / 255.0
    output_rgb = rgba[..., :3].astype(np.float32) * alpha + 255.0 * (1.0 - alpha)
    source_composite = source
    delta = np.linalg.norm(source_composite - output_rgb, axis=2)
    output_mask = rgba[..., 3] > 24
    roi = source_mask | output_mask
    inter = int(np.count_nonzero(source_mask & output_mask))
    union = int(np.count_nonzero(roi))
    values = delta[roi]
    return {
        "meanRgbDeltaForeground": round(float(values.mean()) if values.size else 0.0, 4),
        "p95RgbDeltaForeground": round(float(np.quantile(values, 0.95)) if values.size else 0.0, 4),
        "foregroundIoU": round(inter / max(1, union), 6),
        "sourceForegroundPixels": int(source_mask.sum()),
        "outputForegroundPixels": int(output_mask.sum()),
    }


def _background_montage(render: np.ndarray) -> Image.Image:
    image = Image.fromarray(render, "RGBA")
    width, height = image.size
    checker = Image.new("RGB", (width, height), "white")
    cell = max(8, width // 20)
    draw = ImageDraw.Draw(checker)
    for y in range(0, height, cell):
        for x in range(0, width, cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=(220, 222, 227))
    backgrounds = [
        ("white", Image.new("RGB", (width, height), "white")),
        ("black", Image.new("RGB", (width, height), "black")),
        ("gray", Image.new("RGB", (width, height), (128, 128, 128))),
        ("checker", checker),
    ]
    tiles = []
    for label, base in backgrounds:
        base.paste(image, mask=image.getchannel("A"))
        tile = base.resize((320, 320), Image.Resampling.LANCZOS)
        ImageDraw.Draw(tile).text((10, 8), label, fill=(255, 0, 120) if label == "black" else (24, 24, 30))
        tiles.append(tile)
    montage = Image.new("RGB", (640, 640), "white")
    for index, tile in enumerate(tiles):
        montage.paste(tile, ((index % 2) * 320, (index // 2) * 320))
    return montage


def main() -> int:
    model_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MediaStudio" / "models" / "easyocr"
    output: dict[str, object] = {
        "suite": "Vectorization V2 real-image release checks",
        "assetSource": "repository test fixtures; Active Fox user-provided artwork family",
        "coverageNote": "Both real files depict the same logo. They cover a low-resolution JPG and a multicolor gradient/text/detail logo, but do not represent separate no-text, transparent, or unrelated icon examples.",
        "results": [],
    }
    for asset_name, source_path in ASSETS.items():
        for mode in ("auto", "quality"):
            destination = OUT / mode / asset_name
            destination.mkdir(parents=True, exist_ok=True)
            svg_path = destination / f"{asset_name}_{mode}.svg"
            started = time.perf_counter()
            metrics, size = run_vectorization_v2(
                source_path, svg_path, models_directory=model_dir,
                mode=mode, text_mode="outlined",
            )
            svg_text = svg_path.read_text(encoding="utf-8")
            root = ET.fromstring(svg_text)
            width, height = int(root.attrib["width"]), int(root.attrib["height"])
            view_box = root.attrib.get("viewBox", "")
            working_width, working_height = int(metrics["workingWidth"]), int(metrics["workingHeight"])
            # The WPF preview renders the exact SVG bytes at its viewBox bounds.
            preview_root = ET.fromstring(svg_text)
            preview_root.set("width", str(working_width))
            preview_root.set("height", str(working_height))
            preview_svg = ET.tostring(preview_root, encoding="unicode")
            render = rasterize_svg(preview_svg, expected_size=(working_height, working_width))
            Image.fromarray(render, "RGBA").save(destination / "preview.png")
            _background_montage(render).save(destination / "backgrounds.png")
            source_rgb, source_mask = _source_rgb_and_mask(source_path, working_width)
            comparison = _render_metrics(source_rgb, source_mask, render)
            ns = {"s": SVG_NS}
            graphic_paths = len(root.findall(".//s:g[@id='graphic']//s:path", ns))
            typography_paths = len(root.findall(".//s:g[@id='typography']//s:path", ns))
            text_elements = len(root.findall(".//s:g[@id='typography']//s:text", ns))
            embedded_rasters = len(root.findall(".//s:image", ns))
            phase_d1 = metrics.get("phaseD1", {})
            record = {
                "fixture": asset_name,
                "input": str(source_path.relative_to(ROOT)),
                "mode": mode,
                "sourceWidth": metrics["inputWidth"], "sourceHeight": metrics["inputHeight"],
                "workingWidth": working_width, "workingHeight": working_height,
                "svgWidth": width, "svgHeight": height, "viewBox": view_box,
                "pipeline": metrics.get("pipeline"),
                "pathCount": metrics.get("pathCount"), "graphicPathCount": graphic_paths,
                "textLayerCount": metrics.get("textLayerCount"),
                "outlinedTextPathCount": typography_paths,
                "textElementCount": text_elements,
                "gradientCount": metrics.get("gradientCount"),
                "embeddedRasterCount": embedded_rasters,
                "ocrStatus": metrics.get("ocrStatus"),
                "geometrySelfIntersectionCount": phase_d1.get("self_intersection_count"),
                "geometryStatus": "PASS" if phase_d1.get("self_intersection_count", 0) == 0 else "ISSUES",
                "svgValidXml": True,
                "renderValidated": metrics.get("renderValidated"),
                "visualDifferenceMetrics": comparison,
                "warnings": metrics.get("warningDetails", []),
                "processingTimeMs": metrics.get("processingTimeMs"),
                "phaseTimingsMs": metrics.get("phaseTimingsMs"),
                "wallTimeMs": round((time.perf_counter() - started) * 1000),
                "svgBytes": size,
                "svgSha256": hashlib.sha256(svg_path.read_bytes()).hexdigest(),
                "svgPath": str(svg_path.relative_to(ROOT)),
                "previewPath": str((destination / "preview.png").relative_to(ROOT)),
                "backgroundMontagePath": str((destination / "backgrounds.png").relative_to(ROOT)),
                "functionalStatus": "PASS" if embedded_rasters == 0 and graphic_paths > 0 and metrics.get("renderValidated") else "FAIL",
                "visualQualityValidated": False,
            }
            output["results"].append(record)
            print(json.dumps(record, ensure_ascii=True), flush=True)
    (OUT / "real_image_qa_report.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"REPORT {OUT / 'real_image_qa_report.json'}", flush=True)
    return 0 if all(record["functionalStatus"] == "PASS" for record in output["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
