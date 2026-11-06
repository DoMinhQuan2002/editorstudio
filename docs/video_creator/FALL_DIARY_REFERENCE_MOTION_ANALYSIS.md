# FALL DIARY — REFERENCE MOTION ANALYSIS 3.9G

## Nguồn và cách cô lập

Nguồn là screen recording Muse 720×1556, không phải project/template nguồn. Chỉ crop preview x=0…720, y=0…1215 từ bộ frame đã cô lập ở TASK 3.9C. Header, thanh thông tin, nút Use template, bookmark, nút đóng và home indicator không thuộc nội dung video. Ô đen nhỏ tại gần x=24…82, y=91…163 là mask của nút đóng ứng dụng và không được đưa vào output.

Khung hình Muse dùng trong đối chiếu có timestamp trong [reference_frames/isolated](../../artifacts/video_creator/task3_9c/reference_frames/isolated/). Đối chiếu mới ở [Fall_Diary_3_9G_Reference_Comparison_Contact_Sheet.jpg](../../artifacts/video_creator/task3_9g/Fall_Diary_3_9G_Reference_Comparison_Contact_Sheet.jpg). Hàng so sánh ghi thời điểm Muse gần nhất với frame video pilot. Tại 16.5s không có crop tham chiếu riêng; nearest visible crop vẫn là 13.833s. Không coi nó là frame Muse tại 16.5s.

## Mốc quan sát và loại thay đổi

Timestamp là screen-recording time của candidate detector. Tick được quy đổi bằng 90,000 ticks/s rồi căn frame 30 fps gần nhất. Mỗi tick căn đều bội số 3,000. Giá trị thô 3.767s tương ứng 339,030 ticks, làm tròn thành 339,000, lệch -30 ticks (-0.333ms); các candidate ba chữ số khác có cùng sai lệch.

| Candidate | Tick / frame | Quan sát được trong preview | Phân loại | Confidence |
|---:|---:|---|---|---|
| 0.000s | 0 / 0 | Mở đầu recording; title tile FALL DIARY nằm trong video preview. | Start state; source in-point chưa rõ | Thấp về in-point; cao về graphic nhìn thấy |
| 3.767s | 339,000 / 113 | Nội dung/layer nhỏ đổi trong khi nền còn liên tục. | Confirmed visible change; likely overlay replacement | Trung bình |
| 5.267s | 474,000 / 158 | Card/insert đổi nội dung. | Confirmed visible change; likely overlay replacement | Trung bình |
| 5.767s | 519,000 / 173 | Nền preview thay đổi rõ. | Confirmed visible change; likely cut | Trung bình–cao |
| 6.767s | 609,000 / 203 | Layer/card đổi. | Confirmed visible change; likely overlay replacement | Trung bình |
| 9.267s | 834,000 / 278 | Insert/card đổi trong preview. | Confirmed visible change; likely overlay replacement | Trung bình |
| 9.767s | 879,000 / 293 | Nền preview khác. | Confirmed visible change; likely cut | Trung bình |
| 10.267s | 924,000 / 308 | Collage/layer đổi. | Confirmed visible change; likely overlay replacement | Trung bình |
| 13.267s | 1,194,000 / 398 | Hình nền/cỡ cảnh đổi. | Confirmed visible change; likely cut | Trung bình |
| 13.767s | 1,239,000 / 413 | Cảnh mới xuất hiện. | Confirmed visible change; likely cut | Trung bình |
| 15.067s | 1,356,000 / 452 | Control Center và lớp UI che/mờ vùng preview. | Unknown; không dùng làm cut | Cao về việc không đủ bằng chứng |

## Các đoạn liên tiếp

| Time range | Visual layers nhìn thấy | Observed changes | Motion evidence | Confidence |
|---|---|---|---|---|
| 0.000–3.767s | Footage nền + title tile; có thể có layer nhỏ tùy frame | Graphic title giữ nguyên; chưa thấy candidate replacement | Chuyển động trong nền thuộc footage quay lại; không chứng minh template transform | Cao về title, thấp về nguồn motion |
| 3.767–5.267s | Nền tiếp tục, insert/card đổi | Layer nhỏ thay nội dung | Không đủ bằng chứng về vị trí/scale/opacity keyframe của layer | Trung bình |
| 5.267–5.767s | Card/insert mới trên nền | Card thay nội dung trước candidate nền | Không xác định được chuyển cảnh ngoài replacement | Trung bình |
| 5.767–6.767s | Nền mới + title | Candidate nền đổi | Có thay ảnh; không tách được cut gốc khỏi screen-record cadence | Trung bình–cao |
| 6.767–9.267s | Nền + collage/layer | Insert đổi quanh 9.267s | Không xác nhận chuyển động riêng của overlay; footage có chuyển động | Trung bình |
| 9.267–9.767s | Insert khác; nền chuyển tiếp | Overlay/content replacement rồi nền đổi | Không suy thành animation liên tục | Trung bình |
| 9.767–10.267s | Nền mới + title | Candidate nền đổi | Chỉ xác nhận khác frame/cảnh | Trung bình |
| 10.267–13.267s | Nền + card/collage thay đổi | Layer collage đổi | Không có tracking đủ tin cậy cho keyframe nguồn | Trung bình |
| 13.267–13.767s | Hình/cỡ cảnh khác | Candidate cut-like change | Không thấy transition effect có thể khôi phục chắc chắn | Trung bình |
| 13.767–15.067s | Cảnh mới + title; cuối bị UI che | Scene state đổi rồi preview bị che/mờ | Chuyển động cuối không phân loại được | Thấp ở phần cuối |

## Graphic FALL DIARY

FALL DIARY gồm hai hàng tile ký tự F A L L và D I A R Y; nó xuất hiện bên trong vùng preview, không ở header/footer Muse. Tile graphic giữ nguyên qua nhiều cảnh, nên nhận định “graphic thuộc nội dung video” có confidence cao. Không dùng screenshot Muse làm asset.

Vị trí giữa khung, kích thước tương đối, màu tile sáng, ký tự tối, viền và bóng có thể ước lượng từ crop. Font độc quyền không được xác định. Graphic nhìn thấy tới ít nhất 13.833s; thời điểm biến mất không xác minh được do cuối recording bị che. Version 0.4 giữ tile 17s theo duration metadata để kiểm thử, đây là lựa chọn pilot, không phải chứng minh title nguồn kéo dài 17s.

## Kết luận motion

Các thay đổi nội dung nền/card được nhìn thấy; các keyframe gốc của template không thể khôi phục từ screen recording. Chuyển động liên tục trong frame có thể là chuyển động của source footage hoặc chuyển động của recording. Vì vậy:

- FALL_DIARY_REFERENCE_MOTION_ANALYZED=true: đã xem và phân loại các candidate.
- FALL_DIARY_REFERENCE_MOTION_VERIFIED=false: không xác minh được transform keyframe nguồn.
- Definition 0.4 chỉ gắn nhãn editorial cho slow push-in và card motion.
- Không suy luận transition easing, cutout, soundtrack hay title end-time.
