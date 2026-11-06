from __future__ import annotations

import os
import time
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageChops

from mediastudio.video_editor.api import install_video_editor_api
from mediastudio.video_editor.media_selection import get_template_definition, resolve_template_asset, slot_requirements
from mediastudio.video_editor.template_compiler import TemplateLayer


TOKEN = "fall-diary-svg-title-test"
BACKGROUND = (32, 98, 160)


def test_fall_diary_svg_asset_is_bundled_and_path_traversal_is_rejected():
    definition = get_template_definition("fall-diary")
    assert definition is not None
    asset = resolve_template_asset(definition.template_id, definition.version, "assets/fall_diary_vector.png")
    source_svg = asset.with_suffix(".svg")
    assert source_svg.is_file()
    with Image.open(asset) as image:
        rgba = image.convert("RGBA")
        assert rgba.size == (2800, 1400)
        assert rgba.getpixel((0, 0))[3] == 0

    with pytest.raises(ValueError):
        resolve_template_asset(definition.template_id, definition.version, "../../../../outside.png")
    with pytest.raises(ValueError):
        TemplateLayer.model_validate({
            "layerId": "unsafe-static-image",
            "kind": "image",
            "layerOrder": 1,
            "assetReference": "../../outside.png",
        })


def test_processing_and_preview_render_the_svg_title_at_canvas_center(tmp_path):
    definition = get_template_definition("fall-diary")
    assert definition is not None
    title_layers = [layer for event in definition.events for layer in event.layers
                    if layer.layer_id == "title-fall-diary-vector"]
    assert len(title_layers) == 1
    title = title_layers[0]
    assert title.asset_reference == "assets/fall_diary_vector.png"
    assert title.position_x == 0 and title.position_y == pytest.approx(0.006)
    assert title.scale == pytest.approx(0.42)
    assert title.kind == "image" and title.slot_id is None

    app = FastAPI()
    app.state.token = TOKEN
    install_video_editor_api(app, tmp_path / "backend-data")
    headers = {"X-Media-Studio-Token": TOKEN}

    background_bytes = BytesIO()
    Image.new("RGB", (720, 1556), BACKGROUND).save(background_bytes, format="PNG")
    background_bytes.seek(0)
    background_slot = slot_requirements("fall-diary")[0]["slotId"]

    with TestClient(app) as client:
        imported = client.post(
            "/api/v1/video/media", headers=headers,
            files={"file": ("solid-background.png", background_bytes, "image/png")},
        )
        assert imported.status_code == 201, imported.text
        asset_id = imported.json()["assetId"]
        started = client.post("/api/v1/video/processing-jobs", headers=headers, json={
            "templateId": definition.template_id,
            "templateDefinitionVersion": definition.version,
            "selectionSessionId": "a" * 32,
            "bindings": {background_slot: asset_id},
        })
        assert started.status_code == 202, started.text

        deadline = time.monotonic() + 20
        finished = None
        while time.monotonic() < deadline:
            status = client.get(
                f"/api/v1/video/processing-jobs/{started.json()['jobId']}", headers=headers,
            )
            assert status.status_code == 200, status.text
            finished = status.json()
            if finished["jobStatus"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                break
            time.sleep(0.05)
        assert finished is not None and finished["jobStatus"] == "SUCCEEDED", finished

        saved = client.get(
            f"/api/v1/video/projects/{finished['draftProjectId']}", headers=headers,
        )
        assert saved.status_code == 200, saved.text
        project = saved.json()
        assert (project["width"], project["height"]) == (720, 1556)
        compiled_title = [clip for track in project["tracks"] for clip in track["clips"]
                          if clip["properties"].get("templateAssetReference")]
        assert len(compiled_title) == 1
        assert compiled_title[0]["mediaId"] is None
        assert compiled_title[0]["properties"]["templateAssetReference"] == "assets/fall_diary_vector.png"

        preview = client.get(
            f"/api/v1/video/projects/{project['projectId']}/preview/frame",
            params={"timestamp_ticks": 0}, headers=headers,
        )
        assert preview.status_code == 200, preview.text
        rendered = Image.open(BytesIO(preview.content)).convert("RGB")
        assert rendered.size == (720, 1556)

    difference = ImageChops.difference(rendered, Image.new("RGB", rendered.size, BACKGROUND))
    mask = difference.convert("L").point(lambda value: 255 if value > 48 else 0)
    bounds = mask.getbbox()
    assert bounds is not None
    left, top, right, bottom = bounds
    assert 260 <= right - left <= 360
    assert 110 <= bottom - top <= 190
    assert abs((left + right) / 2 - rendered.width / 2) <= 8
    assert abs((top + bottom) / 2 - rendered.height / 2) <= 8

    artifact_directory = Path(os.environ.get("AGENT_PROMPT_ARTIFACT_DIR", ""))
    if str(artifact_directory) != ".":
        artifact_directory.mkdir(parents=True, exist_ok=True)
        (artifact_directory / "fall_diary_svg_centered_preview.png").write_bytes(preview.content)
