# Media Studio — Task 3.9B report

## Kết luận và trạng thái gate

Task 3.9B đã tạo definition `fall-diary / 0.2.0-motion-pilot`, bổ sung nội suy keyframe tuyến tính dùng timebase Project V2 90 kHz, các collage có số lớp thay đổi theo event, graphic chữ dạng hai ô từ text, và xuất preview/render từ cùng Composition Graph. Definition cùng Project V2 0.1.0 và toàn bộ output 3.9A được giữ nguyên; không đổi schema Project V2, không sửa ảnh nguồn, không tạo Project V2 vĩnh viễn ngoài artifact QA, không tự chạy Template Compiler thành MP4 trong UI.

```text
FALL_DIARY_0_2_DEFINITION_READY                 = true
FALL_DIARY_MOTION_VERIFIED                      = true  # motion thật trong cùng event
FALL_DIARY_DYNAMIC_COLLAGE_VERIFIED             = true
FALL_DIARY_TEXT_STYLE_VERIFIED                  = true  # text graphic được render
FALL_DIARY_AUDIO_VERIFIED                       = true  # chỉ đường QA bằng tone tổng hợp
FALL_DIARY_PREVIEW_EXPORT_PARITY_VERIFIED       = true  # ngưỡng QA được nêu bên dưới
FALL_DIARY_MEDIA_BINDING_VERIFIED               = true  # 12 ảnh thật đã compile theo Slot ID
FALL_DIARY_READY_FOR_TEMPLATE_COMPILER          = true  # Project V2 + Composition Graph hợp lệ
FALL_DIARY_CUTOUT_VERIFIED                      = false
FALL_DIARY_AUDIO_FIDELITY_VERIFIED              = false
FALL_DIARY_REFERENCE_FIDELITY_VERIFIED          = false
FALL_DIARY_GUI_ACCEPTED                         = false  # chưa thực hiện GUI runtime acceptance
FALL_DIARY_READY_FOR_USERS                      = false
```

`GUI_ACCEPTED=false` có nghĩa phần GUI runtime chưa được nghiệm thu trong task này. Kết quả dưới đây chứng minh render/backend; không thay cho thao tác màn hình thực tế. `AUDIO_VERIFIED=true` chỉ nói audio path được kiểm tra với tone QA, không nói soundtrack giống demo.

## Definition và bố cục

- Definition mới: [fall-diary-0.2.0-motion-pilot.json](../../backend/mediastudio/video_editor/definitions/fall-diary-0.2.0-motion-pilot.json).
- Definition baseline `0.1.0-pilot` vẫn load được bằng version cụ thể và policy `unique_asset` không bị đổi. Bản 0.2 dùng 12 slot `photo-01`…`photo-12`, policy `allow`, slot bắt buộc là ảnh. Không suy Slot ID từ tên mẫu, không tạo 36/12 slot giả cho FALL DIARY legacy chưa có slot definition.
- Duration 15 giây, canvas 1080×1920, 30 fps cho pilot. 6 visual event dài 2.5 giây; số visual layer lần lượt **2, 3, 3, 2, 4, 3**. Một title event riêng kéo dài 2.5 giây. Mỗi event dùng layer order độc lập và ảnh có thể được dùng lại theo policy.
- Keyframe có thể dùng cho `positionX`, `positionY`, `scale`, `rotation`, `opacity`; mỗi thuộc tính có key tại tick 0 và tick cuối event. Chỉ `linear` interpolation/easing được chấp nhận. Crop/pan động, transition ngoài hard cut, video layer và keyframe text không được công bố là hỗ trợ trong definition này.
- Graphic chữ được dựng bằng text layer độc lập `FALL` và `DIARY`, mỗi từ có nền màu riêng, viền nhẹ và shadow. Không dùng ảnh UI Muse hoặc ảnh người làm text overlay.

## Render và bằng chứng

Artifact nằm dưới `artifacts/video_creator/task3_9b/`:

- [Fall_Diary_Motion_Preview.mp4](../../artifacts/video_creator/task3_9b/Fall_Diary_Motion_Preview.mp4) — H.264 540×960, 30 fps, 15 giây; AAC stereo 44.1 kHz.
- [Fall_Diary_Motion_Render.mp4](../../artifacts/video_creator/task3_9b/Fall_Diary_Motion_Render.mp4) — H.264 1080×1920, 30 fps, 15 giây; AAC stereo 44.1 kHz.
- [Fall_Diary_Motion_Project_V2.json](../../artifacts/video_creator/task3_9b/Fall_Diary_Motion_Project_V2.json) — Project V2 `templateDefinitionVersion=0.2.0-motion-pilot`; audio QA track tổng hợp được thêm riêng cho lần render, không nằm trong template definition.
- [Fall_Diary_Motion_Composition_Graph.json](../../artifacts/video_creator/task3_9b/Fall_Diary_Motion_Composition_Graph.json) và [Fall_Diary_Motion_Manifest.json](../../artifacts/video_creator/task3_9b/Fall_Diary_Motion_Manifest.json).
- [Fall_Diary_Motion_Frame_Evidence.jpg](../../artifacts/video_creator/task3_9b/Fall_Diary_Motion_Frame_Evidence.jpg) và các PNG frame trong `motion_frames/` là ảnh được trích/render từ fixture thật; ảnh nguồn được đọc tại chỗ, không copy vào template.

Kết quả đo:

| Kiểm tra | Kết quả |
|---|---:|
| FFprobe / full decode cho preview và export | PASS; cả hai 450 frame, audio/video start 0, duration 15.000 s |
| Preview–export SSIM sau khi scale export về 540×960 | 450 frame; mean **0.904437**, min **0.809201** |
| Still preview 1080p so với đúng frame index của export H.264 | 8 timestamp; sai số tuyệt đối RGB trung bình **5.4952/255** |
| Motion trong event đầu | 0.25 / 1.25 / 2.25 s có hash khác; mean absolute RGB difference đầu–cuối **28.4749/255** |
| Audio QA | 440 Hz tổng hợp, fade-in 250 ms/fade-out 500 ms; hai file AAC 15.000 s, start 0; decoded RMS ở 0–50 ms 0.000610, giữa video 0.005305, 14.95–15 s 0.000307 |
| Bộ fixture thứ hai | 12 PNG hình học/icon/gradient; 6 preview frame khác nhau; PASS cho renderer tổng quát, không phải bộ ảnh chân dung |
| Private fixture | SHA-256 trước/sau không đổi; `sourceFilesCopied=false` |

Parity gate áp dụng ngưỡng QA nội bộ: mean SSIM ≥0.90, min ≥0.80, đủ 450 frame và 8 so sánh cùng độ phân giải có sai số trung bình RGB ≤12/255. Không dùng ngưỡng này để tuyên bố giống reference.

## Cutout, audio và giới hạn reference

Không bật cutout tự động. Môi trường có `torch`, `cv2`, `PIL`, nhưng không có `rembg`, `transformers`, `mediapipe`, `ultralytics`, `transparent_background` hoặc `onnxruntime`. Foreground Protection Lab hiện là quy trình alpha có hướng dẫn/thủ công, không phải mô hình segmentation chủ thể đủ tin cậy. Definition 0.2 không có mask/cutout capability và không dùng rectangle crop làm cutout.

Demo Muse là screen recording có chrome ứng dụng xuyên suốt; các mốc scene-detection trong tài liệu 3.9A là ứng viên quan sát, không phải source timing. Animation và nhịp trong 0.2 là thiết kế thử nghiệm suy luận, không phải khôi phục keyframe gốc. Không đưa chrome, watermark, nút Use template hay Control Center vào output. Audio reference không được đóng gói.

## Source files và tests

Source cập nhật:

- `backend/mediastudio/video_editor/template_keyframes.py`
- `backend/mediastudio/video_editor/template_compiler.py`
- `backend/mediastudio/video_editor/composition.py`
- `backend/mediastudio/video_editor/composition_renderer.py`
- `backend/mediastudio/video_editor/media_selection.py`
- `backend/mediastudio/video_editor/project_v2.py`
- `backend/mediastudio/video_editor/definitions/fall-diary-0.2.0-motion-pilot.json`
- `tools/video_creator/render_fall_diary_task39b.py`
- Regression tests: `backend/tests/test_fall_diary_task39b.py`, compiler/media-selection tests, 3.9A pinned-baseline test và Project V2 API catalog test.

Đã chạy `py_compile` cho source Python được sửa và các suite backend video editor, Project V2 API, audio, template processing, media selection, compiler, Fall Diary 3.9A/3.9B: **97 passed, 3 skipped, 10 subtests passed** (một cảnh báo deprecation từ Starlette/AnyIO). `dotnet test MediaStudio.sln --no-restore` build được WPF Desktop và test project, sau đó **54 passed, 0 failed**. GUI runtime acceptance/screenshot chưa chạy; build/test không được tính là GUI acceptance. Không chạy Image Tools smoke vì không sửa Image Tools.

## Cổng tiếp theo

Để chuyển `READY_FOR_USERS` cần xác minh slot/binding workflow trực tiếp trong UI, demo/poster có quyền sử dụng, có nguồn segmentation alpha có provenance nếu cần cutout, và đối chiếu từng hiệu ứng với source project hoặc reference đủ rõ. Task này không triển khai màn hình tiếp theo và không quảng bá 0.2 như bản tái tạo Muse hoàn chỉnh.
