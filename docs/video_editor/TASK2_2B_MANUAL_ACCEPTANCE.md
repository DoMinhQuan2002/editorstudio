# TASK 2.2B — WPF Manual Acceptance

## Start the isolated build

The isolated app is already open in this session. If it has been closed, start it from the workspace root with:

```powershell
powershell -ExecutionPolicy Bypass -File tools\launch_task22b_wpf_acceptance.ps1
```

The app uses `artifacts\video_editor\task2_2b_validation\runtime-data`. It opens on Image Tools; switch to **Video Editor**, then open **TASK 2.2B — WPF Multitrack** from the project list. Do not point the app at personal projects for this test. Its startup log is `artifacts\video_editor\task2_2b_validation\backend-wpf-20261022-111418.log` for the current run.

After saving and reopening the fixture, collect evidence (use the exact backend log path printed by the launcher):

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'backend')
backend\.venv\Scripts\python.exe backend\tools\collect_task22b_wpf_evidence.py `
  --data-directory artifacts\video_editor\task2_2b_validation\runtime-data `
  --artifact-directory artifacts\video_editor\task2_2b_validation `
  --backend-log '<backend-log-path>' `
  --phase after `
  --export '<WPF-export.mp4>'
```

Run with `--phase after` only after Save/Reopen. This creates a dated folder under `artifacts/video_editor/task2_2b_validation/collected/` with the baseline `before.json`, current `after.json`, `log-summary.json` and, when export was supplied, `inspect-export.json`. A normal capture uses `snapshot.json` so it cannot be mistaken for a persistence round-trip. The collector reads project/log/export inputs and writes new evidence files.

## Cases

Record PASS/FAIL/BLOCKED and attach a screenshot or video plus collected JSON when applicable.

| ID | Action | Expected evidence | State |
|---|---|---|---|
| W01–W16 | Repeat the current [TASK 2.1B manual checklist](TASK2_1B_MANUAL_ACCEPTANCE.md), including media binding, save/reopen, trim, audio and export | Existing checklist evidence and stable IDs | BLOCKED / NOT RUN |
| W17 | Play base video with overlay active | Both visual layers visible at the same graph timestamp | BLOCKED / NOT RUN |
| W18 | Inspect alpha PNG edges before, during and after 1–4.5 s activity | Transparent corners preserve the base; overlay appears only in interval | BLOCKED / NOT RUN |
| W19 | Reorder visual tracks and scrub | Layer order in JSON matches preview | BLOCKED / NOT RUN |
| W20 | Play both audio clips across 0–8 s and seek into their overlap | Both sources audible at offsets; note audible skew/loudness | BLOCKED / NOT RUN |
| W21 | Export fixture from WPF | MP4 has expected streams, duration/audio tail and full decode | BLOCKED / NOT RUN |
| W22 | Compare preview and export from same saved project revision | Record revision, graph version/fingerprint, timestamps and ROI evidence | BLOCKED / NOT RUN |
| W23 | Rapidly scrub while overlay and text are active | Final displayed frame corresponds to final seek; no persistent stale frame | BLOCKED / NOT RUN |
| W24 | Save, close/reopen, compare JSON | Track IDs, clip IDs, layer order, ticks and media bindings persist | BLOCKED / NOT RUN |
| W25 | Exercise unsupported effect or media error | Clear diagnostic; no false success or silent track removal | BLOCKED / NOT RUN |
| W26 | Run a copied, fully populated Denim Story through WPF | H.264/AAC export and baseline comparison evidence | BLOCKED / NOT RUN |

Also retain the original Replace stress gate: 20 actual WPF replacements, 10 consecutive, confirm/cancel, undo/redo, Save/Reopen, correct Clip ID/Media ID, and no crash. API PUT counts do not count as Replace operations.

Manual WPF acceptance controls the GUI-dependent flags. Passing model or API checks does not change these rows automatically.
