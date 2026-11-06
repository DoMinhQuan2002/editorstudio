from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BACKEND = Path(__file__).resolve().parents[2]
REPOSITORY = BACKEND.parent
TARGET = BACKEND / "artifacts" / "contour_preserving" / "task_08b_0_1"
DLL = REPOSITORY / "tools" / "VectorDiagnostics" / "bin" / "Debug" / "net10.0" / "VectorDiagnostics.dll"
SVG_NS = "http://www.w3.org/2000/svg"
sys.path.insert(0, str(BACKEND))
from mediastudio.image_tools.vectorization_v2.phase_e1 import find_svg_browser, rasterize_svg  # noqa: E402
from tools.task_08a_1.dataset import MANIFEST, write_json  # noqa: E402


def _bbox(alpha: np.ndarray, threshold: int = 0) -> list[int] | None:
    ys, xs = np.nonzero(alpha > threshold)
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1] if len(xs) else None


def has_visible_artwork(rgba: np.ndarray) -> bool:
    """Visibility is determined from alpha-bearing artwork, not canvas opacity."""
    return bool(rgba.ndim == 3 and rgba.shape[2] == 4 and np.any(rgba[..., 3] > 0))


def rgba_summary(rgba: np.ndarray) -> dict[str, Any]:
    alpha = rgba[..., 3]
    return {
        "canvasWidth": int(rgba.shape[1]), "canvasHeight": int(rgba.shape[0]),
        "alphaNonzeroPixels": int(np.count_nonzero(alpha)),
        "alphaAbove16Pixels": int(np.count_nonzero(alpha > 16)),
        "alphaCoverage": float(np.count_nonzero(alpha > 16) / alpha.size),
        "alphaMax": int(alpha.max(initial=0)),
        "hasVisibleArtwork": has_visible_artwork(rgba),
        "alphaBBoxXYXY": _bbox(alpha),
        "alphaBBoxAbove16XYXY": _bbox(alpha, 16),
    }


def _parse_viewbox(root: ET.Element) -> list[float] | None:
    try:
        values = [float(v) for v in re.split(r"[\s,]+", root.attrib.get("viewBox", "").strip()) if v]
        return values if len(values) == 4 else None
    except ValueError:
        return None


def inspect_xml(svg_path: Path) -> dict[str, Any]:
    raw = svg_path.read_bytes()
    root = ET.fromstring(raw)
    nodes = list(root.iter())
    drawable_names = {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon", "text", "image", "use"}
    drawables = [node for node in nodes if node.tag.rsplit("}", 1)[-1].casefold() in drawable_names]
    transforms = []
    opacity_nodes = []
    clip_refs, mask_refs = [], []
    none_paint_count = 0
    for node in nodes:
        tag = node.tag.rsplit("}", 1)[-1]
        attrs = node.attrib
        if "transform" in attrs:
            transforms.append({"element": tag, "id": attrs.get("id"), "transform": attrs["transform"]})
        for key in ("opacity", "fill-opacity", "stroke-opacity", "display", "visibility"):
            if key in attrs:
                opacity_nodes.append({"element": tag, "id": attrs.get("id"), "attribute": key, "value": attrs[key]})
        for attr in ("clip-path", "mask"):
            if attr in attrs:
                row = {"element": tag, "id": attrs.get("id"), "value": attrs[attr]}
                (clip_refs if attr == "clip-path" else mask_refs).append(row)
        if attrs.get("fill", "").strip().casefold() == "none" and attrs.get("stroke", "none").strip().casefold() == "none":
            none_paint_count += 1
    styles = [n.attrib.get("style", "") for n in nodes if n.attrib.get("style")]
    vb = _parse_viewbox(root)
    return {
        "path": str(svg_path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
        "xmlValid": True, "rootTag": root.tag, "declaredWidth": root.attrib.get("width"),
        "declaredHeight": root.attrib.get("height"), "viewBox": root.attrib.get("viewBox"),
        "viewBoxNumbers": vb,
        "drawableElementCount": len(drawables),
        "elementCounts": {name: sum(n.tag.rsplit("}", 1)[-1].casefold() == name for n in nodes)
                          for name in sorted({n.tag.rsplit("}", 1)[-1].casefold() for n in nodes})},
        "transformCount": len(transforms), "transforms": transforms[:200],
        "opacityVisibilityAttributeCount": len(opacity_nodes), "opacityVisibilityAttributes": opacity_nodes[:200],
        "clipReferenceCount": len(clip_refs), "clipReferences": clip_refs[:200],
        "maskReferenceCount": len(mask_refs), "maskReferences": mask_refs[:200],
        "gradientDefinitionCount": sum(n.tag.rsplit("}", 1)[-1].casefold() in {"lineargradient", "radialgradient"} for n in nodes),
        "gradientStopCount": sum(n.tag.rsplit("}", 1)[-1].casefold() == "stop" for n in nodes),
        "unpaintedDrawableCount": none_paint_count,
        "inlineStyleAttributes": styles[:100],
    }


def skia_inspect(svg_path: Path) -> dict[str, Any]:
    process = subprocess.run(["dotnet", str(DLL), "--inspect", str(svg_path)], capture_output=True,
                             text=True, timeout=90, check=False)
    if process.returncode:
        return {"status": "FAIL", "returnCode": process.returncode, "stderr": process.stderr[-2000:]}
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError:
        return {"status": "FAIL", "stdout": process.stdout[-2000:], "stderr": process.stderr[-2000:]}


def render_skia(svg_path: Path, output_path: Path, width: int, height: int) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.run(["dotnet", str(DLL), "--render-canvas", str(svg_path), str(output_path), str(width), str(height)],
                             capture_output=True, text=True, timeout=90, check=False)
    if process.returncode or not output_path.is_file():
        return {"status": "FAIL", "returnCode": process.returncode, "stdout": process.stdout[-1000:], "stderr": process.stderr[-2000:]}
    with Image.open(output_path) as image:
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    return {"status": "PASS", "renderer": "Svg.Skia 5.2.3", "outputPath": str(output_path),
            "summary": rgba_summary(rgba), "rgba": rgba}


def render_edge(svg_path: Path, width: int, height: int, browser: str) -> np.ndarray:
    return np.asarray(rasterize_svg(svg_path.read_text(encoding="utf-8"), expected_size=(width, height), browser=browser), dtype=np.uint8)


def alpha_iou(first: np.ndarray, second: np.ndarray, threshold: int = 16) -> float:
    a, b = first[..., 3] > threshold, second[..., 3] > threshold
    return float(np.count_nonzero(a & b) / max(np.count_nonzero(a | b), 1))


def _composite(rgba: np.ndarray, background: tuple[int, int, int]) -> np.ndarray:
    alpha = rgba[..., 3:4].astype(np.float32) / 255.0
    bg = np.empty_like(rgba[..., :3]); bg[:] = background
    return np.clip(rgba[..., :3].astype(np.float32) * alpha + bg.astype(np.float32) * (1.0 - alpha), 0, 255).astype(np.uint8)


def _checker(rgba: np.ndarray, cell: int = 12) -> np.ndarray:
    height, width = rgba.shape[:2]
    yy, xx = np.indices((height, width))
    board = np.where(((xx // cell + yy // cell) % 2)[..., None] == 0, 232, 197).astype(np.uint8)
    alpha = rgba[..., 3:4].astype(np.float32) / 255.0
    return np.clip(rgba[..., :3] * alpha + board * (1 - alpha), 0, 255).astype(np.uint8)


def _label(image: np.ndarray, label: str, out_size: tuple[int, int]) -> Image.Image:
    source = Image.fromarray(image, "RGB")
    source.thumbnail((out_size[0] - 20, out_size[1] - 48), Image.Resampling.LANCZOS)
    panel = Image.new("RGB", out_size, "white")
    draw = ImageDraw.Draw(panel)
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    draw.text((10, 8), label, fill=(18, 24, 39), font=font)
    panel.paste(source, ((out_size[0] - source.width) // 2, 36 + (out_size[1] - 48 - source.height) // 2))
    return panel


def analyze_capture(record: dict[str, Any], manifest_item: dict[str, Any], browser: str) -> dict[str, Any]:
    image_id = str(record["imageId"])
    source_path = REPOSITORY / manifest_item["path"]
    with Image.open(source_path) as image:
        source_rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        width, height = image.size
    source_dir = TARGET / "reruns" / image_id
    engine_results = []
    for capture in record.get("captures", []):
        svg_path = Path(capture["svgPath"])
        xml_report = inspect_xml(svg_path)
        inspect_report = skia_inspect(svg_path)
        expected_call = capture.get("expectedSizeArgument", [])
        api_image = None
        api_path = capture.get("edgeRenderPath")
        if api_path and Path(api_path).is_file():
            with Image.open(api_path) as image:
                api_image = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        correct_edge = render_edge(svg_path, width, height, browser)
        correct_edge_path = svg_path.parent / "edge_render_correct_canvas.png"
        Image.fromarray(correct_edge, "RGBA").save(correct_edge_path)
        skia_path = svg_path.parent / "skia_render_correct_canvas.png"
        skia = render_skia(svg_path, skia_path, width, height)
        skia_rgba = skia.pop("rgba", None)
        correct_report = rgba_summary(correct_edge)
        api_report = rgba_summary(api_image) if api_image is not None else None
        skia_report = skia.get("summary")
        rendered_visible = bool(correct_report["alphaAbove16Pixels"] > 0)
        skia_visible = bool(skia_report and skia_report["alphaAbove16Pixels"] > 0)
        match_both = rendered_visible and skia_visible
        root_cause = "UNKNOWN"
        if (api_report and api_report["alphaAbove16Pixels"] > 0 and
                (api_report["canvasWidth"], api_report["canvasHeight"]) != (width, height) and match_both):
            root_cause = "EXPECTED_SIZE_AXIS_ORDER_MISMATCH"
        elif inspect_report.get("status") == "PASS" and inspect_report.get("cullBounds"):
            bounds = inspect_report["cullBounds"]
            vb = xml_report.get("viewBoxNumbers")
            if vb and (bounds["right"] <= vb[0] or bounds["bottom"] <= vb[1] or
                       bounds["left"] >= vb[0] + vb[2] or bounds["top"] >= vb[1] + vb[3]):
                root_cause = "SVG_VIEWBOX_OR_BOUNDS_ERROR"
            elif xml_report["maskReferenceCount"] or xml_report["clipReferenceCount"] or xml_report["opacityVisibilityAttributeCount"]:
                if not rendered_visible and not skia_visible:
                    root_cause = "SVG_CLIP_MASK_OPACITY_ERROR"
            if not rendered_visible and not skia_visible and root_cause == "UNKNOWN":
                root_cause = "SVG_COMPOSITION_EMPTY" if xml_report["drawableElementCount"] == 0 else "GEOMETRY_EMPTY"
        if rendered_visible != skia_visible:
            root_cause = "RENDERER_INCONSISTENCY"
        background_metrics: dict[str, Any] = {}
        if skia_rgba is not None and skia_rgba.shape == correct_edge.shape:
            alpha_mae = float(np.abs(correct_edge[..., 3].astype(np.float32) - skia_rgba[..., 3].astype(np.float32)).mean())
            background_metrics = {"transparentRgbaMeanAbsoluteError": float(np.abs(correct_edge.astype(np.float32) - skia_rgba.astype(np.float32)).mean()),
                                  "alphaMeanAbsoluteError": alpha_mae,
                                  "alphaIoUAt16": alpha_iou(correct_edge, skia_rgba)}
            for name, background in (("white", (255, 255, 255)), ("black", (0, 0, 0))):
                edge_composite = _composite(correct_edge, background)
                skia_composite = _composite(skia_rgba, background)
                background_metrics[f"{name}RgbMeanAbsoluteError"] = float(np.abs(edge_composite.astype(np.float32) - skia_composite.astype(np.float32)).mean())
                Image.fromarray(edge_composite, "RGB").save(svg_path.parent / f"edge_on_{name}.png")
                Image.fromarray(skia_composite, "RGB").save(svg_path.parent / f"skia_on_{name}.png")
        result = {
            "imageId": image_id, "sourceFamilyId": manifest_item.get("sourceFamilyId"),
            "engine": capture["engine"], "sourcePath": str(source_path),
            "sourceSha256": manifest_item["sha256"], "sourceCanvas": [width, height],
            "sourceAlpha": rgba_summary(source_rgba), "apiExpectedSizeArgument": expected_call,
            "apiRender": api_report, "apiRenderVisible": bool(api_report and api_report["alphaAbove16Pixels"] > 0),
            "svg": xml_report, "svgPathBoundsSvgSkia": inspect_report,
            "edgeCorrectCanvas": {"renderer": "Edge/Chromium headless", "path": str(correct_edge_path), **correct_report},
            "skiaCorrectCanvas": {k: v for k, v in skia.items() if k != "rgba"},
            "edgeSkiaAlphaIoU": alpha_iou(correct_edge, skia_rgba) if skia_rgba is not None else None,
            "backgroundComparison": background_metrics,
            "rootCause": root_cause,
            "firstVerifiedFailingStage": "final SVG rasterization/visibility dimension validation",
            "evidence": [
                "SVG was serialized and reached the production render-validation call.",
                f"Output viewBox={xml_report.get('viewBox')}; drawable elements={xml_report['drawableElementCount']}.",
                f"API renderer canvas is {api_report['canvasWidth']}x{api_report['canvasHeight'] if api_report else 'n/a'}; expected source canvas is {width}x{height}.",
                f"Correct-canvas Edge alpha pixels={correct_report['alphaAbove16Pixels']}; Svg.Skia alpha pixels={skia_report.get('alphaAbove16Pixels') if skia_report else 'n/a'}.",
            ],
        }
        case_panels: list[Image.Image] = []
        if api_image is None:
            api_display = np.zeros((height, width, 4), dtype=np.uint8)
        else:
            api_display = api_image
        case_panels.extend([
            _label(_composite(source_rgba, (255, 255, 255)), "Source on white", (420, 360)),
            _label(_checker(api_display), f"API validation render ({api_display.shape[1]}x{api_display.shape[0]})", (420, 360)),
            _label(_checker(correct_edge), "Edge corrected canvas", (420, 360)),
            _label(_checker(skia_rgba if skia_rgba is not None else np.zeros_like(correct_edge)), "Svg.Skia corrected canvas", (420, 360)),
        ])
        sheet = Image.new("RGB", (840, 720), (242, 243, 246))
        for index, panel in enumerate(case_panels):
            sheet.paste(panel, ((index % 2) * 420, (index // 2) * 360))
        compare_path = TARGET / "renderer_comparisons" / f"{image_id}_{capture['engine']}.png"
        compare_path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(compare_path)
        result["rendererComparisonPng"] = str(compare_path)
        engine_results.append(result)
    return {"imageId": image_id, "engines": engine_results}


def run_controls() -> dict[str, Any]:
    controls = {
        "visible_valid": '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><rect x="10" y="10" width="80" height="80" fill="#e32636"/></svg>',
        "outside_viewbox": '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><rect x="120" y="120" width="20" height="20" fill="#e32636"/></svg>',
        "hidden_opacity": '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><rect x="10" y="10" width="80" height="80" fill="#e32636" opacity="0"/></svg>',
        "hidden_mask": '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><defs><mask id="m"><rect width="100" height="100" fill="black"/></mask></defs><rect x="10" y="10" width="80" height="80" fill="#e32636" mask="url(#m)"/></svg>',
        "transparent_background_visible_art": '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><circle cx="50" cy="50" r="30" fill="#e32636"/></svg>',
    }
    result = {"canvas": [100, 100], "controls": []}
    browser = find_svg_browser()
    for name, svg in controls.items():
        path = TARGET / "controls" / f"{name}.svg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(svg, encoding="utf-8")
        edge = np.asarray(rasterize_svg(svg, expected_size=(100, 100), browser=browser), dtype=np.uint8)
        edge_path = path.with_suffix(".edge.png")
        Image.fromarray(edge, "RGBA").save(edge_path)
        skia_path = path.with_suffix(".skia.png")
        skia = render_skia(path, skia_path, 100, 100)
        skia_rgba = skia.pop("rgba", None)
        summary = rgba_summary(edge)
        skia_summary = skia.get("summary")
        expected_visible = name in {"visible_valid", "transparent_background_visible_art"}
        edge_visible = summary["alphaNonzeroPixels"] > 0
        skia_visible = bool(skia_summary and skia_summary["alphaNonzeroPixels"] > 0)
        result["controls"].append({"id": name, "svgPath": str(path), "edgeRenderPath": str(edge_path),
            "edge": summary, "skia": skia, "expectedVisible": expected_visible,
            "edgeDetectorVisible": edge_visible, "skiaDetectorVisible": skia_visible,
            "rendererExpectationPass": edge_visible == expected_visible and skia_visible == expected_visible,
            "detectorVisible": edge_visible})
    result["transparentBackgroundDetectorPass"] = next(row for row in result["controls"] if row["id"] == "transparent_background_visible_art")["edgeDetectorVisible"]
    result["hiddenOpacityIsEmpty"] = next(row for row in result["controls"] if row["id"] == "hidden_opacity")["edge"]["alphaNonzeroPixels"] == 0
    result["outsideViewBoxIsEmpty"] = next(row for row in result["controls"] if row["id"] == "outside_viewbox")["edge"]["alphaNonzeroPixels"] == 0
    result["transparentControlHasTransparentCanvasPixels"] = next(row for row in result["controls"] if row["id"] == "transparent_background_visible_art")["edge"]["alphaNonzeroPixels"] < 100 * 100
    result["allRendererExpectationsPass"] = all(row["rendererExpectationPass"] for row in result["controls"])
    return result


def main() -> int:
    capture_path = TARGET / "rerun_capture_results.json"
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest_items = {str(row["imageId"]): row for row in manifest["items"]}
    browser = find_svg_browser()
    if not browser:
        raise RuntimeError("Edge/Chrome headless renderer not available")
    summaries = []
    for item in capture.get("items", []):
        if len(item.get("captures", [])) != 2:
            summaries.append({"imageId": item.get("imageId"), "status": "CAPTURE_INCOMPLETE"})
            continue
        print(f"Analyzing {item['imageId']} SVG captures", flush=True)
        summaries.append(analyze_capture(item, manifest_items[str(item["imageId"])], browser))
    flattened = [engine for row in summaries for engine in row.get("engines", [])]
    write_json(TARGET / "svg_visibility_diagnostics.json", {"schemaVersion": 1, "browser": browser,
        "caseCount": len(flattened), "items": flattened})
    write_json(TARGET / "renderer_comparison.json", {"schemaVersion": 1, "comparisonCanvasPolicy": "source dimensions; transparent RGBA; composites evaluated on white, black and checkerboard",
        "items": [{k: row.get(k) for k in ("imageId", "engine", "sourceCanvas", "apiExpectedSizeArgument", "apiRender", "edgeCorrectCanvas", "skiaCorrectCanvas", "edgeSkiaAlphaIoU", "backgroundComparison", "rendererComparisonPng")}
                  for row in flattened]})
    write_json(TARGET / "visibility_test_results.json", run_controls())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
