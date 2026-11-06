# Video Creator — release gates

Baseline ngày 2026-10-22.

TASK3_0A_LEGACY_UI_RETIRED = true  
TASK3_0A_CODE_READY = true  
TASK3_0A_GUI_ACCEPTED = false  
TASK3_0B_IMPLEMENTED_AUTOMATED = true  
TASK3_0B_LIVE_GUI_SPOTCHECK = true  
TASK3_0B_GALLERY_UI_READY = false  
TASK3_0B_REFERENCE_COMPARISON = pending  
PRODUCT_DECISION_PENDING = true  
VIDEO_CREATOR_RELEASE_READY = false

## Task 3.0A

| Gate | Status | Evidence / remaining |
|---|---|---|
| Không còn route public mở manual NLE | PASS source audit | MainWindow chỉ bind Gallery; enum route ID còn nội bộ. |
| Timeline UI, inspector, editing commands gỡ WPF | PASS source audit | Legacy View/VM/services/wrappers bị xóa; không còn caller. |
| Gallery dùng catalog thật | CODE PASS | Backend TestClient trả HTTP 200 với 7 templates; Gallery VM tests catalog/search/category. Runtime log ghi request của WPF; chưa quan sát nội dung Gallery vì màn hình khóa. |
| Không fallback khi backend lỗi | PASS | Test xác nhận empty state, không tạo template cục bộ. |
| Preview status không gây nhầm | PASS source/data | Các template previewAvailable=false; card ghi chưa có video preview. |
| Nút Dùng mẫu không tạo project chưa hỗ trợ | PASS source audit | Button disabled, không gọi project create. |
| Project V2/renderer/API giữ | PASS regression subset | Backend không sửa; 57 tests passed, 3 skipped, 10 subtests passed. |
| Image Tools regression | PASS regression subset | 24 tests passed; workspace mặc định vẫn Image Tools. |
| Source backup/restore | PASS | 27 file snapshot và copy-back hash khớp. |
| WPF solution build | PASS | 0 warning, 0 error với output riêng do EXE gốc đang bị hai tiến trình giữ lock. |
| WPF tests | PASS | 16 passed, 0 failed, 0 skipped. |
| GUI acceptance | PENDING | Windows ở lock screen khi chụp; không click/không xác nhận visual. |
| Native ASan | NOT RUN | Không sửa C++; không tuyên bố regression ASan mới. |

## Điều kiện release sản phẩm

1. Gallery hiển thị template thật và preview thật.
2. Slot contract rõ; người dùng gắn ảnh/video đúng slot.
3. Binding lưu bền vững qua Save/Reopen.
4. Compiler tạo Project V2 đúng scene, timing, transform, text, audio.
5. Preview/export parity cho nhiều template và media.
6. MP4 export hoạt động từ workflow Video Creator.
7. Legacy UNKNOWN bảo toàn và báo rõ nếu unsupported.
8. Không backend/native crash, không ảnh hưởng Image Tools.

TASK 3.0A chỉ chuẩn bị nền. Xóa NLE UI không đóng release gates trên.

## Manual GUI verification còn lại

Sau khi Windows được mở khóa:

1. Xác nhận app mới mở ở Image Tools và backend connected.
2. Chuyển sang Video Creator; đối chiếu gallery có 7 mẫu catalog, các thẻ báo “chưa có video xem trước”.
3. Thử search/category/selection và kiểm tra summary khớp.
4. Xác nhận nút “Dùng mẫu” bị disable, không xuất hiện timeline/editor và không tạo project mới.
5. Quay lại Image Tools, xác nhận ba workflow và backend status không bị ảnh hưởng.

Đến khi các bước này được chạy trực tiếp, TASK3_0A_GUI_ACCEPTED giữ false.

## TASK 3.0B — Template Gallery WPF

| Gate | Status | Evidence / remaining |
|---|---|---|
| Catalog backend thật, không fallback | PASS | WPF runtime tải 7 mẫu; backend catalog/API tests 6 passed. |
| Search/category/selection và bottom summary | PASS spot check | Đã lọc Story, search Travel, chọn Denim Story; summary hiện 5 slot, 00:15, 9:16. |
| Poster dọc và responsive grid | PASS code/test + runtime spot check | `PortraitAspectFrame` dùng 9:16; `ResponsiveGalleryPanel` giữ cỡ khi chỉ còn một kết quả. Runtime 1427×744 cho 4 cột. |
| Không preview giả, không route NLE cũ | PASS source/runtime spot check | Catalog báo `previewAvailable=false`; CTA dùng mẫu/mở dự án disabled; chọn card không tạo project. |
| Image Tools route còn hoạt động | PASS runtime spot check | App mở mặc định Image Tools; chuyển tới Video Editor hoạt động. Chưa chạy xử lý ảnh mới. |
| WPF build / .NET tests | PASS | 0 warning, 0 error; 24 passed. |
| Backend catalog/API tests | PASS | 6 passed, một deprecation warning Starlette/AnyIO. |
| Runtime screenshot | PASS | `artifacts/video_creator/task3_0b/screenshots/VideoEditorGallery_1427x744.jpg`. |
| So sánh với ảnh UI reference chính thức | PENDING | Attachment hiện có chỉ chứa task text, không có reference image. |
| Kích thước/scaling mục tiêu | PENDING | Chưa xác minh 1366×768, 1600×900, 1920×1080 hoặc 100/125/150%. |
| `Dùng mẫu` và `Mở dự án` workflow | PENDING | Đang disabled có giải thích; cần instance/slot/persistence/compiler và project-open workflow. |
| Tạo dự án trống | PRODUCT DECISION PENDING | Nút bị ẩn vì chưa có luồng tạo dự án trống của Video Creator. |

Do thiếu reference image và chưa kiểm tra toàn bộ kích thước/scaling, `TASK3_0B_GALLERY_UI_READY` vẫn false dù bản WPF đã được spot check trực tiếp.
