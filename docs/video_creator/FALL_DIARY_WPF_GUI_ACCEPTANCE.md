# FALL DIARY — WPF GUI ACCEPTANCE 3.9H

## Runtime result

Đã sử dụng WPF app đã publish với data/models/runtime workspace riêng tại `artifacts/video_creator/task3_9h/runtime_workspace/`. Luồng chạy thực tế:

| Màn | Quan sát runtime |
|---|---|
| 01 Gallery | Fall Diary hiện là `Pilot · chưa có demo`, 11 media slots, 17s, 5 background scenes. Sau restart, nút **Bản nháp** hiện `Fall Diary Layer Structure Pilot 0.5 · r1`. |
| 02 Details | Metadata `fall-diary / 0.5.0-layer-structure-pilot`, 11 slots, không có poster/demo; click Details chưa tạo project. |
| 03 Media Selection | File Picker import/copy 11 ảnh QA; 11/11 media được chọn, 11/11 slot được gán; slot IDs photo-01…photo-11. Selection map được lưu trong Project V2. |
| 04 Processing | Backend validate bindings và Template Compiler tạo Project V2 mới. Job hoàn tất 100%, UI ghi project ID `99b4b283b46b4645a7cd222aee00ae2c`; stage music bỏ qua vì definition không có audio track. |
| 05 Preview/Edit | Player dựng từ Project V2/Composition Graph; hiển thị đúng template version 0.5, r1, 17s, 9:16, 1080×1920. Scene list hiển thị các background/overlay event. Preview phát collage thật; không phát demo Muse. |
| 06 Export | WPF export tạo MP4 thật 1080×1920, H.264, 30 fps, 17s. UI báo export thành công; player phát và hiển thị frame đang chạy. |

Sau export, app được đóng và mở lại với cùng isolated data directory. Gallery tìm thấy nút mở bản nháp gần nhất; mở lại đưa về Preview/Edit với cùng project ID/revision, version 0.5 và regenerated preview từ Composition Graph. Không có project mới được tạo trong bước reopen.

## Screenshot evidence

- [Gallery sau restart](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Gallery_Reopened.jpg)
- [Template Details](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Details.jpg)
- [Media Selection, 11/11](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Media_Selection.jpg)
- [Processing, project ID và stages](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Processing.jpg)
- [Preview r1](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Preview_R1.jpg)
- [Export success](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Export_Success.jpg)
- [Export player đang phát](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Export_Playback.jpg)
- [Preview sau khi reopen](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Preview_Reopened.jpg)

## Files và trạng thái

- WPF project file: `artifacts/video_creator/task3_9h/runtime_workspace/video_editor/video_editor/projects/99b4b283b46b4645a7cd222aee00ae2c.json`.
- Export history: cùng thư mục `export_history/99b4b283b46b4645a7cd222aee00ae2c.json`; `status=SUCCEEDED`, revision 1, template 0.5, output WPF MP4.
- Bản project để lưu cùng deliverables: [Fall_Diary_3_9H_WPF_Project_V2.json](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Project_V2.json). Video: [WPF preview r1](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Preview.mp4), [WPF export r1](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_WPF_Export.mp4).
- Cùng-revision parity: 22 frame mẫu được so sánh sau khi scale export về preview resolution; mean RGB MAE 6.033/255, max 9.433/255. Toàn bộ 510 frame có SSIM 0.920438; cả hai file đều FFprobe/full-decode hợp lệ. Chi tiết tại [parity report](FALL_DIARY_PREVIEW_EXPORT_PARITY.md).
- Media file picker sao chép media vào workspace cô lập; không sửa file nguồn `local_reference/fall_diary/private_test_media` hoặc user projects.
- GUI status: **PASS cho luồng 6 màn và save/reopen**. Đây không phải layout/fidelity release acceptance.
