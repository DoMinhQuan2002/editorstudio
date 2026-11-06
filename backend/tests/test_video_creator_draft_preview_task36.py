from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mediastudio.video_editor.api import install_video_editor_api
from mediastudio.video_editor.media_selection import LEGACY_PLACEHOLDERS, VERSION


def test_draft_playback_preview_uses_persisted_v2_revision_and_graph(tmp_path, monkeypatch):
    import mediastudio.video_editor.api as video_api

    app = FastAPI()
    app.state.token = "task36"
    install_video_editor_api(app, tmp_path)
    app.state.video_ffmpeg.ffmpeg = "test-ffmpeg"
    app.state.video_ffmpeg.ffprobe = "test-ffprobe"
    app.state.video_ffmpeg.capabilities = lambda: {"h264Encoding": True, "aacEncoding": True}
    monkeypatch.setattr(video_api, "render_preview_frame", lambda *_args, **_kwargs: (
        b"\x89PNG\r\n\x1a\nframe", "task36-fixture-renderer"))

    def render_preview_video(job, graph, _media_store, _ffmpeg, output_directory, quality, _native_engine=None):
        assert quality == "draft"
        assert graph.width <= 540 and graph.height <= 960
        output_directory.mkdir(parents=True, exist_ok=True)
        path = output_directory / f"{graph.project_id}_{job.job_id}.mp4"
        path.write_bytes(b"\x00\x00\x00\x18ftypisomtask36")
        job.update(state="succeeded", progress=100, output_path=path)

    monkeypatch.setattr(video_api, "render_composition_project", render_preview_video)
    repo = Path(__file__).resolve().parents[2]
    headers = {"X-Media-Studio-Token": "task36"}
    with TestClient(app) as client:
        image = repo / "backend/tests/fixtures/active_fox.jpg"
        with image.open("rb") as stream:
            imported = client.post("/api/v1/video/media", headers=headers,
                                   files={"file": (image.name, stream)})
        assert imported.status_code == 201, imported.text
        asset_id = imported.json()["assetId"]
        response = client.post("/api/v1/video/processing-jobs", headers=headers, json={
            "templateId": "denim-story",
            "templateDefinitionVersion": VERSION,
            "selectionSessionId": "a" * 32,
            "bindings": {slot_id: asset_id for slot_id, _ in LEGACY_PLACEHOLDERS["denim-story"]},
        })
        assert response.status_code == 202, response.text
        job_id = response.json()["jobId"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = client.get(f"/api/v1/video/processing-jobs/{job_id}", headers=headers).json()
            if job["jobStatus"] in {"SUCCEEDED", "FAILED"}:
                break
            time.sleep(0.01)
        assert job["jobStatus"] == "SUCCEEDED", job

        project_response = client.get(
            f"/api/v1/video/projects/{job['draftProjectId']}", headers=headers)
        assert project_response.status_code == 200, project_response.text
        project = project_response.json()
        video = client.post(
            f"/api/v1/video/projects/{job['draftProjectId']}/preview/video",
            headers=headers, json=project)
        assert video.status_code == 200, video.text
        assert video.headers["content-type"].startswith("video/mp4")
        assert video.headers["x-composition-project-revision"] == str(project["revision"])
        assert video.headers["x-composition-source-fingerprint"]
        assert video.content[4:8] == b"ftyp"


def test_preview_video_rejects_project_id_mismatch(tmp_path):
    app = FastAPI()
    app.state.token = "task36"
    install_video_editor_api(app, tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/video/projects/" + "a" * 32 + "/preview/video",
            headers={"X-Media-Studio-Token": "task36"},
            json={"projectId": "b" * 32, "schemaVersion": 2},
        )
    assert response.status_code == 422
