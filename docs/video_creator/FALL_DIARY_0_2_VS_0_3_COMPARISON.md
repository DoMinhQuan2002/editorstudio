# FALL DIARY — 0.2 VS 0.3

| Thuộc tính | 0.2.0-motion-pilot | 0.3.0-reference-pilot |
|---|---|---|
| Mục tiêu | Motion/collage prototype 3.9B, không phải cấu hình đã khôi phục từ Muse. | Timeline/layout pilot được đặt lại theo các thay đổi nhìn thấy trong reference screen recording. |
| Event timing | Sáu event 2.5 giây bằng nhau theo baseline 3.9B. | 5 background segment: 5.7667, 4.0, 3.5, 0.5, 3.2333 giây; overlay có timeline độc lập 0.5–3 giây. |
| Duration | Pilot cũ 15 giây. | 17 giây theo metadata template Muse; source duration chưa xác minh. |
| Event count | Bố cục prototype theo event cũ. | 5 background + 6 overlay + 1 title event; 9 text layer riêng. |
| Motion | Có capability thử nghiệm 3.9B. | Không có keyframe: không tự nhận motion mẫu đã khôi phục. Dùng event replacement/hard cut quan sát được. |
| Layout | Có collage/motion prototype; 3.9B report ghi card đôi khi che mặt/mất cân đối. | Card `contain` scale 0.27–0.28, đặt theo safe-area ở nửa trên; layer order rõ. Bounds đã kiểm; không có subject detection. |
| Title | Title graphic của prototype trước. | Chữ tile `FALL DIARY` tách 9 ký tự, dùng renderer text nội bộ; vị trí/style lấy gần đúng từ crop, title end chưa chắc chắn. |
| Slots | Giữ nguyên definition đã đóng băng. | 11 slot role-based pilot, required image, reuse allow, missing error; không tuyên bố 11 slot là số slot Muse. |
| Source references | Không ghi đè. | Không có fixture Media ID hay phụ thuộc ảnh QA trong reusable definition. |
| Audio/cutout | Không khẳng định quyền Muse. | Không audio, không cutout; cả hai fidelity gates vẫn false. |

0.1.0-pilot và 0.2.0-motion-pilot vẫn được registry và regression tests giữ nguyên. 0.3 là definition độc lập; dùng Template Compiler/Composition Graph renderer chung. `FALL_DIARY_REFERENCE_FIDELITY_VERIFIED=false` và `FALL_DIARY_READY_FOR_USERS=false` dù preview/export parity đạt.

Frame comparison ba bản và reference: `artifacts/video_creator/task3_9c/Fall_Diary_Reference_vs_0_3_Frame_Comparison.jpg`. Preview/Render mới: `artifacts/video_creator/task3_9c/Fall_Diary_Reference_Pilot_Preview.mp4`, `Fall_Diary_Reference_Pilot_Render.mp4`; runtime WPF export: `Fall_Diary_Reference_Pilot_WPF_Export.mp4`.
