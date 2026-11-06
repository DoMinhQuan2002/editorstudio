# Fall Diary — preview/export comparison

## Kết quả

Chưa tạo preview frame hay MP4 cho Fall Diary. Thiếu reference MP4, poster, 12 private fixtures, definition, media bindings và slot-selection workflow. Render một slideshow tự tạo từ ảnh khác sẽ không kiểm tra collage/cutout của template gốc, nên không được dùng làm bằng chứng.

| Check | Preview | Export | So sánh |
|---|---|---|---|
| 9:16 và output dimensions | Chưa chạy | Chưa chạy | N/A |
| Duration/timestamp boundaries | Chưa có definition | Chưa có definition | N/A |
| Layer order/collage | Chưa có binding/reference | Chưa có binding/reference | N/A |
| Scale/position/opacity keyframes | Keyframes unsupported | Keyframes unsupported | N/A |
| Text/font | Chưa chạy | Chưa chạy | N/A |
| Alpha/cutout | Không có segmentation artifact | Không có segmentation artifact | N/A |
| Audio | Chưa có licensed/source track | Chưa có licensed/source track | N/A |
| MP4 decode | Không có output | Không có output | N/A |

Generic compiler tests đã xác minh Project V2/Composition Graph được tạo từ fixture JSON tổng hợp; chúng không phải preview/export test. Không có render outputs nào được sinh trong TASK 3.4.

## Kế hoạch xác minh sau khi nhận kit

1. Kiểm tra SHA-256 và README trước khi import; giữ 12 ảnh trong private test fixture location.
2. Tạo definition từ frame-by-frame analysis, đánh dấu OBSERVED/INFERRED/UNKNOWN.
3. Chọn, thay, bỏ và bind các ảnh qua Màn 3; thử ít hơn/khác 12 ảnh theo policy tường minh.
4. Render preview và MP4 bằng cùng Project V2 snapshot; lấy frame tại opening, cut boundaries, overlay/collage, text, cutout, và ending.
5. FFprobe output, decode toàn bộ file, đối chiếu timestamps/layers/alpha/audio và ghi sai khác.
6. Lặp lại với ảnh ngoài bộ fixtures để tìm giả định phụ thuộc bộ test.
