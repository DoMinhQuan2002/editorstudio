# FALL DIARY — REFERENCE VS SAFE LAYOUT 3.9I

## Mục tiêu và phương pháp

Đặt hai biến thể 0.5 cạnh nhau với cùng Project inputs, cùng 11 slot bindings và cùng timeline:

- **Reference Layout QA**: chỉ dùng trong QA; vị trí title/card kế thừa bố cục gần Definition 0.3. Không sửa Definition baseline hoặc catalog.
- **Editorial Safe Layout**: `editorial-safe-v1` trong Definition 0.5; title góc trên trái, card nhỏ ở dưới phải.

Cả hai dùng shared Template Compiler, Project V2 và Composition Graph. Contact sheet có crop Muse và frame của 0.3, 0.4, 0.5 Reference Layout QA, 0.5 Editorial Safe tại sáu thời điểm. Mỗi preview 540×960, 30 fps, 17 giây; hai profile 0.5 có export 1080×1920 tương ứng. Không so SSIM với Muse vì ảnh nguồn không cùng nội dung.

## Kết quả

Reference Layout gần Muse hơn về vị trí và tỉ lệ tương đối của graphic/card. Đây không chứng minh chuyển động hoặc nội dung giống source; card/image bindings là fixture QA khác với Muse.

Editorial Safe tạo ngôn ngữ bố cục khác, nhỏ và lệch về mép hơn. Trong các frame xem, title không chiếm trung tâm như Reference Layout. Card nhỏ hơn nhưng có thể vẫn che mặt/người ở góc dưới phải. Không có face/subject annotation, nên không có tỷ lệ overlap để khẳng định mức cải thiện.

| Khía cạnh | Nhận xét |
|---|---|
| Placement gần Muse | Reference cao hơn; Safe khác có chủ đích. |
| Đọc chữ | Cả hai đọc được trong một số frame; chưa đo độ tương phản/nền phức tạp trên fixture đa dạng. |
| Face/subject overlap | Chưa đo hình học do không có annotation; quan sát contact sheet chỉ dùng làm cảnh báo định tính. |
| Card occlusion | Safe nhỏ hơn; Reference gần bố cục source hơn. Cả hai có thể giao với subject. |
| Ảnh ngang | Chưa có fixture hợp lệ; kết quả crop/layout là `FIXTURE_MISSING`. |
| Product policy | Không đổi default và không thêm UI option trong Task 3.9I. |

## Khuyến nghị

Giữ hai profile là QA variants cho người dùng review. Không gọi Editorial Safe là face-aware hoặc universally safe. Nếu người dùng ưu tiên likeness, chọn Reference Layout làm điểm tham chiếu; nếu ưu tiên bố cục editorial gọn, review Safe trên fixture đa dạng trước khi quyết định. Không tạo Definition 0.6 chỉ để ghi nhận một lựa chọn bố cục chưa được nghiệm thu.

## Đầu ra

- [Contact sheet 6 mốc](../../artifacts/video_creator/task3_9i/Fall_Diary_3_9I_Comparison_Contact_Sheet.jpg)
- [Reference Layout QA preview](../../artifacts/video_creator/task3_9i/Fall_Diary_3_9I_0_5_Reference_Layout_QA_Preview.mp4) và [export](../../artifacts/video_creator/task3_9i/Fall_Diary_3_9I_0_5_Reference_Layout_QA_Export.mp4)
- [Editorial Safe preview](../../artifacts/video_creator/task3_9i/Fall_Diary_3_9I_0_5_Editorial_Safe_Preview.mp4) và [export](../../artifacts/video_creator/task3_9i/Fall_Diary_3_9I_0_5_Editorial_Safe_Export.mp4)

