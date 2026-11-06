# FALL DIARY — LAYOUT QA

## Phương pháp

Đọc trực tiếp layer definition và quy tắc renderer chung. Với ảnh, renderer fit ảnh vào canvas trước (`cover` hoặc `contain`), áp dụng scale, rồi đặt tâm theo công thức `x=(W-w)/2 + W*positionX`, `y=(H-h)/2 + H*positionY`. Vì không có subject detection đáng tin cậy trong backend, không dùng heuristic theo pixel, màu hay 12 fixture để “tìm mặt”. QA giới hạn ở hình học, safe area, layer overlap và kiểm tra frame render.

## Bounding boxes

Canvas 1080×1920. Background layers dùng `cover`, position (0,0), scale 1: bounds luôn [0,0,1080,1920]; crop nội dung theo aspect ratio nhưng layer không vượt canvas.

| Overlay | Slot | x / y | Scale | Bao hình học tối đa trên ảnh portrait |
|---|---|---:|---:|---|
| pour-card | photo-06 | +0.16 / −0.22 | 0.28 | [561.6, 268.8, 864.0, 806.4] |
| basket-card | photo-07 | +0.16 / −0.22 | 0.28 | [561.6, 268.8, 864.0, 806.4] |
| park-figure-card | photo-08 | −0.16 / −0.20 | 0.27 | [221.4, 316.8, 513.0, 835.2] |
| coffee-close-card | photo-09 | +0.15 / −0.22 | 0.28 | [550.8, 268.8, 853.2, 806.4] |
| picnic-transition-card | photo-10 | −0.15 / −0.20 | 0.27 | [232.2, 316.8, 523.8, 835.2] |
| market-figure-card | photo-11 | +0.16 / −0.21 | 0.28 | [561.6, 288.0, 864.0, 825.6] |

Bounds là envelope cho ảnh portrait 9:16; ảnh landscape/square qua `contain` có ít nhất một chiều nhỏ hơn envelope. Tất cả x/y nằm trong canvas. Overlay event nằm khoảng phần trên 14–44% chiều cao; title graphic nằm thấp hơn tại hai baseline y=0.57/0.615. Text tile x được đặt từ 0.382 đến 0.586, font size 64, border 3, shadow (3,4); box ước lượng khoảng x=413…700 và y=1094…1260, còn cách mọi cạnh canvas.

## Overlap và kiểm tra hình ảnh

- Layer order: background 0, collage card 1, title 20. Chồng overlay lên background là chủ đích của collage; title graphic được vẽ trên cùng.
- Không có layer ngoài canvas ở first frame, giữa các event, sát mọi biên cut và frame cuối. Các event ngắn 0.5s được kiểm tra ở cả hai phía boundary bằng frame samples.
- Contact sheet `artifacts/video_creator/task3_9c/Fall_Diary_Reference_vs_0_3_Frame_Comparison.jpg` cho thấy nền portrait và card collage thật; title đôi lúc đi qua vùng thân người trong fixture nhưng không che mặt ở các frame đã xem. Đây là quan sát fixture cụ thể, không phải cam kết về ảnh người dùng bất kỳ.
- Reference crop, 0.1, 0.2 và 0.3 được đặt cạnh nhau để review. SSIM không dùng làm tiêu chí duy nhất của reference fidelity.

## Giới hạn và trạng thái

Backend không có segmentation/face-safe region capability trong phạm vi task. Safe-area fallback là `contain` card kích thước nhỏ, đặt trong nửa trên canvas; không quảng cáo là nhận diện chủ thể thông minh. Text tile vị trí gần đúng theo crop và còn uncertainty về thời điểm kết thúc. Cutout không triển khai.

**Cổng:** `FALL_DIARY_LAYOUT_QA_VERIFIED=true` cho bounds, safe area và cấu trúc layer của definition này. Chưa xác nhận semantic face-safe trên media mới; cần subject-safe placement nếu muốn bảo đảm không che chủ thể.
