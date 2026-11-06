from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import traceback

import shapely
from shapely import from_wkb, get_precision
from shapely.errors import GEOSException
from shapely.geometry import box
from shapely.validation import explain_validity

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
ARTIFACTS = BACKEND / "artifacts/contour_preserving/task_08b_0_4"
REPRO = ARTIFACTS / "geos_exception_context.json"
TARGET = (273.3869747027037, 199.02301419964235)


def cross(a: tuple[float, float], b: tuple[float, float]) -> float:
    return a[0] * b[1] - a[1] * b[0]


def segment_intersection(a, b, c, d, tolerance: float = 1e-9):
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    denominator = cross(r, s)
    if abs(denominator) <= tolerance:
        return None
    qmp = (c[0] - a[0], c[1] - a[1])
    t = cross(qmp, s) / denominator
    u = cross(qmp, r) / denominator
    if -tolerance <= t <= 1 + tolerance and -tolerance <= u <= 1 + tolerance:
        return (a[0] + t * r[0], a[1] + t * r[1]), t, u
    return None


def self_crossings(geometry) -> list[dict]:
    crossings = []
    rings = [("exterior", geometry.exterior),
             *((f"interior_{index}", ring) for index, ring in enumerate(geometry.interiors))]
    for ring_name, ring in rings:
        points = [(float(x), float(y)) for x, y, *_ in ring.coords]
        edge_count = len(points) - 1
        for first in range(edge_count):
            a, b = points[first], points[first + 1]
            for second in range(first + 2, edge_count):
                if first == 0 and second == edge_count - 1:
                    continue
                c, d = points[second], points[second + 1]
                hit = segment_intersection(a, b, c, d)
                if hit is None:
                    continue
                point, t, u = hit
                distance = ((point[0] - TARGET[0]) ** 2 + (point[1] - TARGET[1]) ** 2) ** 0.5
                if distance <= 1e-4:
                    va = (b[0] - a[0], b[1] - a[1])
                    vb = (d[0] - c[0], d[1] - c[1])
                    angle = abs(__import__("math").degrees(__import__("math").atan2(cross(va, vb), va[0] * vb[0] + va[1] * vb[1])))
                    crossings.append({
                        "ring": ring_name,
                        "edgeIndexA": first,
                        "edgeIndexB": second,
                        "edgeA": [list(a), list(b)],
                        "edgeB": [list(c), list(d)],
                        "intersection": list(point),
                        "parameterA": t,
                        "parameterB": u,
                        "intersectionAngleDegrees": angle,
                        "interiorToBothSegments": 1e-7 < t < 1 - 1e-7 and 1e-7 < u < 1 - 1e-7,
                    })
    return crossings


def geometry_summary(geometry, wkb: bytes) -> dict:
    return {
        "type": geometry.geom_type,
        "bounds": list(geometry.bounds),
        "area": float(geometry.area),
        "length": float(geometry.length),
        "isValid": bool(geometry.is_valid),
        "validityReason": explain_validity(geometry),
        "coordinatePrecisionGrid": float(get_precision(geometry)),
        "coordinateCount": int(sum(len(ring.coords) for ring in [geometry.exterior, *geometry.interiors])),
        "wkbSha256": hashlib.sha256(wkb).hexdigest(),
        "wkbBytes": len(wkb),
    }


def main() -> int:
    reproduction = json.loads(REPRO.read_text(encoding="utf-8"))
    first_event = reproduction["geosExceptionEvents"][0]
    metric_frame = next(row for row in first_event["traceback"] if row["function"] == "_compute_metrics")
    targets = metric_frame["geometryLocals"]["shape_polygons"]["targetRegionPolygons"]
    operand_a = targets["2"]
    operand_b = targets["14"]
    a_path = ARTIFACTS / operand_a["wkbPath"]
    b_path = ARTIFACTS / operand_b["wkbPath"]
    a_wkb, b_wkb = a_path.read_bytes(), b_path.read_bytes()
    a, b = from_wkb(a_wkb), from_wkb(b_wkb)
    failure: dict = {"reproduced": False}
    try:
        a.intersection(b)
    except GEOSException as error:
        failure = {
            "reproduced": True,
            "exceptionType": f"{type(error).__module__}.{type(error).__name__}",
            "exceptionMessage": str(error),
            "formattedTraceback": "".join(traceback.format_exception(type(error), error, error.__traceback__)),
        }
    else:
        failure["unexpectedResult"] = "Exact operands did not raise GEOSException in standalone reproduction."

    control = box(272.5, 198.5, 274.5, 200.5)
    control_result = a.intersection(control)
    model_context = metric_frame["geometryLocals"]["model"]
    boundary_context = metric_frame["geometryLocals"]["boundary"]
    output = {
        "schemaVersion": 1,
        "task": "08B.0.4",
        "operation": "Polygon.intersection(R02, R14)",
        "sourceFailure": {
            "exceptionMessage": first_event["exceptionMessage"],
            "exceptionLocation": TARGET,
            "pythonOperationFrame": {
                "file": next(row["file"] for row in first_event["traceback"] if row["function"] == "_compute_metrics"),
                "line": next(row["line"] for row in first_event["traceback"] if row["function"] == "_compute_metrics"),
                "source": next(row["source"] for row in first_event["traceback"] if row["function"] == "_compute_metrics"),
            },
        },
        "regionPair": {
            "regionA": 2,
            "regionB": 14,
            "sharedBoundary": boundary_context,
            "regionShapes": model_context["targetShapes"],
        },
        "operands": {
            "R02": {**geometry_summary(a, a_wkb), "wkbPath": str(a_path.resolve())},
            "R14": {**geometry_summary(b, b_wkb), "wkbPath": str(b_path.resolve()),
                    "selfIntersectionNearReportedPoint": self_crossings(b)},
        },
        "minimalReproduction": {
            "exactCameraPipelineWkbOperands": True,
            "onlyOperationRequired": "R02.intersection(R14)",
            "result": failure,
        },
        "validControl": {
            "operation": "R02.intersection(valid box(272.5, 198.5, 274.5, 200.5))",
            "controlIsValid": bool(control.is_valid),
            "succeeded": bool(control_result.is_valid),
            "resultType": control_result.geom_type,
            "resultArea": float(control_result.area),
            "exception": None,
        },
        "runtime": {
            "shapelyVersion": shapely.__version__,
            "geosVersion": shapely.geos_version_string,
            "geosCapiVersion": shapely.geos_capi_version_string,
        },
    }
    destination = ARTIFACTS / "minimal_reproduction.json"
    destination.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "artifact": str(destination.resolve()),
        "reproduced": failure["reproduced"],
        "validityReason": explain_validity(b),
        "crossingsNearGEOSPoint": len(output["operands"]["R14"]["selfIntersectionNearReportedPoint"]),
        "validControlPassed": output["validControl"]["succeeded"],
    }, ensure_ascii=True))
    return 0 if failure["reproduced"] and output["validControl"]["succeeded"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
