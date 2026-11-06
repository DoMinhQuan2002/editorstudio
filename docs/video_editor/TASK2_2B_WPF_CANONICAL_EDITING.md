# TASK 2.2B — WPF Canonical Editing

## Current state

Project Model V2 remains the persisted multi-track model: track entities own timeline clips with stable track/clip IDs and 90,000 ticks per second. `TimelineV2EditCommands` provides create/remove/reorder track, add/remove visual and audio clip, move, trim, overlap validation and compatibility projection rebuilding. WPF uses these commands in several track-management, placement and move paths.

The edit pipeline is not fully canonical yet. The editor still exposes `Clips`, `TextLayers` and `AudioTracks` as mutable compatibility projections. `PersistCurrentProjectAsync` and the graph preview snapshot call `ApplyEditorProjections`, which rebuilds canonical track clips from those projections. The ViewModel undo/redo stacks hold whole-project snapshots and save the restored snapshot through the API; they are not one `TimelineEngineV2` transaction history. Some trim and inspector timing values still travel through milliseconds.

## Time handling

Drop pixel positions can be converted to ticks using the project FPS numerator/denominator, including 30000/1001. Frame-snapped candidate positions are converted back to exact frame ticks. Clip identity is retained by move/trim commands. Other timing edits still need a complete tick-native path and direct WPF Save/Reopen evidence.

## Decision

`TASK2_2B_CANONICAL_EDITING_READY = false`

Automated tests currently pass: .NET 126/126 and the selected Python composition suite 24 passed, 3 skipped and 10 subtests passed. The next acceptance work is to route every inspector/timeline command through validated V2 mutations, make history operate on canonical transactions, then test revision conflicts and WPF persistence round trips.
