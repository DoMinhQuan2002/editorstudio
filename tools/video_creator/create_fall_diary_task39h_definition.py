"""Create the versioned 3.9H layer-structure pilot from reviewed 0.3 events."""
from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFINITIONS = ROOT / "backend/mediastudio/video_editor/definitions"
BASELINE = DEFINITIONS / "fall-diary-0.3.0-reference-pilot.json"
OUTPUT = DEFINITIONS / "fall-diary-0.5.0-layer-structure-pilot.json"
TIMEBASE = 90_000
FRAME_TICKS = 3_000


EVIDENCE = {
    "background-opening": (
        "Isolated Muse preview frames 0.000s, 3.700s, 3.767s and 3.833s retain the same tree/street landmarks; "
        "source in-point is unknown."
    ),
    "background-autumn-park": (
        "Frames 5.767s, 5.833s, 6.700s and 6.833s show the autumn-park scene; 5.767s is a likely background cut."
    ),
    "background-picnic": (
        "Frames 9.767s, 9.833s, 10.200s and 10.333s show the leaf-ground/picnic scene; 9.767s is a likely cut."
    ),
    "background-food-insert": (
        "Frames 13.200s, 13.267s, 13.333s and 13.700s show a tighter food composition; a background cut versus "
        "a large foreground insert cannot be separated with confidence."
    ),
    "background-bouquet-close": (
        "Frames 13.700s, 13.767s and 13.833s change from the food scene to a flower/lap composition; likely cut."
    ),
    "overlay-pour-replacement": (
        "Frames 3.700s/3.767s/3.833s: tree and street background landmarks persist while foreground content changes."
    ),
    "overlay-basket-replacement": (
        "Frames 5.200s/5.267s/5.333s: the tree/street background persists while a basket/collage replaces the prior insert."
    ),
    "overlay-park-figure": (
        "Frames 6.700s/6.767s/6.833s: autumn-park background persists while foreground content changes."
    ),
    "overlay-coffee-close": (
        "Frames 9.200s/9.267s/9.333s: autumn background persists while the foreground insert changes."
    ),
    "overlay-picnic-transition": (
        "Frames 9.700s/9.767s/9.833s: foreground and background both change near the same boundary; overlay event is "
        "kept independent, but exact source layer split has medium confidence."
    ),
    "overlay-market-figure": (
        "Frames 10.200s/10.267s/10.333s: leaf-ground/picnic landmarks persist while foreground content changes."
    ),
    "title-graphic": (
        "FALL/DIARY tile glyphs are visible inside the isolated preview from 0.000s through 13.833s; the end is "
        "unknown because later screen-recording frames are obscured by UI."
    ),
}


def _frame_keyframes(duration_ticks: int) -> list[dict[str, object]]:
    # Keep the existing linear keyframe engine. The scale change is explicitly
    # editorial and stays continuous for each real background event.
    return [
        {"property": "scale", "timeTicks": 0, "value": 1.0,
         "interpolation": "linear", "easing": "linear"},
        {"property": "scale", "timeTicks": duration_ticks, "value": 1.012,
         "interpolation": "linear", "easing": "linear"},
    ]


def _apply_safe_title_layout(title_event: dict[str, object]) -> None:
    rows = {
        "title-fall-1": (0.080, 0.105), "title-fall-2": (0.128, 0.105),
        "title-fall-3": (0.176, 0.105), "title-fall-4": (0.224, 0.105),
        "title-diary-1": (0.065, 0.151), "title-diary-2": (0.113, 0.151),
        "title-diary-3": (0.161, 0.151), "title-diary-4": (0.209, 0.151),
        "title-diary-5": (0.257, 0.151),
    }
    for layer in title_event["layers"]:
        x, y = rows[layer["layerId"]]
        layer["textX"] = x
        layer["textY"] = y
        layer["fontSize"] = 52


def main() -> None:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    candidate_ticks = [0, 339_000, 474_000, 519_000, 609_000, 834_000,
                       879_000, 924_000, 1_194_000, 1_239_000, 1_530_000]
    assert all(tick % FRAME_TICKS == 0 for tick in candidate_ticks)
    assert candidate_ticks[0] == 0 and candidate_ticks[-1] == 17 * TIMEBASE

    events = copy.deepcopy(baseline["events"])
    background_ids = {
        "background-opening", "background-autumn-park", "background-picnic",
        "background-food-insert", "background-bouquet-close",
    }
    overlay_ids = {
        "overlay-pour-replacement", "overlay-basket-replacement", "overlay-park-figure",
        "overlay-coffee-close", "overlay-picnic-transition", "overlay-market-figure",
    }
    classifications = {
        "background-opening": "UNKNOWN",
        "background-autumn-park": "BACKGROUND_CUT",
        "background-picnic": "BACKGROUND_CUT",
        "background-food-insert": "UNKNOWN",
        "background-bouquet-close": "BACKGROUND_CUT",
        **{event_id: "OVERLAY_REPLACEMENT" for event_id in overlay_ids},
        "title-graphic": "UNKNOWN",
    }

    for event in events:
        event_id = event["eventId"]
        event["eventClassification"] = classifications[event_id]
        event["sourceEvidence"] = EVIDENCE[event_id]
        if event_id in overlay_ids:
            for layer in event["layers"]:
                layer["layerOrder"] = 1
                layer["fitMode"] = "contain"
                layer["positionX"] = 0.28
                layer["positionY"] = 0.30
                layer["scale"] = 0.18
                layer["keyframes"] = []
                layer["motionClassification"] = "UNVERIFIED"
        elif event_id in background_ids:
            layer = event["layers"][0]
            layer["fitMode"] = "cover"
            layer["layerOrder"] = 0
            layer["keyframes"] = _frame_keyframes(event["durationTicks"])
            layer["motionClassification"] = "EDITORIAL_MOTION"
        elif event_id == "title-graphic":
            _apply_safe_title_layout(event)
            for layer in event["layers"]:
                layer["motionClassification"] = "UNVERIFIED"

    definition = {
        **baseline,
        "version": "0.5.0-layer-structure-pilot",
        "name": "Fall Diary Layer Structure Pilot 0.5",
        "supportedCapabilities": [
            "full_frame_image", "hard_cut", "multi_layer_collage", "safe_area_contain_cards",
            "independent_visual_event_timing_90khz", "linear_keyframes_90khz",
            "dynamic_position_scale_rotation_opacity", "letter_tile_text_graphic",
            "preview_export_shared_renderer", "image_slot_reuse", "event_classification_evidence",
            "versioned_editorial_safe_layout",
        ],
        "metadata": {
            "layoutProfile": {"id": "editorial-safe-v1", "version": 1},
            "layoutIntent": "Keep title and contained cards in fixed canvas safe areas; no subject detection or face-aware placement.",
            "referenceLayoutBaseline": "fall-diary/0.4.0-editorial-motion-pilot and 0.3.0-reference-pilot",
            "editorialAssumptions": [
                "Background and overlay events are separate; candidate overlay replacements do not split the background timeline.",
                "The 1.2 percent linear background push-in is editorial motion and is not restored Muse keyframe data.",
                "Static overlay positions and smaller card scale are editorial layout choices.",
                "The end of the title event at 17 seconds is an explicit pilot assumption; reference visibility after 13.833 seconds is obscured.",
                "No cutout masks, segmentation, audio, or source media IDs are included.",
            ],
        },
        "slots": copy.deepcopy(baseline["slots"]),
        "events": events,
        "demoAssetReference": None,
        "posterAssetReference": None,
        "audioAssetReference": None,
        "assetDependencies": [],
    }
    OUTPUT.write_text(json.dumps(definition, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"created {OUTPUT.relative_to(ROOT)}: {len(definition['slots'])} slots, "
          f"{len(definition['events'])} independent events")


if __name__ == "__main__":
    main()
