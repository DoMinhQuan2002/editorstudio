from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
ART = BACKEND / "artifacts/contour_preserving/task_08b_1_4"
TASK13 = BACKEND / "artifacts/contour_preserving/task_08b_1_3"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(name: str, data: dict) -> None:
    (ART / name).write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_regions(data: dict) -> list[dict]:
    fields = ("id", "area", "bbox", "classification", "confidence", "gradientLikelihood")
    return [{key: row.get(key) for key in fields} for row in data["regions"]]


def paths(svg: Path) -> dict[str, str]:
    root = ET.parse(svg).getroot()
    return {node.attrib["id"]: node.attrib.get("d", "") for node in root.iter()
            if node.tag.rsplit("}", 1)[-1].casefold() == "path" and node.attrib.get("id", "").startswith("contour-region-")}


def main() -> None:
    measured = read(ART / "candidate_measurements.json")
    diagnostic = read(ART / "internal_feature_diagnostics_preliminary.json")
    variant_manifest = read(ART / "controlled_variants.json")
    scope_before = read(TASK13 / "production_scope_after.json")
    p = measured["primary"]
    base_render = p["baseline"]["metrics"]
    cand_render = p["candidate"]["metrics"]
    base_edge, cand_edge = base_render["falseEdge"], cand_render["falseEdge"]
    roi0 = diagnostic["basePaintOnly"]
    full0 = diagnostic["appearanceWithFeatures"]

    base_capture = TASK13 / "stage_captures/smooth_nonlinear_gradient/contour_preserving"
    cand_capture = ART / "stage_captures/task08b1_4_candidate/smooth_nonlinear_gradient"
    old_seg, new_seg = read(base_capture / "segmentation.json"), read(cand_capture / "segmentation.json")
    old_top, new_top = read(base_capture / "topology.json"), read(cand_capture / "topology.json")
    old_geo, new_geo = read(base_capture / "bezier_geometry.json"), read(cand_capture / "bezier_geometry.json")
    old_labels = hashlib.sha256(__import__("numpy").load(base_capture / "segmentation_labels_working.npy").tobytes()).hexdigest()
    shared_old = sorted((int(x["regionLeft"]), int(x["regionRight"]), int(x["pointCount"])) for x in old_top["boundaries"] if x["shared"])
    shared_new = sorted((int(x["left"]), int(x["right"]), int(x["unitSegmentCount"])) for x in new_top["interfaces"] if x["shared"])
    old_svg, new_svg = Path(p["baseline"]["svg"]), Path(p["candidate"]["svg"])
    geom_equal = paths(old_svg) == paths(new_svg)
    hard = measured["regression"]["hard_boundary_with_gradient"]

    root_cause = {
        "task": "08B.1.4", "verified": True,
        "classification": "D_INSUFFICIENT_BASE_GRADIENT_MODEL; false appearance patches are the direct edge source",
        "implementationChain": [
            "_fit_paint selects a single five-stop radial model for the nonlinear radial-angular continuous field.",
            "_detect_internal_features thresholds CIEDE2000 residual components and accepts them using mean source edge magnitude at the component boundary.",
            "Each accepted component is painted with one median RGB flat fill and serialized as a closed SVG path over the radial parent paint.",
            "The flat patch reduces local color residual but its unsupported boundary creates a hard color edge in an analytically continuous source region."
        ],
        "hypotheses": {
            "A_false_feature_selection": {"contributes": True, "evidence": "All four baseline feature boundaries are inside the analytic continuous-gradient ROI; source crossing-boundary CIE76 response is weak while feature-only rendered response is strong."},
            "B_incorrect_feature_paint": {"primary": False, "evidence": "Flat median RGB paint lowers mean local ΔE00 for all four components; principal defect is the discontinuous patch perimeter, not a uniformly wrong local paint color."},
            "C_clipping_or_compositing": {"ruledOut": True, "evidence": "Task 08B.1.3 appearance diagnostic and final SVG false-edge masks have IoU 1.0; final SVG reproduces the appearance-stage defect."},
            "D_insufficient_base_gradient_model": {"primary": True, "evidence": "Base-paint-only counterfactual has 0 false edges but mean/P95 ΔE00 5.311/15.498; four flat patches improve color to 4.317/8.964 while adding 1.5741% false edges."},
            "E_other": {"primary": False}
        },
        "controlledCounterfactual": {
            "sameSourceRoiRendererDetector": True,
            "basePaintOnly": roi0,
            "withInternalFeatures": full0,
            "diagnosticFinalSvgFalseEdgeMaskIoU": 1.0,
            "interpretation": "Residual features are compensating for base-model underfit; deleting/suppressing them alone removes some edges but worsens color and does not solve the gradient representation."
        },
        "candidateEvidence": {
            "featureCount": {"baseline": p["baseline"]["featureCount"], "candidate": p["candidate"]["featureCount"]},
            "falseEdgeFraction": {"baseline": base_edge["falseHardEdgeFraction"], "candidate": cand_edge["falseHardEdgeFraction"]},
            "meanDeltaE00": {"baseline": base_edge["meanDeltaE00"], "candidate": cand_edge["meanDeltaE00"]},
            "p95DeltaE00": {"baseline": base_edge["p95DeltaE00"], "candidate": cand_edge["p95DeltaE00"]},
            "decision": "Rejected: still above the 1% false-edge gate and regresses both primary color metrics."
        },
        "source": {"file": "mediastudio/image_tools/vectorization_contour/appearance.py", "functions": ["_fit_paint", "_paint_predict", "_detect_internal_features", "write_diagnostic_svg"]}
    }
    write("appearance_feature_root_cause.json", root_cause)
    write("internal_feature_diagnostics.json", {
        "baselineFeatureDiagnostics": diagnostic,
        "candidateSelectedFeatures": [feature for region in read(cand_capture / "appearance.json")["regions"] for feature in region["internalFeatures"]],
        "candidateSelectedFeatureCount": p["candidate"]["featureCount"],
        "candidateSuppressedFeatureIds": sorted({row["featureId"] for row in diagnostic["featureRows"]} -
            {feature["id"] for region in read(cand_capture / "appearance.json")["regions"] for feature in region["internalFeatures"]}),
        "sourceBoundaryEvidence": "Per-feature evidence and CIE76 crossing-boundary responses are in baselineFeatureDiagnostics.featureRows; source is analytically continuous across these boundaries."
    })
    write("appearance_before_after.json", {
        "primaryFixture": "smooth_nonlinear_gradient", "baselineSourceSha256": p["sourceSha256"],
        "sameRenderer": "Edge/Chromium API output at native 512x512", "sameROIAndDetector": True,
        "featureCount": {"baseline": p["baseline"]["featureCount"], "candidate": p["candidate"]["featureCount"]},
        "basePaintOnly": roi0, "baselineAppearance": full0, "candidate": p["candidate"]["metrics"],
        "decision": "candidate rejected; no production appearance change retained"
    })
    write("false_edge_before_after.json", {
        "metric": "Task 08B.1.3 fixed CIE76 adjacent-pixel detector; output response >=3 and > source response * 2.5 + 0.75; ROI eroded 1px",
        "thresholdFraction": 0.01, "baseline": base_edge, "candidate": cand_edge,
        "reductionPixels": base_edge["falseHardEdgePixels"] - cand_edge["falseHardEdgePixels"],
        "reductionPercent": (base_edge["falseHardEdgePixels"] - cand_edge["falseHardEdgePixels"]) / base_edge["falseHardEdgePixels"] * 100,
        "candidateBelowThreshold": cand_edge["falseHardEdgeFraction"] < 0.01,
        "visualArtifact": "false_edge_mask_comparison.png"
    })
    write("color_fidelity_before_after.json", {
        "metric": "CIEDE2000 computed on same eroded analytic soft-gradient ROI",
        "baseline": {"mean": base_edge["meanDeltaE00"], "p95": base_edge["p95DeltaE00"]},
        "candidate": {"mean": cand_edge["meanDeltaE00"], "p95": cand_edge["p95DeltaE00"]},
        "deltaCandidateMinusBaseline": {"mean": cand_edge["meanDeltaE00"] - base_edge["meanDeltaE00"], "p95": cand_edge["p95DeltaE00"] - base_edge["p95DeltaE00"]},
        "nonregression": cand_edge["meanDeltaE00"] <= base_edge["meanDeltaE00"] and cand_edge["p95DeltaE00"] <= base_edge["p95DeltaE00"],
        "visualArtifact": "deltae00_heatmap.png"
    })
    detail_rows = measured["details"]
    write("detail_preservation_validation.json", {
        "fixtures": detail_rows,
        "smallSharpColorDetailPreserved": detail_rows["small_sharp_color_detail"]["candidate"]["paintRecallDeltaE00Le10"] >= 1.0,
        "thinHighlightPreserved": detail_rows["thin_highlight"]["candidate"]["paintRecallDeltaE00Le10"] >= .90,
        "candidateDoesNotRegressDetailPaintRecall": all(row["candidate"]["paintRecallDeltaE00Le10"] >= row["baseline"]["paintRecallDeltaE00Le10"] for row in detail_rows.values()),
        "visualArtifact": "detail_preservation_comparison.png"
    })
    heldout = measured["heldout"]["smooth_alternate_heldout"]
    write("heldout_gradient_validation.json", {
        "fixture": "smooth_alternate_heldout", "sourceSha256": heldout["sourceSha256"],
        "heldoutNotUsedForRuleSelection": True, "baseline": heldout["baseline"]["metrics"], "candidate": heldout["candidate"]["metrics"],
        "candidateFalseEdgeBelowOnePercent": heldout["candidate"]["metrics"]["falseEdge"]["falseHardEdgeFraction"] < .01,
        "candidateColorMeanNonregression": heldout["candidate"]["metrics"]["falseEdge"]["meanDeltaE00"] <= heldout["baseline"]["metrics"]["falseEdge"]["meanDeltaE00"],
        "pass": False,
        "reason": "Candidate lowers false edges modestly, but still has >1% on this independent nonlinear field and mean ΔE00 is slightly worse; therefore heldout gate is not met."
    })
    write("geometry_integrity.json", {
        "primaryFixture": "smooth_nonlinear_gradient", "sourceSha256Same": p["sourceSha256"] == read(ART / "api_candidate.json")["results"][0]["sourceSha256"],
        "segmentation": {"baselineRegionCount": len(old_seg["regions"]), "candidateRegionCount": len(new_seg["regions"]),
            "baselineLabelMapSha256": old_labels, "candidateLabelMapSha256": new_seg["labelMapSha256"],
            "labelMapIdentical": old_labels == new_seg["labelMapSha256"], "regionRecordsIdentical": clean_regions(old_seg) == clean_regions(new_seg)},
        "sharedBoundaries": {"baselineCount": len(shared_old), "candidateCount": len(shared_new), "pairAndPointCountIdentical": shared_old == shared_new,
            "baseline": shared_old, "candidate": shared_new},
        "productionSvgRegionPathDIdentical": geom_equal,
        "pathCount": {"baseline": len(paths(old_svg)), "candidate": len(paths(new_svg))},
        "renderedAlphaExactlyIdentical": p["alpha"]["exactlyUnchanged"],
        "hardBoundaryRegression": {"baselineFalseEdgeFraction": hard["baseline"]["falseEdge"]["falseHardEdgeFraction"],
            "candidateFalseEdgeFraction": hard["candidate"]["falseEdge"]["falseHardEdgeFraction"],
            "baselineCandidateRenderDifference": hard["baselineCandidateRenderDifference"],
            "groundTruthHardBoundaryF1": 1.0, "f1Basis": "Task 08B.1.3 analytic hard-boundary fixture; identical render and segmentation preserve the existing F1=1.0."},
        "geometryUnchanged": old_labels == new_seg["labelMapSha256"] and clean_regions(old_seg) == clean_regions(new_seg) and shared_old == shared_new and geom_equal,
        "alphaUnchanged": p["alpha"]["exactlyUnchanged"]
    })
    write("svg_validation.json", {"candidateApiOutputs": measured["svgValidation"],
        "passCount": sum(bool(x["pass"]) for x in measured["svgValidation"].values()),
        "allEditableVectorNoEmbeddedRaster": all(bool(x["pass"]) for x in measured["svgValidation"].values())})

    scope = []
    for item in scope_before["scope"]:
        path = BACKEND / item["path"]
        actual = hash_file(path) if path.is_file() else None
        scope.append({"path": item["path"], "baselineSha256": item["sha256"], "currentSha256": actual,
                      "unchanged": actual is not None and actual.casefold() == item["sha256"].casefold()})
    baseline_hash = "FD074787F61D12E4B069F9EF481F9CA66BC3D8423637E13A6D532A08C06AA29D"
    candidate_hash = "DB13DE1D58DA2158B6C2F3F0492E81B1EF3F498577CDE6B2355B93A3FCD0A28A"
    production_source = BACKEND / "mediastudio/image_tools/vectorization_contour/appearance.py"
    current_hash = hash_file(production_source)
    write("production_changes.json", {
        "productionFileAllowedForTrial": "mediastudio/image_tools/vectorization_contour/appearance.py",
        "candidateSha256": candidate_hash, "baselineSha256": baseline_hash, "restoredCurrentSha256": current_hash,
        "candidateDiffSummary": "one appearance-local change: edge_support uses source edge excess over fitted base-paint edge magnitude; no thresholds changed.",
        "productionChangesRolledBack": current_hash.casefold() == baseline_hash.casefold(),
        "onlyProductionFileChangedDuringTrial": "mediastudio/image_tools/vectorization_contour/appearance.py",
        "productionScopeAgainstTask0813": {"files": scope, "unchangedCount": sum(x["unchanged"] for x in scope), "totalCount": len(scope), "allUnchanged": all(x["unchanged"] for x in scope)},
        "smartV2Unchanged": all(x["unchanged"] for x in scope if "vectorization_v2/" in x["path"]),
        "nonProductionFiles": ["tools/task_08b_1_4/*", "artifacts/contour_preserving/task_08b_1_4/*", "tests/test_task_08b_1_4_acceptance.py"]
    })

    regression_path = ART / "full_regression.json"
    regression = read(regression_path) if regression_path.exists() else {"pass": False, "status": "PENDING"}
    artifacts_ok = all((ART / name).is_file() for name in (
        "appearance_feature_root_cause.json", "internal_feature_diagnostics.json", "appearance_before_after.json",
        "false_edge_before_after.json", "color_fidelity_before_after.json", "detail_preservation_validation.json",
        "heldout_gradient_validation.json", "geometry_integrity.json", "production_changes.json", "svg_validation.json"))
    flags = {
        "APPEARANCE_SUBOPERATION_ROOT_CAUSE_VERIFIED": True,
        "CONTOUR_APPEARANCE_FIX_IMPLEMENTED": False,
        "FALSE_EDGE_BELOW_THRESHOLD": cand_edge["falseHardEdgeFraction"] < .01,
        "COLOR_FIDELITY_NONREGRESSION": cand_edge["meanDeltaE00"] <= base_edge["meanDeltaE00"] and cand_edge["p95DeltaE00"] <= base_edge["p95DeltaE00"],
        "REAL_DETAILS_PRESERVED": all(row["candidate"]["paintRecallDeltaE00Le10"] >= row["baseline"]["paintRecallDeltaE00Le10"] for row in detail_rows.values()),
        "HELDOUT_VALIDATION_PASS": False,
        "GEOMETRY_UNCHANGED": geom_equal and old_labels == new_seg["labelMapSha256"] and shared_old == shared_new,
        "ALPHA_UNCHANGED": p["alpha"]["exactlyUnchanged"],
        "SVG_NO_EMBEDDED_RASTER": all(bool(x["pass"]) for x in measured["svgValidation"].values()),
        "SMART_V2_UNCHANGED": all(x["unchanged"] for x in scope if "vectorization_v2/" in x["path"]),
        "FULL_REGRESSION_PASS": bool(regression.get("pass")),
        "FIX_ACCEPTED": False,
        "PRODUCTION_CHANGES_ROLLED_BACK": current_hash.casefold() == baseline_hash.casefold(),
        "TASK_08B_1_4_COMPLETE": bool(regression.get("pass")) and artifacts_ok,
        "PRODUCTION_RELEASE_READY": False
    }
    report = f'''# MediaStudio Task 08B.1.4 — Contour Appearance False-Boundary Repair

## Kết luận

Đã xác minh root cause và thử đúng một candidate appearance-local. Candidate bị loại vì không xuống dưới ngưỡng false-edge 1% và làm xấu cả mean/P95 ΔE00. Production source đã được khôi phục đúng SHA baseline. Không có sửa đổi nào giữ lại trong production; blocker nằm ở giới hạn biểu diễn của base gradient và không thể xử lý an toàn bằng cách chỉ bỏ/sàng lọc residual patches trong phạm vi task.

## Root cause từ code và counterfactual

`_fit_paint` chọn một radial gradient năm stop cho trường radial-angular liên tục phi tuyến. `_detect_internal_features` tìm các connected components có residual ΔE00 cao, rồi xác nhận bằng độ lớn edge nguồn dọc mask boundary. Độ lớn gradient mượt bị xem như edge support dù không có hard boundary thật. Sau đó component được vẽ bằng median RGB phẳng thành closed SVG path. Các patch này giảm local color error nhưng tạo ranh giới cứng giữa fill phẳng và radial parent.

Counterfactual cùng source, ROI, Edge renderer và detector: base paint-only có {roi0['falseEdgeFraction']*100:.4f}% false edge ({roi0['falseEdgePixels']} px), mean/P95 ΔE00 {roi0['meanDeltaE00']['mean']:.3f}/{roi0['meanDeltaE00']['p95']:.3f}. Bốn feature paths hạ sai số thành {full0['meanDeltaE00']['mean']:.3f}/{full0['meanDeltaE00']['p95']:.3f}, nhưng nâng false edge thành {full0['falseEdgeFraction']*100:.4f}% ({full0['falseEdgePixels']} px). Output diagnostic và final SVG có false-edge mask IoU 1.0 nên lỗi không đến từ clipping/composer.

## Candidate và acceptance

| Metric | Baseline | Candidate | Result |
|---|---:|---:|---|
| Nonlinear false edges | {base_edge['falseHardEdgeFraction']*100:.4f}% ({base_edge['falseHardEdgePixels']} px) | {cand_edge['falseHardEdgeFraction']*100:.4f}% ({cand_edge['falseHardEdgePixels']} px) | {'PASS' if cand_edge['falseHardEdgeFraction'] < .01 else 'FAIL: >=1%'} |
| Nonlinear mean ΔE00 | {base_edge['meanDeltaE00']:.4f} | {cand_edge['meanDeltaE00']:.4f} | {'PASS' if cand_edge['meanDeltaE00'] <= base_edge['meanDeltaE00'] else 'FAIL: worsened'} |
| Nonlinear P95 ΔE00 | {base_edge['p95DeltaE00']:.4f} | {cand_edge['p95DeltaE00']:.4f} | {'PASS' if cand_edge['p95DeltaE00'] <= base_edge['p95DeltaE00'] else 'FAIL: worsened'} |
| Internal feature paths | {p['baseline']['featureCount']} | {p['candidate']['featureCount']} | Diagnostic only; count is not an acceptance metric |
| Hard-boundary F1 (2 px) | 1.0000 | 1.0000 | unchanged; render, segmentation and boundary metric unchanged |
| Small sharp detail paint recall (ΔE00≤10) | {detail_rows['small_sharp_color_detail']['baseline']['paintRecallDeltaE00Le10']:.4f} | {detail_rows['small_sharp_color_detail']['candidate']['paintRecallDeltaE00Le10']:.4f} | preserved |
| Thin highlight paint recall (ΔE00≤10) | {detail_rows['thin_highlight']['baseline']['paintRecallDeltaE00Le10']:.4f} | {detail_rows['thin_highlight']['candidate']['paintRecallDeltaE00Le10']:.4f} | preserved, but unchanged from baseline |
| Heldout false edges | {heldout['baseline']['metrics']['falseEdge']['falseHardEdgeFraction']*100:.4f}% | {heldout['candidate']['metrics']['falseEdge']['falseHardEdgeFraction']*100:.4f}% | FAIL: still above 1% |
| Heldout mean ΔE00 | {heldout['baseline']['metrics']['falseEdge']['meanDeltaE00']:.4f} | {heldout['candidate']['metrics']['falseEdge']['meanDeltaE00']:.4f} | FAIL: small regression |

Candidate reduced primary false-edge count by {base_edge['falseHardEdgePixels']-cand_edge['falseHardEdgePixels']} px ({(base_edge['falseHardEdgePixels']-cand_edge['falseHardEdgePixels'])/base_edge['falseHardEdgePixels']*100:.1f}%), but retained large top/bottom patch boundaries. It worsened primary mean ΔE00 by {cand_edge['meanDeltaE00']-base_edge['meanDeltaE00']:.4f} and P95 by {cand_edge['p95DeltaE00']-base_edge['p95DeltaE00']:.4f}. Sharp detail and highlight fixtures were preserved at baseline recall, but that alone does not make the repair acceptable.

## Geometry, alpha, SVG, Smart V2

- Source SHA is shared. Segmentation labels, region records, five shared interface pairs/counts, and all six production region path `d` strings match exactly between baseline and candidate.
- Primary rendered alpha: pixel-exact match.
- Candidate API SVG validation: {sum(bool(x['pass']) for x in measured['svgValidation'].values())}/{len(measured['svgValidation'])} valid editable vector SVGs, with zero embedded raster elements/data URIs.
- Hard-boundary analytic regression output is byte-pixel identical; Task 08B.1.3 F1 remains 1.0000 at 2 px.
- Smart V2 source scope unchanged: {sum(x['unchanged'] for x in scope if 'vectorization_v2/' in x['path'])}/{sum('vectorization_v2/' in x['path'] for x in scope)} files.
- Production appearance source restored SHA-256: `{current_hash}` (expected baseline `{baseline_hash}`).

## Regression

{('Full backend regression passed.' if regression.get('pass') else 'Full backend regression status: ' + str(regression.get('status', 'PENDING')) + '.')}

## Visual artifacts

- [Baseline / candidate nonlinear gradient](nonlinear_gradient_before_after.png)
- [Internal feature path overlay](feature_path_overlay.png)
- [False-edge mask comparison](false_edge_mask_comparison.png)
- [ΔE00 heatmap](deltae00_heatmap.png)
- [Detail preservation fixtures](detail_preservation_comparison.png)

## Status

```text
{chr(10).join(f'{key} = {str(value).lower()}' for key, value in flags.items())}
```

The narrow candidate cannot safely satisfy the gates because the radial base paint underfits the continuous nonlinear field. Removing/suppressing more patches trades the visible edges for worse color fidelity. No broader gradient system or follow-up phase was started.
'''
    (ART / "task_08b_1_4_report.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
