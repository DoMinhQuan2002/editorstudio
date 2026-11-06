from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import sys

from mediastudio.image_tools.vectorization_contour.geometry import TopologyVertex

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "backend" / "artifacts" / "contour_preserving" / "task_07_2"
sys.path.insert(0, str(ARTIFACTS))
from local_refinement_experiment import (  # noqa: E402
    apply_updates_by_roi, build_vertex_updates, rollback_roi_group,
)


@dataclass(frozen=True)
class _Interface:
    id: int
    vertex_ids: tuple[int, ...]


@dataclass
class _Graph:
    vertices: list[TopologyVertex]
    interfaces: list[_Interface]
    scale_xy: tuple[float, float]


def test_global_resolution_candidates_are_true_segmentations_and_valid_svg() -> None:
    metrics = json.loads((ARTIFACTS / "resolution_metrics.json").read_text(encoding="utf-8"))
    for target in (800, 1200, 1600):
        row = metrics["runs"][str(target)]
        assert row["actualWorkingSize"] == [target, target]
        assert row["segmentation"]["working_size"] == [target, target]
        assert row["segmentation"]["data_contract_valid"] is True
        assert row["geometry"]["topologyValid"] is True
        assert row["geometry"]["geometryValid"] is True
        assert row["geometry"]["embeddedRasterCount"] == 0
        assert (ARTIFACTS / f"resolution_{target}.svg").is_file()


def test_local_candidate_is_source_based_and_topology_valid() -> None:
    metrics = json.loads((ARTIFACTS / "local_refinement_metrics.json").read_text(encoding="utf-8"))
    assert metrics["activeFoxCoordinatesOrSemanticsUsedForSelection"] is False
    assert metrics["candidateVertexUpdateCount"] > 0
    assert metrics["acceptedVertexUpdateCount"] > 0
    assert metrics["geometryValidation"]["valid"] is True
    assert metrics["geometryValidation"]["selfIntersectionCount"] == 0
    assert metrics["geometryValidation"]["sharedBoundaryMismatchCount"] == 0
    assert metrics["candidate"]["svg"]["embeddedRasterCount"] == 0
    assert (ARTIFACTS / "local_refined_candidate.svg").is_file()


def test_roi_refinement_updates_a_shared_canonical_vertex_once() -> None:
    vertices = [
        TopologyVertex(0, (0, 0), (0.0, 0.0), (0,), 2, False),
        TopologyVertex(1, (10, 10), (10.0, 10.0), (0, 1), 2, False),
        TopologyVertex(2, (20, 0), (20.0, 0.0), (0,), 2, False),
        TopologyVertex(3, (0, 20), (0.0, 20.0), (1,), 2, False),
        TopologyVertex(4, (20, 20), (20.0, 20.0), (1,), 2, False),
    ]
    graph = _Graph(vertices, [_Interface(0, (0, 1, 2)), _Interface(1, (3, 1, 4))], (1.0, 1.0))
    blank = [None, {"offsetWorkingPx": 0.2, "edgeStrength": 0.8,
                    "persistence": 0.9, "normalSource": [1.0, 0.0]}, None]
    profiles = [{"interfaceId": 0, "perVertex": blank},
                {"interfaceId": 1, "perVertex": blank}]
    selection = {"selectedInterfaceIds": [0, 1], "profiles": profiles,
                 "rois": [{"interfaceIds": [0], "box": [0, 0, 10, 10]},
                          {"interfaceIds": [1], "box": [10, 0, 20, 10]}]}
    updates = build_vertex_updates(graph, selection)
    candidate, ledger = apply_updates_by_roi(graph, selection, updates)
    assert set(updates) == {1}
    assert candidate.vertices[1].processing_xy == (10.2, 10.0)
    assert candidate.interfaces[0].vertex_ids[1] == candidate.interfaces[1].vertex_ids[1] == 1
    assert sum(row["updatedVertexCount"] for row in ledger) == 1
    assert graph.vertices[1].processing_xy == (10, 10)


def test_roi_rollback_restores_only_the_rejected_group() -> None:
    vertices = [
        TopologyVertex(0, (0, 0), (0.0, 0.0), (0,), 2, False),
        TopologyVertex(1, (10, 10), (10.0, 10.0), (0,), 2, False),
        TopologyVertex(2, (20, 0), (20.0, 0.0), (0,), 2, False),
        TopologyVertex(3, (0, 20), (0.0, 20.0), (1,), 2, False),
        TopologyVertex(4, (10, 30), (10.0, 30.0), (1,), 2, False),
        TopologyVertex(5, (20, 20), (20.0, 20.0), (1,), 2, False),
    ]
    graph = _Graph(vertices, [_Interface(0, (0, 1, 2)), _Interface(1, (3, 4, 5))], (1.0, 1.0))
    selection = {"selectedInterfaceIds": [0, 1], "profiles": [],
                 "rois": [{"interfaceIds": [0], "box": [0, 0, 10, 10]},
                          {"interfaceIds": [1], "box": [10, 20, 20, 30]}]}
    candidate, _ = apply_updates_by_roi(graph, selection, {1: (0.25, 0.0), 4: (0.35, 0.0)})
    rolled_back, restored = rollback_roi_group(candidate, graph, selection, [0], 1)
    assert restored == 3
    assert rolled_back.vertices[1].processing_xy == (10.25, 10.0)
    assert rolled_back.vertices[4].processing_xy == (10, 30)
    assert graph.vertices[1].processing_xy == (10, 10)


def test_synthetic_validation_has_predeclared_heldout_fixtures() -> None:
    result = json.loads((ARTIFACTS / "synthetic_analytical_validation.json").read_text(encoding="utf-8"))
    heldout = json.loads((ARTIFACTS / "heldout_validation.json").read_text(encoding="utf-8"))
    assert result["fixtureCount"] == 18
    assert result["splitWasDeclaredBeforeEvaluation"] is True
    assert len(heldout["fixtures"]) == 4
    assert heldout["independentRealWorldFixtures"] == 0


def test_task_07_2_does_not_mutate_production_contour_or_smart_modules() -> None:
    manifest = json.loads((ARTIFACTS / "baseline_manifest.json").read_text(encoding="utf-8"))
    import hashlib
    for relative, expected in manifest["files"].items():
        if not relative.startswith("backend/"):
            continue
        current = (ROOT / relative).read_bytes()
        # The Contour Bézier module has had approved geometry changes since this
        # Task 07.2 snapshot. Pin it to the accepted Task 08B.0.3 source hash;
        # its focused regression also checks that change against the task-start
        # reconstruction, while the remainder stays under the Task 07.2 hashes.
        if relative == "backend/mediastudio/image_tools/vectorization_contour/bezier.py":
            task08b03 = json.loads((ROOT / "backend" / "artifacts" /
                                    "contour_preserving" / "task_08b_0_3" /
                                    "production_changes.json").read_text(encoding="utf-8"))
            assert hashlib.sha256(current).hexdigest() == task08b03[
                "bezierSource"]["postTask08B03Sha256"]
            continue
        # Task 08B.0.2 authorizes only the previously verified SVG canvas
        # dimension-order correction in these two integration call sites.
        # Normalize those exact tuple edits back to the frozen Task 07.2 form,
        # then keep verifying the complete remainder against the untouched hash.
        if relative == "backend/mediastudio/image_tools/vectorization_v2/production.py":
            text = current.decode("utf-8")
            assert text.count("expected_size=(width, height)") == 1
            current = text.replace("expected_size=(width, height)",
                                   "expected_size=(height, width)").encode("utf-8")
        elif relative == "backend/mediastudio/image_tools/contour_backend.py":
            text = current.decode("utf-8")
            assert text.count("expected_size=(source_width, source_height)") == 2
            current = text.replace("expected_size=(source_width, source_height)",
                                   "expected_size=(source_height, source_width)").encode("utf-8")
        assert hashlib.sha256(current).hexdigest() == expected["sha256"]
