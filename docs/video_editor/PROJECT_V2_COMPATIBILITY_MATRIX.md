# Project V2 compatibility matrix

| Area | Current behavior | Evidence | Status |
|---|---|---|---|
| V1 read | Detects project without `schemaVersion`; validates legacy model | Python migration tests | PASS automated |
| V1 migration | Sequential visual positions become absolute ticks; text/audio/placeholders retained | Round-trip tests including full media metadata | PASS automated |
| Backup / recovery | SHA-256 immutable V1 backup; atomic replace; guarded exact rollback | Failure injection, idempotence and rollback tests | PASS automated |
| V2 read/write | Requires version 2 and persistent `tracks`; canonical JSON only | Store/API tests | PASS automated |
| WPF compatibility arrays | Must include clips/text/audio projections and absolute identity/timing | API tests reject incomplete projection | PASS contract |
| Free Editor | Blank V2 project with no fake clip | API create/get/save test | PASS automated |
| Template Editor | Denim Story five 3-second placeholders and `jeans` text | API + migration tests | PASS automated |
| Multiple visual/text/audio tracks in model | Independent IDs/order and persistent empty tracks | Engine + store Save/Reopen tests | PASS automated |
| Move across tracks in domain | Preserves clip ID and timestamp; compatible kinds only | Engine test | PASS automated |
| Move across tracks in WPF | Persistent command and row target resolver implemented | .NET command tests pass; WPF mouse acceptance not run | PARTIAL / PENDING GUI |
| WPF trim | Visual/audio trim command writes canonical ticks and keeps lane/clip IDs | .NET atomic overlap and trim projection tests; WPF drag not run | PARTIAL / PENDING GUI |
| Undo/redo | Domain edit snapshots; IDs/order/timing restored | Engine test | PASS automated |
| Fractional fps/time | 30000/1001 exact frame duration; arbitrary ticks retained | Schema and persistence tests | PASS model |
| Linear renderer adapter | Explicit V2 → current renderer adapter and capability guard | Isolated API/C++ V2 export compared with Task 2.0B baseline; byte-identical, full decode | PASS API fixture; WPF pending |
| Audio longer than visual | Model duration uses max end; renderer extends final visual while audio continues | V2 API export sampled through 37.5s; audio duration 37.608005s | PASS API fixture; WPF pending |
| Multitrack preview/export | Explicitly rejected when unsupported; no silent flatten | Capability tests | PASS safety guard; compositor absent |
| Multiple populated audio tracks / overlapping audio | Refused by render capability until mixing behavior is verified | Project V2 capability test | PASS safety guard; mixing absent/unverified |
| WPF manual acceptance | No mouse-driven acceptance in this Task 2.1 run | GUI not exercised | PENDING |
| CapCut 9.6.0 parity | No complete About/build or interaction evidence | Existing feature inventory | PENDING |

TASK 2.1B regression rerun: **122 .NET passed**; **33 Python passed** (25 Project V2/API, 5 audio, 3 timeline). Automated tests do not constitute WPF mouse acceptance or CapCut parity.

## Status flags

```text
TASK2_1_MODEL_READY = true
TASK2_1_PERSISTENT_TIMELINE_READY = false
TASK2_1_LINEAR_RENDER_COMPATIBLE = false
TASK2_0B_RUNTIME_ACCEPTED = false
CAPCUT_9_6_0_REFERENCE_COMPLETE = false
MULTITRACK_COMPOSITOR_VERIFIED = false
VIDEO_EDITOR_RELEASE_READY = false
```

`TASK2_1_MODEL_READY` covers backend schema/store/API, migration, rollback, blank project and template regressions. It does not imply the editor release gates have passed.
