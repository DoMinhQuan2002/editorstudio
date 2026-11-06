# Video Editor release gates

> **RETIRED_PRODUCT_REQUIREMENT (TASK 3.0A, 2026-10-22):** các gate CapCut/NLE trong tài liệu này đã bị nghỉ. Giữ nguyên các kết quả TASK 2.x làm technical history; tiêu chí sản phẩm hiện hành nằm tại [Video Creator release gates](../video_creator/VIDEO_CREATOR_RELEASE_GATES.md). Engine V2 regression vẫn cần kiểm tra, nhưng không kéo theo yêu cầu NLE UI.

## Current decision (2026-10-22)

```text
TASK2_0B_RUNTIME_ACCEPTED = false
CAPCUT_9_6_0_REFERENCE_COMPLETE = false
MULTITRACK_COMPOSITOR_VERIFIED = false
VIDEO_EDITOR_RELEASE_READY = false

TASK2_1_MODEL_READY = true
TASK2_1_PERSISTENT_TIMELINE_READY = false
TASK2_1_LINEAR_RENDER_COMPATIBLE = false
```

Keep the three TASK 2.1B outcomes separate: API/store persistence is PASS within fixture scope; WPF interaction is PARTIAL/BLOCKED pending GUI acceptance; API linear render is PASS for the Denim fixture, while WPF preview/export remain BLOCKED. None closes another gate.

## Gate 1 — Replace WPF stress

**PENDING.** Require 20 actual WPF Replace operations, including at least 10 consecutive; R01–R10; Replace while filmstrip loads and preview plays; image↔video; cancel; undo/redo; Save/Reopen; no backend crash, lost data or incorrect binding. API PUT count is not a Replace count. Each accepted Replace needs UI action evidence plus target clip binding change.

## Gate 2 — CapCut Desktop 9.6.0 interaction reference

**PENDING.** Confirm About/build for 9.6.0. Keep Insert, Replace, overlay, hover/ghost/drop zones, snap/magnet, ripple, linkage, split/trim/delete, track interaction, keyboard modifiers and undo/redo as reference pending until recordings/evidence establish them. Do not infer from another version.

## Gate 3 — Multitrack preview/export

**PENDING at overall product-release scope.** TASK 2.2A now verifies the declared API/native subset: multi-visual composition, video/image alpha overlay, layer order, timed text, two-tone audio overlap, source offsets, gaps, frame-rate matrix, Preview/Export comparison and the protected Denim baseline. See [TASK 2.2A report](../../VIDEO_EDITOR_TASK2_2A_REPORT.md) and the capability matrix. Transitions and same-track visual overlap are rejected; advanced transform parity and track mute/solo edge cases remain unverified. WPF preview/export and CapCut 9.6.0 reference acceptance remain pending. This API/native evidence does not change the existing product gate or release flags.

## Gate 4 — Persistent project data and migration

**PASS automated for API/store fixture scope; WPF runtime acceptance pending.** The Task 2.1B isolated V1 migration verified backup SHA-256, V2 Save, independent store/API reopen and stable Track ID, Clip ID, layer order and revision. Project V2/API regression suite: 25 passed; included audio suite: 5 passed; timeline suite: 3 passed. The V1 source remained unchanged. This does not establish WPF editing correctness or migration safety for every user project.

## Gate 5 — WPF runtime acceptance

**BLOCKED / NOT RUN.** No WPF GUI session was available to perform and capture mouse-driven acceptance. Follow [TASK2_1B_MANUAL_ACCEPTANCE.md](TASK2_1B_MANUAL_ACCEPTANCE.md) for drag/drop, track identity, trim, undo/redo, Save/Reopen, preview and WPF export. .NET build and 122 passing tests do not replace GUI evidence.

## Linear V2 export regression

**PASS API/C++ export for one isolated Denim Story fixture; overall gate remains PENDING.** `artifacts/video_editor/task2_1b_validation/` holds the Task 2.0B baseline, migrated V2 before/save/reopen JSON, API render MP4 and `inspect_export.py` outputs. Baseline and candidate were both H.264 1080×1920 at 30 fps, AAC 44.1 kHz stereo, 37.608005 s container; both fully decoded. All 13 required frame samples were pixel-identical and four audio windows had correlations ≥0.99999989. SHA-256 also matched exactly for this fixture. The render was requested via API, not WPF, and WPF preview has not been compared; therefore `TASK2_1_LINEAR_RENDER_COMPATIBLE=false` remains.

## Evidence rules

- Keep test scope, command, count and result attached to every PASS.
- Distinguish prior Task 2.0B data from new Task 2.1B V2 evidence.
- Preserve source projects, backups, QA artifacts and logs; test only on isolated copies.
- A model/API PASS never implies WPF or renderer parity PASS.
- Do not infer a release gate from architecture completion or screenshot similarity.

## TASK 2.2A backend evidence (2026-10-22)

- Composition Graph, visual compositor subset, audio mixer subset, API Preview/Export parity and the linear Denim regression passed their TASK2_2A-specific criteria. The implementation flags and measurements are in `VIDEO_EDITOR_TASK2_2A_REPORT.md`.
- Selected Video Editor regressions: **60 passed**, including 27 TASK 2.2A tests; the same 27 composition tests passed under an AddressSanitizer-instrumented native Video Engine. FFmpeg libraries were not instrumented.
- `TASK2_1_PERSISTENT_TIMELINE_READY`, `TASK2_1_LINEAR_RENDER_COMPATIBLE`, `TASK2_0B_RUNTIME_ACCEPTED`, `CAPCUT_9_6_0_REFERENCE_COMPLETE`, `MULTITRACK_COMPOSITOR_VERIFIED` and `VIDEO_EDITOR_RELEASE_READY` remain at their prior values. No WPF mouse-driven runtime session was run in this task.

## TASK 2.2B WPF integration (2026-10-22)

```text
TASK2_2B_CANONICAL_EDITING_READY = false
TASK2_2B_WPF_MULTITRACK_VERIFIED = false
TASK2_2B_WPF_PREVIEW_VERIFIED = false
TASK2_2B_WPF_AUDIO_PLAYBACK_VERIFIED = false
TASK2_2B_WPF_EXPORT_VERIFIED = false
TASK2_2B_GUI_ACCEPTANCE = BLOCKED

TASK2_0B_RUNTIME_ACCEPTED = false
TASK2_1_PERSISTENT_TIMELINE_READY = false
TASK2_1_LINEAR_RENDER_COMPATIBLE = false
CAPCUT_9_6_0_REFERENCE_COMPLETE = false
MULTITRACK_COMPOSITOR_VERIFIED = false
VIDEO_EDITOR_RELEASE_READY = false
```

The WPF V2 preview now calls the Composition Graph frame endpoint with a current snapshot, tracks request revision/fingerprint metadata, coalesces scrubs and ignores stale responses. WPF V2 export now submits Composition Graph render jobs and guards the selected destination with a partial file and MP4 signature check. WPF audio preview supports standalone clips and video source audio with offsets/fades, but its separate MediaPlayers are not proven equivalent to the graph mixer.

New automated results for this task: .NET **126 passed**; selected Python Composition Graph suite **24 passed, 3 skipped, 10 subtests passed**; Release `win-x64` publish succeeded. A 5-second multi-track fixture and isolated launcher are prepared in `artifacts/video_editor/task2_2b_validation/`.

Canonical editing is still **PARTIAL** because compatibility arrays are reconciled into canonical tracks on save/preview, several editor timing paths retain millisecond projection semantics, and undo/redo remains ViewModel snapshot history. GUI acceptance was not run: W01–W26 remain BLOCKED / NOT RUN. WPF Save/Reopen, cross-track interaction, preview content, audio sync, WPF export, full decode and preview/export parity are therefore not accepted. See [TASK 2.2B report](../../VIDEO_EDITOR_TASK2_2B_REPORT.md) and [manual checklist](TASK2_2B_MANUAL_ACCEPTANCE.md).
