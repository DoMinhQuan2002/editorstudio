# Fall Diary — Task 3.9D manual QA

## WPF observations

| Screen | Result | Evidence / limitation |
|---|---|---|
| 01 Gallery | Observed | Fall Diary displayed as a pilot, not released. Exact template ID is `fall-diary`; the card reports 11 media positions and 17 seconds. |
| 02 Template Details | Observed | Definition version `0.3.0-reference-pilot`, 11 image slots, 9:16, and pilot status shown. No licensed demo/poster is available; no user draft was used as a demo. |
| 03 Media Selection | Observed and exercised | WPF resumed an existing 0.3 draft in “Thay media trong bản nháp” mode. The picker showed 12 private QA photos and 11 definition slots. Selecting `photo_11.jpg` and assigning it to `photo-11` showed 12/12 selected media and 11/11 slots bound. |
| 04 Processing | Partial | WPF showed “Payload đã được xác thực. Đang cập nhật media trong bản nháp hiện tại…” and generated the revision 2 draft preview. A fresh-project Screen 4 progress/status surface was not re-opened for this exact revision. |
| 05 Preview/Edit | Partial | The revision 2 MP4 exists in the WPF draft preview cache and was copied as the preview output. The Preview screen was not left open for a screenshot after the edit route returned to Template Details. |
| 06 Export | **Pending** | The WPF Export screen was not reached in this run. The final MP4 in Task 3.9D is a shared-renderer output, not an in-app export. |

## Session and source integrity

- The Details → Media Selection route resumed an existing Project V2 rather than opening a clean empty session. An unchanged binding payload returned a visible “Template Definition không có slot binding được biên dịch” error and did not write a project update.
- Changing slot `photo-11` to the selected QA photo saved revision 2 and generated a WPF preview. The revision 2 Project V2 is retained under `artifacts/video_creator/task3_9d/`.
- This edit was applied to the Task 3.9C runtime project file during UI validation. The accepted Task 3.9C revision 1 JSON was then restored from its saved Task 3.9C artifact; SHA-256 now matches byte-for-byte. The candidate revision 2 is separate from that restored baseline. No user source image bytes changed.
- Opening Media Selection alone did not create a new project. No NLE/legacy editor was used. No Muse UI pixels were added to output.
- Source fixture hash comparison: pass. Preview and final render full decode: pass. Project ID/revision/version/binding hash and Composition Graph fingerprint: recorded in the parity report.

## Acceptance

The in-app route is **not six-screen accepted** because Screen 6 was not validated in WPF. Backend/compiler success and a WPF-generated preview file do not substitute for that GUI step.

```text
FALL_DIARY_SIX_SCREEN_GUI_VERIFIED=false
GUI_STATUS=GUI_PENDING
FALL_DIARY_CUTOUT_VERIFIED=false
FALL_DIARY_AUDIO_FIDELITY_VERIFIED=false
FALL_DIARY_READY_FOR_USERS=false
```

The remaining GUI work is to start an isolated WPF session, verify Processing → Preview/Edit → Export for the same project ID/revision/binding snapshot, save the in-app export record, and compare its exported MP4 against the WPF preview.

