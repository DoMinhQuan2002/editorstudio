# Fall Diary — phân tích reference

> This was the pre-ingest analysis. The reference kit is now verified and the timestamp analysis is maintained in [FALL_DIARY_FRAME_BY_FRAME_ANALYSIS.md](FALL_DIARY_FRAME_BY_FRAME_ANALYSIS.md).

## Trạng thái input

Task brief nêu `FALL_DIARY_Reference_Kit.zip`, chứa demo MP4, 12 ảnh riêng tư, SHA-256 manifest và README phạm vi sử dụng. Tệp ZIP không có trong workspace và không tìm thấy trong `C:\Users\Quan\.codex\attachments`. Vì vậy chưa đọc được README, chưa xác minh hash/quyền dùng và không có MP4/ảnh để phân tích.

FFmpeg và FFprobe có thể gọi trên máy này. Không chạy FFprobe/scene detection vì input không tồn tại. Báo cáo trạng thái máy đọc được tại [FALL_DIARY_FFPROBE_REPORT.json](FALL_DIARY_FFPROBE_REPORT.json); đây không phải probe report của video.

## Bảng timestamp

| Start | End | Visual content | Layers | Effects | Confidence |
|---|---|---|---|---|---|
| N/A | N/A | MP4 demo chưa được cung cấp; không có frame quan sát được. | UNKNOWN | UNKNOWN | UNKNOWN |

Không có timestamp nào được suy diễn từ tên template hay task description. Các ý “collage”, “chuyển cảnh nhanh”, “foreground cutout” chỉ là nội dung yêu cầu cần đối chiếu; chúng chưa được đánh dấu OBSERVED từ video.

## Chưa thể kết luận

- Duration, frame size, aspect ratio thực, frame rate, audio streams và codec.
- Scene changes, lớp hình mới, hard cuts/fades/wipes và thời điểm bắt đầu/kết thúc mỗi event.
- Text/sticker, vị trí/scale/opacity, collage geometry, mask/cutout.
- Nhịp edit so với audio.
- Poster/demo rights và giới hạn phân phối.

Khi kit sẵn có, tính hash theo manifest trước khi giải nén fixture; chạy `ffprobe -v error -show_format -show_streams -of json <demo.mp4>`; dựng contact sheet theo timestamp; sau đó xác nhận scene boundary bằng mắt. MP4 chỉ là bằng chứng hình ảnh cuối cùng, không cung cấp keyframe/easing/mask gốc.
