# FALL DIARY — LAYOUT QUALITY MATRIX 3.9I

## Phạm vi

So sánh `reference-layout-v1` (QA-only, vị trí gần Definition 0.3) và `editorial-safe-v1` (Definition 0.5) bằng cùng 11 media bindings. Cùng Definition 0.5, 11 slot, 5 background events, 6 replacement overlays và 9 glyph được dùng cho hai biến thể. Review hình ảnh giới hạn ở sáu frame: 3.767, 5.267, 6.767, 9.267, 10.267 và 13.767 giây. Đây không phải duyệt toàn bộ 510 frame trên nhiều loại media.

## Bảng so sánh

| Tiêu chí | Reference Layout QA | Editorial Safe Layout | Gần Muse hơn |
|---|---|---|---|
| Title readability | Tile FALL/DIARY giữ vị trí giữa ảnh theo bố cục reference. Đọc được ở các frame xem, nhưng chồng vùng mặt/chủ thể ở một số ảnh trong fixture hiện tại. Chưa có annotation để chấm readability theo vùng mặt. | Title nhỏ ở góc trên trái, hai hàng. Ít cạnh tranh với trung tâm ảnh trong các frame xem; khả năng đọc vẫn phụ thuộc nền sáng/tối và chưa được đo tương phản trên fixture đa dạng. | Reference về placement; chưa có chấm điểm độ đọc độc lập. |
| Face overlap | Chưa có face boxes nên không tính phần trăm. Quan sát định tính trên một số frame cho thấy title/card đi qua vùng mặt. | Chưa đo bằng face boxes. Một số frame xem tránh trung tâm mặt tốt hơn, nhưng vị trí cố định không bảo đảm an toàn trên media khác. | Không kết luận từ overlap; Reference giữ placement gần source. |
| Subject occlusion | Không có subject annotation; tỷ lệ occlusion **NOT MEASURED**. | Không có subject annotation; tỷ lệ occlusion **NOT MEASURED**. | Không đánh giá được chỉ bằng bounding box layer. |
| Card position | Vị trí/scale gần bố cục collage nhìn thấy trong reference; có thể đặt nội dung card lên vùng mặt/chủ thể. | Card `contain` nhỏ ở phía dưới bên phải; rõ ràng là lựa chọn editorial, không phải phục dựng Muse. Vẫn có thể đè lên chủ thể nằm ở góc đó. | Reference. |
| Landscape handling | **FIXTURE_MISSING** — không có ảnh ngang hợp lệ để xem crop, title và card. | **FIXTURE_MISSING** — không có ảnh ngang hợp lệ để xem crop, title và card. | Chưa biết. |
| Portrait handling | Đã xem một bộ ảnh dọc private QA hiện có; profile giữ placement gần source nhưng có overlap quan sát được. | Đã xem cùng bộ ảnh; profile giảm một số chồng lấn trung tâm trong sample nhưng chưa xác minh semantic safe area. | Reference về bố cục, không nhất thiết về độ tiện dụng. |
| Near-Muse placement | Cao hơn theo vị trí tương đối của title/card; không có source project để khẳng định fidelity. | Thấp hơn có chủ đích: title trên trái và card dưới phải khác reference. | Reference Layout QA. |

## Geometry và annotation

- Canvas: 1080×1920; cả hai profile giữ background ở layer order 0, overlay ở 1, title ở 20.
- Với `editorial-safe-v1`, Task 3.9H đã tính geometry từ aspect ratio của fixture: tất cả 20 image/text boxes nằm trong canvas; không có giao nhau hình học giữa title và card.
- Kết quả trên chỉ nói về **layer bounds**, không phải mặt/người. Reference layout không được dùng face detector hay pixel heuristic.
- Không tạo bounding boxes riêng cho ảnh QA thành logic production. Không tuyên bố sản phẩm tự nhận diện chủ thể.

## Quyết định QA

Giữ cả hai profile ở QA/pilot. Không đổi policy mặc định, không thêm lựa chọn UI. Không chọn Editorial Safe làm “tốt nhất” chỉ vì card nhỏ hơn; cần bộ ảnh ngang/đa dạng được phép và annotation mặt/chủ thể để đo chính xác, sau đó cần review mỹ thuật trên cùng bindings.

