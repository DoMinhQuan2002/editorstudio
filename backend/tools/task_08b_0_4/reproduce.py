from __future__ import annotations

"""Diagnostic-only reproduction of the Task 08A.1 camera GEOS failure."""

import hashlib
import json
import linecache
import os
from pathlib import Path
import platform
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from typing import Any

import shapely
from PIL import Image
from shapely.errors import GEOSException
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402
from mediastudio.api import create_app  # noqa: E402

TOKEN = "task08b-0-4-diagnostic-local-token"
FIXTURE = BACKEND / "artifacts/contour_preserving/task_08a_1/acquired/scikit_image/camera.png"
ITEM = BACKEND / "artifacts/contour_preserving/task_08a_1/runs/task08a1-177681542b1195d6/items/camera.json"
OUTPUT = BACKEND / "artifacts/contour_preserving/task_08b_0_4"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_call(fn: Any, default: Any = None) -> Any:
    try:
        return fn()
    except BaseException as error:  # diagnostics must not mask the original failure
        return {"diagnosticError": f"{type(error).__name__}: {error}"} if default is None else default


class GEOSTrace:
    def __init__(self, destination: Path) -> None:
        self.destination = destination
        self.events: list[dict[str, Any]] = []
        self._seen: dict[int, dict[str, Any]] = {}
        self._exception_refs: list[GEOSException] = []
        self.attempt = 0
        self._lock = threading.Lock()

    def _geometry(self, geometry: BaseGeometry, variable: str) -> dict[str, Any]:
        record: dict[str, Any] = {
            "variable": variable,
            "pythonType": f"{type(geometry).__module__}.{type(geometry).__name__}",
            "geometryType": _safe_call(lambda: geometry.geom_type),
            "bounds": _safe_call(lambda: list(geometry.bounds)),
            "isEmpty": _safe_call(lambda: bool(geometry.is_empty)),
            "isValid": _safe_call(lambda: bool(geometry.is_valid)),
            "validityReason": _safe_call(lambda: explain_validity(geometry)),
            "area": _safe_call(lambda: float(geometry.area)),
            "length": _safe_call(lambda: float(geometry.length)),
        }
        wkb = _safe_call(lambda: bytes(geometry.wkb))
        if isinstance(wkb, bytes):
            self.destination.mkdir(parents=True, exist_ok=True)
            safe_name = "".join(c if c.isalnum() else "_" for c in variable)[:72]
            relative = Path(f"operands/attempt_{self.attempt:02d}_{safe_name}_{sha256(wkb)[:12]}.wkb")
            file_path = self.destination / relative
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if not file_path.exists():
                file_path.write_bytes(wkb)
            record["wkbPath"] = str(relative).replace("\\", "/")
            record["wkbSha256"] = sha256(wkb)
            record["wkbBytes"] = len(wkb)
        return record

    def _value(self, value: Any, name: str, depth: int = 0) -> Any:
        if isinstance(value, BaseGeometry):
            return self._geometry(value, name)
        if depth >= 2:
            return {"pythonType": type(value).__name__}
        if isinstance(value, dict):
            result = {}
            for index, (key, child) in enumerate(value.items()):
                if index >= 12:
                    result["_truncated"] = len(value) - 12
                    break
                result[str(key)] = self._value(child, f"{name}_{key}", depth + 1)
            return result
        if isinstance(value, (list, tuple, set)):
            rows = [self._value(child, f"{name}_{index}", depth + 1)
                    for index, child in enumerate(value) if index < 12]
            if len(value) > 12:
                rows.append({"_truncated": len(value) - 12})
            return {"pythonType": type(value).__name__, "length": len(value), "items": rows}
        if isinstance(value, (str, int, float, bool)) or value is None:
            if isinstance(value, str) and len(value) > 1000:
                return value[:1000] + "…[truncated]"
            return value
        if hasattr(value, "shape") and hasattr(value, "dtype"):
            try:
                array = value
                data = array.tobytes(order="C")
                return {
                    "pythonType": type(value).__name__,
                    "shape": list(array.shape),
                    "dtype": str(array.dtype),
                    "nbytes": int(array.nbytes),
                    "sha256": sha256(data),
                }
            except BaseException as error:
                return {"pythonType": type(value).__name__, "diagnosticError": str(error)}
        return {"pythonType": f"{type(value).__module__}.{type(value).__name__}"}

    def _shape_context(self, shape: Any) -> dict[str, Any]:
        def paths(items: Any) -> list[dict[str, Any]]:
            result = []
            for path in items or []:
                refs = getattr(path, "refs", [])
                result.append({
                    "kind": getattr(path, "kind", None),
                    "closed": getattr(path, "closed", None),
                    "boundaryRefs": [
                        {"boundaryId": getattr(ref, "boundary_id", None),
                         "reversed": getattr(ref, "reversed", None),
                         "componentIndex": getattr(ref, "component_index", None)}
                        for ref in refs
                    ],
                })
            return result

        return {
            "id": getattr(shape, "id", None),
            "regionId": getattr(shape, "region_id", None),
            "parentId": getattr(shape, "parent_id", None),
            "childIds": getattr(shape, "child_ids", None),
            "geometryStatus": getattr(shape, "geometry_status", None),
            "confidence": getattr(shape, "confidence", None),
            "outerPaths": paths(getattr(shape, "outer_paths", [])),
            "holePaths": paths(getattr(shape, "hole_paths", [])),
        }

    @staticmethod
    def _boundary_context(boundary: Any) -> dict[str, Any]:
        return {
            name: getattr(boundary, name, None)
            for name in ("id", "region_a", "region_b", "kind", "confidence",
                         "raw_point_count", "mean_error", "max_error", "closed")
        }

    def _capture(self, frame: Any, error: GEOSException) -> None:
        key = id(error)
        filename = frame.f_code.co_filename
        line = frame.f_lineno
        frame_key = f"{filename}:{line}:{frame.f_code.co_name}"
        with self._lock:
            current = self._seen.get(key)
            if current is not None:
                current["propagationFrames"].append(frame_key)
                return
            tb_rows = []
            tb = error.__traceback__
            while tb is not None:
                tb_frame = tb.tb_frame
                tb_filename = tb_frame.f_code.co_filename
                tb_line = tb.tb_lineno
                local_values: dict[str, Any] = {}
                boundary_context = tb_frame.f_locals.get("boundary")
                region_ids: list[int] = []
                if boundary_context is not None:
                    for attr in ("region_a", "region_b"):
                        value = getattr(boundary_context, attr, None)
                        if isinstance(value, int):
                            region_ids.append(value)
                for name, value in tb_frame.f_locals.items():
                    if isinstance(value, BaseGeometry):
                        local_values[name] = self._value(value, f"{tb_frame.f_code.co_name}_{name}")
                    elif isinstance(value, (list, tuple)) and any(
                            isinstance(child, BaseGeometry) for child in value[:12]):
                        local_values[name] = self._value(value, f"{tb_frame.f_code.co_name}_{name}")
                    elif name == "boundary" and boundary_context is not None:
                        local_values[name] = self._boundary_context(value)
                    elif name == "shape_polygons" and isinstance(value, dict):
                        local_values[name] = {
                            "pythonType": "dict",
                            "length": len(value),
                            "targetRegionPolygons": {
                                str(region_id): self._value(value[region_id], f"shape_polygons_region_{region_id}")
                                for region_id in region_ids if region_id in value
                            },
                        }
                    elif name == "model" and hasattr(value, "shapes"):
                        local_values[name] = {
                            "width": getattr(value, "width", None),
                            "height": getattr(value, "height", None),
                            "targetShapes": [self._shape_context(shape) for shape in value.shapes
                                             if getattr(shape, "region_id", None) in region_ids],
                        }
                tb_rows.append({
                    "file": str(Path(tb_filename).resolve()) if not tb_filename.startswith("<") else tb_filename,
                    "line": tb_line,
                    "function": tb_frame.f_code.co_name,
                    "source": linecache.getline(tb_filename, tb_line).strip(),
                    "geometryLocals": local_values,
                })
                tb = tb.tb_next
            event = {
                "attempt": self.attempt,
                "capturedAtUtc": utc_now(),
                "threadName": threading.current_thread().name,
                "exceptionType": f"{type(error).__module__}.{type(error).__name__}",
                "exceptionMessage": str(error),
                "frameAtExceptionEvent": frame_key,
                "operationSourceLine": linecache.getline(filename, line).strip(),
                "traceback": tb_rows,
                "formattedTraceback": "".join(traceback.format_exception(type(error), error, error.__traceback__)),
                "propagationFrames": [frame_key],
            }
            self._seen[key] = event
            self._exception_refs.append(error)
            self.events.append(event)

    def trace(self, frame: Any, event: str, arg: Any):
        filename = frame.f_code.co_filename.replace("\\", "/")
        # Restrict line tracing to the two production V2 modules that directly
        # construct or operate on Shapely geometries. Tracing every Shapely
        # wrapper call made a 512px API job disproportionately slow.
        relevant = filename.endswith((
            "/mediastudio/image_tools/vectorization_v2/phase_d.py",
            "/mediastudio/image_tools/vectorization_v2/phase_d1.py",
            "/mediastudio/image_tools/vectorization_v2/appearance_feature_geometry.py",
        ))
        if event == "call":
            if (filename.endswith("/mediastudio/image_tools/vectorization_v2/phase_d.py")
                    and frame.f_code.co_name == "_compute_metrics"):
                # Keep exception events (including locally caught overlays)
                # without tracing every line in the metric loops.
                frame.f_trace_lines = False
            return self.trace if relevant else None
        if relevant and event == "exception":
            exc_type, exc_value, _ = arg
            if isinstance(exc_value, GEOSException):
                self._capture(frame, exc_value)
        return self.trace if relevant else None


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    item = json.loads(ITEM.read_text(encoding="utf-8"))
    source_bytes = FIXTURE.read_bytes()
    source_sha = sha256(source_bytes)
    with Image.open(FIXTURE) as image:
        dimensions = list(image.size)
        image_mode = image.mode
    if source_sha != item["sha256"]:
        raise RuntimeError(f"fixture hash mismatch: item={item['sha256']} actual={source_sha}")

    os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
    os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
    os.environ["DEBUG_VECTOR"] = "0"
    trace = GEOSTrace(OUTPUT)
    repetitions = int(os.environ.get("TASK_08B_0_4_REPETITIONS", "3"))
    output_filename = os.environ.get("TASK_08B_0_4_OUTPUT_FILENAME", "geos_exception_reproduction.json")
    request_body: dict[str, Any] = {
        "asset_id": None,
        "engine": "auto",
        "mode": "auto",
        "color_count": None,
        "simplification": None,
        "smooth_paths": True,
        "transparent_background": True,
        "text_mode": "outlined",
        "vector_method": "smart_reconstruction",
    }
    attempt_results: list[dict[str, Any]] = []
    models_directory = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "MediaStudio/models/realesrgan"
    workspace = OUTPUT / "reproduction_workspace"
    app = create_app(TOKEN, workspace, models_directory)
    headers = {"X-Media-Studio-Token": TOKEN}
    sys.settrace(trace.trace)
    threading.settrace(trace.trace)
    if hasattr(threading, "settrace_all_threads"):
        threading.settrace_all_threads(trace.trace)
    try:
        with TestClient(app) as client:
            health = client.get("/api/v1/health", headers=headers)
            health.raise_for_status()
            upload = client.post("/api/v1/assets", headers=headers,
                                 files={"file": (FIXTURE.name, source_bytes, "image/png")})
            upload.raise_for_status()
            asset = upload.json()
            request_body["asset_id"] = asset["assetId"]
            for attempt in range(1, repetitions + 1):
                trace.attempt = attempt
                started = time.perf_counter()
                queued_response = client.post("/api/v1/vectorize/jobs", headers=headers, json=request_body)
                queued_response.raise_for_status()
                queued = queued_response.json()
                deadline = time.monotonic() + 900
                history = []
                final = None
                while time.monotonic() < deadline:
                    response = client.get(f"/api/v1/jobs/{queued['jobId']}", headers=headers)
                    response.raise_for_status()
                    final = response.json()
                    history.append({"state": final.get("state"), "stage": final.get("stage"),
                                    "progress": final.get("progress"), "atUtc": utc_now()})
                    if final.get("state") in {"succeeded", "failed"}:
                        break
                    time.sleep(0.2)
                else:
                    raise TimeoutError(f"attempt {attempt} job timed out")
                result = {
                    "attempt": attempt,
                    "jobId": queued["jobId"],
                    "state": final.get("state"),
                    "stage": final.get("stage"),
                    "error": final.get("error"),
                    "errorCode": final.get("errorCode"),
                    "errorDetails": final.get("errorDetails"),
                    "resultVectorMethod": final.get("resultVectorMethod"),
                    "resultPipeline": final.get("resultPipeline"),
                    "elapsedSeconds": round(time.perf_counter() - started, 3),
                    "progressHistory": history,
                }
                if final.get("state") == "succeeded":
                    result_response = client.get(f"/api/v1/jobs/{queued['jobId']}/result", headers=headers)
                    result["resultDownloadStatus"] = result_response.status_code
                    result["resultBytes"] = len(result_response.content)
                attempt_results.append(result)
    finally:
        sys.settrace(None)
        threading.settrace(None)
        if hasattr(threading, "settrace_all_threads"):
            threading.settrace_all_threads(None)

    reproduction = {
        "schemaVersion": 1,
        "task": "08B.0.4",
        "recordedAtUtc": utc_now(),
        "environment": {
            "pythonVersion": sys.version,
            "pythonImplementation": platform.python_implementation(),
            "platform": platform.platform(),
            "shapelyVersion": shapely.__version__,
            "geosVersion": shapely.geos_version_string,
            "geosCapiVersion": shapely.geos_capi_version_string,
        },
        "fixture": {
            "path": str(FIXTURE.resolve()),
            "imageId": item["imageId"],
            "sha256Expected": item["sha256"],
            "sha256Actual": source_sha,
            "hashMatchesManifest": source_sha == item["sha256"],
            "dimensions": dimensions,
            "mode": image_mode,
            "bytes": len(source_bytes),
        },
        "runtimeConfiguration": {
            "apiPath": "POST /api/v1/assets -> POST /api/v1/vectorize/jobs -> GET /api/v1/jobs/{jobId}",
            "request": request_body,
            "environmentVariables": {
                "MEDIASTUDIO_CONTOUR_EXPERIMENTAL": os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"],
                "MEDIASTUDIO_VECTORIZE_PIPELINE": os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"],
                "DEBUG_VECTOR": os.environ["DEBUG_VECTOR"],
            },
            "repetitions": repetitions,
            "sequential": True,
            "instrumentation": "sys/threading trace, captures GEOSException traceback and Shapely geometry locals; no production files monkeypatched",
        },
        "attempts": attempt_results,
        "geosExceptionEvents": trace.events,
        "geosExceptionEventCount": len(trace.events),
    }
    output_path = OUTPUT / output_filename
    output_path.write_text(
        json.dumps(reproduction, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "artifact": str(output_path.resolve()),
        "attemptStates": [item["state"] for item in attempt_results],
        "geosExceptionEvents": len(trace.events),
        "sourceSha256": source_sha,
        "shapely": shapely.__version__,
        "geos": shapely.geos_version_string,
    }, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
