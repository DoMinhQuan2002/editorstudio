# Foreground asset contract — Task 3.9D status

## Status

**Proposal only. No serialized foreground-asset schema, endpoint, or compiler support is implemented.** MODNet did not meet semantic/quality safety gates, so this document records requirements for a later implementation. It does not define an accepted payload format.

## Requirements for a future contract

1. Keep the original source media immutable. Store the derived RGBA/matte separately and include the source media ID plus source SHA-256.
2. Record model name, model version/revision, model file checksum, preprocessing configuration version, output dimensions, alpha format/range, color space, and creation time.
3. Record the requested subject category, detection/quality status, and a structured failure code. A non-empty alpha matte alone is not evidence that the requested subject was identified.
4. Associate the derived foreground with its source and cache key. Recompute or invalidate it when source bytes, model, or preprocessing changes.
5. Bind the derived asset explicitly to a layer/slot in the shared Project V2 and Composition Graph. Preview and export must consume the same derivative and preserve alpha.
6. Reject missing/invalid alpha, unsupported format, unsafe confidence, model/runtime absence, resource exhaustion, and cancellation with visible status. Keep the source binding unchanged after failure.
7. Never silently fall back to a rectangular crop, a fabricated mask, or a different segmentation model.

## Current gates

```text
FOREGROUND_ASSET_CONTRACT_IMPLEMENTED=false
FOREGROUND_ASSET_CONTRACT_PROPOSED=true
FALL_DIARY_CUTOUT_VERIFIED=false
```

