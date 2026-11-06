"""Run two bounded API-level vectorization smoke cases for Task 08B.1.7.

This is an audit harness only. It does not alter production source or settings.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from mediastudio.api import create_app  # noqa: E402


TASK_DIR = BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_7"
SVG_NS = "http://www.w3.org/2000/svg"
TOKEN = "task-08b-1-7-local-audit"


def _validate_svg(svg_bytes: bytes) -> dict[str, Any]:
    root = ET.fromstring(svg_bytes)
    ns = {"svg": SVG_NS}
    image_elements = root.findall(".//svg:image", ns)
    data_image_references = svg_bytes.lower().count(b"data:image/")
    paths = root.findall(".//svg:path", ns)
    gradients = root.findall(".//svg:linearGradient", ns) + root.findall(
        ".//svg:radialGradient", ns
    )
    return {
        "xmlValid": True,
        "rootTag": root.tag,
        "width": root.attrib.get("width"),
        "height": root.attrib.get("height"),
        "viewBox": root.attrib.get("viewBox"),
        "pathCount": len(paths),
        "gradientCount": len(gradients),
        "embeddedRasterElementCount": len(image_elements),
        "embeddedRasterDataUriCount": data_image_references,
        "vectorOnly": len(image_elements) == 0 and data_image_references == 0,
        "pass": root.tag == f"{{{SVG_NS}}}svg" and bool(paths)
        and len(image_elements) == 0 and data_image_references == 0,
    }


def _run_case(client: TestClient, method: str, fixture: Path) -> dict[str, Any]:
    started = time.perf_counter()
    with fixture.open("rb") as stream:
        imported = client.post(
            "/api/v1/assets",
            headers={"x-media-studio-token": TOKEN},
            files={"file": (fixture.name, stream, "image/png")},
        )
    imported.raise_for_status()
    asset = imported.json()
    request = {
        "asset_id": asset["assetId"],
        "engine": "auto",
        "mode": "auto",
        "text_mode": "outlined",
        "transparent_background": True,
        "vector_method": method,
    }
    response = client.post(
        "/api/v1/vectorize/jobs",
        headers={"x-media-studio-token": TOKEN},
        json=request,
    )
    response.raise_for_status()
    job = response.json()
    deadline = time.monotonic() + 420
    while job.get("state") not in {"succeeded", "failed"}:
        if time.monotonic() >= deadline:
            return {
                "method": method,
                "fixture": fixture.relative_to(ROOT).as_posix(),
                "status": "TIMEOUT",
                "jobId": job.get("jobId"),
                "lastJobState": job,
                "elapsedSeconds": round(time.perf_counter() - started, 3),
            }
        time.sleep(0.25)
        status = client.get(
            f"/api/v1/jobs/{job['jobId']}",
            headers={"x-media-studio-token": TOKEN},
        )
        status.raise_for_status()
        job = status.json()

    result: dict[str, Any] = {
        "method": method,
        "fixture": fixture.relative_to(ROOT).as_posix(),
        "fixtureSha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "inputDimensions": [asset.get("width"), asset.get("height")],
        "assetId": asset["assetId"],
        "jobId": job.get("jobId"),
        "state": job.get("state"),
        "stage": job.get("stage"),
        "errorCode": job.get("errorCode"),
        "error": job.get("error"),
        "resultPipeline": job.get("resultPipeline"),
        "resultVectorMethod": job.get("resultVectorMethod"),
        "resultWidth": job.get("resultWidth"),
        "resultHeight": job.get("resultHeight"),
        "resultPathCount": job.get("resultPaths"),
        "resultSvgBytes": job.get("resultSize"),
        "warnings": job.get("resultWarnings", []),
    }
    if job.get("state") == "succeeded":
        downloaded = client.get(
            f"/api/v1/jobs/{job['jobId']}/result",
            headers={"x-media-studio-token": TOKEN},
        )
        downloaded.raise_for_status()
        svg_bytes = downloaded.content
        output_path = TASK_DIR / f"smoke_{method}.svg"
        output_path.write_bytes(svg_bytes)
        result["downloadedBytes"] = len(svg_bytes)
        result["downloadedSha256"] = hashlib.sha256(svg_bytes).hexdigest()
        result["savedArtifact"] = output_path.name
        result["svgValidation"] = _validate_svg(svg_bytes)
    result["elapsedSeconds"] = round(time.perf_counter() - started, 3)
    return result


def main() -> None:
    os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
    os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
    os.environ["DEBUG_VECTOR"] = "0"
    models = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MediaStudio" / "models" / "realesrgan"
    fixtures = [
        (
            "smart_reconstruction",
            BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_3" / "fixtures"
            / "low_contrast_multistop_gradient" / "source.png",
        ),
        (
            "contour_preserving",
            BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_3" / "fixtures"
            / "hard_boundary_with_gradient" / "source.png",
        ),
    ]
    cases: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="mediastudio-beta-smoke-") as temporary:
        app = create_app(TOKEN, Path(temporary) / "workspace", models)
        with TestClient(app) as client:
            for method, fixture in fixtures:
                if not fixture.is_file():
                    cases.append({"method": method, "fixture": str(fixture), "status": "FIXTURE_MISSING"})
                else:
                    cases.append(_run_case(client, method, fixture))

    summary = {
        "task": "08B.1.7",
        "scope": "one API job per production engine; fixtures selected from existing analytic benchmark set",
        "environment": {
            "vectorizationPipeline": "v2",
            "contourExperimentalEnabled": True,
            "debugArtifactsEnabled": False,
            "api": "FastAPI TestClient with real asset upload, job polling and result download",
        },
        "cases": cases,
        "passed": all(
            case.get("state") == "succeeded"
            and case.get("svgValidation", {}).get("pass") is True
            for case in cases
        ),
        "limitations": [
            "Synthetic analytic fixtures validate the current API and SVG integrity path, not real-image fidelity.",
            "This is not a live WPF GUI or installer end-to-end test.",
        ],
    }
    out = TASK_DIR / "beta_smoke_test_results.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
