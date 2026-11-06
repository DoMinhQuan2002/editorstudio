from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np
from PIL import Image


BACKEND = Path(__file__).resolve().parents[2]
REPOSITORY = BACKEND.parent
TASK071 = BACKEND / "artifacts" / "contour_preserving" / "task_07_1"
sys.path.insert(0, str(BACKEND / "tools"))
sys.path.insert(0, str(TASK071))

from mediastudio.image_tools.vectorization_v2.phase_e1 import find_svg_browser, rasterize_svg  # noqa: E402

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
PATH_COMMAND = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]")
URL_REFERENCE = re.compile(r"url\(\s*['\"]?#([^)'\"]+)['\"]?\s*\)")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def validate_svg(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    root = ET.fromstring(raw)
    ids = [node.attrib["id"] for node in root.iter() if node.attrib.get("id")]
    id_set = set(ids)
    references: set[str] = set()
    external_references: list[str] = []
    for node in root.iter():
        for key, value in node.attrib.items():
            local = _local_name(key).casefold()
            if local in {"href", "src"} and value:
                if value.startswith("#"):
                    references.add(value[1:])
                elif not value.startswith("data:"):
                    external_references.append(value)
            references.update(URL_REFERENCE.findall(value))
    raw_text = raw.decode("utf-8", errors="replace")
    references.update(URL_REFERENCE.findall(raw_text))
    tags = [_local_name(node.tag).casefold() for node in root.iter()]
    paths = [node for node in root.iter() if _local_name(node.tag).casefold() == "path"]
    path_command_counts: dict[str, int] = {}
    for node in paths:
        for command in PATH_COMMAND.findall(node.attrib.get("d", "")):
            path_command_counts[command.upper()] = path_command_counts.get(command.upper(), 0) + 1
    view_box_text = root.attrib.get("viewBox", "")
    try:
        view_box = [float(value) for value in re.split(r"[\s,]+", view_box_text.strip())]
        view_box_valid = len(view_box) == 4 and view_box[2] > 0 and view_box[3] > 0
    except (ValueError, TypeError):
        view_box = []
        view_box_valid = False
    root_namespace_ok = root.tag == f"{{{SVG_NS}}}svg"
    image_nodes = sum(tag == "image" for tag in tags)
    unresolved = sorted(references - id_set)
    script_count = sum(tag == "script" for tag in tags)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "xmlValid": True,
        "svgNamespaceValid": root_namespace_ok,
        "rootTag": root.tag,
        "viewBox": view_box_text,
        "viewBoxValid": view_box_valid,
        "declaredWidth": root.attrib.get("width"),
        "declaredHeight": root.attrib.get("height"),
        "visiblePathElementCount": len(paths),
        "pathCommandCounts": path_command_counts,
        "lineCommandCount": sum(path_command_counts.get(key, 0) for key in ("L", "H", "V")),
        "cubicCommandCount": sum(path_command_counts.get(key, 0) for key in ("C", "S")),
        "quadraticCommandCount": sum(path_command_counts.get(key, 0) for key in ("Q", "T")),
        "gradientDefinitionCount": sum(tag in {"lineargradient", "radialgradient"} for tag in tags),
        "gradientStopCount": sum(tag == "stop" for tag in tags),
        "maskCount": sum(tag == "mask" for tag in tags),
        "clipPathCount": sum(tag == "clippath" for tag in tags),
        "filterCount": sum(tag == "filter" for tag in tags),
        "textElementCount": sum(tag in {"text", "textpath"} for tag in tags),
        "embeddedRasterElementCount": image_nodes,
        "embeddedRasterDataUriCount": sum("data:image/" in value.casefold() for value in re.findall(r"(?:href|src)\s*=\s*['\"]([^'\"]+)", raw_text)),
        "uniqueIds": len(ids) == len(id_set),
        "unresolvedLocalReferences": unresolved,
        "externalResourceReferences": external_references,
        "scriptElementCount": script_count,
        "editableVector": root_namespace_ok and len(paths) > 0 and image_nodes == 0,
        "resourcePolicyValid": image_nodes == 0 and not external_references and script_count == 0 and not unresolved,
    }


def render_svg_edge(svg_path: Path, *, width: int, height: int, browser: str | None = None) -> np.ndarray:
    tree = ET.parse(svg_path)
    root = tree.getroot()
    root.set("width", str(width))
    root.set("height", str(height))
    actual_browser = browser or find_svg_browser()
    if not actual_browser:
        raise RuntimeError("Edge/Chrome browser renderer is not available")
    result = rasterize_svg(ET.tostring(root, encoding="unicode"), expected_size=(height, width), browser=actual_browser)
    return np.asarray(result, dtype=np.uint8)


def render_svg_skia(svg_path: Path, *, width: int, height: int, output_path: Path, timeout_seconds: int = 90) -> dict[str, Any]:
    dll = REPOSITORY / "tools" / "VectorDiagnostics" / "bin" / "Debug" / "net10.0" / "VectorDiagnostics.dll"
    if not dll.is_file():
        return {"status": "NOT_AVAILABLE", "reason": f"Svg.Skia diagnostic binary not found: {dll}"}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        process = subprocess.run(
            ["dotnet", str(dll), str(svg_path), str(output_path), str(width)],
            capture_output=True, text=True, timeout=timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "TIMEOUT", "timeoutSeconds": timeout_seconds}
    if process.returncode != 0 or not output_path.is_file():
        return {"status": "FAIL", "returnCode": process.returncode, "stderr": process.stderr[-2000:]}
    with Image.open(output_path) as image:
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    if rgba.shape[:2] != (height, width):
        canvas = np.zeros((height, width, 4), dtype=np.uint8)
        source_h, source_w = rgba.shape[:2]
        scale = min(width / max(source_w, 1), height / max(source_h, 1))
        new_w, new_h = max(1, round(source_w * scale)), max(1, round(source_h * scale))
        resized = np.asarray(Image.fromarray(rgba).resize((new_w, new_h), Image.Resampling.LANCZOS))
        x, y = (width - new_w) // 2, (height - new_h) // 2
        canvas[y:y + new_h, x:x + new_w] = resized
        rgba = canvas
    return {
        "status": "PASS",
        "renderer": "Svg.Skia 5.2.3 via existing VectorDiagnostics tool",
        "outputPath": str(output_path),
        "dimensions": [int(width), int(height)],
        "rawDimensionsBeforeCanvasFit": [int(source_w), int(source_h)] if "source_w" in locals() else [int(width), int(height)],
        "processReturnCode": process.returncode,
        "stderr": process.stderr[-1000:],
        "rgba": rgba,
    }


def alpha_iou(a: np.ndarray, b: np.ndarray, threshold: int = 16) -> float:
    mask_a = a[..., 3] > threshold
    mask_b = b[..., 3] > threshold
    return float(np.count_nonzero(mask_a & mask_b) / max(np.count_nonzero(mask_a | mask_b), 1))


def common_alpha_rgb_mae(a: np.ndarray, b: np.ndarray, threshold: int = 16) -> float:
    common = (a[..., 3] > threshold) & (b[..., 3] > threshold)
    return float(np.abs(a[..., :3][common].astype(np.float32) - b[..., :3][common].astype(np.float32)).mean()) if common.any() else 0.0
