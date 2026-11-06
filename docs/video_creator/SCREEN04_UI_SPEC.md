# Screen 04 — UI spec

## Mục đích

Screen 04 là trạng thái xử lý giữa bước chọn media và bước xem/chỉnh sửa nhẹ. Không chứa timeline, player editor, inspector hay điều khiển xuất MP4.

## Bố cục đã triển khai

- Dùng shell, sidebar và header Media Studio hiện có.
- Phần đầu nội dung có nút Quay lại và stepper Chọn media → Xử lý → Chỉnh sửa → Xuất. Mục 1 hoàn tất, mục 2 đang chạy, mục 3–4 chờ.
- Vùng thân nền trắng/xám rất nhạt. Vòng tím lớn ở chính giữa; tiến độ indeterminate khi chưa có số phần trăm từ backend, phần trăm chỉ hiện khi job trả số.
- Tiêu đề mặc định “Đang áp dụng mẫu...” và mô tả giải thích việc sắp xếp media, bố cục, chuyển cảnh/hiệu ứng.
- Năm hàng: Phân tích media, Áp dụng bố cục mẫu, Tạo chuyển cảnh và hiệu ứng, Đồng bộ nhạc nền, Hoàn tất...
- Badge tím có dấu kiểm cho COMPLETED; vòng tím chạy cho RUNNING; xám cho PENDING/SKIPPED; đỏ cho FAILED. SKIPPED và FAILED có thông điệp stage.
- Khi thành công, tiêu đề đổi thành “Đã chuẩn bị bản nháp”, vòng hiển thị 100%, và hộp thông tin nêu SCREEN05_PENDING cùng draft ID. Khi lỗi, hiện error code/message và nút thử lại.
- Ring indeterminate chỉ quay khi job ở QUEUED/RUNNING; khi FAILED/CANCELLED ring dừng và chuyển sang accent đỏ nhạt.

## Kích thước và kiểm thử

View dùng cột co giãn, nội dung căn giữa và ScrollViewer dọc. Runtime capture hiện có là 1426 × 893. Yêu cầu mục tiêu 1366 × 768, 1600 × 900, 1920 × 1080 chưa được kiểm tra trực tiếp trong phiên này; không tuyên bố pixel-perfect.

## Ảnh runtime

Xem [SCREEN04_runtime.jpg](../../artifacts/video_creator/task3_5/SCREEN04_runtime.jpg). Ảnh chụp từ bản WPF chạy thật sau processing job thành công và xác minh preview.
