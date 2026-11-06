from __future__ import annotations

from array import array
from datetime import datetime, timezone
from io import BytesIO
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from mediastudio.video_editor.api import install_video_editor_api


ROOT = Path(__file__).resolve().parents[2]
SOURCE_DATA = ROOT / "artifacts/video_editor/task2_1b_validation/isolated-v1-data"
BASELINE = ROOT / "artifacts/video_editor/task2_1b_validation/baseline-task2-0b.mp4"
PROJECT_ID = "32e8d68cc8a248b884b7dd1bb08619ee"
TOKEN = "task22a-denim-regression"
SAMPLES_SECONDS = (0.0, 2.9, 3.1, 5.9, 6.1, 8.9, 9.1, 11.9, 12.1, 14.9, 15.1, 20.0, 37.5)
AUDIO_WINDOWS_SECONDS = (0.2, 5.0, 15.2, 36.5)


def run(command: list[str], timeout: int = 180) -> subprocess.CompletedProcess[bytes]:
    process = subprocess.run(command, capture_output=True, check=False, timeout=timeout)
    if process.returncode != 0:
        detail = process.stderr.decode("utf-8", "replace")[-2000:]
        raise RuntimeError(f"Command failed ({process.returncode}): {command[0]} {detail}")
    return process


def audio_samples(path: Path, ffmpeg: str) -> array:
    process = run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0:a:0",
                   "-ac", "2", "-ar", "44100", "-f", "f32le", "pipe:1"])
    data = array("f")
    usable = len(process.stdout) - len(process.stdout) % data.itemsize
    data.frombytes(process.stdout[:usable])
    return data


def rms_correlation(left: array, right: array) -> tuple[float, float, float]:
    count = min(len(left), len(right))
    if count == 0:
        raise RuntimeError("Audio window rỗng.")
    mean_left = sum(left) / count
    mean_right = sum(right) / count
    power_left = power_right = cross = 0.0
    for a, b in zip(left, right):
        da, db = a - mean_left, b - mean_right
        power_left += da * da
        power_right += db * db
        cross += da * db
    rms_left = math.sqrt(power_left / count)
    rms_right = math.sqrt(power_right / count)
    correlation = cross / math.sqrt(power_left * power_right) if power_left and power_right else 0.0
    return rms_left, rms_right, correlation


def frame_at(path: Path, index: int, ffmpeg: str) -> Image.Image:
    process = run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path), "-vf",
                   f"select=eq(n\\,{index})", "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "pipe:1"])
    return Image.open(BytesIO(process.stdout)).convert("RGB")


def rgb_mae(left: Image.Image, right: Image.Image) -> float:
    if left.size != right.size:
        raise RuntimeError(f"Frame size mismatch: {left.size} != {right.size}")
    return sum(abs(a - b) for a, b in zip(left.tobytes(), right.tobytes())) / (left.width * left.height * 3)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python run_task22a_denim_regression.py <new-validation-directory>")
    validation = Path(sys.argv[1]).resolve()
    if validation.exists():
        raise FileExistsError(f"Validation directory already exists; refusing to overwrite: {validation}")
    if not SOURCE_DATA.is_dir() or not BASELINE.is_file():
        raise FileNotFoundError("Task 2.1B isolated fixture or protected baseline is missing.")
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("ffmpeg and ffprobe are required.")

    project_source = SOURCE_DATA / "video_editor" / "projects" / f"{PROJECT_ID}.json"
    if not project_source.is_file():
        raise FileNotFoundError(project_source)
    project = json.loads(project_source.read_text(encoding="utf-8"))
    data_dir = validation / "data"
    project_dir = data_dir / "video_editor" / "projects"
    media_dir = data_dir / "video_editor" / "media"
    preview_dir = validation / "preview"
    project_dir.mkdir(parents=True)
    media_dir.mkdir(parents=True)
    preview_dir.mkdir(parents=True)
    shutil.copy2(project_source, project_dir / project_source.name)
    shutil.copytree(SOURCE_DATA / "video_editor" / "media", media_dir, dirs_exist_ok=True)
    (validation / "fixture.json").write_text(json.dumps({
        "projectId": PROJECT_ID,
        "sourceRevision": project.get("revision"),
        "sourceData": str(SOURCE_DATA),
        "protectedBaseline": str(BASELINE),
        "copiedProjectSha256": __import__("hashlib").sha256((project_dir / project_source.name).read_bytes()).hexdigest(),
        "trackIds": [track["trackId"] for track in project["tracks"]],
        "clipIds": [clip["clipId"] for track in project["tracks"] for clip in track["clips"]],
    }, indent=2), encoding="utf-8")

    app = FastAPI()
    app.state.token = TOKEN
    install_video_editor_api(app, data_dir)
    headers = {"X-Media-Studio-Token": TOKEN}
    preview_samples: list[dict[str, Any]] = []
    with TestClient(app) as client:
        get_project = client.get(f"/api/v1/video/projects/{PROJECT_ID}", headers=headers)
        if get_project.status_code != 200:
            raise RuntimeError(f"GET project failed: {get_project.status_code} {get_project.text}")
        canonical = get_project.json()
        graph_summary = {
            "projectId": canonical["projectId"],
            "schemaVersion": canonical["schemaVersion"],
            "revision": canonical["revision"],
            "trackIds": [track["trackId"] for track in canonical["tracks"]],
            "clipIds": [clip["clipId"] for track in canonical["tracks"] for clip in track["clips"]],
            "timelineDurationTicks": max(
                clip["timelineStartTicks"] + clip["durationTicks"]
                for track in canonical["tracks"] for clip in track["clips"]
            ),
        }
        (validation / "composition_input.json").write_text(json.dumps(graph_summary, indent=2), encoding="utf-8")

        for seconds in (0.5, 14.9, 15.1, 37.5):
            ticks = round(seconds * 90_000)
            response = client.get(f"/api/v1/video/projects/{PROJECT_ID}/preview/frame",
                                  params={"timestamp_ticks": ticks}, headers=headers)
            if response.status_code != 200:
                raise RuntimeError(f"Preview at {seconds}s failed: {response.status_code} {response.text}")
            preview_name = f"preview_{seconds:.1f}s.png"
            (preview_dir / preview_name).write_bytes(response.content)
            preview_samples.append({"seconds": seconds,
                                    "renderer": response.headers.get("x-composition-renderer"),
                                    "graphVersion": response.headers.get("x-composition-graph-version"),
                                    "sourceFingerprint": response.headers.get("x-composition-source-fingerprint"),
                                    "file": f"preview/{preview_name}"})

        submit = client.post(f"/api/v1/video/projects/{PROJECT_ID}/render-jobs",
                             json={"quality": "draft"}, headers=headers)
        if submit.status_code != 202:
            raise RuntimeError(f"Render submit failed: {submit.status_code} {submit.text}")
        job_id = submit.json()["jobId"]
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            snapshot = client.get(f"/api/v1/video/jobs/{job_id}", headers=headers).json()
            if snapshot["state"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(0.2)
        if snapshot["state"] != "succeeded":
            (validation / "render-job-failure.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
            raise RuntimeError(f"API render did not succeed: {snapshot}")
        result = client.get(f"/api/v1/video/jobs/{job_id}/result", headers=headers)
        if result.status_code != 200:
            raise RuntimeError(f"Render result failed: {result.status_code} {result.text}")
        candidate = validation / "denim_task22a_api_composition.mp4"
        candidate.write_bytes(result.content)
        (validation / "render-job.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        ffmpeg_capabilities = client.get("/api/v1/video/capabilities", headers=headers).json()

    probe_results = {}
    for label, path in (("baseline", BASELINE), ("candidate", candidate)):
        process = run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
        probe_results[label] = json.loads(process.stdout.decode("utf-8"))
        run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path), "-f", "null", "-"])
    (validation / "ffprobe.json").write_text(json.dumps(probe_results, indent=2), encoding="utf-8")

    frame_metrics = []
    for seconds in SAMPLES_SECONDS:
        index = round(seconds * 30)
        mae = rgb_mae(frame_at(BASELINE, index, ffmpeg), frame_at(candidate, index, ffmpeg))
        frame_metrics.append({"timeSeconds": seconds, "frameIndex": index, "rgbMae": mae,
                              "status": "PASS" if mae <= 18.0 else "FAIL", "threshold": 18.0})
    baseline_audio = audio_samples(BASELINE, ffmpeg)
    candidate_audio = audio_samples(candidate, ffmpeg)
    audio_metrics = []
    window_samples = int(0.2 * 44_100) * 2
    for seconds in AUDIO_WINDOWS_SECONDS:
        start = int(seconds * 44_100) * 2
        left = baseline_audio[start:start + window_samples]
        right = candidate_audio[start:start + window_samples]
        rms_a, rms_b, correlation = rms_correlation(left, right)
        audio_metrics.append({"startSeconds": seconds, "sampleFrames": window_samples // 2,
                              "baselineRms": rms_a, "candidateRms": rms_b,
                              "correlation": correlation,
                              "status": "PASS" if correlation >= 0.999 else "FAIL"})

    summary = {
        "task": "TASK 2.2A Denim Story graph export regression",
        "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "projectId": PROJECT_ID,
        "candidate": str(candidate),
        "baseline": str(BASELINE),
        "candidateSha256": __import__("hashlib").sha256(candidate.read_bytes()).hexdigest(),
        "ffmpegCapabilities": ffmpeg_capabilities["ffmpeg"],
        "previewSamples": preview_samples,
        "frameComparison": frame_metrics,
        "audioComparison": audio_metrics,
        "baselineAndCandidateFullyDecoded": True,
        "allFrameSamplesPassed": all(item["status"] == "PASS" for item in frame_metrics),
        "allAudioSamplesPassed": all(item["status"] == "PASS" for item in audio_metrics),
    }
    (validation / "denim-regression-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if summary["allFrameSamplesPassed"] and summary["allAudioSamplesPassed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
