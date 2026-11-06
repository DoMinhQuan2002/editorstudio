# FALL DIARY — TASK 3.9C REPORT

**Ngày:** 2026-10-23  
**Definition mới:** `fall-diary / 0.3.0-reference-pilot`  
**Phạm vi:** reference timing/layout, definition 0.3, WPF sáu màn hình và QA preview/export. Không triển khai lại renderer/compiler 3.9B, không làm cutout R&D, không đổi User Projects.

## Kết quả

- Definition 0.3 dùng schema chung, Template Compiler hiện có và Composition Graph 90 kHz. Giữ nguyên 0.1.0-pilot và 0.2.0-motion-pilot.
- Reference được xem như screen recording. Các vùng Muse chrome, nút Use template, bookmark, close, home indicator và Control Center không đưa vào video. Graphic chữ `FALL DIARY` bên trong vùng preview được giữ với độ tin cậy cao đến 13.833 giây; điểm kết thúc sau đó vẫn chưa rõ.
- Timeline pilot có 5 background event thời lượng khác nhau, 6 overlay event độc lập và 9 text layer; không còn chia đều 2.5 giây. Mốc detector chỉ được dùng khi khung hình cho thấy thay đổi; mốc 15.067 giây được ghi `Unknown`.
- Đã chạy đường đi WPF thật Gallery → Details → Media Selection → Processing → Preview/Edit → Export. Phiên có Template ID `fall-diary`, 11/11 slot có binding. Thay/xóa rồi gán lại binding được kiểm tra; phiên được giữ sau khi quay lại Details và mở Media Selection lần nữa.
- Export WPF tạo `Fall_Diary_Reference_Pilot_WPF_Export.mp4`, 1080×1920, 30 fps, 17 giây. FFprobe xác nhận H.264; full decode thoát mã 0.
- Bộ harness compiler dùng chung tạo Preview, Render, Project V2, Composition Graph và Manifest. 21 frame preview/export có MAE trung bình 2.77787 RGB, cao nhất 3.21177; SSIM trung bình 0.944925 trên 510 frame. Cả hai file qua probe và full decode. Đây là parity renderer, không phải phép đo fidelity với Muse.
- 12 file nguồn đã được hash trước/sau; không đổi nội dung và không copy vào reusable template definition. WPF QA dùng runtime workspace riêng `artifacts/video_creator/task3_9c/runtime_workspace`.

## Cổng nghiệm thu

| Cổng | Trạng thái | Cơ sở |
|---|---|---|
| `FALL_DIARY_0_3_DEFINITION_READY` | **true** | Schema, slots, rules, event/layer definitions load và compile bằng compiler chung; tests 0.1/0.2 vẫn qua. |
| `FALL_DIARY_REFERENCE_TIMING_REVIEWED` | **true** | Mỗi candidate được đối chiếu khung hình trước/sau; mốc uncertain không bị nâng thành cut đã xác minh. |
| `FALL_DIARY_LAYOUT_QA_VERIFIED` | **true, giới hạn hình học** | Bounds, safe area, text zone, event placement và overlap theo layer order đều nằm trong canvas; không có nhận diện chủ thể để cam kết tránh mặt cho ảnh bất kỳ. |
| `FALL_DIARY_MOTION_VERIFIED` | **false** | Definition 0.3 không có keyframe. Reference hiện không đủ bằng chứng để khôi phục motion cụ thể. |
| `FALL_DIARY_SIX_SCREEN_GUI_VERIFIED` | **true** | Đã thao tác và quan sát sáu màn hình WPF runtime, bao gồm processing job, draft Preview và export MP4. |
| `FALL_DIARY_PREVIEW_EXPORT_PARITY_VERIFIED` | **true cho pipeline compiler 0.3** | 21 frame so sánh still preview/render và SSIM 510 frame đạt ngưỡng; WPF draft/export dùng cùng revision/Composition Graph fingerprint. |
| `FALL_DIARY_REFERENCE_FIDELITY_VERIFIED` | **false** | Thời lượng nguồn chưa xác minh, keyframe/motion chưa khôi phục, ending/title timing còn giả định, không có cutout hoặc audio đã xác minh. |
| `FALL_DIARY_READY_FOR_USERS` | **false** | Đây là reference pilot; thiếu demo/poster được cấp phép và còn các blocker motion/cutout/audio/fidelity. |

## Kiểm thử và thay đổi

- `dotnet build MediaStudio.sln --no-restore`: thành công, 0 warning, 0 error.
- `dotnet test MediaStudio.sln --no-restore`: 55 passed, 0 failed.
- Backend test matrix chạy lại: 30 passed, 0 failed; 1 deprecation warning của Starlette/AnyIO (`test_media_selection_task33.py`, `test_template_compiler_task34.py`, `test_video_editor_project_v2_api_task21.py`, `test_fall_diary_task39c.py`).
- Harness 3.9C: variable timings, slot bindings/reuse, compiler graph, still parity, SSIM, FFprobe/full decode và hash nguồn thành công.
- Matrix: tương thích 0.1/0.2, 0.3, short overlay, keyframe contract, reuse/missing/wrong-kind, layer order/text/bounds và project migration có test. Denim Story regression nằm trong test mapping/catalog và WPF suite. GUI sáu màn hình Fall Diary được kiểm tra thủ công; Image Tools không thay đổi vì không sửa shared Image Tools components.
- Source thay đổi: đăng ký version trong `media_selection.py`; Catalog lấy metadata/slot từ 0.3 và không gắn demo Muse; Details/Gallery hiển thị trạng thái pilot và requirements thật; slot không bịa thời lượng; thêm definition và test 3.9C; harness QA dùng renderer chung.
- Không sửa Màn 2 ngoài cập nhật hiển thị thông tin cần thiết của pilot, không thêm NLE, không tạo Project V2 lúc chỉ mở Màn 3, không dùng Muse UI làm asset.

## Blocker và đề xuất tiếp

- `FALL_DIARY_CUTOUT_VERIFIED=false`; không có segmentation/cutout.
- `FALL_DIARY_AUDIO_FIDELITY_VERIFIED=false`; không dùng soundtrack Muse. WPF export hiện không có audio stream.
- `REFERENCE_FIDELITY_VERIFIED=false`; title được thấy ổn định qua 13.833 giây nhưng thời điểm kết thúc video/reference không được chứng minh.
- Không có video fixture được cấp cho QA này; 0.3 khai báo slot chỉ nhận ảnh. Quy tắc từ chối sai loại và media reuse được kiểm tra bằng backend tests.
- Bước tiếp theo: lấy nguồn Muse có thời lượng/timing đầy đủ hoặc xác nhận editorial timing; xin asset quyền sử dụng (poster/demo/audio); sau đó mới hiệu chỉnh title/motion và làm acceptance mới. Giữ pilot chưa phát hành tới lúc đó.

## Tệp kết quả

- Definition: `backend/mediastudio/video_editor/definitions/fall-diary-0.3.0-reference-pilot.json`
- Artifacts compiler và GUI: `artifacts/video_creator/task3_9c/`
- WPF project V2: `artifacts/video_creator/task3_9c/runtime_workspace/video_editor/projects/73da1503e49b403f9ad5c56f7d4d688c.json`
- WPF export record: `artifacts/video_creator/task3_9c/runtime_workspace/video_editor/export_history/73da1503e49b403f9ad5c56f7d4d688c.json`
- Khung tham chiếu cô lập và frame comparison: `Fall_Diary_Reference_Isolated_Timestamp_ContactSheet.jpg`, `Fall_Diary_Reference_vs_0_3_Frame_Comparison.jpg`
