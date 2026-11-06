# Fall Diary — effect acceptance matrix 3.9B

## Gate policy

`VERIFIED` below means the named effect was exercised by this task's template binding/render evidence. It does not imply visual equivalence to Muse, release readiness, or GUI acceptance.

| Capability / gate | Definition or runtime implementation | Evidence | Result |
|---|---|---|---|
| Exact template identity / version | `fall-diary`, `0.2.0-motion-pilot`; explicit lookup by version | Definition, Project V2 metadata, Manifest | PASS |
| Legacy 0.1 rollback | Version map still loads `0.1.0-pilot`; original definition/artifacts are unchanged | Baseline compiler regression and pinned-version tests | PASS |
| Slot binding | 12 actual private images bound by exact `photo-01`…`photo-12` IDs | Compiler → Project V2 → Composition Graph, source SHA before/after | PASS for backend binding; UI picker not exercised |
| Reuse policy | 0.2 permits reuse; 0.1 retains `unique_asset` | Media selection regression for both policies | PASS |
| Static transforms backward compatibility | Static scale/position/rotation/opacity continue to compile/render | existing video editor + 3.9A regression | PASS |
| Animated X/Y/scale/rotation/opacity | 90 kHz tick keyframes, linear interpolation, event boundary validation, common preview/export graph | unit tests, render filtergraph and same-event frame evidence | PASS |
| Non-hard-cut motion | Dynamic keyframes inside same visual event | first event samples 0.25/1.25/2.25 s differ; MAE 28.4749/255 from first to last | PASS |
| Dynamic collage / layer order | Layer density varies across events; ascending order remains back-to-front | 2/3/3/2/4/3 layers and Composition Graph | PASS |
| Text graphic and scaling | Separate text clips with word box/color/border/shadow; 1080p design-space sizing | frame evidence at intro; 540p and 1080p output decode | PASS for implemented style; reference style match not claimed |
| Source alpha compositing | Existing RGBA alpha can be passed through renderer | translucent PNG in second fixture set; H.264 compositing output | PASS as alpha compositing only |
| Foreground segmentation/cutout | No suitable model or segmentation pipeline integrated | package capability inspection; existing lab is guided/manual | **BLOCKED / NOT VERIFIED** |
| Animated crop/pan | No keyframe semantics for crop rectangle | not implemented | NOT SUPPORTED |
| Easing curves | Only linear interpolation is accepted | schema validation | Other easing NOT SUPPORTED |
| Fade/wipe and advanced transitions | Not part of graph contract | unsupported guard regression | NOT SUPPORTED |
| Video media in Fall Diary 0.2 | Definition slots are image-only; no real video fixture in this QA run | definition and test source inventory | NOT VERIFIED / NOT ADVERTISED |
| Audio transport | Synthetic 440 Hz QA track; fade in/out; AAC stereo in preview/export | ffprobe 15 s both files; start=0; RMS near fade edges is lower than center | PASS for QA transport only |
| Audio/reference fidelity | No licensed source track or reliable musical timing | demo audio omitted | **NOT VERIFIED** |
| Full decode / format | 540×960 preview + 1080×1920 export, H.264, 30 fps, 450 frames, AAC | FFprobe + FFmpeg null full decode | PASS |
| Preview/export parity | 450-frame SSIM + exact frame extraction at 8 times | mean 0.904437, min 0.809201; same-size MAE mean 5.4952/255 | PASS by stated QA thresholds |
| GUI acceptance | WPF app navigation or interactive preview not exercised in this renderer task | no runtime GUI screenshot | NOT RUN |
| Reference fidelity / users | Motion is a QA design; reference timing/keyframes/cutout unknown | comparison report | **FALSE / NOT READY** |

## Audio measurement detail

The runner synthesizes a 440 Hz sine at 48 kHz solely for test. A 250 ms fade-in and 500 ms fade-out are applied by the existing audio mixer; AAC output is 44.1 kHz stereo. Decoded samples in each MP4 are exactly 720,000 mono floats at the analysis rate (15.000 s), with video/audio start time 0.000 s. Measured RMS:

| Window | Preview | Export |
|---|---:|---:|
| 0–50 ms | 0.000610 | 0.000610 |
| 7.4–7.6 s | 0.005305 | 0.005305 |
| 14.0–14.05 s | 0.005304 | 0.005304 |
| 14.95–15.0 s | 0.000307 | 0.000307 |

This verifies the QA tone path, fade processing and AAC alignment. It is not proof of matching the reference soundtrack or of in-UI playback acceptance.

## Regression and safety

Related backend suite result: **97 passed, 3 skipped, 10 subtests passed**. `dotnet test MediaStudio.sln --no-restore` built the WPF Desktop/test projects and completed **54 passed, 0 failed**. Original media SHA-256 values match before/after render; source images were read in place and not copied. Output artifacts live in the separate `task3_9b` directory; Task 3.9A video/definition was not overwritten. No renderer starts a template export job as a user workflow, and there is no success claim for a rendered MP4 from the Media Selection screen.
