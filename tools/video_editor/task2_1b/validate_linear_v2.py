from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))
from mediastudio.video_editor.api import install_video_editor_api  # noqa: E402
from mediastudio.video_editor.storage import VideoProjectStore  # noqa: E402


TOKEN = "task2-1b-local-validation"
PROJECT_ID = uuid4().hex
SAMPLE_TIMES = [0.0, 2.9, 3.1, 5.9, 6.1, 8.9, 9.1, 11.9, 12.1, 14.9, 15.1, 20.0, 37.5]
AUDIO_SAMPLE_STARTS = [0.2, 5.0, 15.2, 36.5]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_app(data_directory: Path) -> FastAPI:
    app = FastAPI()
    app.state.token = TOKEN
    install_video_editor_api(app, data_directory)
    return app


def require_ok(response, what: str) -> dict:
    if response.status_code >= 400:
        raise RuntimeError(f"{what}: HTTP {response.status_code}: {response.text}")
    return response.json() if response.content else {}


def extract_frame(ffmpeg: str, file_path: Path, seconds: float) -> np.ndarray:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-v", "error", "-ss", f"{seconds:.3f}",
         "-i", str(file_path), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"],
        capture_output=True,
        check=False,
    )
    if result.returncode or not result.stdout:
        raise RuntimeError(f"Could not extract frame at {seconds}s: {result.stderr.decode(errors='replace')}")
    import io
    return np.asarray(Image.open(io.BytesIO(result.stdout)).convert("RGB"), dtype=np.float32)


def extract_audio_window(ffmpeg: str, file_path: Path, seconds: float) -> np.ndarray:
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-v", "error", "-ss", f"{seconds:.3f}", "-i", str(file_path),
         "-t", "0.4", "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "48000",
         "-f", "f32le", "pipe:1"], capture_output=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Could not extract audio at {seconds}s: {result.stderr.decode(errors='replace')}")
    return np.frombuffer(result.stdout, dtype="<f4")


def compare_frames(ffmpeg: str, baseline: Path, candidate: Path) -> list[dict[str, float]]:
    rows = []
    for seconds in SAMPLE_TIMES:
        first = extract_frame(ffmpeg, baseline, seconds)
        second = extract_frame(ffmpeg, candidate, seconds)
        if first.shape != second.shape:
            raise RuntimeError(f"Frame dimensions differ at {seconds}s: {first.shape} vs {second.shape}")
        mae = float(np.mean(np.abs(first - second)))
        rmse = float(np.sqrt(np.mean(np.square(first - second))))
        psnr = None if rmse == 0 else 20 * math.log10(255.0 / rmse)
        rows.append({"timeSeconds": seconds, "maeRgb": mae, "psnrDb": psnr,
                     "pixelIdentical": rmse == 0})
    return rows


def compare_audio(ffmpeg: str, baseline: Path, candidate: Path) -> list[dict[str, float | None]]:
    rows = []
    for seconds in AUDIO_SAMPLE_STARTS:
        first = extract_audio_window(ffmpeg, baseline, seconds)
        second = extract_audio_window(ffmpeg, candidate, seconds)
        count = min(first.size, second.size)
        first, second = first[:count], second[:count]
        if count == 0:
            raise RuntimeError(f"No audio samples at {seconds}s")
        first_centered = first - float(first.mean())
        second_centered = second - float(second.mean())
        denominator = float(np.linalg.norm(first_centered) * np.linalg.norm(second_centered))
        correlation = None if denominator == 0 else float(np.dot(first_centered, second_centered) / denominator)
        rows.append({
            "startSeconds": seconds,
            "sampleCount": count,
            "baselineRms": float(np.sqrt(np.mean(np.square(first)))),
            "candidateRms": float(np.sqrt(np.mean(np.square(second)))),
            "correlation": correlation,
        })
    return rows


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("Usage: validate_linear_v2.py <isolated-data-dir> <baseline-mp4> <output-dir>")
    data_directory = Path(sys.argv[1]).resolve()
    baseline = Path(sys.argv[2]).resolve()
    output_directory = Path(sys.argv[3]).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    source_project_id = "3a257ef6868a4806a4bab01eaad8fe49"
    source_project_path = data_directory / "video_editor" / "projects" / f"{source_project_id}.json"
    if not source_project_path.is_file():
        raise SystemExit(f"V1 baseline project missing: {source_project_path}")
    if not baseline.is_file():
        raise SystemExit(f"Baseline export missing: {baseline}")

    v1_bytes = source_project_path.read_bytes()
    v1_payload = json.loads(v1_bytes)
    if "schemaVersion" in v1_payload:
        raise SystemExit("Source baseline copy is already V2; expected an isolated V1 project copy.")
    v1_payload["projectId"] = PROJECT_ID
    v1_payload["title"] = "Denim Story - Task 2.1B V2 Linear Validation"
    cloned_v1_path = source_project_path.with_name(f"{PROJECT_ID}.json")
    with cloned_v1_path.open("xb") as output:
        output.write(json.dumps(v1_payload, ensure_ascii=False, indent=2).encode("utf-8"))
    cloned_v1_bytes = cloned_v1_path.read_bytes()
    (output_directory / "before-v1.json").write_bytes(cloned_v1_bytes)
    project_hash = sha256(cloned_v1_bytes)

    headers = {"X-Media-Studio-Token": TOKEN}
    with TestClient(make_app(data_directory)) as client:
        migrated = require_ok(client.get(f"/api/v1/video/projects/{PROJECT_ID}", headers=headers), "V1 migration read")
        if migrated.get("schemaVersion") != 2:
            raise RuntimeError("Store did not migrate the isolated V1 project to schemaVersion 2.")
        (output_directory / "migrated-v2.json").write_text(
            json.dumps(migrated, ensure_ascii=False, indent=2), encoding="utf-8")
        backup_files = list(cloned_v1_path.parent.glob(f"{PROJECT_ID}.v1.*.bak"))
        backup_hashes = [sha256(path.read_bytes()) for path in backup_files]
        if project_hash not in backup_hashes:
            raise RuntimeError("V1 migration backup hash does not match the cloned source bytes.")
        saved = require_ok(client.put(f"/api/v1/video/projects/{PROJECT_ID}", json=migrated,
                                      headers=headers), "V2 API Save")
        (output_directory / "after-save.json").write_text(
            json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")

    with TestClient(make_app(data_directory)) as reopened_client:
        reopened = require_ok(reopened_client.get(f"/api/v1/video/projects/{PROJECT_ID}", headers=headers),
                              "independent API/store reopen")
        if reopened["revision"] != saved["revision"]:
            raise RuntimeError("Revision changed unexpectedly between Save and reopened store read.")
        if [(track["trackId"], track["layerOrder"], [clip["clipId"] for clip in track["clips"]])
                for track in reopened["tracks"]] != [
                (track["trackId"], track["layerOrder"], [clip["clipId"] for clip in track["clips"]])
                for track in saved["tracks"]]:
            raise RuntimeError("Track IDs, order, or clip IDs changed after independent reopen.")
        (output_directory / "after-reopen.json").write_text(
            json.dumps(reopened, ensure_ascii=False, indent=2), encoding="utf-8")
        capability = reopened_client.get("/api/v1/video/capabilities", headers=headers)
        capabilities = capability.json() if capability.status_code < 400 else {"httpStatus": capability.status_code}

        job = require_ok(reopened_client.post(f"/api/v1/video/projects/{PROJECT_ID}/render-jobs",
                                               json={"quality": "standard"}, headers=headers),
                         "V2 linear render submission")
        job_id = job["jobId"]
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            job = require_ok(reopened_client.get(f"/api/v1/video/jobs/{job_id}", headers=headers),
                             "V2 render job status")
            if job["state"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(1)
        if job["state"] != "succeeded":
            raise RuntimeError(f"V2 API render did not succeed: {json.dumps(job, ensure_ascii=False)}")
        result = reopened_client.get(f"/api/v1/video/jobs/{job_id}/result", headers=headers)
        if result.status_code != 200:
            raise RuntimeError(f"V2 render result download failed: HTTP {result.status_code}: {result.text}")
        candidate = output_directory / "denim-task2-1b-v2-api.mp4"
        candidate.write_bytes(result.content)

    ffmpeg = os.environ.get("TASK21B_FFMPEG") or "ffmpeg"
    if subprocess.run([ffmpeg, "-version"], capture_output=True, check=False).returncode != 0:
        raise RuntimeError(f"FFmpeg is unavailable: {ffmpeg}")
    frame_metrics = compare_frames(ffmpeg, baseline, candidate)
    audio_metrics = compare_audio(ffmpeg, baseline, candidate)
    summary = {
        "projectId": PROJECT_ID,
        "sourceProjectId": source_project_id,
        "sourceV1Sha256": project_hash,
        "v1BackupSha256": backup_hashes,
        "migrationBackupVerified": project_hash in backup_hashes,
        "schemaVersionAfterMigration": migrated["schemaVersion"],
        "schemaVersionAfterSaveReopen": reopened["schemaVersion"],
        "revisionAfterSave": saved["revision"],
        "revisionAfterReopen": reopened["revision"],
        "trackIdsAndOrdersStableAfterReopen": True,
        "clipIdsStableAfterReopen": True,
        "visualDurationMs": max((clip["timelineStartTicks"] + clip["durationTicks"]
                                  for track in reopened["tracks"] if track["kind"] == "visual"
                                  for clip in track["clips"]), default=0) // 90,
        "audioDurationMs": max((clip["timelineStartTicks"] + clip["durationTicks"]
                                 for track in reopened["tracks"] if track["kind"] == "audio"
                                 for clip in track["clips"]), default=0) // 90,
        "renderJob": job,
        "capabilities": capabilities,
        "baseline": str(baseline),
        "candidate": str(candidate),
        "candidateSha256": sha256(candidate.read_bytes()),
        "frameSamples": frame_metrics,
        "audioSamples": audio_metrics,
        "sourceV1FileStillHasOriginalHash": sha256(source_project_path.read_bytes()) == sha256(v1_bytes),
    }
    (output_directory / "linear-v2-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
