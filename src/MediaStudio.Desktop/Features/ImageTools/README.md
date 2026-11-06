# Image Tools

Nhóm chức năng đầu tiên của app desktop, tham khảo ba công cụ BENDESIGN. Mỗi workflow nằm trong module riêng: `image-upscale`, `image-to-vector` và `die-cut-line`.

WPF views/viewmodels giữ workflow riêng cho `image-upscale`, `image-to-vector` và `die-cut-line`. Viewmodel dùng typed `HttpClient` service để gọi Python backend. File picker, xem trước ảnh/SVG và hộp thoại lưu thuộc WPF; xử lý ảnh, vector hóa, tạo contour đường bế và trạng thái job thuộc backend.

## Giao diện hiện tại

Màn hình vector hóa dùng một thao tác tự động: backend tự chọn engine, nhận diện bảng màu, ưu tiên giữ chi tiết, làm mượt đường và xuất SVG nền trong suốt; người dùng chỉ cần chọn ảnh, bấm chuyển đổi và lưu kết quả. Có bản xem trước SVG và số path sau xử lý. Màn hình upscale và đường bế đã có pipeline riêng. Đường bế nhận diện alpha/nền liền màu, có cọ giữ/bỏ để tinh chỉnh mask, quy đổi offset từ mm theo chiều rộng in, xem trước và lưu SVG. Import vào Media Library và zoom/drag compare vẫn cần triển khai thêm.
