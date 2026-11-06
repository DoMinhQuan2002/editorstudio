from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mediastudio.video_editor.catalog import list_templates
from mediastudio.video_editor.composition import build_composition_graph
from mediastudio.video_editor.media_selection import get_template_definition, prepare_payload, SelectionPayloadRequest
from mediastudio.video_editor.project_v2 import TIMEBASE
from mediastudio.video_editor.template_compiler import TemplateDefinition, compile_template
from mediastudio.video_editor.template_keyframes import interpolate_keyframes


VERSION = "0.4.0-editorial-motion-pilot"
CHANGE_TICKS = [0, 339_000, 474_000, 519_000, 609_000, 834_000,
                879_000, 924_000, 1_194_000, 1_239_000, 1_530_000]


def _metadata(asset_id: str):
    return SimpleNamespace(asset_id=asset_id, kind="image", duration_ms=None, audio_codec=None)


def test_01_02_03_04_remain_available_and_04_baseline_is_unchanged():
    versions = ["0.1.0-pilot", "0.2.0-motion-pilot", "0.3.0-reference-pilot", VERSION]
    definitions = [get_template_definition("fall-diary", version) for version in versions]
    assert all(definition is not None for definition in definitions)
    assert get_template_definition("fall-diary").version == "0.9.0-reference-overlays"
    assert len(definitions[0].slots) == len(definitions[1].slots) == 12
    assert len(definitions[2].slots) == 11
    assert len(definitions[3].slots) == 11


def test_04_tracks_observed_visible_boundaries_and_marks_all_image_motion_editorial():
    definition = get_template_definition("fall-diary", VERSION)
    assert definition is not None
    events = [event for event in definition.events if event.event_id.startswith("shot-")]
    assert [event.timeline_start_ticks for event in events] == CHANGE_TICKS[:-1]
    assert [event.timeline_start_ticks + event.duration_ticks for event in events] == CHANGE_TICKS[1:]
    assert all(event.layers[0].layer_order == 0 and event.layers[0].fit_mode == "cover"
               for event in events)
    assert all(event.layers[0].keyframes for event in events)
    assert all(key.property == "scale" for event in events for key in event.layers[0].keyframes)
    assert "editorial_slow_push_in" in definition.supported_capabilities
    assert "multi_layer_collage" in definition.supported_capabilities
    cards = [event for event in definition.events if event.event_id.startswith("editorial-card-")]
    assert [(event.timeline_start_ticks, event.duration_ticks) for event in cards] == [
        (609_000, 225_000), (924_000, 270_000)]
    assert all(event.layers[0].slot_id == "photo-11" and event.layers[0].layer_order == 1
               for event in cards)
    assert all(tick % 3_000 == 0 for tick in CHANGE_TICKS)
    assert definition.duration_ticks == 17 * TIMEBASE


def test_04_schema_compiles_with_stable_slot_bindings_and_shared_graph():
    definition = get_template_definition("fall-diary", VERSION)
    assert definition is not None
    payload_path = Path(__file__).resolve().parents[1] / "mediastudio/video_editor/definitions/fall-diary-0.4.0-editorial-motion-pilot.json"
    parsed = TemplateDefinition.model_validate(json.loads(payload_path.read_text(encoding="utf-8")))
    bindings = {slot.slot_id: f"{index:032x}" for index, slot in enumerate(parsed.slots, start=1)}
    metadata = {asset_id: _metadata(asset_id) for asset_id in set(bindings.values())}
    project_id = "a" * 32
    compiled = compile_template(parsed, bindings, metadata.__getitem__, project_id=project_id)
    graph = build_composition_graph(compiled.project, metadata.__getitem__)
    assert compiled.project.template_metadata["templateDefinitionVersion"] == VERSION
    assert compiled.project.template_metadata["templateBindings"] == bindings
    assert graph.timebase == TIMEBASE and graph.duration_ticks == 1_530_000
    assert graph.frame_rate_numerator == 30 and graph.frame_rate_denominator == 1
    assert {track.layer_order for track in graph.tracks} == {0, 1, 20}
    assert sum(len(track.clips) for track in graph.tracks) == 21
    image_clips = [clip for track in graph.tracks if track.kind == "visual" for clip in track.clips]
    assert len(image_clips) == 12
    assert all(clip.attributes["keyframes"] for clip in image_clips)
    text_clips = [clip for track in graph.tracks if track.kind == "text" for clip in track.clips]
    assert len(text_clips) == 9
    assert sorted(clip.attributes["text"] for clip in text_clips) == sorted("FALLDIARY")


def test_04_keyframe_interpolation_and_reuse_policy():
    definition = get_template_definition("fall-diary", VERSION)
    assert definition is not None
    first = definition.events[0].layers[0]
    keys = [key.model_dump(mode="json", by_alias=True) for key in first.keyframes]
    assert interpolate_keyframes(keys, "scale", first and definition.events[0].duration_ticks // 2) == pytest.approx(
        (1.0 + keys[-1]["value"]) / 2)

    bindings = {slot.slot_id: f"{index:032x}" for index, slot in enumerate(definition.slots, start=1)}
    metadata = {asset_id: _metadata(asset_id) for asset_id in set(bindings.values())}
    bindings["photo-02"] = bindings["photo-01"]
    request = SelectionPayloadRequest(template_id="fall-diary", template_definition_version=VERSION,
                                      bindings=bindings)
    payload = prepare_payload(request, metadata.__getitem__)
    assert payload["bindings"]["photo-02"] == payload["bindings"]["photo-01"]
    with pytest.raises(ValueError, match="Required media slot is missing"):
        compile_template(definition, {key: value for key, value in bindings.items() if key != "photo-03"},
                         metadata.__getitem__)


def test_catalog_presents_04_editorial_baseline_as_nonreleased_template():
    row = next(item for item in list_templates() if item["templateId"] == "fall-diary")
    assert row["templateDefinitionVersion"] == "0.9.0-reference-overlays"
    assert row["availabilityStatus"] == "PILOT_RENDERABLE"
    assert row["requiredMediaSlots"] == 1
    assert row["durationMs"] == 17_200
    assert row["demoSource"] is None and row["posterSource"] is None
    assert "36 media" in row["description"].lower()
