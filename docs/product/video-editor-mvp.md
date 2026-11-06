# Video Editor — lịch sử phạm vi Backend MVP

> **RETIRED_PRODUCT_REQUIREMENT:** tài liệu này mô tả workflow editor thủ công trước TASK 3.0A. Timeline UI, các thao tác edit và route mở project vào NLE đã được nghỉ. Giữ lại như lịch sử kỹ thuật/API; không dùng như cam kết sản phẩm hiện hành.

Project V2, API và backend renderer được giữ làm runtime nội bộ cho Video Creator template-first. Trạng thái hiện tại được ghi trong [TASK 3.0A report](../../VIDEO_EDITOR_TASK3_0A_REPORT.md).

## Chức năng lịch sử đã nối

- Danh mục mẫu, tìm kiếm/lọc mẫu và lưu/mở dự án qua API cục bộ.
- Nhập nhiều ảnh, video, audio; lưu tệp nguồn cục bộ, metadata và thumbnail.
- Gán ảnh/video vào từng cảnh; sửa source in-point, thời lượng, fit, hiệu ứng màu, opacity, transition và âm lượng nguồn video.
- Sửa tên/tỷ lệ khung hình dự án; sắp xếp, xóa và chia cảnh; undo/redo các lần lưu dự án.
- Thêm lớp chữ theo thời gian, vị trí chuẩn hóa, màu, cỡ chữ và opacity; preview hiển thị chữ đang hoạt động theo playhead.
- Thêm track audio, chỉnh vị trí, in-point, thời lượng, âm lượng và fade in/out.
- Preview media của cảnh đang chọn, phát/tạm dừng video, seek, mở toàn màn hình.
- Xuất MP4 bất đồng bộ bằng FFmpeg H.264/AAC với mức draft/standard/high, tiến độ, hủy và lưu file qua hộp thoại Windows.

## Phần tiếp theo của từng chức năng

- Preview hiện đang tập trung vào một cảnh; chưa phát toàn bộ timeline và chưa hòa tiếng trong preview.
- Hiệu ứng màu, transition, cắt ghép và âm thanh được áp dụng ở bước render backend; preview chưa mô phỏng đầy đủ các hiệu ứng đó.
- Thẻ mẫu hiện dùng artwork màu đại diện do dự án chưa có bộ thumbnail media được duyệt.
- Timeline chưa có waveform audio, kéo thả clip/layer, keyframe hay cắt clip bằng playhead; các giá trị cắt có thể sửa trong inspector.
- Template chưa chứa stock footage hoặc nhạc có bản quyền; người dùng cần thay media placeholder trước khi render.

## API

Backend API và giới hạn upload được mô tả trong [README của video editor](../../backend/mediastudio/video_editor/README.md).
