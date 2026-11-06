# FALL DIARY — WPF GUI ACCEPTANCE 3.9G

## Môi trường

WPF Release build tại artifacts/video_creator/task3_9g/app được chạy với backend và data directory riêng:

- artifacts/video_creator/task3_9g/runtime_workspace
- artifacts/video_creator/task3_9g/models
- Project mới: ffa6f7c801c44e20b557263e6f300afa

Không dùng Project V2 revision 4 của 3.9F làm nền, không ghi đè User Projects hay media nguồn.

## Sáu màn hình đã thao tác

| Screen | Kết quả quan sát |
|---|---|
| 01 Gallery | FALL DIARY hiển thị 00:17, 10 shot, 11 slot, pilot; mô tả nói rõ chuyển động editorial chưa xác minh fidelity. Không có demo/poster. |
| 02 Details | Metadata Template ID fall-diary, Definition 0.4.0-editorial-motion-pilot, 11 slot, 17s, 1080×1920, 9:16. Chọn template không tạo project. |
| 03 Media Selection | File Picker nhập 12 ảnh thật từ private_test_media. Chọn 11; gán photo-01…photo-11 đúng photo_01.jpg…photo_11.jpg. photo_12.jpg chưa chọn. 11/11 slot hợp lệ. |
| 04 Processing | Backend nhận request, xác thực bindings, chạy Template Compiler và lưu Project V2 mới; Composition Graph hợp lệ, job hoàn thành 100%. Không tự sang Preview trước khi draft sẵn sàng. |
| 05 Draft Preview | Preview thật từ Project V2 r1, đúng template/version và thời lượng 17s; có 10 shot, 2 card event và title glyph. Play tiến thời gian; audio báo không có track. |
| 06 Export | WPF export MP4 thật từ Project V2 r1. Màn hình báo Export Success; đường dẫn trong thư mục QA riêng. FFprobe và full decode pass. |

## Selection state, bindings, reopen

Từ Selection quay lại Details rồi vào Selection lần nữa: state giữ 11/12 media selected, 11/11 bound, cùng mapping slot. Binding payload được lưu trong Project V2 templateMetadata. Mở Màn 3 không tạo project; project chỉ được tạo sau Apply/Processing.

Sau export, đóng app và khởi động lại cùng executable/runtime workspace. Gallery nạp nút “Bản nháp” với tooltip Fall Diary Editorial Motion Pilot 0.4 · r1. Chọn nút này mở lại đúng Project V2, template/version và revision 1. Backend dựng lại preview từ graph; UI báo preview revision 1 sẵn sàng. Preview phát đến 00:02 và màn Export player phát tiếp đến 00:08. Project/file giữ nguyên ID/version.

Export:

- [WPF MP4](../../artifacts/video_creator/task3_9g/wpf_output/Fall_Diary_3_9G_WPF_Export.mp4)
- H.264, 1080×1920, 30/1, 17s, 510 frame
- FFprobe: pass; FFmpeg full decode: exit 0
- WPF export hash bằng harness export

## Bằng chứng và giới hạn

GUI state được đọc từ accessibility tree của process WPF đang chạy ở từng màn; các thao tác media, playback, export và reopen thực hiện trong ứng dụng. Không suy GUI acceptance từ backend harness. Ảnh đối chiếu render có sẵn trong [contact sheet](../../artifacts/video_creator/task3_9g/Fall_Diary_3_9G_Reference_Comparison_Contact_Sheet.jpg); không lưu screenshot runtime WPF thành file riêng trong workspace.

Denim Story regression nằm trong suite test WPF/backend đã chạy nhưng không thao tác riêng bằng GUI trong lần 3.9G này. Các template khác chưa có slot definition vẫn hiển thị “Chưa khai báo vị trí media” và không được thử áp dụng. Image Tools không có source changes; sau khi restart app, trang Image Tools mặc định mở được và nút Video Editor điều hướng được.

### Gate

- FALL_DIARY_WPF_INTEGRATION_VERIFIED=true
- FALL_DIARY_PREVIEW_EXPORT_PARITY_VERIFIED=true
- FALL_DIARY_LAYOUT_QA_VERIFIED=false vì title/card có thể giao với chủ thể.
- FALL_DIARY_REFERENCE_FIDELITY_VERIFIED=false
- FALL_DIARY_READY_FOR_USERS=false
