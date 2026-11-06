from types import SimpleNamespace
from pathlib import Path
import hashlib
from io import BytesIO
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageOps
from mediastudio.video_editor.api import install_video_editor_api
from mediastudio.video_editor.catalog import get_template, list_templates
from mediastudio.video_editor.media_selection import (
    LEGACY_PLACEHOLDERS,
    VERSION,
    SelectionPayloadRequest,
    get_template_definition,
    prepare_payload,
)
from mediastudio.video_editor.template_compiler import compile_template


@pytest.mark.parametrize("template_id", LEGACY_PLACEHOLDERS)
def test_explicit_mapping_matches_actual_legacy_visual_placeholders(template_id):
    template = get_template(template_id)
    legacy = template.create_project()
    placeholders = [c for t in legacy.tracks if t.kind == "visual" for c in t.clips]
    mapping = LEGACY_PLACEHOLDERS[template_id]
    assert len(mapping) == len(placeholders)
    bindings = {slot: f"{i + 1:032x}" for i, (slot, _) in enumerate(mapping)}
    media = {asset: SimpleNamespace(kind="image" if i % 2 == 0 else "video", duration_ms=20000,
                                    audio_codec=None) for i, asset in enumerate(bindings.values())}
    payload = prepare_payload(SelectionPayloadRequest(template_id=template_id,
                              template_definition_version=VERSION, bindings=bindings), media.__getitem__)
    compiled = compile_template(payload["definition"], payload["bindings"], media.__getitem__)
    clips = [c for t in compiled.project.tracks if t.kind == "visual" for c in t.clips]
    assert [(c.timeline_start_ticks, c.duration_ticks) for c in clips] == [(c.timeline_start_ticks, c.duration_ticks) for c in placeholders]
    assert [c.template_metadata["slotId"] for c in clips] == [slot for slot, _ in mapping]
    assert len([c for t in compiled.project.tracks if t.kind == "text" for c in t.clips]) == 1


def test_invalid_bindings_and_unavailable_definition():
    def request(id="denim-story", version=VERSION, bindings=None):
        return SelectionPayloadRequest(template_id=id, template_definition_version=version, bindings=bindings or {})
    fall_definition = get_template_definition("fall-diary")
    assert fall_definition is not None
    fall_bindings = {slot.slot_id: f"{index + 1:032x}" for index, slot in enumerate(fall_definition.slots)}
    fall_media = {asset: SimpleNamespace(kind="image", duration_ms=None, audio_codec=None)
                  for asset in fall_bindings.values()}
    fall_payload = prepare_payload(
        SelectionPayloadRequest(template_id="fall-diary", template_definition_version=fall_definition.version,
                                bindings=fall_bindings),
        fall_media.__getitem__,
    )
    assert fall_payload["templateDefinitionVersion"] == "0.9.0-reference-overlays"
    assert len(fall_payload["definition"]["slots"]) == 2
    reused = dict(fall_bindings)
    background_slot, first_overlay_slot = [slot.slot_id for slot in fall_definition.slots]
    reused[first_overlay_slot] = reused[background_slot]
    reused_payload = prepare_payload(
        SelectionPayloadRequest(template_id="fall-diary", template_definition_version=fall_definition.version,
                                bindings=reused),
        fall_media.__getitem__,
    )
    assert reused_payload["bindings"][first_overlay_slot] == reused_payload["bindings"][background_slot]
    legacy_definition = get_template_definition("fall-diary", "0.1.0-pilot")
    assert legacy_definition is not None
    legacy_bindings = {slot.slot_id: f"{index + 1:032x}" for index, slot in enumerate(legacy_definition.slots)}
    legacy_bindings["photo-02"] = legacy_bindings["photo-01"]
    with pytest.raises(ValueError, match="unique_asset"):
        prepare_payload(
            SelectionPayloadRequest(template_id="fall-diary", template_definition_version=legacy_definition.version,
                                    bindings=legacy_bindings),
            fall_media.__getitem__,
        )
    with pytest.raises(ValueError): prepare_payload(request("fall-diary"), lambda _: None)
    with pytest.raises(ValueError): prepare_payload(request(version="old"), lambda _: None)
    with pytest.raises(ValueError): prepare_payload(request(bindings={"invented": "a" * 32}), lambda _: None)
    bindings = {slot: "a" * 32 for slot, _ in LEGACY_PLACEHOLDERS["denim-story"]}
    for kind, duration in [("audio", 20000), ("video", 1000)]:
        with pytest.raises(ValueError):
            prepare_payload(request(bindings=bindings), lambda _: SimpleNamespace(kind=kind, duration_ms=duration))
    with pytest.raises(KeyError): prepare_payload(request(bindings=bindings), {}.__getitem__)


def test_prepare_endpoint_has_no_project_or_render_side_effects(tmp_path):
    app = FastAPI(); app.state.token = "test"
    install_video_editor_api(app, tmp_path)
    with TestClient(app) as client:
        headers = {"X-Media-Studio-Token": "test"}
        before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
        response = client.post("/api/v1/video/media-selection/prepare", headers=headers,
                               json={"templateId": "fall-diary", "templateDefinitionVersion": VERSION, "bindings": {}})
        assert response.status_code == 422
        assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before
    catalog = {t["templateId"]: t for t in list_templates()}
    assert catalog["denim-story"]["requiredMediaSlots"] == 5
    assert catalog["product-intro"]["requiredMediaSlots"] == 6
    assert catalog["fall-diary"]["requiredMediaSlots"] == 1
    assert catalog["fall-diary"]["templateDefinitionVersion"] == "0.9.0-reference-overlays"


def test_real_media_import_payload_compiles_without_overwriting_sources_or_projects(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    source_photo = repo / "backend/tests/fixtures/active_fox.jpg"
    video_source = repo / "capcut-cli-master/media/two-sisters-vietnam-short.mp4"
    portrait_png = tmp_path / "portrait.png"
    landscape_png = tmp_path / "landscape.png"
    with Image.open(source_photo) as image:
        ImageOps.fit(image.convert("RGB"), (320, 480), method=Image.Resampling.LANCZOS).save(portrait_png)
        ImageOps.fit(image.convert("RGB"), (480, 320), method=Image.Resampling.LANCZOS).save(landscape_png)
    sources = [source_photo, portrait_png, landscape_png, video_source]
    source_hash = hashlib.sha256(source_photo.read_bytes()).hexdigest()
    app = FastAPI(); app.state.token = "test"
    install_video_editor_api(app, tmp_path)
    with TestClient(app) as client:
        headers = {"X-Media-Studio-Token": "test"}
        project = client.post("/api/v1/video/projects/blank", headers=headers, json={"title": "sentinel"}).json()
        project_path = tmp_path / "video_editor/projects" / (project["projectId"] + ".json")
        original_project = project_path.read_bytes()
        media = []
        for source in sources:
            with source.open("rb") as stream:
                response = client.post("/api/v1/video/media", headers=headers, files={"file": (source.name, stream)})
            assert response.status_code == 201, response.text
            media.append(response.json())
            thumbnail = client.get(f'/api/v1/video/media/{media[-1]["assetId"]}/thumbnail', headers=headers)
            assert thumbnail.status_code == 200
            with Image.open(BytesIO(thumbnail.content)) as decoded:
                decoded.verify()
            assert media[-1]["thumbnailAvailable"] is True
        assert [m["kind"] for m in media] == ["image", "image", "image", "video"]
        assert (media[0]["width"], media[0]["height"]) == (554, 554)
        assert (media[1]["width"], media[1]["height"]) == (320, 480)
        assert (media[2]["width"], media[2]["height"]) == (480, 320)
        bindings = {slot: media[i % 2]["assetId"] for i, (slot, _) in enumerate(LEGACY_PLACEHOLDERS["denim-story"])}
        response = client.post("/api/v1/video/media-selection/prepare", headers=headers,
                               json={"templateId": "denim-story", "templateDefinitionVersion": VERSION, "bindings": bindings})
        assert response.status_code == 200, response.text
        payload = response.json()
        compiled = compile_template(payload["definition"], payload["bindings"], app.state.video_media.get_metadata)
        assert compiled.project.template_id == "denim-story"
        assert project_path.read_bytes() == original_project
        assert len(list(project_path.parent.glob("*.json"))) == 1
    assert hashlib.sha256(source_photo.read_bytes()).hexdigest() == source_hash
