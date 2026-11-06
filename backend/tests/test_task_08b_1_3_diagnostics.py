from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

BACKEND = Path(__file__).resolve().parents[1]
ARTIFACTS = BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_3"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def test_three_analytic_fixture_groups_have_valid_masks_and_fixed_canvas() -> None:
    record = _json(ARTIFACTS / "analytic_gradient_fixtures.json")
    assert record["fixtureGroupCount"] == 3
    assert record["allValid"] is True
    assert len({row["sourceFamilyId"] for row in record["fixtureGroups"]}) == 3
    for row in record["fixtureGroups"]:
        assert row["validation"]["valid"] is True
        assert row["size"] == [512, 512]
        for key in ("source", "alpha", "labels", "hard", "soft", "silhouette"):
            path = ARTIFACTS / row["files"][key]
            assert path.is_file()
            with Image.open(path) as image:
                assert image.size == (512, 512)


def test_false_edge_detector_negative_and_positive_controls_pass() -> None:
    record = _json(ARTIFACTS / "false_edge_detector_controls.json")
    assert record["pass"] is True
    assert record["negativeControl"]["falseEdgeFraction"] == 0.0
    assert record["positiveControl"]["falseEdgeFraction"] > 0.01


def test_both_real_api_engines_succeeded_on_each_fixture() -> None:
    record = _json(ARTIFACTS / "api_runs.json")
    assert record["allPass"] is True
    assert len(record["results"]) == 3
    for row in record["results"]:
        assert row["status"] == "PASS"
        assert row["sameAssetIdUsedByBothEngines"] is True
        assert set(row["engines"]) == {"smart_reconstruction", "contour_preserving"}
        assert all(engine["status"] == "SUCCEEDED" for engine in row["engines"].values())


def test_svg_viewbox_native_render_and_alpha_coordinate_alignment() -> None:
    record = _json(ARTIFACTS / "false_edge_analysis.json")
    for fixture in record["fixtures"].values():
        for row in fixture["engines"].values():
            assert row["coordinateAlignmentValid"] is True
            assert row["svgViewBoxMatchesNativeCanvas"] is True
            assert row["svgNoEmbeddedRaster"] is True
            assert row["nativeRenderDimensions"] == [512, 512]
            assert row["outputAlphaIoU"] >= 0.99
            assert row["edgeVsSvgSkia"]["status"] == "PASS"
            assert row["edgeVsSvgSkia"]["dimensions"] == [512, 512]


def test_true_internal_hard_boundary_is_recovered_within_two_pixels() -> None:
    record = _json(ARTIFACTS / "false_edge_analysis.json")
    fixture = record["fixtures"]["hard_boundary_with_gradient"]
    assert fixture["hardBoundaryTruthPixels"] > 0
    for row in fixture["engines"].values():
        metrics = row["boundaryStageComparison"]["segmentationVsGroundTruth"]
        assert metrics["tolerancePx"] == 2.0
        assert metrics["precisionWithinTolerance"] >= 0.98
        assert metrics["recallWithinTolerance"] >= 0.98


def test_contour_gradient_false_edges_are_visible_and_not_segmentation_splits() -> None:
    record = _json(ARTIFACTS / "false_edge_analysis.json")
    row = record["fixtures"]["smooth_nonlinear_gradient"]["engines"]["contour_preserving"]
    assert row["gradientMetrics"]["falseHardEdgeFraction"] >= 0.01
    assert row["segmentation"]["uniqueRegionCountInSoftROI"] == 1
    assert row["segmentation"]["internalBoundaryPixelCountInSoftROI"] == 0
    assert row["appearanceBasePaintOnlyMetrics"]["falseHardEdgeFraction"] < 0.01
    assert row["appearanceStageMetrics"]["falseHardEdgeFraction"] >= 0.01
    assert row["appearanceDiagnosticVsProductionRender"]["falseEdgeMaskIoU"] >= 0.70
    assert row["boundaryStageComparison"]["falseVisualEdgeOverlapWithInternalAppearanceFeatures"] >= 0.70
    assert row["firstFailingStage"] == "GRADIENT_FITTING_ERROR"
