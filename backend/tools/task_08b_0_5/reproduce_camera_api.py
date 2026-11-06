from __future__ import annotations

"""Run the Task 08A.1 camera through the real V2 API and preserve D1 evidence."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
from datetime import datetime, timezone

import shapely
from PIL import Image

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402
from mediastudio.api import create_app  # noqa: E402
from mediastudio.image_tools.vectorization_v2.phase_e1 import rasterize_svg  # noqa: E402

FIXTURE = BACKEND / "artifacts/contour_preserving/task_08a_1/acquired/scikit_image/camera.png"
OUTPUT = BACKEND / "artifacts/contour_preserving/task_08b_0_5"
TOKEN = "task08b-0-5-camera-validation-token"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def main() -> int:
    os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
    os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
    os.environ["DEBUG_VECTOR"] = "1"

    source = FIXTURE.read_bytes()
    with Image.open(FIXTURE) as image:
        dimensions = list(image.size)
    run_tag = os.environ.get("TASK_08B_0_5_RUN_TAG", "run")
    workspace = OUTPUT / f"camera_api_workspace_{run_tag}"
    models_directory = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "MediaStudio/models/realesrgan"
    app = create_app(TOKEN, workspace, models_directory)
    headers = {"X-Media-Studio-Token": TOKEN}
    request = {
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
    job_id = None
    start = time.perf_counter()
    with TestClient(app) as client:
        health = client.get("/api/v1/health", headers=headers)
        health.raise_for_status()
        upload = client.post("/api/v1/assets", headers=headers,
                             files={"file": (FIXTURE.name, source, "image/png")})
        upload.raise_for_status()
        request["asset_id"] = upload.json()["assetId"]
        queued_response = client.post("/api/v1/vectorize/jobs", headers=headers, json=request)
        queued_response.raise_for_status()
        queued = queued_response.json()
        job_id = queued["jobId"]
        deadline = time.monotonic() + 900
        progress = []
        final = None
        while time.monotonic() < deadline:
            response = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
            response.raise_for_status()
            final = response.json()
            progress.append({"state": final.get("state"), "stage": final.get("stage"),
                             "progress": final.get("progress"), "atUtc": utc_now()})
            if final.get("state") in {"succeeded", "failed"}:
                break
            time.sleep(0.2)
        else:
            raise TimeoutError("Camera vectorization job timed out after 900 seconds.")

        result_path = OUTPUT / "camera_fixed.svg"
        render_path = OUTPUT / "camera_fixed_render.png"
        result_status = None
        result_bytes = 0
        if final.get("state") == "succeeded":
            result_response = client.get(f"/api/v1/jobs/{job_id}/result", headers=headers)
            result_status = result_response.status_code
            result_response.raise_for_status()
            result_bytes = len(result_response.content)
            result_path.write_bytes(result_response.content)
            rendered = rasterize_svg(result_response.text, expected_size=tuple(dimensions))
            Image.fromarray(rendered, mode="RGBA").save(render_path)

    debug_source = workspace / "results" / "vector-debug" / str(job_id) / "phase_d1"
    debug_destination = OUTPUT / f"camera_d1_diagnostics_{job_id}"
    if debug_source.is_dir():
        shutil.copytree(debug_source, debug_destination)
    d1_metrics_path = debug_destination / "phase_d1_metrics.json"
    d1_metrics = json.loads(d1_metrics_path.read_text(encoding="utf-8")) if d1_metrics_path.is_file() else None
    report = {
        "schemaVersion": 1,
        "task": "08B.0.5",
        "recordedAtUtc": utc_now(),
        "fixture": {
            "path": str(FIXTURE.resolve()),
            "sha256": hashlib.sha256(source).hexdigest(),
            "dimensions": dimensions,
            "bytes": len(source),
        },
        "environment": {
            "pythonVersion": sys.version,
            "shapelyVersion": shapely.__version__,
            "geosVersion": shapely.geos_version_string,
        },
        "runtimeConfiguration": {
            "apiPath": "POST /api/v1/assets -> POST /api/v1/vectorize/jobs -> GET /api/v1/jobs/{jobId}",
            "request": request,
            "environmentVariables": {
                "MEDIASTUDIO_CONTOUR_EXPERIMENTAL": os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"],
                "MEDIASTUDIO_VECTORIZE_PIPELINE": os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"],
                "DEBUG_VECTOR": os.environ["DEBUG_VECTOR"],
            },
        },
        "job": {
            "jobId": job_id,
            "state": final.get("state"),
            "stage": final.get("stage"),
            "error": final.get("error"),
            "errorCode": final.get("errorCode"),
            "errorDetails": final.get("errorDetails"),
            "resultPipeline": final.get("resultPipeline"),
            "resultVectorMethod": final.get("resultVectorMethod"),
            "elapsedSeconds": round(time.perf_counter() - start, 3),
            "progressHistory": progress,
            "resultDownloadStatus": result_status,
            "resultBytes": result_bytes,
        },
        "d1Reached": d1_metrics is not None,
        "d1MetricsPath": str(d1_metrics_path.resolve()) if d1_metrics_path.is_file() else None,
        "d1Metrics": d1_metrics,
        "savedSvg": str(result_path.resolve()) if result_path.is_file() else None,
        "savedRender": str(render_path.resolve()) if render_path.is_file() else None,
        "diagnosticsDirectory": str(debug_destination.resolve()) if debug_destination.is_dir() else None,
    }
    output_path = OUTPUT / "camera_api_reproduction.json"
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(output_path.resolve()),
        "jobState": final.get("state"),
        "error": final.get("error"),
        "d1Reached": d1_metrics is not None,
        "d1SelfIntersections": None if d1_metrics is None else d1_metrics.get("self_intersection_count"),
        "overlapStatus": None if d1_metrics is None else d1_metrics.get("shared_interface_overlap_area_status"),
        "finalGeometryValidation": None if d1_metrics is None else d1_metrics.get("final_geometry_validation"),
    }, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
