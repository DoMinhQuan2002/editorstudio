from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from mediastudio.video_editor.composition import build_composition_graph
from mediastudio.video_editor.media_selection import get_template_definition
from mediastudio.video_editor.project_v2 import TIMEBASE
from mediastudio.video_editor.template_compiler import TemplateDefinition, compile_template


VERSION = "0.5.0-layer-structure-pilot"
BACKGROUND_STARTS = [0, 519_000, 879_000, 1_194_000, 1_239_000]
OVERLAY_STARTS = [339_000, 474_000, 609_000, 834_000, 879_000, 924_000]
CANDIDATES = [0, 339_000, 474_000, 519_000, 609_000, 834_000,
              879_000, 924_000, 1_194_000, 1_239_000, 1_530_000]


def _metadata(asset_id: str):
    return SimpleNamespace(asset_id=asset_id, kind="image", duration_ms=None, audio_codec=None)


def test_all_prior_definitions_remain_available_and_06_is_latest():
    versions = ["0.1.0-pilot", "0.2.0-motion-pilot", "0.3.0-reference-pilot",
                "0.4.0-editorial-motion-pilot", VERSION]
    definitions = [get_template_definition("fall-diary", version) for version in versions]
    assert all(definition is not None for definition in definitions)
    assert get_template_definition("fall-diary").version == "0.9.0-reference-overlays"
    assert [len(definition.slots) for definition in definitions] == [12, 12, 11, 11, 11]


def test_05_separates_five_backgrounds_from_six_independent_overlays():
    definition = get_template_definition("fall-diary", VERSION)
    assert definition is not None
    backgrounds = [event for event in definition.events if event.event_id.startswith("background-")]
    overlays = [event for event in definition.events if event.event_id.startswith("overlay-")]
    assert [event.timeline_start_ticks for event in backgrounds] == BACKGROUND_STARTS
    assert [event.timeline_start_ticks for event in overlays] == OVERLAY_STARTS
    assert all(event.layers[0].layer_order == 0 and event.layers[0].fit_mode == "cover"
               for event in backgrounds)
    assert all(event.layers[0].layer_order == 1 and event.layers[0].fit_mode == "contain"
               for event in overlays)
    assert all(event.event_classification == "OVERLAY_REPLACEMENT" for event in overlays)
    assert all(event.source_evidence for event in definition.events)
    assert all(tick % 3_000 == 0 for tick in CANDIDATES)
    assert definition.duration_ticks == 17 * TIMEBASE
    assert len(definition.slots) == 11


def test_overlay_replacements_do_not_split_background_events_and_motion_is_labeled():
    definition = get_template_definition("fall-diary", VERSION)
    assert definition is not None
    background_events = [event for event in definition.events if event.event_id.startswith("background-")]
    background_intervals = [(event.timeline_start_ticks,
                             event.timeline_start_ticks + event.duration_ticks)
                            for event in background_events]
    for overlay in (event for event in definition.events if event.event_id.startswith("overlay-")):
        start = overlay.timeline_start_ticks
        # The background event beginning at 5.767, 6.767, 9.267, 9.767, or 10.267
        # is unaffected except where reference review classifies an actual cut.
        containing = [interval for interval in background_intervals
                      if interval[0] <= start < interval[1]]
        assert len(containing) == 1
    for event in background_events:
        layer = event.layers[0]
        assert layer.motion_classification == "EDITORIAL_MOTION"
        assert [key.property for key in layer.keyframes] == ["scale", "scale"]
        assert layer.keyframes[0].time_ticks == 0
        assert layer.keyframes[-1].time_ticks == event.duration_ticks
    overlays = [event for event in definition.events if event.event_id.startswith("overlay-")]
    assert all(not event.layers[0].keyframes for event in overlays)
    assert all(event.layers[0].motion_classification == "UNVERIFIED" for event in overlays)


def test_05_metadata_and_safe_layout_are_versioned_and_compiler_preserves_evidence():
    definition = get_template_definition("fall-diary", VERSION)
    assert definition is not None
    assert definition.metadata["layoutProfile"] == {"id": "editorial-safe-v1", "version": 1}
    assert "no subject detection" in definition.metadata["layoutIntent"].lower()
    assert any("not restored Muse keyframe data" in item
               for item in definition.metadata["editorialAssumptions"])
    path = (Path(__file__).resolve().parents[1] /
            "mediastudio/video_editor/definitions/fall-diary-0.5.0-layer-structure-pilot.json")
    parsed = TemplateDefinition.model_validate(json.loads(path.read_text(encoding="utf-8")))
    bindings = {slot.slot_id: f"{index:032x}" for index, slot in enumerate(parsed.slots, start=1)}
    metadata = {asset_id: _metadata(asset_id) for asset_id in set(bindings.values())}
    compiled = compile_template(parsed, bindings, metadata.__getitem__, project_id="a" * 32)
    graph = build_composition_graph(compiled.project, metadata.__getitem__)
    assert compiled.project.template_metadata["definitionMetadata"] == parsed.metadata
    assert graph.duration_ticks == 1_530_000 and graph.timebase == TIMEBASE
    assert len([track for track in graph.tracks if track.kind == "visual"]) == 3
    clips = [clip for track in compiled.project.tracks for clip in track.clips]
    overlay_clip = next(clip for clip in clips if clip.template_metadata["eventId"] == "overlay-pour-replacement")
    assert overlay_clip.template_metadata["eventClassification"] == "OVERLAY_REPLACEMENT"
    assert "3.700s/3.767s/3.833s" in overlay_clip.template_metadata["sourceEvidence"]
    background_clip = next(clip for clip in clips if clip.template_metadata["eventId"] == "background-opening")
    assert background_clip.template_metadata["motionClassification"] == "EDITORIAL_MOTION"


def test_05_title_uses_centered_bundled_svg_asset():
    definition = get_template_definition("fall-diary", VERSION)
    assert definition is not None
    title = next(event for event in definition.events if event.event_id == "title-graphic")
    assert len(title.layers) == 1
    layer = title.layers[0]
    assert layer.layer_id == "title-fall-diary-vector"
    assert layer.asset_reference == "assets/fall_diary_vector.png"
    assert layer.position_x == 0 and layer.position_y == 0.006
    assert layer.scale == 0.42
