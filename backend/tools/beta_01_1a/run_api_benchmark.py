from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
PACK = REPO / "mediastudio_beta_testpack"
OUT = BACKEND / "artifacts" / "contour_preserving" / "beta_01_1a"
sys.path.insert(0, str(BACKEND))

from mediastudio.api import create_app  # noqa: E402
from mediastudio.desktop_capabilities import install_desktop_capabilities  # noqa: E402
from tools.vectorization_benchmark.performance import ProcessTreeSampler  # noqa: E402
from tools.vectorization_benchmark.svg import render_svg_edge, render_svg_skia, validate_svg  # noqa: E402

TOKEN = "mediastudio-beta-01-1a-local-validation-token"
PREFLIGHT_IDS = ["C01_three_tone_disc", "C06_rocket", "D01_small_colored_islands", "A04_transparent_fine_lines"]
METHODS = ["smart_reconstruction", "contour_preserving"]
SVG_NS = "http://www.w3.org/2000/svg"
MATRIX_PATH = OUT / "api_run_matrix.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(encoded, encoding="utf-8")
    os.replace(temp, path)


def load_manifest() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    manifest = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))
    return manifest, {str(row["id"]): row for row in manifest["items"]}


def config_for(method: str) -> dict[str, Any]:
    return {
        "engineMethod": method,
        "vectorizationPipeline": "v2",
        "apiEngine": "auto",
        "mode": "auto",
        "colorCount": None,
        "simplification": None,
        "smoothPaths": True,
        "transparentBackground": True,
        "textMode": "outlined",
        "contourExperimental": method == "contour_preserving",
        "timeoutApplied": False,
    }


def _load_matrix() -> dict[str, Any]:
    if MATRIX_PATH.is_file():
        try:
            matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
            if matrix.get("schemaVersion") == 1:
                return matrix
        except Exception:
            pass
    return {"schemaVersion": 1, "task": "BETA-01.1A", "packPath": str(PACK), "cases": {},
            "preflight": {"status": "NOT_RUN", "fixtureIds": PREFLIGHT_IDS},
            "fullBenchmark": {"status": "NOT_RUN", "expectedFixtureCount": 24, "expectedEngineCaseCount": 48},
            "policy": "No engine cache hit is reused across tasks; successful cases in this task are resume-eligible only when source SHA and canonical request config match."}


def _case_key(fid: str, method: str) -> str:
    return f"{fid}|{method}"


def _valid_reusable_case(row: dict[str, Any], source_hash: str, request: dict[str, Any]) -> bool:
    return (row.get("sourceSha256") == source_hash and row.get("requestedConfiguration") == request
            and row.get("apiJobStatus") == "SUCCEEDED" and row.get("svgPath")
            and Path(row["svgPath"]).is_file() and sha256_file(Path(row["svgPath"])) == row.get("svgSha256"))


def _wait_for_job(client: TestClient, job_id: str, headers: dict[str, str]) -> tuple[dict[str, Any], bytes, float, list[dict[str, Any]]]:
    started = time.perf_counter()
    history: list[dict[str, Any]] = []
    while True:  # BETA-01.1A applies no job timeout; actual runtime is recorded.
        response = client.get(f"/api/v1/jobs/{job_id}", headers=headers)
        response.raise_for_status()
        job = response.json()
        history.append({"atUtc": utc_now(), "state": job.get("state"), "stage": job.get("stage"),
                        "progress": job.get("progress")})
        if job.get("state") in {"succeeded", "failed"}:
            if job.get("state") != "succeeded":
                return job, b"", time.perf_counter() - started, history
            response = client.get(f"/api/v1/jobs/{job_id}/result", headers=headers)
            response.raise_for_status()
            media = response.headers.get("content-type", "").split(";", 1)[0]
            if media != "image/svg+xml":
                raise RuntimeError(f"Expected image/svg+xml, got {media!r}")
            return job, response.content, time.perf_counter() - started, history
        time.sleep(0.25)


def _engine_metadata(method: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    meta = snapshot.get("resultEngineMetadata") or {}
    return {
        "actualMethod": snapshot.get("resultVectorMethod"),
        "pipeline": snapshot.get("resultPipeline"),
        "engineName": snapshot.get("resultEngine"),
        "mode": snapshot.get("resultMode"),
        "textMode": snapshot.get("resultTextMode"),
        "inputWidth": snapshot.get("resultInputWidth"),
        "inputHeight": snapshot.get("resultInputHeight"),
        "outputWidth": snapshot.get("resultWidth"),
        "outputHeight": snapshot.get("resultHeight"),
        "traceWidth": snapshot.get("resultTraceWidth"),
        "traceHeight": snapshot.get("resultTraceHeight"),
        "pathCount": snapshot.get("resultPaths"),
        "regionCount": snapshot.get("resultRegions"),
        "gradientCount": snapshot.get("resultGradients"),
        "phaseTimingsMs": snapshot.get("resultPhaseTimingsMs", {}),
        "warnings": snapshot.get("resultWarnings", []),
        "warningDetails": snapshot.get("resultWarningDetails", []),
        "engineMetadata": meta,
        "fallback": meta.get("fallback", False),
        "topologyGeometryValid": (meta.get("topology", {}).get("geometryValid")
                                  if isinstance(meta.get("topology"), dict) else None),
    }


def _validate_and_render(svg_path: Path, out_dir: Path, source_size: tuple[int, int]) -> dict[str, Any]:
    structural = validate_svg(svg_path)
    root = ET.parse(svg_path).getroot()
    width, height = source_size
    try:
        view_box = [float(value) for value in root.attrib.get("viewBox", "").replace(",", " ").split()]
    except ValueError:
        view_box = []
    def declared_px(value: str | None) -> float | None:
        if not value:
            return None
        text = value.strip().lower().removesuffix("px")
        try:
            return float(text)
        except ValueError:
            return None
    dimensions = {
        "declaredWidth": root.attrib.get("width"), "declaredHeight": root.attrib.get("height"),
        "viewBox": view_box,
        "dimensionsMatchSource": (declared_px(root.attrib.get("width")) == width
                                   and declared_px(root.attrib.get("height")) == height),
        "viewBoxMatchesSource": len(view_box) == 4 and np.allclose(view_box, [0, 0, width, height]),
    }
    valid_xml = bool(structural.get("xmlValid"))
    no_raster = structural.get("embeddedRasterElementCount") == 0 and structural.get("embeddedRasterDataUriCount") == 0
    no_external = structural.get("resourcePolicyValid") is True
    vector_content = structural.get("visiblePathElementCount", 0) > 0 or any(
        tag.rsplit("}", 1)[-1].lower() in {"polygon", "circle", "ellipse", "rect", "line", "polyline"}
        for tag in (node.tag for node in root.iter()))
    render_path = out_dir / "render_edge_512.png"
    rgba = render_svg_edge(svg_path, width=width, height=height)
    Image.fromarray(rgba, "RGBA").save(render_path)
    visible_pixels = int(np.count_nonzero(rgba[..., 3] > 16))
    visible = visible_pixels > 0
    svg_skia_path = out_dir / "render_skia_512.png"
    skia = render_svg_skia(svg_path, width=width, height=height, output_path=svg_skia_path)
    if "rgba" in skia:
        skia = {key: value for key, value in skia.items() if key != "rgba"}
    integrity_checks = {
        "xmlValid": valid_xml,
        "svgNamespaceValid": structural.get("svgNamespaceValid") is True,
        "viewBoxValid": structural.get("viewBoxValid") is True and dimensions["viewBoxMatchesSource"],
        "dimensionsMatchSource": dimensions["dimensionsMatchSource"],
        "uniqueIds": structural.get("uniqueIds") is True,
        "referencesResolved": not structural.get("unresolvedLocalReferences"),
        "noExternalResources": no_external,
        "noEmbeddedRaster": no_raster,
        "vectorElementsPresent": vector_content,
        "edgeRendererVisible": visible,
    }
    geometry_meta_valid = structural.get("svgNamespaceValid") is True and structural.get("viewBoxValid") is True and vector_content and visible
    return {
        "svgSha256": sha256_file(svg_path), "svgBytes": svg_path.stat().st_size,
        "svgStructural": structural, "dimensions": dimensions,
        "edgeRender": {"status": "PASS" if visible else "FAIL", "path": str(render_path),
                       "sha256": sha256_file(render_path), "width": width, "height": height,
                       "visibleAlphaPixels": visible_pixels, "renderer": "Microsoft Edge headless"},
        "svgSkia": skia,
        "checks": integrity_checks,
        "validSvg": bool(all(integrity_checks.values())),
        "visibleSvg": bool(visible),
        "vectorOnly": bool(no_raster and no_external and vector_content),
        "geometryValidStatus": "STRUCTURE_AND_NATIVE_RENDER_VALID" if geometry_meta_valid else "INVALID_OR_NOT_RENDERABLE",
        "geometryValidityScope": "SVG XML, viewBox/dimensions, vector element presence, and native browser rendering; this is not a proof of non-self-intersecting geometry.",
        "fidelityAccepted": False,
        "fidelityStatus": "NOT_ACCEPTED_AUTOMATICALLY; metrics and human review are separate gates",
    }


def _production_paths() -> list[Path]:
    reference = BACKEND / "artifacts" / "contour_preserving" / "beta_01_0" / "production_changes.json"
    data = json.loads(reference.read_text(encoding="utf-8"))
    names = list(data.get("afterSha256", {}).keys())
    return [REPO / Path(name) for name in names]


def _hash_snapshot() -> dict[str, str]:
    return {path.relative_to(REPO).as_posix(): sha256_file(path) for path in _production_paths() if path.is_file()}


def run_stage(stage: str, requested_ids: list[str] | None = None) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    pack_validation_path = OUT / "input_manifest_validation.json"
    if not pack_validation_path.is_file() or not json.loads(pack_validation_path.read_text(encoding="utf-8")).get("inputPackValid"):
        raise RuntimeError("Pack validation has not passed; API tests are prohibited until it does.")
    manifest, items = load_manifest()
    matrix = _load_matrix()
    prod_before_path = OUT / "production_before_sha256.json"
    if not prod_before_path.is_file():
        write_json(prod_before_path, {"capturedAtUtc": utc_now(), "scope": "BETA-01.0 audited 85 production source/config files",
            "files": _hash_snapshot()})
    if stage == "preflight":
        ids = requested_ids or PREFLIGHT_IDS
        matrix["preflight"] = {"status": "RUNNING", "fixtureIds": ids, "expectedCaseCount": len(ids) * 2,
                                "startedAtUtc": matrix.get("preflight", {}).get("startedAtUtc") or utc_now()}
    elif stage == "full":
        if matrix.get("preflight", {}).get("status") != "PASS":
            raise RuntimeError("Full benchmark is gated on a passing preflight.")
        ids = requested_ids or list(items)
        matrix["fullBenchmark"] = {"status": "RUNNING", "fixtureIds": ids, "expectedFixtureCount": len(ids),
                                   "expectedEngineCaseCount": len(ids) * 2,
                                   "startedAtUtc": matrix.get("fullBenchmark", {}).get("startedAtUtc") or utc_now()}
    else:
        raise ValueError(stage)

    os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
    os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
    os.environ["DEBUG_VECTOR"] = "0"
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    models_dir = local_app_data / "MediaStudio" / "models" / "realesrgan"
    all_preflight_ok = True

    for order, fid in enumerate(ids):
        if fid not in items:
            raise KeyError(f"Unknown fixture id {fid}")
        item = items[fid]
        source_path = PACK / str(item["png_paths"]["512"])
        source_bytes = source_path.read_bytes()
        source_hash = sha256_bytes(source_bytes)
        if source_hash != item["png_sha256"]["512"]:
            raise RuntimeError(f"Hash drift for {fid}; stopping without uploading")
        request_configs = {method: {
            "asset_id": None, "engine": "auto", "mode": "auto", "color_count": None,
            "simplification": None, "smooth_paths": True, "transparent_background": True,
            "text_mode": "outlined", "vector_method": method,
        } for method in METHODS}
        reusable = {
            method: _valid_reusable_case(matrix.get("cases", {}).get(_case_key(fid, method), {}), source_hash,
                                         {k: v for k, v in request_configs[method].items() if k != "asset_id"})
            for method in METHODS
        }
        missing = [method for method in METHODS if not reusable[method]]
        if not missing:
            print(f"[{stage}] {fid}: reuse exact source/config outputs from this task", flush=True)
            continue

        work = OUT / "runs" / stage / fid / "workspace"
        output_directory = OUT / "runs" / stage / fid / "api_output"
        app = create_app(TOKEN, work, models_dir)
        install_desktop_capabilities(app)
        app.state.output_directory = output_directory
        headers = {"X-Media-Studio-Token": TOKEN}
        try:
            with TestClient(app) as client:
                health_response = client.get("/api/v1/health", headers=headers)
                health_response.raise_for_status()
                health = health_response.json()
                caps_response = client.get("/api/v1/desktop/contour-capabilities", headers=headers)
                caps_response.raise_for_status()
                capabilities = caps_response.json()
                if not capabilities.get("ready"):
                    raise RuntimeError(f"Contour experimental dependency/flag unavailable: {capabilities}")
                if health.get("vectorizationPipeline") != "v2" or health.get("contourExperimentalEnabled") is not True:
                    raise RuntimeError(f"Unexpected API engine configuration: {health}")
                upload_started = time.perf_counter()
                upload = client.post("/api/v1/assets", headers=headers,
                    files={"file": (source_path.name, source_bytes, "image/png")})
                upload.raise_for_status()
                asset = upload.json()
                upload_seconds = time.perf_counter() - upload_started
                if (asset.get("width"), asset.get("height")) != (512, 512):
                    raise RuntimeError(f"API upload decoded wrong dimensions for {fid}: {asset}")

                for method in missing:
                    key = _case_key(fid, method)
                    config = {k: v for k, v in request_configs[method].items() if k != "asset_id"}
                    request = {**request_configs[method], "asset_id": asset["assetId"]}
                    started_utc = utc_now()
                    wall = time.perf_counter()
                    sampler = ProcessTreeSampler().start()
                    row: dict[str, Any] = {
                        "fixtureId": fid,
                        "sourceFamilyId": item["source_family_id"],
                        "sourceOrigin": item["origin"],
                        "engine": method,
                        "sourceSha256": source_hash,
                        "engineConfiguration": config_for(method),
                        "apiRequestConfiguration": request,
                        "requestedConfiguration": config,
                        "configSha256": hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                        "apiEnvironment": {"health": health, "contourCapabilities": capabilities,
                                           "scikitImageVersion": capabilities.get("dependencyVersion")},
                        "uploadSeconds": round(upload_seconds, 4),
                        "requestStartedAtUtc": started_utc,
                        "apiJobStatus": "SUBMITTING",
                        "timeoutApplied": False,
                        "artifactDirectory": str(OUT / "runs" / stage / fid / method),
                        "stage": stage,
                    }
                    write_json(MATRIX_PATH, matrix)
                    try:
                        queued_response = client.post("/api/v1/vectorize/jobs", headers=headers, json=request)
                        row["jobCreateHttpStatus"] = queued_response.status_code
                        queued_response.raise_for_status()
                        queued = queued_response.json()
                        row["jobId"] = queued.get("jobId")
                        job, svg_bytes, job_wait, progress = _wait_for_job(client, str(row["jobId"]), headers)
                        row["progressHistory"] = progress
                        row["jobWallSeconds"] = round(job_wait, 4)
                        row["jobCompletedAtUtc"] = utc_now()
                        row["jobSnapshot"] = job
                        row["engineResultMetadata"] = _engine_metadata(method, job)
                        row["apiJobStatus"] = "SUCCEEDED" if job.get("state") == "succeeded" else "FAILED"
                        row["errorCode"] = job.get("errorCode")
                        row["errorMessage"] = job.get("error")
                        row["errorDetails"] = job.get("errorDetails")
                        row["apiProcessingTimeMs"] = job.get("resultProcessingTimeMs")
                        row["actualMethod"] = job.get("resultVectorMethod")
                        row["actualPipeline"] = job.get("resultPipeline")
                        row["outputDimensions"] = [job.get("resultWidth"), job.get("resultHeight")]
                        row["memory"] = sampler.stop()
                        row["caseRuntimeSeconds"] = round(time.perf_counter() - wall, 4)
                        if row["apiJobStatus"] == "SUCCEEDED":
                            if row["actualMethod"] != method:
                                raise RuntimeError(f"Requested {method} but API reported {row['actualMethod']}")
                            if method == "smart_reconstruction" and row["actualPipeline"] != "vectorization_v2":
                                raise RuntimeError(f"Smart V2 pipeline drift: {row['actualPipeline']}")
                            if method == "contour_preserving" and row["actualPipeline"] != "contour_preserving":
                                raise RuntimeError(f"Contour pipeline drift: {row['actualPipeline']}")
                            if row["outputDimensions"] != [512, 512]:
                                raise RuntimeError(f"API result dimension mismatch for {fid}/{method}: {row['outputDimensions']}")
                            case_dir = OUT / "runs" / stage / fid / method
                            case_dir.mkdir(parents=True, exist_ok=True)
                            svg_path = case_dir / "output.svg"
                            svg_path.write_bytes(svg_bytes)
                            row["svgPath"] = str(svg_path)
                            row["svgSha256"] = sha256_file(svg_path)
                            row["svgIntegrity"] = _validate_and_render(svg_path, case_dir, (512, 512))
                        else:
                            all_preflight_ok = False
                        row["requestEndedAtUtc"] = utc_now()
                        matrix.setdefault("cases", {})[key] = row
                        matrix["lastUpdatedAtUtc"] = utc_now()
                        write_json(MATRIX_PATH, matrix)
                        print(f"[{stage}] {fid}/{method}: {row['apiJobStatus']} "
                              f"runtime={row.get('caseRuntimeSeconds')}s svg={row.get('svgSha256')}", flush=True)
                    except Exception as exc:
                        try:
                            row["memory"] = sampler.stop()
                        except Exception:
                            pass
                        row["apiJobStatus"] = "HARNESS_ERROR"
                        row["errorMessage"] = str(exc)
                        row["traceback"] = traceback.format_exc()
                        row["caseRuntimeSeconds"] = round(time.perf_counter() - wall, 4)
                        row["requestEndedAtUtc"] = utc_now()
                        matrix.setdefault("cases", {})[key] = row
                        if stage == "preflight":
                            matrix["preflight"].update({"status": "FAIL", "completedAtUtc": utc_now(),
                                "stoppedAfterCase": key, "stopReason": str(exc)})
                        write_json(MATRIX_PATH, matrix)
                        all_preflight_ok = False
                        print(f"[{stage}] {fid}/{method}: HARNESS_ERROR {exc}", flush=True)
                        # API/render pipeline failures are preserved and stop a preflight batch.
                        if stage == "preflight":
                            raise
        finally:
            app.state.jobs.shutdown()

    all_preflight_ok = all(
        _valid_reusable_case(matrix.get("cases", {}).get(_case_key(fid, method), {}),
            sha256_file(PACK / str(items[fid]["png_paths"]["512"])),
            {k: v for k, v in {
                "asset_id": None, "engine": "auto", "mode": "auto", "color_count": None,
                "simplification": None, "smooth_paths": True, "transparent_background": True,
                "text_mode": "outlined", "vector_method": method}.items() if k != "asset_id"})
        and matrix["cases"][_case_key(fid, method)].get("svgIntegrity", {}).get("validSvg") is True
        and matrix["cases"][_case_key(fid, method)].get("svgIntegrity", {}).get("visibleSvg") is True
        and matrix["cases"][_case_key(fid, method)].get("svgIntegrity", {}).get("vectorOnly") is True
        for fid in ids for method in METHODS)
    if stage == "preflight":
        matrix["preflight"].update({"status": "PASS" if all_preflight_ok else "FAIL",
            "completedAtUtc": utc_now(), "completedCaseCount": len(ids) * 2,
            "apiFailures": [key for key, row in matrix.get("cases", {}).items()
                            if row.get("stage") == "preflight" and row.get("apiJobStatus") != "SUCCEEDED"],
            "blockingIntegrityFailures": [key for key, row in matrix.get("cases", {}).items()
                if row.get("stage") == "preflight" and row.get("svgIntegrity", {}).get("validSvg") is not True]})
    else:
        rows = [row for key, row in matrix.get("cases", {}).items()
                if row.get("fixtureId") in ids and row.get("apiJobStatus") != "SUBMITTING"]
        completed = [row for row in rows if row.get("apiJobStatus") == "SUCCEEDED"]
        matrix["fullBenchmark"].update({"status": "COMPLETE" if len(completed) == len(ids) * 2 else "PARTIAL",
            "completedAtUtc": utc_now(), "completedFixtureEngineCases": len(completed),
            "missingCases": [f"{fid}|{method}" for fid in ids for method in METHODS
                             if not _valid_reusable_case(matrix.get("cases", {}).get(_case_key(fid, method), {}),
                                 sha256_file(PACK / str(items[fid]["png_paths"]["512"])),
                                 {k: v for k, v in {"asset_id": None, "engine": "auto", "mode": "auto",
                                     "color_count": None, "simplification": None, "smooth_paths": True,
                                     "transparent_background": True, "text_mode": "outlined",
                                     "vector_method": method}.items() if k != "asset_id"})]})
    write_json(MATRIX_PATH, matrix)
    print(json.dumps({"stage": stage, "status": matrix["preflight" if stage == "preflight" else "fullBenchmark"]["status"],
        "caseCountInMatrix": len(matrix.get("cases", {})), "preflight": matrix["preflight"],
        "fullBenchmark": matrix["fullBenchmark"]}, indent=2, ensure_ascii=False))
    return 0 if matrix["preflight" if stage == "preflight" else "fullBenchmark"]["status"] in {"PASS", "COMPLETE"} else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("preflight", "full"))
    parser.add_argument("fixture_ids", nargs="*")
    args = parser.parse_args()
    raise SystemExit(run_stage(args.stage, args.fixture_ids or None))
