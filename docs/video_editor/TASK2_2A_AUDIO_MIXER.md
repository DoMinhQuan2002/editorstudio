# TASK 2.2A — Audio graph and mix policy

Audio clips retain V2 track/clip IDs, timeline start, source start, duration, per-clip volume and fade times. Video sources with embedded audio are also routed when enabled, unless audio solo semantics exclude them. FFmpeg filters reset source timestamps, trim source range, resample to 48 kHz float, convert to stereo, apply volume/fades, delay in samples on the timeline, pad only to composition end, and trim at the clip/output end. Final audio is resampled to 44.1 kHz stereo and encoded AAC.

Two mix policies are explicit in `CompositionGraph.audioMixPolicy`:

| Project category | FFmpeg policy | Reason |
|---|---|---|
| Legacy-linear compatibility subset | `amix normalize=1` | Preserve measured Task 2.0B/2.1B gain law and byte-independent baseline behavior. |
| New multi-track project | `amix normalize=0` | Sum each clip's stored gain directly; do not add automatic gain normalization. |

No limiter, ducking or loudness normalization is applied. New multi-track sums can clip if the source gains/levels exceed full scale; this is measured/documented behavior and is not hidden by automatic processing. Legacy input-count normalization is only the compatibility path.

## Evidence

- Two synthetic audio tracks overlap: 440 Hz mono/48 kHz and 880 Hz stereo/44.1 kHz. Spectrum tests detect both tones only in the overlap, verify the second source offset and fades, and verify silence after both clips end.
- A video with embedded 440 Hz audio mixed with a separate 880 Hz audio clip contains both frequencies in the export.
- The protected Denim baseline has four 200 ms audio-window comparisons: correlations 0.9999999990, 0.9999999986, 0.9999742920 and 0.9998755738. RMS levels also match the baseline within AAC encode tolerance.

Mixing and gain behavior are not asserted to match CapCut 9.6.0; no CapCut audio export reference was supplied for this task. See the [validation summary](../../artifacts/video_editor/task2_2a_validation/denim_linear_graph_20261022_fix2/denim-regression-summary.json) and the fixture test module.
