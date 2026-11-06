# Fall Diary — WPF preview and shared-render parity, Task 3.9D

## Exact project identity

| Field | Value |
|---|---|
| Project ID | `73da1503e49b403f9ad5c56f7d4d688c` |
| Project revision | `2` |
| Template | `fall-diary / 0.3.0-reference-pilot` |
| Slot count | 11 required image slots, `photo-01`…`photo-11` |
| Binding SHA-256 | `88113c8337f15adf0723d0604c286301e84a2caa07f5260e827b812241896a34` |
| Composition Graph source fingerprint | `365753eb926ffb71d6d5d0bef37a0eedd24ca12d02b88564684cb1d039eb6e6b` |
| Duration | 1,530,000 ticks / 90,000 ticks per second = 17.000 s |
| Frame rate | 30/1; 510 frames |

The WPF-created proxy preview was copied from the Media Studio draft preview cache for this exact revision. The full-resolution output was rendered from the copied Project V2 with the existing shared Composition Graph renderer. Both files were probed and fully decoded. The in-app Screen 6 export command was not completed; this is renderer parity, not GUI export acceptance.

## Outputs and measurements

| Output | Dimensions | Video | Duration | Audio | Decode |
|---|---:|---|---:|---:|---|
| `Fall_Diary_Reference_Pilot_Preview.mp4` | 540×960 | H.264, 30 fps, 510 frames | 17.000 s | none | FFmpeg full decode passed |
| `Fall_Diary_Reference_Pilot_Render.mp4` | 1080×1920 | H.264, 30 fps, 510 frames | 17.000 s | none | FFmpeg full decode passed |

- 13 exact frame indices were extracted from both outputs, including opening, scene/overlay boundaries, and final frames. The full-resolution render was resized to 540×960 for per-pixel comparison.
- Sampled mean RGB MAE: **5.8456/255**. Highest sampled frame mean RGB MAE: **6.98234/255**. Stated thresholds (mean ≤12, each sample ≤24) pass.
- Full-sequence SSIM: **510/510 aligned frames**, mean **0.92632286**, minimum **0.914221** after downscaling the export to preview dimensions.
- This compares two encodes of the same graph. It is not a reference-fidelity score and does not establish equality between the Muse demo and the pilot.
- Slot binding and graph fingerprints match the Project V2 snapshot. Source media hashes matched before and after rendering.
- The original Task 3.9C revision 1 baseline Project V2 was restored byte-for-byte after the in-app edit attempt; its saved artifact and runtime file SHA-256 both equal `5e71fe677376ccd32828325498508a89dc68cd3f2648bd8a17affc6cb1eddda7`. Revision 2 is kept as a separate Task 3.9D artifact.

## GUI boundary

The WPF app created the revision 2 preview cache file, but after the media-update route completed it returned to Template Details. The Export screen was not reached. Therefore:

```text
WPF_PREVIEW_FILE_GENERATED=true
SHARED_RENDER_PARITY_VERIFIED=true
WPF_SCREEN06_EXPORT_VERIFIED=false
FALL_DIARY_PREVIEW_EXPORT_PARITY_VERIFIED=false
FALL_DIARY_SIX_SCREEN_GUI_VERIFIED=false
GUI_STATUS=GUI_PENDING
```

The visual contact sheet is [Fall_Diary_WPF_Preview_Export_Comparison.jpg](../../artifacts/video_creator/task3_9d/Fall_Diary_WPF_Preview_Export_Comparison.jpg). Machine-readable metrics are in [Fall_Diary_Reference_Pilot_Manifest.json](../../artifacts/video_creator/task3_9d/Fall_Diary_Reference_Pilot_Manifest.json).

