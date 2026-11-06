from __future__ import annotations

import csv
import logging
import re
import statistics
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mediastudio.video_editor.api import install_video_editor_api
from mediastudio.video_editor.media_selection import get_template_definition


STAGE_IDS = ("analyze_media", "apply_layout", "build_composition", "sync_audio", "prepare_preview")
TOKEN = "agent-prompt-benchmark"
STAGE_DURATION = re.compile(r"\((\d+(?:\.\d+)?)s\)$")
RENDERER = re.compile(r"renderer=([^ ]+)")


def _wait_for_job(client: TestClient, headers: dict[str, str], job_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 130
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/video/processing-jobs/{job_id}", headers=headers)
        response.raise_for_status()
        payload = response.json()
        if payload["jobStatus"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return payload
        time.sleep(0.05)
    raise TimeoutError(f"Processing job {job_id} did not finish within the benchmark window.")


def _stage_seconds(stages: list[dict[str, object]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for stage in stages:
        stage_id = str(stage["stageId"])
        duration = stage.get("durationSeconds")
        match = STAGE_DURATION.search(str(stage.get("message") or ""))
        if isinstance(duration, (int, float)):
            result[stage_id] = float(duration)
        elif match:
            result[stage_id] = float(match.group(1))
    missing = set(STAGE_IDS) - result.keys()
    if missing:
        raise ValueError(f"Processing job omitted stage timings: {sorted(missing)}")
    return result


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    output_directory = root / "artifacts" / "agent_prompt_verification"
    output_directory.mkdir(parents=True, exist_ok=True)
    image_path = root / "backend" / "tests" / "fixtures" / "active_fox.jpg"
    definition = get_template_definition("fall-diary")
    if definition is None:
        raise RuntimeError("Latest Fall Diary template definition is unavailable.")

    app = FastAPI()
    app.state.token = TOKEN
    captured_logs: list[str] = []

    class _CaptureLogs(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured_logs.append(record.getMessage())

    logger = logging.getLogger("mediastudio.video_editor")
    original_log_level = logger.level
    logger.setLevel(logging.INFO)
    log_capture = _CaptureLogs()
    logger.addHandler(log_capture)
    with tempfile.TemporaryDirectory(prefix="mediastudio_processing_benchmark_") as data_directory:
        install_video_editor_api(app, Path(data_directory))
        toolchain = app.state.video_ffmpeg
        if not toolchain.ffmpeg or not toolchain.ffprobe:
            raise RuntimeError("FFmpeg and FFprobe are required for the real preview benchmark.")
        headers = {"X-Media-Studio-Token": TOKEN}
        rows: list[dict[str, object]] = []

        with TestClient(app) as client:
            with image_path.open("rb") as source:
                imported = client.post(
                    "/api/v1/video/media", headers=headers,
                    files={"file": (image_path.name, source)},
                )
            imported.raise_for_status()
            asset_id = str(imported.json()["assetId"])
            bindings = {slot.slot_id: asset_id for slot in definition.slots}

            for run_number in range(1, 6):
                request = {
                    "templateId": definition.template_id,
                    "templateDefinitionVersion": definition.version,
                    "selectionSessionId": uuid4().hex,
                    "bindings": bindings,
                }
                started_at = time.perf_counter()
                started = client.post("/api/v1/video/processing-jobs", headers=headers, json=request)
                started.raise_for_status()
                finished = _wait_for_job(client, headers, str(started.json()["jobId"]))
                wall_seconds = time.perf_counter() - started_at
                if finished["jobStatus"] != "SUCCEEDED":
                    raise RuntimeError(f"Fall Diary processing run {run_number} failed: {finished}")
                stage_seconds = _stage_seconds(finished["stages"])
                job_id = str(finished["jobId"])
                renderer_log = next((message for message in reversed(captured_logs)
                                     if f"template_processing.preview_renderer job_id={job_id} " in message), "")
                renderer_match = RENDERER.search(renderer_log)
                if renderer_match is None:
                    raise ValueError(f"Processing run {run_number} did not log its preview renderer.")
                rows.append({
                    "run": run_number,
                    "status": finished["jobStatus"],
                    "wall_seconds": round(wall_seconds, 3),
                    "renderer": renderer_match.group(1),
                    **{stage: stage_seconds[stage] for stage in STAGE_IDS},
                })
    logger.removeHandler(log_capture)
    logger.setLevel(original_log_level)

    csv_path = output_directory / "processing_benchmark.csv"
    fieldnames = ["run", "status", "wall_seconds", "renderer", *STAGE_IDS]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    total_values = [float(row["wall_seconds"]) for row in rows]
    stage_means = {
        stage: statistics.mean(float(row[stage]) for row in rows)
        for stage in STAGE_IDS
    }
    report_path = output_directory / "processing_benchmark.md"
    lines = [
        "# Fall Diary Processing Benchmark",
        "",
        "Five real processing jobs used the latest Fall Diary definition, 11 image bindings "
        "pointing to the same local test fixture, and the installed FFmpeg preview renderer.",
        "The measured wall time starts when the processing request is submitted and stops "
        "when the job reaches a terminal state.",
        "",
        "| Run | Status | Renderer | Total wall (s) | Analyze (s) | Layout (s) | Composition (s) | Audio (s) | Preview (s) |",
        "|---:|:---|:---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['run']} | {row['status']} | {row['renderer']} | {row['wall_seconds']:.3f} | "
            f"{row['analyze_media']:.3f} | {row['apply_layout']:.3f} | "
            f"{row['build_composition']:.3f} | {row['sync_audio']:.3f} | {row['prepare_preview']:.3f} |"
        )
    lines.extend([
        "",
        f"Mean total wall time: **{statistics.mean(total_values):.3f}s**; "
        f"maximum: **{max(total_values):.3f}s**.",
        "Mean stage durations (based on API stage instrumentation): "
        + ", ".join(f"{stage} {seconds:.3f}s" for stage, seconds in stage_means.items()) + ".",
        "",
        "Targets: the prompt cites 16s as the reference and <20s as the acceptance target. "
        "The current project checkout has no recorded pre-change Git baseline, so this report "
        "does not claim a before/after speedup.",
        "",
        f"CSV: `{csv_path.name}`.",
    ])
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(report_path)
    print(csv_path)
    print(f"mean={statistics.mean(total_values):.3f}s max={max(total_values):.3f}s")


if __name__ == "__main__":
    main()
