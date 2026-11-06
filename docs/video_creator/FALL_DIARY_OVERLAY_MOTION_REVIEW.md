# FALL DIARY — OVERLAY MOTION REVIEW 3.9I

## Cách diễn giải

Nguồn là screen recording Muse, không phải source timeline. Frame crop chứng minh những gì nhìn thấy trong preview tại timestamp, không chứng minh transform/keyframe của template. Không phân loại chuyển động của footage/camera thành animation overlay. Không thêm animation vào Definition 0.5.

## Các khoảng yêu cầu

| Khoảng | Quan sát frame/candidate | Phân loại QA | Confidence và giới hạn |
|---|---|---|---|
| 3.767–5.267s | Nội dung foreground/card đổi; các landmark nền đầu đoạn có vẻ còn liên tục. Có replacement ở 5.267s. | **Content replacement only**; transform overlay **UNKNOWN**. | Trung bình về việc nội dung đổi; thấp về transform. |
| 5.267–5.767s | Basket/collage ở 5.267s; candidate background cut ở 5.767s. Không có keyframe riêng biệt được thấy rõ. | **Content replacement only**, sau đó **likely background cut**; overlay motion **UNKNOWN**. | Trung bình–cao về background change, thấp về motion. |
| 6.767–9.267s | Cảnh park giữ chủ đề nền; insert/card thay đổi gần 9.267s. Chuyển động trong footage không tách được khỏi layer. | **Possible editorial animation / UNKNOWN**; chỉ xác nhận content replacement, không xác nhận transform. | Trung bình về nội dung đổi; thấp về animation. |
| 9.267–9.767s | Foreground insert đổi; một background change có khả năng xảy ra ở 9.767s. | **Content replacement only** trước likely cut; overlay motion **UNKNOWN**. | Trung bình. |
| 9.767–10.267s | Background và foreground thay đổi gần cùng một mốc; layer split của source chưa rõ. | **Unknown** giữa background cut và simultaneous content replacement; không tuyên bố chuyển động. | Trung bình về visible change, thấp về phân lớp source. |
| 10.267–13.267s | Replacement mới xuất hiện ở 10.267s; candidate 13.267s là chuyển sang cận cảnh đồ ăn nhưng chưa tách được background cut khỏi large foreground insert. | **Content replacement only** ở đầu đoạn; **UNKNOWN** tại 13.267s; motion overlay chưa xác minh. | Trung bình/thấp theo từng candidate. |

Title `FALL / DIARY` nhìn ổn định trong các crop đã lấy mẫu, nên chỉ có thể ghi **static overlay trong các frame sample** với confidence trung bình. Điều đó không loại trừ motion nhỏ giữa sample. Với card/insert, không đủ căn cứ để xếp chúng vào nhóm “observed movement” của template.

## Editorial proposal

Chưa đề xuất motion editorial mới. Trước khi thiết kế proposal cần fixture được duyệt, quyết định mỹ thuật từ người dùng và review trên cùng binding. Definition 0.5 hiện giữ overlay tĩnh; scale nền 1.0→1.012 vẫn được đánh dấu `EDITORIAL_MOTION`, không phải motion Muse.

## Candidate chưa kết luận

- **13.267s:** giữ `UNKNOWN`; không đổi event `background-food-insert` thành shot/cut hoặc overlay insert.
- **Title end-time:** graphic nhìn thấy ít nhất đến 13.833s; recording bị che sau đó. Mốc 17s chỉ là pilot assumption.
- **15.067s:** vùng preview bị UI/Control Center che; không dùng làm bằng chứng event.

