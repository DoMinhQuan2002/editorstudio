# FALL DIARY — TASK 3.9H REPORT

## Kết luận

Đã tạo `fall-diary / 0.5.0-layer-structure-pilot` bằng Template Definition schema và Template Compiler dùng chung. Bản mới tách timeline thành 5 background events và 6 overlay replacement events, giữ nguyên các Definition 0.1–0.4, và khai báo bố cục `editorial-safe-v1`. WPF đã chạy luồng Gallery → Details → Media Selection → Processing → Preview/Edit → Export; bản nháp r1 được lưu, app được khởi động lại, và cùng draft được mở lại từ Gallery.

0.5 là pilot có cấu trúc dựng tốt hơn 0.4. Đây chưa phải bản fidelity hoặc bản phát hành: source project/keyframe Muse không có, một candidate tại 13.267s vẫn chưa phân loại được, layout chưa được kiểm tra trên fixture ảnh đa dạng phù hợp, cutout và soundtrack chưa xác minh.

## Cổng nghiệm thu

| Gate | Trạng thái | Bằng chứng / giới hạn |
|---|---|---|
| `FALL_DIARY_EVENT_CLASSIFICATION_VERIFIED` | **true** | Các candidate có event class và evidence riêng; 13.267s và 15.067s giữ `UNKNOWN`. |
| `FALL_DIARY_BACKGROUND_CONTINUITY_VERIFIED` | **true** | 5 background events liên tục; thay overlay 3.767/5.267/6.767/9.267/10.267 không chia nền. Kiểm tra bằng Definition, Composition Graph và WPF preview. |
| `FALL_DIARY_OVERLAY_TIMING_VERIFIED` | **true** | 6 event có Slot ID, start/end ticks, layer order; starts/ends căn frame 30 fps. |
| `FALL_DIARY_MOTION_CONTINUITY_VERIFIED` | **true** | Shared linear keyframe engine; background không reset tại overlay boundary; preview và export đã decode/so khớp. Chỉ xác nhận continuity của pilot, không xác nhận motion nguồn Muse. |
| `FALL_DIARY_LAYOUT_QA_VERIFIED` | **false — PARTIAL** | Tất cả geometry nằm trong canvas, text không giao bounding box card. Chưa có bộ QA thứ hai chứa ảnh ngang và đa dạng chủ thể; không có subject detector đã kiểm chứng. |
| `FALL_DIARY_PREVIEW_EXPORT_PARITY_VERIFIED` | **true** | WPF preview và export cùng Project V2 r1, cùng fingerprint. So 22 frame sau khi scale export 1080p về 540p: RGB MAE trung bình 6.033, lớn nhất 9.433; đều dưới ngưỡng cross-resolution đã dùng ở 3.9D (12/24). SSIM toàn chuỗi 510 frame là 0.920438. Harness cùng graph ở cùng kích thước có MAE 1.749/2.248 dưới ngưỡng 3.5. |
| `FALL_DIARY_WPF_INTEGRATION_VERIFIED` | **true** | Đã thao tác thực tế đủ 6 màn hình, xuất MP4 trong WPF, phát player, khởi động lại app và mở lại bản nháp r1. |
| `FALL_DIARY_REFERENCE_MOTION_VERIFIED` | **false** | Không có project/keyframe nguồn; chuyển động nền 1.2% là editorial. |
| `FALL_DIARY_REFERENCE_FIDELITY_VERIFIED` | **false** | Bố cục/motion còn giả định editorial; 13.267s chưa phân biệt được cut nền với foreground insert. |
| `FALL_DIARY_CUTOUT_VERIFIED` | **false** | Không có segmentation/cutout mới trong task này. |
| `FALL_DIARY_AUDIO_FIDELITY_VERIFIED` | **false** | Không có soundtrack được cấp quyền hoặc timing được xác minh; output không có audio. |
| `FALL_DIARY_READY_FOR_USERS` | **false** | Pilot chưa có demo/poster, layout QA và reference fidelity chưa đạt. |

## Nguyên nhân và thay đổi cấu trúc

0.4 biểu diễn 10 trạng thái hình ảnh như 10 full-frame shot events. Các thay đổi nội dung ở 3.767, 5.267, 6.767, 9.267 và 10.267 giây vì thế bị biến thành thay nền, dù các khung Muse cho thấy nhiều candidate giữ landmark nền và chủ yếu thay card/insert. 0.4 còn dùng hai card editorial chia sẻ `photo-11`, nên không thể mô tả các lần replacement độc lập.

0.5 giữ nền qua các đoạn có evidence liên tục, đưa 6 replacement thành event layerOrder 1 độc lập, và giữ title graphic vector ở layerOrder 20. Số slot vẫn là 11 slot QA ổn định; đây không phải khẳng định số slot nguồn Muse. Slot mapping dùng ảnh fixture khi render, không hardcode Media ID trong definition.

| Version | Background / full-frame | Overlay | Title | Tổng Definition events |
|---|---:|---:|---:|---:|
| 0.3 reference pilot | 5 | 6 | 1 event / 9 glyph | 12 |
| 0.4 editorial motion pilot | 10 full-frame shot | 2 editorial card | 1 event / 9 glyph | 13 |
| 0.5 layer structure pilot | 5 | 6 replacement độc lập | 1 event / 9 glyph | 12 |

Chi tiết candidate và thời lượng nằm trong [timeline](FALL_DIARY_BACKGROUND_OVERLAY_TIMELINE.md); bảng so sánh cấu trúc ở [0.4 vs 0.5](FALL_DIARY_0_4_VS_NEW_STRUCTURE.md).

## Render và WPF

- WPF preview của draft r1: [Fall_Diary_3_9H_Preview.mp4](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Preview.mp4), 540×960, H.264, 30 fps, 17 giây, 510 frame. Bản preview từ shared-renderer harness được giữ riêng tại [Fall_Diary_3_9H_Shared_Renderer_Preview.mp4](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Shared_Renderer_Preview.mp4).
- WPF export thật: [Fall_Diary_3_9H_WPF_Export.mp4](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Export.mp4), 1080×1920, H.264, 30 fps, 17 giây, 510 frame, 6,157,141 bytes; không có audio stream.
- Harness Project V2: [Fall_Diary_3_9H_Project_V2.json](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Project_V2.json). Composition Graph: [Fall_Diary_3_9H_Composition_Graph.json](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Composition_Graph.json). WPF draft Project V2 r1: [Fall_Diary_3_9H_WPF_Project_V2.json](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Project_V2.json). Binding manifest: [Fall_Diary_3_9H_Binding_Manifest.json](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Binding_Manifest.json).
- Đối chiếu Muse / 0.3 / 0.4 / reference-layout QA / safe-layout: [Fall_Diary_3_9H_Reference_Comparison.jpg](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Reference_Comparison.jpg).
- Ảnh 11 fixture thật: [contact sheet](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Private_Photo_Fixture_Contact_Sheet.jpg). Ảnh nguồn được giữ nguyên; app import bản copy vào workspace QA cô lập.
- WPF runtime evidence: [Gallery](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Gallery_Reopened.jpg), [Details](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Details.jpg), [Media Selection 11/11](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Media_Selection.jpg), [Processing](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Processing.jpg), [Preview r1](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Preview_R1.jpg), [Export playback](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Export_Playback.jpg), [Preview reopened](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Preview_Reopened.jpg).

GUI project `99b4b283b46b4645a7cd222aee00ae2c`, revision 1, template `fall-diary`, Definition `0.5.0-layer-structure-pilot`. Export history ghi cùng project/revision/template và composition fingerprint `060873eca7608d243013cf72add8ac701f7748790dfbb4af1a4c7a221dbc6e3b`. WPF import UI gán ảnh theo thứ tự ngược với filename (`photo-01` → `photo_11.jpg` … `photo-11` → `photo_01.jpg`); bộ so sánh .3/.4/.5 dùng cùng một mapping chung khác. Vì vậy parity WPF được đo từ preview r1 và export r1; đối chiếu version dùng cùng fixture mapping giữa các bản.

## Build và tests

- WPF Release publish thành công; `dotnet test MediaStudio.Desktop.Tests`: **58 passed, 0 failed**.
- Backend tests liên quan: **105 passed, 3 skipped, 10 subtests passed**. Có một deprecation warning Starlette/anyio hiện hữu.
- Test cũ còn kỳ vọng .4 là latest và 10 scene durations; đã cập nhật sang .5 cùng 5 background durations. Definition .1–.4 vẫn được kiểm tra riêng.
- Preview, shared-renderer output và WPF MP4 đều qua FFprobe/full decode. Chi tiết parity ở [FALL_DIARY_PREVIEW_EXPORT_PARITY.md](FALL_DIARY_PREVIEW_EXPORT_PARITY.md).

## Quyết định còn mở

1. 13.267s có phải cut nền hay full-frame foreground insert hay không.
2. Điểm kết chính xác của title sau 13.833s; 17s hiện là pilot assumption.
3. Có chấp nhận `editorial-safe-v1` làm mặc định hay cần giữ một layout option tham chiếu gần Muse.
4. Cần fixture QA thứ hai có ảnh ngang, portrait close-up, full-body và landscape thật để đóng layout gate.
5. Cần cung cấp quyền/timing soundtrack và foreground cutout nếu các capability đó còn nằm trong phạm vi sản phẩm.

Task 3.9H dừng tại đây; không tự triển khai task sau.
