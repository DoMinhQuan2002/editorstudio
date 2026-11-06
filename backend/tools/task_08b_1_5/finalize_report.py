from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

BACKEND = Path(__file__).resolve().parents[2]
ART = BACKEND / "artifacts/contour_preserving/task_08b_1_5"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main() -> None:
    all_fixtures = read_json(ART / "feasibility_all_fixtures.json")
    primary = read_json(ART / "primary_feasibility_comparison.json")
    heldout = read_json(ART / "heldout_gradient_validation.json")
    details = read_json(ART / "detail_preservation_validation.json")
    renderer = read_json(ART / "renderer_compatibility.json")
    production = read_json(ART / "production_changes.json")
    geometry = read_json(ART / "generalization_results.json")
    base = read_json(ART / "base_model_limitations.json")

    exp = primary["EXPERIMENTAL_CONTINUOUS_APPEARANCE"]
    current = primary["CURRENT_FULL_APPEARANCE"]
    base_only = primary["BASE_PAINT_ONLY"]
    target_mean, target_p95 = 4.3173, 8.9644
    primary["acceptanceTargets"].update({
        "lockedMeanDeltaE00Maximum": target_mean,
        "lockedP95DeltaE00Maximum": target_p95,
        "meanColorFidelityPass": exp["meanDeltaE00"] <= target_mean,
        "p95ColorFidelityPass": exp["p95DeltaE00"] <= target_p95,
    })
    write_json(ART / "primary_feasibility_comparison.json", primary)

    # Retain exact alpha-pixel differences alongside the thresholded alpha IoU, which can round to 1.0.
    for fixture_id, row in all_fixtures["fixtures"].items():
        geometry["fixtures"].setdefault(fixture_id, {})["alphaDifferentPixelsVsBase"] = row["experimentalContinuous"]["alphaDifferentPixelsVsBase"]
        geometry["fixtures"][fixture_id]["alphaIoUWithBase"] = row["experimentalContinuous"]["renderedAlphaIoUWithBase"]
    write_json(ART / "generalization_results.json", geometry)

    xml_root = ET.parse(ART / "full_regression.xml").getroot()
    suite = next(node for node in xml_root.iter() if node.tag.endswith("testsuite"))
    junit_cases = len([node for node in suite if node.tag.endswith("testcase")])
    junit_tests = int(suite.attrib.get("tests", "0"))
    failures = int(suite.attrib.get("failures", "0"))
    errors = int(suite.attrib.get("errors", "0"))
    skipped = int(suite.attrib.get("skipped", "0"))
    regression_pass = failures == 0 and errors == 0 and skipped == 0
    write_json(ART / "full_regression.json", {
        "task": "08B.1.5",
        "status": "PASS" if regression_pass else "FAIL",
        "command": ".venv\\Scripts\\python.exe -m pytest -q tests --junitxml=artifacts\\contour_preserving\\task_08b_1_5\\full_regression.xml",
        "pytestBaseTestsPassed": junit_cases - failures - errors - skipped,
        "pytestSubtestsPassed": max(0, junit_tests - junit_cases),
        "junitTestCasesIncludingSubtests": junit_tests,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "durationSeconds": float(suite.attrib.get("time", "0")),
        "warnings": 24,
        "junitXml": str(ART / "full_regression.xml"),
        "pass": regression_pass,
    })

    source_scope = production["sourceScopeComparison"]
    production_unchanged = (production["productionFilesChanged"] == []
                            and production["productionAppearanceSha256"].upper() == production["approvedBaselineSha256"].upper()
                            and source_scope.get("allUnchanged") is True)
    geometry_unchanged = all(row["experimentalContinuous"]["geometryDIdenticalToCurrent"]
                             for row in all_fixtures["fixtures"].values())
    detail_geometry = details["realDetailsPreserved"] and details["thinFeatureNotRemoved"]
    primary_alpha_unchanged = exp["alphaDifferentPixels"] == 0
    vector_only = primary["acceptanceTargets"]["svgVectorOnly"] is True
    full_color_pass = (exp["meanDeltaE00"] <= target_mean and exp["p95DeltaE00"] <= target_p95)
    heldout_pass = heldout["pass"] is True
    statuses = {
        "BASE_MODEL_LIMITATION_VERIFIED": True,
        "CONTINUOUS_PROTOTYPE_BUILT": (ART / "experimental_continuous.svg").is_file(),
        "PRIMARY_FALSE_EDGE_BELOW_1_PERCENT": exp["falseEdgeFraction"] < 0.01,
        "PRIMARY_COLOR_FIDELITY_PASS": full_color_pass,
        "HELDOUT_VALIDATION_PASS": heldout_pass,
        "REAL_DETAILS_PRESERVED": detail_geometry,
        "GEOMETRY_UNCHANGED": geometry_unchanged,
        "ALPHA_UNCHANGED": primary_alpha_unchanged,
        "SVG_VECTOR_ONLY": vector_only,
        "RENDERER_COMPATIBILITY_PASS": renderer["pass"] is True,
        "FULL_REGRESSION_PASS": regression_pass,
        "PRODUCTION_UNCHANGED": production_unchanged,
        "FEASIBILITY_PROVEN": bool(exp["falseEdgeFraction"] < 0.01 and full_color_pass and heldout_pass and detail_geometry and geometry_unchanged and primary_alpha_unchanged and vector_only and renderer["pass"] and regression_pass and production_unchanged),
        "TASK_08B_1_5_COMPLETE": regression_pass and all((ART / name).is_file() for name in (
            "base_model_limitations.json", "continuous_appearance_prototype.json", "primary_feasibility_comparison.json",
            "heldout_gradient_validation.json", "detail_preservation_validation.json", "renderer_compatibility.json",
            "production_changes.json", "full_regression.xml", "experimental_continuous.svg",
            "base_vs_full_vs_experimental.png", "continuous_gradient_deltae00.png",
            "continuous_gradient_false_edges.png", "heldout_comparison.png")),
        "PRODUCTION_RELEASE_READY": False,
    }
    write_json(ART / "acceptance_status.json", statuses)

    metrics = base["radialAngularResidual"]
    detail_rows = details["fixtures"]
    highlight = detail_rows["thin_highlight"]["detailPreservation"]
    scope_count = len(source_scope.get("files", []))
    report = f"""# MediaStudio — Task 08B.1.5 feasibility report

**Result:** the continuous appearance prototype was built and evaluated as a research-only model. The feasibility target was **not proven**. No production source, dispatcher, API/WPF, Smart V2, segmentation, or geometry implementation was changed.

## Model evaluated

The experiment adds a continuous native SVG gradient correction over the frozen vector region paint. It fits 17 uniformly spaced stops in the existing gradient's parameter space (radial distance or linear projection). Each stop uses the source median color and a bounded least-squares source-over opacity; color and opacity sequences receive a fixed Gaussian smoothing of sigma 0.8 stops. The same frozen path and alpha mask are used. No pixel texture, mesh, semantic fixture labels, or flat-filled residual patches are emitted.

## Primary comparison

All three outputs use the same 512×512 source, ROI, Edge/Chromium renderer, Task 08B.1.3 CIE76 false-edge detector, and CIEDE2000 color metric.

| Metric | Base paint only | Current full appearance | Experimental continuous |
|---|---:|---:|---:|
| False-edge fraction | {base_only['falseEdgeFraction']:.6%} | {current['falseEdgeFraction']:.6%} | {exp['falseEdgeFraction']:.6%} |
| Mean ΔE00 | {base_only['meanDeltaE00']:.4f} | {current['meanDeltaE00']:.4f} | {exp['meanDeltaE00']:.4f} |
| P95 ΔE00 | {base_only['p95DeltaE00']:.4f} | {current['p95DeltaE00']:.4f} | {exp['p95DeltaE00']:.4f} |
| Gradient definitions | {base_only['geometry']['gradientDefinitions']} | {current['geometry']['gradientDefinitions']} | {exp['geometry']['gradientDefinitions']} |
| Internal feature paths | {base_only['geometry']['internalFeaturePaths']} | {current['geometry']['internalFeaturePaths']} | {exp['geometry']['internalFeaturePaths']} |
| SVG size | {base_only['geometry']['svgBytes']:,} bytes | {current['geometry']['svgBytes']:,} bytes | {exp['geometry']['svgBytes']:,} bytes |
| Edge render median | {base_only['renderTimeMedianMs']:.1f} ms | {current['renderTimeMedianMs']:.1f} ms | {exp['renderTimeMedianMs']:.1f} ms |

The experiment removes the primary smooth ROI's false-edge response (1.5741% → 0%). It improves on base-only color error, but misses both locked color limits: mean ΔE00 {exp['meanDeltaE00']:.4f} > {target_mean:.4f} and P95 {exp['p95DeltaE00']:.4f} > {target_p95:.4f}. Current full appearance has better color metrics, at the cost of false edges. Therefore the prototype does not resolve the core color-versus-false-boundary tradeoff.

## Base-model limitation

The source hard-boundary annotation has {base['sourceHardEdgeEvidenceInsideRoi']['annotatedHardBoundaryPixelsInsideSoftRoi']} pixels inside the smooth-gradient ROI; source-versus-itself yields {base['sourceHardEdgeEvidenceInsideRoi']['selfComparisonFalseHardEdgePixels']} false edges. The base radial residual is spatially coherent (horizontal/vertical neighbor correlation {metrics['spatialResidualAutocorrelation']['horizontalNeighborPearson']:.4f}/{metrics['spatialResidualAutocorrelation']['verticalNeighborPearson']:.4f}) and retains angular color variation after removing radial means (Lab RMS {metrics['angularSourceColorAfterRemovingRadialMean']['residualRmsLab']:.4f}). This supports a systematic model limitation rather than independent pixel noise.

## Generalization and detail

- Heldout false-edge fraction is {heldout['falseEdgeFraction']:.6%}, but mean/P95 ΔE00 are {heldout['meanDeltaE00']:.4f}/{heldout['p95DeltaE00']:.4f}; the P95 is worse than current full appearance ({heldout['currentFull']['gradient']['p95DeltaE00']:.4f}), so heldout validation fails.
- The hard-boundary fixture retains exact frozen region paths; inherited fitted-geometry boundary F1 is {geometry['hardBoundaryF1']['experimental']:.6f} at {geometry['hardBoundaryF1']['tolerancePx']:.1f}px. No segmentation/topology inputs were changed.
- Small sharp detail paths remain identical and paint recall stays 1.0000. The thin-highlight paths also remain identical, but its color-recall proxy decreases from {highlight['baselinePaintRecallDeltaE00Le10']:.4f} to {highlight['experimentalPaintRecallDeltaE00Le10']:.4f}; the SVG retains all four detail paths. On this fixture the exact rendered alpha differs at {geometry['fixtures']['thin_highlight']['alphaDifferentPixelsVsBase']} antialiased pixels, although thresholded alpha IoU rounds to 1.0. This is a minor but real detail/alpha caveat.

## SVG and renderer checks

The primary experimental SVG is editable vector output with no embedded raster, identical region path data, and zero changed alpha pixels. Edge/Chromium versus Svg.Skia compatibility passes on {len(renderer['fixtures'])} fixtures; maximum common-alpha mean/P95 ΔE00 are {max(x['commonAlphaMeanDeltaE00'] for x in renderer['fixtures'].values()):.4f}/{max(x['commonAlphaP95DeltaE00'] for x in renderer['fixtures'].values()):.4f}. Renderer thresholds were fixed before evaluation.

## Regression and production safety

Full backend regression: **{junit_cases - failures - errors - skipped} tests passed, {max(0, junit_tests - junit_cases)} subtests passed, {failures} failures, {errors} errors, {skipped} skipped** in {float(suite.attrib.get('time', '0')):.2f}s. Production source scope has {scope_count} files matching the approved Task 08B.1.4 baseline hashes; the appearance source hash is unchanged. The experiment is not connected to the production dispatcher.

## Acceptance status

""" + "\n".join(f"- `{key} = {str(value).lower()}`" for key, value in statuses.items()) + f"""

`ALPHA_UNCHANGED = true` refers to the primary fixture. The heldout/detail alpha observation above is recorded separately. `REAL_DETAILS_PRESERVED = true` means vector detail paths were retained; it does not mean their color-recall metric was non-regressing.

## Artifacts

- [Primary feasibility comparison](primary_feasibility_comparison.json)
- [Base-model residual analysis](base_model_limitations.json)
- [Continuous prototype description](continuous_appearance_prototype.json)
- [Experimental vector SVG](experimental_continuous.svg)
- [Heldout validation](heldout_gradient_validation.json)
- [Detail preservation](detail_preservation_validation.json)
- [Renderer compatibility](renderer_compatibility.json)
- [Production hash verification](production_changes.json)
- [Full regression result](full_regression.json)
- [Source/base/current/experimental comparison](base_vs_full_vs_experimental.png)
- [ΔE00 heatmap](continuous_gradient_deltae00.png)
- [False-edge comparison](continuous_gradient_false_edges.png)
- [Heldout comparison](heldout_comparison.png)

**Conclusion:** native continuous gradient correction is technically renderable and removes the primary false-edge artifacts without changing primary geometry or alpha. This one tested model does not meet the locked primary color thresholds, does not pass heldout color validation, and slightly reduces thin-highlight color recall. `FEASIBILITY_PROVEN = false`. No alternate model or production integration was started.
"""
    (ART / "task_08b_1_5_report.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
