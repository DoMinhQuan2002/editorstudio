# Screen 05 — Result Preview & Light Editing

## Mục tiêu

Màn 5 xem bản dựng đã lưu từ Screen 04 trong cùng workflow Video Creator. Đây là màn xem kết quả và thực hiện thay đổi được template cùng renderer hỗ trợ; không phải NLE nhiều track.

## Bố cục

- Dùng shell, sidebar, header, màu tím và các thành phần WPF sẵn có.
- Stepper đánh dấu Chọn media và Xử lý hoàn tất, Chỉnh sửa đang hoạt động, Xuất chưa thực hiện.
- Khung preview dọc theo aspect ratio của Project V2. Player có Play, Pause, seek, thời gian hiện tại/tổng thời lượng, mute khi xem và toàn màn hình khi MediaElement hỗ trợ.
- Danh sách cảnh được nhóm từ event/timing trong compiled composition. Mỗi cảnh có thumbnail render từ Project V2, nhãn, thời lượng và nút điều hướng đến thời điểm bắt đầu.
- Bảng bên cạnh hiển thị tên mẫu, Template ID/version, revision, thời lượng, độ phân giải và những thiết lập thật sự có thể thay đổi.
- Nút Thay media dùng lại Media Selection của Video Creator. Nút lưu chỉ bật khi có thay đổi cần commit.
- Nút sang xuất bị khóa cho đến khi có Screen 06; lý do được hiển thị trên nút.

## Quy tắc khả năng

- Text/sticker chỉ mở khi đúng Template Definition khai báo trường editable. Denim Story hiện không có khai báo nên giao diện nêu lý do và không hiển thị input giả.
- Thiết lập âm thanh chỉ mở khi Project V2 có đúng một audio track được hỗ trợ. Nếu không có track, volume/mute của nhạc nền bị khóa và có giải thích.
- Không hiển thị thao tác thêm/xóa cảnh, kéo-thả, split, trim, reorder, track ID hoặc clip ID.
- Không dùng poster hay video demo của template làm preview kết quả.

## Trạng thái

| Trạng thái | Hành vi |
| --- | --- |
| Đang mở bản nháp / dựng preview | Khóa điều khiển sửa và hiện trạng thái tiến hành |
| Preview hợp lệ | Bật phát, tua, xem cảnh và thay media |
| Render hoặc validation lỗi | Hiện lỗi; không báo đã lưu/cập nhật thành công |
| Cập nhật đang chờ | Khóa tiếp tục và không bàn giao revision cũ |
| Không có capability | Khóa đúng điều khiển và nêu nguyên nhân |

Quay lại trở về flow Video Creator mà không xóa selection, bindings hay Project V2. Job Screen 04 chỉ mở Màn 5 sau khi succeeded và trả về Project ID hợp lệ. Gallery có lối mở lại bản nháp template gần nhất đã lưu.
