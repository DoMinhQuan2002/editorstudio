# FALL DIARY — 0.3 VS 0.4 COMPARISON

| Thuộc tính | 0.3.0-reference-pilot | 0.4.0-editorial-motion-pilot |
|---|---|---|
| Tính toàn vẹn | Definition giữ nguyên | Definition mới, không sửa .3 |
| Slot | 11: photo-01…photo-11 | 11 slot ổn định giống .3 |
| Main visuals | 5 background event | 10 full-frame shot event theo visible-state candidates |
| Overlay | 6 overlay event thay thế/collage | 2 editorial card event độc lập, đều reuse photo-11 |
| Title | 9 glyph, xuyên suốt 17s | Giữ 9 glyph và vị trí gần .3/reference |
| Motion | Không keyframe | Linear push-in nhẹ cho 10 shot; X/Y/scale cho 2 card |
| Event total | 12 definition events (5 background + 6 overlay + title) | 13 events (10 shot + 2 card + title) |
| Graph clips | 20 (11 image + 9 text) | 21 (12 image + 9 text) |
| Timing | Main background dài 5.7667, 4.0, 3.5, 0.5, 3.2333s; overlays độc lập | Main event duration variable: 3.7667, 1.5, 0.5, 1.0, 2.5, 0.5, 0.5, 3.0, 0.5, 3.2333s |
| Renderer | Shared Template Compiler / graph | Cùng shared Template Compiler / graph |
| Duration/rate | 17s, 30 fps, 90 kHz | Giữ nguyên |
| Cutout/audio | Không | Không |
| Fidelity | Reference pilot; motion chưa xác minh | Editorial motion pilot; reference fidelity vẫn false |

## So sánh trực quan

[Contact sheet Muse crop / 0.2 / 0.3 / 0.4](../../artifacts/video_creator/task3_9g/Fall_Diary_3_9G_Reference_Comparison_Contact_Sheet.jpg) đặt crop Muse gần nhất ở cột đầu, rồi render 0.2, 0.3, 0.4 tại 19 mốc thời gian quanh các candidate boundaries.

- 0.4 có 10 trạng thái nền riêng nên nhịp thay đổi nhanh/chậm khác nhau thay vì 5 background interval của .3.
- Hai card ở 6.767–9.267s và 10.267–13.267s xuất hiện song song nền, tạo collage thật trong graph thay vì chỉ đổi toàn khung.
- 0.2 đã có prototype keyframe nhưng không phải cấu hình nguồn đã phục hồi. 0.3 có timing/layout từ các thay đổi nhìn thấy nhưng không có keyframe. 0.4 thêm chuyển động linear gắn nhãn editorial.
- Title giữ liên tục ở cả các version đang so. 17s không chứng minh title có cùng end-time trong Muse.
- Muse preview là screen recording với footage/card/title; chuyển động trong footage không chứng minh template motion.
- 0.4 fixture cho thấy title chồng lên mặt người ở vài cảnh. Đây là hạn chế bố cục được giữ rõ trong báo cáo, không được che bằng SSIM.
- Không dùng SSIM giữa nội dung Muse và ảnh fixture để chấm fidelity. SSIM chỉ đo parity giữa output preview và export của cùng một Composition Graph.
- Cutout và audio không có ở 0.4; không đóng gói Muse soundtrack hoặc footage/UI Muse vào output.

## Gate

0.4 cải thiện cấu trúc collage và tạo keyframe thật trong shared engine. Nó không được gọi là bản sao hay bản fidelity của Muse. FALL_DIARY_REFERENCE_FIDELITY_VERIFIED=false, FALL_DIARY_READY_FOR_USERS=false.
