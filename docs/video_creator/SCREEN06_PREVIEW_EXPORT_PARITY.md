# Screen 06 — preview/export parity

Parity phải so đúng revision/fingerprint, không đòi byte-level bằng preview proxy.

## Runtime GUI fixture

Project `3421002bb44a434e866c5213b2938cd8`, revision 1, denim-story, là draft WPF mở ở Screen 5 rồi handoff Screen 6. Screen 5 preview cache là 540×960; output là 1080×1920. Script `artifacts/video_creator/task3_7/verify_gui_export_parity.py` lấy các frame tại 1, 7, 13 giây, resize output Lanczos về proxy size và tính mean RGB absolute error trên thang 0–255.

| Timestamp | MAE RGB |
|---:|---:|
| 1s | 1.404 |
| 7s | 1.133 |
| 13s | 0.993 |

Ngưỡng được công bố là <18. PNG mẫu được lưu trong `artifacts/video_creator/task3_7/gui_export/parity_frames/`.

## Backend integration fixture

`test_screen06_real_export_is_probeable_decodable_and_tracks_preview` so frame preview Composition Graph ở 1/7/13s với frame output cùng thời điểm, cùng kích thước 1080×1920, và assert mean RGB difference <18. Test chạy thật FFmpeg/FFprobe, full decode và pass trong suite Task 3.3–3.7.

## Phạm vi kết luận

Runtime sample lặp cùng ảnh tĩnh qua năm cảnh, có text layer, không có audio. Ba frame xác nhận visual parity cho fixture này; chưa nghiệm thu video chuyển động, nhiều nguồn khác nhau, alpha/cutout, transition đa track hoặc audio sync. Transition khác `cut` hiện bị graph validation từ chối.
