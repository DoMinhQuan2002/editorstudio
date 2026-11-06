# Screen 04 — Progress và stage mapping

## Progress ring

Backend chưa phát phần trăm trung gian đáng tin cậy. Vì vậy ring quay indeterminate khi progressPercent null; giao diện không nội suy, đếm giờ hay hardcode 65%. Backend chỉ trả 100 khi preview PNG đã dựng và Project V2 đã được lưu. WPF vẫn xác minh lại project/preview trước khi chuyển UI sang trạng thái thành công.

## Stage mapping

| Stage ID | Nhãn UI | Nguồn trạng thái |
|---|---|---|
| analyze_media | Phân tích media | Kiểm tra binding, metadata, kind và file đọc được |
| apply_layout | Áp dụng bố cục mẫu | Template Compiler sinh Project V2 và xác nhận metadata template/version/bindings |
| build_composition | Tạo chuyển cảnh và hiệu ứng | Composition Graph được dựng/kiểm tra; tính năng renderer không hỗ trợ bị từ chối |
| sync_audio | Đồng bộ nhạc nền | COMPLETED nếu graph có audio track enabled; SKIPPED nếu không có track audio |
| prepare_preview | Hoàn tất... | Dựng frame PNG thật, lưu project, đọc lại metadata và chỉ sau đó đánh dấu hoàn tất |

UI ánh xạ PENDING, RUNNING, COMPLETED, SKIPPED và FAILED trực tiếp từ job snapshot. Thông báo stage được giữ làm tooltip/text phụ; thông báo SKIPPED/FAILED hiển thị cạnh dòng tương ứng.

Animation ring lấy từ JobStatus: chỉ QUEUED/RUNNING mới quay. FAILED/CANCELLED dừng animation và dùng màu đỏ; SUCCEEDED dừng animation ở phần trăm backend trả về.

## Độ tin cậy và ranh giới

Stage mô tả thao tác đã chạy, không phải ước lượng thời gian. Build composition hiện xác thực graph và khả năng renderer; nó không đồng nghĩa đã render toàn bộ video. Screen 04 tạo bản nháp có frame preview, không tạo file MP4.
