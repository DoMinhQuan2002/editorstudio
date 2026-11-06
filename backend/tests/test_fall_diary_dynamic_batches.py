from __future__ import annotations

from types import SimpleNamespace

import pytest
from PIL import Image

from mediastudio.video_editor.cutout import ensure_background_removed_image
from mediastudio.video_editor.media_selection import (
    FALL_DIARY_FIRST_BACKGROUND_DURATION_MS, FALL_DIARY_MAX_MEDIA, FALL_DIARY_GROUP_SIZE,
    FALL_DIARY_SUBSEQUENT_BACKGROUND_DURATION_MS, SelectionPayloadRequest,
    get_template_definition, prepare_payload, slot_requirements,
)
from mediastudio.video_editor.template_compiler import compile_template


def _prepare(count: int, *, video_backgrounds: dict[int, int] | None = None):
    requirements = slot_requirements("fall-diary")
    bindings = {}
    media = {}
    video_backgrounds = video_backgrounds or {}
    for index, requirement in enumerate(requirements[:count]):
        asset_id = f"{index + 1:032x}"
        bindings[requirement["slotId"]] = asset_id
        duration_ms = video_backgrounds.get(index)
        media[asset_id] = SimpleNamespace(
            kind="video" if duration_ms is not None else "image",
            duration_ms=duration_ms,
            audio_codec=None,
        )
    request = SelectionPayloadRequest(
        template_id="fall-diary",
        template_definition_version=get_template_definition("fall-diary").version,
        bindings=bindings,
    )
    return prepare_payload(request, media.__getitem__), bindings, media


@pytest.mark.parametrize("count,group_count", [(1, 1), (7, 1), (9, 1), (10, 2), (36, 4)])
def test_fall_diary_accepts_ordered_partial_groups_and_caps_four_batches(count: int, group_count: int):
    payload, bindings, media = _prepare(count)
    definition = get_template_definition("fall-diary", payload["templateDefinitionVersion"])
    assert definition is not None
    compiled = compile_template(payload["definition"], bindings, media.__getitem__, project_id="a" * 32)
    assert len(payload["definition"]["slots"]) == count
    assert compiled.project.template_metadata["definitionMetadata"]["selectionPlan"]["groupCount"] == group_count
    expected_duration_ms = (FALL_DIARY_FIRST_BACKGROUND_DURATION_MS
                            + (group_count - 1) * FALL_DIARY_SUBSEQUENT_BACKGROUND_DURATION_MS)
    assert compiled.project.duration_ticks == expected_duration_ms * 90
    plan = payload["definition"]["metadata"]["selectionPlan"]
    assert plan["firstBackgroundTitleOverlapMs"] == 1_200
    assert plan["titleDurationMs"] == 1_200
    assert plan["backgroundDurationsMs"] == [5_200, *([4_000] * (group_count - 1))]
    title = next(event for event in payload["definition"]["events"] if event["eventId"] == "title-graphic")
    assert title["timelineStartTicks"] == 0
    assert title["durationTicks"] == 1_200 * 90
    backgrounds = [event for event in payload["definition"]["events"]
                   if event["eventClassification"] == "BACKGROUND_CUT"]
    assert [event["timelineStartTicks"] for event in backgrounds] == [
        sum(plan["backgroundDurationsMs"][:index]) * 90 for index in range(group_count)
    ]
    assert [event["durationTicks"] for event in backgrounds] == [
        duration_ms * 90 for duration_ms in plan["backgroundDurationsMs"]
    ]
    overlay_clips = [clip for track in compiled.project.tracks if track.kind == "visual"
                     for clip in track.clips if clip.properties.get("removeBackground")]
    assert len(overlay_clips) == count - group_count
    assert all(clip.properties["removeBackground"] is True for clip in overlay_clips)


def test_fall_diary_video_backgrounds_use_reference_beats_and_reset_each_nine_media():
    payload, bindings, media = _prepare(19, video_backgrounds={0: 22_000, 9: 8_000, 18: 12_000})
    definition = payload["definition"]
    plan = definition["metadata"]["selectionPlan"]
    assert plan["backgroundDurationsMs"] == [5_200, 4_000, 4_000]
    backgrounds = [event for event in definition["events"] if event["eventClassification"] == "BACKGROUND_CUT"]
    assert [event["timelineStartTicks"] for event in backgrounds] == [0, 5_200 * 90, 9_200 * 90]
    assert [event["durationTicks"] for event in backgrounds] == [5_200 * 90, 4_000 * 90, 4_000 * 90]
    assert [event["layers"][0]["slotId"] for event in backgrounds] == [
        "group-01-background", "group-02-background", "group-03-background",
    ]
    title = next(event for event in definition["events"] if event["eventId"] == "title-graphic")
    assert title["timelineStartTicks"] == 0
    assert title["durationTicks"] == 1_200 * 90
    compiled = compile_template(definition, bindings, media.__getitem__, project_id="b" * 32)
    assert compiled.project.duration_ticks == 13_200 * 90
    title_clip = next(clip for track in compiled.project.tracks for clip in track.clips
                      if clip.template_metadata.get("eventId") == "title-graphic")
    assert title_clip.duration_ticks == 1_200 * 90


def test_fall_diary_rejects_video_in_overlay_position_and_non_contiguous_selection():
    requirements = slot_requirements("fall-diary")
    request = SelectionPayloadRequest(
        template_id="fall-diary",
        template_definition_version="0.8.0-intro-title",
        bindings={requirements[0]["slotId"]: "1" * 32, requirements[1]["slotId"]: "2" * 32},
    )
    metadata = {
        "1" * 32: SimpleNamespace(kind="image", duration_ms=None),
        "2" * 32: SimpleNamespace(kind="video", duration_ms=5_000),
    }
    with pytest.raises(ValueError, match="cần ảnh phủ"):
        prepare_payload(request, metadata.__getitem__)

    non_contiguous = SelectionPayloadRequest(
        template_id="fall-diary",
        template_definition_version="0.8.0-intro-title",
        bindings={requirements[0]["slotId"]: "1" * 32, requirements[2]["slotId"]: "3" * 32},
    )
    with pytest.raises(ValueError, match="liên tục"):
        prepare_payload(non_contiguous, metadata.__getitem__)


@pytest.mark.parametrize("slot_index,duration_ms", [(0, 5_199), (9, 3_999)])
def test_fall_diary_video_background_must_cover_its_reference_timing(slot_index: int, duration_ms: int):
    requirements = slot_requirements("fall-diary")
    selected_requirements = requirements[:slot_index + 1]
    bindings = {item["slotId"]: f"{index + 1:032x}" for index, item in enumerate(selected_requirements)}
    metadata = {
        asset_id: SimpleNamespace(
            kind="video" if index == slot_index else "image",
            duration_ms=duration_ms if index == slot_index else None,
        )
        for index, asset_id in enumerate(bindings.values())
    }
    request = SelectionPayloadRequest(
        template_id="fall-diary",
        template_definition_version=get_template_definition("fall-diary").version,
        bindings=bindings,
    )
    with pytest.raises(ValueError, match="cần dài ít nhất"):
        prepare_payload(request, metadata.__getitem__)


def test_previous_dynamic_template_version_keeps_its_original_background_timing():
    version = "0.6.0-dynamic-batches"
    requirements = slot_requirements("fall-diary")
    asset_id = "b" * 32
    request = SelectionPayloadRequest(
        template_id="fall-diary",
        template_definition_version=version,
        bindings={requirements[0]["slotId"]: asset_id},
    )
    payload = prepare_payload(request, lambda _: SimpleNamespace(kind="image", duration_ms=None))
    plan = payload["definition"]["metadata"]["selectionPlan"]
    assert plan["backgroundDurationsMs"] == [17_000]
    assert payload["definition"]["durationTicks"] == 17_000 * 90


def test_reference_timing_version_keeps_saved_title_duration():
    version = "0.7.0-reference-timing"
    requirements = slot_requirements("fall-diary")
    asset_id = "c" * 32
    request = SelectionPayloadRequest(
        template_id="fall-diary",
        template_definition_version=version,
        bindings={requirements[0]["slotId"]: asset_id},
    )
    payload = prepare_payload(request, lambda _: SimpleNamespace(kind="image", duration_ms=None))
    title = next(event for event in payload["definition"]["events"] if event["eventId"] == "title-graphic")
    assert title["durationTicks"] == 5_200 * 90


def test_fall_diary_definition_declares_thirty_six_positions_in_four_groups():
    definition = get_template_definition("fall-diary")
    requirements = slot_requirements("fall-diary")
    assert definition is not None
    assert FALL_DIARY_MAX_MEDIA == 36
    assert FALL_DIARY_GROUP_SIZE == 9
    assert len(requirements) == 36
    assert [index + 1 for index, requirement in enumerate(requirements)
            if "background" in requirement["slotId"]] == [1, 10, 19, 28]
    assert [requirement["allowedMediaKinds"] for requirement in requirements[:3]] == [
        ["image", "video"], ["image"], ["image"],
    ]
    assert requirements[0]["required"] is True
    assert all(requirement["required"] is False for requirement in requirements[1:])


def test_background_cutout_is_rgba_and_cached(tmp_path, monkeypatch):
    import sys
    import types

    source = tmp_path / "source.jpg"
    Image.new("RGB", (12, 8), "white").save(source)
    calls = {"session": 0, "remove": 0}

    def new_session(model_name: str):
        assert model_name == "u2netp"
        calls["session"] += 1
        return object()

    def remove(image: Image.Image, *, session, **_kwargs):
        calls["remove"] += 1
        result = image.copy()
        result.putpixel((0, 0), (255, 255, 255, 0))
        return result

    fake_rembg = types.ModuleType("rembg")
    fake_rembg.new_session = new_session
    fake_rembg.remove = remove
    monkeypatch.setitem(sys.modules, "rembg", fake_rembg)

    destination = tmp_path / "cutouts" / "source.png"
    model_home = tmp_path / "models" / "rembg"
    assert ensure_background_removed_image(source, destination, model_home) == destination
    assert ensure_background_removed_image(source, destination, model_home) == destination
    with Image.open(destination) as cutout:
        assert cutout.mode == "RGBA"
        assert cutout.getpixel((0, 0))[3] == 0
    assert calls == {"session": 1, "remove": 1}
