# TASK 2.2B — WPF Audio Playback

WPF preview now manages audio players for standalone audio clips and for video clips with an audio codec. Playback seeks use timeline start and source start; per-clip fade-in/fade-out envelopes are applied during playback. The fixture includes two standalone tracks that overlap, a base video with embedded AAC audio, fades, and an audio end three seconds after the visual end.

This is a functional preview path, not a verified Composition Graph mixer. WPF currently uses separate `MediaPlayer` objects and caps individual volume values to the platform range. The export mixer sums gain and uses graph semantics. Output headroom, overlap loudness, exact fade curves, end-of-visual behavior and A/V synchronization have not been measured. Seek inside overlapping clips, mute/solo behavior and delete/undo/redo routing also need GUI acceptance.

```text
WPF audio preview: PARTIAL
WPF audio playback verified: false
Measured A/V skew: not available
```

Do not claim parity with export until a loopback recording or equivalent audio capture compares timed markers and offsets across the overlap cases.
