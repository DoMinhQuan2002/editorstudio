# Screen 06 — UI spec

## Mục đích

Màn cuối nhận bản nháp đã lưu và xem xét ở Screen 5, cho người dùng kiểm tra preview, đặt cấu hình mà engine hỗ trợ, xuất MP4 và truy cập file kết quả.

## Bố cục và trạng thái

- Dùng shell/sidebar Media Studio hiện tại; không thay route hay workflow Image Tools.
- Thanh bước thể hiện Chọn media → Xử lý → Chỉnh sửa → Xuất, bước Xuất màu tím.
- Nút “Quay lại chỉnh sửa” chỉ ẩn export host. Draft preview view model còn trong Gallery nên quay lại không tạo project/revision mới.
- Hai cột: preview dọc ở trái; settings và panel export ở phải.
- Preview là file Composition Graph được Screen 5 tạo cho cùng Project ID và revision; có play/pause, seek, thời gian, mute và fullscreen.
- Không có timeline nhiều track hoặc công cụ chỉnh sửa thủ công.
- Settings chỉ hiển thị độ phân giải/fps/container/codec lấy từ capability API. Quality là danh sách Standard/High do API trả về.
- Khi chạy, panel hiển thị stage/progress backend và nút hủy nếu khả dụng. Thành công yêu cầu file backend xác nhận có thật, kích thước trùng và full decode passed.
- Success panel có file name/path, duration, resolution, size, Mở video, Mở thư mục và Quay lại dự án.
- Khi lỗi, giữ nguyên draft/media, hiện lỗi, cho retry phù hợp. Mất kết nối trước hết truy vấn lại cùng Job ID.

## So với reference và giới hạn layout

UI WPF giữ tông sáng, accent tím, hai cột và CTA phía dưới như mockup. Vì renderer hiện chỉ xuất cấu hình gốc, UI không vẽ các lựa chọn 720p, 60 fps hoặc MOV chỉ để khớp ảnh. Screenshot runtime tại `artifacts/video_creator/task3_7/SCREEN06_runtime_success.jpg` là 1427×744; panel bên phải cuộn khi viewport thấp. Chưa nghiệm thu các độ phân giải cửa sổ còn lại trong brief.
