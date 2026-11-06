from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mediastudio.video_editor.catalog import get_template, list_templates
from mediastudio.video_editor.composition import build_composition_graph
from mediastudio.video_editor.media_selection import get_template_definition
from mediastudio.video_editor.project_v2 import TIMEBASE
from mediastudio.video_editor.template_compiler import TemplateDefinition, compile_template


def _metadata(asset_id: str, kind: str = "image"):
    return SimpleNamespace(asset_id=asset_id, kind=kind, duration_ms=15_000 if kind == "video" else None,
                           audio_codec=None)


def _bindings(definition):
    return {slot.slot_id: f"{index:032x}" for index, slot in enumerate(definition.slots, start=1)}


def test_versioned_definitions_keep_01_and_02_and_advertise_03():
    legacy = get_template_definition("fall-diary", "0.1.0-pilot")
    motion = get_template_definition("fall-diary", "0.2.0-motion-pilot")
    reference = get_template_definition("fall-diary", "0.3.0-reference-pilot")

    assert legacy is not None and motion is not None and reference is not None
    assert legacy.version == "0.1.0-pilot"
    assert motion.version == "0.2.0-motion-pilot"
    latest = get_template_definition("fall-diary")
    assert latest is not None and latest.version == "0.9.0-reference-overlays"
    assert reference.version == "0.3.0-reference-pilot"
    assert len(legacy.slots) == len(motion.slots) == 12
    assert all(slot.reuse_policy == "unique_asset" for slot in legacy.slots)
    assert all(slot.allowed_media_kinds == ["image"] for slot in motion.slots)


def test_03_events_use_verified_frame_ticks_without_equal_scene_assumption():
    definition = get_template_definition("fall-diary", "0.3.0-reference-pilot")
    assert definition is not None
    backgrounds = [event for event in definition.events if event.event_id.startswith("background-")]
    overlays = [event for event in definition.events if event.event_id.startswith("overlay-")]
    title = next(event for event in definition.events if event.event_id == "title-graphic")

    assert [(event.timeline_start_ticks, event.duration_ticks) for event in backgrounds] == [
        (0, 519_000), (519_000, 360_000), (879_000, 315_000),
        (1_194_000, 45_000), (1_239_000, 291_000),
    ]
    assert [(event.timeline_start_ticks, event.duration_ticks) for event in overlays] == [
        (339_000, 135_000), (474_000, 135_000), (609_000, 225_000),
        (834_000, 45_000), (879_000, 45_000), (924_000, 270_000),
    ]
    assert title.timeline_start_ticks == 0 and title.duration_ticks == 1_530_000
    assert all(tick % 3_000 == 0 for event in definition.events
               for tick in (event.timeline_start_ticks, event.timeline_start_ticks + event.duration_ticks))
    assert definition.duration_ticks == 510 * (TIMEBASE // 30)
    assert sum(event.duration_ticks for event in backgrounds) == definition.duration_ticks


def test_reference_definition_uses_generic_compiler_and_accepts_reused_images():
    definition = get_template_definition("fall-diary", "0.3.0-reference-pilot")
    assert definition is not None
    bindings = _bindings(definition)
    bindings["photo-02"] = bindings["photo-01"]
    metadata = {asset_id: _metadata(asset_id) for asset_id in set(bindings.values())}

    compiled = compile_template(definition, bindings, metadata.__getitem__, project_id="a" * 32)
    graph = build_composition_graph(compiled.project, metadata.__getitem__)
    assert compiled.project.template_metadata["templateDefinitionVersion"] == definition.version
    assert graph.timebase == TIMEBASE and graph.duration_ticks == definition.duration_ticks
    assert graph.frame_rate_numerator == 30 and graph.frame_rate_denominator == 1
    assert {track.layer_order for track in graph.tracks} == {0, 1, 20}
    assert sum(len(track.clips) for track in graph.tracks) == 20
    assert not any(track.kind == "audio" for track in graph.tracks)
    assert any(clip.attributes.get("text") == "F" for track in graph.tracks for clip in track.clips)


def test_03_slot_rules_reject_missing_and_wrong_kinds_but_allow_reuse():
    definition = get_template_definition("fall-diary", "0.3.0-reference-pilot")
    assert definition is not None
    assert len(definition.slots) == 11
    assert all(slot.required and slot.reuse_policy == "allow" and slot.missing_slot_policy == "error"
               and slot.allowed_media_kinds == ["image"] for slot in definition.slots)
    assert all("local_reference" not in json.dumps(layer.model_dump(mode="json"))
               for event in definition.events for layer in event.layers)

    bindings = _bindings(definition)
    metadata = {asset_id: _metadata(asset_id) for asset_id in set(bindings.values())}
    with pytest.raises(ValueError, match="Required media slot is missing"):
        compile_template(definition, {key: value for key, value in bindings.items() if key != "photo-04"},
                         metadata.__getitem__)
    metadata[bindings["photo-04"]] = _metadata(bindings["photo-04"], "video")
    with pytest.raises(ValueError, match="not allowed"):
        compile_template(definition, bindings, metadata.__getitem__)


def test_catalog_exposes_03_as_pilot_without_demo_or_muse_screen_recording():
    catalog = {item["templateId"]: item for item in list_templates()}
    fall = catalog["fall-diary"]
    assert fall["templateDefinitionVersion"] == "0.9.0-reference-overlays"
    assert fall["availabilityStatus"] == "PILOT_RENDERABLE"
    assert fall["durationMs"] == 17_200
    assert fall["requiredMediaSlots"] == 1
    assert fall["previewAvailable"] is False
    assert fall["demoSource"] is None and fall["posterSource"] is None
    assert [scene["durationMs"] for scene in fall["scenes"]] == [5_200, 4_000, 4_000, 4_000]
    assert get_template("fall-diary") is not None


def test_03_definition_schema_and_layout_layers_are_explicit():
    path = Path(__file__).resolve().parents[1] / "mediastudio/video_editor/definitions/fall-diary-0.3.0-reference-pilot.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    definition = TemplateDefinition.model_validate(payload)
    overlay_layers = [layer for event in definition.events for layer in event.layers
                      if layer.layer_id.endswith("-card")]
    assert overlay_layers
    assert all(layer.kind == "image" and layer.fit_mode == "contain" and layer.rotation == 0
               and not layer.keyframes for layer in overlay_layers)
    assert all(layer.position_y < 0 and layer.scale <= 0.28 for layer in overlay_layers)
    assert "linear_keyframes_90khz" not in definition.supported_capabilities
    assert all(not layer.keyframes for event in definition.events for layer in event.layers)
