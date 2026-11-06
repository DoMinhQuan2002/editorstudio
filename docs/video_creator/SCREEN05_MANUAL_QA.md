# Screen 05 — Manual QA

## Runtime fixture

- App: WPF build Task 3.6 với backend Python/FastAPI cục bộ.
- Draft: Project V2 đã lưu từ Task 3.5, Denim Story, 15 giây, 9:16, 1080×1920, 5 compiled events.
- Preview source: Composition Graph và media bindings của draft; không dùng demo video/poster.
- Fixture có asset kiểm thử Active Fox, vì vậy frame runtime không giống ảnh minh họa Denim Story.
- Runtime screenshots: `artifacts/video_creator/task3_6/SCREEN05_runtime.jpg` (1920×1032 main window) và `SCREEN05_fullscreen_preview.jpg` (1920×1080 preview).

## Checklist

| Kiểm tra | Trạng thái | Bằng chứng/ghi chú |
| --- | --- | --- |
| Mở bản nháp đã lưu, giữ Project ID/template version | PASS | Mở lại latest saved draft, revision 3 |
| Dựng MP4 proxy từ Composition Graph, kiểm tra duration | PASS | MediaElement mở thời lượng 15 giây |
| Play / Pause | PASS | Runtime WPF |
| Chọn scene thứ ba seek và Play tiếp từ timestamp | PASS | Seek tới 00:06, phát tiếp tới khoảng 00:09 |
| Full-screen và đóng bằng Esc | PASS | Cửa sổ preview 1920×1080; frame Composition Graph nhìn thấy |
| Thay media qua UI và giữ bindings không liên quan | PASS | Slot đầu thay đổi; bốn slot còn lại giữ nguyên |
| Commit revision và mở lại | PASS | Thay media lên revision 2; khôi phục asset gốc thành revision 3; mở lại revision 3 |
| Audio track không có thì volume/mute track bị khóa có lý do | PASS | Không tạo nhạc nền giả |
| Không hiện input text khi definition thiếu editable field | PASS | Hiển thị lý do capability guard |
| Screen 06 disabled khi chưa triển khai | PASS | Nút tiếp tục bị khóa, nêu lý do |
| Main window 1426×893 | PASS | Runtime interaction ban đầu |
| Main window tối đa hóa 1920×1032 | PASS | Nội dung chính, preview và scene list hiển thị |
| Full-screen preview 1920×1080 | PASS | Ảnh frame và điều khiển phát/đóng hiển thị |
| Main window 1366×768 | Chưa xác nhận | Cửa sổ compact quan sát được là 1358×713, ngoài target và có thanh cuộn |
| Main window 1600×900 | Chưa xác nhận | Chưa đạt chính xác kích thước target |

GUI acceptance tổng thể giữ false cho tới khi xác nhận hai kích thước main window còn thiếu.
