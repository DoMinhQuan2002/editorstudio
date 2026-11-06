# FALL DIARY — MOTION CONTINUITY TESTS 3.9H

## Engine và cấu hình 0.5

0.5 dùng linear interpolation engine chung. Chỉ background event có keyframe scale: `1.0 → 1.012` trong thời lượng event; hai keyframe nằm tại 0 và duration của clip. Đây là **EDITORIAL_MOTION**, không phải motion nguồn được khôi phục. Overlay events và title giữ tĩnh; overlay motion được gắn `UNVERIFIED`. Không thêm easing, random motion, transition mới hay renderer riêng.

Khi overlay thay đổi tại 3.767, 5.267, 6.767, 9.267 hoặc 10.267, background clip không bị chia hoặc restart. Background keyframes chỉ bắt đầu lại tại các event nền độc lập. Event boundary nằm trên 30 fps frame boundary (`3000 ticks` ở timebase `90000`). Background/candidate changes tại 5.767, 9.767, 13.267 (UNKNOWN), 13.767 được giữ như các đoạn mới trong graph.

## Ma trận kiểm tra

| Kiểm tra | Bằng chứng | Kết quả |
|---|---|---|
| First frame | Preview frame 0 / WPF preview đầu timeline | Khung đã xem có ảnh nền/title; không thấy black frame ở sample này |
| Mid frames | 3.733/3.767, 5.233/5.267, 6.733/6.767, 9.233/9.267, 10.233/10.267s | Overlay changes tại boundary; background continuity theo graph |
| Background boundaries | 5.733/5.767, 9.733/9.767, 13.233/13.267, 13.733/13.767s | Frame trước/sau hiện trong reference comparison; các sample không cho thấy black gap; full decode không lỗi |
| Short overlay | 0.5s coffee/picnic replacement và 0.5s food background candidate | 15 frame mỗi event ở 30 fps; boundary ticks căn khung hình |
| End frames | 16.5s / frame 495 và WPF preview duration 17s | Có hình đến cuối draft; title end vẫn là giả định pilot |
| Keyframe interpolation | 90 kHz/linear keys được compile vào Project V2/Graph | PASS; Không khẳng định Muse source motion |
| Preview/export agreement | 22 same-graph frame samples; 22 WPF r1 frame samples và SSIM trên 510 frame | PASS theo [parity report](FALL_DIARY_PREVIEW_EXPORT_PARITY.md) |

## Kết quả và giới hạn

Preview và export đều full-decode không lỗi; các frame mẫu quanh event boundaries không cho thấy black frame. Geometry/continuity tests xác nhận overlay không reset nền. `FALL_DIARY_MOTION_CONTINUITY_VERIFIED=true` chỉ nghĩa là event/keyframe behavior hiện tại liên tục và có thể phát/xuất; `FALL_DIARY_REFERENCE_MOTION_VERIFIED=false` vì screen recording không cung cấp source keyframes, easing hoặc transform chính xác.
