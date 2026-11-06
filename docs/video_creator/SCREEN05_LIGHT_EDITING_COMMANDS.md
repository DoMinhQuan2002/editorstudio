# Screen 05 — Light Editing Commands

Các điều khiển hướng theo thao tác người dùng; không đưa thuật ngữ Track ID, Clip ID hay Composition Graph vào luồng sản phẩm.

| Điều khiển | Tác động | Điều kiện |
| --- | --- | --- |
| Phát / Tạm dừng | Điều khiển MediaElement đang phát MP4 proxy của draft | Preview đã mở và duration được xác minh |
| Tua | Đặt vị trí playback và yêu cầu render frame tại timestamp đó | Preview hợp lệ |
| Chọn cảnh | Tua player đến thời điểm bắt đầu event, đồng thời cập nhật frame preview | Cảnh đến từ event thật trong composition |
| Tắt tiếng khi xem | Chỉ mute/unmute playback cục bộ | Không sửa audio Project V2 |
| Toàn màn hình | Mở player cùng URI; Esc đóng và trả vị trí phát về màn chính | WPF MediaElement mở được |
| Thay media | Mở Media Selection với bindings hiện tại; chỉ slot đổi media mới được cập nhật | Template/version khớp và media mới được validate |
| Âm lượng track | Cập nhật volume audio track canonical rồi lưu revision mới | Chính xác một audio track được hỗ trợ |
| Tắt tiếng track | Cập nhật muted trên lane audio và lưu revision mới | Chính xác một audio track được hỗ trợ |
| Lưu bản nháp | Commit thay đổi audio vào Project V2 hiện tại | Có thay đổi hợp lệ; không tạo project mới |

## Bị khóa theo capability

- Text/sticker: template hiện hành không khai báo trường chữ editable.
- Nhạc nền: Denim Story runtime không có audio track; không sinh nhạc giả, không hiển thị volume thay đổi được.
- Undo/redo, crop/style override và sửa hiệu ứng: chưa có capability/transaction an toàn, nên không hiển thị nút giả.
- Chuyển sang xuất: Screen 06 chưa nằm trong phạm vi.
