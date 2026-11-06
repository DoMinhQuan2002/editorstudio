from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

BACKEND = Path(__file__).resolve().parents[2]
TARGET = BACKEND / "artifacts" / "contour_preserving" / "task_08b_0_1"
sys.path.insert(0, str(BACKEND))
from tools.task_08a_1.dataset import write_json  # noqa: E402
from tools.task_08a_1.runner import snapshots  # noqa: E402


def _run(name: str, args: list[str]) -> dict:
    command = [sys.executable, *args]
    started = time.perf_counter()
    process = subprocess.run(command, cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {"name": name, "command": command, "returnCode": process.returncode,
            "status": "PASS" if process.returncode == 0 else "FAIL",
            "durationSeconds": round(time.perf_counter() - started, 3),
            "stdout": process.stdout, "stderr": process.stderr}


def main() -> int:
    TARGET.mkdir(parents=True, exist_ok=True)
    before = snapshots()
    if (TARGET / "production_hashes_before.json").is_file():
        before = json.loads((TARGET / "production_hashes_before.json").read_text(encoding="utf-8"))
    focused = _run("focused_benchmark_and_visibility", ["-m", "pytest", "-q",
                  "tests/test_vectorization_benchmark.py", "tests/test_task_08a_1.py", "tests/test_task_08b_0_1.py"])
    write_json(TARGET / "full_regression.json", {"schemaVersion": 1, "startedAtUtc": datetime.now(timezone.utc).isoformat(),
        "focused": focused, "fullBackend": {"status": "NOT_RUN"},
        "productionSourceSha256Before": before, "productionSourceSha256After": snapshots()})
    full = _run("full_backend", ["-m", "pytest", "-q", "tests"])
    after = snapshots()
    result = {"schemaVersion": 1, "finishedAtUtc": datetime.now(timezone.utc).isoformat(),
              "focused": focused, "fullBackend": full,
              "productionSourceSha256Before": before, "productionSourceSha256After": after,
              "productionSourcesUnchanged": before == after,
              "overallStatus": "PASS" if focused["status"] == "PASS" and full["status"] == "PASS" and before == after else "FAIL"}
    write_json(TARGET / "full_regression.json", result)
    print(json.dumps({"focused": focused["status"], "fullBackend": full["status"],
                      "productionSourcesUnchanged": before == after,
                      "focusedDurationSeconds": focused["durationSeconds"],
                      "fullDurationSeconds": full["durationSeconds"],
                      "fullStdoutTail": full["stdout"][-1500:], "fullStderrTail": full["stderr"][-1000:]}, ensure_ascii=False, indent=2))
    return 0 if result["overallStatus"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
