from __future__ import annotations

from types import SimpleNamespace

import pytest

from mediastudio.video_editor.composition import FPS_RATES, build_composition_graph
from mediastudio.video_editor.media_selection import get_template_definition
from mediastudio.video_editor.project_v2 import TIMEBASE, VideoProjectV2, project_api_payload
from mediastudio.video_editor.template_compiler import TemplateDefinition, compile_template
from mediastudio.video_editor.template_keyframes import interpolate_keyframes, keyframe_expression


def _media(asset_id: str):
    return SimpleNamespace(asset_id=asset_id, kind="image", duration_ms=None, audio_codec=None)


def test_keyframe_interpolation_is_tick_based_and_linear():
    keys = [
        {"property": "positionX", "timeTicks": 0, "value": -0.4},
        {"property": "positionX", "timeTicks": 45_000, "value": 0.0},
        {"property": "positionX", "timeTicks": 90_000, "value": 0.4},
    ]
    assert interpolate_keyframes(keys, "positionX", 0) == pytest.approx(-0.4)
    assert interpolate_keyframes(keys, "positionX", 22_500) == pytest.approx(-0.2)
    assert interpolate_keyframes(keys, "positionX", 67_500) == pytest.approx(0.2)
    assert interpolate_keyframes(keys, "positionX", 90_000) == pytest.approx(0.4)
    assert interpolate_keyframes(keys, "scale", 22_500) is None
    expression = keyframe_expression(keys, "positionX", "t")
    assert expression is not None and "if(lt(t," in expression


@pytest.mark.parametrize("numerator,denominator", FPS_RATES)
def test_90khz_project_timebase_represents_supported_rates(numerator: int, denominator: int):
    project = VideoProjectV2.blank("timebase", fps_num=numerator, fps_den=denominator)
    graph = build_composition_graph(project, lambda _asset_id: None)
    ticks_per_frame = TIMEBASE * denominator // numerator
    assert TIMEBASE * denominator % numerator == 0
    assert graph.frame_start_ticks(0) == 0
    assert graph.frame_start_ticks(1) == ticks_per_frame
    assert graph.frame_start_ticks(30) == 30 * ticks_per_frame
    assert graph.frame_index_at(30 * ticks_per_frame) == 30


def test_fall_diary_motion_definition_is_versioned_and_baseline_remains_loadable():
    baseline = get_template_definition("fall-diary", "0.1.0-pilot")
    motion = get_template_definition("fall-diary", "0.2.0-motion-pilot")
    assert baseline is not None and baseline.version == "0.1.0-pilot"
    assert motion is not None and motion.version == "0.2.0-motion-pilot"
    assert len(baseline.slots) == len(motion.slots) == 12
    assert all(slot.reuse_policy == "unique_asset" for slot in baseline.slots)
    assert all(slot.reuse_policy == "allow" for slot in motion.slots)
    assert all(slot.allowed_media_kinds == ["image"] for slot in motion.slots)
    visual_layer_counts = [sum(layer.kind in {"image", "video"} for layer in event.layers)
                           for event in motion.events if any(layer.kind in {"image", "video"}
                                                            for layer in event.layers)]
    assert sorted(set(visual_layer_counts)) == [2, 3, 4]
    assert max(visual_layer_counts) == 4
    assert sum(bool(layer.keyframes) for event in motion.events for layer in event.layers) >= 10
    assert not any(layer.kind == "text" and layer.keyframes
                   for event in motion.events for layer in event.layers)
    assert any(layer.kind == "text" and layer.text_box and layer.text_box_color == "#F3D990"
               for event in motion.events for layer in event.layers)
    assert not any("cutout" in feature.casefold() or "mask" in feature.casefold()
                   for feature in motion.supported_capabilities)


def test_motion_template_compiles_animation_into_project_v2_and_graph():
    definition = get_template_definition("fall-diary", "0.2.0-motion-pilot")
    assert definition is not None
    bindings = {slot.slot_id: f"{index:032x}" for index, slot in enumerate(definition.slots, start=1)}
    metadata = {asset_id: _media(asset_id) for asset_id in bindings.values()}
    result = compile_template(definition, bindings, metadata.__getitem__, project_id="f" * 32)
    assert result.project.timebase == TIMEBASE
    assert result.project.template_metadata["templateDefinitionVersion"] == "0.2.0-motion-pilot"
    graph_clips = [clip for track in result.composition_graph["tracks"] if track["kind"] == "visual"
                   for clip in track["clips"]]
    animated = [clip for clip in graph_clips if clip["attributes"]["keyframes"]]
    assert len(animated) >= 10
    assert {key["property"] for clip in animated for key in clip["attributes"]["keyframes"]} == {
        "positionX", "positionY", "scale", "rotation", "opacity",
    }
    assert {clip["timelineStartTicks"] for clip in graph_clips} >= {0, 225_000, 450_000, 675_000, 900_000, 1_125_000}
    api_payload = project_api_payload(result.project)
    assert api_payload["templateMetadata"]["templateDefinitionVersion"] == "0.2.0-motion-pilot"
    assert any(clip["properties"].get("keyframes") for track in api_payload["tracks"]
               if track["kind"] == "visual" for clip in track["clips"])


def test_motion_keyframes_require_linear_interpolation_and_event_endpoints():
    definition = get_template_definition("fall-diary", "0.2.0-motion-pilot")
    assert definition is not None
    value = definition.model_dump(mode="json", by_alias=True)
    layer = next(layer for event in value["events"] for layer in event["layers"]
                 if layer.get("keyframes"))
    layer["keyframes"][0]["interpolation"] = "cubic"
    with pytest.raises(ValueError):
        TemplateDefinition.model_validate(value)

    value = definition.model_dump(mode="json", by_alias=True)
    layer = next(layer for event in value["events"] for layer in event["layers"]
                 if layer.get("keyframes"))
    layer["keyframes"].pop()
    with pytest.raises(ValueError, match="start at 0 and end at the event duration"):
        TemplateDefinition.model_validate(value)
