# TASK 2.2B — Current / Target / Gap Matrix

| Component | Current path | Target | Gap / decision |
|---|---|---|---|
| Canonical model | Persistent V2 tracks and clips in project DTO/store | All edits commit to V2 transaction | Compatibility arrays still feed `ApplyEditorProjections`; not ready |
| Edit history | ViewModel stacks of project snapshots saved via API | One validated canonical command history | No single TimelineEngineV2 history; not ready |
| IDs and time | V2 commands retain IDs; timebase is 90,000 ticks/s | Stable IDs/ticks through every edit and reopen | Some trim/inspector paths use ms; WPF round trip untested |
| Track interactions | Track create/reorder and target-aware placement commands exist | Correct target, order and clip identity via GUI | Cross-track drag/drop and cancellation not demonstrated |
| Overlap semantics | Existing same-track validator rejects overlap | Safe explicit behavior based on reference | Insert/Replace/ripple semantics remain pending; unchanged |
| Preview | WPF V2 snapshot → Composition Graph API → PNG | Correct layers, text, alpha and time in WPF | Code integrated, but GUI and boundary checks not run |
| Preview queue | Latest-request coalescing, cancellation token, response revision check | Responsive scrub without stale output | Backend FFmpeg may continue after client cancellation; latency unmeasured |
| Playback | Preview frames throttled near 4.5 requests/s | Stable interactive playback | Not real-time; runtime responsiveness not measured |
| Audio preview | Separate players for standalone clips and embedded video audio | Timeline/source offsets, gains, fades and sync match graph | Gain summation, headroom, fades and A/V sync not parity-tested |
| Export | V2 save → Composition Graph render job → partial download/guard | WPF export matches preview and full graph | WPF button/export/decode not exercised |
| Native DLL | Release DLL copied with validation publish and hash recorded | Known production binary is loaded at runtime | Process module load not observed in GUI; runtime safety unverified |
| Evidence | Isolated fixture + read-only collector | Before/after, logs, export inspection and GUI video | Initial state captured; user interaction evidence pending |
| CapCut reference | Supplied 9.6.0 recordings/screenshots guide desired UX | Version-specific behavior verified | Several interaction contracts remain `REFERENCE_PENDING` |
