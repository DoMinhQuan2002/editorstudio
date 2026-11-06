# FALL DIARY — LAYOUT ACCEPTANCE 3.9H

## Hai bố cục được so sánh

1. **Reference Layout QA** là biến thể chỉ dùng để so sánh trong harness. Nó lấy vị trí title/card từ Definition 0.3; metadata đánh dấu `qaOnly`. Baseline này giữ vị trí gần crop Muse và có thể đi qua mặt/người trong ảnh bất kỳ.
2. **Editorial Safe Layout** là profile khai báo trong Definition 0.5: `editorial-safe-v1`, version 1. Title hai hàng ở góc trên trái, card image `contain` nhỏ ở vùng dưới phải. Không có di chuyển ngẫu nhiên theo media và không gọi là face-aware.

Reference crop/UI không được đưa vào MP4. Title được vẽ bằng vector/text renderer nội bộ; dùng font Arial fallback, không dùng font độc quyền hay screenshot.

## Geometry

Canvas 1080×1920. Title dùng fontSize 52, glyph box opaque, x khoảng 0.065–0.257 và y 0.105/0.151. Ảnh card dùng `scale=0.18`, `positionX=0.28`, `positionY=0.30`, `fitMode=contain`, layerOrder 1; title ở layerOrder 20. Background là layerOrder 0 với cover. `Fall_Diary_3_9H_Layout_Bounds.json` tính geometry theo source aspect ratio; 20/20 image/text layer bounds nằm trong canvas (cover background fill là overflow có chủ đích), 0 title/card bounding-box intersections.

Tệp bounds chứng minh tọa độ hình học, nhưng không chứng minh bounding box tránh mặt hoặc chủ thể trong ảnh. Hiện không có face/subject detector đã được xác minh.

## Fixture review

- [11 ảnh QA thật](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Private_Photo_Fixture_Contact_Sheet.jpg) chứa close portraits, ảnh nằm/ngồi, full-body trong công viên và ảnh dọc. Tất cả 11 ảnh đều là portrait; không có ảnh nguồn ngang riêng.
- Bộ “second fixture” tại `task3_9b/second_fixture_set` thực chất là hình minh họa hình học. [Contact sheet](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Second_Fixture_Contact_Sheet.jpg) chỉ xác nhận renderer/bounds/decode trên hình đó; nó không đáp ứng diversity request về portrait, full-body, landscape, horizontal, vertical.
- WPF ảnh thật cho thấy title safe-area ở trên trái và card nhỏ ở dưới phải trên các frame được xem. Không suy rộng thành không che mặt trên mọi media.

## Trạng thái

- `allLayersWithinCanvas`: **true**.
- `titleOverlayIntersections` theo geometry: **0**.
- Bbox subject/face collision: **chưa đo được**.
- Fixture diversity review: **partial** (ảnh người thật và cảnh park có, nhưng không có ảnh ngang; second fixture synthetic).
- `FALL_DIARY_LAYOUT_QA_VERIFIED`: **false**.

Để đóng gate cần một bộ ảnh QA thứ hai hợp lệ, bao gồm portrait close-up, full-body, landscape, horizontal và vertical. Không sửa, crop hay ghi đè source media để tạo fixture này.
