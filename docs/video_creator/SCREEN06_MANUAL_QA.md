# Screen 06 — manual QA

## WPF runtime đã chạy

| Bước | Kết quả |
|---|---|
| Mở Media Studio và kết nối backend | PASS |
| Mở Project V2 đã lưu `3421002bb44a434e866c5213b2938cd8` / revision 1 | PASS |
| Preview Screen 5 mở và xác minh 15 giây | PASS |
| Chuyển sang Screen 6 | PASS |
| Phát preview cùng revision | PASS |
| Độ phân giải/fps/format lấy từ capability thật | PASS: 1080×1920, 30/1, MP4/H.264 |
| Đổi filename và output directory | PASS |
| Nhấn Export tạo backend job thật | PASS: `7625b9e5ced642f09f6c7f63a16cc931` |
| Progress phản ánh job; 100% sau verify/publish | PASS |
| Success panel path/resolution/duration/size | PASS |
| FFprobe và full decode file từ job UI | PASS |
| Quay lại Screen 5 | PASS: Project ID context, revision 1, 5 cảnh và status preview còn nguyên |
| Viewport | PASS tại 1427×744 |

Screenshot:

- Settings/runtime: `artifacts/video_creator/task3_7/SCREEN06_runtime.jpg`
- Export success: `artifacts/video_creator/task3_7/SCREEN06_runtime_success.jpg`

Log/history:

- Backend log: `artifacts/video_creator/task3_7/runtime_backend.log`
- Export history: `artifacts/video_creator/task3_7/runtime_workspace/video_editor/export_history/3421002bb44a434e866c5213b2938cd8.json`

## Automated results

- WPF build: 0 warnings, 0 errors.
- WPF tests: 54/54 passed.
- Backend Task 3.3–3.7 suite: 30 passed, 1 deprecation warning.
- Task 3.7 test file: 3 passed, gồm API validation, idempotency, real export/FFprobe/full decode/parity.
- Runtime GUI export: file 220,361 bytes, MP4/H.264 1080×1920 30 fps, 15s; full decode pass.
- Runtime preview/export parity (1/7/13s): MAE RGB 1.404/1.133/0.993 sau khi resize output 1080×1920 về proxy 540×960.

## Còn cần kiểm tra

- Ma trận kích thước 1366×768, 1600×900, 1920×1080 và DPI.
- AAC export với project có audio; AAC sync/mute/volume.
- Existing file confirmation, locked destination, no-write permission, disk full, user cancel, FFmpeg unavailable, renderer error, retry sau failure và backend process restart.
- Nhiều loại source video/motion/alpha và template transition.
- Full Gallery → Details → Media Selection → Processing → Draft Preview → Export runtime; chưa đặt gate end-to-end/release thành true.
