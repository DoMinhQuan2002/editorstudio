# MEDIA STUDIO — TASK 3.9G REPORT
# FALL DIARY — REFERENCE-DRIVEN VISUAL & MOTION PILOT

Ngày thực hiện: 23-10-2026

## Kết quả

TASK 3.9G đã tạo definition mới FALL DIARY 0.4.0-editorial-motion-pilot, render bằng Template Compiler và Composition Graph dùng chung, rồi chạy thật trên WPF qua sáu màn hình. Bản xuất WPF mở lại được từ Gallery sau khi khởi động lại ứng dụng.

0.4 là một **editorial motion pilot**. Các điểm đổi hình được chọn từ trạng thái nhìn thấy trong video screen recording Muse; chúng không phải cut hoặc keyframe nguồn đã được xác minh. Chuyển động scale và chuyển động card là thiết kế của Media Studio. Reference fidelity và ready-for-users vẫn false.

## Cổng nghiệm thu

| Gate | Kết quả | Bằng chứng / giới hạn |
|---|---|---|
| FALL_DIARY_REFERENCE_MOTION_ANALYZED | true | Đã xem crop preview và các frame trước/sau tại các candidate change points; không khôi phục được keyframe của source từ screen recording. |
| FALL_DIARY_NEW_DEFINITION_READY | true | Definition 0.4 hợp lệ với schema chung; 11 slot ổn định; compile thành Project V2 và graph chung. |
| FALL_DIARY_DYNAMIC_LAYOUT_VERIFIED | true, trong phạm vi khai báo | 10 shot, 2 card độc lập, 9 glyph; layer order và thời điểm được kiểm tra qua graph/render. Không có subject detection. |
| FALL_DIARY_KEYFRAME_MOTION_VERIFIED | true, editorial | Scale của ảnh nền và position/scale của card nội suy tuyến tính, được render ở preview/export. Đây không phải motion fidelity với Muse. |
| FALL_DIARY_PREVIEW_EXPORT_PARITY_VERIFIED | true | 20 frame still-vs-export: mean RGB MAE 2.03518, max 2.84328; 510-frame SSIM trung bình 0.9127. WPF MP4 và harness export có SHA-256 trùng nhau. |
| FALL_DIARY_WPF_INTEGRATION_VERIFIED | true | WPF thực tế Gallery → Details → Media Selection → Processing → Draft Preview → Export; export success; đóng/mở lại WPF rồi mở bản nháp mới nhất và phát lại preview. |
| FALL_DIARY_LAYOUT_QA_VERIFIED | false | Chữ FALL DIARY ở vị trí giữa ảnh tham chiếu che mặt trên một số ảnh QA; card dưới phải cũng có thể đè lên thân người. Không có cách tránh theo từng ảnh nếu không có nhận diện chủ thể. |
| FALL_DIARY_REFERENCE_MOTION_VERIFIED | false | Không tách được chuyển động nội dung ảnh khỏi chuyển động của cảnh quay trong video tham chiếu. |
| FALL_DIARY_REFERENCE_FIDELITY_VERIFIED | false | Cut/timing cuối, chuyển cảnh, motion nguồn, title end-time, cutout và audio chưa được xác minh. |
| FALL_DIARY_CUTOUT_VERIFIED | false | Không có foreground cutout trong definition mới. |
| FALL_DIARY_AUDIO_FIDELITY_VERIFIED | false | Muse soundtrack không được dùng; output không có audio stream. |
| FALL_DIARY_READY_FOR_USERS | false | Đây là pilot, chưa có demo/poster được cấp quyền, layout có thể che chủ thể và fidelity chưa xác minh. |

Gate dynamic layout chỉ xác nhận cấu trúc đa lớp, event timing và vị trí nằm trong canvas ở fixture. Gate layout QA tổng thể được giữ false vì title/card giao với chủ thể trong một số frame thật.

## Definition và timeline

- Template ID: fall-diary
- Version: 0.4.0-editorial-motion-pilot
- Canvas: 1080×1920, 30/1 fps, timebase 90,000 ticks/s
- Duration: 1,530,000 ticks, 17 giây, 510 frame
- Slots: photo-01…photo-11; 11 slot bắt buộc, image-only, reuse được theo policy
- Events: 10 full-frame shots + 2 editorial cards + 1 title event; composition graph có 21 clip gồm 12 image clip và 9 text glyph
- Không có source Media ID, demo, poster hoặc audio asset hardcode trong reusable definition.
- Definition 0.1, 0.2 và 0.3 vẫn còn nguyên trong registry.

Timeline shot dùng các mốc 0, 339,000, 474,000, 519,000, 609,000, 834,000, 879,000, 924,000, 1,194,000 và 1,239,000 ticks; kết thúc pilot tại 1,530,000 ticks. Tất cả đều chia hết cho 3,000 ticks/frame. Các mốc đầu là candidate timestamp từ screen recording, được dùng làm điểm dựng của pilot chứ không tuyên bố là cut gốc.

Các animation chỉ dùng linear interpolation đã hỗ trợ: scale 1.0→1.0+0.012×duration/90,000 trên từng shot; hai card dùng positionX 0.28→0.24, positionY 0.30→0.24, scale 0.24→0.27. Phân loại trong definition là editorial. Không thêm easing phi tuyến, transition mới, segmentation hay cutout.

## GUI thực tế và dữ liệu

WPF publish Release trong artifacts/video_creator/task3_9g/app đã mở ở workspace runtime riêng. Gallery và Details hiển thị đúng template fall-diary, version 0.4.0-editorial-motion-pilot, 11 slot, 17 giây, trạng thái Pilot · chưa phát hành, không có demo/poster. Media Selection hiển thị 11 Slot ID. Đã nhập 12 ảnh QA thật bằng File Picker; chọn 11 ảnh, gán photo-01…photo-11 đúng tên photo_01.jpg…photo_11.jpg và để photo_12.jpg chưa chọn. Quay lại Details rồi vào lại Selection vẫn giữ 11/12 đã chọn và 11/11 đã gán.

Processing tạo Project V2 mới, Project ID ffa6f7c801c44e20b557263e6f300afa, revision 1, template fall-diary / 0.4.0-editorial-motion-pilot. Job hoàn tất; draft preview thực có nhiều shot/card và phát từ 00:00 đến 00:02 trong lần mở lại. Project JSON lưu trong runtime_workspace cô lập, không ghi đè Project V2 r4 hoặc User Projects.

WPF Export báo thành công cho:

- [Fall_Diary_3_9G_WPF_Export.mp4](../../artifacts/video_creator/task3_9g/wpf_output/Fall_Diary_3_9G_WPF_Export.mp4)
- Project ID: ffa6f7c801c44e20b557263e6f300afa, revision 1
- H.264, 1080×1920, 30/1 fps, 17 giây, 510 frame, không có audio stream
- FFprobe thành công; full decode bằng FFmpeg exit code 0
- SHA-256: 621A5D35750E1F28440106099DB827D556D091657CD038EEAC49C25DCDC138B4

Sau khi khởi động lại cùng app/runtime, Gallery bật nút “Bản nháp” và nêu Fall Diary Editorial Motion Pilot 0.4 · r1. Mở nút đó gọi lại project, khôi phục đúng Template ID/version/revision, dựng lại preview và phát được. WPF output và harness export giống byte-for-byte.

## Tệp đầu ra và so sánh

- [Preview MP4 540×960](../../artifacts/video_creator/task3_9g/Fall_Diary_3_9G_Preview.mp4)
- [Harness Export MP4 1080×1920](../../artifacts/video_creator/task3_9g/Fall_Diary_3_9G_Export.mp4)
- [WPF Export MP4 1080×1920](../../artifacts/video_creator/task3_9g/wpf_output/Fall_Diary_3_9G_WPF_Export.mp4)
- [Project V2](../../artifacts/video_creator/task3_9g/Fall_Diary_3_9G_Project_V2.json)
- [Composition Graph](../../artifacts/video_creator/task3_9g/Fall_Diary_3_9G_Composition_Graph.json)
- [Manifest QA](../../artifacts/video_creator/task3_9g/Fall_Diary_3_9G_Manifest.json)
- [Contact sheet Muse / 0.2 / 0.3 / 0.4](../../artifacts/video_creator/task3_9g/Fall_Diary_3_9G_Reference_Comparison_Contact_Sheet.jpg)
- [Contact sheet Preview / Export](../../artifacts/video_creator/task3_9g/Fall_Diary_3_9G_Preview_Export_Contact_Sheet.jpg)
- [Contact sheet fixture thứ hai](../../artifacts/video_creator/task3_9g/Fall_Diary_3_9G_Second_Fixture_Contact_Sheet.jpg)

Fixture thứ hai gồm 6 ảnh khác, được compile qua 11 slot có reuse, duration 17 giây, 30 fps và full-decode thành công. Hash ảnh nguồn trước/sau giữ nguyên. 12 ảnh QA ban đầu không bị sửa; WPF runtime lưu media trong thư mục QA riêng.

## Build và tests

- Backend tests liên quan (FALL DIARY 3.9A/B/C/G, Template Compiler 3.4, Media Selection 3.3, Processing 3.5, Project V2, Composition, Draft Preview, Export): **105 passed, 3 skipped, 10 subtests passed**, 1 deprecation warning hiện hữu từ Starlette/anyio.
- WPF tests: **58 passed, 0 failed**.
- WPF Release publish win-x64: thành công; chính executable đó được dùng cho GUI run.
- Harness Preview/Export: FFprobe và full decode đều pass; không có audio stream.
- Denim Story: regressions backend/WPF unit tests nằm trong suite đã chạy; không có thao tác GUI riêng cho Denim Story trong 3.9G.
- Image Tools không có source change; app được mở lại ở trang Image Tools mặc định sau khi restart và vẫn tải giao diện bình thường.

## Source changes

- backend/mediastudio/video_editor/definitions/fall-diary-0.4.0-editorial-motion-pilot.json
- backend/mediastudio/video_editor/media_selection.py — đăng ký version 0.4
- backend/mediastudio/video_editor/catalog.py — metadata, duration, slot count và trạng thái pilot
- backend/tests/test_fall_diary_task39g.py
- tools/video_creator/create_fall_diary_task39g_definition.py
- tools/video_creator/render_fall_diary_task39g.py
- Sáu báo cáo cùng task này trong docs/video_creator/

Không sửa Template Compiler/renderer, WPF source, Project V2 r4, User Projects, media nguồn, Image Tools hoặc Definition 0.1/0.2/0.3. Không commit/push.

## Còn lại

1. Title nằm giữa khung theo quan sát Muse nhưng che mặt trên fixture có người; cần quyết định giữa giữ reference placement và đổi sang vùng editorial an toàn.
2. Card không nhận diện người/vật; vị trí dưới phải nằm trong canvas nhưng có thể đè lên thân người.
3. Chuyển động thấy trong Muse có thể thuộc footage, không chứng minh template keyframe. Definition 0.4 ghi rõ motion là editorial.
4. Scene timing cuối, title end-time và phần cuối screen recording chưa xác định chắc chắn.
5. Chưa có segmentation/cutout đã kiểm chứng hoặc soundtrack có quyền/timing phù hợp.
6. Chưa có demo video hoặc poster phù hợp để phát hành.

### Đề xuất bước tiếp

Xin duyệt lựa chọn vị trí title (giữ vị trí trung tâm theo Muse hay dùng editorial safe-area), rồi thử QA bằng bộ media có nhiều loại bố cục người/vật. Sau đó mới xác minh cutout/audio theo nguồn được cấp quyền; không nâng Reference Fidelity hoặc Ready for Users khi các blocker chưa xử lý.
