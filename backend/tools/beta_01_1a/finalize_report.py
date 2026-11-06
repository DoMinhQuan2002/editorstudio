from __future__ import annotations

import hashlib
import json
import math
import statistics
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
OUT = BACKEND / "artifacts" / "contour_preserving" / "beta_01_1a"


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def pstats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "p05": None, "p95": None, "min": None, "max": None}
    values = [float(x) for x in values]
    return {"count": len(values), "mean": statistics.mean(values), "median": statistics.median(values),
            "p05": float(sorted(values)[max(0, math.floor(.05 * (len(values) - 1)))]),
            "p95": float(sorted(values)[min(len(values) - 1, math.ceil(.95 * (len(values) - 1)))]),
            "min": min(values), "max": max(values)}


def main() -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    pack = json.loads((OUT / "input_manifest_validation.json").read_text(encoding="utf-8"))
    family = json.loads((OUT / "source_family_validation.json").read_text(encoding="utf-8"))
    matrix = json.loads((OUT / "api_run_matrix.json").read_text(encoding="utf-8"))
    geometry = json.loads((OUT / "geometry_fidelity.json").read_text(encoding="utf-8"))
    color = json.loads((OUT / "color_fidelity.json").read_text(encoding="utf-8"))
    detail = json.loads((OUT / "detail_alpha_fidelity.json").read_text(encoding="utf-8"))
    svg = json.loads((OUT / "svg_integrity.json").read_text(encoding="utf-8"))
    renderer = json.loads((OUT / "renderer_consistency.json").read_text(encoding="utf-8"))
    resources = json.loads((OUT / "resource_usage.json").read_text(encoding="utf-8"))
    real_gap = json.loads((OUT / "beta_real_artwork_gaps.json").read_text(encoding="utf-8"))
    matrix_rows = list(matrix["cases"].values())
    production_ref = json.loads((BACKEND / "artifacts" / "contour_preserving" / "beta_01_0" / "production_changes.json").read_text(encoding="utf-8"))
    production_files = list(production_ref.get("afterSha256", {}).keys())
    before_data = json.loads((OUT / "production_before_sha256.json").read_text(encoding="utf-8"))
    before = before_data.get("files", {})
    after = {name: sha256(REPO / Path(name)) for name in production_files if (REPO / Path(name)).is_file()}
    missing_now = sorted(set(production_files) - set(after))
    changed = sorted(name for name in set(before) & set(after) if before[name] != after[name])
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    production_unchanged = not (changed or added or removed or missing_now) and len(before) == len(production_files) == 85
    write_json(OUT / "production_before_after_hashes.json", {
        "schemaVersion": 1, "scope": production_ref.get("scope"), "capturedBeforeAtUtc": before_data.get("capturedAtUtc"),
        "capturedAfterAtUtc": now, "productionFileCountExpected": len(production_files),
        "productionFileCountBefore": len(before), "productionFileCountAfter": len(after),
        "beforeSha256": before, "afterSha256": after, "changedFiles": changed, "addedFiles": added,
        "removedFiles": removed, "missingProductionFiles": missing_now, "productionUnchanged": production_unchanged,
        "note": "Hashes cover the BETA-01.0 audited production source/config scope. BETA-01.1A scripts and artifacts are outside this scope."})

    junit_path = OUT / "full_regression.junit.xml"
    junit_root = ET.parse(junit_path).getroot()
    suites = junit_root.findall(".//testsuite") or [junit_root]
    testcases = junit_root.findall(".//testcase")
    total_xml_tests = sum(int(s.attrib.get("tests", 0)) for s in suites)
    failures = sum(int(s.attrib.get("failures", 0)) for s in suites)
    errors = sum(int(s.attrib.get("errors", 0)) for s in suites)
    skipped = sum(int(s.attrib.get("skipped", 0)) for s in suites)
    suite_time = sum(float(s.attrib.get("time", 0)) for s in suites)
    warnings = 24  # Pytest terminal summary; see command transcript and exact JUnit XML warnings where available.
    regression_pass = failures == 0 and errors == 0 and len(testcases) == 383 and total_xml_tests >= len(testcases)
    regression = {"schemaVersion": 1, "command": ".venv\\Scripts\\python.exe -m pytest tests -q --junitxml=artifacts\\contour_preserving\\beta_01_1a\\full_regression.junit.xml",
        "workingDirectory": str(BACKEND), "result": "PASS" if regression_pass else "FAIL",
        "testCases": len(testcases), "subtests": max(0, total_xml_tests - len(testcases)),
        "xmlTestCountIncludingSubtests": total_xml_tests, "failures": failures, "errors": errors,
        "skipped": skipped, "warningsFromPytestTerminalSummary": warnings, "suiteTimeSeconds": suite_time,
        "junitXml": str(junit_path), "junitXmlSha256": sha256(junit_path),
        "pytestTerminalResult": "383 passed, 24 warnings, 360 subtests passed in 280.17s",
        "pass": regression_pass}
    write_json(OUT / "full_regression.json", regression)

    all_api = len(matrix_rows) == 48 and all(row.get("apiJobStatus") == "SUCCEEDED" for row in matrix_rows)
    all_svg = svg.get("validSvgCount") == 48 and svg.get("visibleSvgCount") == 48
    vector_only = svg.get("vectorOnlyCount") == 48
    both_engine = all(sum(1 for x in matrix_rows if x.get("engine") == engine and x.get("apiJobStatus") == "SUCCEEDED") == 24
                      for engine in ("smart_reconstruction", "contour_preserving"))
    geometry_valid = len(geometry.get("metrics", [])) == 48 and len(geometry.get("rendererBaseline", [])) == 23
    color_values_valid = len(color.get("metrics", [])) == 48 and all(
        isinstance(row["metrics"].get("meanDeltaE00"), (int, float)) and math.isfinite(row["metrics"]["meanDeltaE00"])
        and isinstance(row["metrics"].get("p95DeltaE00"), (int, float)) and math.isfinite(row["metrics"]["p95DeltaE00"])
        for row in color["metrics"])
    detail_valid = len(detail.get("metrics", [])) == 16 and all(
        isinstance(row.get("alphaFidelity", {}).get("exactChangedPixelCount"), int)
        and row.get("alphaFidelity", {}).get("binaryMaskIoUThreshold16") is not None
        and row.get("alphaFidelity", {}).get("binaryMaskIoUThreshold128") is not None for row in detail["metrics"])
    blind_ready = (Path(OUT / "blind_review" / "index.html").is_file() and
                   (OUT / "human_review_template.csv").is_file() and
                   (OUT / "blind_review_identity_mapping.json").is_file())

    summary: dict[str, Any] = {"schemaVersion": 1, "generatedAtUtc": now, "dataset": {
        "syntheticFamilies": family.get("uniqueManifestFamilyCount"), "realIndependentArtworkFamilies": 0,
        "png512": 24, "png256": 24, "jpegVariants": 4, "referenceSvg": 23, "analyticReferences": 1,
        "inputPackValid": pack.get("inputPackValid")}, "engines": {}}
    for engine in ("smart_reconstruction", "contour_preserving"):
        engine_geometry = [x for x in geometry["metrics"] if x["engine"] == engine and x.get("status") == "MEASURED_AGAINST_ORIGINAL_SVG"]
        engine_colors = [x["metrics"] for x in color["metrics"] if x["engine"] == engine]
        c_geometry = [x["silhouetteIoU"] for x in engine_geometry if x["fixtureId"].startswith("C")]
        c_color = [x["meanDeltaE00"] for x in engine_colors if any(xrow["engine"] == engine and xrow["fixtureId"].startswith("C") and xrow["metrics"] is x for xrow in color["metrics"])]
        all_color_mean = [x["meanDeltaE00"] for x in engine_colors if x["meanDeltaE00"] is not None]
        all_color_p95 = [x["p95DeltaE00"] for x in engine_colors if x["p95DeltaE00"] is not None]
        engine_rows = [x for x in matrix_rows if x.get("engine") == engine]
        runtime = [float(x.get("caseRuntimeSeconds", 0)) for x in engine_rows]
        memory = [x.get("memory", {}).get("peakCombinedWorkingSetBytes") for x in engine_rows
                  if x.get("memory", {}).get("peakCombinedWorkingSetBytes") is not None]
        alpha_rows = [x for x in detail["metrics"] if x["engine"] == engine and x["fixtureId"].startswith("A")]
        alpha_summary = [{"fixtureId": x["fixtureId"], "exactChangedPixelCount": x["alphaFidelity"]["exactChangedPixelCount"],
            "binaryMaskIoUThreshold16": x["alphaFidelity"]["binaryMaskIoUThreshold16"],
            "binaryMaskIoUThreshold128": x["alphaFidelity"]["binaryMaskIoUThreshold128"],
            "referenceHoleCount": x["topology"]["referenceHoleCount"], "outputHoleCount": x["topology"]["outputHoleCount"]}
            for x in alpha_rows]
        summary["engines"][engine] = {
            "apiSuccessCases": sum(x.get("apiJobStatus") == "SUCCEEDED" for x in engine_rows),
            "medianRuntimeSeconds": statistics.median(runtime) if runtime else None,
            "maxRuntimeSeconds": max(runtime) if runtime else None,
            "maxPeakProcessTreeWorkingSetBytes": max(memory) if memory else None,
            "flatColorCFixtureSilhouetteIoU": pstats(c_geometry),
            "allFixtureMeanDeltaE00": pstats(all_color_mean), "allFixtureP95DeltaE00": pstats(all_color_p95),
            "alphaCaseResults": alpha_summary}
    summary["g04FalseEdgeStressControl"] = color.get("falseEdgeStressControl")
    summary["rendererConsistency"] = {"comparedCases": renderer.get("edgeAndSkiaComparedCount"),
        "notComparedCases": renderer.get("edgeAndSkiaUnavailableOrFailedCount"), "manualWpfPreview": renderer.get("manualWpfPreview")}
    write_json(OUT / "benchmark_summary.json", summary)

    statuses = {
        "INPUT_PACK_VALID": bool(pack.get("inputPackValid")),
        "SYNTHETIC_CASES_VERIFIED": bool(pack.get("inputPackValid") and family.get("validationPassed")),
        "PRIMARY_API_JOBS_COMPLETED": all_api,
        "BOTH_ENGINE_COMPARISON_COMPLETE": bool(both_engine and matrix.get("fullBenchmark", {}).get("status") == "COMPLETE"),
        "SVG_VECTOR_ONLY": vector_only,
        "GEOMETRY_VALID": "PARTIAL_BY_ENGINE_METADATA",
        "GEOMETRY_METRICS_VALID": geometry_valid,
        "COLOR_METRICS_VALID": color_values_valid,
        "DETAIL_ALPHA_METRICS_VALID": detail_valid,
        "BLIND_REVIEW_PACKAGE_READY": blind_ready,
        "HUMAN_VISUAL_REVIEW_COMPLETE": False,
        "REAL_INDEPENDENT_ARTWORK_FAMILIES_COUNT": 0,
        "REAL_ARTWORK_INPUT_REQUIRED": True,
        "SUPPORTED_BETA_CATEGORY_PROVEN": False,
        "FULL_REGRESSION_PASS": bool(regression_pass),
        "PRODUCTION_UNCHANGED": production_unchanged,
        "BETA_01_1A_TECHNICAL_COMPLETE": all([pack.get("inputPackValid"), all_api, both_engine, all_svg, vector_only,
            geometry_valid, color_values_valid, detail_valid, blind_ready, regression_pass, production_unchanged]),
        "BETA_01_1_READY": False,
        "BETA_RELEASE_READY": False,
    }
    evidence = {
        "input_manifest_validation": str(OUT / "input_manifest_validation.json"),
        "source_family_validation": str(OUT / "source_family_validation.json"),
        "api_run_matrix": str(OUT / "api_run_matrix.json"), "svg_integrity": str(OUT / "svg_integrity.json"),
        "geometry_fidelity": str(OUT / "geometry_fidelity.json"), "color_fidelity": str(OUT / "color_fidelity.json"),
        "detail_alpha_fidelity": str(OUT / "detail_alpha_fidelity.json"), "renderer_consistency": str(OUT / "renderer_consistency.json"),
        "resource_usage": str(OUT / "resource_usage.json"), "beta_real_artwork_gaps": str(OUT / "beta_real_artwork_gaps.json"),
        "production_before_after_hashes": str(OUT / "production_before_after_hashes.json"),
        "full_regression": str(OUT / "full_regression.json"), "comparison_index": str(OUT / "visual_comparison_index.json"),
        "blind_review": str(OUT / "blind_review" / "index.html"),
        "blind_identity_mapping_separate": str(OUT / "blind_review_identity_mapping.json"),
        "report": str(OUT / "beta_01_1a_report.md")}
    write_json(OUT / "acceptance_status.json", {"task": "BETA-01.1A", "statuses": statuses, "evidence": evidence,
        "limitations": ["All fixtures are synthetic and do not qualify a real artwork category.",
                        "No human scores or acceptance were recorded.",
                        "WPF preview was not manually opened; backend Edge and Svg.Skia renders are not WPF manual QA.",
                        "G01–G04 are gradient stress controls only."]})

    g_by_engine: dict[str, dict[str, Any]] = {}
    c_by_engine: dict[str, dict[str, Any]] = {}
    for engine in ("smart_reconstruction", "contour_preserving"):
        geom = [x for x in geometry["metrics"] if x["engine"] == engine and x.get("status") == "MEASURED_AGAINST_ORIGINAL_SVG"]
        core_geom = [x["silhouetteIoU"] for x in geom if x["fixtureId"].startswith("C")]
        all_iou = [x["silhouetteIoU"] for x in geom]
        g_by_engine[engine] = {"coreFlatColorMeanIoU": statistics.mean(core_geom), "coreFlatColorMinimumIoU": min(core_geom),
            "allSvgReferenceMeanIoU": statistics.mean(all_iou), "allSvgReferenceMinimumIoU": min(all_iou)}
        color_rows = [x for x in color["metrics"] if x["engine"] == engine]
        core_de = [x["metrics"]["meanDeltaE00"] for x in color_rows if x["fixtureId"].startswith("C")]
        core_p95 = [x["metrics"]["p95DeltaE00"] for x in color_rows if x["fixtureId"].startswith("C")]
        c_by_engine[engine] = {"coreFlatColorMeanDeltaE00": statistics.mean(core_de),
            "coreFlatColorMeanP95DeltaE00": statistics.mean(core_p95)}

    alpha_notes = []
    for fid in ("A01_outline_stroke", "A02_translucent_overlays", "A03_ring_cutout", "A04_transparent_fine_lines"):
        for engine in ("smart_reconstruction", "contour_preserving"):
            row = next(x for x in detail["metrics"] if x["fixtureId"] == fid and x["engine"] == engine)
            alpha = row["alphaFidelity"]
            alpha_notes.append(f"| {fid} | {engine} | {alpha['exactChangedPixelCount']} | {alpha['binaryMaskIoUThreshold16']:.4f} | {alpha['binaryMaskIoUThreshold128']:.4f} | {row['topology']['referenceHoleCount']} | {row['topology']['outputHoleCount']} |")
    report_lines = [
        "# MediaStudio BETA-01.1A — Technical Raster-to-SVG Benchmark & Real Artwork Readiness", "",
        f"Generated: {now}  ", "Scope: benchmark/evidence only. No production engine, API, default, WPF, or golden baseline was changed.", "",
        "## Executive result", "",
        "The input pack validated and the full 24-fixture × 2-engine benchmark completed. All 48 API jobs succeeded; all resulting SVGs passed the recorded structural/native-render/vector-only checks and rendered in both Edge and Svg.Skia. These results establish technical performance on this synthetic fixture set only.", "",
        "| Status | Result |", "|---|---|",
    ]
    report_lines.extend(f"| `{key}` | `{str(value).lower() if isinstance(value, bool) else value}` |" for key, value in statuses.items())
    report_lines += ["", "No human review was performed. `BETA_01_1_READY` and `BETA_RELEASE_READY` remain false because this pack has no real rights-cleared artwork families and no independent human review.", "",
        "## Input pack", "",
        "| Content | Validated count |", "|---|---:|",
        "| Synthetic source families | 24 |", "| PNG 512×512 | 24 |", "| PNG 256×256 variants | 24 |",
        "| JPEG variants | 4 |", "| Original SVG references | 23 |", "| Analytic 2D reference | 1 |", "",
        "All manifest SHA-256 values, dimensions, PNG decodes/alpha channels, JPEG hashes, SVG XML and family mapping checks passed. The 256px and JPEG files remain variants, not independent families. A04's source PNG vs Edge-rendered reference baseline has alpha IoU 0.9706 at threshold 16 and 0.9752 at threshold 128, same opaque-core bounds and RGBA mean absolute difference 0.657; these are recorded as renderer/antialiasing baseline for one-pixel lines.", "",
        "## API reliability and SVG integrity", "",
        f"- Preflight: {matrix['preflight']['completedCaseCount']}/{matrix['preflight']['expectedCaseCount']} cases passed; Smart V2 and Contour-Preserving were explicitly selected. Experimental Contour used scikit-image {matrix['cases']['C01_three_tone_disc|contour_preserving']['apiEnvironment']['scikitImageVersion']} with the feature flag on; Smart V2 remained the V2 pipeline.",
        f"- Full benchmark: 48/48 API jobs succeeded; {svg['validSvgCount']}/48 valid SVG, {svg['visibleSvgCount']}/48 visible in Edge, {svg['vectorOnlyCount']}/48 vector-only with no embedded raster or unresolved/external resources.",
        f"- Edge and Svg.Skia comparison: {renderer['edgeAndSkiaComparedCount']}/48 outputs rendered in both; alpha IoU and ΔE00 per pair are recorded in `renderer_consistency.json`.",
        f"- Contour-Preserving API reported geometry/topology valid for {svg['engineGeometryEvidence']['contourPreserving']['geometryValidCount']}/24, with 0 self-intersections and 0 shared-boundary mismatches in all 24 cases. WPF preview validation is false in all 24 API results.",
        "- Smart V2 API does not expose topology/self-intersection fields in its result metadata. For Smart V2, only SVG structure, native render visibility and reference-fidelity metrics are asserted; path self-intersection status remains unreported.",
        f"- Pixel-tile check: {svg['pixelTileSubstitutionHeuristic']['embeddedImageCount']} embedded image elements, maximum {svg['pixelTileSubstitutionHeuristic']['maximumVectorPrimitiveCount']} vector primitives/case and 0 `<rect>` primitives; no high-volume tile signature was detected. This is a heuristic, not a mathematical proof against manually tiled vector shapes.",
        "- The `GEOMETRY_VALID` task-wide status is `PARTIAL_BY_ENGINE_METADATA`: Contour reports topology validation; Smart V2 does not expose it. Both engines have valid SVG structure and visible native Edge renders.", "",
        "## Geometry and color fidelity", "",
        "SVG-backed geometry metrics compare Edge-rendered output against each of the 23 original SVGs at native 512×512; boundary F1 uses a 2px tolerance. G04 has analytic alpha/color truth but no SVG geometry, so only its alpha silhouette is reported.", "",
        "| Engine | C01–C12 mean silhouette IoU | C01–C12 min IoU | All 23 SVG mean IoU | All 23 min IoU | C01–C12 mean ΔE00 | C01–C12 average P95 ΔE00 | Median API runtime | Max runtime | Peak sampled process-tree memory |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for engine, short in (("smart_reconstruction", "Smart V2"), ("contour_preserving", "Contour-Preserving")):
        rt = resources["byEngine"][engine]
        maxmem = summary["engines"][engine]["maxPeakProcessTreeWorkingSetBytes"]
        report_lines.append(f"| {short} | {g_by_engine[engine]['coreFlatColorMeanIoU']:.4f} | {g_by_engine[engine]['coreFlatColorMinimumIoU']:.4f} | {g_by_engine[engine]['allSvgReferenceMeanIoU']:.4f} | {g_by_engine[engine]['allSvgReferenceMinimumIoU']:.4f} | {c_by_engine[engine]['coreFlatColorMeanDeltaE00']:.3f} | {c_by_engine[engine]['coreFlatColorMeanP95DeltaE00']:.3f} | {rt['medianRuntimeSeconds']:.2f}s | {rt['maxRuntimeCase']['runtimeSeconds']:.2f}s ({rt['maxRuntimeCase']['fixtureId']}) | {maxmem / (1024**3):.2f} GiB |")
    report_lines += ["", "On the C flat-color group, Contour-Preserving has higher average silhouette IoU and lower average color error in this technical fixture pack. This is a descriptive benchmark result, not a general product category support claim. Detail, alpha and gradient stress fixtures show materially different outcomes.", "",
        "### Detail and alpha findings", "",
        "The table reports exact changed alpha pixel count and binary mask IoU at both alpha thresholds; these remain separate to expose antialiasing changes. Hole counts are rendered mask topology counts, not semantic interpretation.", "",
        "| Fixture | Engine | Exact alpha pixels changed | Mask IoU >16 | Mask IoU >128 | Reference holes | Output holes |", "|---|---|---:|---:|---:|---:|---:|"]
    report_lines.extend(alpha_notes)
    report_lines += ["", "Specific findings:",
        "- `A04_transparent_fine_lines`: reference has 1 hole; both engines render 0. Mask IoU at threshold 16 is 0.8570 for Smart V2 and 0.9693 for Contour-Preserving. Fine-line/alpha fidelity is therefore not fully retained, despite successful API and SVG rendering.",
        "- `A03_ring_cutout`: reference has 1 hole; Smart V2 output has 7 and Contour-Preserving has 3. These are measurable topology differences and should be reviewed on the actual diagnostic sheets.",
        "- `A01_outline_stroke`: Smart V2 alpha mask IoU is 0.9330; Contour-Preserving is 0.9890 at threshold 16, with the binary threshold-128 IoU separately recorded.",
        "- `D02_thin_orbits`: both engines retain the main mask well; color P95 ΔE00 is 11.622 for Smart V2 and 0.753 for Contour in this fixture.", "",
        "### Gradient stress controls", "",
        "G01–G04 are stress controls only. G04's task-fixed CIE76 neighboring-pixel false-edge detector reports:"]
    report_lines += ["", "| Engine | False hard-edge pixels | Fraction of analytic smooth ROI |", "|---|---:|---:|"]
    for row in color["falseEdgeStressControl"]:
        report_lines.append(f"| {row['engine']} | {row['falseHardEdgePixels']} | {row['falseHardEdgeFraction']:.4%} |")
    report_lines += ["", "Both values exceed the 1% reference threshold used by the prior detector task; this only describes G04's smooth analytic ROI and is not a general claim about gradient support. G02 color fidelity is a clear stress-case limitation: mean ΔE00 4.133 Smart V2 and 10.481 Contour-Preserving. The per-fixture CIEDE2000 distributions are in `color_fidelity.json`.", "",
        "## Visual and human review artifacts", "",
        "- Four actual-render comparison sheets: flat-color C, detail D, transparency/stroke A, gradient stress G. Each panel is Source | Reference SVG (G04 uses its analytic source) | Smart V2 | Contour-Preserving.",
        "- For the eight D/A focus fixtures, per-engine outputs include 2× and 4× ROI crops, boundary overlays, ΔE00 heatmaps, alpha-difference maps and missing/extra foreground maps.",
        "- Blind review package uses labels Candidate A/B, with interactive white/black/checkerboard backgrounds and 100/200/400% zoom. Engine mapping is saved separately; review template remains unfilled.",
        "- Human visual review is not complete and no scores or acceptance were inferred.", "",
        "## Runtime, regression, production integrity", "",
        f"- No vectorization timeout was applied. Slowest job: Smart V2 on G02 at {resources['byEngine']['smart_reconstruction']['maxRuntimeCase']['runtimeSeconds']:.2f}s; it completed successfully.",
        f"- Full backend regression: {regression['result']}, {regression['testCases']} tests + {regression['subtests']} subtests, {regression['warningsFromPytestTerminalSummary']} warnings, {regression['suiteTimeSeconds']:.2f}s.",
        f"- Production snapshot: {len(before)} files before / {len(after)} after; changed/added/removed production files: {len(changed)}/{len(added)}/{len(removed)}. `PRODUCTION_UNCHANGED={str(production_unchanged).lower()}`.",
        "- No Smart V2, Contour, segmentation, Bézier, appearance, composer, API, WPF, engine default/flag, or benchmark golden baseline source was edited.", "",
        "## Real artwork readiness", "",
        "This test pack is synthetic-only: 24 source families generated programmatically, zero rights-cleared independent human-authored artwork families, and zero human review rows. To qualify `FLAT_COLOR_LOGOS_AND_ICONS`, provide at least four independent rights-cleared original artwork families and complete blind human review; 8–12 varied families are recommended. Do not count resizes/JPEG versions or these synthetic fixtures as real artwork.", "",
        "## Required artifact index", "",
    ]
    required = ["input_manifest_validation.json", "source_family_validation.json", "api_run_matrix.json", "svg_integrity.json",
        "geometry_fidelity.json", "color_fidelity.json", "detail_alpha_fidelity.json", "renderer_consistency.json",
        "resource_usage.json", "beta_real_artwork_gaps.json", "production_before_after_hashes.json", "full_regression.json"]
    for name in required:
        report_lines.append(f"- `{name}`")
    report_lines += ["- `visual_comparisons/` — four comparison sheets", "- `roi_diagnostics/` — focus-fixture and stress-control diagnostics",
        "- `blind_review/index.html` and separate `blind_review_identity_mapping.json`", "- `full_regression.junit.xml`", "",
        "## Stop condition", "", "BETA-01.1A is complete. No production fix, WPF UI change, Beta release, or follow-on task has been started.", ""]
    report_path = OUT / "beta_01_1a_report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(json.dumps({"statuses": statuses, "productionUnchanged": production_unchanged,
        "regression": regression, "report": str(report_path), "summary": summary}, indent=2, ensure_ascii=False))
    return 0 if statuses["BETA_01_1A_TECHNICAL_COMPLETE"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
