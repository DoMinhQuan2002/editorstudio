# TASK 2.2B — WPF Export and Preview/Export Parity

## WPF route

V2 export saves the current project before creating a backend render job. WPF polls the Composition Graph job, downloads the result to a sibling `.partial.mp4`, verifies the MP4 `ftyp` signature, and replaces the selected destination only after that check. A failed or cancelled operation cleans its partial file; cancellation also asks the API job to cancel.

This task did not press the WPF export button. The current build therefore has no WPF export job ID, MP4, `inspect_export.py` output, or WPF preview/export comparison. The partial-file signature check is only a basic container guard; it does not establish a valid stream or full decode.

## Fixture contract

The test project has a 5 s base video, alpha PNG overlay from 1–4.5 s, timed text from 2–4.5 s, audio A from 0–4 s, audio B from 2–8 s, and embedded video audio. This makes the visual duration 5 s and the longest audio end 8 s. Preserve that behavior as implemented by the graph; do not trim audio by assumption.

## Acceptance

`TASK2_2B_WPF_EXPORT_VERIFIED = false` and multi-track preview/export parity remains unverified in WPF. After exporting from the GUI, run the collector with `--export <file>`; it runs the repository `inspect_export.py` and stores the full-decode/stream summary. Compare preview and export at the listed boundary times in the manual checklist, using ROI checks for the alpha overlay and text.
