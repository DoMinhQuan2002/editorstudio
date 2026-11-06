# Fall Diary — motion pilot specification 0.2.0

## Phạm vi

Đây là một definition QA có version riêng, được compile bởi generic Template Compiler và Composition Graph. Definition `0.1.0-pilot` giữ nguyên. Bản 0.2 thử chuyển động liên tục trên asset bất kỳ theo Slot ID; các lựa chọn motion trong bản này là thiết kế mới để kiểm chứng renderer, không phải dữ liệu keyframe lấy từ Muse.

| Thuộc tính | Giá trị |
|---|---|
| Template ID / version | `fall-diary` / `0.2.0-motion-pilot` |
| Canvas / rate / duration | 1080×1920 / 30/1 pilot / 1,350,000 ticks = 15 s |
| Slot | 12 slot ảnh, required, `reusePolicy=allow`, thiếu media là lỗi |
| Visual events | Sáu event hard-cut nối tiếp, mỗi event 225,000 ticks (2.5 s) |
| Text graphic | Hai text clip riêng: `FALL`, `DIARY`; text box, màu, viền và shadow |
| Audio | Không có trong reusable definition; tone chỉ được gắn ở QA project |
| Cutout/mask | Không khai báo và không được hỗ trợ |

## Bố cục và chuyển động

| Event | Khoảng (s) | Số visual layer | Ý đồ bố cục | Motion thử nghiệm |
|---|---:|---:|---|---|
| `scene-01-open` | 0–2.5 | 2 | Nền tràn khung + card chính | Nền scale 1.00→1.045; card dịch X/Y, scale 0.52→0.60, rotation −5°→−2°, opacity 0.72→1 |
| `scene-02-double-card` | 2.5–5 | 3 | Nền + hai card lệch hai bên | Hai card có đường đi và scale riêng; card phụ tăng opacity |
| `scene-03-offset-stack` | 5–7.5 | 3 | Nền + card chính lệch tâm + detail | Cả hai card đổi vị trí/scale độc lập; detail tăng opacity |
| `scene-04-sweep` | 7.5–10 | 2 | Nền + một card lớn quét ngang | Nền scale 0.98→1.07; card dịch X/Y, scale 0.45→0.64 và rotation 3°→−2° |
| `scene-05-four-layer-collage` | 10–12.5 | 4 | Nền + ba card, mật độ không đều | Nền zoom nhẹ; card trái/giữa/phải đổi vị trí, scale hoặc opacity khác nhau |
| `scene-06-close` | 12.5–15 | 3 | Nền + hai card tiến vào nhau | Hai card có path riêng theo X/Y, scale; card dưới tăng opacity |

`title-card` hiển thị từ 0–2.5 giây phía trên lớp hình ảnh. Nền là ảnh `cover`; card là ảnh `contain` có transform. Các vị trí dùng tọa độ tương đối tâm khung. Tất cả event duration/keyframe được khai báo bằng tick 90 kHz. Không dùng frame index làm timing.

## Hành vi renderer

- Preview ảnh tĩnh chọn frame theo Project V2 timebase, rồi gọi cùng bộ nội suy tuyến tính để giải `positionX`, `positionY`, `scale`, `rotation`, `opacity`.
- Video preview và export gọi chung FFmpeg composition builder; export dùng biểu thức theo timestamp source/timeline phù hợp mỗi filter. Scale/rotation dùng thời gian local của clip; overlay position và alpha dùng thời gian global sau khi đặt PTS, trừ thời điểm bắt đầu clip.
- Opacity animation chạy trên alpha plane bằng biểu thức geq của FFmpeg; preview frame giải giá trị cùng hàm nội suy để so khớp export.
- Text box/shadow là thuộc tính V2 rõ ràng; text size vẫn scale theo canvas thiết kế portrait 1080×1920.
- Native still-preview backend từ chối keyframe để fallback sang FFmpeg, tránh hiển thị frame không animation.
- `to_legacy_project` chỉ tạo projection tĩnh cho consumer cũ. Keyframe/text graphic vẫn còn nguyên trong canonical Project V2 tracks; projection legacy bỏ các field mà model cũ không hiểu.

## Cổng support

| Hiệu ứng | Trạng thái 0.2 |
|---|---|
| Linear keyframes: X/Y/scale/rotation/opacity | Được hỗ trợ, compile và render đã kiểm chứng |
| Transform tĩnh hiện có | Giữ tương thích; regression cũ đạt |
| Varying layer count và slot reuse | Được hỗ trợ; 2/3/3/2/4/3 layer trong các event |
| Text box graphic | Được hỗ trợ dạng tĩnh; hai text layer, canvas scaling |
| Hard cut | Được hỗ trợ |
| Video media trong definition Fall Diary | Chưa hỗ trợ: slot/layer của definition 0.2 giới hạn ảnh tĩnh |
| Keyframed crop/pan, non-linear easing, fade/wipe | Chưa hỗ trợ |
| Automatic foreground segmentation / mask provenance | Chưa hỗ trợ |
| Source Muse motion/easing/timing parity | Chưa xác định |

Evidence file: `artifacts/video_creator/task3_9b/Fall_Diary_Motion_Manifest.json`; render harness: `tools/video_creator/render_fall_diary_task39b.py`.
