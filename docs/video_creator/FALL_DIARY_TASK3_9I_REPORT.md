# FALL DIARY — TASK 3.9I
# Visual Quality Acceptance & Template Refinement

**Ngày thực hiện:** 2026-10-24  
**Phiên bản được đánh giá:** `fall-diary / 0.5.0-layer-structure-pilot`  
**Phạm vi:** kiểm tra QA bằng fixture cục bộ, so sánh hai layout, rà soát motion từ frame reference có sẵn và kiểm tra Preview/Export bằng shared renderer. Không tạo Definition 0.6.

## Kết luận

Giữ Definition 0.5 làm pilot. Chưa có căn cứ để thay đổi product layout hoặc tạo Definition 0.6: bộ ảnh được phép hiện có chỉ là ảnh riêng tư dùng QA và toàn bộ ảnh là ảnh dọc; chưa có fixture ngang được phê duyệt, ảnh không có người, hay annotation face/subject đủ để đo occlusion. Reference Layout QA gần bố cục Muse hơn trong vị trí title/card; Editorial Safe thay đổi có chủ đích sang title góc trên trái và card nhỏ dưới phải. Đây là khác biệt editorial, không phải bằng chứng rằng một profile tốt hơn trên ảnh bất kỳ.

Đã biên dịch 0.3, 0.4, 0.5 Reference Layout QA và 0.5 Editorial Safe với cùng 11 media bindings. Tất cả bốn preview là H.264 540×960, 30 fps, 17 giây/510 frame, full-decode thành công. Hai profile 0.5 có thêm export H.264 1080×1920; parity qua 22 frame quanh các mốc timeline, với MAE trung bình 5.067/255 (Reference Layout QA) và 4.796/255 (Editorial Safe). Không có blackdetect interval trong sáu MP4 đã quét. Các kết quả này xác nhận khả năng render/parity trên binding cục bộ hiện có, không đóng gate multi-media/layout, không phải GUI acceptance và không đo độ giống Muse.

## Bằng chứng và giới hạn

- Nguồn Muse là screen recording, không có project hoặc source keyframes. Các mốc 3.767–13.267 giây được xem như candidate quan sát; chuyển động trong footage không được quy thành animation của template.
- Bộ 11 ảnh đã được cung cấp trước đó chỉ được dùng cho local QA trong tác vụ này. Không sao chép hoặc sửa ảnh nguồn. Manifest ghi SHA-256 trước/sau giống nhau.
- Bộ `second_fixture_set` sẵn có là hình học tổng hợp; không tính là ảnh chụp thực tế hay bằng chứng layout trên ảnh người dùng.
- Không có face/subject detector đã kiểm chứng và không có bộ annotation bounding box. Vì vậy tỷ lệ giao nhau với mặt/chủ thể được ghi là **chưa đo**, không suy luận từ layer bounds.
- Không chạy WPF GUI cho các biến thể 3.9I. Bằng chứng WPF/Save-Reopen trước đó chỉ áp dụng cho draft 0.5 r1 của Task 3.9H; không thay cho acceptance GUI của hai variant QA mới.

## Kết quả theo cổng

| Gate | Trạng thái | Cơ sở |
|---|---|---|
| `FALL_DIARY_MULTI_MEDIA_QA_VERIFIED` | **false — FIXTURE_MISSING** | Chưa có bộ ảnh thật thứ hai được duyệt; thiếu ảnh ngang 16:9/4:3 và ảnh không có người. |
| `FALL_DIARY_LAYOUT_QA_VERIFIED` | **false — PARTIAL** | Hai profile được render và xem ở 6 mốc; chưa có fixture đa dạng/annotation để xác minh subject-safe. |
| `FALL_DIARY_REFERENCE_LAYOUT_REVIEWED` | **true — QA only** | Đã đối chiếu cùng bindings với reference crop và Editorial Safe. Không đồng nghĩa reference fidelity. |
| `FALL_DIARY_SAFE_LAYOUT_REVIEWED` | **true — QA only** | Đã xem profile 0.5 safe trên cùng 6 mốc và cùng bindings. |
| `FALL_DIARY_OVERLAY_MOTION_ANALYZED` | **true — limited evidence** | Đã phân loại sáu khoảng thời gian yêu cầu từ crop trước/tại/sau. Không khôi phục keyframe nguồn. |
| `FALL_DIARY_BACKGROUND_CONTINUITY_VERIFIED` | **true — structural/render scope** | Shared graph giữ background track độc lập qua replacement events; full decode/blackdetect trên 6 output không báo frame đen. Không xác nhận source cut 13.267s. |
| `FALL_DIARY_PREVIEW_EXPORT_PARITY_VERIFIED` | **true — shared renderer only** | Hai profile 0.5 dùng cùng Project V2/Graph/Binding; 22 frame mỗi cặp dưới ngưỡng cross-resolution MAE 12/24. Không phải GUI parity. |
| `FALL_DIARY_0_6_DECISION_READY` | **true — quyết định là hoãn 0.6** | Bằng chứng đủ để không tạo version mới trước khi có fixture/annotation được duyệt và review người dùng. |
| `FALL_DIARY_REFERENCE_MOTION_VERIFIED` | **false** | Không có source keyframes; footage và camera recording có thể tạo chuyển động biểu kiến. |
| `FALL_DIARY_REFERENCE_FIDELITY_VERIFIED` | **false** | Layout/motion còn editorial; candidate 13.267s và title end-time chưa xác minh. |
| `FALL_DIARY_AUDIO_FIDELITY_VERIFIED` | **false** | Không có soundtrack/timing được cấp quyền và xác minh. |
| `FALL_DIARY_CUTOUT_VERIFIED` | **false** | Không có cutout/segmentation được kiểm chứng. |
| `FALL_DIARY_READY_FOR_USERS` | **false** | Các gate về multi-media, layout semantics, fidelity, audio và cutout chưa đạt. |

## Đầu ra QA

Các file dưới đây chứa hình ảnh cá nhân trong phạm vi local QA. Không đưa chúng vào Git, release package hoặc public artifact.

- So sánh 0.3 / 0.4 / 0.5 Reference Layout QA / 0.5 Editorial Safe: [contact sheet](../../artifacts/video_creator/task3_9i/Fall_Diary_3_9I_Comparison_Contact_Sheet.jpg).
- Video preview 0.3: [MP4](../../artifacts/video_creator/task3_9i/Fall_Diary_3_9I_0_3_Reference_Pilot_Preview.mp4).
- Video preview 0.4: [MP4](../../artifacts/video_creator/task3_9i/Fall_Diary_3_9I_0_4_Editorial_Motion_Pilot_Preview.mp4).
- Video preview 0.5 Reference Layout QA: [MP4](../../artifacts/video_creator/task3_9i/Fall_Diary_3_9I_0_5_Reference_Layout_QA_Preview.mp4); export: [MP4](../../artifacts/video_creator/task3_9i/Fall_Diary_3_9I_0_5_Reference_Layout_QA_Export.mp4).
- Video preview 0.5 Editorial Safe: [MP4](../../artifacts/video_creator/task3_9i/Fall_Diary_3_9I_0_5_Editorial_Safe_Preview.mp4); export: [MP4](../../artifacts/video_creator/task3_9i/Fall_Diary_3_9I_0_5_Editorial_Safe_Export.mp4).
- Bindings, FFprobe, full-decode, parity samples, input hash và contact-sheet frame hashes: [QA manifest](../../artifacts/video_creator/task3_9i/Fall_Diary_3_9I_QA_Manifest.json).
- Project V2 và Composition Graph riêng cho từng profile: nằm trong cùng [thư mục Task 3.9I](../../artifacts/video_creator/task3_9i).

WPF evidence có từ Task 3.9H được giữ riêng trong [GUI acceptance report](FALL_DIARY_WPF_GUI_ACCEPTANCE.md) và [Preview/Export parity report](FALL_DIARY_PREVIEW_EXPORT_PARITY.md); không coi đó là lần chạy GUI của Task 3.9I.

## Tài liệu kèm theo

- [Layout quality matrix](FALL_DIARY_LAYOUT_QUALITY_MATRIX.md)
- [Multi-media fixture report](FALL_DIARY_MULTI_MEDIA_FIXTURE_REPORT.md)
- [Reference vs Safe layout review](FALL_DIARY_REFERENCE_VS_SAFE_LAYOUT.md)
- [Overlay motion review](FALL_DIARY_OVERLAY_MOTION_REVIEW.md)
- [Definition 0.6 readiness decision](FALL_DIARY_0_6_READINESS_DECISION.md)
- [Visual acceptance gates](FALL_DIARY_VISUAL_ACCEPTANCE.md)

