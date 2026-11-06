# FALL DIARY — BACKGROUND / OVERLAY TIMELINE 3.9H

## Cách đọc evidence

Nguồn Muse là screen recording 720×1556, không phải project nguồn. Chỉ crop vùng preview video; header, footer, nút Use template, nút bookmark, nút đóng và Control Center không được xem là layer của video. Khung cô lập theo timestamp nằm trong [reference_frames/isolated](../../artifacts/video_creator/task3_9c/reference_frames/isolated/). Sheet đối chiếu mới nhất là [Fall_Diary_3_9H_Reference_Comparison.jpg](../../artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Reference_Comparison.jpg).

Detector timestamps là thời điểm screen-recording; chúng không chứng minh source cut point. 30 fps và 90 kHz cho `3,000 ticks/frame`. Ví dụ `3.767 s × 90,000 = 339,030 ticks`, căn gần nhất về `339,000` (frame 113), lệch −30 ticks = −0.333 ms. Các mốc 3 chữ số dưới đây đều lệch −30 ticks trước lượng tử hóa; sau đó đều nằm đúng frame boundary.

## Candidate change points

| Candidate | Tick / frame | Khung trước / tại / sau trong recording | Phân loại | Confidence | Cách biểu diễn trong 0.5 |
|---:|---:|---|---|---|---|
| 0.000 s | 0 / 0 | 0.000 s; source in-point không biết | Start state / UNKNOWN về source in-point | Thấp cho in-point; cao graphic nhìn thấy | Background Opening bắt đầu ở tick 0; không gọi là cut đã xác minh |
| 3.767 s | 339,000 / 113 | 3.700 / 3.767 / 3.833 s | OVERLAY_REPLACEMENT có khả năng cao hơn background cut | Trung bình | Background Opening giữ nguyên; overlay `pour` bắt đầu |
| 5.267 s | 474,000 / 158 | 5.200 / 5.267 / 5.333 s | OVERLAY_REPLACEMENT có khả năng cao hơn background cut | Trung bình | Cùng background; overlay `basket` thay nội dung |
| 5.767 s | 519,000 / 173 | 5.700 / 5.767 / 5.833 s | Likely BACKGROUND_CUT | Trung bình–cao | Background Autumn Park bắt đầu |
| 6.767 s | 609,000 / 203 | 6.700 / 6.767 / 6.833 s | OVERLAY_REPLACEMENT | Trung bình | Background Autumn Park giữ nguyên; overlay `park-figure` bắt đầu |
| 9.267 s | 834,000 / 278 | 9.200 / 9.267 / 9.333 s | OVERLAY_REPLACEMENT | Trung bình | Autumn Park giữ nguyên đến 9.767s; overlay `coffee-close` |
| 9.767 s | 879,000 / 293 | 9.700 / 9.767 / 9.833 s | Likely BACKGROUND_CUT và overlay replacement gần đồng thời | Trung bình | Background Picnic và overlay `picnic-transition` cùng bắt đầu; layer split chưa chắc chắn |
| 10.267 s | 924,000 / 308 | 10.200 / 10.267 / 10.333 s | OVERLAY_REPLACEMENT | Trung bình | Background Picnic giữ nguyên; overlay `market-figure` bắt đầu |
| 13.267 s | 1,194,000 / 398 | 13.200 / 13.267 / 13.333 s | UNKNOWN: background cut hay large foreground insert | Thấp–trung bình | `background-food-insert` chỉ là representation pilot có nhãn UNKNOWN |
| 13.767 s | 1,239,000 / 413 | 13.700 / 13.767 / 13.833 s | Likely BACKGROUND_CUT | Trung bình | Background Bouquet Close bắt đầu |
| 15.067 s | 1,356,000 / 452 | Preview cuối bị UI/Control Center che; crop gần nhất không chứng minh nội dung tại đúng mốc | UNKNOWN | Cao về việc thiếu evidence | Không tạo event/cut tại đây |

`Fall_Diary_3_9H_Reference_Comparison.jpg` đặt crop Muse cạnh 0.3, 0.4, Reference Layout QA và Editorial Safe ở các mốc trước/tại candidate. Mốc sau screen recording bị che không được kéo dài thành một frame nguồn giả định.

## Timeline 0.5 pilot

### Backgrounds — layer order 0

| Event | Start / end ticks (nửa mở) | Frame range | Thời lượng | Slot | Nhãn evidence |
|---|---:|---:|---:|---|---|
| `background-opening` | [0, 519,000) | [0, 173) | 5.7667 s | `photo-01` | UNKNOWN source in-point; landmark nền giữ liên tục qua 3.767 và 5.267 |
| `background-autumn-park` | [519,000, 879,000) | [173, 293) | 4.0000 s | `photo-02` | Likely cut tại 5.767 |
| `background-picnic` | [879,000, 1,194,000) | [293, 398) | 3.5000 s | `photo-03` | Likely cut tại 9.767 |
| `background-food-insert` | [1,194,000, 1,239,000) | [398, 413) | 0.5000 s | `photo-04` | UNKNOWN: có thể là shot nền hoặc insert lớn |
| `background-bouquet-close` | [1,239,000, 1,530,000) | [413, 510) | 3.2333 s | `photo-05` | Likely cut tại 13.767 |

### Overlays — layer order 1

| Event | Start / end ticks (nửa mở) | Frame range | Thời lượng | Slot | Evidence |
|---|---:|---:|---:|---|---|
| `overlay-pour-replacement` | [339,000, 474,000) | [113, 158) | 1.500 s | `photo-06` | Nền tree/street có vẻ giữ landmark |
| `overlay-basket-replacement` | [474,000, 609,000) | [158, 203) | 1.500 s | `photo-07` | Replacement bắt đầu trước cut nền 5.767 |
| `overlay-park-figure` | [609,000, 834,000) | [203, 278) | 2.500 s | `photo-08` | Autumn-park giữ nguyên |
| `overlay-coffee-close` | [834,000, 879,000) | [278, 293) | 0.500 s | `photo-09` | Autumn-park giữ nguyên đến candidate 9.767 |
| `overlay-picnic-transition` | [879,000, 924,000) | [293, 308) | 0.500 s | `photo-10` | Bắt đầu cùng candidate nền; layer split confidence trung bình |
| `overlay-market-figure` | [924,000, 1,194,000) | [308, 398) | 3.000 s | `photo-11` | Picnic background giữ nguyên |

Title `FALL / DIARY` được thấy trong crop đến 13.833s, gồm 9 glyph text/vector. End tick 1,530,000 (17s) là pilot assumption, không phải source end đã xác minh. Không dùng screenshot UI Muse làm graphic.

## Tick rounding và event boundaries

Mọi start/end tick trong 0.5 đều là bội số 3,000; không có event boundary nằm giữa frame. Tại cùng một tick có thể có cut nền và thay overlay (9.767s), nhưng hai event vẫn độc lập trong graph. Candidate 13.267s được giữ nhãn UNKNOWN để tránh biến detector thành bằng chứng cut.
