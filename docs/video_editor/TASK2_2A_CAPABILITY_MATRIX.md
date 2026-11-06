# TASK 2.2A — Render capability matrix

Status is limited to the tested API/native subset. It does not imply WPF acceptance or CapCut Desktop 9.6.0 parity.

| Capability | Status | Evidence / limits |
|---|---|---|
| Deterministic V2 composition graph | `SUPPORTED_VERIFIED` | Stable IDs, ticks, graph order, validation and fingerprint tests. |
| Multiple visual tracks | `SUPPORTED_VERIFIED` | Two simultaneous visual tracks; no implicit flatten. |
| Video overlay | `SUPPORTED_VERIFIED` | Active/inactive interval, native preview and decoded export parity. |
| Image overlay / straight alpha | `SUPPORTED_VERIFIED` | PNG alpha 0/128/255, opacity and preview/export pixel check. |
| Track layer order | `SUPPORTED_VERIFIED` | Reversing tracks changes native composite. |
| Text layer | `SUPPORTED_VERIFIED` | Arial/drawtext subset with timing and preview/export boundaries. Text uses FFmpeg fallback, not C++ pixel drawing. |
| Multiple audio clips / overlap | `SUPPORTED_VERIFIED` | 440/880 Hz overlap, offsets, gain, fade and post-clip silence. |
| Embedded video audio + separate clip | `SUPPORTED_VERIFIED` | Both spectral components present in output; legacy fixture preserves old normalization. |
| Source time offsets | `SUPPORTED_VERIFIED` | Moving video source offset preview/export; audio source offset tested. |
| Visual gaps | `SUPPORTED_VERIFIED` | Preview and exported gap decode as black; next clip starts on its absolute timestamp. |
| Frame-rate matrix | `SUPPORTED_VERIFIED` | Mapping and actual export at 24, 25, 30, 60 and 30000/1001 fps. |
| Legacy audio-tail frame hold | `SUPPORTED_VERIFIED` | Denim output sampled at 15.1, 20.0 and 37.5 s; baseline parity. Policy is legacy-only. |
| Native C++ preview compositor | `SUPPORTED_VERIFIED` for tested visual subset | Video/image layers, alpha/order/source ticks. C++ preview falls back to FFmpeg for active text/effects. Advanced transform parity remains below. |
| Native nonzero scale/position/rotation parity | `SUPPORTED_UNVERIFIED` | Fields are routed, but visual tolerances across all combinations were not measured. |
| Effects and color-management parity | `SUPPORTED_UNVERIFIED` / fallback | FFmpeg graph renders declared warm/mono/vivid filters. Native preview falls back; no CapCut comparison. |
| Track mute/solo/visible state matrix | `SUPPORTED_UNVERIFIED` | Visible/locked editing semantics are tested; muted/solo edge cases need a dedicated render matrix. |
| Transitions | `UNSUPPORTED` | Non-cut transition is explicitly rejected. |
| Same-track visual overlap | `UNSUPPORTED` | Explicitly rejected; no inferred ripple/replace rule. |
| WPF Preview/Export | `REFERENCE_PENDING` | This task did not alter or manually operate WPF. |
| CapCut 9.6.0 interaction/render reference | `REFERENCE_PENDING` | Backend fixture evidence does not establish product reference semantics. |

The API exposes this split at `/api/v1/video/capabilities`; the global release flags remain unchanged by this task. Unsupported graph input fails before export and leaves the canonical V2 project untouched.
