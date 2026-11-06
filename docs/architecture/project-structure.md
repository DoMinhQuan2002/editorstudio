# Cấu trúc dự án

> Cập nhật 2026-10-22: tài liệu từng là kế hoạch kiến trúc. Phần stack và cây thư mục đề xuất ban đầu được giữ làm lịch sử; cấu trúc hiện đã xác minh được ghi riêng dưới đây.

## Cấu trúc đã xác minh

- MediaStudio.sln có hai project: src/MediaStudio.Desktop và src/MediaStudio.Desktop.Tests.
- Desktop có App.xaml/App.xaml.cs, MainWindow.xaml/code-behind, Views, ViewModels, Services và Infrastructure.
- Workspace video hiện trỏ tới VideoCreatorGalleryView và VideoCreatorGalleryViewModel; manual NLE view/viewmodel đã retire.
- backend/mediastudio chứa api.py, desktop_main.py, image_tools, video_editor, jobs, storage và media_library.
- backend/native/video_engine chứa native C++ engine.
- MediaStudio.Application và package scaffolding không phải project đang build nếu chưa đăng ký vào solution.
- WPF MVVM hiện dùng ObservableObject/RelayCommand riêng. Backend khởi động cục bộ qua FastAPI và token loopback.

## Định hướng

Sản phẩm là **ứng dụng desktop Windows**. Giao diện viết bằng C# + WPF; backend Python chạy cục bộ cùng máy và được WPF khởi động/dừng theo vòng đời ứng dụng. Đây không phải website; người dùng mở app desktop, không cần trình duyệt, tài khoản hoặc máy chủ từ xa.

WPF gọi backend qua REST API chỉ bind vào `127.0.0.1` trên cổng động. App truyền token phiên ngẫu nhiên để chỉ tiến trình desktop hiện tại gọi được API. Backend quản lý xử lý, storage và các job dài; WPF lo giao diện, file picker và trình bày kết quả.

## Stack MVP ban đầu (lịch sử)

- Desktop UI: C# + WPF trên .NET 10 LTS, theo MVVM với `CommunityToolkit.Mvvm`.
- Backend cục bộ: Python + FastAPI + Pydantic, đóng gói cùng app bằng PyInstaller.
- Job dài: local job manager và một worker hàng đợi; không cần Celery/Redis cho bản đơn máy.
- Image Tools: Pillow, PyTorch/Real-ESRGAN, VTracer, OpenCV và Pyclipper sau các adapter riêng.
- Giao tiếp: REST/JSON trên loopback; WPF nhận `jobId`, rồi truy vấn tiến độ/kết quả.

Lựa chọn, rủi ro và giới hạn được ghi ở [ADR 0001](decisions/0001-image-tools-technology.md).

## Cây thư mục đề xuất ban đầu (lịch sử)

```text
MediaStudio.sln
src/
  MediaStudio.Desktop/                 # C# WPF app, net10.0-windows
    App.xaml
    Views/
    ViewModels/
    Features/
      ImageTools/
        ImageUpscale/
        ImageToVector/
        DieCutLine/
      VideoCreatorGalleryView.xaml     # Catalog template; không có manual timeline UI
      MediaLibrary/
    Backend/                           # Process launcher, health check, typed HttpClient
  MediaStudio.Application/             # Use cases, app-level job and media workflows
backend/
  mediastudio/
    api/                               # FastAPI routes, Pydantic schemas
    jobs/                              # Queue, job status/progress, cancellation
    storage/                           # Local files, SQLite metadata
    image_tools/
      image_upscale/
      image_to_vector/
      die_cut_line/
    video_editor/
    media_library/
  pyproject.toml
contracts/
  README.md                            # OpenAPI contract and DTO policy
engines/
  models/                              # Model weights and their license notices
docs/
  architecture/
  product/
```

`MediaStudio.sln` và project WPF khởi đầu đã được tạo trong `src/MediaStudio.Desktop`. Ba màn hình Image Tools hiện có giao diện và viewmodel nền tảng; Python backend và pipeline xử lý chưa được triển khai.

## Luồng khởi động và tác vụ

```text
Người dùng mở app WPF
        ↓
WPF khởi động Python backend cục bộ và chờ health check
        ↓
WPF gửi request REST / tải file đã chọn / tạo job
        ↓
Backend lưu input, chạy pipeline trong worker và cập nhật job
        ↓
WPF poll tiến độ, hiển thị preview và cho lưu kết quả
```

Backend chỉ bind loopback, cổng được cấp động, xác thực request bằng token ngẫu nhiên do WPF tạo. Không mở cổng trong LAN và không nạp nội dung từ website. WPF stream file người dùng chọn tới backend; backend quản lý đường dẫn bên trong app data thay vì nhận đường dẫn tùy ý.

Job có trạng thái `queued`, `processing`, `succeeded`, `failed`, `cancelled`, phần trăm tiến độ và thông tin lỗi an toàn để hiển thị. Backend chạy pipeline nặng ngoài request handler để giao diện/API vẫn phản hồi. MVP giới hạn số worker để tránh nhiều model cùng chiếm bộ nhớ/GPU.

## Lưu trữ

- Backend giữ source, temporary, preview và output trong thư mục dữ liệu ứng dụng hoặc project workspace do người dùng chọn.
- Metadata project/job đặt trong SQLite; file media nằm riêng trên filesystem.
- WPF mở hộp thoại hệ điều hành và gửi nội dung file theo luồng tới API import.
- Module xử lý dùng storage service chung thay vì tự ghép đường dẫn.

## Ranh giới module

WPF viewmodel chỉ phụ trách state giao diện và gọi typed backend client. Python route xác thực request và điều phối use case; thuật toán nằm trong pipeline theo từng tool. Model/library cụ thể được bọc sau adapter để thay được mà không đổi API hoặc workflow người dùng.
