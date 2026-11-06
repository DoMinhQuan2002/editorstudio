# Video Template Gallery — UI Spec

Phạm vi: màn hình chọn mẫu trong WPF Video Creator. Đây là gallery chọn template, không phải NLE/CapCut timeline.

## Bố cục

1. Shell sáng có sidebar điều hướng trái và top bar dùng window chrome của Windows.
2. Header gallery hiển thị `Chọn mẫu video`, subtitle, và search box. Nút `+ Dự án trống` bị ẩn cho đến khi sản phẩm có workflow phù hợp (`PRODUCT_DECISION_PENDING`).
3. Hàng category là danh sách động từ catalog, có `Tất cả` đứng đầu. Các category hiện có theo thứ tự ưu tiên: Xu hướng, Story, Carousel, Cut Out, Du lịch; category mới được thêm sau các category ưu tiên.
4. Nội dung gallery cuộn dọc độc lập với action bar.
5. Action bar tóm tắt mẫu đang chọn và được ghim dưới cùng.

## Card template

- Poster portrait 9:16; chiều cao được tính từ chiều rộng theo `16/9`.
- Grid dùng card có chiều rộng tối thiểu 220 DIP, khoảng cách 16 DIP và tối đa 6 cột. Số cột dựa trên chiều rộng cửa sổ, không dựa vào số lượng kết quả lọc. Vì vậy một kết quả search vẫn giữ nguyên cỡ card.
- Card dùng poster cục bộ nếu catalog cung cấp. Không có poster thì hiện placeholder portrait trung tính, không dùng ảnh screenshot hoặc ảnh ngẫu nhiên.
- Metadata hiển thị thời lượng, badge cảnh, số vị trí media, tên, mô tả và category. `Mới` chỉ hiện khi metadata `isNew` là true.
- Chỉ báo preview phản ánh việc catalog có preview; không tạo video giả.
- Chọn card hiển thị viền tím và dấu check; chỉ có một card được chọn.

## Hành vi

- Search tìm trên tên, mô tả và category, không phân biệt hoa/thường.
- Search và category được áp dụng đồng thời.
- Category được chọn có nền tím nhạt/viền tím; hover và keyboard focus có viền tương phản.
- Selection tồn tại khi search/category vẫn hiển thị mẫu đó; selection bị xóa rõ ràng nếu mẫu rời tập kết quả.
- Empty catalog, không có kết quả, loading và backend lỗi có thông báo riêng; không tạo template giả.
- Action bar cập nhật tên, số vị trí media, thời lượng và tỷ lệ.
- `Mở dự án` và `Dùng mẫu` đang disabled kèm lý do vì project-open và media-slot workflow chưa kết nối. Chọn card không tạo project.

## Navigation

- Video Editor và Image Tools là route hoạt động.
- Dự án, Thư viện, Xuất video và Cài đặt chưa có trang/flow tích hợp trong shell này nên disabled với tooltip giải thích.
- Không có route từ gallery về UI timeline cũ.

## Ranh giới so sánh thiết kế

Attachment của TASK 3.0B hiện chỉ chứa nội dung task, không có ảnh UI reference chính thức. Runtime screenshot tại 1427×744 đã được lưu, nhưng chưa thể đánh giá pixel parity. Các độ phân giải 1366×768, 1600×900, 1920×1080 và các mức Windows scaling 100/125/150% chưa được chạy trong môi trường này.

