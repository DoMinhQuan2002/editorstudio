from types import SimpleNamespace

import pytest

from mediastudio.video_editor.composition_renderer import _canvas_font_size
from mediastudio.video_editor.media_selection import get_template_definition
from mediastudio.video_editor.template_compiler import compile_template


def _media(asset_id: str):
    return SimpleNamespace(asset_id=asset_id, kind="image", duration_ms=None, audio_codec=None)


def test_fall_diary_definition_is_versioned_pilot_and_multi_layer():
    definition = get_template_definition("fall-diary", "0.1.0-pilot")

    assert definition is not None
    assert definition.version == "0.1.0-pilot"
    assert (definition.width, definition.height) == (1080, 1920)
    assert definition.duration_ticks == 1_350_000
    assert [slot.slot_id for slot in definition.slots] == [f"photo-{index:02d}" for index in range(1, 13)]
    visual_events = [event for event in definition.events if any(layer.kind == "image" for layer in event.layers)]
    assert len(visual_events) == 6
    assert all(sum(layer.kind == "image" for layer in event.layers) >= 2 for event in visual_events)


def test_fall_diary_compiles_project_v2_with_explicit_slots_and_text():
    definition = get_template_definition("fall-diary", "0.1.0-pilot")
    bindings = {slot.slot_id: f"{index:032x}" for index, slot in enumerate(definition.slots, start=1)}
    media = {asset_id: _media(asset_id) for asset_id in bindings.values()}

    result = compile_template(definition, bindings, media.__getitem__, project_id="9" * 32)

    assert result.project.template_metadata["templateDefinitionVersion"] == "0.1.0-pilot"
    assert result.project.template_metadata["templateBindings"] == dict(sorted(bindings.items()))
    assert len([track for track in result.project.tracks if track.kind == "visual"]) == 2
    assert len([track for track in result.project.tracks if track.kind == "text"]) == 1
    assert sum(len(track.clips) for track in result.project.tracks if track.kind == "visual") == 12
    assert sum(len(track.clips) for track in result.project.tracks if track.kind == "text") == 1


@pytest.mark.parametrize(
    ("font_size", "width", "height", "expected"),
    [(76, 1080, 1920, 76), (76, 540, 960, 38), (64, 720, 1280, 43)],
)
def test_text_scale_uses_shared_portrait_design_canvas(font_size, width, height, expected):
    assert _canvas_font_size(font_size, width, height) == expected
