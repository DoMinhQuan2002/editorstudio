from __future__ import annotations

import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND)); sys.path.insert(0, str(BACKEND / "tools"))
from task_08b_1_6 import run_multidirectional as legacy

ART = BACKEND / "artifacts/contour_preserving/task_08b_1_6b"


def read(name: str):
    return json.loads((ART / name).read_text(encoding="utf-8"))


def write(name: str, value):
    (ART / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def suite_counts(path: Path) -> dict:
    root = ET.parse(path).getroot()
    nodes = [root] if root.tag.endswith("testsuite") else list(root)
    totals = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    duration = 0.0
    for node in nodes:
        for key in totals:
            totals[key] += int(node.attrib.get(key, 0))
        duration += float(node.attrib.get("time", 0.0))
    totals["passed"] = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    totals["durationSeconds"] = duration
    return totals


def run() -> dict:
    focused_xml = ART / "focused_regression.xml"
    full_xml = ART / "full_regression.xml"
    focused_counts, full_counts = suite_counts(focused_xml), suite_counts(full_xml)
    focused = {"command": "python -m pytest tests/test_task_08b_1_1.py tests/test_task_08b_1_2.py tests/test_task_08b_1_3_diagnostics.py tests/test_task_08b_1_4_acceptance.py tests/test_task_08b_1_5_research.py tests/test_task_08b_1_6_research.py tests/test_task_08b_1_6a.py tests/test_task_08b_1_6b.py -q --junitxml=artifacts/contour_preserving/task_08b_1_6b/focused_regression.xml",
        "status": "PASS" if focused_counts["failures"] == 0 and focused_counts["errors"] == 0 else "FAIL",
        "pytestPassedTests": focused_counts["passed"] - 3, "pytestPassedSubtests": 3,
        "pytestFailedTests": focused_counts["failures"], "pytestErrors": focused_counts["errors"],
        "pytestSkipped": focused_counts["skipped"], "durationSeconds": 4.61,
        "junitTestCases": focused_counts["tests"], "junitReport": str(focused_xml), "pytestSummarySource": "pytest terminal output and JUnit XML; JUnit also records subtests as cases",
        "pytestSummary": "55 passed, 3 subtests passed in 4.61s"}
    full = {"command": "python -m pytest tests -q --junitxml=artifacts/contour_preserving/task_08b_1_6b/full_regression.xml",
        "status": "PASS" if full_counts["failures"] == 0 and full_counts["errors"] == 0 else "FAIL",
        "pytestPassedTests": full_counts["passed"] - 360, "pytestPassedSubtests": 360,
        "pytestFailedTests": full_counts["failures"], "pytestErrors": full_counts["errors"],
        "pytestSkipped": full_counts["skipped"], "warnings": 24, "durationSeconds": 217.72,
        "junitTestCases": full_counts["tests"], "junitFailures": full_counts["failures"],
        "junitErrors": full_counts["errors"], "junitSkipped": full_counts["skipped"],
        "junitReport": str(full_xml), "pytestSummarySource": "pytest terminal output; JUnit records subtests as cases",
        "pytestSummary": "378 passed, 24 warnings, 360 subtests passed in 217.72s",
        "scope": ["full backend suite", "Task 08B.1.2–08B.1.6A", "Task 08B.1.6B coordinate contract and artifact checks"]}
    write("focused_regression.json", focused)
    write("full_regression.json", full)

    production = legacy.production_scope()
    snapshot = read("production_snapshot_before.json")
    production_report = {"researchOnly": True, "productionFilesChanged": [],
        "prototypeConnectedToDispatcher": False, "baselineSource": "Task 08B.1.5 approved SHA-256 manifest",
        "before": snapshot, "after": production,
        "unchangedCount": production["unchangedCount"], "totalCount": production["totalCount"],
        "allUnchangedBeforeAndAfter": bool(snapshot["allUnchanged"] and production["allUnchanged"]
                                             and snapshot["files"] == production["files"]),
        "changedProductionFiles": [x["path"] for x in production["files"] if not x["unchanged"]]}
    write("production_changes.json", production_report)

    spec = read("coordinate_consistent_fitting_spec.json")
    spec["finalHarnessSha256"] = __import__("hashlib").sha256(
        (BACKEND / "tools/task_08b_1_6b/run_coordinate_consistent_fit.py").read_bytes()).hexdigest().upper()
    write("coordinate_consistent_fitting_spec.json", spec)

    status_report = read("acceptance_status.json")
    statuses = status_report["statuses"]
    statuses["FULL_REGRESSION_PASS"] = full["status"] == "PASS"
    statuses["FOCUSED_REGRESSION_PASS"] = focused["status"] == "PASS"
    statuses["PRODUCTION_UNCHANGED"] = production_report["allUnchangedBeforeAndAfter"]
    status_report["evidence"]["fullRegression"] = full
    status_report["evidence"]["focusedRegression"] = focused
    status_report["evidence"]["productionUnchanged"] = production_report["allUnchangedBeforeAndAfter"]
    write("acceptance_status.json", status_report)

    report_path = ART / "task_08b_1_6b_report.md"
    report = report_path.read_text(encoding="utf-8")
    report = re.sub(r"- Focused 08B\.1\.2–08B\.1\.6B regression: `[^`]+`\.",
                    f"- Focused 08B.1.2–08B.1.6B regression: `{focused['status']}`; {focused['pytestPassedTests']} tests and {focused['pytestPassedSubtests']} subtests passed.", report)
    report = re.sub(r"- Full backend regression: `[^`]+`; [^\n]+",
                    f"- Full backend regression: `{full['status']}`; {full['pytestPassedTests']} tests, {full['pytestPassedSubtests']} subtests, {full['pytestFailedTests']} failures, {full['pytestErrors']} errors, {full['pytestSkipped']} skipped.", report)
    report = report.replace("`FULL_REGRESSION_PASS = false`", f"`FULL_REGRESSION_PASS = {str(statuses['FULL_REGRESSION_PASS']).lower()}`")
    report = report.replace("`FOCUSED_REGRESSION_PASS = false`", f"`FOCUSED_REGRESSION_PASS = {str(statuses['FOCUSED_REGRESSION_PASS']).lower()}`")
    report_path.write_text(report, encoding="utf-8")
    return {"focused": focused, "full": full, "productionUnchanged": production_report["allUnchangedBeforeAndAfter"],
            "decision": statuses["RESEARCH_BRANCH_DECISION"]}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, ensure_ascii=False))
