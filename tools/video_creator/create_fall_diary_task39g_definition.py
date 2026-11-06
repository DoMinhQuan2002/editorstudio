"""Create the versioned 3.9G definition from the reviewed 0.3 timing baseline."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFINITIONS = ROOT / "backend/mediastudio/video_editor/definitions"
BASELINE = DEFINITIONS / "fall-diary-0.3.0-reference-pilot.json"
OUTPUT = DEFINITIONS / "fall-diary-0.4.0-editorial-motion-pilot.json"


def main() -> None:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    candidate_ticks = [0, 339_000, 474_000, 519_000, 609_000,
                       834_000, 879_000, 924_000, 1_194_000, 1_239_000, 1_530_000]
    starts = candidate_ticks[:-1]
    durations = [end - start for start, end in zip(candidate_ticks, candidate_ticks[1:])]
    assert sum(durations) == baseline["durationTicks"]
    assert all(tick % 3_000 == 0 for tick in candidate_ticks)

    names = [
        "shot-opening", "shot-tea-insert", "shot-market-basket", "shot-autumn-wide",
        "shot-autumn-figure", "shot-latte-insert", "shot-picnic-insert",
        "shot-autumn-still-life", "shot-food-detail", "shot-flower-ending",
    ]
    slots = [
        {"slotId": f"photo-{index:02d}", "allowedMediaKinds": ["image"],
         "required": True, "reusePolicy": "allow", "missingSlotPolicy": "error"}
        for index in range(1, 12)
    ]
    events = []
    for index, (name, start, duration) in enumerate(zip(names, starts, durations), start=1):
        # A restrained, constant-rate push-in is an editorial treatment for still
        # photos. It is not presented as motion restored from the Muse recording.
        end_scale = round(1.0 + 0.012 * duration / 90_000, 6)
        layer = {
            "layerId": f"{name}-image", "kind": "image", "layerOrder": 0,
            "slotId": f"photo-{index:02d}", "fitMode": "cover",
            "positionX": 0.0, "positionY": 0.0, "scale": 1.0,
            "rotation": 0.0, "opacity": 1.0, "effect": "none",
            "keyframes": [
                {"property": "scale", "timeTicks": 0, "value": 1.0,
                 "interpolation": "linear", "easing": "linear"},
                {"property": "scale", "timeTicks": duration, "value": end_scale,
                 "interpolation": "linear", "easing": "linear"},
            ],
        }
        events.append({"eventId": name, "timelineStartTicks": start,
                       "durationTicks": duration, "layers": [layer]})

    card_events = []
    for event_id, start, duration in (
        ("editorial-card-autumn-figure", 609_000, 225_000),
        ("editorial-card-still-life", 924_000, 270_000),
    ):
        card_events.append({
            "eventId": event_id, "timelineStartTicks": start, "durationTicks": duration,
            "layers": [{
                "layerId": f"{event_id}-image", "kind": "image", "layerOrder": 1,
                "slotId": "photo-11", "fitMode": "contain", "positionX": 0.28,
                "positionY": 0.30, "scale": 0.24, "rotation": 0.0, "opacity": 1.0,
                "effect": "none", "keyframes": [
                    {"property": "positionX", "timeTicks": 0, "value": 0.28,
                     "interpolation": "linear", "easing": "linear"},
                    {"property": "positionX", "timeTicks": duration, "value": 0.24,
                     "interpolation": "linear", "easing": "linear"},
                    {"property": "positionY", "timeTicks": 0, "value": 0.30,
                     "interpolation": "linear", "easing": "linear"},
                    {"property": "positionY", "timeTicks": duration, "value": 0.24,
                     "interpolation": "linear", "easing": "linear"},
                    {"property": "scale", "timeTicks": 0, "value": 0.24,
                     "interpolation": "linear", "easing": "linear"},
                    {"property": "scale", "timeTicks": duration, "value": 0.27,
                     "interpolation": "linear", "easing": "linear"},
                ],
            }],
        })

    title = next(event for event in baseline["events"] if event["eventId"] == "title-graphic")
    title["timelineStartTicks"] = 0
    title["durationTicks"] = baseline["durationTicks"]
    events.append(title)

    definition = {
        **baseline,
        "version": "0.4.0-editorial-motion-pilot",
        "name": "Fall Diary Editorial Motion Pilot 0.4",
        "supportedCapabilities": [
            "full_frame_image", "hard_cut", "multi_layer_collage", "safe_area_contain_cards",
            "independent_visual_event_timing_90khz",
            "linear_keyframes_90khz", "dynamic_position_scale_rotation_opacity",
            "letter_tile_text_graphic", "preview_export_shared_renderer",
            "image_slot_reuse", "editorial_slow_push_in",
        ],
        "slots": slots,
        "events": events + card_events,
        "demoAssetReference": None,
        "posterAssetReference": None,
        "audioAssetReference": None,
        "assetDependencies": [],
    }
    OUTPUT.write_text(json.dumps(definition, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"created {OUTPUT.relative_to(ROOT)}: {len(slots)} slots, {len(events)} events")


if __name__ == "__main__":
    main()
