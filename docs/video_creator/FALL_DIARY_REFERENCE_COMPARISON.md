# Fall Diary — reference comparison 3.9A / 3.9B

## Phạm vi bằng chứng

Reference là screen recording Muse dài khoảng 15.067 s ở 720×1556, không phải source project. Muse title/chrome và footer xuất hiện trong capture; không coi chúng là nội dung template. Nút Use template, watermark/chrome và Control Center cuối bản quay không được dùng trong output. Video không tiết lộ slot ID, keyframe, easing, mask, crop gốc hay thứ tự timeline có thể chỉnh sửa.

Các mốc scene sau đây là ứng viên quan sát từ screen recording. Event 2.5 giây của 3.9A/3.9B là timeline pilot để kiểm thử, không phải các mốc reference.

| Time quan sát ở reference | Background role | Overlay role | Text | Motion | Transition | Evidence / confidence |
|---|---|---|---|---|---|---|
| 0.000–3.767 s | Ảnh nền/ảnh chính thấy trong preview | Một hoặc nhiều card ảnh | `FALL DIARY` xuất hiện, nhưng app chrome luôn tồn tại nên nguồn chữ là UNKNOWN | Card có hình học riêng; nội suy liên tục không thể xác định | Hold rồi đổi bố cục; fade không xác nhận | Multi-layer appearance OBSERVED; layer semantics INFERRED; keyframes UNKNOWN |
| 3.767–5.267 s | Background mới | Card/ảnh foreground thay đổi | UNKNOWN | Crop/position khác; motion liên tục UNKNOWN | Hard cut ứng viên | Thay đổi hình OBSERVED; tham số UNKNOWN |
| 5.267–6.767 s | Nền tiếp tục thay đổi | Insert/card ngắn, nhiều lớp | UNKNOWN | UNKNOWN | Các hard cut ứng viên tại 5.267/5.767/6.767 s | Mốc scene-detection OBSERVED, không phải timing gốc |
| 6.767–9.267 s | Nền full-frame | Card foreground | UNKNOWN | Vị trí/scale có thể thấy; keyframe không khôi phục được | Hold ứng viên | Bố cục OBSERVED; transform nguồn UNKNOWN |
| 9.267–10.267 s | Thay đổi ảnh/nền theo insert | Insert/card ngắn lần lượt | UNKNOWN | UNKNOWN | Hard cut ứng viên tại 9.267/9.767/10.267 s | Thay đổi hình OBSERVED, nhịp chính xác có thể bị ảnh hưởng bởi screen recording |
| 10.267–13.267 s | Nền full-frame mới | Nhiều card đồng thời | UNKNOWN | Crop/scale/position khác; keyframe UNKNOWN | Hold ứng viên | Multi-layer appearance OBSERVED; collage semantics INFERRED |
| 13.267–15.067 s | Nền/ảnh cuối | Card cuối; UI Muse vẫn hiện | Text/chrome không thể tách chắc chắn | UNKNOWN | Hard cut ứng viên 13.267/13.767 s rồi hold đến capture end | End time của template UNKNOWN; cuối MP4 là capture end OBSERVED |

## So sánh ba bản

| Hạng mục | Muse reference | 3.9A (`0.1.0-pilot`) | 3.9B (`0.2.0-motion-pilot`) |
|---|---|---|---|
| Nhịp cut | Nhiều insert ngắn; candidate cuts 3.767, 5.267, 5.767, 6.767, 9.267, 9.767, 10.267, 13.267, 13.767 s | 6 cảnh đều 2.5 s / hard cut | 6 event đều 2.5 s / hard cut; được chọn làm nhịp QA, không phải căn lại theo demo |
| Độ dài layout | Thay đổi không đều theo recording | 2.5 s cố định | 2.5 s cố định |
| Số layer nhìn thấy | Nền + card/multiple card ở một số cảnh; UI chrome bị loại | Hai visual layer lặp lại ở 6 event | Visual layer theo event: 2, 3, 3, 2, 4, 3 |
| Text graphic | Một title nhìn thấy, nguồn template/UI không chắc | Một dòng text Arial trắng qua toàn 15 s | Hai text tile độc lập có nền, viền/shadow, dùng system Arial |
| Animation | Không thể kết luận từ screen recording | Không có keyframes | Linear motion X/Y/scale/rotation/opacity thực, tạo mới để QA |
| Cutout | Mask gốc không quan sát được | Không có | Không có; alpha input ≠ segmentation |
| Transition | Hard cut ứng viên; fade/wipe chưa xác nhận | Hard cut | Hard cut |
| Audio | AAC trong capture; quyền/timing nhạc không rõ | Không có | Tone 440 Hz tổng hợp để test pipeline; không dùng nhạc demo |
| Media thay thế | Source template không có | 12 private images, dùng mỗi ảnh một lần | 12 private images; reuse policy allow; test thêm 12 graphic fixtures khác |
| Technical correctness | N/A | 15 s, 30 fps, full decode PASS theo 3.9A report | 15 s, 450 frame, full decode/FFprobe PASS; preview+export AAC 15 s |
| Motion correctness | UNKNOWN | Chưa hỗ trợ | Có nội suy liên tục, kiểm tra 3 timestamp trong cùng event; khác reference là chủ ý |
| Layout/effect fidelity | Nguồn gốc không thể khôi phục đầy đủ | Thấp/trung bình; bố cục lặp | Đa dạng hơn và có motion; vẫn là pilot, không có cutout, chưa reference-match |
| Preview/export parity | Không áp dụng | 3.9A mean SSIM 0.932965 / min 0.886313 | Mean SSIM 0.904437 / min 0.809201; 8 exact-frame same-resolution sample mean MAE 5.4952/255 |

Không chạy SSIM giữa demo và output làm tiêu chí chính vì source media khác nhau và capture có app chrome. Chưa có một điểm tổng hoặc tỷ lệ phần trăm “giống Muse”. Kết luận reference fidelity vẫn **false**.
