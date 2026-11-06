# TASK 2.2B — WPF Multi-track Interaction

## Implemented paths

- WPF can create persistent visual, text and audio lanes through `TimelineV2EditCommands`.
- Visual placement and clip move resolve a target track and retain clip identity. The unsnapped pixel drop uses rational-FPS tick conversion; resolved snap positions use frame-aligned tick conversion.
- Same-lane overlaps are rejected by the existing V2 placement validator. This task did not invent a ripple or replacement policy for overlapping clips.
- The test fixture contains two visual lanes, one text lane and two audio lanes, with explicit IDs and offsets.

## Open evidence

No mouse-driven GUI test has been run here. Cross-track move, overlay drop, track reorder, invalid drop/cancel, trim handles, undo/redo, and Save/Reopen must be exercised in the WPF validation build. Whether the UI always targets the hovered persistent lane and whether a single drag creates exactly one clip remain unverified until those actions are captured.

`TASK2_2B_WPF_MULTITRACK_VERIFIED = false`

See [manual acceptance](TASK2_2B_MANUAL_ACCEPTANCE.md) for cases W17–W26 and the earlier W01–W16 continuation.
