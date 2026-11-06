from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

from tools.task_08b_1_6b.svg_coordinate_contract import (
    linear_gradient_coordinates, sample_stops,
)

ART = Path(__file__).resolve().parents[1] / "artifacts/contour_preserving/task_08b_1_6b"
SVG_NS = "http://www.w3.org/2000/svg"


def make_gradient(viewbox: str, shape: tuple[int, int], attrs: dict[str, str], par: str = "none"):
    root = ET.Element(f"{{{SVG_NS}}}svg", {"viewBox": viewbox, "preserveAspectRatio": par})
    gradient = ET.SubElement(root, f"{{{SVG_NS}}}linearGradient", attrs)
    return linear_gradient_coordinates(root, gradient, shape)[0]


def test_user_space_full_canvas_coordinates_use_pixel_centers_and_pad():
    t = make_gradient("0 0 512 512", (512, 512), {
        "gradientUnits": "userSpaceOnUse", "x1": "0", "y1": "0", "x2": "511", "y2": "0"})
    assert t[100, 0] == pytest.approx(.5 / 511)
    assert t[100, 510] == pytest.approx(510.5 / 511)
    assert t[100, 511] == 1.0
    assert np.allclose(t[0], t[-1])


def test_coordinates_do_not_depend_on_off_center_or_eroded_training_support():
    t = make_gradient("0 0 100 80", (80, 100), {
        "gradientUnits": "userSpaceOnUse", "x1": "0", "y1": "0", "x2": "99", "y2": "0"})
    support = np.zeros((80, 100), dtype=bool)
    support[8:70, 17:88] = True
    eroded = np.zeros_like(support)
    eroded[9:69, 18:87] = True
    assert np.array_equal(t[support & eroded], t[eroded])
    assert t[30, 20] == pytest.approx(20.5 / 99)
    assert t[30, 4] == pytest.approx(4.5 / 99)


def test_viewbox_aspect_ratio_mapping_for_portrait_and_landscape():
    portrait = make_gradient("0 0 100 200", (200, 100), {
        "gradientUnits": "userSpaceOnUse", "x1": "0", "x2": "100"})
    landscape = make_gradient("0 0 200 100", (100, 200), {
        "gradientUnits": "userSpaceOnUse", "x1": "0", "x2": "200"})
    assert portrait[50, 0] == pytest.approx(.5 / 100)
    assert portrait[50, 99] == pytest.approx(99.5 / 100)
    assert landscape[50, 0] == pytest.approx(.5 / 200)
    assert landscape[50, 199] == pytest.approx(199.5 / 200)


def test_gradient_transform_is_inverted_for_fitting_coordinates():
    t = make_gradient("0 0 50 10", (10, 50), {
        "gradientUnits": "userSpaceOnUse", "x1": "0", "y1": "0", "x2": "100", "y2": "0",
        "gradientTransform": "translate(10 0) scale(2 1)"})
    assert t[0, 19] == pytest.approx(.0475)


def test_object_bounding_box_coordinates_support_bbox_transform():
    root = ET.Element(f"{{{SVG_NS}}}svg", {"viewBox": "0 0 200 120", "preserveAspectRatio": "none"})
    grad = ET.SubElement(root, f"{{{SVG_NS}}}linearGradient", {
        "gradientUnits": "objectBoundingBox", "x1": "0%", "x2": "100%",
        "gradientTransform": "translate(0.1 0)"})
    t, meta = linear_gradient_coordinates(root, grad, (120, 200), object_bbox=(50, 20, 100, 80))
    assert t[20, 50] == 0.0  # start falls before bbox after the 0.1 transform; default spread is pad
    assert meta["gradientUnits"] == "objectBoundingBox"


def test_svg_spread_methods_and_duplicate_stop_interpolation():
    common = {"gradientUnits": "userSpaceOnUse", "x1": "0", "x2": "10", "y1": "0", "y2": "0"}
    pad = make_gradient("0 0 30 1", (1, 30), {**common, "spreadMethod": "pad"})
    repeat = make_gradient("0 0 30 1", (1, 30), {**common, "spreadMethod": "repeat"})
    reflect = make_gradient("0 0 30 1", (1, 30), {**common, "spreadMethod": "reflect"})
    assert pad[0, 10] == 1.0
    assert repeat[0, 10] == pytest.approx(.05)
    assert reflect[0, 10] == pytest.approx(.95)
    colors, _ = sample_stops(np.array([0., .5, .5, 1.]),
        np.array([[0., 0., 0.], [0., 0., 0.], [1., 0., 0.], [1., 1., 1.]]), np.ones(4),
        np.array([.499999, .5, .500001]))
    assert colors[0, 0] == 0.0
    assert colors[1, 0] == 1.0
    assert colors[2, 0] == 1.0


def test_coordinate_contract_artifacts_confirm_fit_svg_agreement_and_baseline():
    baseline = json.loads((ART / "baseline_reproduction.json").read_text(encoding="utf-8"))
    contract = json.loads((ART / "coordinate_contract_analysis.json").read_text(encoding="utf-8"))
    assert baseline["reproduced"] is True
    assert contract["selfCheckPass"] is True
    assert contract["candidateFitterVsSerializedSVG"]["allSampleCoordinatesExactWithin1e-12"] is True
    assert contract["candidateFitterVsSerializedSVG"]["percentageMismatchedAt1e-10"] == 0.0
    assert contract["baselineLegacyVsSVG"]["maxAbsAcrossSamples"] > 0.1


def test_primary_candidate_svg_preserves_geometry_and_is_vector_only():
    svg = ART / "experimental_coordinate_consistent.svg"
    root = ET.parse(svg).getroot()
    assert root.tag == f"{{{SVG_NS}}}svg"
    names = [node.tag.rsplit("}", 1)[-1] for node in root.iter()]
    assert names.count("linearGradient") == 2
    assert names.count("image") == 0
    assert b"data:image/" not in svg.read_bytes().lower()
    integrity = json.loads((ART / "geometry_alpha_integrity.json").read_text(encoding="utf-8"))
    assert integrity["geometryUnchangedAll"] is True
    assert integrity["alphaUnchangedVsOldAll"] is True


def test_report_decision_does_not_claim_production_release_or_task_1_7_without_gates():
    status = json.loads((ART / "acceptance_status.json").read_text(encoding="utf-8"))["statuses"]
    assert status["PRODUCTION_RELEASE_READY"] is False
    if not status["FEASIBILITY_PROVEN"]:
        assert status["TASK_08B_1_7_READY"] is False
        assert status["RESEARCH_BRANCH_DECISION"] != "CASE_A"
