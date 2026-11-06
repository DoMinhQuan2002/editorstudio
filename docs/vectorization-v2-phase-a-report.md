# Vectorization V2 — Phase A: Background + Foreground

Ngày thực hiện: 2026-10-07. Phạm vi kết thúc tại foreground raster. Kết quả sẵn sàng để người dùng duyệt ảnh; không coi đây là V2 SVG hoàn chỉnh hoặc tự chuyển sang Phase B.

## 1. Files created

Code mới, tối thiểu cho vertical slice:

- `backend/mediastudio/image_tools/vectorization_v2/__init__.py`
- `backend/mediastudio/image_tools/vectorization_v2/models.py`
- `backend/mediastudio/image_tools/vectorization_v2/pipeline.py`
- `backend/mediastudio/image_tools/vectorization_v2/background.py`
- `backend/mediastudio/image_tools/vectorization_v2/debug.py`
- `tools/capture_vector_legacy_baseline.py`
- `tools/run_vector_phase_a.py`
- `backend/tests/test_vectorization_v2_phase_a.py`
- `backend/tests/fixtures/active_fox_phase_a_annotations.json`
- Báo cáo này.

Dữ liệu baseline và artifact được tạo ở các thư mục trong mục 3 và 8. Artifact runtime nằm trong quy tắc ignore `artifacts/` sẵn có; baseline và fixture không thuộc quy tắc đó.

## 2. Files changed

Không sửa file source tồn tại trước task. `vectorize.py`, composer, OCR, VTracer parameters, API, WPF, requirements, upscale và die-cut giữ nguyên. Bản chụp legacy gồm source Python backend và cấu hình dependency đã được nén; SHA-256 của từng file được lưu và kiểm tra trong test.

V2 được gọi trực tiếp bằng CLI, chưa nối vào endpoint và chưa có dispatcher thay default.

## 3. Legacy baseline metrics

Baseline được chạy lại từ fixture thật với request giống WPF: auto engine, auto mode, màu/simplification tự động, smooth paths và transparent background bật.

| Metric đọc từ output | Kết quả |
|---|---:|
| Path | 86 |
| Linear + radial gradient definitions | 61 |
| Text elements | 2 |
| SVG size | 184751 byte |
| Render | 554 × 554 |

Các con số được đếm bằng XML parser, kích thước file và Pillow; không lấy số gradient 0/1 do composer legacy báo.

Đường dẫn: `backend/tests/baselines/vectorization/`

- `active_fox_legacy.svg`
- `active_fox_legacy_render.png`
- `active_fox_legacy_metrics.json` — gồm package versions, request, source/output/fixture hashes và metrics cũ để đối chiếu.
- `legacy_foreground.png` — gọi helper nền hiện có, không sửa legacy.
- `legacy_source_snapshot.zip`
- `legacy_tests_before.txt`

Script capture từ chối ghi đè khi baseline đã tồn tại. Fixture trùng SHA-256 với `Downloads/images.jpg`.

## 4. Background estimator

Đọc reference RGBA sau EXIF orientation. Lấy mẫu dải biên và bốn góc, đánh giá mức đồng thuận theo Lab. Khi bằng chứng về nền phẳng yếu, giữ nguyên ảnh và ghi warning `BACKGROUND_UNCERTAIN`.

Khi nền đủ rõ, tìm các mẫu màu gần nền nối với mép ảnh. Fit một mặt chiếu sáng bậc hai bằng least squares có trọng số robust, rồi nội suy residual cục bộ từ mẫu nền. Cách này cho phép nền xám nhạt của ảnh mẫu thay đổi độ sáng nhẹ, thay vì giả định toàn bộ canvas có đúng một RGB.

Từ sai khác với background field, tạo background appearance/connectivity confidence. Giá trị này là confidence heuristic, không phải xác suất được hiệu chuẩn bởi mô hình học máy. `background_confidence=1.0` trong metrics là đồng thuận biên, không phải chất lượng foreground 100%.

## 5. Alpha matte

Ngưỡng màu chỉ dùng tạo trimap. Vùng chắc chắn là nền và foreground được xác định qua connectedness và erode; giữ dải uncertainty ở biên.

Ước lượng màu foreground gần đó từ nội thất artwork. Chi tiết tối có tương phản cao được làm seed dù chỉ một pixel. Nét sáng mảnh độc lập có màu liên tục cũng có thể làm seed. Không có quy tắc xóa component theo diện tích.

Trong dải uncertainty, giải alpha bằng phép chiếu theo mô hình màu cục bộ:

`I ≈ alpha × F + (1 − alpha) × B`

Giữ alpha liên tục trước khi ghi PNG 8-bit. Vùng sáng khép kín được bảo vệ bởi connectedness. Với input có alpha sẵn, giữ nguyên alpha nguồn.

Matte được tính trên lưới reference 554 × 554. Processing image 1662 × 1662 được chuẩn bị riêng bằng Lanczos4 trên màu premultiplied để tránh kéo RGB ẩn vào biên. Mapping theo tâm pixel: `p = (r + 0.5) × scale − 0.5`. Upscale chưa được dùng để suy ra màu mới.

## 6. Edge decontamination

Chỉ sửa RGB ở pixel có alpha một phần. Đảo mô hình compositing để ước lượng màu foreground khi bỏ nền. Regularization kéo nghiệm về màu foreground lân cận khi alpha rất thấp, hạn chế khuếch đại nhiễu JPEG và clip màu về miền hợp lệ.

Pixel output alpha=255 giữ nguyên RGB reference. `04_foreground.png` chứa RGB nguồn cùng matte để đối chiếu; `05_decontaminated_foreground.png` và `v2_foreground.png` là output đã khử màu nền ở biên.

Metrics của lần chạy ACTIVE FOX cuối:

| Metric | Giá trị |
|---|---:|
| Reference | 554 × 554 |
| Processing | 1662 × 1662 |
| Pixel alpha=0 | 264818 |
| Pixel alpha=255 | 32439 |
| Pixel alpha một phần | 9659 |
| Sai khác RGB tối đa ở pixel output opaque | 0 |
| MAE khi composite lại biên lên background ước lượng | 0.9754 / 255 |
| Pixel dải uncertainty có color-line residual cao | 2040 |
| Thời gian gồm ghi debug ở lần chạy này | khoảng 0.78 giây |

Recomposition MAE chỉ đo mức nhất quán với nền ước lượng. Nó không chứng minh đã khôi phục alpha thật của JPEG và không thay cho kiểm tra ảnh trực quan. Giá trị này không áp dụng cho input có alpha sẵn hoặc nền bị giữ lại.

## 7. Test results

Kết quả cuối: **22/22 pass**, gồm **18 test Phase A** và **4 test legacy**. Log: `backend/tests/artifacts/vectorization_v2/active_fox/phase_a/test_results.txt`.

Các nhóm kiểm tra gồm:

- EXIF, reference nguyên pixel/read-only, processing không chung bộ nhớ, mapping tọa độ khứ hồi.
- White, off-white, gray và flat colored background.
- Alpha mềm và decontamination so với ảnh tổng hợp có foreground/alpha thật; thêm phiên bản JPEG.
- Chi tiết tối một pixel, vùng cream, nét cream mảnh và chi tiết trắng khép kín.
- Giữ alpha sẵn; nền phức tạp giữ nguyên có warning.
- Chặn `Image.quantize()` để chứng minh Phase A không lượng tử màu.
- Chạy trong process chặn import VTracer/EasyOCR/PyTorch/PaddleOCR để kiểm tra không chạy phase sau.
- Hash legacy và SVG baseline không thay đổi.
- Artifact bắt buộc được tạo, không tạo SVG trong Phase A.
- ACTIVE FOX: điểm mũi/mắt/tai/highlight/chữ được chú thích từ source; kiểm tra rộng vùng nội thất có màu và cream không bị thủng/mất alpha.

Đã có lỗi kiểm tra trong quá trình phát triển và được xử lý công khai:

1. Một annotation chữ đặt vào pixel source RGB `[248,248,248]`, thực tế là nền. Đã thay bằng điểm nằm trong nét chữ tím, dựa trên ảnh nguồn.
2. Assertion đầu tiên yêu cầu mọi pixel trong mask màu đã erode 1 pixel phải gần opaque. Nó bao gồm biên antialias của JPG, nơi không có ground-truth alpha. Đã tách kiểm tra không tạo lỗ trên vùng gần biên và kiểm tra opaque ở nội thất cách biên 2 pixel. Test synthetic có ground-truth vẫn kiểm tra alpha biên nghiêm ngặt. Log lần fail này được giữ trong `test_results_intermediate_failure.txt`.

Không còn test fail ở lần chạy cuối. Không dùng kết quả này để tuyên bố đáp ứng các phase SVG/chữ/gradient chưa được triển khai.

## 8. Debug artifact paths

Thư mục: `backend/tests/artifacts/vectorization_v2/active_fox/phase_a/`

- `00_reference.png`
- `01_processing.png`
- `02_background_probability.png`: trắng = nghiêng về nền, đen = foreground, xám = chưa chắc chắn.
- `03_alpha_matte.png`: trắng = opaque, đen = transparent, xám = alpha mềm.
- `04_foreground.png`
- `05_decontaminated_foreground.png`
- `foreground_on_dark.png`
- `foreground_on_white.png`
- `legacy_foreground.png`
- `v2_foreground.png`
- `foreground_side_by_side.png`: source / legacy nền tối / V2 nền tối.
- `trimap.png`
- `estimated_background.png`
- `phase_a_metrics.json`
- `background_debug.json`
- `test_results.txt`

Chạy lại từ repository root bằng PowerShell:

```powershell
backend/.venv/Scripts/python.exe tools/run_vector_phase_a.py
$env:PYTHONPATH = (Join-Path (Get-Location).Path 'backend')
backend/.venv/Scripts/python.exe -m unittest discover -s backend/tests -p 'test_vectorization*.py' -v
```

CLI cũng nhận ảnh khác và `--output`, `--scale 1|3|4`. Nó chỉ đưa ảnh legacy ACTIVE FOX vào comparison khi hash input trùng fixture. Không gọi API đang chạy.

## 9. Những vấn đề còn nhìn thấy

Kiểm tra source/legacy/V2 trên nền tối, nền trắng và matte cho thấy: nền lớn đã được loại bỏ, màu cam/đỏ/vàng/cream và mũi/mắt/tai còn nguyên về cấu trúc; viền sáng liên tục của legacy giảm rõ.

Tuy nhiên, vẫn còn một số đốm JPEG nhỏ hoặc biên sáng ở phần đuôi/đường viền khi phóng lớn. Đầu đuôi rất nhạt vẫn là vùng không chắc chắn và có alpha mềm; chưa có alpha ground-truth để khẳng định khôi phục hoàn hảo. Các màu sáng khép kín trong chữ O/R được giữ lại; trên nền tối chúng còn là các mảng sáng. Đây là đánh đổi có chủ đích để Phase A không xóa nhầm mắt trắng của logo khi chưa có xử lý text/semantic được phép.

Không có vùng mất alpha lớn mới trong các nội thất có màu/cream mà test kiểm tra. Text nhỏ trên nền tối khó đọc do màu tím tối và độ phân giải source; Phase A giữ chữ raster, không làm OCR hoặc thay font.

Vì các điểm trên, kết quả là bản Phase A để người dùng duyệt, không phải cam kết foreground hoàn hảo trên mọi nền/ảnh.

## 10. Assumptions

- Mép ảnh và ít nhất ba góc cung cấp bằng chứng về một nền phẳng hoặc biến thiên sáng nhẹ.
- Input alpha nếu có là dữ liệu đáng tin, không tự xóa thêm nền khỏi ảnh đó.
- Giữ nguyên giá trị RGB nguồn; phép đo Lab giả định sRGB. Chưa chuyển ICC profile trong Phase A.
- Color-line matting dùng RGB encoded của ảnh để xấp xỉ cách raster/JPEG được composited.
- Chỉ xử lý ảnh tĩnh đầu tiên theo Pillow; không khôi phục chi tiết mà JPEG đã mất.
- Vùng artwork trùng hẳn màu nền và kết nối với nền là không thể xác định chắc chắn chỉ từ một ảnh.
- Processing upscale phục vụ các phase geometry sau này; không sinh palette hay semantic region.
- Giới hạn processing image 20 megapixel để tránh cấp phát không kiểm soát; CLI có thể chọn scale nhỏ hơn.

## 11. Dependencies

Không thêm dependency, không cài package và không đổi requirements. Phase A dùng Pillow, NumPy, OpenCV và thư viện chuẩn đã có. Renderer Svg.Skia hiện có chỉ được dùng trong bước capture baseline legacy.

**Dừng tại Phase A. Legacy vẫn là default. Chờ người dùng kiểm tra artifact trước khi có yêu cầu cho phase tiếp theo.**
