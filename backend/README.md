# Python backend

Backend Python chạy cục bộ cùng ứng dụng C# WPF. FastAPI cung cấp REST/JSON API trên loopback; job manager và storage service phục vụ Image Tools, Video Editor và Media Library.

## Chạy trong môi trường phát triển

1. Cài Python 3.12 và driver GPU NVIDIA mới nếu máy có GPU NVIDIA.
2. Chạy `./backend/setup.ps1` từ thư mục gốc. Script tạo `backend/.venv`, cài PyTorch CUDA 12.6 khi phát hiện NVIDIA hoặc bản CPU trong trường hợp còn lại, rồi cài dependency API/model.
3. Chạy ứng dụng WPF. App tự tìm `.venv`, khởi động backend, chờ health check và đóng backend cùng ứng dụng.
4. Trong Image Tools → Nâng cấp ảnh, chọn ảnh, cấu hình hệ số/model/định dạng rồi nhấn **Bắt đầu nâng cấp**. Model weights tải một lần từ GitHub Releases chính thức vào `%LOCALAPPDATA%\MediaStudio\models\realesrgan`; ảnh tạm và kết quả nằm trong `%LOCALAPPDATA%\MediaStudio\workspace`.

Để chuyển ảnh sang SVG, chọn Image Tools → Ảnh sang vector. VTracer xử lý ảnh màu; Potrace xử lý logo/ảnh đen trắng. `setup.ps1` tải Potrace 1.16 Windows x64 từ trang phát hành Potrace và kiểm tra SHA-1. Potrace được phát hành theo GPL-2.0-or-later; khi phân phối ứng dụng kèm binary này cần giữ thông báo giấy phép và cung cấp mã nguồn tương ứng theo điều khoản GPL.

API chuyển ảnh sang vector dùng Vectorization V2 mặc định: Phase A/B/C/D1/E1 → text reconstruction → production SVG composer. Để rollback khi cần chẩn đoán, đặt biến môi trường `MEDIASTUDIO_VECTORIZE_PIPELINE=legacy` trước khi khởi động WPF; log backend và metadata của từng job ghi rõ pipeline thực tế. `MEDIASTUDIO_VECTORIZE_PIPELINE=v2` chọn rõ V2. Lỗi V2 được trả về cho giao diện, không tự chuyển sang legacy. OCR được cache theo process; thư mục model dùng chung là `%LOCALAPPDATA%\MediaStudio\models\easyocr` khi thư mục này tồn tại. Chế độ chữ `outlined` giữ hình dáng dưới dạng path; `editable` xuất SVG `<text>` và đánh dấu khi font chỉ là gần đúng. Ảnh có cạnh dài trên 800 px được dựng trên work canvas tối đa 800 px để giới hạn bộ nhớ; SVG giữ `width`/`height` theo ảnh nguồn và cảnh báo việc giảm work canvas.

Contour-Preserving là phương pháp thử nghiệm riêng, không được bật mặc định. Sau `setup.ps1`, chạy `./backend/setup-contour-experimental.ps1` để cài wheel Windows của `scikit-image==0.26.0`; sau đó đặt `MEDIASTUDIO_CONTOUR_EXPERIMENTAL=1` trước khi khởi động backend. API có thể nhận `vector_method: "contour_preserving"` hoặc `"smart_reconstruction"`; request cũ không có trường này tiếp tục dùng dispatch hiện tại. Khi chưa cài đúng dependency, request contour báo lỗi có mã rõ ràng và không chuyển ngầm sang V2. Job trả về method/engine metadata, work resolution, warnings, số region/path/gradient, memory RSS tại ranh giới phase và timing theo phase. Giới hạn hiện có: ảnh tối đa 20 MP/12,000 px mỗi cạnh, contour canvas tối đa 800 px, SVG tối đa 100 MB và process RSS tối đa 4 GiB được kiểm tra ở ranh giới phase. JobManager hiện chỉ xử lý một job cùng lúc và chưa có API hủy job. Contour SVG được kiểm tra và render bằng Edge/Chrome trước khi thành công; trường `wpfPreviewValidated` hiện là `false` cho đến khi WPF preview được kiểm tra thủ công.

Backend chỉ bind `127.0.0.1`, dùng cổng động và token phiên ngẫu nhiên; chỉ nhận file người dùng chủ động import. Request xử lý dùng `assetId`, không nhận đường dẫn filesystem tùy ý.

Các model general hỗ trợ mức AI native 2× và 4×. Mức 8× tạo 4× bằng AI rồi dùng Lanczos thêm 2×; giao diện hiển thị rõ để không nhầm resize hậu kỳ với chi tiết AI mới. Nếu thiếu CUDA, backend dùng CPU. Chạy một job AI tại một thời điểm và chia ảnh thành tile để giới hạn bộ nhớ GPU.

Khi đóng WPF, app yêu cầu backend dừng có trật tự; log backend để chẩn đoán nằm tại `%LOCALAPPDATA%\MediaStudio\backend.log`.

## Phát hành

Thiết kế đã hỗ trợ backend PyInstaller đặt cạnh WPF dưới tên `MediaStudio.Backend.exe`; cấu hình installer/self-contained, bundle dependency và license notices vẫn cần hoàn thiện trước khi phân phối.

Thư mục `mediastudio/` chứa routes, job orchestration, storage và các feature module. Tài liệu ranh giới API nằm trong [contracts](../contracts/README.md).

### WPF dual-engine comparison (Task 07)

Smart Reconstruction V2 remains the default vectorization engine. Contour-Preserving is opt-in and appears in the desktop selector only when the backend is started with `MEDIASTUDIO_CONTOUR_EXPERIMENTAL=1` and the pinned `scikit-image==0.26.0` dependency is available. The desktop capability endpoint reports both conditions; changing the environment flag requires restarting the backend. For desktop development with the experimental engine enabled, run `./backend/run-desktop-contour-experimental.ps1` from the repository root. Compare mode imports the source once and submits the two engine jobs sequentially because the backend job manager has one worker. It uses the same source asset, quality mode, and text mode, and saves the SVG response bytes without re-encoding them.
