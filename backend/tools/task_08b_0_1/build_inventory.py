from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any

BACKEND = Path(__file__).resolve().parents[2]
REPOSITORY = BACKEND.parent
TARGET = BACKEND / "artifacts" / "contour_preserving" / "task_08b_0_1"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build() -> dict[str, Any]:
    records = []
    exclusions = []
    task_specs = [
        ("08A", BACKEND / "artifacts" / "contour_preserving" / "task_08a" / "per_image_results.json"),
        ("08A.1", BACKEND / "artifacts" / "contour_preserving" / "task_08a_1" / "per_image_results.json"),
    ]
    for task, path in task_specs:
        data = read_json(path)
        for item in data.get("items", []):
            for engine_name, engine in item.get("engines", {}).items():
                if engine.get("status") != "FAILED":
                    continue
                code = engine.get("failureCode")
                reason = str(engine.get("failureReason") or "")
                is_visibility = (code in {"SVG_RENDER_EMPTY", "EMPTY_VISIBLE_SVG_OUTPUT"} or
                                 "không tạo được ảnh vector nhìn thấy" in reason.casefold() or
                                 "rendered the svg as empty" in reason.casefold() or
                                 "empty_visible_svg_output" in reason.casefold())
                row = {
                    "task": task, "imageId": item.get("imageId"), "sourceFamilyId": item.get("sourceFamilyId"),
                    "engine": engine_name, "jobStatus": engine.get("status"),
                    "originalFailureCode": code, "originalFailureReason": reason,
                    "sourcePath": item.get("sourcePath"), "sourceSha256": item.get("sourceSha256"),
                    "svgOutputPathAtOriginalRun": engine.get("svgPath"),
                    "svgSha256AtOriginalRun": engine.get("svgSha256"),
                    "visibilityFailure": is_visibility,
                }
                if is_visibility:
                    rerun_svg = TARGET / "reruns" / str(item["imageId"]) / engine_name / "output.svg"
                    row["reproduced"] = rerun_svg.is_file()
                    row["rerunSvgPath"] = str(rerun_svg) if rerun_svg.is_file() else None
                    row["rerunSvgSha256"] = hashlib.sha256(rerun_svg.read_bytes()).hexdigest() if rerun_svg.is_file() else None
                    records.append(row)
                else:
                    exclusions.append({**row, "exclusionReason": "Failure is recorded in prior benchmark but is outside SVG visibility scope."})
    unique_images = sorted({row["imageId"] for row in records})
    unique_families = sorted({row["sourceFamilyId"] for row in records})
    return {
        "schemaVersion": 1,
        "sources": [str(path) for _, path in task_specs],
        "countingNote": "Each engine failure is an independent benchmark record; the paired runs on the same source are grouped as one source-level case for root-cause deduplication.",
        "engineFailureRecordCount": len(records),
        "uniqueSourceImageCount": len(unique_images),
        "uniqueSourceFamilyCount": len(unique_families),
        "uniqueImageIds": unique_images,
        "uniqueSourceFamilyIds": unique_families,
        "priorNonVisibilityFailuresExcluded": exclusions,
        "items": records,
    }


def main() -> int:
    result = build()
    path = TARGET / "visibility_failure_inventory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"inventory: {result['engineFailureRecordCount']} engine failures; {result['uniqueSourceImageCount']} source images")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
