# Keyframe contract — Template Compiler / Project V2

## Canonical representation

Each visual layer may have `keyframes[]` entries in its existing V2 `properties` object. No Project V2 schema-version bump was needed because `TimelineClipV2.properties` is already extensible and its canonical timeline uses `timebase=90000`.

```json
{
  "property": "positionX",
  "timeTicks": 0,
  "value": 0.22,
  "interpolation": "linear",
  "easing": "linear"
}
```

Supported properties and accepted ranges:

| Property | Range |
|---|---:|
| `positionX`, `positionY` | −2.0 … +2.0, relative to centered layer placement |
| `scale` | 0.1 … 5.0 |
| `rotation` | −180° … +180° |
| `opacity` | 0 … 1 |

`timeTicks` is an integer tick offset from the beginning of the layer's event/clip. Every animated property must contain at least two distinct keys, start at 0, and end exactly at the event duration. Values outside the property range, keys past event end, duplicate times, unknown fields/properties, non-finite values, or unsupported interpolation/easing fail validation. Intermediate keys are allowed. Only linear interpolation with linear easing is accepted.

## Evaluation rules

For keys `(t0, v0)` and `(t1, v1)` enclosing `t`, evaluate:

```text
u = (t - t0) / (t1 - t0)
value(t) = v0 + (v1 - v0) * u
```

The shared function `template_keyframes.interpolate_keyframes` evaluates still-preview values in integer Project V2 ticks. `keyframe_expression` emits the corresponding bounded piecewise-linear FFmpeg expression for movie rendering. Frame-rate conversion only selects the output frame; it does not redefine animation time. Tested frame rates are 24, 25, 30, 60 and 30000/1001 where 90 kHz can represent each rate exactly.

## Preview/export timing

- Preview snaps requested timeline tick to `CompositionGraph.frame_start_ticks(frame_index)` before interpolation.
- Scale and rotation run before export PTS is moved to the clip's global timeline start, so their FFmpeg time variable is clip-local.
- Overlay X/Y and opacity run after PTS is placed on the global composition timeline; their expression subtracts the clip's timeline start to recover the same local time.
- Export and preview share `composition_renderer.build_composition_command`; still-preview values are resolved using `interpolate_keyframes` and then fed through the same image transform/order path.
- Each test event's first/last keys equal its event duration in ticks, including fractional millisecond durations. Graph validation uses `TimelineClipV2.duration_ticks`, not truncated `durationMs` compatibility fields.

## Compatibility and limits

- Static transform definitions omit the optional `keyframes` field from their `VideoClip` legacy projection. Dynamic values remain on canonical Project V2 and Composition Graph; old projection intentionally removes only unsupported keyframe/style fields.
- A native preview engine does not evaluate keyframes, so the still preview falls back to FFmpeg whenever it sees animation.
- Text keyframes, crop/pan animation, easing curves other than linear, non-cut transitions, and crossfade semantics are rejected/not advertised.
- `opacity` evaluates source alpha when present and multiplies it over time. This does not synthesize a subject mask or mean foreground cutout is supported.

## Test evidence

- `backend/tests/test_fall_diary_task39b.py`: interpolation, timebase rate matrix, range/endpoint validation, definition versioning, V2 Graph preservation and legacy API projection.
- `backend/tests/test_template_compiler_task34.py`: generic keyframes survive compiler-to-graph mapping; unsupported mask/cutout/transition still reject.
- `artifacts/video_creator/task3_9b/Fall_Diary_Motion_Manifest.json`: exact frame hashes, motion sample differences, 8 same-resolution preview/export frame comparisons and 450-frame SSIM results.
