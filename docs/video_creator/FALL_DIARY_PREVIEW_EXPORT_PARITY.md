# FALL DIARY — PREVIEW / EXPORT PARITY 3.9H

## WPF draft r1 outputs

| Output | Kích thước | Codec | FPS / frames | Duration | Audio | Decode |
|---|---:|---|---:|---:|---|---|
| [WPF preview r1](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Preview.mp4) | 540×960 | H.264 | 30/1, 510 | 17.000s | Không | FFmpeg full decode passed |
| [WPF export r1](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Export.mp4) | 1080×1920 | H.264 | 30/1, 510 | 17.000s | Không | FFmpeg full decode passed |

## Cùng project và revision

WPF Project V2 ID `99b4b283b46b4645a7cd222aee00ae2c`, revision 1, template `fall-diary / 0.5.0-layer-structure-pilot`. Export history ghi cùng `projectId`, `draftRevision: 1`, version và composition fingerprint `060873eca7608d243013cf72add8ac701f7748790dfbb4af1a4c7a221dbc6e3b`. App được restart và mở lại draft r1; preview được tái dựng từ draft đó. Export player phát cùng MP4 r1.

Project V2 r1 được lưu tại [Fall_Diary_3_9H_WPF_Project_V2.json](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Project_V2.json). 11 slot binding và thứ tự media được lưu; selection map của WPF gán `photo-01` → `photo_11.jpg` … `photo-11` → `photo_01.jpg`. Project/graph của shared-renderer comparison được giữ riêng ở [harness Project V2](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Project_V2.json) và [Composition Graph](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Composition_Graph.json).

## Đối chiếu khung hình WPF

Preview/export dùng độ phân giải khác nhau. Đã scale export từ 1080×1920 về 540×960 bằng Lanczos, rồi so RGB ở 22 chỉ số frame trùng nhau quanh opening, các event boundary và cuối timeline. Mean absolute error là **6.033/255**, cao nhất **9.433/255**. Cả hai đều thấp hơn cross-resolution thresholds đã dùng trong Task 3.9D (**mean ≤12**, **mỗi frame ≤24**). Full-sequence SSIM trên **510/510 frame** là **0.920438**; PSNR trung bình là **28.124 dB**. Các chỉ số này đo độ tương đồng giữa hai output của cùng draft, không phải độ giống Muse.

Machine-readable frame measurements: [Fall_Diary_3_9H_WPF_Revision1_Parity.json](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Revision1_Parity.json). Các frame vẫn giữ resolution-specific rasterization và H.264 differences; so sánh pixel chính xác không kỳ vọng bằng 0 khi thu nhỏ export.

## Shared-renderer cross-check

Harness dùng cùng 0.5 Composition Graph cho preview và render, tại cùng kích thước so sánh. 22 frame cho mean RGB MAE **1.74932**, lớn nhất **2.24822**, dưới ngưỡng same-resolution **3.5**. Kết quả này bổ sung cho WPF same-revision comparison; nó không thay cho kiểm tra GUI.

[Shared-renderer preview](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Shared_Renderer_Preview.mp4) được giữ riêng vì binding order của harness khác với 11 file đã chọn qua WPF UI. Video chính ở link trên cùng là preview r1 thực tế của draft WPF.

## GUI playback và kết luận

- [WPF preview r1 screenshot](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Preview_R1.jpg), [preview sau reopen](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Preview_Reopened.jpg), [export đang phát](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Export_Playback.jpg).
- `ffprobe`: preview H.264 540×960; export H.264 1080×1920; cả hai 30/1, 510 frame, 17s, không audio.
- FFmpeg full decode cho preview/export WPF và harness preview/render đều trả exit code 0.
- `FALL_DIARY_PREVIEW_EXPORT_PARITY_VERIFIED=true` cho draft WPF r1 theo same-project identity, cross-resolution frame comparison và GUI playback. `FALL_DIARY_AUDIO_FIDELITY_VERIFIED=false` vì không có soundtrack được cấp quyền/timing đã xác minh.
