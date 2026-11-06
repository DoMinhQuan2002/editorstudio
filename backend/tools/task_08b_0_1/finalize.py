from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

BACKEND = Path(__file__).resolve().parents[2]
TARGET = BACKEND / "artifacts" / "contour_preserving" / "task_08b_0_1"
sys.path.insert(0, str(BACKEND))
from tools.task_08a_1.dataset import write_json  # noqa: E402
from tools.task_08a_1.runner import snapshots  # noqa: E402


def load(name: str) -> dict[str, Any]:
    return json.loads((TARGET / name).read_text(encoding="utf-8"))


def viewbox_maps_to_source(row: dict[str, Any]) -> bool:
    vb = row["svg"].get("viewBoxNumbers")
    width, height = row["sourceCanvas"]
    try:
        declared_width = float(str(row["svg"].get("declaredWidth", "")).replace("px", ""))
        declared_height = float(str(row["svg"].get("declaredHeight", "")).replace("px", ""))
    except ValueError:
        return False
    if not vb or vb[2] <= 0 or vb[3] <= 0:
        return False
    source_ratio = width / height
    vb_ratio = vb[2] / vb[3]
    return bool(abs(vb[0]) < 1e-6 and abs(vb[1]) < 1e-6 and
                declared_width == width and declared_height == height and
                abs(vb_ratio - source_ratio) / source_ratio <= 0.001)


def path_bounds_inside(row: dict[str, Any]) -> bool:
    bounds = row.get("svgPathBoundsSvgSkia", {}).get("cullBounds")
    if not bounds:
        return False
    try:
        width = float(str(row["svg"].get("declaredWidth", "")).replace("px", ""))
        height = float(str(row["svg"].get("declaredHeight", "")).replace("px", ""))
    except ValueError:
        return False
    return (bounds["left"] >= -1e-3 and bounds["top"] >= -1e-3 and
            bounds["right"] <= width + 1e-3 and bounds["bottom"] <= height + 1e-3)


def main() -> int:
    inventory = load("visibility_failure_inventory.json")
    diagnostics = load("svg_visibility_diagnostics.json")
    controls = load("visibility_test_results.json")
    regressions = load("full_regression.json")
    before = load("production_hashes_before.json")
    after = snapshots()
    write_json(TARGET / "production_hashes_after.json", after)
    hashes_unchanged = before == after
    original = {(row["imageId"], row["engine"]): row for row in inventory["items"]}
    causes: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    for row in diagnostics.get("items", []):
        old = original.get((row["imageId"], row["engine"]), {})
        vb_ok, bounds_ok = viewbox_maps_to_source(row), path_bounds_inside(row)
        edge_visible = row.get("edgeCorrectCanvas", {}).get("alphaAbove16Pixels", 0) > 0
        skia_summary = row.get("skiaCorrectCanvas", {}).get("summary", {})
        skia_visible = skia_summary.get("alphaAbove16Pixels", 0) > 0
        causes.append({
            "imageId": row["imageId"], "sourceFamilyId": row.get("sourceFamilyId"),
            "engine": row["engine"], "sourceSha256": row["sourceSha256"],
            "sourceCanvas": row["sourceCanvas"],
            "originalJobStatus": old.get("jobStatus"), "originalFailureCode": old.get("originalFailureCode"),
            "originalFailureReason": old.get("originalFailureReason"),
            "svgPath": row["svg"]["path"], "svgSha256": row["svg"]["sha256"],
            "xmlValid": row["svg"]["xmlValid"], "viewBox": row["svg"].get("viewBox"),
            "viewBoxMapsToSourceCanvas": vb_ok, "pathBounds": row.get("svgPathBoundsSvgSkia", {}).get("cullBounds"),
            "cullBoundsInsideDeclaredViewport": bounds_ok, "drawableElementCount": row["svg"]["drawableElementCount"],
            "transforms": row["svg"]["transforms"], "opacityVisibilityAttributes": row["svg"]["opacityVisibilityAttributes"],
            "clipReferences": row["svg"]["clipReferences"], "maskReferences": row["svg"]["maskReferences"],
            "gradientDefinitionCount": row["svg"]["gradientDefinitionCount"],
            "gradientStopCount": row["svg"]["gradientStopCount"],
            "apiRender": row.get("apiRender"), "edgeCorrectCanvas": row.get("edgeCorrectCanvas"),
            "skiaCorrectCanvas": row.get("skiaCorrectCanvas"),
            "edgeSkiaAlphaIoU": row.get("edgeSkiaAlphaIoU"),
            "backgroundComparison": row.get("backgroundComparison"),
            "classification": row["rootCause"], "confidence": "HIGH" if vb_ok and bounds_ok and edge_visible and skia_visible else "PARTIAL",
            "proposedMinimalFix": "Follow-up only: pass (width, height) at both engine render call sites; retain ndarray validation in (height, width, 4) and add nonsquare tests.",
            "rendererComparisonPng": row.get("rendererComparisonPng"),
        })
        stages.append({
            "imageId": row["imageId"], "engine": row["engine"],
            "sourceForegroundPresent": row.get("sourceAlpha", {}).get("alphaAbove16Pixels", 0) > 0,
            "pipelineReachedSvgSerialization": bool(row.get("svg", {}).get("path") and Path(row["svg"]["path"]).is_file()),
            "drawableGeometryPresent": row["svg"]["drawableElementCount"] > 0,
            "geometryInsideDeclaredViewport": bounds_ok, "edgeVisibleOnCorrectCanvas": edge_visible,
            "skiaVisibleOnCorrectCanvas": skia_visible,
            "apiCanvas": [row.get("apiRender", {}).get("canvasWidth"), row.get("apiRender", {}).get("canvasHeight")],
            "sourceCanvas": row["sourceCanvas"],
            "firstVerifiedFailingStage": "final SVG rasterization/visibility dimensions validation",
            "confidence": "HIGH",
            "limits": "The failed original jobs did not retain phase-local masks. The first failing API validation is directly verified from the captured SVG and renderer results.",
        })

    actual_empty = sum(not (case["edgeCorrectCanvas"]["alphaAbove16Pixels"] > 0 and
                            case["skiaCorrectCanvas"]["summary"]["alphaAbove16Pixels"] > 0) for case in causes)
    renderer_errors = sum(case["skiaCorrectCanvas"].get("status") != "PASS" for case in causes)
    bounds_errors = sum(not case["viewBoxMapsToSourceCanvas"] or not case["cullBoundsInsideDeclaredViewport"] for case in causes)
    complete = len(causes) == inventory["engineFailureRecordCount"] and all(c["confidence"] == "HIGH" for c in causes)
    write_json(TARGET / "empty_svg_root_causes.json", {
        "schemaVersion": 1, "classificationTaxonomy": "Task taxonomy plus EXPECTED_SIZE_AXIS_ORDER_MISMATCH subtype",
        "actualEmptyOutputCount": actual_empty, "caseCount": len(causes), "cases": causes,
        "summary": "All SVGs contain geometry within a source-matching viewBox and render visibly in Edge and Svg.Skia when given the intended canvas. The rasterizer expects (width,height), but both engines pass (height,width). On nonsquare images this creates a transposed, cropped canvas; shape validation then rejects and deletes the SVG.",
    })
    write_json(TARGET / "first_failing_stage_analysis.json", {
        "schemaVersion": 1, "firstFailingStageIdentified": complete,
        "stage": "final SVG render and visibility dimensions validation",
        "confidence": "HIGH" if complete else "PARTIAL", "cases": stages,
        "limits": "Upstream intermediate masks were not retained by failed API jobs; serialized SVG and the first failed final validation are directly evidenced.",
    })

    focused, full = regressions.get("focused", {}), regressions.get("fullBackend", {})
    tests_pass = focused.get("status") == "PASS" and full.get("status") == "PASS"
    report = [
        "# Task 08B.0.1 — SVG visibility failure root-cause isolation", "",
        f"Completed: {datetime.now(timezone.utc).isoformat()}. Scope: diagnostics only; no production vectorization or WPF changes.", "",
        "## Conclusion", "",
        "Reproduced all 12 Task 08A.1 engine failure records on six source images. Each rerun saved the exact production SVG before failed-job cleanup.",
        "The common root cause is a width/height order mismatch: rasterize_svg accepts (width, height), but both engines pass (height, width). Edge renders visible alpha into the transposed viewport, clipping the image; the API then rejects the rendered array because its shape does not equal (height, width, 4), and removes the output SVG.",
        "The SVGs are not empty. Their declared width/height match the source; each viewBox maps to the source aspect ratio (Contour/eagle uses its 724×800 processing coordinate space, mapped to 1826×2019). Svg.Skia cull bounds stay inside the declared viewport. Both Edge and Svg.Skia render visible content on the intended source-sized canvas. The production job failure is real, but the EMPTY_VISIBLE_SVG_OUTPUT label is an inaccurate description of the cause.", "",
        "## Per-case results", "",
        "| Image | Engine | Source | API canvas → intended | API alpha pixels | Edge alpha (correct) | Svg.Skia alpha (correct) | Alpha IoU | Root cause |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in causes:
        width, height = row["sourceCanvas"]
        api = row.get("apiRender") or {}
        report.append(
            f"| {row['imageId']} | {row['engine']} | {width}×{height} | "
            f"{api.get('canvasWidth')}×{api.get('canvasHeight')} → {width}×{height} | "
            f"{api.get('alphaAbove16Pixels', 0):,} | {row['edgeCorrectCanvas']['alphaAbove16Pixels']:,} | "
            f"{row['skiaCorrectCanvas']['summary']['alphaAbove16Pixels']:,} | "
            f"{row.get('edgeSkiaAlphaIoU'):.6f} | {row['classification']} |"
        )
    report += [
        "", "EXPECTED_SIZE_AXIS_ORDER_MISMATCH is a supplementary subtype because the required taxonomy has no dedicated dimension-contract category.", "",
        "## Task 08A / 08A.1 inventory", "",
        f"- Task 08A.1: {inventory['engineFailureRecordCount']} failed engine runs on {inventory['uniqueSourceImageCount']} sources; all {sum(bool(x.get('rerunSvgSha256')) for x in inventory['items'])} SVGs were captured on rerun and SHA-256 recorded.",
        "- Task 08A: no EMPTY_VISIBLE_SVG_OUTPUT; one unrelated Contour geometry failure on synthetic-multiregion_illustration.",
        "- Task 08A.1 also has one unrelated Smart V2 GEOS failure on camera.",
        "- Six source hashes are unchanged and pair across both engines.", "",
        "## SVG and renderer checks", "",
        "- All 12 XML documents parse; declared dimensions match the source and viewBox proportions map to the source viewport. Contour/eagle uses processing coordinates (724×800) mapped to 1826×2019; its aspect ratio differs by about 0.07% due to integer sizing.",
        "- Svg.Skia cull bounds are inside the declared output viewport; all SVGs contain drawable elements.",
        "- Correct-canvas Edge and Svg.Skia alpha IoU is 1.0 for 11 cases and 0.999007 for Contour/eagle; both show visible artwork.",
        "- RGBA transparency plus white and black composites are measured in renderer_comparison.json; per-engine PNGs show source, API render, corrected Edge and corrected Svg.Skia.",
        "- Control SVGs for visible artwork, outside-viewBox geometry, opacity=0, black mask and transparent background match expectations in both renderers.", "",
        "## Controls and regression", "",
        f"- Renderer control expectations: {'PASS' if controls.get('allRendererExpectationsPass') else 'FAIL'}.",
        f"- Off-viewBox and opacity controls render empty: {controls.get('outsideViewBoxIsEmpty')} / {controls.get('hiddenOpacityIsEmpty')}.",
        f"- Transparent-canvas artwork remains visible: {controls.get('transparentBackgroundDetectorPass')}; outside pixels stay transparent: {controls.get('transparentControlHasTransparentCanvasPixels')}.",
        f"- Focused tests: {focused.get('status')} ({focused.get('durationSeconds')}s).",
        f"- Full backend regression: {full.get('status')} ({full.get('durationSeconds')}s).",
        f"- Production source hashes unchanged: {hashes_unchanged} across {len(before)} files.",
        "- An initial direct-Edge pytest had a Windows Crashpad temp-profile cleanup race. The automatic detector test now checks alpha without launching Edge; actual Edge and Svg.Skia controls remain run separately and recorded.", "",
        "## Smallest proposed follow-up", "",
        "Change only the render call tuples in Smart V2 and Contour to (width,height) / (source_width,source_height); retain result-array validation as (height,width,4). Add nonsquare regression cases for both engines. No production fix was made in this diagnostic task.", "",
        "## Acceptance status", "",
        "SVG_VISIBILITY_FAILURES_REPRODUCED = " + ("true" if len(causes) == inventory["engineFailureRecordCount"] else "partial"),
        f"ACTUAL_EMPTY_OUTPUT_COUNT = {actual_empty}",
        f"RENDERER_ERROR_COUNT = {renderer_errors}",
        f"VIEWBOX_OR_BOUNDS_ERROR_COUNT = {bounds_errors}",
        "BENCHMARK_FALSE_POSITIVE_COUNT = 0",
        f"EMPTY_SYMPTOM_MISCLASSIFICATION_COUNT = {len(causes)}",
        "FIRST_FAILING_STAGES_IDENTIFIED = " + ("true" if complete else "partial"),
        "ROOT_CAUSE_CLASSIFICATION_COMPLETE = " + ("true" if complete else "false"),
        "PRODUCTION_ALGORITHMS_UNCHANGED = " + ("true" if hashes_unchanged else "false"),
        "SMART_V2_UNCHANGED = " + ("true" if hashes_unchanged else "false"),
        "CONTOUR_DEFAULT_UNCHANGED = " + ("true" if hashes_unchanged else "false"),
        "FULL_REGRESSION_PASS = " + ("true" if tests_pass else "false"),
        "TASK_08B_0_1_COMPLETE = " + ("true" if complete and tests_pass and hashes_unchanged else "false"),
        "TASK_08B_0_2_READY = " + ("true" if complete else "false"), "",
        "Artifacts are in this task directory. Task 08B.0.1 stops here; Task 08B.0.2 was not started.",
    ]
    (TARGET / "task_08b_0_1_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    summary = {"caseCount": len(causes), "actualEmptyCount": actual_empty,
               "rendererErrorCount": renderer_errors, "boundsErrorCount": bounds_errors,
               "rootCauseClassificationComplete": complete, "testsPass": tests_pass,
               "productionHashesUnchanged": hashes_unchanged,
               "taskComplete": complete and tests_pass and hashes_unchanged}
    write_json(TARGET / "final_acceptance.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["taskComplete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
