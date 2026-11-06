# Persistent Track Engine report

## Domain engine

`TimelineEngineV2` is a backend domain core independent of WPF. It owns a validated `VideoProjectV2` snapshot and offers:

- Create track; remove only empty track; reorder persistent tracks.
- Add/remove clip; move on track; move between compatible track kinds.
- Change absolute timeline start; trim source in/out; split clip.
- Read/update track state; validate clip placement.
- Snapshot undo/redo preserving IDs and unrelated timestamps.

All timestamps are absolute ticks. Cross-track overlaps and same-start clips are permitted. Gaps are represented as time, not synthetic clips. Cross-track move changes only the clip's track ID and optional start; it does not generate a new clip ID. Track identity stays fixed when contents change.

Same-track overlap is deliberately unresolved. Placement reports `REFERENCE_PENDING` and edit commands refuse it; there is no guessed replace/ripple policy. No first-fit operation runs after move/trim. Legacy audio grouping occurs once as migration bootstrap only.

## WPF integration status

WPF DTOs carry schema, frame rate, timebase, canonical tracks, per-track clip ID/kind/start/source/duration ticks, track state, template metadata and extensions. `RebuildTimeline` uses persisted tracks ordered by `LayerOrder`; track rows are matched by Track ID and empty persisted tracks survive. Audio items keep their stable `LaneTrackId`, not a per-edit first-fit lane.

TASK 2.1B adds `TimelineV2EditCommands` and connects persistent track creation/reorder/removal, media add, audio routing and clip move to the WPF ViewModel. The row resolver supplies the target Track ID and tick position. Save validates that compatibility projections still contain every canonical clip. The Free Editor button is connected to the V2 API.

WPF integration is **partial**, not runtime-accepted: drag/drop and Save/Reopen were not manually exercised. Visual/audio trim commands now mutate canonical ticks and then update compatibility projections. WPF undo/redo still saves ViewModel project snapshots rather than invoking `TimelineEngineV2` history. Therefore `TASK2_1_PERSISTENT_TIMELINE_READY=false` remains.

## Tests run

- TASK 2.1B rerun: 25 Python Project V2/API, 5 audio Task 1F, and 3 timeline Task 1D tests passed (33 total).
- 122 .NET tests passed, including persistent track projection, empty track display, precision guard, V2 edit command invariants, trim range and refusal to mutate unsupported multitrack data.

Automated projection coverage is not equivalent to WPF mouse testing. The CapCut 9.6.0 interaction reference remains incomplete.

## Renderer contract

`render_capability()` permits only the supported linear subset, including compatible layer ordering, one visual track, at most one populated audio lane, no unverified audio overlap, no visual gaps/overlaps/state changes, millisecond-aligned timestamps and integral frame rate. Export endpoint checks capability before adapting to the current renderer. Unsupported multi-track layouts return an explicit error while preserving V2 data. No multi-track flattening or compositor is claimed.

TASK 2.1B exported the isolated Denim V2 fixture through the **API/C++ render job** and compared it with the Task 2.0B baseline. It matched the baseline MP4 hash; all 13 requested video samples and four audio windows matched, and full decode passed. This does not establish WPF Preview or Export parity. See [TASK2_1B_LINEAR_RENDER_COMPARISON.md](TASK2_1B_LINEAR_RENDER_COMPARISON.md).
