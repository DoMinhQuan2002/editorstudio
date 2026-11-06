# ADR 0001: WPF desktop app và Python Image Tools backend

- **Trạng thái:** Chọn hướng cho MVP; chưa cài dependency hoặc khóa phiên bản.
- **Phạm vi:** Desktop Windows, Python backend cục bộ và ba tool: nâng cấp ảnh, vector hóa, tạo đường line bế.

## Bối cảnh

Sản phẩm là app desktop, không phải website. Giao diện và thao tác hệ điều hành dùng C# + WPF; Python backend chạy trên cùng máy để tận dụng hệ sinh thái xử lý ảnh/AI. Backend không triển khai trên máy chủ từ xa và không cần mạng để xử lý file.

## Quyết định

| Lớp | Công nghệ | Trách nhiệm |
|---|---|---|
| Desktop app | C# + WPF, `.NET 10` (`net10.0-windows`) | Cửa sổ, file picker, preview, điều khiển workflow |
| Presentation pattern | MVVM + `CommunityToolkit.Mvvm` | Binding, command bất đồng bộ, state và progress UI |
| Backend local | Python + FastAPI + Pydantic | API nghiệp vụ, kiểm tra request, storage, điều phối job |
| Backend lifecycle | WPF khởi động Python backend đã đóng gói | Health check, quản lý process, shutdown cùng app |
| Giao tiếp | REST/JSON qua loopback `127.0.0.1` | WPF gửi lệnh/import file và đọc trạng thái job |
| Job dài | Local queue + worker giới hạn concurrency | Xử lý nặng ngoài request handler; không thêm Celery/Redis cho MVP đơn máy |
| Decode/chuẩn hóa ảnh | Pillow | Đọc ảnh và chuẩn bị đầu vào |
| Nâng cấp ảnh | PyTorch + Real-ESRGAN qua `Upscaler` adapter | Khôi phục/nâng độ phân giải; tiled inference khi cần |
| Raster sang vector màu | VTracer Python binding (`vtracer==0.6.15`) | Giảm bảng màu và dựng đường SVG |
| Raster sang vector đơn sắc | Potrace 1.16 CLI, chọn engine thủ công hoặc qua auto-detect | Logo/ảnh đen trắng thành đường Bézier SVG |
| Mask/đường bao | OpenCV | Tạo mask, tìm contour ngoài, giản lược path |
| Bù đường line bế | Pyclipper | Offset contour theo khoảng cách in đã chọn |
| SVG sang PDF | CairoSVG, tùy chọn export | Tạo PDF từ SVG nếu workflow in yêu cầu |
| Local storage | Filesystem + SQLite metadata | Lưu nguồn, file tạm, preview, kết quả, project/job metadata |
| Đóng gói backend | PyInstaller | Bundle Python runtime và dependency cùng desktop installer |

WPF gọi Python API qua localhost nhưng sản phẩm vẫn là ứng dụng Windows cài trên máy: không có frontend website, không cần browser và không mở API ra mạng LAN.

## Giao tiếp và bảo vệ backend

1. WPF khởi động backend trên `127.0.0.1` với cổng động và token phiên ngẫu nhiên.
2. Backend báo sẵn sàng sau health check; WPF giữ `HttpClient` tới địa chỉ cục bộ đó.
3. WPF dùng file picker của Windows, sau đó stream file đã chọn tới endpoint import. Backend không nhận đường dẫn tùy ý từ giao diện.
4. WPF tạo job qua REST; backend trả `jobId`. WPF poll tiến độ/kết quả theo khoảng thời gian ngắn.
5. Khi đóng app, WPF yêu cầu backend dừng có trật tự; nếu cần, cưỡng dừng sau timeout.

Backend chỉ bind loopback, kiểm tra token, giới hạn kích thước/loại file và xác thực request. Tắt CORS vì client WPF dùng `HttpClient`, không phải trình duyệt; không mở port LAN và không nạp code từ URL. Worker giữ số tác vụ AI đồng thời thấp để tránh quá tải RAM/VRAM.

## Xử lý job

API không chạy trực tiếp pipeline nặng trong request handler. Job manager thêm yêu cầu vào local queue; worker chạy xử lý và cập nhật trạng thái `queued`, `processing`, `succeeded`, `failed`, `cancelled` cùng progress. Worker duy trì model đã nạp khi phù hợp để giảm thời gian chờ. MVP chỉ cần một worker AI mặc định; concurrency/config GPU sẽ được đo trên máy Windows mục tiêu.

Không dùng Celery/Redis ở bản đầu vì backend phục vụ một ứng dụng và một máy. Nếu sau này có xử lý phân tán hoặc nhiều người dùng, có thể thêm remote backend sau lớp service/job contract hiện tại.

## Quyết định theo từng công cụ

### 1. Nâng cấp ảnh

Dùng `RealESRGAN_x4plus` làm model mặc định cho ảnh thường qua Python/PyTorch `Upscaler` adapter. Dùng model x2 tổng quát của upstream (`RealESRGAN_x2plus`) cho mức 2×; mức 4× dùng model x4. Cho ảnh minh họa có lựa chọn riêng `RealESRGAN_x4plus_anime_6B`; không tự động áp model anime cho ảnh chụp. Khi chọn anime 2×, chạy model 4× rồi thu nhỏ bằng Lanczos.

Backend chọn thiết bị lúc khởi động: CUDA khi PyTorch phát hiện GPU NVIDIA tương thích, nếu không thì xử lý bằng CPU. MVP không hứa tăng tốc GPU cho Intel/AMD. Dùng tiled inference có báo tiến độ thật theo từng tile; giảm tile size nếu CUDA hết bộ nhớ. Chỉ một worker AI chạy tại một thời điểm và giữ model trong bộ nhớ giữa các job nếu còn đủ tài nguyên. Pillow phụ trách đọc ảnh, chuẩn hóa hướng EXIF và lưu kết quả; pipeline model nằm ngoài request handler trong job worker.

Mức 8× trong UI là **4× AI + resize Lanczos 2×**, hiển thị rõ cả hệ số AI lẫn kích thước đầu ra. Không chạy model liên tiếp để gọi đó là 8× AI ở MVP vì tốn tài nguyên và dễ khuếch đại artefact. Model zoo có model tổng quát x2/x4; `outscale` của upstream Python có thể resize đầu ra sau inference. Upstream Python inference cũng có tiled inference và xử lý alpha, grayscale, ảnh 16-bit.

PyTorch/Real-ESRGAN cho phép dùng cùng pipeline trên GPU NVIDIA và CPU fallback, nhưng làm tăng dung lượng gói và độ phức tạp đóng gói. Giai đoạn MVP chấp nhận giới hạn GPU NVIDIA; có thể đánh giá NCNN/Vulkan sau nếu cần tăng tốc trên GPU Intel/AMD. Kiểm tra license riêng của mã nguồn, trọng số model và dependency trước khi phát hành.

### 2. Chuyển ảnh sang vector

Dùng VTracer cho ảnh màu và Potrace cho đầu vào đơn sắc. VTracer có pipeline xử lý ảnh màu; Potrace nhận bitmap đen trắng và xuất các đường vector SVG. UI cho phép chọn engine, số màu, mức giản lược, làm mượt và loại nền trắng; auto-detect chỉ chọn Potrace khi ảnh trông đơn sắc và engine có sẵn. SVG là định dạng xuất đầu tiên. Potrace được phát hành theo GPL-2.0-or-later; rà soát nghĩa vụ giấy phép trước khi phân phối ứng dụng kèm engine này.

### 3. Tạo đường line bế

OpenCV tạo mask/contour; ưu tiên alpha channel hoặc mask đã có trước khi thử ngưỡng màu. Dùng contour ngoài và đơn giản hóa path, sau đó Pyclipper offset theo khoảng cách đã đổi từ pixel sang đơn vị in. Preview cho phép chỉnh mask và khoảng bù. Ảnh nền phức tạp có thể cần segmentation hoặc thao tác tay; không đảm bảo contour tự động luôn chọn đúng chủ thể.

## Lưu trữ và phát hành

- File nguồn/đầu ra nằm trong app data hoặc workspace do người dùng chọn; metadata lưu SQLite.
- PyInstaller đóng backend Python cùng dependency. Cần thử gói trên Windows sạch, bao gồm PyTorch/native libraries, model weights, quyền ghi thư mục và shutdown process.
- WPF có thể phát hành self-contained để người dùng không phải cài riêng .NET; kiểu installer/ký ứng dụng sẽ chốt trước bản phân phối.
- WPF chỉ hỗ trợ Windows; yêu cầu macOS/Linux sẽ cần chọn UI framework khác.
- CairoSVG dùng LGPLv3; rà soát nghĩa vụ license nếu phân phối. Cũng rà soát licenses của mọi package và model weights.

## Lý do chọn

- WPF cung cấp app desktop Windows thực thụ với file picker và windowing native.
- MVVM giữ XAML/view state tách khỏi API client và workflow.
- Python backend gom thuật toán ảnh/AI, storage và job queue vào process riêng để model crash hoặc tác vụ nặng không làm treo cửa sổ.
- REST qua loopback giúp ranh giới C#/Python rõ, dễ chẩn đoán và giữ backend độc lập với WPF; local-only binding và token giới hạn truy cập.
- Tool adapters cho phép đổi model/library mà không viết lại luồng người dùng.

## Chưa quyết định

- Bản Python/PyTorch cụ thể, CUDA/cuDNN, precision và cách phân phối model weights.
- Đánh giá kết quả vector trên bộ ảnh logo, chữ, minh họa và ảnh chụp.
- Profile OpenCV và giới hạn kích thước input theo máy mục tiêu.
- Định dạng project và lựa chọn thư mục lưu mặc định.
- Tạo PDF trực tiếp trong MVP hay chỉ xuất SVG trước.
- Installer, ký ứng dụng và cập nhật tự động.

## Nguồn kỹ thuật

- [Microsoft: tạo WPF app trên .NET 10](https://learn.microsoft.com/en-us/dotnet/desktop/wpf/get-started/create-app-visual-studio) · [.NET support policy](https://dotnet.microsoft.com/en-us/platform/support/policy)
- [Microsoft: CommunityToolkit.Mvvm](https://learn.microsoft.com/en-us/dotnet/communitytoolkit/mvvm/)
- [FastAPI: Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/) · [PyInstaller documentation](https://pyinstaller.org/en/stable/)
- [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) · [model zoo](https://github.com/xinntao/Real-ESRGAN/blob/master/docs/model_zoo.md) · [license](https://github.com/xinntao/Real-ESRGAN/blob/master/LICENSE)
- [VTracer repository and Python bindings](https://github.com/visioncortex/vtracer) · [releases](https://github.com/visioncortex/vtracer/releases)
- [OpenCV contour functions](https://docs.opencv.org/4.x/d3/dc0/group__imgproc__shape.html)
- [Pyclipper](https://github.com/fonttools/pyclipper)
- [CairoSVG documentation and LGPLv3 notice](https://cairosvg.org/documentation/)
