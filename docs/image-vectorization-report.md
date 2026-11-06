# Báo cáo chức năng chuyển ảnh sang vector

**Ngày lập:** 2026-10-23  
**Phạm vi:** Luồng chuyển ảnh raster thành SVG trong Media Studio desktop, dựa trên mã nguồn và cấu hình hiện có. Báo cáo không phải kết quả chạy benchmark mới.

## 1. Tóm tắt

Chức năng **Ảnh sang vector** biến ảnh raster do người dùng chọn thành tệp **SVG** gồm các hình học vector, màu/gradient và lớp chữ được tái dựng khi nhận diện được. Người dùng có thể xem trước SVG cạnh ảnh nguồn, phóng to để kiểm tra và lưu SVG ra tệp.

Luồng desktop hiện chọn **Smart Reconstruction V2** làm phương pháp mặc định. Đây là pipeline phân tích ảnh, nhận diện/tách chữ, phân vùng hình, dựng đường Bézier, khôi phục appearance và ghép SVG. Không nên hiểu lựa chọn “AI” trong danh sách chất lượng là một mô hình sinh ảnh: V2 chủ yếu dùng xử lý ảnh, thuật toán hình học và OCR; OCR sử dụng EasyOCR.

**Contour-Preserving** là phương pháp thử nghiệm riêng, không bật mặc định. VTracer/Potrace vẫn có trong backend legacy, nhưng UI hiện tại gửi `vector_method` rõ ràng cho Smart Reconstruction hoặc Contour-Preserving; yêu cầu Smart Reconstruction được định tuyến sang V2.

## 2. Tác dụng và đầu ra

### Mục đích

- Tạo artwork dạng vector để phóng to mà không phụ thuộc vào độ phân giải raster như ảnh bitmap.
- Giữ các mảng hình, đường biên, màu và gradient trong SVG.
- Nhận diện chữ trong ảnh để xuất dưới dạng outline path hoặc nội dung text có thể sửa.
- Cho người dùng kiểm tra kết quả trước khi lưu.

### Đầu ra

- Một tệp `.svg` được backend tạo và app lưu nguyên byte SVG; preview trong WPF chỉ là ảnh bitmap dựng từ SVG để hiển thị.
- V2 báo cáo kích thước SVG theo kích thước ảnh nguồn, kể cả khi ảnh lớn đã được thu nhỏ cho các bước xử lý.
- Job trả metadata như số path, gradient, vùng, chế độ chữ, cảnh báo và thời gian từng phase. Các thông tin này được dùng để kiểm tra kết quả và chẩn đoán; UI hiện chủ yếu trình bày trạng thái, số đường và kích thước SVG.

SVG là định dạng vector, nhưng việc chuyển đổi không thể khôi phục hoàn hảo thông tin đã mất trong ảnh raster. Kết quả phụ thuộc vào độ rõ của biên, màu, nền, độ phân giải và khả năng nhận dạng chữ.

## 3. Luồng hoạt động đầu-cuối

```text
Người dùng chọn ảnh trong WPF
    ↓
WPF hiển thị ảnh nguồn và các tùy chọn
    ↓
Upload ảnh tới backend local → nhận assetId
    ↓
POST /api/v1/vectorize/jobs → nhận jobId
    ↓
Worker backend chạy engine được chọn và cập nhật tiến độ
    ↓
WPF poll trạng thái job
    ↓
Khi thành công: GET /api/v1/jobs/{jobId}/result → tải SVG
    ↓
WPF dựng bitmap preview từ SVG → người dùng kiểm tra
    ↓
Người dùng chọn vị trí và lưu byte SVG gốc
```

### 3.1 Chọn và chuẩn bị ảnh

Màn hình có artwork mẫu minh họa cho tới khi người dùng chọn ảnh thật. Khi ảnh được chọn, WPF hiển thị tên, kích thước, preview nguồn và cho phép đổi ảnh. Backend chấp nhận JPEG, PNG, BMP, TIFF và WebP; giới hạn upload 100 MB và 40 megapixel. Ảnh được đọc, áp dụng hướng EXIF và chuẩn hóa thành PNG trước khi pipeline sử dụng.

Backend trả `assetId`; request xử lý dùng ID này chứ không gửi đường dẫn filesystem từ giao diện. Asset và job được lưu trong registry của tiến trình backend, còn dữ liệu ảnh/kết quả là tệp cục bộ. Vì vậy ID/job không phải kho lưu bền vững qua lần backend khởi động lại.

### 3.2 Tùy chọn trong giao diện

| Tùy chọn | Giá trị hiện có | Ý nghĩa |
|---|---|---|
| Engine | Smart Reconstruction V2; Contour-Preserving (Experimental) | Chọn phương pháp dựng SVG. Smart là mặc định; Contour chỉ dùng khi backend và dependency được bật. |
| Chế độ chất lượng | Tự động, Nhanh, Chất lượng, AI | Trong V2 hiện tại, `fast` giới hạn cạnh dài work canvas ở 554 px; `auto`, `quality`, `ai` dùng 800 px. Không có cấu hình pipeline riêng cho ba lựa chọn 800 px trong hàm production hiện tại. |
| Kiểu chữ | Giữ hình dáng (outlined); Chỉnh sửa nội dung (editable) | Chọn chữ được chuyển thành vector outline hay thành SVG `<text>`. |
| Nền preview | Ô caro, trắng, đen | Chỉ đổi nền hiển thị, không thay đổi SVG. |
| Zoom/pan | Thu phóng, vừa khung và di chuyển | Dùng để xem chi tiết; trạng thái zoom/pan được đồng bộ giữa các khung so sánh. |

Giao diện còn có thao tác **Chỉnh vùng giữ / alpha** khi Foreground Protection Lab được backend bật. Nếu người dùng chấp nhận thay đổi alpha, ảnh RGBA đó sẽ là đầu vào cho lần vector hóa tiếp theo; nếu không, dùng ảnh nguồn đã chọn.

### 3.3 Chạy job và theo dõi tiến độ

WPF gửi ảnh lên backend, tạo job và poll trạng thái mỗi 400 ms; thời hạn chờ phía client là 15 phút. Job chạy trên một worker backend, do đó job vector khác phải chờ. Timeout phía client chỉ kết thúc việc chờ ở giao diện, không phải lệnh hủy job trên backend.

Smart Reconstruction được gửi dưới dạng `vector_method="smart_reconstruction"` và được dispatch sang pipeline V2. Nếu V2 thất bại, lỗi được trả ra; không âm thầm fallback sang legacy. Job báo từng giai đoạn xử lý, rồi trả SVG cùng metadata hoặc lỗi/cảnh báo.

## 4. Các bước xử lý trong Smart Reconstruction V2

Thứ tự được thực hiện trong `run_vectorization_v2`:

| Giai đoạn | Công việc | Công nghệ/chủ ý chính |
|---|---|---|
| Tiền xử lý | Đọc ảnh, áp hướng EXIF, chuyển RGBA; giới hạn work canvas theo chế độ | Pillow; Lanczos khi cần thu nhỏ. |
| Phase A — nền và alpha | Ước lượng nền từ biên/góc; phân biệt nền với tiền cảnh; tạo matte alpha và xử lý màu viền | NumPy, OpenCV, Pillow; bảo toàn alpha sẵn có và cảnh báo khi nền không chắc chắn. |
| Phase B — OCR/tách chữ | Tìm vùng chữ, nội dung, đa giác, độ tin cậy; ước lượng màu/coverage chữ và tách chữ khỏi lớp đồ họa | EasyOCR chạy local, NumPy/OpenCV; engine được cache trong process. OCR lỗi được thể hiện bằng trạng thái/cảnh báo, không giả vờ đã tái dựng được chữ. |
| Phase C — phân vùng | Tạo các region và graph kề; tìm biên mạnh/yếu, nhập các ranh giới yếu và phân loại chi tiết/nhiễu/ứng viên gradient | OpenCV, NumPy; đặc trưng Lab, Sobel và marker-controlled watershed. Không tạo SVG ở phase này. |
| Phase D1 — geometry | Khớp biên thành các đoạn Bézier cubic, giữ cấu trúc vùng và ranh giới dùng chung; thử sửa cục bộ geometry lỗi | Thuật toán hình học riêng của dự án: regularized least-squares Bézier, phân tích góc/độ cong và kiểm tra topology/self-intersection. Nếu geometry không hợp lệ, pipeline chặn bước ghép SVG. |
| Phase E1 — appearance | Khớp màu, gradient và một số lớp chi tiết lên geometry đã đóng băng; kiểm tra ánh xạ và độ nhất quán khi render | NumPy/Pillow và SVG/browser rendering; phase này được thiết kế không đổi geometry D1. |
| Tái dựng chữ và ghép SVG | Chuyển mask chữ thành outline Bézier hoặc SVG text; ghép phần graphic và typography, kiểm tra XML/ID/definition | Python `xml.etree.ElementTree`, model geometry và composer nội bộ. Không nhúng raster vào SVG V2. |
| Kiểm định cuối | Render SVG ở kích thước nguồn; yêu cầu ảnh render có đúng kích thước và pixel nhìn thấy; giới hạn file SVG 100 MB | Microsoft Edge hoặc Google Chrome chạy headless, được gọi từ backend; Pillow/NumPy đọc ảnh render. |

### Cách xử lý chữ

- **Outlined:** mask glyph được fit thành các contour/path. Hình dạng gần ảnh nguồn hơn và không cần cùng font ở máy đích, nhưng nội dung không còn sửa như văn bản.
- **Editable:** backend chọn font gần nhất có thể từ danh sách font cài đặt và tạo phần tử SVG `<text>`. Nếu không có font đủ gần, metadata/cảnh báo đánh dấu việc xấp xỉ; cách hiển thị phụ thuộc font có sẵn ở máy mở SVG.
- Nếu OCR không hoạt động, pipeline ghi cảnh báo và có thể không tạo text layer; không thể cam kết giữ đúng nội dung chữ trong trường hợp đó.

### Work canvas và độ phân giải

V2 lưu kích thước nguồn để tạo SVG đúng kích thước, nhưng giới hạn cạnh dài canvas xử lý ở 554 px (Nhanh) hoặc 800 px (các lựa chọn còn lại). Ảnh lớn hơn được thu nhỏ bằng Lanczos trước các phase chính và backend ghi cảnh báo `HIGH_RES_WORKING_DOWNSAMPLED`. Vì vậy, kích thước trang SVG có thể bằng ảnh nguồn nhưng độ phức tạp/chi tiết đường vector bị ảnh hưởng bởi canvas xử lý. Thu nhỏ không tạo thêm chi tiết nguồn.

## 5. Xem trước, lưu và lỗi

Sau khi job thành công, WPF tải SVG, kiểm tra metadata engine/method và asset ID, sau đó dựng preview qua Svg.Skia/SkiaSharp. Preview được giới hạn tối đa 1024 px mỗi chiều để hiển thị trong UI; giới hạn này không làm giảm chất lượng tệp SVG lưu ra.

Khi lưu, app mở hộp thoại Save, thêm đuôi `.svg` nếu cần và ghi byte SVG nhận từ backend. App từ chối lưu đè lên ảnh nguồn. Nếu render preview lỗi nhưng backend đã tạo SVG, UI vẫn giữ kết quả để người dùng có thể lưu, đồng thời báo preview lỗi.

Những lỗi thường gặp được báo rõ, ví dụ ảnh không hợp lệ/quá giới hạn, backend không kết nối, OCR hoặc bước xử lý thất bại, geometry không hợp lệ, SVG rỗng/quá lớn hoặc browser renderer không khả dụng. V2 không được thay thế âm thầm bằng engine khác.

## 6. Công nghệ sử dụng

| Lớp | Công nghệ | Vai trò |
|---|---|---|
| Desktop | C# / WPF, mô hình MVVM | Màn hình, chọn ảnh/lưu tệp, state, lệnh và tiến độ. |
| Preview desktop | Svg.Skia, SkiaSharp | Rasterize SVG thành bitmap preview cho WPF. |
| Giao tiếp | REST/JSON, multipart upload, HTTP loopback | WPF gửi ảnh và job; backend trả trạng thái, metadata, SVG. |
| Backend API | Python, FastAPI, Pydantic | Xác thực request, giới hạn kiểu/dữ liệu, dispatch và định nghĩa API. |
| Quản lý tác vụ | `ThreadPoolExecutor`, một worker | Chạy xử lý ngoài request handler và giữ trạng thái tiến độ trong bộ nhớ. |
| Ảnh raster | Pillow, NumPy, OpenCV | Đọc/chuẩn hóa/resize ảnh, xử lý alpha, segmentation và dữ liệu pixel. |
| OCR | EasyOCR, model cục bộ | Tìm vùng chữ và nội dung chữ; cache engine theo process. |
| Geometry/SVG | Bézier, thuật toán topology và composer Python của dự án; `ElementTree` | Dựng region/path/gradient, xử lý typography và serialize SVG. |
| Kiểm tra SVG phía backend | Microsoft Edge hoặc Google Chrome headless | Render SVG thực tế để xác nhận đầu ra có nội dung và kích thước hợp lệ. |
| Preview phía app | Svg.Skia/SkiaSharp | Render riêng để xem trước; không phải tệp đầu ra người dùng lưu. |

### Phân biệt pipeline V2 với legacy và thử nghiệm

- **Smart Reconstruction V2:** đường chạy mặc định ở UI và là trọng tâm báo cáo này.
- **Legacy:** `VectorizeService` vẫn có nhánh VTracer cho vector hóa màu và Potrace cho trường hợp phù hợp. Cờ `MEDIASTUDIO_VECTORIZE_PIPELINE=legacy` có thể chọn legacy cho request không chỉ định `vector_method`; tuy nhiên yêu cầu Smart Reconstruction từ UI luôn chọn V2.
- **Contour-Preserving:** phương pháp thử nghiệm tách biệt, cần `MEDIASTUDIO_CONTOUR_EXPERIMENTAL=1` và `scikit-image==0.26.0`. Nếu chưa sẵn sàng, API trả lỗi rõ ràng và không fallback. Kết quả có kiểm tra browser nhưng metadata vẫn ghi `wpfPreviewValidated=false` cho tới khi được kiểm tra preview WPF thủ công.

Do đó, không nên mô tả V2 là “chạy VTracer/Potrace”: hai công cụ này thuộc khả năng legacy, không phải các phase production V2 nêu trên.

## 7. Giới hạn và lưu ý sử dụng

1. Tách nền là heuristic dựa trên ảnh và bằng chứng ở biên; nền phức tạp, nền không đồng nhất hoặc chủ thể cùng màu với nền có thể gây mất/thừa vùng. Alpha đầu vào được ưu tiên khi có.
2. OCR có thể bỏ sót chữ, đọc sai ký tự hoặc ước lượng font không chính xác. Nên rà soát SVG, đặc biệt với logo, chữ nhỏ và chữ có trang trí.
3. Work canvas 554/800 px giới hạn mức chi tiết xử lý; tệp SVG có kích thước trang theo nguồn không đồng nghĩa giữ được mọi chi tiết của ảnh gốc.
4. Raster nhiều sắc thái/chụp ảnh có thể trở thành nhiều vùng/path/gradient và cho SVG phức tạp; ảnh logo/illustration có biên rõ thường phù hợp hơn.
5. Backend xử lý tuần tự một job; thời gian phụ thuộc kích thước, độ phức tạp, OCR/model sẵn có và khả năng render browser.
6. Job/asset registry hiện ở bộ nhớ process; nếu backend dừng giữa chừng, app có thể phải nhập và chạy lại ảnh.
7. Chế độ Contour là experimental và chưa mặc định; kết quả cần đánh giá thủ công. UI Compare chạy tuần tự Smart rồi Contour trên cùng asset và cấu hình.
8. Kết quả SVG cần mở/kiểm tra trong công cụ đích nếu dùng cho in ấn hoặc sản xuất; backend render-pass không thay thế kiểm tra chất lượng/giấy phép/độ chính xác thiết kế.

## 8. Kiểm thử liên quan trong repository

Các bài test hiện có bao phủ những phần của chức năng, gồm:

- `backend/tests/test_vectorization_v2_product.py`: outline/editable text, cảnh báo OCR, ghép SVG, cảnh báo/validation và dispatch API V2.
- `backend/tests/test_vectorization_v2_phase_a.py` cùng các test phase B/C/D1/E1: các bước xử lý nền/alpha, OCR, phân vùng, hình học và appearance.
- `backend/tests/test_vectorization_v2_detail_fidelity.py`: kiểm tra độ trung thực một số chi tiết của pipeline.
- `backend/tests/test_vectorization.py`: nhánh vector hóa legacy.
- `src/MediaStudio.Desktop.Tests/SourceCoordinateAndViewModelTests.cs`: một số kiểm tra ViewModel/tọa độ liên quan đến Image Tools; test project cũng có các kiểm tra chức năng giao diện khác.

Danh sách này mô tả test có trong repository, không khẳng định đã chạy lại chúng khi lập báo cáo.

## 9. Vị trí mã nguồn chính

- Giao diện: `src/MediaStudio.Desktop/Views/VectorizeToolView.xaml`
- Điều khiển luồng desktop: `src/MediaStudio.Desktop/ViewModels/VectorizeToolViewModel.cs`
- Import/job/poll/result client: `src/MediaStudio.Desktop/Services/VectorizationJobService.cs`, `src/MediaStudio.Desktop/Services/MediaStudioApiClient.cs`
- API và dispatch: `backend/mediastudio/api.py`, `backend/mediastudio/image_tools/vectorize.py`
- Pipeline V2: `backend/mediastudio/image_tools/vectorization_v2/production.py`
- Chuẩn hóa/nền: `backend/mediastudio/image_tools/vectorization_v2/pipeline.py`, `background.py`
- OCR/tách chữ: `backend/mediastudio/image_tools/vectorization_v2/phase_b.py`, `text_reconstruction.py`
- Phân vùng: `backend/mediastudio/image_tools/vectorization_v2/phase_c.py`
- Dựng geometry: `backend/mediastudio/image_tools/vectorization_v2/phase_d1.py`
- Appearance/render validation: `backend/mediastudio/image_tools/vectorization_v2/phase_e1.py`
- Ghép SVG: `backend/mediastudio/image_tools/vectorization_v2/svg_composer.py`

