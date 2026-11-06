# Media Studio — Task 3.9A report

## Kết luận ngắn

Fall Diary đã đi từ catalog `REFERENCE_ONLY` với duration/slot bằng 0 đến một pilot definition `0.1.0-pilot`, binding bằng Slot ID, Project V2/Composition Graph thật và hai MP4 được render từ 12 ảnh private trong workspace. Pilot đang ở `PILOT_RENDERABLE` trong catalog test; chưa chuyển sang `READY_FOR_USERS`.

Các cổng cuối:

```text
FALL_DIARY_REFERENCE_INGESTED       = true
FALL_DIARY_DEFINITION_READY         = true
FALL_DIARY_COMPILER_READY           = true
FALL_DIARY_FIRST_RENDER_VERIFIED    = true
FALL_DIARY_PREVIEW_EXPORT_PARITY_VERIFIED = true
FALL_DIARY_FULL_EFFECT_FIDELITY_VERIFIED  = false
FALL_DIARY_READY_FOR_USERS          = false
```

## 1. Reference kit và hash verification

Đã đọc `local_reference/fall_diary/README.txt` và `manifest.json`. Bộ kit có đúng 13 file: 1 demo MP4 và 12 ảnh private. SHA-256 của cả 13 file khớp manifest (`all_match=True`, kích thước byte cũng khớp).

| Input | Kết quả kiểm tra |
|---|---|
| `demo/fall_diary_reference.mp4` | tồn tại, 4,045,490 bytes, H.264/AAC, 720×1556, 15.066667 s |
| `private_test_media/photo_01.jpg` … `photo_12.jpg` | tồn tại, hash khớp; ảnh portrait 2048 px chiều cao, chiều rộng 1151/1364/1536 tùy file |
| README/manifest | xác nhận đây là reference/testing input, không phải editable template; ảnh private không được commit/package/publish |

Ảnh nguồn được đọc tại chỗ. Harness ghi `sourceFilesCopied: false`; không sửa ảnh, không đưa ảnh vào template package và không dùng demo MP4 làm output export. Demo/audio bên thứ ba vẫn cần xác minh quyền trước khi phân phối.

## 2. Phân tích demo

Demo là screen recording của Muse, không phải source project. FFprobe ghi nhận 720×1556, H.264, 30 fps danh nghĩa, AAC 44.1 kHz stereo. Scene-detection/contact sheet cho thấy nhiều mốc thay đổi bố cục ứng viên tại khoảng 3.767, 5.267, 5.767, 6.767, 9.267, 9.767, 10.267, 13.267 và 13.767 giây. Muse chrome tồn tại xuyên suốt capture.

Bảng chi tiết Start/End/Media role/Layers/Transform/Effect/Confidence nằm tại [FALL_DIARY_FRAME_BY_FRAME_ANALYSIS.md](FALL_DIARY_FRAME_BY_FRAME_ANALYSIS.md). Các mốc đó là quan sát ở cấp screen recording; 6 event của pilot dùng các đoạn 2.5 giây để kiểm chứng compiler, không được coi là keyframe gốc của Muse.

## 3. Template Definition `fall-diary / 0.1.0-pilot`

Definition: [fall-diary-0.1.0-pilot.json](../../backend/mediastudio/video_editor/definitions/fall-diary-0.1.0-pilot.json)

- Canvas 1080×1920, 30/1, duration 1,350,000 ticks = 15 giây.
- 12 required image slots `photo-01` … `photo-12`.
- `reusePolicy: unique_asset`, `missingSlotPolicy: error`; binding chỉ chấp nhận Slot ID từ definition.
- 6 visual events, mỗi event 2.5 giây, mỗi event có background full-frame và card overlay ở layer order 0/1.
- 1 text event độc lập kéo dài toàn bộ 15 giây, text `FALL\nDIARY`, layer order 3.
- Pilot dùng mỗi slot một lần để chứng minh 12 ảnh thật và tránh suy diễn số slot từ UI demo. Schema vẫn cho phép một slot tham gia nhiều event.

| Event | Time | Background | Card | Bố cục pilot |
|---|---:|---|---|---|
| scene-01 | 0.0–2.5 s | photo-01 | photo-02 | cover + contain, card xoay -6° |
| scene-02 | 2.5–5.0 s | photo-03 | photo-04 | cover + contain, card xoay +5° |
| scene-03 | 5.0–7.5 s | photo-05 | photo-06 | cover + contain, card xoay -5° |
| scene-04 | 7.5–10.0 s | photo-07 | photo-08 | cover + contain, card xoay +6° |
| scene-05 | 10.0–12.5 s | photo-09 | photo-10 | cover + contain, card xoay -4° |
| scene-06 | 12.5–15.0 s | photo-11 | photo-12 | cover + contain, card xoay +5° |

## 4. Effect capability matrix

| Capability | Demo evidence | Pilot result | Status |
|---|---|---|---|
| Full-frame image | Ảnh full-frame xuất hiện trong preview | `fitMode=cover` ở layer order 0 | IMPLEMENTED/VERIFIED |
| Hard cut / nhịp cảnh | Nhiều thay đổi nhanh trong capture | 6 event nối tiếp, không transition | IMPLEMENTED/VERIFIED |
| Multi-layer collage | Nhiều ảnh nhìn thấy đồng thời | 2 visual tracks, 12 visual clips | IMPLEMENTED/VERIFIED |
| Crop/fit/position/scale/rotation tĩnh | Quan sát thấy card có hình học riêng | static `contain`, position, scale, rotation | IMPLEMENTED/VERIFIED |
| Static opacity | Alpha là capability của renderer | opacity trên card | IMPLEMENTED/VERIFIED |
| Text overlay độc lập | Text của template không thể tách khỏi Muse chrome | 1 text clip, drawtext trên track riêng | IMPLEMENTED/VERIFIED cho pilot |
| Animated position/scale/opacity | MP4 không tiết lộ keyframes/easing | compiler/renderer chưa nhận keyframes | DEFERRED/UNSUPPORTED |
| Foreground cutout / mask | Không thể khôi phục original mask từ capture | không tạo crop giả và không claim cutout | UNSUPPORTED |
| Fade/wipe/transition nâng cao | Không đủ bằng chứng chắc chắn | chỉ dùng hard cut | UNSUPPORTED |
| Audio sync / soundtrack | Demo có audio nhưng quyền và track gốc chưa biết | pilot không nhúng audio demo | DEFERRED |

## 5. Source files thay đổi

- `backend/mediastudio/video_editor/definitions/fall-diary-0.1.0-pilot.json`: definition versioned.
- `backend/mediastudio/video_editor/template_compiler.py`: public slot metadata và `templateSupportedCapabilities`; dùng schema compiler chung.
- `backend/mediastudio/video_editor/media_selection.py`: loader/cache definition, version guard, slot requirements từ definition và compile validation theo Slot ID.
- `backend/mediastudio/video_editor/catalog.py`: duration/slots/capabilities/demo source được lấy từ definition; Fall Diary công khai là `PILOT_RENDERABLE` khi definition/slot path hợp lệ, không phải `READY_FOR_USERS`.
- `backend/mediastudio/video_editor/composition_renderer.py`: text size quy về canvas thiết kế 1080×1920 cho canvas portrait; fixture canvas vuông giữ pixel-space legacy để không phá regression.
- `tools/video_creator/render_fall_diary_task39a.py`: harness render/FFprobe/full decode/SSIM, không copy private source.
- `backend/tests/test_fall_diary_task39a.py` và các test Task 3.3/3.4/3.5/2.1 được cập nhật cho definition/version/slot policy.

## 6. Pipeline và artifacts

Pipeline đã chạy:

```text
12 private photos
  → Slot ID bindings
  → Template Compiler
  → Project V2
  → Composition Graph
  → preview render 540×960
  → export render 1080×1920
```

Project metadata ghi `templateDefinitionVersion=0.1.0-pilot`, 2 visual tracks (6 clips mỗi track) và 1 text track (1 clip). Đây là composition nhiều lớp, không phải slideshow một track.

- [Fall_Diary_Project_V2.json](../../artifacts/video_creator/task3_9a/Fall_Diary_Project_V2.json)
- [Fall_Diary_Composition_Graph.json](../../artifacts/video_creator/task3_9a/Fall_Diary_Composition_Graph.json)
- [Fall_Diary_Render_Manifest.json](../../artifacts/video_creator/task3_9a/Fall_Diary_Render_Manifest.json)
- Contact sheet kiểm tra trực quan: `artifacts/video_creator/task3_9a/Fall_Diary_Render_Contact_New.jpg`

## 7. Preview, export và decode

| Output | Probe | Decode | Audio |
|---|---|---|---|
| [Fall_Diary_First_Preview.mp4](../../artifacts/video_creator/task3_9a/Fall_Diary_First_Preview.mp4) | H.264, 540×960, 30 fps, 15.000 s, 450 frames | PASS, exit 0, stderr rỗng | Không có |
| [Fall_Diary_First_Render.mp4](../../artifacts/video_creator/task3_9a/Fall_Diary_First_Render.mp4) | H.264, 1080×1920, 30 fps, 15.000 s, 450 frames | PASS, exit 0, stderr rỗng | Không có |

Preview và export đều được tạo từ 12 ảnh private; demo MP4 không nằm trong input graph.

## 8. Preview/export parity

Text và image graph dùng cùng layer order, timing, fit, transform và text coordinate. Quy tắc text mới scale font theo canvas portrait chuẩn: `76 px` ở 1080×1920 và `38 px` ở 540×960. SSIM được tính sau khi scale export về 540×960:

```text
framesCompared = 450
meanSsim       = 0.9329646822
minSsim        = 0.886313
decode         = PASS cho cả hai output
```

Contact sheet preview/export cho thấy cùng các cảnh và text; SSIM chỉ là một chỉ báo, nên đã xem trực quan và kiểm tra text cùng vị trí. Đây là parity kỹ thuật giữa hai output của pilot, không phải pixel parity với demo dùng source media khác.

## 9. Regression và test matrix

- Fall Diary definition/catalog/slot/compiler/API tests: **36 passed, 1 warning**.
- Composition, draft preview, export và audio regression: **34 passed, 3 skipped, 10 subtests passed, 1 warning**.
- Full decode/FFprobe của hai artifact: **PASS**.
- Reused media references, missing binding, invalid definition version và unsupported keyframe/cutout/mask/transition guards: **PASS** trong test suite liên quan.
- Denim Story dùng compiler/renderer chung và nhóm composition regression vẫn pass; không có hardcode riêng cho `jeans` hoặc Fall Diary.

## 10. Handoff Task 3.9B

Task 3.9B có thể bắt đầu từ definition và artifacts hiện tại để mở rộng fidelity có bằng chứng. Phạm vi còn lại cần xử lý có chủ đích:

1. xác định keyframe/easing thật nếu có source hoặc recording đủ rõ;
2. thiết kế mask/foreground-cutout có dữ liệu alpha thật;
3. bổ sung transition/audio sau khi xác minh quyền và timing;
4. thêm golden visual checks cho các event pilot trước khi nâng trạng thái catalog.

Không mở rộng sang template khác trong Task 3.9A và không nâng `READY_FOR_USERS`.
