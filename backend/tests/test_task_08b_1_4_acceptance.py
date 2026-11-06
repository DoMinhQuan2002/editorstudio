from __future__ import annotations

import json
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
ART = BACKEND / "artifacts/contour_preserving/task_08b_1_4"


def load(name: str):
    return json.loads((ART / name).read_text(encoding="utf-8"))


def test_task_08b_1_4_feature_level_root_cause_counterfactual():
    data = load("appearance_feature_root_cause.json")
    diag = load("internal_feature_diagnostics.json")["baselineFeatureDiagnostics"]
    assert data["verified"] is True
    assert data["hypotheses"]["D_insufficient_base_gradient_model"]["primary"] is True
    assert diag["basePaintOnly"]["falseEdgeFraction"] == 0
    assert diag["appearanceWithFeatures"]["falseEdgeFraction"] > 0.01
    assert len(diag["featureRows"]) == 4
    for row in diag["featureRows"]:
        assert row["falseEdgePixelsNearFeatureBoundary"] > 0
        assert row["sourceCrossingBoundaryResponseCIE76"]["mean"] < row["featureOnlyBoundaryResponseCIE76"]["mean"]
        assert row["meanLocalDeltaE00Change"] < 0


def test_task_08b_1_4_primary_candidate_is_rejected_by_fixed_gates():
    edge = load("false_edge_before_after.json")
    color = load("color_fidelity_before_after.json")
    assert edge["candidateBelowThreshold"] is False
    assert edge["candidate"]["falseHardEdgeFraction"] < edge["baseline"]["falseHardEdgeFraction"]
    assert color["nonregression"] is False
    assert color["candidate"]["mean"] > color["baseline"]["mean"]
    assert color["candidate"]["p95"] > color["baseline"]["p95"]
    assert load("appearance_feature_root_cause.json")["candidateEvidence"]["decision"].startswith("Rejected")


def test_task_08b_1_4_analytic_detail_and_thin_highlight_are_preserved():
    data = load("detail_preservation_validation.json")
    assert data["smallSharpColorDetailPreserved"] is True
    assert data["thinHighlightPreserved"] is True
    assert data["candidateDoesNotRegressDetailPaintRecall"] is True
    assert data["fixtures"]["small_sharp_color_detail"]["candidate"]["paintRecallDeltaE00Le10"] == 1.0
    assert data["fixtures"]["thin_highlight"]["candidate"]["paintRecallDeltaE00Le10"] >= 0.9


def test_task_08b_1_4_heldout_variant_is_reported_as_not_passing():
    data = load("heldout_gradient_validation.json")
    assert data["heldoutNotUsedForRuleSelection"] is True
    assert data["pass"] is False
    assert data["candidateFalseEdgeBelowOnePercent"] is False
    assert data["candidateColorMeanNonregression"] is False


def test_task_08b_1_4_geometry_alpha_and_hard_boundary_are_unchanged():
    data = load("geometry_integrity.json")
    assert data["sourceSha256Same"] is True
    assert data["segmentation"]["labelMapIdentical"] is True
    assert data["segmentation"]["regionRecordsIdentical"] is True
    assert data["sharedBoundaries"]["pairAndPointCountIdentical"] is True
    assert data["productionSvgRegionPathDIdentical"] is True
    assert data["geometryUnchanged"] is True
    assert data["alphaUnchanged"] is True
    hard = data["hardBoundaryRegression"]
    assert hard["baselineCandidateRenderDifference"]["rgbMeanAbsoluteError"] == 0
    assert hard["baselineCandidateRenderDifference"]["alphaDifferentPixels"] == 0
    assert hard["groundTruthHardBoundaryF1"] == 1.0


def test_task_08b_1_4_svg_api_and_smart_v2_safety():
    svg = load("svg_validation.json")
    assert svg["passCount"] == len(svg["candidateApiOutputs"])
    assert svg["allEditableVectorNoEmbeddedRaster"] is True
    assert all(row["pass"] for row in svg["candidateApiOutputs"].values())
    baseline_api, candidate_api = load("api_baseline.json"), load("api_candidate.json")
    assert baseline_api["allApiRunsPassed"] is True
    assert candidate_api["allApiRunsPassed"] is True
    production = load("production_changes.json")
    assert production["smartV2Unchanged"] is True
    assert production["productionChangesRolledBack"] is True
    assert production["productionScopeAgainstTask0813"]["allUnchanged"] is True


def test_task_08b_1_4_all_required_artifacts_exist():
    required = [
        "appearance_feature_root_cause.json", "internal_feature_diagnostics.json",
        "appearance_before_after.json", "false_edge_before_after.json",
        "color_fidelity_before_after.json", "detail_preservation_validation.json",
        "heldout_gradient_validation.json", "geometry_integrity.json",
        "production_changes.json", "full_regression.json", "task_08b_1_4_report.md",
        "nonlinear_gradient_before_after.png", "feature_path_overlay.png",
        "false_edge_mask_comparison.png", "deltae00_heatmap.png",
        "detail_preservation_comparison.png",
    ]
    assert all((ART / name).is_file() for name in required)
