from __future__ import annotations

import json
import os
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from tools.vectorization_benchmark.dataset import MANIFEST_PATH, write_json  # noqa: E402
from tools.vectorization_benchmark.worker import run_image  # noqa: E402


ARTIFACTS = BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_2"
TARGET_IDS = {
    "synthetic-radial_gradient",
    "synthetic-linear_gradient",
    "synthetic-circle",
    "synthetic-multiregion_illustration",
    "active-fox-native-jpeg",
}


def main() -> None:
    os.environ["MEDIASTUDIO_CONTOUR_EXPERIMENTAL"] = "1"
    os.environ["MEDIASTUDIO_VECTORIZE_PIPELINE"] = "v2"
    os.environ["DEBUG_VECTOR"] = "0"
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    items = [item for item in manifest["items"] if item["imageId"] in TARGET_IDS]
    found = {item["imageId"] for item in items}
    if found != TARGET_IDS:
        raise RuntimeError(f"Missing required fixture(s): {sorted(TARGET_IDS - found)}")
    for index, item in enumerate(items):
        item["benchmarkOrderIndex"] = index

    summary = []
    for item in items:
        print(f"API regression: {item['imageId']}", flush=True)
        result = run_image(item, ARTIFACTS, per_engine_timeout=240,
                           run_id="task08b1_2_api_nonreg")
        summary.append({
            "imageId": item["imageId"],
            "sourceSha256": item["sha256"],
            "status": result.get("status"),
            "smart": result.get("engines", {}).get("smart_reconstruction"),
            "contour": result.get("engines", {}).get("contour_preserving"),
        })
        print(json.dumps(summary[-1], ensure_ascii=False)[:1200], flush=True)

    write_json(ARTIFACTS / "api_nonreg_summary.json", {
        "requiredFixtures": sorted(TARGET_IDS),
        "actualFixtureOrder": [item["imageId"] for item in items],
        "results": summary,
        "all_succeeded": all(
            row["status"] == "PASS"
            and row["smart"].get("status") == "SUCCEEDED"
            and row["contour"].get("status") == "SUCCEEDED"
            for row in summary
        ),
        "note": "The API worker executes the production Smart V2 and Contour-Preserving routes. Contour is exercised as an unchanged control only.",
    })


if __name__ == "__main__":
    main()
