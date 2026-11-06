# Media Studio

Ứng dụng **desktop Windows** gồm Image Tools và một workspace Video Creator theo mẫu. Giao diện viết bằng C# + WPF; Python backend chạy cục bộ cùng máy để xử lý media. Không phải website và không cần trình duyệt hay máy chủ từ xa.

## Nhóm chức năng

1. **Image Tools** — ba công cụ tham khảo BENDESIGN:
   - Nâng cấp ảnh.
   - Chuyển ảnh sang vector.
   - Tạo đường line bế.
2. **Video Creator** — chọn template, gán media theo từng vị trí, xử lý, xem trước và xuất video. Không còn giao diện chỉnh sửa timeline NLE thủ công.
3. **Media Library** — quản lý ảnh, video, âm thanh và tệp đầu ra dùng chung.
4. **Fashion Studio** — chỉnh sửa ảnh bằng Qwen-Image-Edit: thử trang phục, đổi bối cảnh và chỉnh màu trang phục.

## Tài liệu

- [Cấu trúc dự án](docs/architecture/project-structure.md)
- [Bản đồ chức năng](docs/product/feature-map.md)
- [Chức năng và model AI](docs/MODELS_AND_FEATURES.md)
- [Video Creator — kiến trúc và trạng thái](docs/video_creator/VIDEO_CREATOR_ARCHITECTURE_BASELINE.md)
- [Báo cáo retire NLE Task 3.0A](VIDEO_EDITOR_TASK3_0A_REPORT.md)
- [Quyết định công nghệ Image Tools](docs/architecture/decisions/0001-image-tools-technology.md)

## Chạy giao diện desktop

Yêu cầu Windows, .NET 10 SDK và Python 3.12. Trước lần chạy đầu, cài Python backend:

```powershell
./backend/setup.ps1
```

Sau đó chạy app từ thư mục gốc repository:

```powershell
dotnet run --project src/MediaStudio.Desktop/MediaStudio.Desktop.csproj
```

Chức năng nâng cấp ảnh đã nối với Python backend: chọn ảnh, chọn mức 2×/4×/8× và model ảnh thường/anime, theo dõi tiến độ, so sánh trước/sau, rồi lưu PNG/JPG/TIFF. Model weights tải một lần từ GitHub Releases chính thức khi cần và được lưu trong `%LOCALAPPDATA%\MediaStudio\models\realesrgan`. Chức năng ảnh sang vector nối với VTracer/Potrace, xem trước và lưu SVG. Chức năng đường bế tạo contour ngoài từ alpha/nền ảnh, cho phép tô mask Giữ/Bỏ, quy đổi khoảng bù theo kích thước in, xem trước và lưu SVG.
