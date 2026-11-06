from __future__ import annotations

import time
import subprocess
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageChops, ImageStat

from mediastudio.video_editor.api import install_video_editor_api
from mediastudio.video_editor.ffmpeg import FFmpegToolchain
from mediastudio.video_editor.media_selection import LEGACY_PLACEHOLDERS, VERSION


def _wait_for_job(client: TestClient, headers: dict[str, str], job_id: str,
                  timeout_seconds: int = 5) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/video/jobs/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        job = response.json()
        if job["state"] in {"succeeded", "failed", "cancelled"}:
            return job
        time.sleep(0.01)
    raise AssertionError(f"Export job {job_id} did not finish in time")


def _create_draft(client: TestClient, headers: dict[str, str], repo: Path) -> dict[str, object]:
    image = repo / "backend/tests/fixtures/active_fox.jpg"
    with image.open("rb") as stream:
        imported = client.post("/api/v1/video/media", headers=headers,
                               files={"file": (image.name, stream)})
    assert imported.status_code == 201, imported.text
    asset_id = imported.json()["assetId"]
    processing = client.post("/api/v1/video/processing-jobs", headers=headers, json={
        "templateId": "denim-story",
        "templateDefinitionVersion": VERSION,
        "selectionSessionId": "a" * 32,
        "bindings": {slot_id: asset_id for slot_id, _ in LEGACY_PLACEHOLDERS["denim-story"]},
    })
    assert processing.status_code == 202, processing.text
    job_id = processing.json()["jobId"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = client.get(f"/api/v1/video/processing-jobs/{job_id}", headers=headers).json()
        if state["jobStatus"] in {"SUCCEEDED", "FAILED"}:
            assert state["jobStatus"] == "SUCCEEDED", state
            break
        time.sleep(0.01)
    else:
        raise AssertionError("Task 3.5 processing fixture did not complete")
    return client.get(f"/api/v1/video/projects/{state['draftProjectId']}", headers=headers).json()


def test_screen06_capabilities_are_derived_from_saved_composition(tmp_path, monkeypatch):
    import mediastudio.video_editor.api as video_api

    app = FastAPI()
    app.state.token = "task37"
    install_video_editor_api(app, tmp_path)
    app.state.video_ffmpeg.ffmpeg = "test-ffmpeg"
    app.state.video_ffmpeg.ffprobe = "test-ffprobe"
    app.state.video_ffmpeg.capabilities = lambda: {
        "available": True, "h264Encoding": True, "aacEncoding": True, "textOverlay": True,
    }
    monkeypatch.setattr(video_api, "render_preview_frame", lambda *_args, **_kwargs: (
        b"\x89PNG\r\n\x1a\nframe", "task37-fixture-renderer"))
    headers = {"X-Media-Studio-Token": "task37"}
    repo = Path(__file__).resolve().parents[2]

    with TestClient(app) as client:
        project = _create_draft(client, headers, repo)
        response = client.get(
            f"/api/v1/video/projects/{project['projectId']}/export-capabilities", headers=headers)
        assert response.status_code == 200, response.text
        capabilities = response.json()
        assert capabilities["canExport"] is True
        assert capabilities["draftRevision"] == project["revision"]
        assert capabilities["templateId"] == "denim-story"
        assert capabilities["templateVersion"] == VERSION
        assert capabilities["width"] == 1080 and capabilities["height"] == 1920
        assert capabilities["frameRateNumerator"] == 30
        assert capabilities["frameRateDenominator"] == 1
        assert capabilities["format"] == "mp4"
        assert capabilities["videoCodec"] == "h264"
        assert capabilities["qualities"] == ["standard", "high"]
        assert capabilities["hasAudio"] is False


def test_screen06_export_validates_draft_and_publishes_one_verified_job(tmp_path, monkeypatch):
    import mediastudio.video_editor.api as video_api

    app = FastAPI()
    app.state.token = "task37"
    install_video_editor_api(app, tmp_path)
    app.state.video_ffmpeg.ffmpeg = "test-ffmpeg"
    app.state.video_ffmpeg.ffprobe = "test-ffprobe"
    app.state.video_ffmpeg.capabilities = lambda: {
        "available": True, "h264Encoding": True, "aacEncoding": True, "textOverlay": True,
    }
    monkeypatch.setattr(video_api, "render_preview_frame", lambda *_args, **_kwargs: (
        b"\x89PNG\r\n\x1a\nframe", "task37-fixture-renderer"))
    render_calls: list[str] = []
    fake_mp4 = b"\x00\x00\x00\x18ftypisomtask37-verified-mp4"

    def render_export(job, graph, _media, _ffmpeg, output_directory, quality, _native=None, *, defer_success=False):
        assert quality == "standard"
        assert defer_success is True
        render_calls.append(job.job_id)
        output_directory.mkdir(parents=True, exist_ok=True)
        rendered = output_directory / f"{graph.project_id}_{job.job_id}.mp4"
        rendered.write_bytes(fake_mp4)
        job.update(state="processing", progress=99, stage="checking", output_path=rendered)

    monkeypatch.setattr(video_api, "render_composition_project", render_export)
    monkeypatch.setattr(video_api, "_probe_and_decode_export", lambda path, graph, _ffmpeg, _job, has_audio: {
        "outputPath": str(path), "durationMs": 15_000, "width": graph.width, "height": graph.height,
        "frameRateNumerator": graph.frame_rate_numerator, "frameRateDenominator": graph.frame_rate_denominator,
        "format": "MP4", "videoCodec": "H.264", "audioCodec": None, "sizeBytes": path.stat().st_size,
        "fullDecodePassed": True,
    })
    headers = {"X-Media-Studio-Token": "task37"}
    repo = Path(__file__).resolve().parents[2]
    destination = tmp_path / "user output"
    assert not destination.exists()

    with TestClient(app) as client:
        project = _create_draft(client, headers, repo)
        project_id = str(project["projectId"])
        capabilities = client.get(
            f"/api/v1/video/projects/{project_id}/export-capabilities", headers=headers).json()
        request = {
            "requestId": "b" * 32,
            "draftRevision": project["revision"],
            "templateId": project["templateId"],
            "templateVersion": VERSION,
            "compositionFingerprint": capabilities["compositionFingerprint"],
            "mediaBindings": capabilities["mediaBindings"],
            "quality": "standard",
            "outputDirectory": str(destination),
            "fileName": "Denim Story",
            "overwrite": False,
        }
        stale = dict(request, draftRevision=int(project["revision"]) + 1)
        rejected = client.post(f"/api/v1/video/projects/{project_id}/export-jobs", headers=headers, json=stale)
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == "DRAFT_REVISION_MISMATCH"

        invalid_name = dict(request, requestId="c" * 32, fileName="CON")
        rejected = client.post(f"/api/v1/video/projects/{project_id}/export-jobs", headers=headers, json=invalid_name)
        assert rejected.status_code == 422

        started = client.post(f"/api/v1/video/projects/{project_id}/export-jobs", headers=headers, json=request)
        assert started.status_code == 202, started.text
        job_id = started.json()["jobId"]
        job = _wait_for_job(client, headers, job_id)
        assert job["state"] == "succeeded", job
        assert job["progress"] == 100
        assert job["draftProjectId"] == project_id
        assert job["templateVersion"] == VERSION
        assert job["bindingFingerprint"] == capabilities["compositionFingerprint"]
        assert job["exportResult"]["fullDecodePassed"] is True
        output = Path(job["exportResult"]["outputPath"])
        assert output == destination / "Denim Story.mp4"
        assert destination.is_dir()
        assert output.read_bytes() == fake_mp4
        assert not list((tmp_path / "video_editor" / "export_staging").glob("*.mp4"))
        assert len(render_calls) == 1

        duplicate = client.post(f"/api/v1/video/projects/{project_id}/export-jobs", headers=headers, json=request)
        assert duplicate.status_code == 202
        assert duplicate.json()["jobId"] == job_id
        assert len(render_calls) == 1
        history = tmp_path / "video_editor" / "export_history" / f"{project_id}.json"
        assert history.exists()
        assert history.read_text(encoding="utf-8").count('"status": "SUCCEEDED"') == 1


def test_screen06_real_export_is_probeable_decodable_and_tracks_preview(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    toolchain = FFmpegToolchain()
    capabilities = toolchain.capabilities()
    if not capabilities.get("available") or not capabilities.get("h264Encoding"):
        import pytest
        pytest.skip("Local FFmpeg/FFprobe with H.264 is unavailable.")

    app = FastAPI()
    app.state.token = "task37-real"
    data_directory = tmp_path / "backend-data"
    install_video_editor_api(app, data_directory)
    headers = {"X-Media-Studio-Token": "task37-real"}
    output_directory = repo / "artifacts" / "video_creator" / "task3_7" / "real_export"
    output_directory.mkdir(parents=True, exist_ok=True)
    file_name = "Denim Story Task 3.7"

    with TestClient(app) as client:
        project = _create_draft(client, headers, repo)
        project_id = str(project["projectId"])
        export_capabilities = client.get(
            f"/api/v1/video/projects/{project_id}/export-capabilities", headers=headers).json()
        assert export_capabilities["canExport"], export_capabilities
        request = {
            "requestId": "d" * 32,
            "draftRevision": project["revision"],
            "templateId": project["templateId"],
            "templateVersion": VERSION,
            "compositionFingerprint": export_capabilities["compositionFingerprint"],
            "mediaBindings": export_capabilities["mediaBindings"],
            "quality": "standard",
            "outputDirectory": str(output_directory),
            "fileName": file_name,
            "overwrite": (output_directory / f"{file_name}.mp4").exists(),
        }
        started = client.post(f"/api/v1/video/projects/{project_id}/export-jobs", headers=headers, json=request)
        assert started.status_code == 202, started.text
        job = _wait_for_job(client, headers, started.json()["jobId"], timeout_seconds=180)
        assert job["state"] == "succeeded", job
        result = job["exportResult"]
        output_path = Path(result["outputPath"])
        assert output_path == output_directory / f"{file_name}.mp4"
        assert result["fullDecodePassed"] is True
        assert result["videoCodec"] == "H.264"
        assert (result["width"], result["height"]) == (project["width"], project["height"])
        assert result["frameRateNumerator"] == project["frameRateNumerator"]
        assert result["frameRateDenominator"] == project["frameRateDenominator"]
        assert result["durationMs"] > 0

        differences: dict[int, float] = {}
        for second in (1, 7, 13):
            preview = client.get(
                f"/api/v1/video/projects/{project_id}/preview/frame",
                params={"timestamp_ticks": second * 90_000}, headers=headers)
            assert preview.status_code == 200, preview.text
            decoded = subprocess.run(
                [toolchain.ffmpeg, "-v", "error", "-ss", str(second), "-i", str(output_path),
                 "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                capture_output=True, check=False,
            )
            assert decoded.returncode == 0, decoded.stderr.decode("utf-8", errors="replace")
            from io import BytesIO
            preview_image = Image.open(BytesIO(preview.content)).convert("RGB")
            output_image = Image.open(BytesIO(decoded.stdout)).convert("RGB")
            assert output_image.size == preview_image.size
            difference = ImageStat.Stat(ImageChops.difference(preview_image, output_image))
            mean_channel_difference = sum(difference.mean) / 3
            differences[second] = mean_channel_difference
            assert mean_channel_difference < 18, (second, mean_channel_difference)
        assert set(differences) == {1, 7, 13}
