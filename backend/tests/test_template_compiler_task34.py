from __future__ import annotations

from types import SimpleNamespace

import pytest

from mediastudio.video_editor.catalog import get_template, list_templates
from mediastudio.video_editor.media_selection import get_template_definition
from mediastudio.video_editor.template_compiler import (
    TemplateCompilerError,
    TemplateDefinition,
    TemplateKeyframe,
    compile_template,
)


IMAGE_A = "a" * 32
IMAGE_B = "b" * 32


def _definition(**changes) -> TemplateDefinition:
    value = {
        "templateId": "compiler-fixture",
        "version": "1.0.0",
        "name": "Compiler Fixture",
        "width": 1080,
        "height": 1920,
        "frameRateNumerator": 30000,
        "frameRateDenominator": 1001,
        "durationTicks": 15_015,
        "slots": [
            {"slotId": "hero", "allowedMediaKinds": ["image"], "required": True},
            {"slotId": "detail", "allowedMediaKinds": ["image"], "required": False,
             "missingSlotPolicy": "skip_event"},
        ],
        "events": [
            {"eventId": "opening", "timelineStartTicks": 3_003, "durationTicks": 6_006,
             "layers": [
                 {"layerId": "hero-frame", "kind": "image", "layerOrder": 0, "slotId": "hero",
                  "scale": 1.1, "positionY": -0.1, "opacity": 0.95},
                 {"layerId": "title", "kind": "text", "layerOrder": 1, "text": "Fall Diary",
                  "textY": 0.2, "fontSize": 64},
                 {"layerId": "detail-frame", "kind": "image", "layerOrder": 2, "slotId": "detail"},
             ]},
            {"eventId": "closing", "timelineStartTicks": 9_009, "durationTicks": 6_006,
             "layers": [
                 {"layerId": "closing-frame", "kind": "image", "layerOrder": 0, "slotId": "hero"},
             ]},
        ],
    }
    value.update(changes)
    return TemplateDefinition.model_validate(value)


def _media(media_id: str, kind: str = "image", duration_ms: int | None = None):
    return SimpleNamespace(asset_id=media_id, kind=kind, duration_ms=duration_ms, audio_codec=None)


def test_catalog_registers_fall_diary_once_as_pilot_renderable_definition():
    rows = list_templates()
    fall_diary = [item for item in rows if item["templateId"] == "fall-diary"]

    assert len(fall_diary) == 1
    assert fall_diary[0]["availabilityStatus"] == "PILOT_RENDERABLE"
    assert fall_diary[0]["previewAvailable"] is False
    assert fall_diary[0]["requiredMediaSlots"] == 1
    assert fall_diary[0]["durationMs"] == 17200
    assert fall_diary[0]["templateDefinitionVersion"] == "0.9.0-reference-overlays"
    assert fall_diary[0]["demoSource"] is None
    assert fall_diary[0]["posterSource"] is None
    assert get_template("fall-diary") is not None


def test_fall_diary_canvas_dimensions_flow_from_definition_through_catalog_project_and_graph():
    definition = get_template_definition("fall-diary")
    template = get_template("fall-diary")
    assert definition is not None and template is not None
    assert (definition.width, definition.height) == (720, 1556)

    catalog_entry = next(item for item in list_templates() if item["templateId"] == "fall-diary")
    assert (catalog_entry["width"], catalog_entry["height"]) == (720, 1556)
    assert catalog_entry["aspectRatio"] == "180:389"

    placeholder = template.create_project()
    assert (placeholder.width, placeholder.height) == (720, 1556)

    metadata = _media(IMAGE_A)
    compiled = compile_template(
        definition,
        {slot.slot_id: IMAGE_A for slot in definition.slots},
        lambda _asset_id: metadata,
        project_id="d" * 32,
    )
    assert (compiled.project.width, compiled.project.height) == (720, 1556)
    assert (compiled.composition_graph["width"], compiled.composition_graph["height"]) == (720, 1556)


def test_catalog_does_not_treat_scene_events_as_media_slots():
    denim = next(item for item in list_templates() if item["templateId"] == "denim-story")

    assert denim["sceneCount"] == 5
    assert denim["requiredMediaSlots"] == 5
    assert denim["mediaSlotRequirements"][0]["slotId"] == "denim-close-up"
    # Task 3.3 verified explicit legacy placeholder mapping; no generic scene inference.


def test_compiler_preserves_exact_ticks_layer_order_bindings_and_text():
    media = {IMAGE_A: _media(IMAGE_A), IMAGE_B: _media(IMAGE_B)}
    result = compile_template(
        _definition(), {"hero": IMAGE_A, "detail": IMAGE_B}, media.__getitem__,
        project_id="c" * 32,
    )

    project = result.project
    graph = result.composition_graph
    assert project.template_id == "compiler-fixture"
    assert project.frame_rate_numerator == 30000
    assert project.frame_rate_denominator == 1001
    assert project.template_metadata["templateBindings"] == {"detail": IMAGE_B, "hero": IMAGE_A}
    assert graph["timebase"] == 90_000
    assert [(track["layerOrder"], track["kind"]) for track in graph["tracks"]] == [
        (0, "visual"), (1, "text"), (2, "visual")
    ]
    hero = graph["tracks"][0]["clips"][0]
    assert hero["timelineStartTicks"] == 3_003
    assert hero["durationTicks"] == 6_006
    assert hero["attributes"]["scale"] == 1.1
    assert hero["attributes"]["positionY"] == -0.1
    text_clip = graph["tracks"][1]["clips"][0]
    assert text_clip["attributes"]["text"] == "Fall Diary"
    assert text_clip["attributes"]["fontSize"] == 64
    assert all(len(clip["clipId"]) == 32 for track in graph["tracks"] for clip in track["clips"])


def test_compiler_preserves_valid_linear_keyframes_in_project_graph():
    definition = _definition()
    duration = definition.events[0].duration_ticks
    definition.events[0].layers[0].keyframes = [
        TemplateKeyframe(property="positionX", timeTicks=0, value=-0.25),
        TemplateKeyframe(property="positionX", timeTicks=duration // 2, value=0.0),
        TemplateKeyframe(property="positionX", timeTicks=duration, value=0.25),
    ]
    result = compile_template(
        definition, {"hero": IMAGE_A, "detail": IMAGE_B},
        {IMAGE_A: _media(IMAGE_A), IMAGE_B: _media(IMAGE_B)}.__getitem__,
        project_id="4" * 32,
    )
    hero = result.composition_graph["tracks"][0]["clips"][0]
    assert hero["attributes"]["keyframes"] == [
        {"property": "positionX", "timeTicks": 0, "value": -0.25,
         "interpolation": "linear", "easing": "linear"},
        {"property": "positionX", "timeTicks": duration // 2, "value": 0.0,
         "interpolation": "linear", "easing": "linear"},
        {"property": "positionX", "timeTicks": duration, "value": 0.25,
         "interpolation": "linear", "easing": "linear"},
    ]


def test_optional_slot_uses_explicit_skip_policy_and_warns():
    result = compile_template(
        _definition(), {"hero": IMAGE_A}, {IMAGE_A: _media(IMAGE_A)}.__getitem__,
        project_id="d" * 32,
    )

    assert len(result.warnings) == 1
    assert "opening" in result.warnings[0]
    assert "detail" in result.warnings[0]
    assert [track["layerOrder"] for track in result.composition_graph["tracks"]] == [0]
    assert result.composition_graph["tracks"][0]["clips"][0]["attributes"]["name"] == "closing-frame"


def test_missing_required_slot_fails_before_project_creation():
    with pytest.raises(TemplateCompilerError, match="Required media slot is missing: hero"):
        compile_template(_definition(), {}, lambda _asset_id: None, project_id="e" * 32)


def test_disallowed_media_type_and_invalid_source_range_fail():
    with pytest.raises(TemplateCompilerError, match="not allowed for slot hero"):
        compile_template(
            _definition(), {"hero": IMAGE_A}, {IMAGE_A: _media(IMAGE_A, "video", 1000)}.__getitem__,
            project_id="f" * 32,
        )


def test_unique_asset_policy_rejects_cross_slot_reuse():
    definition = _definition()
    definition.slots[0].reuse_policy = "unique_asset"
    definition.slots[1].reuse_policy = "unique_asset"
    with pytest.raises(TemplateCompilerError, match="unique_asset policy forbids reuse"):
        compile_template(
            definition, {"hero": IMAGE_A, "detail": IMAGE_A},
            {IMAGE_A: _media(IMAGE_A)}.__getitem__, project_id="1" * 32,
        )


@pytest.mark.parametrize("feature", ["cutoutReference", "maskReference", "transition"])
def test_unsupported_renderer_features_are_reported(feature: str):
    definition = _definition()
    visual = definition.events[0].layers[0]
    if feature == "cutoutReference":
        visual.cutout_reference = "person-mask"
    elif feature == "maskReference":
        visual.mask_reference = "frame-mask"
    else:
        visual.transition = "fade"

    with pytest.raises(TemplateCompilerError, match="unsupported features"):
        compile_template(
            definition, {"hero": IMAGE_A, "detail": IMAGE_B},
            {IMAGE_A: _media(IMAGE_A), IMAGE_B: _media(IMAGE_B)}.__getitem__,
            project_id="2" * 32,
        )


def test_video_source_bounds_are_validated_in_ticks():
    value = _definition().model_dump(mode="python", by_alias=True)
    value["slots"][0]["allowedMediaKinds"] = ["video"]
    value["events"][0]["layers"][0]["kind"] = "video"
    value["events"][1]["layers"][0]["kind"] = "video"
    value["events"][0]["layers"][0]["sourceTimeMapping"]["sourceStartTicks"] = 90_000
    definition = TemplateDefinition.model_validate(value)

    with pytest.raises(TemplateCompilerError, match="exceeds its source media duration"):
        compile_template(
            definition, {"hero": IMAGE_A, "detail": IMAGE_B},
            {IMAGE_A: _media(IMAGE_A, "video", 1000), IMAGE_B: _media(IMAGE_B)}.__getitem__,
            project_id="3" * 32,
        )
