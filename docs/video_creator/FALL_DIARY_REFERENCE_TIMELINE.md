# FALL DIARY — REFERENCE TIMELINE

## Phạm vi và vùng tham chiếu

Nguồn Muse là screen recording 720×1556, không có source project. Chỉ dùng vùng video preview x=0…720, y=0…1215 để xem nội dung. Header, avatar/metadata, nút Use template, bookmark, nút đóng, home indicator và Control Center được xem là UI của ứng dụng. Góc đóng ở phía trên preview được che/mờ trong một số frame nên không dùng để suy luận đồ họa video.

Khung hình cô lập theo timestamp và contact sheet: `artifacts/video_creator/task3_9c/reference_frames/isolated/`, `artifacts/video_creator/task3_9c/Fall_Diary_Reference_Isolated_Timestamp_ContactSheet.jpg`. Khung trước/sau candidate cũng có trong `reference_frames/`.

## Candidate change points

Timestamp detector là screen-recording time. Ticks tính bằng `round(timestamp × 90000)` rồi lượng tử hóa về frame 30 fps gần nhất (3.000 ticks/frame). Bảng ghi nhận thay đổi nhìn thấy, không coi detector là bằng chứng độc lập cho cut.

| Candidate (s) | Tick sau frame alignment | Frame | Quan sát và phân loại | Confidence |
|---:|---:|---:|---|---|
| 0.000 | 0 | 0 | Trạng thái nội dung mở đầu; source start, không phải cut đã biết. | Thấp về điểm bắt đầu nguồn |
| 3.767 | 339,000 | 113 | **Confirmed visible change**; thumbnail/layer nhỏ đổi, **likely overlay replacement**. | Trung bình |
| 5.267 | 474,000 | 158 | **Confirmed visible change**; card thay nội dung, **likely overlay replacement**. | Trung bình |
| 5.767 | 519,000 | 173 | **Confirmed visible change**, nền đổi; **likely cut**. | Trung bình–cao |
| 6.767 | 609,000 | 203 | **Confirmed visible change**; card/layer thay, **likely overlay replacement**. | Trung bình |
| 9.267 | 834,000 | 278 | **Confirmed visible change**; insert/card đổi, **likely overlay replacement**. | Trung bình |
| 9.767 | 879,000 | 293 | **Confirmed visible change**, nền khác; **likely cut**. | Trung bình |
| 10.267 | 924,000 | 308 | **Confirmed visible change**; layer collage thay, **likely overlay replacement**. | Trung bình |
| 13.267 | 1,194,000 | 398 | **Confirmed visible change**, hình nền/cỡ cảnh đổi; **likely cut**. | Trung bình |
| 13.767 | 1,239,000 | 413 | **Confirmed visible change**, kết cảnh mới; **likely cut**. | Trung bình |
| 15.067 | 1,356,000 | 452 | **Unknown**. Screen recording đã hiện Control Center; không phân loại thành cut nội dung. | Cao về trạng thái unknown |

Các tick candidate được dùng đều chia hết cho 3.000, nên không có sai lệch frame sau alignment. Ví dụ 3.767 s tương ứng 339,030 ticks thô; nearest frame là 339,000 (113), lệch −30 ticks = −0.333 ms. Các candidate còn lại có cùng hiệu chỉnh −30 ticks do timestamp detector làm tròn ba chữ số.

## Timeline pilot được biên dịch

Thời lượng 17.000 giây lấy từ metadata hiển thị của template trong Muse, không được xác minh là duration của source video. Timeline có 510 frame ở 30 fps và 1,530,000 ticks. Năm background event tạo thành các đoạn liên tục; overlay event được định thời độc lập.

| Event | Start tick | Duration tick | Thời lượng | Frame range nửa mở |
|---|---:|---:|---:|---:|
| Background Opening | 0 | 519,000 | 5.7667 s | [0, 173) |
| Background Autumn Park | 519,000 | 360,000 | 4.0000 s | [173, 293) |
| Background Picnic | 879,000 | 315,000 | 3.5000 s | [293, 398) |
| Background Food Insert | 1,194,000 | 45,000 | 0.5000 s | [398, 413) |
| Background Bouquet Close | 1,239,000 | 291,000 | 3.2333 s | [413, 510) |

| Overlay event | Start tick | Duration tick | Thời lượng | Gợi ý quan sát |
|---|---:|---:|---:|---|
| Overlay Pour Replacement | 339,000 | 135,000 | 1.500 s | Thay card/layer ngắn |
| Overlay Basket Replacement | 474,000 | 135,000 | 1.500 s | Thay card trước cut nền |
| Overlay Park Figure | 609,000 | 225,000 | 2.500 s | Collage trên nền park |
| Overlay Coffee Close | 834,000 | 45,000 | 0.500 s | Insert rất ngắn |
| Overlay Picnic Transition | 879,000 | 45,000 | 0.500 s | Overlay đổi tại cut nền |
| Overlay Market Figure | 924,000 | 270,000 | 3.000 s | Layer collage kéo dài |

Title graphic có duration pilot 17 giây để giữ liên tục trong definition. Quan sát được xác nhận đến 13.833 giây; việc giữ title đến 17 giây là suy luận vì phần sau bị UI che và metadata không xác minh điểm kết video. Không dùng audio Muse.

## Cô lập graphic chữ

`FALL DIARY` xuất hiện bên trong preview, gồm hai hàng ô chữ đơn: `F A L L` và `D I A R Y`. Bằng chứng nhìn thấy qua nhiều cảnh, độ tin cậy cao đến 13.833 giây. Không đưa Muse UI, nút điều khiển hoặc nhãn ứng dụng vào output.

Definition dùng text/vector renderer nội bộ: 9 text layers, chữ tối, tile sáng, viền tối 3 px, shadow (3,4), hai hàng tại y=0.57 và 0.615, mỗi layer có `layerOrder=20`. Font Arial là fallback thông dụng, không phải font độc quyền. Tọa độ/kích thước là pilot gần đúng từ crop; thời điểm kết thúc còn uncertainty. Không tuyên bố khớp pixel với Muse.
