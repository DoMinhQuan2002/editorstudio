from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient
from mediastudio.api import create_app
from mediastudio.desktop_capabilities import install_desktop_capabilities


REPOSITORY = BACKEND.parent
ARTIFACTS = BACKEND / "artifacts" / "contour_preserving" / "task_07"
SOURCE = Path.home() / "Downloads" / "images_upscaled_8x.png"
POLL_SECONDS = 0.35
JOB_TIMEOUT_SECONDS = 15 * 60


def wait_for_job(client: TestClient, job_id: str, headers: dict[str, str]) -> tuple[dict[str, Any], bytes, float]:
    started = time.perf_counter()
    deadline = started + JOB_TIMEOUT_SECONDS
    history: list[dict[str, Any]] = []
    while time.perf_counter() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
        response.raise_for_status()
        job = response.json()
        history.append({"state": job.get("state"), "progress": job.get("progress"), "stage": job.get("stage")})
        if job.get("state") in {"succeeded", "failed"}:
            if job["state"] != "succeeded":
                return {**job, "progressHistory": history}, b"", time.perf_counter() - started
            result = client.get(f"/api/v1/jobs/{job_id}/result", headers=headers)
            result.raise_for_status()
            if result.headers.get("content-type", "").split(";")[0] != "image/svg+xml":
                raise RuntimeError(f"Expected SVG response, got {result.headers.get('content-type')}")
            return {**job, "progressHistory": history}, result.content, time.perf_counter() - started
        time.sleep(POLL_SECONDS)
    raise TimeoutError(f"Job {job_id} exceeded {JOB_TIMEOUT_SECONDS}s. Waiting stopped; backend job was not cancelled.")


def validate_svg(svg_bytes: bytes, output_path: Path) -> dict[str, Any]:
    import xml.etree.ElementTree as ET

    output_path.write_bytes(svg_bytes)
    root = ET.fromstring(svg_bytes)
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    embedded = root.findall(".//svg:image", namespace)
    if embedded:
        raise RuntimeError(f"SVG contains {len(embedded)} embedded image element(s)")
    return {
        "bytes": len(svg_bytes),
        "sha256": sha256(svg_bytes).hexdigest(),
        "pathCount": len(root.findall(".//svg:path", namespace)),
        "gradientCount": len(root.findall(".//svg:linearGradient", namespace)) + len(root.findall(".//svg:radialGradient", namespace)),
        "embeddedRasterCount": len(embedded),
        "savedPath": str(output_path),
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Pinned raster fixture was not found: {SOURCE}")
    source_bytes = SOURCE.read_bytes()
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    models_directory = local_app_data / "MediaStudio" / "models" / "realesrgan"
    old_flag = os.environ.get("MEDIASTUDIO_CONTOUR_EXPERIMENTAL")
    os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
    try:
        with tempfile.TemporaryDirectory(prefix="mediastudio-task07-") as temp:
            root = Path(temp)
            app = create_app("task07-local-token", root / "workspace", models_directory)
            install_desktop_capabilities(app)
            app.state.output_directory = root / "results"
            headers = {"X-Media-Studio-Token": "task07-local-token"}
            with TestClient(app) as client:
                health_response = client.get("/api/v1/health", headers=headers)
                health_response.raise_for_status()
                health = health_response.json()
                capability_response = client.get("/api/v1/desktop/contour-capabilities", headers=headers)
                capability_response.raise_for_status()
                capabilities = capability_response.json()
                if not capabilities.get("ready"):
                    raise RuntimeError(
                        "Contour is not ready in this local Python environment: "
                        f"flag={capabilities.get('experimentalEnabled')} "
                        f"dependency={capabilities.get('dependencyVersion')}"
                    )

                upload = client.post(
                    "/api/v1/assets",
                    headers=headers,
                    files={"file": (SOURCE.name, source_bytes, "image/png")},
                )
                upload.raise_for_status()
                asset = upload.json()
                asset_id = asset["assetId"]
                request_common = {
                    "asset_id": asset_id,
                    "engine": "auto",
                    "mode": "auto",
                    "color_count": None,
                    "simplification": None,
                    "smooth_paths": True,
                    "transparent_background": True,
                    "text_mode": "outlined",
                }
                runs: list[dict[str, Any]] = []
                for method in ("smart_reconstruction", "contour_preserving"):
                    request_body = {**request_common, "vector_method": method}
                    created = client.post("/api/v1/vectorize/jobs", headers=headers, json=request_body)
                    if created.status_code != 202:
                        raise RuntimeError(f"{method} create job returned {created.status_code}: {created.text}")
                    initial_job = created.json()
                    job, svg, wall_seconds = wait_for_job(client, initial_job["jobId"], headers)
                    if job.get("state") != "succeeded":
                        runs.append({"method": method, "state": job.get("state"), "error": job.get("error"), "errorCode": job.get("errorCode")})
                        raise RuntimeError(f"{method} failed: {job.get('errorCode')} {job.get('error')}")
                    if job.get("resultVectorMethod") != method:
                        raise RuntimeError(
                            f"Metadata mismatch: requested {method}, backend returned {job.get('resultVectorMethod')}"
                        )
                    if method == "smart_reconstruction" and job.get("resultPipeline") != "vectorization_v2":
                        raise RuntimeError(f"Smart method did not route to V2: {job.get('resultPipeline')}")
                    filename = "smart_reconstruction_active_fox.svg" if method == "smart_reconstruction" else "contour_preserving_active_fox.svg"
                    svg_info = validate_svg(svg, ARTIFACTS / filename)
                    runs.append({
                        "method": method,
                        "request": request_body,
                        "jobId": job["jobId"],
                        "state": job["state"],
                        "engine": job.get("resultEngine"),
                        "pipeline": job.get("resultPipeline"),
                        "resultVectorMethod": job.get("resultVectorMethod"),
                        "resultMode": job.get("resultMode"),
                        "resultTextMode": job.get("resultTextMode"),
                        "processingTimeMs": job.get("resultProcessingTimeMs"),
                        "resultPaths": job.get("resultPaths"),
                        "resultGradients": job.get("resultGradients"),
                        "resultWarnings": job.get("resultWarnings", []),
                        "progressHistory": job.get("progressHistory", []),
                        "wallSeconds": round(wall_seconds, 3),
                        "svg": svg_info,
                    })

                if runs[0]["request"]["asset_id"] != runs[1]["request"]["asset_id"]:
                    raise RuntimeError("The methods did not use the same imported asset.")
                routing = {
                    "status": "PASS",
                    "sourcePath": str(SOURCE),
                    "sourceSha256": sha256(source_bytes).hexdigest(),
                    "sourceSizeBytes": len(source_bytes),
                    "assetImportCount": 1,
                    "assetId": asset_id,
                    "requestOrder": [run["method"] for run in runs],
                    "sameAssetId": True,
                    "qualityMode": "auto",
                    "textMode": "outlined",
                    "metadataMatchesRequest": all(run["resultVectorMethod"] == run["method"] for run in runs),
                    "smartPipelineV2": runs[0]["pipeline"] == "vectorization_v2",
                    "sequential": True,
                    "jobManagerMaxWorkers": 1,
                    "health": health,
                    "contourCapabilities": capabilities,
                }
                (ARTIFACTS / "api_method_routing.json").write_text(json.dumps(routing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                compare = {
                    "status": "PASS",
                    "sameSource": True,
                    "sequentialJobs": True,
                    "runs": runs,
                    "summary": "Both engine results came from one uploaded asset and were executed in sequence.",
                }
                (ARTIFACTS / "compare_job_results.json").write_text(json.dumps(compare, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                print(json.dumps({
                    "routing": routing,
                    "compare": {
                        "status": compare["status"],
                        "sameSource": compare["sameSource"],
                        "sequentialJobs": compare["sequentialJobs"],
                        "runs": [{key: run.get(key) for key in (
                            "method", "state", "engine", "pipeline", "resultVectorMethod", "resultMode",
                            "resultTextMode", "processingTimeMs", "resultPaths", "resultGradients", "wallSeconds", "svg"
                        )} for run in runs],
                    },
                }, indent=2, ensure_ascii=False))
                return 0
    finally:
        if old_flag is None:
            os.environ.pop("MEDIASTUDIO_CONTOUR_EXPERIMENTAL", None)
        else:
            os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = old_flag


if __name__ == "__main__":
    raise SystemExit(main())
