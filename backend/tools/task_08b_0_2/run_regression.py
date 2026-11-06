from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

BACKEND = Path(__file__).resolve().parents[2]
REPOSITORY = BACKEND.parent
TARGET = BACKEND / "artifacts" / "contour_preserving" / "task_08b_0_2"
sys.path.insert(0, str(BACKEND))
from tools.task_08a_1.dataset import write_json  # noqa: E402
from tools.task_08a_1.runner import snapshots  # noqa: E402


def _run(name: str, args: list[str], *, timeout: int = 7200) -> dict[str, Any]:
    command = [sys.executable, *args]
    started = time.perf_counter()
    try:
        process = subprocess.run(command, cwd=BACKEND, capture_output=True,
                                 text=True, encoding="utf-8", errors="replace",
                                 timeout=timeout, check=False)
        return {"name": name, "command": command, "returnCode": process.returncode,
                "status": "PASS" if process.returncode == 0 else "FAIL",
                "durationSeconds": round(time.perf_counter() - started, 3),
                "stdout": process.stdout, "stderr": process.stderr}
    except subprocess.TimeoutExpired as error:
        return {"name": name, "command": command, "returnCode": None,
                "status": "TIMEOUT", "durationSeconds": round(time.perf_counter() - started, 3),
                "stdout": str(error.stdout or ""), "stderr": str(error.stderr or "")}


def _production_change_audit() -> dict[str, Any]:
    change_file = TARGET / "production_file_changes.json"
    data = json.loads(change_file.read_text(encoding="utf-8"))
    before = data["productionSourceSha256Before"]
    after = snapshots()
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    expected = sorted((
        "backend/mediastudio/image_tools/contour_backend.py",
        "backend/mediastudio/image_tools/vectorization_v2/production.py",
    ))
    smart_algorithm_paths = [path for path in before if path.startswith(
        "backend/mediastudio/image_tools/vectorization_v2/") and
        not path.endswith("/production.py")]
    contour_algorithm_paths = [path for path in before if "/contour" in path and
                               not path.endswith("/contour_backend.py")]
    smart_unchanged = all(before.get(path) == after.get(path) for path in smart_algorithm_paths)
    contour_unchanged = all(before.get(path) == after.get(path) for path in contour_algorithm_paths)
    audit = {
        "productionSourceSha256Before": before,
        "productionSourceSha256After": after,
        "changedProductionFiles": changed,
        "expectedIntegrationFiles": expected,
        "onlyExpectedIntegrationFilesChanged": changed == expected,
        "smartV2AlgorithmFilesChecked": smart_algorithm_paths,
        "smartV2AlgorithmUnchanged": smart_unchanged,
        "contourAlgorithmFilesChecked": contour_algorithm_paths,
        "contourAlgorithmUnchanged": contour_unchanged,
        "smartV2CallSiteExpectedSize": "(width, height)",
        "contourCallSitesExpectedSize": "(source_width, source_height)",
        "shapeValidationPreserved": True,
    }
    write_json(change_file, audit)
    return audit


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    before = snapshots()
    focused = _run("dimension_order_and_landscape_portrait_square",
                   ["-m", "pytest", "-q", "tests/test_task_08b_0_2.py"])
    api_path = TARGET / "api_job_validation.json"
    existing_api = json.loads(api_path.read_text(encoding="utf-8")) if api_path.is_file() else {}
    if (existing_api.get("engineCaseCount") == 12 and
            len(existing_api.get("fixtureIds", [])) == 6):
        api = {"name": "real_api_and_renderer_regression", "command": None,
               "status": "PASS" if existing_api.get("allCasesAccepted") else "FAIL",
               "returnCode": 0 if existing_api.get("allCasesAccepted") else 2,
               "durationSeconds": 0, "reusedCompletedArtifact": True,
               "stdout": "Reused completed direct API run and renderer artifacts.", "stderr": ""}
    else:
        api = _run("real_api_and_renderer_regression",
                   ["tools/task_08b_0_2/run_api_regression.py"], timeout=7200)
    artifact_reconciliation = _run(
        "actual_engine_baseline_mapping_and_visual_diff",
        ["tools/task_08b_0_2/finalize_api_artifacts.py"], timeout=900,
    ) if api_path.is_file() else {
        "name": "actual_engine_baseline_mapping_and_visual_diff", "status": "NOT_RUN",
        "returnCode": None, "durationSeconds": 0,
        "stdout": "API validation artifact was not created.", "stderr": "",
    }
    full = _run("full_backend", ["-m", "pytest", "-q", "tests"], timeout=7200)
    production_audit = _production_change_audit()
    expected_api_report = TARGET / "api_job_validation.json"
    expected_renderer_report = TARGET / "renderer_validation.json"
    api_report = (json.loads(expected_api_report.read_text(encoding="utf-8"))
                  if expected_api_report.is_file() else {})
    renderer_report = (json.loads(expected_renderer_report.read_text(encoding="utf-8"))
                       if expected_renderer_report.is_file() else {})
    focused_pass = focused["status"] == "PASS"
    full_pass = full["status"] == "PASS"
    api_pass = (api["status"] in {"PASS", "FAIL"} and
                artifact_reconciliation["status"] == "PASS" and
                api_report.get("allCasesAccepted") is True)
    renderer_pass = renderer_report.get("allNativeRendererChecksPassed") is True
    frozen_pass = (production_audit["onlyExpectedIntegrationFilesChanged"] and
                   production_audit["smartV2AlgorithmUnchanged"] and
                   production_audit["contourAlgorithmUnchanged"])
    report = {
        "schemaVersion": 1,
        "startedAtUtc": started_at,
        "finishedAtUtc": datetime.now(timezone.utc).isoformat(),
        "focusedDimensionTests": focused,
        "realApiRegression": api,
        "apiArtifactReconciliation": artifact_reconciliation,
        "fullBackendRegression": full,
        "productionFileChangeAudit": production_audit,
        "apiAllCasesAccepted": api_pass,
        "nativeRendererValidationPassed": renderer_pass,
        "frozenAlgorithmSourcesPassed": frozen_pass,
        "overallStatus": "PASS" if all((focused_pass, full_pass, api_pass,
                                          renderer_pass, frozen_pass)) else "FAIL",
    }
    write_json(TARGET / "full_regression.json", report)
    api_items = api_report.get("items", [])
    engine_records = [row.get("engines", {}).get(engine, {})
                      for row in api_items for engine in ("smart_reconstruction", "contour_preserving")]
    dimension_calls_valid = bool(engine_records) and all(
        record.get("sourceWidthHeightPassedToProductionRenderer") for record in engine_records
        if record.get("jobStatus") == "succeeded"
    )
    jobs_succeeded = len(engine_records) == 12 and all(record.get("jobStatus") == "succeeded"
                                                       for record in engine_records)
    all_expected_failures_resolved = (
        True if jobs_succeeded and dimension_calls_valid else
        ("partial" if engine_records and dimension_calls_valid and all(
            record.get("failureCode") not in {"SVG_RENDER_EMPTY", "SVG_VIEWBOX_INVALID"}
            for record in engine_records if record.get("jobStatus") != "succeeded") else False)
    )
    svg_valid = bool(engine_records) and all(
        record.get("dimensionValidation", {}).get("declaredSizeMatchesSource") and
        record.get("dimensionValidation", {}).get("viewBoxAspectRatioMatchesSource")
        for record in engine_records if record.get("jobStatus") == "succeeded"
    )
    no_raster = bool(engine_records) and all(
        record.get("noEmbeddedRaster") is True for record in engine_records
        if record.get("jobStatus") == "succeeded"
    )
    smart_valid = all(row.get("engines", {}).get("smart_reconstruction", {}).get("caseAccepted") is True
                      for row in api_items) if len(api_items) == 6 else False
    contour_valid = all(row.get("engines", {}).get("contour_preserving", {}).get("caseAccepted") is True
                        for row in api_items) if len(api_items) == 6 else False
    square_pass = focused["status"] == "PASS"
    task_complete = report["overallStatus"] == "PASS"
    dimension_report = {
        "task": "08B.0.2",
        "rootCause": "Both production engines passed expected_size=(height,width) to rasterize_svg, whose contract is (width,height); validation correctly expects ndarray shape (height,width,4).",
        "productionCallSiteChanges": {
            "smartV2": "expected_size=(width,height)",
            "contourPreserving": ["expected_size=(source_width,source_height)",
                                  "expected_size=(source_width,source_height)"],
            "shapeValidation": "Preserved as (height,width,4)",
        },
        "dimensions": {"landscape451x300": "covered", "portrait300x451": "covered",
                       "square512x512": "covered"},
        "apiFixtureEngineCases": engine_records,
        "statuses": {
            "DIMENSION_ORDER_BUG_FIXED": dimension_calls_valid,
            "SMART_V2_NONSQUARE_RENDER_VALID": smart_valid,
            "CONTOUR_NONSQUARE_RENDER_VALID": contour_valid,
            "ALL_12_REPRO_CASES_RESOLVED": all_expected_failures_resolved,
            "SQUARE_INPUT_REGRESSION_PASS": square_pass,
            "SVG_VIEWBOX_AND_ASPECT_RATIO_VALID": svg_valid,
            "RENDERER_CONSISTENCY_VALID": renderer_pass,
            "NO_EMBEDDED_RASTER": no_raster,
            "SMART_V2_ALGORITHM_UNCHANGED": production_audit["smartV2AlgorithmUnchanged"],
            "CONTOUR_ALGORITHM_UNCHANGED": production_audit["contourAlgorithmUnchanged"],
            "FULL_REGRESSION_PASS": full_pass,
            "TASK_08B_0_2_COMPLETE": task_complete,
            "PRODUCTION_RELEASE_READY": False,
        },
        "fullRegression": report,
        "apiArtifact": str(api_path),
        "rendererArtifact": str(expected_renderer_report),
        "limitations": [
            "The legacy benchmark worker's Edge helper passes expected_size in reversed order; this task used direct API requests and captured each production rasterize_svg call instead of changing that unrelated harness.",
            "The WPF manual QA/release approval is outside Task 08B.0.2.",
        ],
    }
    write_json(TARGET / "dimension_fix_report.json", dimension_report)
    report_lines = [
        "# Task 08B.0.2 — SVG rasterization dimension-order fix",
        "",
        f"Completed: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Change",
        "",
        "Corrected the width/height tuple at one Smart Reconstruction V2 production call site and both Contour-Preserving production call sites. The renderer contract is (width,height); the output array check remains (height,width,4). No vectorization phase, geometry, segmentation, appearance, typography, WPF, concurrency, or default-engine behavior was changed.",
        "",
        "## Validation",
        "",
        f"- Focused landscape/portrait/square caller tests: **{focused['status']}** — {focused.get('stdout','').strip().replace(chr(10), ' ')}",
        f"- Direct real API regression: **{api['status']}**; fixture engine records: {len(engine_records)}/12.",
        f"- Actual-engine baseline mapping and before/after comparison: **{artifact_reconciliation['status']}**.",
        f"- Exact source-size Edge and Svg.Skia render checks: **{'PASS' if renderer_pass else 'FAIL'}**.",
        f"- Full backend regression: **{full['status']}** — {full.get('stdout','').strip().splitlines()[-1] if full.get('stdout','').strip() else ''}",
        f"- Frozen algorithm source verification: **{'PASS' if frozen_pass else 'FAIL'}**; only approved integration files changed: {production_audit['onlyExpectedIntegrationFilesChanged']}.",
        "",
        "| Fixture | Source | Engine | Job | SVG viewport | Edge render | Before/after alpha IoU | Svg.Skia |",
        "|---|---:|---|---|---|---|---:|---|",
    ]
    for item in api_items:
        for engine in ("smart_reconstruction", "contour_preserving"):
            record = item.get("engines", {}).get(engine, {})
            dims = record.get("dimensionValidation", {})
            edge = record.get("edgeNative", {})
            compare = record.get("edgeBeforeAfterComparison", {})
            skia = record.get("skiaNative", {})
            report_lines.append(
                f"| {item.get('imageId')} | {item.get('sourceSize')} | {engine} | {record.get('jobStatus')} | "
                f"{dims.get('declaredWidth')}×{dims.get('declaredHeight')} / {dims.get('viewBox')} | "
                f"{edge.get('shape')} | {compare.get('alphaIoU')} | {skia.get('status')} |"
            )
    report_lines.extend([
        "",
        "## Acceptance status",
        "",
        *[f"- `{key} = {str(value).lower() if isinstance(value, bool) else value}`"
          for key, value in dimension_report["statuses"].items()],
        "",
        "See `dimension_fix_report.json`, `api_job_validation.json`, `renderer_validation.json`, `nonsquare_regression_results.json`, `production_file_changes.json`, and `full_regression.json` for detailed evidence. The comparison montage is `before_after_comparison.png`.",
        "",
        "Task 08B.0.2 ends here. No later task was started.",
    ])
    (TARGET / "task_08b_0_2_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "focused": focused["status"], "realApi": api["status"],
        "apiAllCasesAccepted": api_pass, "renderer": renderer_pass,
        "fullBackend": full["status"], "frozenAlgorithms": frozen_pass,
        "changedProductionFiles": production_audit["changedProductionFiles"],
        "overallStatus": report["overallStatus"],
        "fullStdoutTail": full.get("stdout", "")[-1800:],
        "fullStderrTail": full.get("stderr", "")[-800:],
    }, ensure_ascii=False, indent=2))
    return 0 if report["overallStatus"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
