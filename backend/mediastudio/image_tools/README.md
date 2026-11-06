# Image Tools backend

Python module cho ba workflow `image_upscale`, `image_to_vector` và `die_cut_line`. FastAPI routes kiểm tra request và tạo job; pipeline thuật toán nằm trong service riêng để không khóa request/API.

Pillow chuẩn hóa ảnh đầu vào. Upscale dùng PyTorch/Real-ESRGAN: model x2/x4 cho kết quả AI tương ứng; tùy chọn 8× là x4 AI cộng resize Lanczos 2×. Worker ưu tiên CUDA trên GPU NVIDIA tương thích, có CPU fallback và tiled inference cho ảnh lớn.

Vector hóa phân tích loại ảnh, độ phức tạp màu, vùng nền, màu chuyển sắc và vùng giống chữ. Chế độ `auto` chọn tham số theo ảnh; logo nhỏ được phóng 2× bằng bicubic để đường viền có thêm điểm lấy mẫu, không phải AI tạo chi tiết mới. Nền phẳng nối với viền ảnh được tách bằng OpenCV. Ở chế độ `auto`, chữ được giữ như artwork để trace thành path, tránh chờ tải EasyOCR và tránh thay kiểu chữ logo bằng font hệ thống. OCR chỉ chạy khi API yêu cầu rõ `quality` hoặc `ai`; khi đó model chạy local trên CPU và có thể được tải lần đầu.

Pillow lượng tử màu, VTracer tạo các lớp path, Potrace được dùng cho line-art đơn sắc, còn `SvgComposer` gom path vào `graphic`, thêm nhóm `typography` khi OCR được yêu cầu, và lấy màu gradient theo vị trí ngang trong ảnh nguồn. Palette tự động cho ảnh có gradient được giới hạn ở mức vừa đủ để giảm path nhiễu; gradient SVG đảm nhiệm chuyển sắc liên tục. SVG được kiểm tra và giữ viewBox đã crop. `DEBUG_VECTOR=true` lưu các trung gian theo từng job trong `results/vector-debug/` (ảnh gốc, nền đã tách, upscale, mask chữ, phân vùng màu, ảnh lượng tử, SVG thô và SVG cuối).

Đường bế ưu tiên kênh alpha; ảnh nền liền màu dùng OpenCV để nhận diện vùng nền nối với mép ảnh, ảnh phức tạp dùng GrabCut và các nét Giữ/Bỏ từ giao diện để hiệu chỉnh mask. Contour ngoài được làm sạch/giản lược bằng OpenCV, bù mm theo chiều rộng in bằng Pyclipper và xuất thành SVG có lớp `CutContour`. Xem [ADR 0001](../../../docs/architecture/decisions/0001-image-tools-technology.md) trước khi thêm dependency.
