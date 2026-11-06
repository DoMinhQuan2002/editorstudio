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
from xml.etree import ElementTree

from .dataset import ARTIFACTS, BACKEND, MANIFEST, REPOSITORY, build_manifest, sha256, validate_manifest, write_json
from .defects import build_defects, build_summaries
from .review import build_review_package
from .typography import create_fixtures, evaluate_active_fox_ocr

OLD_ROOT = BACKEND / "artifacts" / "contour_preserving" / "task_08a"
RESULTS_PATH = ARTIFACTS / "per_image_results.json"
RUN_ID_PATH = ARTIFACTS / "run_identity.json"


def production_paths() -> list[Path]:
    paths = [BACKEND / "mediastudio" / "api.py", BACKEND / "mediastudio" / "desktop_capabilities.py",
             BACKEND / "mediastudio" / "image_tools" / "vectorize.py",
             BACKEND / "mediastudio" / "image_tools" / "contour_backend.py",
             BACKEND / "mediastudio" / "image_tools" / "contour_svg_composer.py"]
    paths.extend(sorted((BACKEND / "mediastudio" / "image_tools" / "vectorization_v2").glob("*.py")))
    paths.extend(sorted((BACKEND / "mediastudio" / "image_tools").glob("contour*.py")))
    paths.extend(sorted((REPOSITORY / "src" / "MediaStudio.Desktop").rglob("*.cs")))
    return sorted(set(p for p in paths if p.is_file()))


def snapshots() -> dict[str, str]:
    return {p.relative_to(REPOSITORY).as_posix(): sha256(p) for p in production_paths()}


def _valid_resume(row: dict[str, Any], source_hash: str, run_id: str) -> bool:
    if row.get("runId") != run_id or row.get("sourceSha256") != source_hash or row.get("status") != "PASS":
        return False
    seen = set()
    for run in row.get("engines", {}).values():
        if run.get("status") != "SUCCEEDED": return False
        svg, render = Path(run.get("svgPath", "")), Path(run.get("edgeRenderPath", ""))
        if not svg.is_file() or not render.is_file(): return False
        seen.add(run.get("actualMethod"))
        if run.get("svgSha256") and sha256(svg) != run["svgSha256"]: return False
        if run.get("edgeRenderSha256") and sha256(render) != run["edgeRenderSha256"]: return False
    return seen == {"smart_reconstruction", "contour_preserving"}


def _old_activefox_rows() -> list[dict[str, Any]]:
    old_path = OLD_ROOT / "per_image_results.json"
    if not old_path.is_file(): return []
    old = json.loads(old_path.read_text(encoding="utf-8"))
    rows = []
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    valid_items = {i["imageId"]: i for i in manifest["items"]}
    for row in old.get("items", []):
        if row.get("sourceType") != "real_raster_user_provided": continue
        item = valid_items.get(row["imageId"])
        if not item or row.get("sourceSha256") != item["sha256"]: continue
        clone = dict(row)
        clone["reusedFromTask08A"] = True
        clone["reuseValidation"] = {"sourceHashMatches": True, "svgAndRenderHashValidation": True,
                                    "oldRunId": row.get("runId"), "limitations": "Task08A outputs reused as evidence; not a fresh 08A.1 engine run."}
        for engine in clone.get("engines", {}).values():
            for key, hash_key in (("svgPath", "svgSha256"), ("edgeRenderPath", "edgeRenderSha256")):
                target = Path(engine.get(key, ""))
                if engine.get("status") == "SUCCEEDED" and (not target.is_file() or (engine.get(hash_key) and sha256(target) != engine[hash_key])):
                    clone["reuseValidation"]["svgAndRenderHashValidation"] = False
        rows.append(clone)
    return rows


def run_new_images(*, timeout: int = 900, resume: bool = True) -> dict[str, Any]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    validation = validate_manifest(manifest)
    if validation["status"] != "PASS": raise RuntimeError(f"Dataset manifest invalid: {validation}")
    production_before = snapshots()
    config = {"engineMethods": ["smart_reconstruction", "contour_preserving"], "engine": "auto", "mode": "auto",
              "textMode": "outlined", "transparentBackground": True, "sameAssetPerEngine": True,
              "renderLongEdgeMax": 1600, "api": "existing Task08A worker/production API", "algorithmChanges": False}
    digest = hashlib.sha256(json.dumps({"manifest": manifest, "config": config, "production": production_before}, sort_keys=True).encode()).hexdigest()
    run_id = "task08a1-" + digest[:16]
    old_run = json.loads(RUN_ID_PATH.read_text(encoding="utf-8")) if RUN_ID_PATH.exists() else {}
    previous_rows = {}
    if resume and old_run.get("runId") == run_id and RESULTS_PATH.is_file():
        previous_rows = {r["imageId"]: r for r in json.loads(RESULTS_PATH.read_text(encoding="utf-8")).get("items", [])}
    run_root = ARTIFACTS / "runs" / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    records = _old_activefox_rows()
    public_items = [i for i in manifest["items"] if i["sourceType"] == "real_public_sample"]
    failures = []
    for index, item in enumerate(public_items, 1):
        old = previous_rows.get(item["imageId"])
        if old and _valid_resume(old, item["sha256"], run_id):
            print(f"[{index}/{len(public_items)}] {item['imageId']}: resume (source/SVG/render hashes checked)", flush=True)
            records.append(old); continue
        item_file = run_root / "items" / f"{item['imageId']}.json"
        result_file = run_root / "results" / f"{item['imageId']}.json"
        item_file.parent.mkdir(parents=True, exist_ok=True); result_file.parent.mkdir(parents=True, exist_ok=True)
        worker_item = dict(item); worker_item["benchmarkOrderIndex"] = int(hashlib.sha256(item["imageId"].encode()).hexdigest()[:2], 16) % 2
        write_json(item_file, worker_item)
        stdout_path, stderr_path = run_root / "logs" / f"{item['imageId']}.stdout.log", run_root / "logs" / f"{item['imageId']}.stderr.log"
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, "-m", "tools.vectorization_benchmark.worker", "--item-json", str(item_file),
                   "--artifact-root", str(ARTIFACTS), "--result-json", str(result_file), "--run-id", run_id,
                   "--timeout", str(timeout)]
        env = os.environ.copy(); env["PYTHONUTF8"] = "1"
        print(f"[{index}/{len(public_items)}] {item['imageId']}: running paired Smart V2 and Contour API jobs", flush=True)
        start = time.perf_counter()
        with stdout_path.open("w", encoding="utf-8") as so, stderr_path.open("w", encoding="utf-8") as se:
            proc = subprocess.run(command, cwd=BACKEND, env=env, stdout=so, stderr=se, timeout=timeout * 2 + 150)
        elapsed = time.perf_counter() - start
        if result_file.is_file():
            row = json.loads(result_file.read_text(encoding="utf-8")); row["workerReturnCode"] = proc.returncode
            row["workerWallSeconds"] = round(elapsed, 3); row["stdoutLog"] = str(stdout_path); row["stderrLog"] = str(stderr_path)
        else:
            row = {"schemaVersion": 1, "runId": run_id, "imageId": item["imageId"], "sourceSha256": item["sha256"],
                   "sourcePath": str(REPOSITORY / item["path"]), "sourceFamilyId": item["sourceFamilyId"],
                   "sourceType": item["sourceType"], "categories": item["categories"], "status": "FAILED",
                   "failureType": "WORKER_RESULT_MISSING", "failureReason": f"worker exit {proc.returncode}; inspect log", "workerWallSeconds": round(elapsed, 3)}
        records.append(row)
        if row.get("status") != "PASS": failures.append({"imageId": item["imageId"], "status": row.get("status"), "reason": row.get("failureReason")})
        write_json(RESULTS_PATH, {"schemaVersion": 1, "runId": run_id, "items": records})
        print(f"    {row.get('status')} in {elapsed:.1f}s", flush=True)
    after = snapshots()
    run_manifest = {"schemaVersion": 1, "runId": run_id, "createdAtUtc": old_run.get("createdAtUtc") if old_run.get("runId") == run_id else datetime.now(timezone.utc).isoformat(),
        "finishedAtUtc": datetime.now(timezone.utc).isoformat(), "datasetManifestSha256": validation["manifestSha256"],
        "config": config, "productionSourceSha256Before": production_before, "productionSourceSha256After": after,
        "productionSourcesUnchanged": production_before == after, "sourceFamilySplitPolicy": "family grouped; all acquired images analysis split",
        "completedRecordCount": len(records), "publicSampleRunCount": len(public_items), "failures": failures,
        "task08aActiveFoxRowsReused": len([r for r in records if r.get("reusedFromTask08A")]), "resumeIdentityChecked": True}
    write_json(RUN_ID_PATH, run_manifest); write_json(ARTIFACTS / "benchmark_run_manifest.json", run_manifest)
    write_json(RESULTS_PATH, {"schemaVersion": 1, "runId": run_id, "items": records})
    return run_manifest


def _write_report(test_results: dict[str, Any], geometry: dict[str, Any] | None) -> dict[str, Any]:
    validation = validate_manifest(json.loads(MANIFEST.read_text(encoding="utf-8")))
    review = build_review_package()
    typography = create_fixtures()
    ocr = evaluate_active_fox_ocr()
    defect_summary = build_defects()
    image_summary = build_summaries()
    run = json.loads(RUN_ID_PATH.read_text(encoding="utf-8"))
    all_pass = test_results.get("fullBackend", {}).get("status") == "PASS" and test_results.get("task08aBenchmark", {}).get("status") == "PASS" and test_results.get("task08a1", {}).get("status") == "PASS"
    geo = geometry or {"reproduced": False, "status": "NOT_RUN"}
    svg_validation = validate_svg_outputs()
    engine_failure_data = json.loads((ARTIFACTS / "engine_failures.json").read_text(encoding="utf-8")) if (ARTIFACTS / "engine_failures.json").is_file() else {"items": []}
    engine_stage_rows = []
    for issue in engine_failure_data.get("items", []):
        if issue.get("failureClass") == "CONTOUR_GEOMETRY_INVALID" and geo.get("reproduced"):
            continue
        engine_stage_rows.append({"engine": issue.get("engine"), "imageIds": issue.get("imageIds", []),
            "failureClass": issue.get("failureClass"), "firstFailingStage": issue.get("firstFailingStage", "UNKNOWN"),
            "confidence": issue.get("confidence", "UNKNOWN"), "evidence": issue.get("evidence", [])})
    stage_status = "VERIFIED" if geo.get("reproduced") and geo.get("firstFailingStageVerified") and not engine_stage_rows else "partial"
    dataset_complete = validation["DATASET_COVERAGE_SUFFICIENT"]
    result_rows = json.loads(RESULTS_PATH.read_text(encoding="utf-8")).get("items", [])
    evaluated_public_ids = {row.get("imageId") for row in result_rows if row.get("sourceType") == "real_public_sample"}
    expected_public_ids = {item["imageId"] for item in json.loads(MANIFEST.read_text(encoding="utf-8")).get("items", [])
                           if item.get("sourceType") == "real_public_sample"}
    eval_complete = (review["imageCount"] > 0 and typography["validationPass"] and geo.get("reproduced", False)
                     and expected_public_ids <= evaluated_public_ids)
    task08b_ready = bool(geo.get("reproduced") and geo.get("firstFailingStageVerified") and all_pass)
    statuses = {
        "REAL_DATASET_IMPORT_IMPLEMENTED": True,
        "SOURCE_FAMILY_DEDUPLICATION_VALID": validation["status"] == "PASS" and not validation["exactDuplicatePairs"],
        "DATASET_PROVENANCE_VALID": validation["status"] == "PASS",
        "INDEPENDENT_REAL_IMAGE_COUNT": validation["independentRealImageCount"],
        "DATASET_COVERAGE_SUFFICIENT": dataset_complete,
        "HUMAN_REVIEW_PACKAGE_READY": review["imageCount"] > 0,
        "HUMAN_VISUAL_REVIEW_COMPLETE": False,
        "TYPOGRAPHY_EVALUATION_IMPLEMENTED": typography["fixtures"] >= 7,
        "TYPOGRAPHY_METRICS_VALID": "partial" if typography["validationPass"] and ocr.get("status") in {"OCR_READY", "OCR_FALLBACK"} else False,
        "VISUAL_DEFECT_LOCALIZATION_VALID": defect_summary["visualCandidateCount"] > 0,
        "VISUAL_DEFECT_RANKING_COMPLETE": "partial",
        "ENGINE_FAILURES_DEDUPLICATED": True,
        "GEOMETRY_FAILURE_REPRODUCED": bool(geo.get("reproduced")),
        "FIRST_FAILING_STAGES_IDENTIFIED": stage_status,
        "REAL_WORLD_GENERALIZATION_PROVEN": False,
        "BENCHMARK_INFRASTRUCTURE_PASS": bool(test_results.get("task08a1", {}).get("status") == "PASS"),
        "SMART_V2_UNCHANGED": run.get("productionSourcesUnchanged", False),
        "CONTOUR_DEFAULT_UNCHANGED": run.get("productionSourcesUnchanged", False),
        "FULL_REGRESSION_PASS": all_pass,
        "SVG_NO_EMBEDDED_RASTER_VALID": svg_validation["status"] == "PASS",
        "TASK_08A_1_INFRASTRUCTURE_COMPLETE": bool(test_results.get("task08a1", {}).get("status") == "PASS" and review["imageCount"] > 0),
        "TASK_08A_1_EVALUATION_COMPLETE": bool(eval_complete),
        "TASK_08B_READY_FOR_TARGETED_REPAIR": task08b_ready,
        "TASK_08B_READY_FOR_BROAD_GENERALIZATION": bool(dataset_complete and review["humanReviewComplete"]),
        "PRODUCTION_RELEASE_READY": False,
    }
    write_json(ARTIFACTS / "first_failing_stage_analysis.json", {"status": stage_status,
        "verifiedContourGeometryReproduction": geo, "additionalEngineFailures": engine_stage_rows,
        "visualFidelityAttribution": "pending intermediate-stage evidence and human ROI review; see visual_defects.json",
        "rule": "VERIFIED only with saved segmentation/topology/Bézier intermediate evidence; final render alone is not stage attribution."})
    write_json(ARTIFACTS / "root_cause_evidence_index.json", {"geometryFailure": geo,
        "visualIssues": "visual_defect_ranking.json and ROI image references", "confidenceRule": "No hypothesis promoted without direct intermediate artifact."})
    write_json(ARTIFACTS / "task_08b_recommendations.json", {"status": "provisional", "maximumDirections": 3,
        "recommendations": ([{"rank": 1, "issue": "Contour thin-feature coverage validation failure", "proposedModule": "Task 04 Bézier fitting/geometry validator", "evidence": geo, "repair": "target minimum-IoU offending interface/region; preserve shared geometry", "risk": "regression requires synthetic-multiregion plus all Task08A regressions"}] if geo.get("reproduced") else []),
        "broadGeneralizationNotSupported": not dataset_complete, "noTask08BImplemented": True})
    # Stage directories are evidence indexes only; no synthetic intermediate stage images are claimed.
    (ARTIFACTS / "phase_diagnostics").mkdir(parents=True, exist_ok=True)
    report = ["# MediaStudio Vectorization — Task 08A.1 report", "", "## Scope", "",
        "Added benchmark-side dataset import/provenance, blind review package, synthetic typography ground truth, defect triage and reproduction tooling. No production vectorization algorithm or WPF code was changed.", "",
        "## Dataset", "",
        f"- Independent real source families: **{validation['independentRealImageCount']}**; variants: **{validation['variantCount']}**; synthetic fixtures retained separately: **{validation['syntheticFixtureCount']}**.",
        "- ACTIVE FOX native and upscaled images count as one family. Nine documented scikit-image samples add nine families; samples are heterogeneous and mostly photographs.",
        f"- Coverage sufficient: **{validation['DATASET_COVERAGE_SUFFICIENT']}**. Missing groups at 4 independent families: {', '.join(k for k,v in validation['categoryCoverage'].items() if not v['coverageSufficient'])}.",
        "- New public samples are `review_analysis`, not blind. The old synthetic heldout fixtures were previously exposed; no heldout families are claimed.",
        "- License/provenance and file hashes are recorded per source. ACTIVE FOX stays local-only with unknown external license.", "",
        "## Human review", "",
        f"- Static blind review package generated for {review['imageCount']} result images with {review['roiCount']} ROI records; mapping is stored separately.",
        "- CSV is blank and valid by design. Human review complete: **false**. The static page displays images and metrics but does not save scores.", "",
        "## Typography", "",
        f"- {typography['fixtures']} synthetic font fixtures use the bundled Roboto OFL font and exact rendered glyph masks; controlled identity/defect sanity checks: **{typography['validationPass']}**.",
        f"- OCR status: **{ocr.get('status', 'not available')}**. OCR predictions are separated from ground truth; ACTIVE FOX has known transcription but no verified glyph/font reference.",
        "- Real glyph geometry/layout/color remain partial because source vector/font references are absent.", "",
        "## Visual defects and engine failures", "",
        f"- Pending visual ROI candidates: {defect_summary['visualCandidateCount']}; separate ranked candidate issues: {defect_summary['visualRankedIssueCount']}; engine root failures after dedupe: {defect_summary['engineRootIssueCount']}.",
        "- ROI labels/severity are machine candidates only. Human confirmation and first-stage attribution remain pending unless direct intermediate evidence exists.",
        "- Real and synthetic evidence remain separate; no preferred engine is declared.", "",
        "### Engine/structural failure ranking", "",
        "| Failure symptom | Engine | Affected images/families | Severity | Evidence | First failing stage |",
        "|---|---|---:|---|---|---|"]
    engine_rank_path = ARTIFACTS / "engine_failure_ranking.json"
    engine_rank = json.loads(engine_rank_path.read_text(encoding="utf-8")).get("ranking", []) if engine_rank_path.is_file() else []
    if geo.get("reproduced") and geo.get("firstFailingStageVerified"):
        for issue in engine_rank:
            if issue.get("failureClass") == "CONTOUR_GEOMETRY_INVALID":
                issue["firstFailingStage"] = geo.get("firstFailingStage", "bezier_geometry_validation")
                issue["rootCauseConfidence"] = "VERIFIED"
                issue["verifiedEvidence"] = geo.get("artifactPath", "geometry_failure_reproduction.json")
        write_json(engine_rank_path, {"ranking": engine_rank,
            "note": "Grouped by failure symptom and engine; the known geometry failure stage is verified only against direct reproduction capture.",
            "syntheticAndRealEvidenceSeparate": True})
    if engine_rank:
        for issue in engine_rank:
            evidence = str(issue.get("evidence", [{}])[0].get("reason", ""))[:130].replace("|", "\\|").replace("\n", " ")
            report.append(f"| {issue.get('failureClass')} | {issue.get('engine')} | {len(issue.get('affectedImageIds', []))} / {len(issue.get('affectedSourceFamilies', []))} | {issue.get('severity')} | {evidence} | {issue.get('firstFailingStage')} ({issue.get('rootCauseConfidence')}) |")
    else:
        report.append("| none observed | — | 0 / 0 | — | — | — |")
    report.extend(["", "### Visual-fidelity candidate ranking", "",
        "| Candidate defect | Engine | Affected images/families | Severity | Evidence | First failing stage |",
        "|---|---|---:|---|---|---|"])
    visual_rank_path = ARTIFACTS / "visual_defect_ranking.json"
    visual_rank = json.loads(visual_rank_path.read_text(encoding="utf-8")).get("ranking", []) if visual_rank_path.is_file() else []
    if visual_rank:
        for issue in visual_rank[:12]:
            first = issue.get("examples", [{}])[0]
            evidence = f"ROI {first.get('roiIndex')} {first.get('roi')} risk metrics".replace("|", "\\|")
            report.append(f"| {issue.get('issueKey')} | {issue.get('engine')} | {len(issue.get('affectedImageIds', []))} / {len(issue.get('affectedSourceFamilies', []))} | {issue.get('provisionalSeverity')} (unreviewed) | {evidence} | {issue.get('firstFailingStage')} ({issue.get('rootCauseConfidence')}) |")
    else:
        report.append("| pending | — | 0 / 0 | pending | no ROI artifacts | UNKNOWN |")
    report.extend(["", "## Geometry reproduction", "",
        f"- Result: **{geo.get('status', 'NOT_RUN')}**; reproduced: **{geo.get('reproduced', False)}**; first stage: **{geo.get('firstFailingStage', 'UNKNOWN')}**; confidence: **{geo.get('confidence', 'UNKNOWN')}**.",
        f"- Evidence file: `{geo.get('artifactPath', 'not available')}`. No geometry engine changes were made.", "",
        "## Regression and immutable production sources", "",
        f"- Full backend regression: **{test_results.get('fullBackend', {}).get('status', 'NOT_RUN')}**.",
        f"- Task 08A benchmark tests: **{test_results.get('task08aBenchmark', {}).get('status', 'NOT_RUN')}**.",
        f"- Task 08A.1 tests: **{test_results.get('task08a1', {}).get('status', 'NOT_RUN')}**.",
        f"- SVG output constraint check: **{svg_validation['status']}** ({svg_validation['validatedSvgCount']} SVG files checked; embedded raster elements: {svg_validation['embeddedRasterElementCount']}; embedded raster data URIs: {svg_validation['embeddedRasterDataUriCount']}).",
        f"- Production source hashes unchanged: **{run.get('productionSourcesUnchanged', False)}**.", "",
        "## Final status", "", "```text"])
    report.extend(f"{k} = {str(v).lower() if isinstance(v, bool) else v}" for k, v in statuses.items())
    report.extend(["```", "", "## Artifact map", "", "See files in this directory: `real_dataset_manifest.json`, `review_index.html`, `human_review_template.csv`, `typography/`, `visual_defects.json`, `engine_failures.json`, `first_failing_stage_analysis.json`, and regression JSONs.", ""])
    (ARTIFACTS / "task_08a_1_report.md").write_text("\n".join(report), encoding="utf-8")
    write_json(ARTIFACTS / "final_status.json", {"statuses": statuses, "evidence": {"datasetValidation": validation,
        "review": review, "typography": typography, "ocr": ocr, "defects": defect_summary, "geometry": geo,
        "tests": test_results, "svgConstraints": svg_validation, "productionHashesUnchanged": run.get("productionSourcesUnchanged", False)}})
    return statuses


def validate_svg_outputs() -> dict[str, Any]:
    """Recheck the actual saved SVGs from all completed benchmark records."""
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8")) if RESULTS_PATH.is_file() else {"items": []}
    checked, issues = [], []
    embedded_raster_elements = embedded_data_uris = 0
    for record in results.get("items", []):
        for engine, run in record.get("engines", {}).items():
            if run.get("status") != "SUCCEEDED":
                continue
            raw_path = run.get("svgPath")
            path = Path(raw_path) if raw_path else None
            item = {"imageId": record.get("imageId"), "engine": engine, "path": raw_path,
                    "status": "PASS", "embeddedRasterElementCount": 0, "embeddedRasterDataUriCount": 0}
            try:
                if path is None or not path.is_file():
                    raise FileNotFoundError(raw_path or "SVG path missing")
                if run.get("svgSha256") and sha256(path) != run["svgSha256"]:
                    raise ValueError("saved SVG SHA-256 differs from benchmark record")
                root = ElementTree.parse(path).getroot()
                image_tags = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1].casefold() == "image"]
                data_uris = []
                for node in root.iter():
                    for key, value in node.attrib.items():
                        if key.rsplit("}", 1)[-1].casefold() in {"href", "src"} and str(value).strip().casefold().startswith("data:image/"):
                            data_uris.append(value)
                item["embeddedRasterElementCount"] = len(image_tags)
                item["embeddedRasterDataUriCount"] = len(data_uris)
                item["xmlRoot"] = root.tag
                if image_tags or data_uris:
                    raise ValueError("SVG contains raster image elements or data:image URIs")
                worker_validation = run.get("svgValidation", {})
                if worker_validation.get("status") != "PASS":
                    raise ValueError("benchmark SVG validator did not report PASS")
            except Exception as exc:
                item["status"] = "FAIL"
                item["error"] = f"{type(exc).__name__}: {exc}"
                issues.append(item)
            embedded_raster_elements += item["embeddedRasterElementCount"]
            embedded_data_uris += item["embeddedRasterDataUriCount"]
            checked.append(item)
    outcome = {"status": "PASS" if checked and not issues else "FAIL", "validatedSvgCount": len(checked),
               "embeddedRasterElementCount": embedded_raster_elements, "embeddedRasterDataUriCount": embedded_data_uris,
               "failedSvgCount": len(issues), "items": checked, "issues": issues,
               "method": "XML-parse actual saved SVG; verify saved SHA-256 and worker validation; reject <image> elements and data:image URIs"}
    write_json(ARTIFACTS / "svg_constraint_validation.json", outcome)
    return outcome


def run_tests() -> dict[str, Any]:
    tests = [
        ("task08aBenchmark", [sys.executable, "-m", "pytest", "-q", "tests/test_vectorization_benchmark.py"]),
        ("task08a1", [sys.executable, "-m", "pytest", "-q", "tests/test_task_08a_1.py"]),
        ("fullBackend", [sys.executable, "-m", "pytest", "-q", "tests"]),
    ]
    outcomes = {}
    for name, cmd in tests:
        start = time.perf_counter()
        result = subprocess.run(cmd, cwd=BACKEND, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        outcomes[name] = {"status": "PASS" if result.returncode == 0 else "FAIL", "returnCode": result.returncode,
                          "durationSeconds": round(time.perf_counter() - start, 3), "command": cmd, "output": result.stdout[-20000:]}
        print(f"{name}: {outcomes[name]['status']} ({outcomes[name]['durationSeconds']}s)", flush=True)
    write_json(ARTIFACTS / "benchmark_test_results.json", outcomes["task08aBenchmark"] | {"allSuites": outcomes})
    write_json(ARTIFACTS / "backend_regression.json", outcomes["fullBackend"])
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description="Task 08A.1 real-image and visual fidelity diagnostics")
    parser.add_argument("command", choices=("prepare", "run", "finalize", "all"))
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--no-geometry-repro", action="store_true")
    args = parser.parse_args()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if args.command in {"prepare", "all"}:
        if not MANIFEST.exists(): write_json(MANIFEST, build_manifest())
        # Generate complete inventory/coverage/split reports through the dataset validator CLI.
        subprocess.run([sys.executable, "-m", "tools.task_08a_1.dataset", "validate"], cwd=BACKEND, check=False)
        create_fixtures()
    run_manifest = None
    if args.command in {"run", "all"}:
        run_manifest = run_new_images(timeout=args.timeout)
    if args.command in {"finalize", "all"}:
        geometry = None
        if not args.no_geometry_repro:
            proc = subprocess.run([sys.executable, "-m", "tools.task_08a_1.geometry_repro"], cwd=BACKEND,
                                  text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            print(proc.stdout[-8000:], flush=True)
            p = ARTIFACTS / "geometry_failure_reproduction.json"
            geometry = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"status": "BLOCKED", "reproduced": False, "reason": proc.stdout[-4000:]}
        else:
            p = ARTIFACTS / "geometry_failure_reproduction.json"
            geometry = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"status": "NOT_RUN", "reproduced": False}
        tests = run_tests()
        statuses = _write_report(tests, geometry)
        print(json.dumps(statuses, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
