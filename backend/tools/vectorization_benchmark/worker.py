from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from typing import Any

import numpy as np
from PIL import Image

BACKEND = Path(__file__).resolve().parents[2]
REPOSITORY = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402
from mediastudio.api import create_app  # noqa: E402
from mediastudio.desktop_capabilities import install_desktop_capabilities  # noqa: E402
from .dataset import resolve_path, sha256_file, write_json  # noqa: E402
from .metrics import evaluate_render  # noqa: E402
from .performance import ProcessTreeSampler  # noqa: E402
from .svg import common_alpha_rgb_mae, file_sha256, render_svg_edge, render_svg_skia, validate_svg  # noqa: E402
from .visuals import persist_visual_diagnostics  # noqa: E402


TOKEN = "task08a-benchmark-local-token"
ENGINE_NAMES = ("smart_reconstruction", "contour_preserving")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _load_gray(path: str | None) -> np.ndarray | None:
    if not path:
        return None
    reference_path = resolve_path(path)
    if not reference_path.is_file():
        return None
    with Image.open(reference_path) as image:
        return np.asarray(image.convert("L"), dtype=np.uint8)


def _json_safe_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metrics.items() if key != "errorMap"}


def _copy_debug_artifacts(output_directory: Path, job_id: str, target: Path) -> list[str]:
    source = output_directory / "vector-debug" / job_id
    if not source.is_dir():
        return []
    destination = target / "stages"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    return [str(path) for path in sorted(destination.rglob("*")) if path.is_file()]


def _wait_for_job(client: TestClient, job_id: str, headers: dict[str, str], timeout_seconds: int) -> tuple[dict[str, Any], bytes, float, list[dict[str, Any]]]:
    started = time.perf_counter()
    deadline = started + timeout_seconds
    history: list[dict[str, Any]] = []
    while time.perf_counter() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
        response.raise_for_status()
        job = response.json()
        history.append({"atUtc": utc_now(), "state": job.get("state"), "stage": job.get("stage"), "progress": job.get("progress")})
        if job.get("state") in {"succeeded", "failed"}:
            if job.get("state") != "succeeded":
                return job, b"", time.perf_counter() - started, history
            result_response = client.get(f"/api/v1/jobs/{job_id}/result", headers=headers)
            result_response.raise_for_status()
            media_type = result_response.headers.get("content-type", "").split(";", 1)[0]
            if media_type != "image/svg+xml":
                raise RuntimeError(f"Expected image/svg+xml for {job_id}; API returned {media_type!r}")
            return job, result_response.content, time.perf_counter() - started, history
        time.sleep(0.25)
    raise TimeoutError(f"API job {job_id} did not finish before {timeout_seconds}s")


def run_image(item: dict[str, Any], artifact_root: Path, *, per_engine_timeout: int, run_id: str) -> dict[str, Any]:
    image_id = str(item["imageId"])
    source_path = resolve_path(str(item["path"]))
    source_bytes = source_path.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    if source_sha != item.get("sha256"):
        raise RuntimeError(f"Source hash changed for {image_id}: manifest {item.get('sha256')} actual {source_sha}")
    with Image.open(source_path) as image:
        source_rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        input_width, input_height = image.size
    max_side = 1600
    ratio = min(1.0, max_side / max(input_width, input_height))
    render_width = max(1, round(input_width * ratio))
    render_height = max(1, round(input_height * ratio))
    run_root = artifact_root / "runs" / run_id
    run_directory = run_root / "outputs" / image_id
    run_directory.mkdir(parents=True, exist_ok=True)
    (run_root / "temp").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"task08a-{image_id}-", dir=run_root / "temp") as temp_name:
        temp_root = Path(temp_name)
        models_directory = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "MediaStudio" / "models" / "realesrgan"
        app = create_app(TOKEN, temp_root / "workspace", models_directory)
        install_desktop_capabilities(app)
        output_directory = run_directory / "api_output"
        app.state.output_directory = output_directory
        headers = {"X-Media-Studio-Token": TOKEN}
        runs: dict[str, dict[str, Any]] = {}
        with TestClient(app) as client:
            health_response = client.get("/api/v1/health", headers=headers)
            health_response.raise_for_status()
            capabilities_response = client.get("/api/v1/desktop/contour-capabilities", headers=headers)
            capabilities_response.raise_for_status()
            capabilities = capabilities_response.json()
            if not capabilities.get("ready"):
                raise RuntimeError(f"Experimental Contour engine unavailable: {capabilities}")
            upload_start = time.perf_counter()
            uploaded = client.post("/api/v1/assets", headers=headers, files={"file": (source_path.name, source_bytes, "application/octet-stream")})
            uploaded.raise_for_status()
            asset = uploaded.json()
            upload_seconds = time.perf_counter() - upload_start
            # Alternate engine order by source index so the same engine is not always cold.
            method_order = list(ENGINE_NAMES)
            if int(item.get("benchmarkOrderIndex", 0)) % 2:
                method_order.reverse()
            for method_position, method in enumerate(method_order):
                engine_dir = run_directory / method
                engine_dir.mkdir(parents=True, exist_ok=True)
                request = {
                    "asset_id": asset["assetId"], "engine": "auto", "mode": "auto",
                    "color_count": None, "simplification": None, "smooth_paths": True,
                    "transparent_background": True, "text_mode": "outlined", "vector_method": method,
                }
                started_at = utc_now()
                wall_start = time.perf_counter()
                cpu_start = time.process_time()
                sampler = ProcessTreeSampler().start()
                queued_response = client.post("/api/v1/vectorize/jobs", headers=headers, json=request)
                if queued_response.status_code != 202:
                    sampler.stop()
                    raise RuntimeError(f"{method} job creation failed: HTTP {queued_response.status_code} {queued_response.text}")
                queued = queued_response.json()
                job, svg_bytes, job_wait_seconds, progress_history = _wait_for_job(client, queued["jobId"], headers, per_engine_timeout)
                elapsed_api = time.perf_counter() - wall_start
                cpu_seconds = time.process_time() - cpu_start
                memory = sampler.stop()
                if job.get("state") != "succeeded":
                    runs[method] = {
                        "status": "FAILED", "requestedMethod": method, "actualMethod": job.get("resultVectorMethod"),
                        "jobId": queued.get("jobId"), "assetId": asset["assetId"], "failureCode": job.get("errorCode"),
                        "failureReason": job.get("error"), "failureDetails": job.get("errorDetails"),
                        "progressHistory": progress_history, "wallSeconds": elapsed_api, "memory": memory,
                        "startCondition": "cold_first_job_in_fresh_worker" if method_position == 0 else "warm_second_job_same_worker",
                    }
                    write_json(engine_dir / "run_record.json", runs[method])
                    continue
                actual_method = job.get("resultVectorMethod")
                pipeline = job.get("resultPipeline")
                expected_pipeline = "vectorization_v2" if method == "smart_reconstruction" else "contour_preserving"
                if actual_method != method:
                    raise RuntimeError(f"Requested {method}, API executed {actual_method!r}; refusing silent engine substitution")
                if method == "smart_reconstruction" and pipeline != expected_pipeline:
                    raise RuntimeError(f"Smart V2 pipeline mismatch: expected {expected_pipeline}, got {pipeline!r}")
                if method == "contour_preserving" and job.get("resultEngine") != "Contour-Preserving":
                    raise RuntimeError(f"Contour engine metadata mismatch: {job.get('resultEngine')!r}")
                svg_path = engine_dir / "output.svg"
                svg_path.write_bytes(svg_bytes)
                validation = validate_svg(svg_path)
                validation_checks = {
                    "xmlValid": validation["xmlValid"],
                    "svgNamespaceValid": validation["svgNamespaceValid"],
                    "viewBoxValid": validation["viewBoxValid"],
                    "uniqueIds": validation["uniqueIds"],
                    "referencesResolved": not validation["unresolvedLocalReferences"],
                    "noEmbeddedRaster": validation["embeddedRasterElementCount"] == 0 and validation["embeddedRasterDataUriCount"] == 0,
                    "noExternalResources": not validation["externalResourceReferences"],
                    "noScripts": validation["scriptElementCount"] == 0,
                    "editableVector": validation["editableVector"],
                }
                validation["checks"] = validation_checks
                validation["status"] = "PASS" if all(validation_checks.values()) else "FAIL"
                write_json(engine_dir / "svg_validation.json", validation)

                render_sampler = ProcessTreeSampler().start()
                render_start = time.perf_counter()
                edge_rgba = render_svg_edge(svg_path, width=render_width, height=render_height)
                edge_render_path = engine_dir / "render_edge.png"
                Image.fromarray(edge_rgba, "RGBA").save(edge_render_path)
                render_seconds = time.perf_counter() - render_start
                skia_start = time.perf_counter()
                skia = render_svg_skia(svg_path, width=render_width, height=render_height, output_path=engine_dir / "render_skia.png")
                skia_seconds = time.perf_counter() - skia_start
                render_memory = render_sampler.stop()
                skia_summary: dict[str, Any] = {key: value for key, value in skia.items() if key != "rgba"}
                if skia.get("status") == "PASS":
                    skia_rgba = skia["rgba"]
                    skia_summary["alphaIoUAgainstEdge"] = _alpha_iou(edge_rgba, skia_rgba)
                    skia_summary["commonAlphaRgbMaeAgainstEdge"] = common_alpha_rgb_mae(edge_rgba, skia_rgba)

                alpha_path = item.get("referenceFiles", {}).get("analyticAlphaMaskPath")
                label_path = item.get("referenceFiles", {}).get("semanticLabelMapPath")
                analytic_alpha = _load_gray(alpha_path)
                semantic_labels = _load_gray(label_path)
                reference_mask = {
                    "kind": item.get("referenceType"),
                    "groundTruth": bool(analytic_alpha is not None or source_rgba[..., 3].min() < 255),
                }
                metric_started = time.perf_counter()
                metrics, bundle = evaluate_render(
                    source_rgba, edge_rgba, width=render_width, height=render_height,
                    reference_mask_kind=reference_mask, analytic_alpha=analytic_alpha,
                    semantic_label_map=semantic_labels,
                )
                metric_seconds = time.perf_counter() - metric_started
                debug_files = _copy_debug_artifacts(output_directory, queued["jobId"], engine_dir)
                metadata = job.get("resultEngineMetadata") or {}
                text_layers = job.get("resultTextLayers")
                metrics["typography"]["ocrTelemetry"] = {
                    "status": metadata.get("ocrStatus") or ("API_METADATA_NOT_EXPOSED" if method == "smart_reconstruction" else "UNKNOWN"),
                    "detectedRegionCount": metadata.get("phaseBTextRegions"),
                    "resultTextLayerCount": len(text_layers) if isinstance(text_layers, list) else None,
                    "outlinedTextCount": job.get("resultOutlinedTextCount"),
                    "editableTextCount": job.get("resultEditableTextCount"),
                    "groundTruthAvailable": False,
                    "warning": "Recognition/output telemetry is not OCR accuracy or glyph-shape fidelity without source text/glyph annotations.",
                }
                write_json(engine_dir / "quality_metrics.json", _json_safe_metrics(metrics))
                actual_config = {
                    "requested": request,
                    "actualQualityMode": job.get("resultMode"),
                    "actualTextMode": job.get("resultTextMode"),
                    "actualEngine": actual_method,
                    "actualPipeline": "contour_preserving" if method == "contour_preserving" else pipeline,
                    "apiPipelineMetadata": pipeline,
                    "resultEngineName": job.get("resultEngine"),
                    "workingWidth": metadata.get("workingWidth", job.get("resultTraceWidth")),
                    "workingHeight": metadata.get("workingHeight", job.get("resultTraceHeight")),
                    "inputWidth": job.get("resultInputWidth"),
                    "inputHeight": job.get("resultInputHeight"),
                    "resultWidth": job.get("resultWidth"),
                    "resultHeight": job.get("resultHeight"),
                    "resultPaths": job.get("resultPaths"),
                    "resultGradients": job.get("resultGradients"),
                    "phaseTimingsMs": job.get("resultPhaseTimingsMs", {}),
                    "jobProcessingTimeMs": job.get("resultProcessingTimeMs"),
                    "textLayers": text_layers,
                    "editableTextCount": job.get("resultEditableTextCount"),
                    "outlinedTextCount": job.get("resultOutlinedTextCount"),
                    "textElementCount": job.get("resultTextElementCount"),
                    "outlinedTextPathCount": job.get("resultOutlinedTextPathCount"),
                    "ocrStatus": metadata.get("ocrStatus"),
                    "ocrDetectedRegionCount": metadata.get("phaseBTextRegions"),
                    "engineMetadata": metadata,
                    "warnings": job.get("resultWarnings", []),
                }
                run_record = {
                    "status": "SUCCEEDED", "imageId": image_id, "sourceSha256": source_sha,
                    "assetId": asset["assetId"], "jobId": queued["jobId"],
                    "requestedMethod": method, "actualMethod": actual_method, "pipeline": pipeline,
                    "requestedConfiguration": request, "actualConfiguration": actual_config,
                    "requestStartedAtUtc": started_at, "jobCompletedAtUtc": utc_now(),
                    "startCondition": "cold_first_job_in_fresh_worker" if method_position == 0 else "warm_second_job_same_worker",
                    "jobWaitSeconds": round(job_wait_seconds, 3), "wallSeconds": round(elapsed_api, 3),
                    "endToEndSeconds": round(elapsed_api + render_seconds + skia_seconds + metric_seconds, 3),
                    "renderValidationSeconds": round(render_seconds + skia_seconds + metric_seconds, 3),
                    "edgeRenderSeconds": round(render_seconds, 3), "skiaRenderSeconds": round(skia_seconds, 3),
                    "cpuSecondsRootProcess": round(cpu_seconds, 3), "memory": memory,
                    "renderMemory": render_memory,
                    "svgPath": str(svg_path), "svgSha256": file_sha256(svg_path), "svgBytes": len(svg_bytes),
                    "svgValidation": validation, "edgeRenderPath": str(edge_render_path),
                    "edgeRenderSha256": file_sha256(edge_render_path),
                    "skiaRenderSha256": file_sha256(Path(skia_summary["outputPath"])) if skia_summary.get("status") == "PASS" and skia_summary.get("outputPath") else None,
                    "skiaRendererCheck": skia_summary, "renderDimensions": [render_width, render_height],
                    "qualityMetrics": _json_safe_metrics(metrics), "debugArtifactFiles": debug_files,
                    "progressHistory": progress_history,
                }
                runs[method] = run_record
                write_json(engine_dir / "run_record.json", run_record)

            record: dict[str, Any] = {
                "schemaVersion": 1, "runId": run_id, "imageId": image_id,
                "sourcePath": str(source_path), "sourceSha256": source_sha,
                "sourceFamilyId": item.get("sourceFamilyId"), "sourceType": item.get("sourceType"),
                "categories": item.get("categories", []), "datasetSplit": item.get("datasetSplit"),
                "referenceType": item.get("referenceType"), "hasTypography": item.get("hasTypography", False),
                "inputDimensions": [input_width, input_height], "renderDimensions": [render_width, render_height],
                "sameAssetIdUsedByBothEngines": set(runs) == set(ENGINE_NAMES) and len({row.get("assetId") for row in runs.values() if row.get("assetId")}) == 1,
                "assetId": asset["assetId"], "uploadSeconds": round(upload_seconds, 3),
                "engineOrder": method_order, "engines": runs,
                "status": "PASS" if all(runs.get(name, {}).get("status") == "SUCCEEDED" for name in ENGINE_NAMES) else "PARTIAL_OR_FAILED",
                "humanReviewStatus": "pending_human_review",
            }
            if all(record["engines"].get(name, {}).get("status") == "SUCCEEDED" for name in ENGINE_NAMES):
                source_for_visuals = np.asarray(Image.fromarray(source_rgba).resize((render_width, render_height), Image.Resampling.LANCZOS), dtype=np.uint8)
                smart_rgba = np.asarray(Image.open(record["engines"]["smart_reconstruction"]["edgeRenderPath"]).convert("RGBA"), dtype=np.uint8)
                contour_rgba = np.asarray(Image.open(record["engines"]["contour_preserving"]["edgeRenderPath"]).convert("RGBA"), dtype=np.uint8)
                # Engine bundles carry independent, source-aligned error maps and masks.
                smart_metrics, smart_bundle = evaluate_render(source_rgba, smart_rgba, width=render_width, height=render_height,
                    reference_mask_kind={"groundTruth": reference_mask["groundTruth"]}, analytic_alpha=analytic_alpha, semantic_label_map=semantic_labels)
                contour_metrics, contour_bundle = evaluate_render(source_rgba, contour_rgba, width=render_width, height=render_height,
                    reference_mask_kind={"groundTruth": reference_mask["groundTruth"]}, analytic_alpha=analytic_alpha, semantic_label_map=semantic_labels)
                visuals = persist_visual_diagnostics(image_id=image_id, artifact_root=run_root / "visuals",
                    source_rgba=source_for_visuals, smart_rgba=smart_rgba, contour_rgba=contour_rgba,
                    smart_bundle=smart_bundle, contour_bundle=contour_bundle,
                    has_typography=bool(item.get("hasTypography", False)))
                record["visualDiagnostics"] = visuals
            return record


def _alpha_iou(a: np.ndarray, b: np.ndarray) -> float:
    ma, mb = a[..., 3] > 16, b[..., 3] > 16
    return float(np.count_nonzero(ma & mb) / max(np.count_nonzero(ma | mb), 1))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--item-json", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--result-json", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
    os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
    # The existing Smart V2 diagnostics writer assumes at least four appearance
    # regions and can raise for simple fixtures. Keep this opt-in writer off so
    # diagnostics do not change API job success; API phase timings remain captured.
    os.environ["DEBUG_VECTOR"] = "0"
    item = json.loads(Path(args.item_json).read_text(encoding="utf-8"))
    try:
        result = run_image(item, Path(args.artifact_root), per_engine_timeout=args.timeout, run_id=args.run_id)
        write_json(Path(args.result_json), result)
        print(json.dumps({"imageId": result["imageId"], "status": result["status"], "sourceSha256": result["sourceSha256"]}, ensure_ascii=False))
        return 0 if result["status"] == "PASS" else 2
    except BaseException as error:
        recovered: dict[str, Any] = {}
        for method in ENGINE_NAMES:
            saved = Path(args.artifact_root) / "runs" / args.run_id / "outputs" / str(item.get("imageId")) / method / "run_record.json"
            if saved.is_file():
                try:
                    recovered[method] = json.loads(saved.read_text(encoding="utf-8"))
                except Exception:
                    pass
        failure = {
            "schemaVersion": 1, "runId": args.run_id, "imageId": item.get("imageId"),
            "sourceSha256": item.get("sha256"), "status": "FAILED",
            "failureType": type(error).__name__, "failureReason": str(error),
            "engines": recovered,
            "recordedAtUtc": utc_now(),
        }
        write_json(Path(args.result_json), failure)
        print(json.dumps(failure, ensure_ascii=False), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
