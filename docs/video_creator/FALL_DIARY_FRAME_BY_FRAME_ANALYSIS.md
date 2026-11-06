# Fall Diary — frame by frame analysis

## Phạm vi và phương pháp

Nguồn quan sát là `local_reference/fall_diary/demo/fall_diary_reference.mp4`, một bản quay màn hình Muse dài 15.066667 giây ở 720×1556, H.264/AAC. Video này là bằng chứng hình ảnh cuối cùng, không phải source project editable. Tôi đã kiểm tra hash theo `manifest.json`, probe bằng FFprobe, tạo contact sheet 1 fps và dùng scene-detection để tìm các mốc thay đổi ứng viên. Các mốc dưới đây là mốc quan sát ở cấp screen recording; chúng không phải keyframe gốc.

Trong toàn bộ video, phần chrome của Muse (tiêu đề `FALL DIARY`, nút dùng template và footer) vẫn hiện. Vì vậy không gán chrome đó thành một text layer của template. Demo hiển thị nhiều bố cục ảnh đồng thời, nhưng số layer, source slot, mask, easing và timeline nội bộ không được tiết lộ. `36 clips` trên UI cũng không được suy ra thành 36 media slots.

## Bảng timestamp

| Start | End | Media role | Layers | Transform | Effect | Confidence |
|---:|---:|---|---|---|---|---|
| 00:00.000 | 00:03.767 | Intro / bố cục ảnh đầu | Một nền ảnh và một hoặc nhiều card ảnh nhìn thấy trong preview; Muse chrome luôn ở trên | Card có vị trí, scale và góc riêng; giá trị gốc UNKNOWN | Hold rồi đổi bố cục; không thấy fade chắc chắn | OBSERVED: có thay đổi hình; INFERRED: lớp/card riêng |
| 00:03.767 | 00:05.267 | Bố cục ảnh thứ hai | Nền mới và card overlay | Crop/fit và vị trí card thay đổi | Hard cut ứng viên tại 3.767 s | OBSERVED: hard cut ứng viên; tham số UNKNOWN |
| 00:05.267 | 00:05.767 | Insert/card ngắn | Một card hoặc ảnh foreground thay đổi trên bố cục | Scale/position tĩnh hoặc chuyển động rất ngắn không phân biệt được từ capture | Hard cut ứng viên tại 5.267 s | OBSERVED: thay đổi; UNKNOWN: animation |
| 00:05.767 | 00:06.767 | Insert/card tiếp theo | Nhiều lớp ảnh tiếp tục chồng | Có dấu hiệu crop/scale khác | Hard cut ứng viên tại 5.767 s | OBSERVED: thay đổi; INFERRED: collage |
| 00:06.767 | 00:09.267 | Bố cục ảnh thứ ba | Nền full-frame và card foreground | Vị trí/scale/rotation cụ thể UNKNOWN | Hold; hard cut ứng viên tại 6.767 s | OBSERVED: bố cục giữ trong khoảng |
| 00:09.267 | 00:09.767 | Insert/card ngắn | Card foreground thay đổi | Transform gốc UNKNOWN | Hard cut ứng viên tại 9.267 s | OBSERVED: thay đổi |
| 00:09.767 | 00:10.267 | Insert/card ngắn | Lớp ảnh khác thay thế lớp trước | Transform gốc UNKNOWN | Hard cut ứng viên tại 9.767 s | OBSERVED: thay đổi |
| 00:10.267 | 00:13.267 | Bố cục ảnh thứ tư | Nền full-frame và nhiều card/ảnh đồng thời | Crop/fit/position/scale nhìn thấy; keyframe UNKNOWN | Hold; hard cut ứng viên tại 10.267 s | OBSERVED: multi-layer appearance; INFERRED: static collage |
| 00:13.267 | 00:13.767 | Insert/card ngắn | Card foreground thay đổi | Transform gốc UNKNOWN | Hard cut ứng viên tại 13.267 s | OBSERVED: thay đổi |
| 00:13.767 | 00:15.067 | Bố cục kết | Nền và card ảnh cuối cùng, cùng Muse chrome | Giá trị gốc UNKNOWN | Giữ đến hết bản quay | OBSERVED: kết thúc capture; UNKNOWN: template end timing |

### Những gì chưa thể kết luận từ MP4

- Không thể khôi phục số slot gốc, source timing, keyframe/easing, original mask hoặc foreground cutout.
- Không thể tách chắc text của template khỏi text/chrome của ứng dụng quay màn hình.
- Không xác minh được pan/zoom liên tục, opacity animation hay transition nâng cao ở mức pixel từ bản capture này.
- Audio có trong container reference theo manifest, nhưng quyền sử dụng và nhịp sync của soundtrack không được dùng cho pilot.

Các mốc 2.5 giây trong pilot definition là cấu hình render đầu tiên để kiểm chứng pipeline; chúng không được trình bày như mốc source chính xác của Muse.
