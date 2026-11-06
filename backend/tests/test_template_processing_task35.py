from __future__ import annotations

import time
import logging
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mediastudio.video_editor.api import install_video_editor_api
from mediastudio.video_editor.media_selection import LEGACY_PLACEHOLDERS, VERSION


PNG = b"\x89PNG\r\n\x1a\n" + b"screen04-preview-fixture"


def test_preview_proxy_preserves_template_aspect_ratio():
    from mediastudio.video_editor.api import _preview_proxy_dimensions

    assert _preview_proxy_dimensions(720, 1556) == (444, 960)
    assert _preview_proxy_dimensions(1080, 1920) == (540, 960)
    assert _preview_proxy_dimensions(64, 3840) == (16, 960)


def _app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.state.token = "test"
    install_video_editor_api(app, tmp_path)
    app.state.video_ffmpeg.ffmpeg = "test-ffmpeg"
    return app


def _import_image(client: TestClient, headers: dict[str, str], repo: Path) -> str:
    source = repo / "backend/tests/fixtures/active_fox.jpg"
    with source.open("rb") as stream:
        response = client.post("/api/v1/video/media", headers=headers,
                               files={"file": (source.name, stream)})
    assert response.status_code == 201, response.text
    return response.json()["assetId"]


def _request(asset_id: str, session_id: str = "a" * 32, template_id: str = "denim-story") -> dict[str, object]:
    return {
        "templateId": template_id,
        "templateDefinitionVersion": VERSION,
        "selectionSessionId": session_id,
        "bindings": {slot: asset_id for slot, _ in LEGACY_PLACEHOLDERS[template_id]},
    }


def _wait_for_terminal(client: TestClient, headers: dict[str, str], job_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 5
    latest: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/video/processing-jobs/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        latest = response.json()
        if latest["jobStatus"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return latest
        time.sleep(0.01)
    raise AssertionError(f"Processing job did not finish: {latest}")


@pytest.mark.parametrize("template_id", LEGACY_PLACEHOLDERS)
def test_processing_job_compiles_persists_and_requires_a_real_preview(tmp_path, monkeypatch, template_id):
    import mediastudio.video_editor.api as video_api

    monkeypatch.setattr(video_api, "render_preview_frame", lambda *_args, **_kwargs: (PNG, "test-renderer"))
    app = _app(tmp_path)
    repo = Path(__file__).resolve().parents[2]
    headers = {"X-Media-Studio-Token": "test"}
    with TestClient(app) as client:
        asset_id = _import_image(client, headers, repo)
        request = _request(asset_id, template_id=template_id)
        response = client.post("/api/v1/video/processing-jobs", headers=headers, json=request)
        assert response.status_code == 202, response.text
        initial = response.json()
        assert initial["templateId"] == template_id
        assert initial["bindingFingerprint"]
        assert initial["progressPercent"] is None

        duplicate = client.post("/api/v1/video/processing-jobs", headers=headers, json=request)
        assert duplicate.status_code == 202, duplicate.text
        assert duplicate.json()["jobId"] == initial["jobId"]

        finished = _wait_for_terminal(client, headers, initial["jobId"])
        assert finished["jobStatus"] == "SUCCEEDED", finished
        assert finished["progressPercent"] == 100
        assert finished["draftProjectId"]
        assert finished["compositionReference"]
        assert finished["previewReference"]
        assert {stage["stageId"]: stage["status"] for stage in finished["stages"]} == {
            "analyze_media": "COMPLETED",
            "apply_layout": "COMPLETED",
            "remove_background": "SKIPPED",
            "build_composition": "COMPLETED",
            "sync_audio": "SKIPPED",
            "prepare_preview": "COMPLETED",
        }
        assert all(isinstance(stage["durationSeconds"], (int, float)) for stage in finished["stages"])

        project = client.get(f"/api/v1/video/projects/{finished['draftProjectId']}", headers=headers)
        assert project.status_code == 200
        assert project.json()["templateId"] == template_id
        assert project.json()["templateMetadata"]["templateBindings"] == request["bindings"]
        preview = client.get(f"/api/v1/video/projects/{finished['draftProjectId']}/preview/frame?timestamp_ticks=0",
                             headers=headers)
        assert preview.status_code == 200
        assert preview.content == PNG


def test_processing_rejects_reference_only_templates_and_bad_media_before_job_creation(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        headers = {"X-Media-Studio-Token": "test"}
        fall_diary = client.post("/api/v1/video/processing-jobs", headers=headers, json={
            "templateId": "fall-diary", "templateDefinitionVersion": VERSION,
            "selectionSessionId": "b" * 32, "bindings": {"fake": "c" * 32},
        })
        assert fall_diary.status_code == 422
        assert app.state.video_jobs._jobs == {}

        missing = client.post("/api/v1/video/processing-jobs", headers=headers,
                              json=_request("d" * 32, "e" * 32))
        assert missing.status_code == 422
        assert app.state.video_jobs._jobs == {}


def test_failed_preview_is_not_reported_as_success_and_can_be_retried(tmp_path, monkeypatch):
    import mediastudio.video_editor.api as video_api

    render_calls = 0

    def preview_once_fails(*_args, **_kwargs):
        nonlocal render_calls
        render_calls += 1
        if render_calls == 1:
            return b"not-a-png", "broken"
        return PNG, "test-renderer"

    monkeypatch.setattr(video_api, "render_preview_frame", preview_once_fails)
    app = _app(tmp_path)
    repo = Path(__file__).resolve().parents[2]
    headers = {"X-Media-Studio-Token": "test"}
    with TestClient(app) as client:
        asset_id = _import_image(client, headers, repo)
        started = client.post("/api/v1/video/processing-jobs", headers=headers, json=_request(asset_id, "f" * 32))
        assert started.status_code == 202, started.text
        failed = _wait_for_terminal(client, headers, started.json()["jobId"])
        assert failed["jobStatus"] == "FAILED"
        assert failed["errorCode"] == "PREVIEW_FAILED"
        assert failed["draftProjectId"] is None
        assert not any(stage["stageId"] == "prepare_preview" and stage["status"] == "COMPLETED"
                       for stage in failed["stages"])

        retry = client.post("/api/v1/video/processing-jobs", headers=headers,
                            json=_request(asset_id, "f" * 32))
        assert retry.status_code == 202, retry.text
        assert retry.json()["jobId"] != failed["jobId"]
        recovered = _wait_for_terminal(client, headers, retry.json()["jobId"])
        assert recovered["jobStatus"] == "SUCCEEDED"
        assert recovered["draftProjectId"]
        assert render_calls == 2


def test_preview_process_timeout_fails_the_active_stage_without_persisting_a_draft(tmp_path, monkeypatch):
    import mediastudio.video_editor.api as video_api

    def preview_timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("ffmpeg", video_api.PROCESSING_STAGE_TIMEOUT_SECONDS)

    monkeypatch.setattr(video_api, "render_preview_frame", preview_timeout)
    app = _app(tmp_path)
    repo = Path(__file__).resolve().parents[2]
    headers = {"X-Media-Studio-Token": "test"}
    with TestClient(app) as client:
        asset_id = _import_image(client, headers, repo)
        started = client.post("/api/v1/video/processing-jobs", headers=headers,
                              json=_request(asset_id, "8" * 32))
        assert started.status_code == 202, started.text

        finished = _wait_for_terminal(client, headers, started.json()["jobId"])
        assert finished["jobStatus"] == "FAILED"
        assert finished["errorCode"] == "PROCESSING_TIMEOUT"
        assert finished["draftProjectId"] is None
        preview_stage = next(stage for stage in finished["stages"] if stage["stageId"] == "prepare_preview")
        assert preview_stage["status"] == "FAILED"
        assert preview_stage["errorCode"] == "PROCESSING_TIMEOUT"


def test_processing_logs_each_stage_duration_and_total(caplog, tmp_path, monkeypatch):
    import mediastudio.video_editor.api as video_api

    monkeypatch.setattr(video_api, "render_preview_frame", lambda *_args, **_kwargs: (PNG, "test-renderer"))
    caplog.set_level(logging.INFO, logger="mediastudio.video_editor")
    app = _app(tmp_path)
    repo = Path(__file__).resolve().parents[2]
    headers = {"X-Media-Studio-Token": "test"}
    with TestClient(app) as client:
        asset_id = _import_image(client, headers, repo)
        started = client.post("/api/v1/video/processing-jobs", headers=headers,
                              json=_request(asset_id, "9" * 32))
        finished = _wait_for_terminal(client, headers, started.json()["jobId"])
        assert finished["jobStatus"] == "SUCCEEDED"

    stage_records = [record.getMessage() for record in caplog.records
                     if "template_processing.stage_complete" in record.getMessage()]
    assert {f"stage_id={stage_id}" for stage_id in (
        "analyze_media", "apply_layout", "build_composition", "sync_audio", "prepare_preview",
    )} <= {token for message in stage_records for token in message.split()}
    assert any("template_processing.complete" in record.getMessage()
               and "duration_seconds=" in record.getMessage() for record in caplog.records)


def test_unsupported_compiler_feature_is_reported_without_saving_a_draft(tmp_path, monkeypatch):
    import mediastudio.video_editor.api as video_api

    def reject_unsupported(*_args, **_kwargs):
        raise video_api.TemplateCompilerError("Unsupported transition fixture.")

    monkeypatch.setattr(video_api, "compile_template", reject_unsupported)
    app = _app(tmp_path)
    repo = Path(__file__).resolve().parents[2]
    headers = {"X-Media-Studio-Token": "test"}
    with TestClient(app) as client:
        asset_id = _import_image(client, headers, repo)
        started = client.post("/api/v1/video/processing-jobs", headers=headers, json=_request(asset_id, "7" * 32))
        assert started.status_code == 202, started.text

        failed = _wait_for_terminal(client, headers, started.json()["jobId"])

        assert failed["jobStatus"] == "FAILED"
        assert failed["errorCode"] == "UNSUPPORTED_FEATURE"
        assert failed["draftProjectId"] is None
        assert any(stage["stageId"] == "apply_layout" and stage["status"] == "FAILED"
                   for stage in failed["stages"])


def test_selection_session_deduplicates_same_bindings_but_allows_a_revised_binding_set(tmp_path, monkeypatch):
    import mediastudio.video_editor.api as video_api

    monkeypatch.setattr(video_api, "render_preview_frame", lambda *_args, **_kwargs: (PNG, "test-renderer"))
    app = _app(tmp_path)
    repo = Path(__file__).resolve().parents[2]
    headers = {"X-Media-Studio-Token": "test"}
    with TestClient(app) as client:
        first_asset = _import_image(client, headers, repo)
        second_asset = _import_image(client, headers, repo)
        request = _request(first_asset, "9" * 32)
        first = client.post("/api/v1/video/processing-jobs", headers=headers, json=request)
        assert first.status_code == 202, first.text
        changed = dict(request)
        changed["bindings"] = dict(request["bindings"])
        changed["bindings"][next(iter(changed["bindings"]))] = second_asset
        revised = client.post("/api/v1/video/processing-jobs", headers=headers, json=changed)
        assert revised.status_code == 202
        assert revised.json()["jobId"] != first.json()["jobId"]

