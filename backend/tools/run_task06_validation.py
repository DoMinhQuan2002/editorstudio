from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
import xml.etree.ElementTree as ET

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from mediastudio.api import create_app
from mediastudio.image_tools.contour_svg_composer import _safe_references
from mediastudio.image_tools.vectorization_v2.phase_e1 import rasterize_svg
from mediastudio.image_tools.vectorize import VectorizeService
from mediastudio.jobs.manager import Job, JobManager
from mediastudio.storage.assets import Asset

SVG_NS = "http://www.w3.org/2000/svg"


class PeakRssSampler:
    def __init__(self, interval_seconds: float = 0.05) -> None:
        self.interval_seconds = interval_seconds
        self.peak_bytes: int | None = None
        self.start_bytes: int | None = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        try:
            import psutil
            process = psutil.Process()
            get_rss = lambda: int(process.memory_info().rss)
        except Exception:
            if os.name != "nt":
                return
            try:
                import ctypes
                from ctypes import wintypes

                class ProcessMemoryCounters(ctypes.Structure):
                    _fields_ = [
                        ("cb", wintypes.DWORD),
                        ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t),
                        ("PrivateUsage", ctypes.c_size_t),
                    ]

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                psapi = ctypes.WinDLL("psapi", use_last_error=True)
                get_current_process = kernel32.GetCurrentProcess
                get_current_process.restype = wintypes.HANDLE
                get_process_memory_info = psapi.GetProcessMemoryInfo
                get_process_memory_info.argtypes = [wintypes.HANDLE,
                                                    ctypes.POINTER(ProcessMemoryCounters),
                                                    wintypes.DWORD]
                get_process_memory_info.restype = wintypes.BOOL

                def get_rss() -> int:
                    counters = ProcessMemoryCounters()
                    counters.cb = ctypes.sizeof(counters)
                    if not get_process_memory_info(get_current_process(), ctypes.byref(counters), counters.cb):
                        raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
                    return int(counters.WorkingSetSize)
            except Exception:
                return
        while not self._stop.is_set():
            try:
                rss = get_rss()
                if self.start_bytes is None:
                    self.start_bytes = rss
                self.peak_bytes = max(self.peak_bytes or 0, rss)
            except Exception:
                pass
            self._ready.set()
            self._stop.wait(self.interval_seconds)

    def __enter__(self) -> "PeakRssSampler":
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=1)
        return self

    @property
    def peak_delta_bytes(self) -> int | None:
        if self.peak_bytes is None or self.start_bytes is None:
            return None
        return max(0, self.peak_bytes - self.start_bytes)

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)


def _json_write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")


def _await_snapshot(client: Any, job_id: str, token: str, timeout: float = 1800) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}", headers={"X-Media-Studio-Token": token})
        response.raise_for_status()
        snapshot = response.json()
        if snapshot["state"] in {"succeeded", "failed"}:
            return snapshot
        time.sleep(0.25)
    raise TimeoutError(f"MediaStudio job {job_id} exceeded {timeout:.0f} seconds.")


def run_contour_api(source_path: Path, artifacts: Path) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    """Exercise the actual FastAPI upload -> job -> SVG result endpoints."""
    from fastapi.testclient import TestClient

    token = "task06-local-validation-token"
    workspace = artifacts / "api_workspace"
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    models_directory = local_app_data / "MediaStudio" / "models" / "realesrgan"
    ocr_directory = local_app_data / "MediaStudio" / "models" / "easyocr"
    old_environment = {
        "MEDIASTUDIO_VECTORIZE_PIPELINE": os.environ.get("MEDIASTUDIO_VECTORIZE_PIPELINE"),
        "MEDIASTUDIO_CONTOUR_EXPERIMENTAL": os.environ.get("MEDIASTUDIO_CONTOUR_EXPERIMENTAL"),
    }
    os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
    os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
    try:
        app = create_app(token, workspace, models_directory)
        with TestClient(app) as client, source_path.open("rb") as source_handle:
            headers = {"X-Media-Studio-Token": token}
            health = client.get("/api/v1/health", headers=headers)
            health.raise_for_status()
            if not health.json().get("contourExperimentalEnabled"):
                raise AssertionError("API health did not report experimental contour opt-in.")
            upload = client.post("/api/v1/assets", headers=headers,
                                 files={"file": (source_path.name, source_handle, "image/png")})
            upload.raise_for_status()
            asset_record = upload.json()
            request = {
                "asset_id": asset_record["assetId"],
                "engine": "auto",
                "mode": "quality",
                "text_mode": "outlined",
                "vector_method": "contour_preserving",
            }
            with PeakRssSampler() as memory:
                cpu_started = time.process_time()
                wall_started = time.perf_counter()
                queued = client.post("/api/v1/vectorize/jobs", headers=headers, json=request)
                queued.raise_for_status()
                snapshot = _await_snapshot(client, str(queued.json()["jobId"]), token)
                wall_seconds = time.perf_counter() - wall_started
                python_cpu_seconds = time.process_time() - cpu_started
            if snapshot["state"] != "succeeded":
                result = {
                    "passed": False,
                    "stage": "upload-job-result",
                    "health": health.json(),
                    "asset": asset_record,
                    "request": request,
                    "job": snapshot,
                    "wallSeconds": wall_seconds,
                    "pythonCpuSeconds": python_cpu_seconds,
                    "peakPythonProcessRssBytes": memory.peak_bytes,
                    "peakPythonProcessRssDeltaBytes": memory.peak_delta_bytes,
                }
                _json_write(artifacts / "api_integration_results.json", result)
                raise RuntimeError(f"Contour API job failed: {snapshot.get('errorCode')} {snapshot.get('error')}")
            if snapshot.get("resultVectorMethod") != "contour_preserving" or snapshot.get("resultEngine") != "Contour-Preserving":
                raise AssertionError("API job metadata does not identify the actual contour engine.")
            result_response = client.get(f"/api/v1/jobs/{snapshot['jobId']}/result", headers=headers)
            result_response.raise_for_status()
            svg_path = artifacts / "contour_preserving_final.svg"
            svg_path.write_bytes(result_response.content)
            result = {
                "passed": True,
                "health": health.json(),
                "asset": asset_record,
                "request": request,
                "job": snapshot,
                "resultEndpoint": {
                    "statusCode": result_response.status_code,
                    "mediaType": result_response.headers.get("content-type"),
                    "bytes": len(result_response.content),
                    "savedAs": svg_path.name,
                },
                "wallSeconds": wall_seconds,
                "pythonCpuSeconds": python_cpu_seconds,
                "peakPythonProcessRssBytes": memory.peak_bytes,
                "peakPythonProcessRssDeltaBytes": memory.peak_delta_bytes,
                "ocrModelsPresent": (ocr_directory / "craft_mlt_25k.pth").is_file()
                and (ocr_directory / "latin_g2.pth").is_file(),
                "readiness": {
                    "contourBackendPipelineWorking": True,
                    "contourExperimentalApiReady": True,
                    "contourProductionReleaseReady": False,
                    "wpfPreviewValidated": snapshot.get("resultEngineMetadata", {}).get("wpfPreviewValidated", False),
                },
            }
            _json_write(artifacts / "api_integration_results.json", result)
            engine_metadata = dict(snapshot.get("resultEngineMetadata", {}))
            engine_metadata["apiWallSeconds"] = wall_seconds
            engine_metadata["pythonCpuSeconds"] = python_cpu_seconds
            engine_metadata["peakPythonProcessRssBytes"] = memory.peak_bytes
            engine_metadata["peakPythonProcessRssDeltaBytes"] = memory.peak_delta_bytes
            return result, svg_path, engine_metadata
    finally:
        for name, value in old_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def run_smart_v2(source_path: Path, artifacts: Path) -> tuple[dict[str, Any], Path, int | None]:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    models_directory = local_app_data / "MediaStudio" / "models" / "easyocr"
    asset = Asset("task06smartreconstructionv2", source_path, source_path.name, 0, 0,
                  source_path.stat().st_size, "RGBA")
    output_directory = artifacts / "v2_workspace"
    sampler = PeakRssSampler()
    output_path: Path | None = None
    cpu_started = time.process_time()
    wall_started = time.perf_counter()
    with sampler:
        result = VectorizeService(models_directory).run(
            Job("task06smartreconstructionv2", asset.asset_id),
            asset,
            engine="auto",
            color_count=None,
            simplification=None,
            smooth_paths=True,
            transparent_background=True,
            output_directory=output_directory,
            mode="quality",
            pipeline="v2",
            text_mode="outlined",
            vector_method="smart_reconstruction",
            contour_enabled=False,
        )
    wall_seconds = time.perf_counter() - wall_started
    python_cpu_seconds = time.process_time() - cpu_started
    output_path = result[0]
    final_path = artifacts / "smart_v2_comparison.svg"
    shutil.copyfile(output_path, final_path)
    metrics = result[-1]
    record = {
        "passed": True,
        "engine": result[5],
        "vectorMethod": metrics.get("vectorMethod", "smart_reconstruction"),
        "mode": metrics.get("mode"),
        "textMode": metrics.get("textMode"),
        "outputWidth": result[1],
        "outputHeight": result[2],
        "svgBytes": result[3],
        "pathCount": result[4],
        "metrics": metrics,
        "wallSeconds": wall_seconds,
        "pythonCpuSeconds": python_cpu_seconds,
        "peakPythonProcessRssBytes": sampler.peak_bytes,
        "peakPythonProcessRssDeltaBytes": sampler.peak_delta_bytes,
        "svgArtifact": final_path.name,
    }
    _json_write(artifacts / "smart_v2_run.json", record)
    return record, final_path, sampler.peak_bytes


def _composite(rgba: np.ndarray, kind: str) -> Image.Image:
    image = Image.fromarray(rgba, "RGBA")
    width, height = image.size
    if kind == "white":
        background = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    elif kind == "black":
        background = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    elif kind == "checkerboard":
        tile = 24
        yy, xx = np.indices((height, width))
        values = np.where(((xx // tile + yy // tile) % 2) == 0, 230, 190).astype(np.uint8)
        gray = np.stack((values, values, values, np.full_like(values, 255)), axis=2)
        background = Image.fromarray(gray, "RGBA")
    else:
        raise ValueError(kind)
    return Image.alpha_composite(background, image).convert("RGB")


def _render_svg_with_groups(svg_path: Path, expected_size: tuple[int, int],
                            *, show_artwork: bool, show_text: bool,
                            browser: str | None = None) -> np.ndarray:
    tree = ET.parse(svg_path)
    root = tree.getroot()
    for group_id, visible in (("artwork", show_artwork), ("typography", show_text)):
        if visible:
            continue
        for group in list(root.iter(f"{{{SVG_NS}}}g")):
            if group.attrib.get("id") == group_id:
                parent = next((node for node in root.iter() if group in list(node)), None)
                if parent is not None:
                    parent.remove(group)
                break
    root.set("width", str(expected_size[1]))
    root.set("height", str(expected_size[0]))
    return rasterize_svg(ET.tostring(root, encoding="unicode"),
                         expected_size=expected_size, browser=browser)


def _render_svg_review_size(svg_text: str, *, review_size: int,
                            browser: str | None = None) -> np.ndarray:
    root = ET.fromstring(svg_text)
    if root.tag != f"{{{SVG_NS}}}svg":
        raise ValueError("Expected an SVG root element for renderer comparison.")
    root.set("width", str(review_size))
    root.set("height", str(review_size))
    return rasterize_svg(ET.tostring(root, encoding="unicode"),
                         expected_size=(review_size, review_size), browser=browser)


def _score_images(source_rgba: np.ndarray, rendered: np.ndarray,
                  foreground_mask: np.ndarray) -> dict[str, Any]:
    from skimage.color import deltaE_ciede2000, rgb2lab
    from skimage.metrics import structural_similarity

    target_size = (800, 800)
    source = cv2.resize(source_rgba, target_size, interpolation=cv2.INTER_AREA)
    output = cv2.resize(rendered, target_size, interpolation=cv2.INTER_AREA)
    reference_mask = cv2.resize(foreground_mask.astype(np.uint8), target_size,
                                interpolation=cv2.INTER_NEAREST) > 0
    output_mask = output[..., 3] > 16
    intersection = int(np.count_nonzero(reference_mask & output_mask))
    union = int(np.count_nonzero(reference_mask | output_mask))
    common = reference_mask & output_mask
    if np.any(common):
        delta = deltaE_ciede2000(
            rgb2lab(source[..., :3][common] / 255.0),
            rgb2lab(output[..., :3][common] / 255.0),
        )
        delta_mean = float(np.mean(delta))
        delta_p95 = float(np.quantile(delta, 0.95))
    else:
        delta_mean = delta_p95 = None
    source_rgb = source[..., :3]
    output_white = np.asarray(_composite(output, "white"), dtype=np.uint8)
    source_white = np.asarray(_composite(source, "white"), dtype=np.uint8)
    bbox = cv2.boundingRect(reference_mask.astype(np.uint8))
    if bbox[2] > 0 and bbox[3] > 0:
        x, y, width, height = bbox
        first = source_white[y:y + height, x:x + width]
        second = output_white[y:y + height, x:x + width]
        ssim = float(structural_similarity(first, second, channel_axis=2, data_range=255))
    else:
        ssim = None
    return {
        "metricCanvas": list(target_size),
        "referenceForegroundMaskPixels": int(reference_mask.sum()),
        "renderedForegroundMaskPixels": int(output_mask.sum()),
        "foregroundIoU": intersection / max(union, 1),
        "foregroundCoverage": intersection / max(int(reference_mask.sum()), 1),
        "meanDeltaE00OnCommonForeground": delta_mean,
        "p95DeltaE00OnCommonForeground": delta_p95,
        "foregroundBoundingBoxRgbSsimOnWhite": ssim,
        "renderer": "Microsoft Edge headless",
        "backgroundForColorSsim": "white",
        "_sourceDownsampled": source,
        "_outputDownsampled": output,
        "_sourceWhite": source_white,
        "_outputWhite": output_white,
    }


def _comparison_image(source: np.ndarray, v2: np.ndarray, contour: np.ndarray,
                      output_path: Path) -> None:
    panels = []
    for label, rgba in (("SOURCE", source), ("SMART RECONSTRUCTION V2", v2), ("CONTOUR-PRESERVING", contour)):
        panel = _composite(rgba, "white")
        panel.thumbnail((560, 560), Image.Resampling.LANCZOS)
        panels.append((label, panel.copy()))
    canvas = Image.new("RGB", (3 * 590, 610), "#e9e9e9")
    draw = ImageDraw.Draw(canvas)
    for index, (label, panel) in enumerate(panels):
        x = index * 590 + 15
        draw.text((x, 12), label, fill="#222222")
        canvas.paste(panel, (x, 40))
    canvas.save(output_path)


def _typography_comparison(source: np.ndarray, rendered: np.ndarray,
                           engine_metadata: dict[str, Any], output_path: Path) -> None:
    layers = engine_metadata.get("textLayerMetadata") or []
    bbox = None
    for layer in layers:
        candidate = layer.get("bbox")
        if isinstance(candidate, list) and len(candidate) == 4:
            scales = engine_metadata.get("textToSourceMapping", {}).get("scaleXY", [1.0, 1.0])
            bbox = [int(round(candidate[0] * scales[0])),
                    int(round(candidate[1] * scales[1])),
                    int(round(candidate[2] * scales[0])),
                    int(round(candidate[3] * scales[1]))]
            break
    if bbox is None:
        width, height = source.shape[1], source.shape[0]
        bbox = [0, 0, width, height]
    scale_x = rendered.shape[1] / source.shape[1]
    scale_y = rendered.shape[0] / source.shape[0]
    x0, y0, x1, y1 = [int(round(value * scale)) for value, scale in
                       zip(bbox, (scale_x, scale_y, scale_x, scale_y))]
    pad_x, pad_y = max(12, (x1 - x0) // 8), max(12, (y1 - y0) // 5)
    x0, y0 = max(0, x0 - pad_x), max(0, y0 - pad_y)
    x1, y1 = min(rendered.shape[1], x1 + pad_x), min(rendered.shape[0], y1 + pad_y)
    source_box = (int(round(x0 / scale_x)), int(round(y0 / scale_y)),
                  int(round(x1 / scale_x)), int(round(y1 / scale_y)))
    original = Image.fromarray(source[source_box[1]:source_box[3], source_box[0]:source_box[2], :3], "RGB")
    original = original.resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS)
    converted = _composite(rendered, "white").crop((x0, y0, x1, y1))
    width = max(original.width, converted.width)
    height = max(original.height, converted.height)
    canvas = Image.new("RGB", (width * 2 + 48, height + 52), "white")
    draw = ImageDraw.Draw(canvas)
    draw.text((8, 8), "SOURCE TEXT REGION", fill="#222222")
    draw.text((width + 32, 8), "CONTOUR SVG TEXT", fill="#222222")
    canvas.paste(original, (8, 36))
    canvas.paste(converted, (width + 32, 36))
    canvas.save(output_path)


def _write_svg_validation(svg_paths: list[Path], artifacts: Path,
                          renderer_checks: dict[str, Any]) -> None:
    reports: dict[str, Any] = {"rendererChecks": renderer_checks, "files": {}}
    for path in svg_paths:
        tree = ET.parse(path)
        root = tree.getroot()
        reference_report = _safe_references(root)
        all_ids = [node.attrib["id"] for node in root.iter() if "id" in node.attrib]
        images = list(root.iter(f"{{{SVG_NS}}}image"))
        external_count = sum(
            1 for node in root.iter() for name, value in node.attrib.items()
            if name in {"href", "{http://www.w3.org/1999/xlink}href"}
            and value and not value.startswith("#")
        )
        reports["files"][path.name] = {
            "xmlParseValid": True,
            "svgNamespaceValid": root.tag == f"{{{SVG_NS}}}svg",
            "viewBox": root.attrib.get("viewBox"),
            "uniqueIds": len(all_ids) == len(set(all_ids)),
            "pathCount": len(list(root.iter(f"{{{SVG_NS}}}path"))),
            "visibleUseCount": len(list(root.iter(f"{{{SVG_NS}}}use"))),
            "linearGradientCount": len(list(root.iter(f"{{{SVG_NS}}}linearGradient"))),
            "radialGradientCount": len(list(root.iter(f"{{{SVG_NS}}}radialGradient"))),
            "clipPathCount": len(list(root.iter(f"{{{SVG_NS}}}clipPath"))),
            "maskCount": len(list(root.iter(f"{{{SVG_NS}}}mask"))),
            "filterCount": len(list(root.iter(f"{{{SVG_NS}}}filter"))),
            "embeddedRasterCount": len(images),
            "externalResourceCount": external_count,
            "references": reference_report,
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    _json_write(artifacts / "svg_validation.json", reports)


def create_artifacts(source_path: Path, artifacts: Path,
                     contour_path: Path, contour_meta: dict[str, Any],
                     v2_path: Path, v2_record: dict[str, Any]) -> dict[str, Any]:
    from mediastudio.image_tools.vectorization_v2.pipeline import run_phase_a
    from mediastudio.image_tools.vectorization_v2.phase_e1 import find_svg_browser

    source_image = ImageOps.exif_transpose(Image.open(source_path)).convert("RGBA")
    source_rgba = np.asarray(source_image, dtype=np.uint8)
    width, height = source_image.size
    phase_a_image = source_image
    if max(width, height) > 1_600:
        scale = 1_600 / max(width, height)
        phase_a_image = source_image.resize(
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            Image.Resampling.LANCZOS,
        )
    phase_a = run_phase_a(phase_a_image, processing_scale=1)
    foreground = phase_a.foreground_rgba[..., 3] > 16
    shutil.copyfile(source_path, artifacts / "source_reference.png")

    browser_edge = find_svg_browser()
    review_size = 1_600
    browser_chrome = shutil.which("chrome") or shutil.which("chrome.exe")
    if not browser_chrome:
        for candidate in (Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
                          Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe")):
            if candidate.is_file():
                browser_chrome = str(candidate)
                break
    contour_text = contour_path.read_text(encoding="utf-8")
    contour_edge = _render_svg_review_size(contour_text, review_size=review_size, browser=browser_edge)
    contour_chrome = None
    if browser_chrome:
        contour_chrome = _render_svg_review_size(contour_text, review_size=review_size, browser=browser_chrome)
    contour_score = _score_images(source_rgba, contour_edge, foreground)

    v2_text = v2_path.read_text(encoding="utf-8")
    v2_edge = _render_svg_review_size(v2_text, review_size=review_size, browser=browser_edge)
    v2_chrome = None
    if browser_chrome:
        v2_chrome = _render_svg_review_size(v2_text, review_size=review_size, browser=browser_chrome)
    v2_score = _score_images(source_rgba, v2_edge, foreground)

    for kind in ("white", "black", "checkerboard"):
        _composite(contour_edge, kind).save(artifacts / f"contour_render_{kind}.png")
    contour_edge_image = Image.fromarray(contour_edge, "RGBA")
    contour_edge_image.save(artifacts / "composed_final.png")
    if contour_chrome is not None:
        _composite(contour_chrome, "checkerboard").save(artifacts / "contour_render_chrome.png")

    artwork_only = _render_svg_with_groups(contour_path, (review_size, review_size),
                                            show_artwork=True, show_text=False,
                                            browser=browser_edge)
    text_only = _render_svg_with_groups(contour_path, (review_size, review_size),
                                        show_artwork=False, show_text=True,
                                        browser=browser_edge)
    Image.fromarray(artwork_only, "RGBA").save(artifacts / "artwork_only.png")
    Image.fromarray(text_only, "RGBA").save(artifacts / "text_only.png")
    _typography_comparison(source_rgba, contour_edge, contour_meta,
                           artifacts / "typography_before_after.png")
    _comparison_image(source_rgba, v2_edge, contour_edge,
                      artifacts / "source_vs_two_engines.png")

    cross_renderer: dict[str, Any] = {
        "edge": {"browser": browser_edge, "rendered": True},
        "chrome": {"browser": browser_chrome, "rendered": contour_chrome is not None and v2_chrome is not None},
        "svgSkia": {"packageVersion": "5.2.3", "rendered": False,
                    "wpfPreviewValidated": False},
    }
    if contour_chrome is not None:
        edge_small = cv2.resize(contour_edge, (800, 800), interpolation=cv2.INTER_AREA)
        chrome_small = cv2.resize(contour_chrome, (800, 800), interpolation=cv2.INTER_AREA)
        alpha_union = (edge_small[..., 3] > 16) | (chrome_small[..., 3] > 16)
        alpha_intersection = (edge_small[..., 3] > 16) & (chrome_small[..., 3] > 16)
        cross_renderer["edgeVsChromeContour"] = {
            "alphaIoU": int(alpha_intersection.sum()) / max(int(alpha_union.sum()), 1),
            "rgbMeanAbsoluteDifferenceOnCommonAlpha": float(np.mean(np.abs(
                edge_small[..., :3][alpha_intersection].astype(np.float32) -
                chrome_small[..., :3][alpha_intersection].astype(np.float32)))) if alpha_intersection.any() else None,
            "viewBoxCoordinateSpace": [width, height],
            "sameReviewRenderCanvas": [review_size, review_size],
        }

    dotnet = Path(r"C:\Program Files\dotnet\dotnet.exe")
    diagnostics_project = REPOSITORY / "tools" / "VectorDiagnostics" / "VectorDiagnostics.csproj"
    skia_png = artifacts / "contour_render_svgskia.png"
    if dotnet.is_file() and diagnostics_project.is_file():
        try:
            completed = subprocess.run(
                [str(dotnet), "run", "--project", str(diagnostics_project), "--no-launch-profile",
                 "--", str(contour_path), str(skia_png), "1000"],
                capture_output=True, text=True, timeout=600, check=False,
                cwd=REPOSITORY,
            )
            if completed.returncode == 0 and skia_png.is_file():
                skia_rgba = np.asarray(Image.open(skia_png).convert("RGBA"))
                edge_1000 = cv2.resize(contour_edge, (1000, 1000), interpolation=cv2.INTER_AREA)
                if skia_rgba.shape[:2] != (1000, 1000):
                    skia_rgba = cv2.resize(skia_rgba, (1000, 1000), interpolation=cv2.INTER_AREA)
                skia_mask = skia_rgba[..., 3] > 16
                edge_mask = edge_1000[..., 3] > 16
                alpha_union = skia_mask | edge_mask
                alpha_intersection = skia_mask & edge_mask
                alpha_iou = int(alpha_intersection.sum()) / max(int(alpha_union.sum()), 1)
                rgb_mae = float(np.mean(np.abs(
                    skia_rgba[..., :3][alpha_intersection].astype(np.float32) -
                    edge_1000[..., :3][alpha_intersection].astype(np.float32)))) if alpha_intersection.any() else None
                cross_renderer["svgSkia"].update({
                    "rendered": True,
                    "output": skia_png.name,
                    "alphaIoUVsEdge": alpha_iou,
                    "rgbMeanAbsoluteDifferenceVsEdge": rgb_mae,
                    "compatibleByTask06Threshold": bool(alpha_iou >= 0.97 and rgb_mae is not None and rgb_mae <= 16),
                    "width": int(skia_rgba.shape[1]),
                    "height": int(skia_rgba.shape[0]),
                })
            else:
                cross_renderer["svgSkia"].update({
                    "rendered": False,
                    "error": (completed.stderr or completed.stdout)[-3000:],
                    "exitCode": completed.returncode,
                })
        except Exception as error:
            cross_renderer["svgSkia"].update({"rendered": False,
                                                "error": f"{type(error).__name__}: {error}"})

    skia_report = cross_renderer["svgSkia"]
    contour_meta["svgSkiaCompatible"] = (
        bool(skia_report.get("compatibleByTask06Threshold")) if skia_report.get("rendered") else None
    )
    api_result_path = artifacts / "api_integration_results.json"
    if api_result_path.is_file():
        api_report = json.loads(api_result_path.read_text(encoding="utf-8"))
        api_report["postRunRendererCheck"] = {
            "svgSkiaPackageVersion": skia_report.get("packageVersion"),
            "svgSkiaRendered": skia_report.get("rendered"),
            "svgSkiaCompatibleByMeasuredThreshold": skia_report.get("compatibleByTask06Threshold"),
            "wpfPreviewValidated": False,
        }
        api_report["readiness"]["svgSkiaCompatibleByMeasuredThreshold"] = skia_report.get(
            "compatibleByTask06Threshold")
        api_report["readiness"]["wpfPreviewValidated"] = False
        _json_write(api_result_path, api_report)

    renderer_checks = cross_renderer
    _write_svg_validation([contour_path, v2_path], artifacts, renderer_checks)
    comparison = {
        "reference": source_path.name,
        "referenceDimensions": [width, height],
        "referenceForegroundMask": "Phase A foreground alpha > 16",
        "renderers": "Microsoft Edge/Chrome headless at identical source canvas; composited over white for color/SSIM",
        "smartReconstructionV2": {key: value for key, value in v2_score.items() if not key.startswith("_")},
        "contourPreserving": {key: value for key, value in contour_score.items() if not key.startswith("_")},
        "v2Runtime": {key: v2_record.get(key) for key in
                       ("wallSeconds", "pythonCpuSeconds", "peakPythonProcessRssBytes")},
        "contourRuntime": {key: contour_meta.get(key) for key in
                           ("processingTimeMs", "phaseTimingsMs", "workingWidth", "workingHeight", "svgBytes",
                            "apiWallSeconds", "pythonCpuSeconds", "peakPythonProcessRssBytes",
                            "peakPythonProcessRssDeltaBytes")},
        "counts": {
            "smartV2PathCount": v2_record.get("pathCount"),
            "smartV2GradientCount": v2_record.get("metrics", {}).get("gradients", v2_record.get("metrics", {}).get("gradientCount")),
            "smartV2DetailPathCount": v2_record.get("metrics", {}).get("appearanceLayers"),
            "smartV2TypographyCount": v2_record.get("metrics", {}).get("textLayers"),
            "contourVisibleRegionPaints": contour_meta.get("visibleRegionPaths"),
            "contourPathCount": contour_meta.get("pathCount"),
            "contourGradientCount": contour_meta.get("gradientCount"),
            "contourDetailPathCount": contour_meta.get("detailPaths"),
            "contourTypographyCount": contour_meta.get("textLayers"),
            "contourCubicSegments": contour_meta.get("cubicSegments"),
            "contourLineSegments": contour_meta.get("lineSegments"),
            "contourSharedInterfaces": contour_meta.get("sharedInterfaces"),
        },
        "topology": {
            "contourGeometryValid": contour_meta.get("geometryValid"),
            "contourTopologyValid": contour_meta.get("topologyValid"),
            "contourSelfIntersections": contour_meta.get("selfIntersectionCount"),
            "contourSharedBoundaryMismatches": contour_meta.get("sharedBoundaryMismatchCount"),
        },
        "renderValidation": {
            "contourBrowserRenderValidated": contour_meta.get("browserRenderValidated"),
            "smartV2BrowserRenderValidated": v2_record.get("metrics", {}).get("renderValidated"),
            "crossRenderer": cross_renderer,
        },
        "readiness": {
            "contourBackendPipelineWorking": True,
            "contourExperimentalApiReady": True,
            "contourProductionReleaseReady": False,
            "svgSkiaCompatibleByMeasuredThreshold": contour_meta.get("svgSkiaCompatible"),
            "wpfPreviewValidated": False,
        },
        "limitations": [
            "The comparison is one real fixture plus the synthetic E2E matrix; it is not broad independent real-world validation.",
            "WPF manual preview has not been performed; Svg.Skia rendering does not by itself prove WPF preview compatibility.",
            "Peak RSS is sampled for the Python process; child Edge/Chrome process memory is not included.",
        ],
    }
    _json_write(artifacts / "engine_comparison_metrics.json", comparison)
    _json_write(artifacts / "performance_metrics.json", {
        "reference": source_path.name,
        "smartReconstructionV2": v2_record,
        "contourPreserving": {
            "wallSeconds": contour_meta.get("apiWallSeconds"),
            "pythonCpuSeconds": contour_meta.get("pythonCpuSeconds"),
            "peakPythonProcessRssBytes": contour_meta.get("peakPythonProcessRssBytes"),
            "peakPythonProcessRssDeltaBytes": contour_meta.get("peakPythonProcessRssDeltaBytes"),
            "phaseTimingsMs": contour_meta.get("phaseTimingsMs"),
            "workingResolution": [contour_meta.get("workingWidth"), contour_meta.get("workingHeight")],
            "svgBytes": contour_meta.get("svgBytes"),
            "actualJobApiWallSeconds": comparison["contourRuntime"],
        },
        "measurementNotes": [
            "Contour processingTimeMs includes full in-process Phase A/B, segmentation, topology, Bézier, appearance, composition, and browser validation.",
            "API wall/CPU/RSS measurements are recorded in api_integration_results.json.",
            "Smart V2 total/phase times and Python CPU/RSS are recorded in smart_v2_run.json.",
        ],
    })
    return comparison


def main() -> int:
    parser = argparse.ArgumentParser(description="Run MediaStudio Task 06 Contour-Preserving API validation.")
    parser.add_argument("--input", type=Path,
                        default=Path(r"C:\Users\Quan\Downloads\images_upscaled_8x.png"))
    parser.add_argument("--artifacts", type=Path,
                        default=BACKEND / "artifacts" / "contour_preserving" / "task_06")
    arguments = parser.parse_args()
    source = arguments.input.resolve()
    artifacts = arguments.artifacts.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Pinned validation image not found: {source}")
    artifacts.mkdir(parents=True, exist_ok=True)
    contour_api, contour_svg, contour_meta = run_contour_api(source, artifacts)
    v2_record, v2_svg, _ = run_smart_v2(source, artifacts)
    comparison = create_artifacts(source, artifacts, contour_svg, contour_meta, v2_svg, v2_record)
    print(json.dumps({
        "artifacts": str(artifacts),
        "apiSucceeded": contour_api["passed"],
        "contourSvgBytes": contour_svg.stat().st_size,
        "smartV2SvgBytes": v2_svg.stat().st_size,
        "contourPathCount": contour_meta.get("pathCount"),
        "smartV2PathCount": v2_record.get("pathCount"),
        "contourCoverage": comparison["contourPreserving"]["foregroundCoverage"],
        "v2Coverage": comparison["smartReconstructionV2"]["foregroundCoverage"],
        "wpfPreviewValidated": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
