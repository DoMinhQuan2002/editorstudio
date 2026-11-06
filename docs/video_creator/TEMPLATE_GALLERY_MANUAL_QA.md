# Video Template Gallery — Manual QA

## Môi trường đã kiểm tra

- Windows WPF build: `artifacts/video_creator/task3_0b/solution-output-reviewed/Debug/net10.0-windows/MediaStudio.Desktop.exe`.
- Cửa sổ thực tế: 1427×744 logical pixels. Mức scaling Windows chưa được xác minh.
- Backend: đã kết nối; catalog tải 7 mẫu.
- Screenshot: `artifacts/video_creator/task3_0b/screenshots/VideoEditorGallery_1427x744.jpg`.

## Bài kiểm tra runtime đã chạy

| Thao tác | Kết quả |
|---|---|
| Khởi động app | Mở ở Image Tools; backend báo connected. |
| Chọn Video Editor | Điều hướng vào gallery trong cùng shell. |
| Tải catalog | Hiện 7 mẫu thật; card không có poster ghi placeholder 9:16 và chưa có preview. |
| Lọc Story | Danh sách thay đổi theo metadata category của catalog. |
| Search `Travel` | Còn một card và card giữ chiều rộng chuẩn, vùng trống không làm card giãn. |
| Chọn `Tất cả`, chọn Denim Story | Viền tím và dấu check hiện; action bar cho biết 5 vị trí media, 00:15, 9:16. |
| Sidebar shell | Image Tools vẫn hiển thị và route hoạt động; trang phụ chưa triển khai được disable. |
| Cuộn danh sách | Gallery có scroll dọc độc lập với action bar ghim dưới. |

Không nhấn hai CTA đang disabled. Source binding xác nhận chọn card chỉ cập nhật selection, không tạo project hoặc điều hướng tới timeline cũ.

## Kiểm tra tự động

- WPF solution build: 0 warning, 0 error (`artifacts/video_creator/task3_0b/dotnet-build.log`).
- .NET tests: 24 passed, 0 failed, 0 skipped (`artifacts/video_creator/task3_0b/dotnet-test.log`, `test-results-reviewed/task3_0b.trx`).
- Backend catalog/API tests: 6 passed; một cảnh báo deprecation Starlette/AnyIO (`artifacts/video_creator/task3_0b/backend-catalog-test.log`).
- Test gồm load catalog thật qua client giả lập HTTP, không fallback, selection/filter/search, số slot và badge preview lấy từ catalog, responsive column calculation và toán tỷ lệ 9:16.

## Còn chờ kiểm tra

1. Chụp/đối chiếu với ảnh UI reference được duyệt: file reference không có trong attachment TASK 3.0B hiện có.
2. Chạy kích thước 1366×768, 1600×900 và 1920×1080.
3. Chạy Windows scaling 100%, 125%, 150%.
4. Kiểm tra keyboard-only qua tất cả category/card/search và trạng thái focus trong phiên thao tác thủ công.
5. Kiểm tra loading lâu, backend lỗi rồi phục hồi, danh mục dài, file poster thật và cache khi cuộn nhiều.
6. Kiểm tra media-slot workflow sau khi backend/Template Instance triển khai; hiện CTA disabled nên chưa thể kiểm tra tạo instance.

Ở 1427×744, poster giữ tỷ lệ đúng nên một phần card nằm dưới vùng cuộn. Không quan sát thấy card lấn lên action bar.

## Mở app để test

Build cuối đã được mở và đang ở màn hình Video Editor với Denim Story được chọn. Nếu cần tự mở lại, chạy executable nêu ở phần môi trường. Để kiểm tra search/filter, dùng các chip category hoặc ô tìm kiếm ở góc phải trên gallery.

