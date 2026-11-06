from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
ART = BACKEND / "artifacts/contour_preserving/task_08b_1_5"
sys.path.insert(0, str(BACKEND))
from tools.task_08b_1_5.run_feasibility import _smooth_stops  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def path_data(path: Path, prefixes: tuple[str, ...]) -> dict[str, str]:
    root = ET.parse(path).getroot()
    return {n.attrib["id"]: n.attrib.get("d", "") for n in root.iter()
            if n.tag.rsplit("}", 1)[-1] == "path" and n.attrib.get("id", "").startswith(prefixes)}


def test_continuous_gradient_fit_uses_bounded_smoothed_stops_with_sparse_bins():
    y, x = np.mgrid[0:32, 0:32]
    t = np.where(x < 16, 0.08, 0.92).astype(np.float32)
    source = np.stack([40 + 130 * t, 80 + 50 * t, 170 - 60 * t], axis=-1).astype(np.uint8)
    base = np.full_like(source, [90, 100, 110])
    support = np.ones(t.shape, dtype=bool)

    stops, counts = _smooth_stops(source, base, t, support)

    assert len(stops) == 17
    assert len(counts) == 17
    assert [row["offset"] for row in stops] == sorted(row["offset"] for row in stops)
    assert stops[0]["offset"] == 0.0 and stops[-1]["offset"] == 1.0
    assert all(0.0 <= row["opacity"] <= 1.0 for row in stops)
    assert all(len(row["colorRGB"]) == 3 and all(0 <= c <= 255 for c in row["colorRGB"]) for row in stops)
    assert np.isfinite(np.asarray([row["opacity"] for row in stops])).all()


def test_primary_experiment_reports_fixed_feasibility_gates_without_hiding_failure():
    result = read_json(ART / "primary_feasibility_comparison.json")
    exp = result["EXPERIMENTAL_CONTINUOUS_APPEARANCE"]
    gates = result["acceptanceTargets"]
    assert exp["falseEdgeFraction"] < 0.01
    assert exp["geometryUnchanged"] is True
    assert exp["alphaDifferentPixels"] == 0
    assert gates["svgVectorOnly"] is True
    assert gates["meanDeltaE00NoWorseThanCurrentFull"] == (
        exp["meanDeltaE00"] <= result["CURRENT_FULL_APPEARANCE"]["meanDeltaE00"]
    )
    assert gates["p95DeltaE00NoWorseThanCurrentFull"] == (
        exp["p95DeltaE00"] <= result["CURRENT_FULL_APPEARANCE"]["p95DeltaE00"]
    )


def test_experimental_svg_keeps_frozen_geometry_and_contains_no_raster():
    data = read_json(ART / "feasibility_all_fixtures.json")
    for fixture_id, row in data["fixtures"].items():
        svg = Path(row["experimentalContinuous"]["svg"])
        validation = row["experimentalContinuous"]["svgValidation"]
        assert svg.is_file()
        assert validation["xmlValid"] is True
        assert validation["embeddedRasterElementCount"] == 0
        assert validation["embeddedRasterDataUriCount"] == 0
        assert row["experimentalContinuous"]["geometryDIdenticalToCurrent"] is True
    primary = data["fixtures"]["smooth_nonlinear_gradient"]["experimentalContinuous"]
    assert primary["alphaDifferentPixelsVsBase"] == 0


def test_detail_paths_remain_identical_when_experiment_keeps_existing_details():
    for fixture_id in ("small_sharp_color_detail", "thin_highlight"):
        folder = ART / "fixtures" / fixture_id
        current = BACKEND / "artifacts/contour_preserving/task_08b_1_4/runs/task08b1_4_baseline/outputs" / fixture_id / "contour_preserving/output.svg"
        experimental = folder / "experimental_with_existing_details.svg"
        assert path_data(current, ("contour-detail-",)) == path_data(experimental, ("contour-detail-",))


def test_renderer_compatibility_is_measured_and_production_hashes_match_baseline():
    renderers = read_json(ART / "renderer_compatibility.json")
    assert renderers["pass"] is True
    assert all(row["compatible"] for row in renderers["fixtures"].values())
    production = read_json(ART / "production_changes.json")
    assert production["productionUnchanged"] is True
    assert production["productionAppearanceSha256"].upper() == production["approvedBaselineSha256"].upper()
    assert production["sourceScopeComparison"]["allUnchanged"] is True

