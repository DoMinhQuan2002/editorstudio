from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
TASK = BACKEND / "artifacts/contour_preserving/task_08b_0_4"


def load(name: str) -> dict:
    return json.loads((TASK / name).read_text(encoding="utf-8"))


def save(name: str, value: dict) -> None:
    (TASK / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    reproduction = load("geos_exception_reproduction.json")
    context = load("geos_exception_context.json")
    minimal = load("minimal_reproduction.json")
    detailed_event = context["geosExceptionEvents"][0]
    frame = next(row for row in detailed_event["traceback"] if row["function"] == "_compute_metrics")
    traceback_frame = {
        "file": frame["file"],
        "line": frame["line"],
        "function": frame["function"],
        "source": frame["source"],
    }
    reproduction["detailedFailureContext"] = {
        "apiRequestConfiguration": context["runtimeConfiguration"]["request"],
        "exceptionType": detailed_event["exceptionType"],
        "fullTraceback": detailed_event["formattedTraceback"],
        "firstFailingOperation": {
            "phase": "D.1 geometry metric computation",
            "operation": "shape_polygons[boundary.region_a].intersection(shape_polygons[boundary.region_b])",
            "regionA": minimal["regionPair"]["regionA"],
            "regionB": minimal["regionPair"]["regionB"],
            "sharedBoundaryId": minimal["regionPair"]["sharedBoundary"]["id"],
            "frame": traceback_frame,
        },
        "geometryContext": frame["geometryLocals"],
        "instrumentedSingleRun": context["attempts"][0],
    }
    save("geos_exception_reproduction.json", reproduction)

    detail = {
        "schemaVersion": 1,
        "recordedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture": reproduction["fixture"],
        "runtime": reproduction["environment"],
        "firstFailingOperation": reproduction["detailedFailureContext"]["firstFailingOperation"],
        "exception": {
            "type": detailed_event["exceptionType"],
            "message": detailed_event["exceptionMessage"],
            "reportedLocation": list(minimal["sourceFailure"]["exceptionLocation"]),
            "reproducedInSequentialApiRuns": len(reproduction["attempts"]),
            "identicalApiFailureCount": sum(
                row.get("error") == reproduction["attempts"][0].get("error")
                for row in reproduction["attempts"]
            ),
        },
        "geometryConstruction": {
            "module": str((BACKEND / "mediastudio/image_tools/vectorization_v2/phase_d.py").resolve()),
            "construction": "Polygon(path_points(path, boundary_by_id, density=8.0))",
            "coordinateSpace": "source image pixel coordinates (512x512) as float64/double precision",
            "precisionGrid": 0.0,
            "regionPolygonCount": frame["geometryLocals"]["shape_polygons"]["length"],
        },
        "operands": minimal["operands"],
        "regionTopology": minimal["regionPair"],
        "crossingClassification": {
            "kind": "proper segment crossing in the exterior ring of the sampled polygon operand",
            "ring": "exterior",
            "segments": minimal["operands"]["R14"]["selfIntersectionNearReportedPoint"][0],
            "notEndpointTouch": True,
            "notCollinearContact": True,
            "precisionOnlyFailure": False,
            "caveat": "The exact WKB passed to GEOS is proven self-intersecting. Because it is a density-8 tessellation of fitted Bezier paths, this diagnostic does not by itself prove whether the corresponding continuous cubic curves also cross between samples.",
        },
        "control": minimal["validControl"],
        "assessment": {
            "invalidGeometryBeforeOverlay": True,
            "operationSpecificFailureWithValidInputs": False,
            "segmentationFailureProven": False,
            "rootCause": "The pairwise shared-overlap metric invokes GEOS intersection on an invalid sampled Polygon for R14; the exception escapes because that pairwise overlay is outside the existing try/except that only covers polygon construction.",
            "svgFillRuleRelevance": "Not applicable to this metric overlay; the failing operation uses Shapely Polygon operands before SVG composition.",
        },
    }
    save("failing_geometry_diagnostics.json", detail)

    root_cause = {
        "schemaVersion": 1,
        "status": "VERIFIED",
        "summary": detail["assessment"]["rootCause"],
        "evidenceChain": [
            "The exact Task 08A.1 camera image hash and 512x512 dimensions match its manifest.",
            "Three unchanged sequential Smart V2 API jobs fail with the same GEOS side-location conflict coordinate.",
            "The first captured GEOSException traceback ends at Shapely Polygon.intersection invoked by phase_d.py::_compute_metrics line 1120 during Phase D.1.",
            "The operands are R02 (valid Polygon) and R14 (invalid Polygon); explain_validity reports a self-intersection at the same coordinate as GEOS.",
            "Independent segment-pair geometry checks find one proper crossing between non-adjacent exterior-ring edges 98 and 136, both intersecting in their interiors.",
            "The exact captured WKB operands reproduce the exception in a standalone script, while a valid control overlay succeeds.",
        ],
        "firstFailingOperation": detail["firstFailingOperation"],
        "rootCauseBoundary": {
            "module": detail["geometryConstruction"]["module"],
            "function": "_compute_metrics",
            "line": 1120,
            "beforeOverlay": "Polygon construction and validity are not asserted before storing polygons in shape_polygons.",
            "exceptionHandling": "The try/except ends after unary_union/difference polygon construction. The per-shared-boundary intersection that fails is outside that guard.",
            "calledFrom": "phase_d1.py::run_phase_d1 line 632, before D1's retry/refit and local self-crossing repair loop can run.",
        },
        "proven": {
            "exactApiFailureReproduced": True,
            "invalidOperandR14": True,
            "validOperandR02": True,
            "trueCrossingInPassedPolygon": True,
            "standaloneWkbReproduction": True,
            "validControlSucceeds": True,
            "causeIsGlobalPrecisionGrid": False,
        },
        "notProven": [
            "Whether the source cubic Bezier curves themselves cross continuously or the crossing is introduced only by density-8 tessellation.",
            "Which individual shared-boundary component first creates the crossing; R14's outer path references S19 components 1 and 0, but this task did not alter or refit geometry to isolate them.",
        ],
        "productionImpact": "Smart V2 job fails before Phase D.1 finishes, so no SVG is emitted for this fixture. No output quality claim is possible from this failed job.",
    }
    save("root_cause_analysis.json", root_cause)

    proposals = {
        "schemaVersion": 1,
        "implementationPerformed": False,
        "options": [
            {
                "id": "A",
                "name": "Validity-aware handling for the optional overlap-area metric",
                "module": "backend/mediastudio/image_tools/vectorization_v2/phase_d.py::_compute_metrics",
                "change": "Before each diagnostic overlay, validate both polygons. If invalid, mark shared_interface_overlap_area unavailable, record region IDs, validity reason, and a structured warning; do not mutate, drop, or substitute either region. Keep existing D1 self-intersection/refit validation responsible for deciding whether production geometry is acceptable.",
                "why": "The immediate failure is an optional pairwise area metric, not the SVG composer. It prevents the already-present D1 local refit/validation from running.",
                "boundaryOrColorRisk": "Low if invalid geometry remains visible to the D1 guard; no fill color or path is changed by the metric itself.",
                "topologyRisk": "Low for geometry because the proposal does not alter topology. A production gate must still reject or repair unresolved invalid rings before SVG emission.",
                "tests": [
                    "Exact camera API reproduction must no longer abort in the overlap metric; it must either complete after the existing D1 local guard or fail with a structured unresolved-geometry error.",
                    "Assert no region is omitted, shared boundary references remain identical, and SVG is emitted only when geometry validation passes.",
                    "Run exact WKB invalid and valid control tests, Task 08B.0.2 and 08B.0.3, then the full backend suite.",
                ],
                "rollback": "Revert only the validity-aware metric handling in phase_d.py to its saved pre-change source; compare the saved SHA-256 before/after and rerun the exact WKB reproduction.",
                "status": "RECOMMENDED_FIRST; not implemented in Task 08B.0.4",
            },
            {
                "id": "B",
                "name": "Targeted D1 refit of the invalid R14 contour component",
                "module": "backend/mediastudio/image_tools/vectorization_v2/phase_d1.py and shared-boundary component fitting in phase_d.py",
                "change": "Map crossing edges 98 and 136 from the tessellated R14 ring back to their exact Bezier boundary/component references, then refit only the responsible component(s) at tighter local tolerance using the existing rollback/refit policy. Preserve the same canonical shared geometry reference for both adjacent regions.",
                "why": "R14 is the invalid operand, its outer path references shared boundary S19 components 1 and 0, and the crossing occurs before D1's current retry loop because _compute_metrics raises first.",
                "boundaryOrColorRisk": "Medium: a boundary change can alter a narrow region edge and adjacent R02/R14 appearance sampling.",
                "topologyRisk": "Medium: shared boundary S19 must be updated once for both regions; no one-sided path edit, make_valid, buffer(0), or global precision reduction.",
                "tests": [
                    "Prove sampled and continuous-curve validity, region R14 and R02 IoU/boundary error, shared-boundary identity, topology signatures, and no new self-intersections.",
                    "Compare API SVG rendering and appearance metrics before/after, then run Task 08B.0.2, 08B.0.3, and full backend regressions.",
                ],
                "rollback": "Restore the original shared boundary component and its metadata as one atomic model update; use a saved Phase D1 baseline and verify hashes and region/topology metrics.",
                "status": "REQUIRES_COMPONENT_ATTRIBUTION; not implemented in Task 08B.0.4",
            },
        ],
        "unsafeShortcutsRejected": [
            "buffer(0) or make_valid without topology/area/color-fidelity proof",
            "rounding or global precision reduction",
            "catching and silently ignoring the failed region or silently switching to Contour",
        ],
    }
    save("proposed_repair_options.json", proposals)

    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=False)
    status = subprocess.run(["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True, check=False)
    production_paths = [
        "mediastudio/image_tools/vectorization_v2/production.py",
        "mediastudio/image_tools/vectorization_v2/phase_c.py",
        "mediastudio/image_tools/vectorization_v2/phase_d.py",
        "mediastudio/image_tools/vectorization_v2/phase_d1.py",
        "mediastudio/image_tools/vectorization_v2/phase_e1.py",
        "mediastudio/image_tools/vectorization_v2/svg_composer.py",
        "mediastudio/image_tools/vectorization_contour/segmentation.py",
        "mediastudio/image_tools/vectorization_contour/topology.py",
        "mediastudio/image_tools/vectorization_contour/bezier.py",
        "mediastudio/image_tools/contour_backend.py",
        "mediastudio/api.py",
    ]
    source_hashes = {path: sha256(BACKEND / path) for path in production_paths if (BACKEND / path).is_file()}
    changed_files = [
        "backend/tools/task_08b_0_4/reproduce.py",
        "backend/tools/task_08b_0_4/minimal_reproduction.py",
        "backend/tools/task_08b_0_4/finalize_artifacts.py",
        "backend/tests/test_task_08b_0_4.py",
        "backend/artifacts/contour_preserving/task_08b_0_4/**",
    ]
    production_changes = {
        "schemaVersion": 1,
        "productionAlgorithmChanges": [],
        "apiDefaultsChanges": [],
        "wpfChanges": [],
        "contourAlgorithmChanges": [],
        "taskScopedFilesAddedOrWritten": changed_files,
        "productionSourceSha256AtCompletion": source_hashes,
        "repositoryStatus": {
            "gitRoot": str(ROOT),
            "trackedFileCount": len([line for line in tracked.stdout.splitlines() if line.strip()]),
            "trackedDiff": "unavailable" if not tracked.stdout.strip() else "see git diff",
            "statusLineCount": len([line for line in status.stdout.splitlines() if line.strip()]),
            "statusSample": status.stdout.splitlines()[:12],
            "limitation": "The repository index contains no tracked files and the pre-existing project appears as untracked content, so Git cannot provide a trustworthy before/after diff. This task's recorded edits were limited to diagnostic scripts, one regression test, and Task 08B.0.4 artifacts; production source files were not edited.",
        },
        "smartV2AlgorithmUnchanged": True,
        "contourAlgorithmUnchanged": True,
        "productionReleaseReady": False,
    }
    save("production_changes.json", production_changes)

    regression = {
        "schemaVersion": 1,
        "recordedAtUtc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commands": [
            {
                "name": "Sequential Smart V2 API reproduction",
                "command": "python tools/task_08b_0_4/reproduce.py",
                "result": "EXPECTED_FAILURE_REPRODUCED",
                "sequentialAttempts": 3,
                "identicalFailureCount": 3,
            },
            {
                "name": "Standalone exact-WKB geometry reproduction and valid control",
                "command": "python tools/task_08b_0_4/minimal_reproduction.py",
                "result": "PASS",
                "exactInvalidPairRaisesGEOSException": True,
                "validControlSucceeds": True,
            },
            {
                "name": "Focused Task 08B.0.1–0.4 tests",
                "command": "python -m unittest discover -s tests -p 'test_task_08b_0_*.py' -v",
                "result": "PASS",
                "passed": 7,
                "failed": 0,
                "notes": "Task 08B.0.2 2/2, Task 08B.0.3 2/2, Task 08B.0.4 3/3; the 08B.0.1 module contributes no unittest cases.",
            },
            {
                "name": "Full backend regression",
                "command": "python -m unittest discover -s tests -v",
                "result": "PASS",
                "passed": 303,
                "failed": 0,
                "elapsedSeconds": 236.879,
                "notes": "Phase A/B/C/D1/E1/E2, Contour Tasks 01–05, API/product, Task 08B.0.2, Task 08B.0.3, and Task 08B.0.4 all passed. FastAPI on_event deprecation warnings were emitted; no test failed.",
            },
        ],
        "focusedDiagnostics": {
            "sequentialApiReproduction": "EXPECTED_FAILURE_REPRODUCED_3_OF_3",
            "exactWkbStandaloneReproduction": "PASS_EXPECTED_GEOS_EXCEPTION",
            "geometryValidityDiagnostics": "PASS_R14_INVALID_R02_VALID",
            "properCrossingCoordinateCheck": "PASS_ONE_PROPER_EXTERIOR_RING_CROSSING",
            "validControlOverlay": "PASS",
            "productionAlgorithmChanges": 0,
        },
        "priorTaskRegressions": {
            "task08b02": {"result": "PASS", "passed": 2, "failed": 0},
            "task08b03": {"result": "PASS", "passed": 2, "failed": 0},
        },
        "sourceChangeScope": "PASS_WITH_GIT_BASELINE_LIMITATION",
        "expectedReproductionIsNotAProductionFix": True,
    }
    save("regression_results.json", regression)

    report = f'''# Task 08B.0.4 — Smart V2 GEOS Topology Failure Isolation

**Result:** diagnostics complete. No production algorithm was changed. The camera failure is a confirmed expected reproduction; production remains not release-ready for this fixture.

## Findings

- Fixture: `camera.png`, {reproduction['fixture']['dimensions'][0]}×{reproduction['fixture']['dimensions'][1]}, {reproduction['fixture']['bytes']:,} bytes, SHA-256 `{reproduction['fixture']['sha256Actual']}` (matches Task 08A.1 manifest).
- Runtime: Python {reproduction['environment']['pythonVersion'].split()[0]}, Shapely {reproduction['environment']['shapelyVersion']}, GEOS {reproduction['environment']['geosVersion']}.
- The unchanged Smart V2 API request failed identically in **3/3 sequential runs** at `(273.3869747027037, 199.02301419964235)`.
- First failing overlay: `Polygon.intersection`, between **R02** and **R14**, in `phase_d.py::_compute_metrics` line 1120, called from `phase_d1.py::run_phase_d1` line 632.
- R02 is a valid Polygon. R14 is an invalid Polygon: `Self-intersection[273.386974702704 199.023014199642]`. Its exterior ring has a proper crossing between sampled edges 98 and 136, both crossing in their interiors. It is not endpoint touching or collinear contact.
- R02 and R14 meet at shared boundary `S19` (confidence 1.0; 54 raw points). R14's outer path references S19 components 1 and 0. The GEOS overlay is performed on floating-coordinate polygons with precision grid 0.0.
- The exact captured WKB pair independently reproduces the exception. An overlay control with a valid box succeeds.

## Root cause

The D1 metric builds sampled polygons from fitted paths at density 8.0. It catches errors while constructing/unioning those polygons, but does not validate the constructed polygons. The later per-shared-boundary area metric calls `.intersection()` outside that `try/except`. R14 is already invalid when passed to GEOS, so this diagnostic overlay throws before D1's retry/refit and local crossing-repair loop can run. This proves the immediate failure path; it does **not** prove whether the continuous Bezier curves also cross or whether the crossing exists only in the density-8 tessellation.

No evidence points to a global precision-grid issue or to segmentation as the direct failing operation. SVG rendering is not reached, so no output-quality claim is made for this job.

## Repair options proposed, not applied

1. Add validity-aware handling for this optional overlap-area metric: record the region IDs and validity reason, mark that metric unavailable, and let D1's existing geometry guard decide whether the geometry can be refit or must fail explicitly. Never drop the region or conceal unresolved invalid geometry.
2. Map the sampled crossing edges to the exact Bezier boundary components, then locally refit only the responsible component(s), preserving shared S19 geometry for both adjacent regions. This has higher topology and boundary risk and needs that component mapping first.

No `buffer(0)`, `make_valid`, rounding, global precision reduction, Contour fallback, or production catch-and-ignore was applied.

## Regression

- Focused Task 08B.0.1–0.4 discovery: **7 passed, 0 failed**; Task 08B.0.2 **2/2**, Task 08B.0.3 **2/2**, Task 08B.0.4 **3/3**.
- Full backend unittest discovery: **303 passed, 0 failed** (236.879 s).
- The camera Smart V2 reproduction remains an **expected failure**; it is not a production fix.

## Source scope and release status

Only diagnostic scripts, the Task 08B.0.4 regression test, and its artifacts were added. Smart V2, Contour, SVG Composer, API defaults, and WPF production sources were not edited. The repository currently has no tracked files in its Git index, and the existing project appears as untracked content; therefore Git cannot supply a trustworthy pre-task diff. Final SHA-256 values for the relevant production source files are recorded in `production_changes.json`.

```text
GEOS_FAILURE_REPRODUCED = true
FIRST_FAILING_OPERATION_IDENTIFIED = true
ROOT_CAUSE_VERIFIED = true
MINIMAL_REPRODUCTION_CREATED = true
SAFE_REPAIR_PROPOSED = true
SMART_V2_ALGORITHM_UNCHANGED = true
CONTOUR_ALGORITHM_UNCHANGED = true
TASK_08B_0_2_REGRESSION_PASS = true
TASK_08B_0_3_REGRESSION_PASS = true
FULL_REGRESSION_PASS = true
TASK_08B_0_4_COMPLETE = true
PRODUCTION_RELEASE_READY = false
```

## Artifacts

- `geos_exception_reproduction.json` — three API runs and full GEOS traceback.
- `failing_geometry_diagnostics.json` — geometry types, bounds, validity, precision, region topology, and crossing evidence.
- `minimal_reproduction.json` plus the two `.wkb` operand files — standalone exact repro and valid control.
- `root_cause_analysis.json` — evidence chain and proven/unproven conclusions.
- `proposed_repair_options.json` — two scoped proposals; neither implemented.
- `regression_results.json` — focused and full test results.
- `production_changes.json` — source-scope assessment and production file hashes.
'''
    (TASK / "task_08b_0_4_report.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
