# TASK 2.2A — API Preview/Export parity

## Contract

Both endpoints load the canonical V2 project and build `CompositionGraph v1`. Preview chooses the frame index from 90 kHz ticks, selects all active visual/text clips and reports graph version, renderer and source fingerprint. Export uses the same absolute timeline/source mapping, layer-order and interval rules; FFmpeg graph preview is also the fallback for native preview cases not handled by the C++ pixel compositor. API export no longer routes V2 projects through the old sequential scene renderer.

The regression compared decoded export frames to the protected Task 2.0B Denim Story MP4 at 13 timestamps. Threshold: RGB MAE ≤18, allowing H.264 encode differences. All 13 passed; MAE range was 0.83998–2.44187. The export and baseline both fully decoded. The output used H.264 1080×1920 at 30 fps and AAC 44.1 kHz stereo; container duration was 37.608005 s and video duration 37.600 s. Hash equality is not required for graph export.

| Baseline frame time (s) | Frame index | RGB MAE | Result |
|---:|---:|---:|---|
| 0.0 | 0 | 1.11353 | PASS |
| 2.9 | 87 | 1.11215 | PASS |
| 3.1 | 93 | 1.50524 | PASS |
| 5.9 | 177 | 2.44187 | PASS |
| 6.1 | 183 | 1.37553 | PASS |
| 8.9 | 267 | 1.37561 | PASS |
| 9.1 | 273 | 1.44098 | PASS |
| 11.9 | 357 | 2.24730 | PASS |
| 12.1 | 363 | 0.86004 | PASS |
| 14.9 | 447 | 0.86169 | PASS |
| 15.1 | 453 | 0.86169 | PASS |
| 20.0 | 600 | 0.86171 | PASS |
| 37.5 | 1125 | 0.83998 | PASS |

Four actual API Preview PNGs were compared with decoded frames from the same export: 0.5 s (FFmpeg fallback), 14.9 s, 15.1 s and 37.5 s (native C++). All passed MAE ≤18; values were 1.19229, then 5.51477 for each native-tail sample. Synthetic checks also compare native video/image overlay previews with export, alpha pixels, text boundaries and black visual gaps.

Audio comparison extracted stereo f32 at 44.1 kHz and compared matching 200 ms windows. Correlations and RMS are recorded in `denim-regression-summary.json`. Four windows all pass correlation ≥0.999; the output stays aligned through the 37.608 s audio tail while the last visual frame is held under the legacy-only policy.

## Diagnosis fixed during this task

The first graph export left later clips black because it tested absolute visibility intervals but left each trimmed clip stream at PTS zero. The export compiler now shifts each clip to `timelineStartTicks` before overlay. It also applies the old renderer's input-count normalization only to the legacy-compatible subset; new multi-track mixes remain direct sums. The final metrics above were generated after both fixes.

## Artifacts

- `artifacts/video_editor/task2_2a_validation/denim_linear_graph_20261022_fix2/denim_task22a_api_composition.mp4`
- `.../denim-regression-summary.json`
- `.../preview-export-parity.json`
- Baseline, preview PNGs, baseline/candidate sample frames and ffprobe output are in that same directory.
