# Screen 06 — output validation

Backend tạo staging MP4, sau đó:

1. FFprobe phải nhận dạng MP4 container và H.264 video stream.
2. Width/height và rational fps phải khớp Composition Graph.
3. Duration phải khớp graph trong tolerance 0.1 giây hoặc 1.5 frame.
4. Nếu draft có audio, output phải chứa AAC.
5. FFmpeg giải mã toàn bộ với `-xerror`; lỗi giải mã làm job fail.
6. Recheck dung lượng đích; copy vào partial file cùng thư mục đích, flush/fsync, xác nhận size rồi atomic rename/replace.
7. Chỉ sau publish mới ghi `SUCCEEDED`, history record và progress 100.

UI kiểm tra file tồn tại và kích thước bằng backend result trước khi hiện thành công.

## Runtime MP4

File `artifacts/video_creator/task3_7/gui_export/Denim Story Task 3.7 GUI.mp4`:

| Trường | Kết quả |
|---|---|
| Container | MP4 (`mov,mp4,m4a,3gp,3g2,mj2`) |
| Video | H.264 |
| Resolution | 1080×1920 |
| Average frame rate | 30/1 |
| Duration | 15.000000 giây |
| Size | 220,361 bytes |
| Audio | Không có stream; draft fixture không có audio nguồn |
| Full decode | Pass, ffmpeg exit 0 |

Output chưa được kiểm bằng player ngoài trong ma trận nhiều OS; WPF preview và file decoder backend đều đã đọc được.
