from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

ART = Path(__file__).resolve().parents[1] / "artifacts/contour_preserving/task_08b_1_6a"
OLD = Path(__file__).resolve().parents[1] / "artifacts/contour_preserving/task_08b_1_6"


def read(name: str):
    return json.loads((ART / name).read_text(encoding="utf-8"))


def test_primary_baseline_reproduces_frozen_source_geometry_and_metrics():
    report = read("baseline_reproduction.json")
    assert report["reproduced"] is True
    assert report["sourceHashMatch"] is True
    assert report["baseSvgHashMatch"] is True
    assert report["originalSvgHashMatch"] is True
    assert report["currentSvgHashMatch"] is True
    assert report["inputs"]["roiPixels"] == 109048
    assert report["metricReproductionDelta"]["meanDeltaE00"] == 0.0
    assert report["metricReproductionDelta"]["p95DeltaE00"] == 0.0


def test_fitting_matrix_has_only_the_shared_constant_null_direction():
    matrix = read("fitting_matrix_analysis.json")
    null = read("null_space_analysis.json")
    assert matrix["numberOfColumns"] == 34
    assert matrix["numericalRank"] == 33
    assert matrix["numericalNullity"] == null["nullity"] == 1
    assert null["absoluteAlignment"] > 0.999999
    assert null["A_times_v_l2"] < 1e-12
    assert null["regularizer_times_v_l2"] < 1e-12
    assert matrix["sharedConstantBasis"]["parameterFamily"]["designPredictionLinf"] < 1e-12


def test_equivalent_row_orders_are_numerically_stable():
    stability = read("parameter_stability_comparison.json")
    assert len(stability["rowPermutationRuns"]) == 3
    assert max(row["parameterDeltaMaxAbs"] for row in stability["rowPermutationRuns"]) < 1e-10
    assert max(row["predictionDeltaLinf"] for row in stability["rowPermutationRuns"]) < 1e-10
    constrained = stability["constrainedVsOriginal"]
    assert constrained["parameterDeltaMaxAbs"] < 1e-10
    assert constrained["predictionDeltaLinf"] < 1e-10


def test_gauge_candidate_isolated_and_preserves_the_original_svg():
    result = read("constrained_fitting_results.json")
    original = OLD / "fixtures/smooth_nonlinear_gradient/experimental_multidirectional.svg"
    candidate = ART / "experimental_constrained.svg"
    assert result["serializedStopColorsChanged"] is False
    assert result["svgBytesIdentical"] is True
    assert original.read_bytes() == candidate.read_bytes()
    assert result["renderedQuality"]["originalResearch"] == result["renderedQuality"]["constrainedCandidate"]


def test_objective_to_svg_mapping_mismatch_is_distinguished_from_renderer_error():
    report = read("objective_renderer_comparison.json")
    assessment = report["rootCauseAssessment"]
    pairs = report["pairwiseComparisons"]
    fit_vs_svg = pairs["A_LINEAR_FITTING_SPACE__VS__B_ANALYTICAL_SOURCE_OVER_FROM_EMITTED_SVG"]
    analytic_vs_edge = pairs["B_ANALYTICAL_SOURCE_OVER_FROM_EMITTED_SVG__VS__C_ACTUAL_EDGE_GRADIENT_ONLY"]
    analytic_detail_vs_full = pairs["B_PLUS_FROZEN_DETAIL_OVERLAY__VS__C_ACTUAL_EDGE_FULL_SVG"]
    assert assessment["primaryClassification"] == "OBJECTIVE_RENDER_MISMATCH"
    assert report["fittingVsSvgCoordinates"]["mismatchVerified"] is True
    assert fit_vs_svg["meanDeltaE00"] > 5.0
    assert fit_vs_svg["p95DeltaE00"] > 10.0
    assert analytic_vs_edge["meanDeltaE00"] < 1.0
    assert analytic_vs_edge["p95DeltaE00"] < 3.0
    assert analytic_detail_vs_full["meanDeltaE00"] < 1.0
    assert analytic_detail_vs_full["p95DeltaE00"] < 3.0


def test_primary_and_heldout_quality_failures_remain_truthful():
    primary = read("primary_before_after.json")
    heldout = read("heldout_validation.json")
    detail = read("detail_preservation.json")
    assert primary["primaryFalseEdgePass"] is False
    assert primary["primaryMeanDeltaE00Pass"] is False
    assert primary["primaryP95DeltaE00Pass"] is False
    assert primary["originalResearch"] == primary["constrainedCandidate"]
    assert heldout["pass"] is False
    assert heldout["candidateFrozenBeforeHeldout"] is True
    assert heldout["tunedOnHeldout"] is False
    assert detail["smallSharpDetailPass"] is True
    assert detail["thinHighlightRecallNonregression"] is False
    assert detail["inheritedThinHighlightAlphaDifferenceFromCurrent"] == 124
    assert detail["alphaUnchangedByNumericalCandidate"] is True


def test_all_candidate_svgs_remain_geometry_preserving_vector_only_and_renderer_compatible():
    integrity = read("geometry_alpha_integrity.json")
    renderer = read("renderer_compatibility.json")
    vector = read("svg_vector_only_validation.json")
    assert integrity["geometryUnchangedAll"] is True
    assert integrity["alphaUnchangedByCandidateAll"] is True
    assert renderer["passCount"] == 6
    assert renderer["allPass"] is True
    assert vector["allValidVectorOnly"] is True
    for path in (ART / "experimental_constrained.svg", *(ART / "fixtures" / x / "experimental_constrained.svg"
                                                        for x in ("smooth_nonlinear_gradient", "smooth_alternate_heldout",
                                                                  "small_sharp_color_detail", "thin_highlight",
                                                                  "hard_boundary_with_gradient", "low_contrast_multistop_gradient"))):
        root = ET.parse(path).getroot()
        assert root.tag.endswith("svg")
        assert not any(node.tag.rsplit("}", 1)[-1] == "image" for node in root.iter())
        assert b"data:image/" not in path.read_bytes().lower()


def test_production_scope_remains_unchanged():
    result = read("production_changes.json")
    assert result["researchOnly"] is True
    assert result["productionFilesChanged"] == []
    assert result["prototypeConnectedToDispatcher"] is False
    assert result["unchangedCount"] == result["totalCount"] == 36
    assert result["allUnchanged"] is True
