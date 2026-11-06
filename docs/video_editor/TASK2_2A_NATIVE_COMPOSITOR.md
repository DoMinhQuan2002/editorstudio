# TASK 2.2A — Native visual compositor

## Preview path

`composition_renderer.py` obtains active V2 visual clips at one exact output frame, maps each to a source timestamp, and decodes video through `msve_decode_frame_rgba_ticks`. Images are loaded as RGBA. The native API `msve_compose_preview_bgra` composites up to 32 active layers on a BGRA canvas. C++ source sampling is bilinear; fit (`cover`/`contain`), scale, position, rotation, opacity and layer order are passed from the graph. Project image data uses straight alpha.

For the opaque destination canvas, the tested blend law is `Cout = Csrc × (sourceAlpha × opacity) + Cdst × (1 − effectiveAlpha)`. Tests cover PNG transparent, half-alpha and opaque regions, with a separate video base. Reordering the track layers changes the native preview result. Two video layers are decoded/composited in one request, and repeated seeks across two sources run under concurrency.

Native preview deliberately falls back to the FFmpeg graph if an active text layer/effect is present, required native ABI is unavailable, or the native layer cap is exceeded. This preserves output content. Text uses `drawtext` from the same graph contract. Transitions are rejected. Advanced geometry/effect parity is not claimed.

## Export path

Export compiles the same graph into FFmpeg filters: source trim, timestamp reset, absolute timeline `setpts`, geometry/fit, alpha, layer overlay, text timing and output duration. The C++ `msve_render_ffmpeg_arguments` routine is the cancellation/progress process host; FFmpeg performs the export filters and H.264/AAC encoding. This is a real multi-layer graph export and retains the editable V2 project; no clip list is flattened or replaced.

## Verified subset

- Two simultaneous video tracks, overlay start/end and track order.
- Video base plus image overlay with alpha 0, 128 and 255 and clip opacity.
- Text active interval and its disappearance in preview/export.
- Absolute timeline/source mapping, visual gaps and half-open end boundaries.
- Native preview vs decoded export frame MAE threshold 18; API preview fallback and native paths both sampled.

Effect-specific visual appearance, non-zero rotation/scale parity, complex color management and transition semantics remain unverified or unsupported. The graph rejects unknown effect/style properties rather than omitting them silently.

## Files

- `backend/native/video_engine/src/video_engine.cpp`, `video_engine.h`
- `backend/mediastudio/video_editor/native_engine.py`
- `backend/mediastudio/video_editor/composition_renderer.py`
- `backend/tests/test_video_editor_task22a_composition.py`
