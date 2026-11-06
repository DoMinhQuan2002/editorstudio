# Video Editor backend

Module xử lý dự án video, nhập media và kết xuất MP4 cục bộ. Module được tích hợp vào local API và tách khỏi các pipeline xử lý ảnh.

## API

- `GET /api/v1/video/capabilities` báo trạng thái FFmpeg và định dạng media hỗ trợ.
- `GET /api/v1/video/templates` trả danh mục mẫu khởi đầu.
- `POST /api/v1/video/media` nhập một ảnh, video hoặc âm thanh qua multipart field `file`.
- `GET /api/v1/video/media` liệt kê media đã nhập.
- `GET /api/v1/video/media/{assetId}` trả metadata media.
- `GET /api/v1/video/media/{assetId}/content` trả tệp gốc để preview/tải.
- `GET /api/v1/video/media/{assetId}/thumbnail` trả thumbnail nếu có.
- `GET/POST /api/v1/video/projects` liệt kê dự án hoặc tạo dự án từ mẫu.
- `GET/PUT /api/v1/video/projects/{projectId}` mở hoặc lưu dự án JSON.
- `POST /api/v1/video/projects/{projectId}/render-jobs` bắt đầu kết xuất MP4.
- `GET/DELETE /api/v1/video/jobs/{jobId}` đọc trạng thái hoặc hủy job.
- `GET /api/v1/video/jobs/{jobId}/result` tải MP4 đã hoàn tất.

Dự án và media lưu dưới thư mục dữ liệu backend trong `video_editor/`. Render chạy bằng một worker cục bộ. Nhập video/âm thanh và xuất MP4 cần `ffmpeg` cùng `ffprobe` trong `PATH`; endpoint capabilities báo tình trạng cài đặt. Dự án có âm thanh được gửi qua native engine C++ để dựng filter graph trộn, cắt, chỉnh âm lượng, delay và fade; FFmpeg thực thi các bộ lọc native và mã hóa AAC. Python tiếp tục điều phối job và lưu dữ liệu. Dự án không có âm thanh có thể tiếp tục dùng renderer Python.

Clip tạo từ mẫu ban đầu là placeholder chưa gán media. Client cần gắn media ID hợp lệ cho mỗi cảnh trước khi xuất. API render hỗ trợ cắt cảnh, chuyển cảnh fade, fit/fill khung hình, hiệu ứng warm/mono/vivid, lớp chữ, audio gốc của video có chỉnh âm lượng, track âm thanh bổ sung với vị trí/in-point/volume/fade và các preset chất lượng draft/standard/high.
