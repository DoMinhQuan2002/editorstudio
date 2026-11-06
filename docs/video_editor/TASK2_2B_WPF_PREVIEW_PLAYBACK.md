# TASK 2.2B — WPF Preview and Playback

## Composition Graph connection

For schema V2 projects the WPF preview requests a frame from `POST /projects/{project_id}/preview/frame`, passing a cloned current project snapshot after projecting current editor values. The backend validates media references, builds the shared Composition Graph, renders the timestamp and returns a PNG plus graph version, frame index, source fingerprint, renderer name and project revision. This includes unsaved inspector edits in the request body.

The WPF view coalesces paused seeks, keeps only the latest pending timestamp, cancels an older paused request and ignores results whose request revision is stale. Image decoding and request work are asynchronous. The composition status shown by WPF reports the returned graph metadata.

## Limits and status

Playback requests are intentionally throttled to about 220 ms apart (roughly 4.5 requested frames per second), with extra coalescing when seeking. This protects the synchronous frame renderer from an unbounded scrub queue; it is not a 30/60 fps playback implementation. Cancelling an HTTP request prevents an old frame from being displayed, but may not stop FFmpeg work already running in the backend.

The Python composition endpoint tests pass in the selected suite, but the WPF preview surface has not been viewed or scrubbed in this environment. Alpha, text boundaries, overlays, stale frame behavior and preview/export parity require manual evidence.

```text
Composition API frame path: automated suite PASS in stated scope
WPF preview interaction: BLOCKED / NOT RUN
Timeline Playback: PARTIAL
Real-time Playback: NOT VERIFIED
TASK2_2B_WPF_PREVIEW_VERIFIED = false
```
