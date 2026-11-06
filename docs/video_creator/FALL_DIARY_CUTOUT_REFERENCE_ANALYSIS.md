# Fall Diary 3.9D — reference isolation and foreground cutout analysis

## Decision

**No foreground cutout is evidenced in the sampled Muse preview.** The people, clothing, hands, food, flowers, and other objects appear as pixels in ordinary camera footage. No transparent edge, isolated person layer, or separately moving subject is visible in the reviewed samples. `FALL_DIARY_CUTOUT_VERIFIED=false`.

The letters `FALL DIARY` in small bordered tiles sit inside the video preview and remain at a stable position across shot changes. They are likely a video graphic, with high confidence. They are separate from the Muse header, controls, and phone status UI. Their original editable source and exact layer implementation are unavailable.

## Evidence and isolation method

- Reference: `local_reference/fall_diary/demo/fall_diary_reference.mp4`, 720×1556, H.264/AAC, 15.066667 seconds. SHA-256: `341884edb553ce70e2e3a92cd06c75015ec76f70501fb2cf0ca3fcb8b8ddea36`.
- This is a screen recording, not an editable project. The runtime template must not use its frames or UI as media.
- Reviewed the preview crop and frames immediately before/after the candidate times listed below. The isolated contact sheet is [Fall_Diary_Reference_Isolated_Timestamp_ContactSheet.jpg](../../artifacts/video_creator/task3_9c/Fall_Diary_Reference_Isolated_Timestamp_ContactSheet.jpg). The capture's close control is masked; Muse header/footer, Use template, bookmark, close, status bar, and Control Center are excluded from video-content interpretation.
- Screen-recording timestamps and detector boundaries are observations, not source edit points. Exact source frame boundaries cannot be recovered from the screen recording.

## Candidate timestamp review

| Candidate (s) | Before/after observation | Classification | Confidence and limit |
|---:|---|---|---|
| 0.000 | First captured preview frame; there is no preceding frame in the recording. | Unknown boundary / opening visible | High that this is the first captured image; no claim about the template's actual start. |
| 3.767 | The preview composition visibly changes around this sample; the title tiles remain. The camera content is consistent with a short insert/replacement. | Confirmed visible change; likely overlay replacement | Medium on replacement type, low on the original cut time. |
| 5.267 | A brief image/card change is visible before the next wider composition. | Confirmed visible change; likely overlay replacement | Medium; compression and screen capture prevent exact layer separation. |
| 5.767 | The underlying full-frame image changes to an outdoor park view. | Confirmed visible change; likely background cut | High for a visible scene change; medium for the exact cut boundary. |
| 6.767 | A new image arrangement is visible while the tile title stays in place. | Confirmed visible change; likely overlay replacement | Medium; no original layer/timing data. |
| 9.267 | The preview switches to a close-up insert. | Confirmed visible change; likely close-up replacement | High for visible change; medium for cut classification. |
| 9.767 | The full-frame content changes to a picnic/table composition. | Confirmed visible change; likely scene cut | High for visible change; medium for exact source boundary. |
| 10.267 | The content arrangement changes while the title remains aligned within the preview. | Confirmed visible change; likely overlay replacement | Medium; a new shot and an overlay change may coincide. |
| 13.267 | A visible cut moves to a new food/flower sequence. | Confirmed visible change; likely scene cut | High for visible change; medium for exact source boundary. |
| 13.767 | The preview changes to the final floral/park composition. | Confirmed visible change; likely scene cut | High for visible change; medium for exact source boundary. |
| 15.067 | The capture ends while phone Control Center/UI covers the preview. | Unknown / recording boundary | High that the recording is ending; not evidence of a template cut or ending. |

`Confirmed visible change` describes what appears in the screen capture. It does not establish whether Muse implemented the change as a cut, replacement, or animation. No candidate is promoted to a source keyframe.

## Foreground and title findings

| Element | Interpretation | Confidence |
|---|---|---|
| People and objects in the sampled shots | Part of the rectangular camera image; not observed as separate alpha layers | High for reviewed samples |
| Tile letters `FALL DIARY` | Graphic inside the video preview, recurring at a consistent relative position across scene changes | High that it belongs to preview content; medium that it is a separately editable text layer |
| Muse title/header, transport controls, Use template, bookmark, close, phone status/Control Center | Application/screen-recording UI; not video content | High |
| Any hidden/blurred region or short unsampled motion | Unknown | Low / not inferable |

The tile graphic is visible through at least 13.833 seconds in the isolated samples. The screen recording ends at 15.066667 seconds; it does not establish when the graphic or template ends. Do not use the screenshot, preview crop, or UI pixels as a rendered layer.

## Cutout gate

- No cutout was created from Muse frames.
- No cutout asset was added to Definition 0.3 or the reusable template catalog.
- MODNet QA masks and RGBA files in `artifacts/video_creator/task3_9d/qa/modnet/` are diagnostic outputs for the local test set only. They are not template assets and must not be treated as user-approved results.
- Status: `FALL_DIARY_CUTOUT_VERIFIED=false`.

