from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from .dataset import (ARTIFACTS, CATEGORY_NAMES, MANIFEST_PATH, SPLIT_PATH, build_initial_manifest,
                      canonical_sha256, dataset_coverage, dataset_inventory, lock_split,
                      validate_dataset, write_json)
from .reporting import write_all_reports


BACKEND = Path(__file__).resolve().parents[2]
REPOSITORY = BACKEND.parent
CHECKPOINT_PATH = ARTIFACTS / "per_image_results.json"
CODE_PATHS = [
    BACKEND / "mediastudio" / "api.py",
    BACKEND / "mediastudio" / "desktop_capabilities.py",
    BACKEND / "mediastudio" / "image_tools" / "vectorize.py",
    BACKEND / "mediastudio" / "image_tools" / "vectorization_v2" / "production.py",
    BACKEND / "mediastudio" / "image_tools" / "vectorization_v2" / "pipeline.py",
    BACKEND / "mediastudio" / "image_tools" / "contour_backend.py",
    BACKEND / "mediastudio" / "image_tools" / "contour_svg_composer.py",
    REPOSITORY / "src" / "MediaStudio.Desktop" / "Services" / "VectorizationJobService.cs",
    REPOSITORY / "src" / "MediaStudio.Desktop" / "ViewModels" / "VectorizeToolViewModel.cs",
]
CODE_PATHS += sorted((BACKEND / "mediastudio" / "image_tools" / "vectorization_v2").glob("*.py"))
CODE_PATHS += sorted((BACKEND / "mediastudio" / "image_tools").glob("contour*.py"))
BENCHMARK_PATHS = sorted(Path(__file__).resolve().parent.glob("*.py"))


def _sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _snapshots() -> dict[str, str | None]:
    return {path.relative_to(REPOSITORY).as_posix(): _sha(path) for path in CODE_PATHS}


def _benchmark_hashes() -> dict[str, str | None]:
    return {path.relative_to(REPOSITORY).as_posix(): _sha(path) for path in BENCHMARK_PATHS}


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file():
        raise FileNotFoundError(f"Dataset manifest is missing. Run: python -m tools.vectorization_benchmark init")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _checkpoint() -> dict[str, dict[str, Any]]:
    if not CHECKPOINT_PATH.is_file():
        return {}
    value = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    return {row["imageId"]: row for row in value.get("items", []) if row.get("imageId")}


def _is_resumable(record: dict[str, Any] | None, item: dict[str, Any], run_id: str) -> bool:
    if not record or record.get("status") != "PASS" or record.get("runId") != run_id or record.get("sourceSha256") != item.get("sha256"):
        return False
    for method in ("smart_reconstruction", "contour_preserving"):
        run = (record.get("engines") or {}).get(method, {})
        svg_path, render_path = Path(run.get("svgPath", "")), Path(run.get("edgeRenderPath", ""))
        if run.get("status") != "SUCCEEDED" or not svg_path.is_file() or not render_path.is_file():
            return False
        if _sha(svg_path) != run.get("svgSha256") or _sha(render_path) != run.get("edgeRenderSha256"):
            return False
    return True


def _select_items(manifest: dict[str, Any], *, scope: str, category: str | None, image_ids: list[str] | None) -> list[dict[str, Any]]:
    items = manifest.get("items", [])
    if image_ids:
        wanted = set(image_ids)
        selected = [item for item in items if item.get("imageId") in wanted]
        missing = wanted - {item.get("imageId") for item in selected}
        if missing:
            raise ValueError(f"Unknown image id(s): {sorted(missing)}")
    elif scope == "smoke":
        preferred = ("active-fox-native-jpeg", "synthetic-sharp_polygon", "synthetic-linear_gradient", "synthetic-thin_line", "synthetic-multiregion_illustration", "synthetic-jpeg_compressed_illustration")
        by_id = {item.get("imageId"): item for item in items}
        selected = [by_id[name] for name in preferred if name in by_id]
    elif scope == "category":
        if category not in CATEGORY_NAMES:
            raise ValueError(f"For --scope category specify --category from: {', '.join(CATEGORY_NAMES)}")
        selected = [item for item in items if category in item.get("categories", [])]
    else:
        selected = list(items)
    return sorted(selected, key=lambda item: str(item.get("imageId")))


def initialize_dataset(*, force: bool = False) -> dict[str, Any]:
    manifest = build_initial_manifest(force=force)
    validation = validate_dataset()
    inventory = dataset_inventory(validation)
    coverage = dataset_coverage(validation)
    write_json(ARTIFACTS / "dataset_inventory.json", inventory)
    write_json(ARTIFACTS / "dataset_coverage.json", coverage)
    write_json(ARTIFACTS / "dataset_validation.json", validation)
    return {"manifest": manifest, "validation": validation, "inventory": inventory, "coverage": coverage}


def validate_and_write() -> dict[str, Any]:
    validation = validate_dataset()
    inventory = dataset_inventory(validation)
    coverage = dataset_coverage(validation)
    write_json(ARTIFACTS / "dataset_inventory.json", inventory)
    write_json(ARTIFACTS / "dataset_coverage.json", coverage)
    write_json(ARTIFACTS / "dataset_validation.json", validation)
    return validation


def _kill_process_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=15, check=False)
    else:
        try:
            os.killpg(pid, 9)
        except Exception:
            pass


def _run_worker(item: dict[str, Any], *, run_id: str, timeout: int, logs_dir: Path) -> dict[str, Any]:
    run_root = ARTIFACTS / "runs" / run_id
    logs_dir = run_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    item_path = run_root / "temp" / f"{item['imageId']}.json"
    result_path = run_root / "worker_results" / f"{item['imageId']}.json"
    item_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    stable_order = int(hashlib.sha256(str(item["imageId"]).encode("utf-8")).hexdigest()[:2], 16) % 2
    item = {**item, "benchmarkOrderIndex": stable_order}
    write_json(item_path, item)
    command = [sys.executable, "-m", "tools.vectorization_benchmark.worker", "--item-json", str(item_path),
               "--artifact-root", str(ARTIFACTS), "--result-json", str(result_path), "--run-id", run_id,
               "--timeout", str(timeout)]
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    stdout_path, stderr_path = logs_dir / f"{item['imageId']}.stdout.log", logs_dir / f"{item['imageId']}.stderr.log"
    started = time.perf_counter()
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, cwd=BACKEND, env=environment, stdout=stdout, stderr=stderr, text=True)
        timed_out = False
        try:
            return_code = process.wait(timeout=max(60, timeout * 2 + 90))
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree(process.pid)
            try:
                return_code = process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = process.wait(timeout=10)
    elapsed = time.perf_counter() - started
    if timed_out:
        return {"schemaVersion": 1, "runId": run_id, "imageId": item["imageId"], "sourceSha256": item.get("sha256"),
                "status": "FAILED", "failureType": "PER_IMAGE_TIMEOUT", "failureReason": f"Worker subprocess exceeded {timeout * 2 + 90}s; process tree termination requested.",
                "workerReturnCode": return_code, "workerWallSeconds": round(elapsed, 3), "stdoutLog": str(stdout_path), "stderrLog": str(stderr_path)}
    if not result_path.is_file():
        return {"schemaVersion": 1, "runId": run_id, "imageId": item["imageId"], "sourceSha256": item.get("sha256"),
                "status": "FAILED", "failureType": "WORKER_RESULT_MISSING", "failureReason": f"Worker exited {return_code} without a result checkpoint.",
                "workerWallSeconds": round(elapsed, 3), "stdoutLog": str(stdout_path), "stderrLog": str(stderr_path)}
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["workerReturnCode"] = return_code
    result["workerWallSeconds"] = round(elapsed, 3)
    result["stdoutLog"] = str(stdout_path)
    result["stderrLog"] = str(stderr_path)
    return result


def run_benchmark(*, scope: str = "all", category: str | None = None, image_ids: list[str] | None = None,
                  timeout: int = 900, resume: bool = False) -> dict[str, Any]:
    manifest = _load_manifest()
    validation = validate_and_write()
    if validation.get("status") != "PASS":
        raise RuntimeError(f"Dataset validation failed; refusing benchmark: {validation}")
    selected = _select_items(manifest, scope=scope, category=category, image_ids=image_ids)
    if not selected:
        raise ValueError("No dataset images selected")
    config = {
        "schemaVersion": 1, "requestedScope": scope, "requestedCategory": category,
        "sameAssetPerEngine": True, "engineMethods": ["smart_reconstruction", "contour_preserving"],
        "engine": "auto", "qualityMode": "auto", "textMode": "outlined", "transparentBackground": True,
        "colorCount": None, "simplification": None, "smoothPaths": True,
        "renderLongEdgeMax": 1600, "primaryRenderer": "Edge/Chromium through existing Phase E1 renderer",
        "secondaryRenderer": "Svg.Skia 5.2.3 when existing local diagnostic binary is available",
        "apiPipeline": "v2", "experimentalContourOptIn": "benchmark worker only",
        "smartV2DebugArtifacts": False,
        "diagnosticNote": "The existing Smart V2 debug writer assumes a region artifact named R04 and can fail on low-region fixtures; benchmark leaves DEBUG_VECTOR off to preserve API behavior and records engine phase timings instead.",
    }
    run_material = {"datasetManifest": canonical_sha256(manifest), "config": config,
                    "productionCode": _snapshots(), "benchmarkCode": _benchmark_hashes()}
    run_id = "task08a-" + canonical_sha256(run_material)[:16]
    run_manifest = {
        "schemaVersion": 1, "runId": run_id, "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "selectedImageIds": [item["imageId"] for item in selected], "datasetManifestSha256": canonical_sha256(manifest),
        "datasetSplitLock": json.loads(SPLIT_PATH.read_text(encoding="utf-8")) if SPLIT_PATH.exists() else None,
        "config": config, "productionSourceSha256Before": run_material["productionCode"],
        "benchmarkCodeSha256": run_material["benchmarkCode"], "resumed": resume,
        "productionDefaultsModifiedByBenchmark": False,
    }
    write_json(ARTIFACTS / "benchmark_run_manifest.json", run_manifest)
    checkpoint = _checkpoint()
    records = list(checkpoint.values()) if resume else []
    completed_ids = set(checkpoint) if resume else set()
    failures = []
    for index, item in enumerate(selected, 1):
        old = checkpoint.get(item["imageId"])
        if resume and _is_resumable(old, item, run_id):
            print(f"[{index}/{len(selected)}] {item['imageId']}: resume skip (verified result hashes)", flush=True)
            continue
        print(f"[{index}/{len(selected)}] {item['imageId']}: running Smart V2 + Contour via API", flush=True)
        result = _run_worker(item, run_id=run_id, timeout=timeout, logs_dir=ARTIFACTS / "runs" / run_id / "logs")
        if result.get("status") != "PASS":
            failures.append(result)
        checkpoint[item["imageId"]] = result
        records = list(checkpoint.values())
        write_json(CHECKPOINT_PATH, {"schemaVersion": 1, "runId": run_id, "items": records})
        print(f"    {item['imageId']}: {result.get('status')}; {result.get('workerWallSeconds', 0):.1f}s", flush=True)
    # Keep records from prior successful checkpoint entries only when they belong to this same run identity.
    records = [row for row in _checkpoint().values() if row.get("runId") == run_id]
    outputs = write_all_reports(records, manifest, ARTIFACTS)
    end_snapshot = _snapshots()
    production_unchanged = end_snapshot == run_manifest["productionSourceSha256Before"]
    benchmark_unchanged = _benchmark_hashes() == run_manifest["benchmarkCodeSha256"]
    unchanged = production_unchanged and benchmark_unchanged
    run_manifest.update({"finishedAtUtc": datetime.now(timezone.utc).isoformat(), "productionSourceSha256After": end_snapshot,
                         "productionSourcesUnchangedDuringRun": production_unchanged,
                         "benchmarkCodeUnchangedDuringRun": benchmark_unchanged,
                         "completedImageCount": sum(row.get("status") == "PASS" for row in records),
                         "failedOrPartialImageCount": sum(row.get("status") != "PASS" for row in records),
                         "selectedRunScopeCompleted": len(records) >= len(selected),
                         "failures": failures,
                         "benchmarkCodeSha256After": _benchmark_hashes()})
    write_json(ARTIFACTS / "benchmark_run_manifest.json", run_manifest)
    write_json(ARTIFACTS / "benchmark_failures.json", failures)
    return {"runManifest": run_manifest, "recordCount": len(records), "selectedCount": len(selected),
            "failureCount": len(failures), "summary": outputs["summary"], "unchanged": unchanged}


def main() -> int:
    parser = argparse.ArgumentParser(description="Reproducible Smart V2 vs Contour-Preserving benchmark")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Build local dataset manifest and lock the family split")
    init.add_argument("--force", action="store_true")
    sub.add_parser("validate", help="Validate source hashes, provenance, family splits and coverage")
    lock = sub.add_parser("lock-split", help="Re-lock manifest after a reviewed image import")
    lock.add_argument("--confirm-review", action="store_true", help="Confirm source families and split assignments have been reviewed")
    run = sub.add_parser("run", help="Run smoke/category/full benchmark through the production API")
    run.add_argument("--scope", choices=("smoke", "category", "all"), default="all")
    run.add_argument("--category", choices=CATEGORY_NAMES)
    run.add_argument("--image-id", action="append", dest="image_ids")
    run.add_argument("--timeout", type=int, default=900, help="Per-engine API job timeout in seconds")
    run.add_argument("--resume", action="store_true")
    report = sub.add_parser("report", help="Regenerate reports from the current checkpoint")
    args = parser.parse_args()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if args.command == "init":
        result = initialize_dataset(force=args.force)
        print(json.dumps({"manifestItemCount": len(result["manifest"]["items"]), "validationStatus": result["validation"]["status"], "coverage": result["coverage"]}, indent=2, ensure_ascii=False))
        return 0 if result["validation"]["status"] == "PASS" else 2
    if args.command == "validate":
        result = validate_and_write()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["status"] == "PASS" else 2
    if args.command == "lock-split":
        if not args.confirm_review:
            raise SystemExit("Refusing to lock a changed manifest without --confirm-review; check family/split assignments first.")
        result = lock_split()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if args.command == "run":
        result = run_benchmark(scope=args.scope, category=args.category, image_ids=args.image_ids, timeout=args.timeout, resume=args.resume)
        print(json.dumps({key: result[key] for key in ("recordCount", "selectedCount", "failureCount", "unchanged")}, indent=2))
        return 0 if result["failureCount"] == 0 and result["unchanged"] else 2
    manifest = _load_manifest()
    records = list(_checkpoint().values())
    result = write_all_reports(records, manifest, ARTIFACTS)
    print(json.dumps({"recordCount": len(records), "failureCount": len(result["failures"]), "report": str(ARTIFACTS / "task_08a_report.md")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
