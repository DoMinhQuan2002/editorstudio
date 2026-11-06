from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from tools.task_08b_1_6.run_multidirectional import (
    ART, OPACITY, STOPS, basis, de_map, fit_stops, jread, load_rgba, white,
)


def test_directional_basis_interpolates_constant_and_ramp_without_discontinuity():
    t = np.linspace(0.0, 1.0, 1001)
    b = basis(t)
    assert b.shape == (1001, STOPS)
    assert np.allclose(b.sum(axis=1), 1.0, atol=1e-12)
    assert np.array_equal(b[0], np.eye(STOPS)[0])
    assert np.array_equal(b[-1], np.eye(STOPS)[-1])
    ramp = b @ np.linspace(0.0, 1.0, STOPS)
    assert np.all(np.diff(ramp) >= 0.0)
    assert np.max(np.abs(ramp - t)) < 1e-12


def test_multidirectional_stop_fit_is_deterministic_and_bounded():
    yy, xx = np.mgrid[0:48, 0:48]
    source = np.stack((60 + xx * 2, 40 + yy * 2, 100 + (xx + yy)), axis=2).clip(0, 255).astype(np.uint8)
    base = np.full((48, 48, 3), 100, dtype=np.uint8)
    support = np.ones((48, 48), dtype=bool)
    a, trace_a = fit_stops(source, base, support, [0.0, 90.0])
    b, trace_b = fit_stops(source, base, support, [0.0, 90.0])
    assert trace_a == trace_b
    assert len(a) == 2
    assert all(x.shape == (STOPS, 3) for x in a)
    assert all(np.isfinite(x).all() and (x >= 0).all() and (x <= 1).all() for x in a)
    assert OPACITY == 0.5
    assert trace_a["iterations"] == 1
    assert trace_a["sampleCount"] == int(support.sum())


def test_residual_analysis_uses_development_only_and_freezes_two_directions():
    analysis = jread(ART / "residual_2d_analysis.json")
    cfg = jread(ART / "fitting_configuration.json")
    assert analysis["fixture"] == "smooth_nonlinear_gradient"
    assert analysis["annotatedHardBoundaryPixelsInsideSupport"] == 0
    assert cfg["state"] == "FROZEN_BEFORE_HELDOUT"
    assert cfg["heldoutTuning"] is False
    assert len(cfg["selectedDirectionsDegrees"]) == 2
    assert cfg["selectedDirectionsDegrees"] == analysis["directionPairSelection"]["selectedDegrees"]


def test_primary_metrics_report_locked_task_0815_baseline_and_failed_gates_truthfully():
    d = jread(ART / "primary_fidelity_comparison.json")
    current = d["models"]["CURRENT_FULL_APPEARANCE"]
    old = d["models"]["TASK_08B_1_5_CONTINUOUS"]
    candidate = d["models"]["TASK_08B_1_6_MULTIDIRECTIONAL"]
    assert abs(current["meanDeltaE00"] - 4.317268371582031) < 1e-5
    assert abs(current["p95DeltaE00"] - 8.964447975158691) < 1e-5
    assert abs(old["meanDeltaE00"] - 5.00398588180542) < 1e-5
    assert d["targets"]["falseEdgeBelow1Percent"] == (candidate["falseEdgeFraction"] < 0.01)
    assert d["targets"]["meanNoWorseThanCurrent"] == (candidate["meanDeltaE00"] <= current["meanDeltaE00"])
    assert d["targets"]["p95NoWorseThanCurrent"] == (candidate["p95DeltaE00"] <= current["p95DeltaE00"])
    assert d["targets"]["falseEdgeBelow1Percent"] is False
    assert d["targets"]["meanNoWorseThanCurrent"] is False
    assert d["targets"]["p95NoWorseThanCurrent"] is False


def test_primary_geometry_and_alpha_are_exact_and_svg_is_editable_vector_only():
    geometry = jread(ART / "primary_geometry_integrity.json")
    alpha = jread(ART / "primary_alpha_integrity.json")
    structure = jread(ART / "svg_structure_validation.json")
    svg = ART / "experimental_multidirectional.svg"
    root = ET.parse(svg).getroot()
    assert geometry["geometryPathsIdentical"] is True
    assert alpha["candidateBaseChangedPixels"] == 0
    assert structure["vectorOnlyAllFixtures"] is True
    assert structure["fixtures"]["smooth_nonlinear_gradient"]["validation"]["xmlValid"] is True
    assert sum(1 for n in root.iter() if n.tag.rsplit("}", 1)[-1] == "image") == 0
    assert b"data:image/" not in svg.read_bytes().lower()


def test_detail_and_alpha_regressions_are_not_hidden_as_pass():
    report = jread(ART / "detail_preservation_validation.json")
    small = report["fixtures"]["small_sharp_color_detail"]["recall"]
    thin = report["fixtures"]["thin_highlight"]["recall"]
    assert small["candidateRecall"] == small["currentRecall"] == 1.0
    assert thin["candidateRecall"] < thin["currentRecall"]
    assert report["thinHighlightPreserved"] is False
    assert report["geometryUnchanged"] is True
    assert report["alphaNonregression"] is False


def test_heldout_is_evaluated_after_freeze_and_failure_is_explicit():
    held = jread(ART / "heldout_validation.json")
    assert held["frozenConfigBeforeEvaluation"] is True
    assert held["tunedOnHeldout"] is False
    assert held["pass"] is False
    assert held["multidirectional"]["p95DeltaE00"] > held["current"]["p95DeltaE00"]


def test_renderer_compatibility_and_complexity_budget_are_measured():
    renderers = jread(ART / "renderer_compatibility.json")
    complexity = jread(ART / "performance_and_complexity.json")
    assert len(renderers["fixtures"]) == 6
    assert renderers["pass"] is True
    assert complexity["withinBudget"] is True
    for row in complexity["fixtures"].values():
        assert row["maxLayersPerRegion"] <= 4
        assert row["maxStopsPerGradient"] <= 17
        assert row["addedGradientDefinitions"] <= 8


def test_hard_boundary_geometry_regression_uses_frozen_path_equality():
    result = jread(ART / "hard_boundary_regression.json")
    assert result["geometryUnchanged"] is True
    assert result["geometryBoundaryF1PreservedByExactPathEquality"] is True
    assert result["candidateColorMeanDeltaE00"] > result["currentColorMeanDeltaE00"]


def test_production_hash_manifest_is_unchanged_and_no_dispatcher_integration():
    production = jread(ART / "production_changes.json")
    assert production["allUnchanged"] is True
    assert production["unchangedCount"] == production["totalCount"] == 36
    assert production["prototypeConnectedToDispatcher"] is False
    assert production["researchOnly"] is True
