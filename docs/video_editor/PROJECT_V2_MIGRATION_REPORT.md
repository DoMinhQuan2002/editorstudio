# Project V1 → V2 migration report

## Scope and rules

Migration is per-project when opened. `list()` can show a converted in-memory view but does not modify files. No bulk migration was run. V2 projects are validated and returned unchanged; there is no automatic downgrade.

| Legacy data | V2 mapping |
|---|---|
| `clips[]` | One persistent visual track; each clip start is the sum of preceding durations, converted from ms to ticks. Clip ID, Media ID and legacy property snapshot are retained. |
| Placeholder (`mediaId=null`) | Retained as a clip with `templateMetadata.placeholder=true`, original duration and slot order. |
| `textLayers[]` | Persistent text track; text layer ID becomes clip ID; absolute start/duration and all legacy style properties are retained. `legacyRenderOrder` preserves old list order in the compatibility adapter. |
| `audioTracks[]` | Audio item ID remains clip ID. New deterministic persistent lane track ID is separate. The legacy first-fit grouping is applied once during migration and then persisted. Timeline/source/duration, Media ID and audio properties remain. |
| Empty Free Editor | Empty visual track entity is created, no fake media or placeholder. |

The original V1 model only has integer milliseconds and integer fps; migration retains those values exactly and sets denominator 1. Migration does not invent fractional fps values that V1 did not store.

## Safe write sequence

1. Read original bytes and parse/validate V1.
2. Build V2 in memory; validate IDs, references within model, track ownership, layer order, timeline ranges and source range arithmetic.
3. Compute source SHA-256.
4. Create immutable sibling backup `*.v1.<sha256>.bak` using exclusive create; flush/fsync and verify hash.
5. Serialize complete V2 to a temp file in the same directory, flush/fsync, then `os.replace` atomically.
6. If temp write/replace fails, preserve original V1 and backup; temp is removed. No partial V2 file is exposed.

Rollback restores exact backup bytes only while revision still matches the migration source revision; after first V2 Save it refuses rollback. Hash mismatch refuses restoration. If a concurrent V2 write supersedes the bytes while migration is running, the reader validates and returns that V2 instead of overwriting it.

## Regression evidence in this repository

Executed `backend.venv\Scripts\python.exe -m unittest discover -s backend/tests -p 'test_video_editor_project_v2*.py'`: **23 passed**.

Coverage includes:

- Empty V1 Free Editor and Denim Story V1 with five unbound 3-second slots.
- Fully bound V1 clip, text and audio with source offsets, transforms, effect, transition, opacity, font, fades, volume, IDs and timing round-tripped through the compatibility adapter.
- Missing-media placeholder remains unbound; overlapping legacy audio items persist as distinct track lanes and clip IDs.
- Audio longer than visual timeline remains the timeline end in the migrated model.
- List is read-only; open migration creates SHA-256 backup; repeated open is idempotent.
- Simulated interrupted atomic write leaves original bytes intact and backup retained.
- Rollback exact bytes before V2 edit; rollback refusal after Save.
- Malformed JSON/unsupported schema remain untouched and are rejected.
- Multi-track V2 Save/Reopen retains ID, track order and non-ms-aligned absolute ticks.

These are automated model/store tests. They do not assert that a WPF mouse workflow was manually accepted. TASK 2.1B later reran the focused Project V2/API suite with **25 passed**, plus the audio and timeline suites (33 Python tests total), and independently verified a V1 backup + Save/Reopen on a cloned fixture.

## Known gaps

- There is no bulk migration or migration tool for user directories.
- The current API compatibility collections are complete projections; incomplete Save payloads are rejected rather than silently ignored.
- TASK 2.1B later re-exported an isolated migrated Denim V2 copy through the API/C++ renderer and compared it with the Task 2.0B MP4. The fixture output was byte-identical and fully decoded. The WPF Preview and WPF Export paths remain unverified; see [TASK2_1B_LINEAR_RENDER_COMPARISON.md](TASK2_1B_LINEAR_RENDER_COMPARISON.md).
