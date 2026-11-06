# FALL DIARY — TASK 3.9E REPORT

**Ngày:** 2026-10-23  
**Trạng thái:** Luồng thay media → cập nhật draft → mở lại → WPF export và kiểm tra parity đã được xác minh trong runtime cô lập.  
**Template:** `fall-diary / 0.3.0-reference-pilot`.

## Kết quả

Task 3.9E hoàn tất việc kiểm tra WPF thật trên runtime riêng `artifacts/video_creator/task3_9e/runtime_workspace`. Media được thay trong Screen 3 qua đường `Thay media` từ Preview/Edit; ứng dụng lưu lại cùng Project V2, tăng revision, mở preview revision mới, rồi xuất MP4 bằng nút Screen 6. Sau khi đóng và khởi động lại WPF, Gallery đọc đúng revision mới; preview được mở lại và export thêm lần nữa.

Không sửa Template Compiler, Composition Graph renderer, schema Project V2, các Definition hay media nguồn. Thay đổi code duy nhất sửa thông tin revision cũ còn lưu trên Gallery sau khi cập nhật draft.

## Root cause của phiên Task 3.9D

Task 3.9D không cung cấp bằng chứng rằng callback thay media từ Screen 5 bị lỗi. Manual QA của D ghi lại nhánh **Details → Media Selection** để tiếp tục draft cũ; nhánh này đi qua `OpenMediaSelectionAsync` và luồng `ContinueToProcessingAsync`. Nó khác với nhánh **Preview/Edit → Thay media** trong `OpenMediaReplacement`, nơi callback gọi `ReplaceMediaAsync` trên Preview hiện tại. Vì vậy, việc D quay về Details không chứng minh return callback của Screen 5 bị lỗi; phiên D chưa hoàn tất đúng đường chỉnh sửa đang được Task 3.9E yêu cầu.

Task 3.9E đã thao tác trực tiếp đường Screen 5 `ReplaceDraftMedia`. WPF giữ Preview hiện tại, gửi binding mới cho cùng Project ID/template/version, lưu qua đường Project V2 hiện có, render preview cho revision tăng và quay về Preview/Edit. Không tạo project mới, không mở NLE cũ, không dùng Demo MP4. Nhánh cập nhật draft cũ không tạo Processing Job mới: nó ghi binding vào Project V2 hiện hữu rồi gọi Composition Graph preview. Processing job khởi tạo project trong baseline 3.9C là `0109d95afa9a443c8dd4d04331152588`; preview Composition job sau lần mở lại r4 là `5d2462dfd9b74f21a4242a21b8cff357`.

Một vấn đề UI phụ được tái hiện: sau khi revision tăng, nhãn draft trên Gallery có thể vẫn hiển thị revision cũ cho tới lần tải catalog tiếp theo. Bản sửa hiện chờ `RefreshLatestSavedDraftAsync()` sau khi thay media lưu thành công. Regression test mới kiểm tra Gallery hiển thị revision mới sau khi tải lại catalog; phiên WPF xác nhận callback thay media làm mới ngay nhãn `r4`.

### Route và trạng thái trước/sau

| Bước | Runtime evidence |
|---|---|
| Gallery / Details | Fall Diary được hiển thị dưới dạng pilot. ID dùng từ DTO là `fall-diary`; phiên bản Definition là `0.3.0-reference-pilot`. |
| Preview/Edit trước chỉnh sửa | Project V2 hiện hữu, Project ID `73da1503e49b403f9ad5c56f7d4d688c`; không tạo project khi chỉ mở màn hình. |
| Screen 5 → Thay media | Màn 3 mở ở chế độ thay media và khôi phục binding đã lưu. Bỏ binding làm validation không cho tiếp tục; gán lại media được chấp nhận. |
| Cập nhật draft | Screen 3 xác thực payload và cập nhật draft hiện tại. Revision r2 → r3 đã được chạy trong WPF; vòng regression sau bản sửa thay `photo-11` bằng `photo_11.jpg`, tăng r3 → r4. |
| Preview/Edit sau cập nhật | WPF hiển thị “Video preview revision 4 đã được mở và kiểm tra thời lượng.” Project ID và template version không đổi; bindings vẫn đủ 11/11. |
| Gallery sau cập nhật | Nút Bản nháp cập nhật ngay thành `Fall Diary Reference Pilot 0.3 · r4`. |
| Save/reopen | Đóng WPF task instance, khởi động lại từ cùng runtime workspace, mở Bản nháp r4 từ Gallery; Project V2 revision 4 và preview được tải lại. |
| Export | Screen 6 xuất `Fall Diary Reference Pilot 0.3 Task3.9E Final.mp4` từ revision 4. WPF báo thành công sau kiểm tra FFprobe và full decode. |

Project ID, template, revision, binding hash và Composition Graph fingerprint đều được lấy từ Project V2/runtime export history của lần chạy này, không lấy giá trị ID/fingerprint cũ của Task 3.9D làm bằng chứng cho revision 4.

## Build được WPF và process runtime

- WPF runtime được chạy từ `artifacts/video_creator/task3_9e/app/MediaStudio.Desktop.exe` (PID 10848 trong phiên export cuối). Cùng lúc còn process PID 5388 chạy từ source `bin`; process cũ không bị đóng hoặc sửa.
- Apphost SHA-256 từ source `bin` và apphost runtime đều bằng `2E360765E399A7075A3F30C8F96A20C16F128EC032FBD6CA2B7B6848B09D31C9`; riêng DLL chứa code khác nhau: source `bin` là `B0CC9C4410D908C5E9FD82AC7B19E2E715B24AE575F075FC83E83B3657B84E52`, isolated publish là `EFFA6457ECC9F506AB0DE0E1E5310261CB97D132C447F461EA00055BAA46ED38`. PID 10848 chạy trực tiếp từ thư mục isolated publish, nên phiên export dùng DLL đã build sau bản sửa; PID 5388 và output mặc định không bị chạm.
- Build và test được chuyển sang `OutDir` cô lập vì process WPF có sẵn giữ file trong output mặc định. Build cô lập thành công; test cô lập kết thúc với 56 passed, 0 failed, 0 skipped.

## WPF export và identity revision 4

| Field | Giá trị |
|---|---|
| Project ID | `73da1503e49b403f9ad5c56f7d4d688c` |
| Project V2 revision | `4` |
| Template ID / Definition | `fall-diary` / `0.3.0-reference-pilot` |
| Schema / timeline | Project V2 schema 2; 1,530,000 ticks / 90,000 = 17 giây |
| Frame rate / binding | 30/1 fps; 11 slot (`photo-01`…`photo-11`) |
| Binding SHA-256 | `e786310979fe6153c179e70221b2f21d2d3e0087af8eab6afdbe322dcb867307` |
| Composition Graph fingerprint | `8653846be39a2f343772d1b971e2dc2b7823a025de278b64ec3a9280a3d566c7` |
| Preview Composition job sau khi mở lại r4 | `5d2462dfd9b74f21a4242a21b8cff357` |
| Export job | `59e7afefebb74f77aa9c9460b7d5254e` — `SUCCEEDED` |
| Export settings | MP4/H.264, 1080×1920, 30 fps, preset Standard; không có audio stream |
| Kích thước MP4 | 3,732,698 byte; duration 17.000 giây |

Slot `photo-11` ở revision 4 liên kết `photo_11.jpg`, asset `1e159a7a4cbe4a2c9e4f2a3eb6bee61a`. So với revision 3, các binding khác không đổi. Runtime metadata và source hashes được lưu trong manifest revision 4.

## Preview / Export parity

Parity được tính giữa preview MP4 lấy từ cache WPF của revision 4 sau khi mở lại và MP4 vừa xuất bằng nút WPF Screen 6. Checker tái dựng graph từ Project V2 r4, kiểm tra export history fingerprint, rồi căn frame theo **frame index**.

- Cả hai file có 510 frame, 30 fps và 17 giây; preview 540×960, export 1080×1920. Export được resize về kích thước preview chỉ trong phép so sánh.
- 42 frame mẫu gồm frame đầu, 1 giây, các frame kề mốc event, frame giữa event và frame cuối; RGB MAE trung bình **5.479902/255**, lớn nhất **6.965801/255**.
- So sánh toàn bộ 510 frame: SSIM trung bình **0.92719395**, thấp nhất **0.915438**. Ngưỡng QA hiện dùng (mean MAE ≤12, sample MAE ≤24, mean SSIM ≥0.90) đều đạt.
- Export history và graph có cùng fingerprint `8653846be39a2f343772d1b971e2dc2b7823a025de278b64ec3a9280a3d566c7`. FFprobe và full decode cho cả preview/export đều pass.
- Hash các file media trong runtime trước/sau parity giống nhau. Đây là kiểm chứng parity giữa hai bản mã hóa của cùng graph; không phải phép đo fidelity với video Muse.

## Thay đổi source và kiểm thử

- `src/MediaStudio.Desktop/ViewModels/VideoCreatorGalleryViewModel.cs`: sau khi `ReplaceMediaAsync` hoàn tất và binding của session được đồng bộ, gọi `RefreshLatestSavedDraftAsync()` để Gallery hiện revision mới ngay.
- `src/MediaStudio.Desktop.Tests/VideoCreatorGalleryViewModelTests.cs`: thêm `GalleryDraftLabelRefreshesAfterSavedRevisionAdvances`, kiểm tra cập nhật nhãn r2 → r3.
- Không sửa Screen 2, route xử lý hiện có, compiler, renderer, Project V2, Definition 0.3, Image Tools hoặc media gốc.
- `dotnet build MediaStudio.sln --no-restore` với `-p:OutDir=artifacts\video_creator\task3_9e\dotnet_build_out\`: **0 warning, 0 error**.
- `dotnet test MediaStudio.sln --no-restore` với output cô lập: **56 passed, 0 failed, 0 skipped**.
- Backend suites liên quan Media Selection, Template Compiler/Processing, draft preview, export, Project V2/API và Fall Diary 3.9A/B/C: **76 passed**; 1 deprecation warning Starlette/AnyIO.
- Không chạy Image Tools smoke riêng: thay đổi chỉ nằm trong Video Creator Gallery ViewModel, không dùng code chung với Image Tools.

## Giới hạn còn lại

- Screen 3 trong runtime cô lập hiển thị fallback “Không tải được thumbnail” cho media grid vì workspace QA không có thumbnail derivatives. Việc chọn/gán vẫn dùng file ảnh thật; preview và export dùng asset IDs/file thật. Đây là giới hạn hiển thị của runtime fixture và không được ghi nhận là thumbnail acceptance.
- Template 0.3 chỉ khai báo ảnh; lần export không có audio. Không nạp nhạc từ Muse.
- Cutout, audio fidelity và reference fidelity chưa được xác minh. Task này chỉ chứng minh lưu, mở lại, xử lý preview/export và parity của cùng Project V2.

## Cổng nghiệm thu

| Gate | Trạng thái | Evidence |
|---|---|---|
| `FALL_DIARY_EDIT_RETURN_FLOW_VERIFIED` | **true** | WPF thay media từ Screen 5, giữ Project ID/template/version, tăng revision và quay lại Preview/Edit của r4. |
| `FALL_DIARY_WPF_EXPORT_AFTER_EDIT_VERIFIED` | **true** | Nút Export Screen 6 tạo MP4 thành công từ r4; history ghi job `59e7afefebb74f77aa9c9460b7d5254e`. |
| `FALL_DIARY_WPF_PREVIEW_EXPORT_PARITY_VERIFIED` | **true** | Cùng project/revision/bindings/fingerprint; 42 frame mẫu và 510-frame SSIM đạt ngưỡng; full decode pass. |
| `FALL_DIARY_EDIT_SAVE_REOPEN_VERIFIED` | **true** | Đóng/mở lại WPF từ runtime QA; Gallery, Project V2, preview r4 và export sử dụng đúng revision/bindings. |
| `FALL_DIARY_SIX_SCREEN_GUI_VERIFIED` | **true — giới hạn fixture** | Các màn Gallery/Details/Media Selection/Processing/Preview/Edit/Export được kiểm tra bằng WPF thật; Screen 3 không có thumbnail derivatives trong runtime cô lập. |
| `FALL_DIARY_CUTOUT_VERIFIED` | **false** | Không triển khai trong Task 3.9E. |
| `FALL_DIARY_AUDIO_FIDELITY_VERIFIED` | **false** | Không có audio track được cấp quyền/timing xác minh. |
| `FALL_DIARY_REFERENCE_FIDELITY_VERIFIED` | **false** | Parity là WPF preview/export cùng graph, không xác nhận fidelity với Muse. |
| `FALL_DIARY_READY_FOR_USERS` | **false** | Fall Diary vẫn là reference pilot; blocker cutout/audio/fidelity và demo/poster còn nguyên. |

## Deliverables

- WPF final MP4: [Fall Diary Reference Pilot 0.3 Task3.9E Final.mp4](../../artifacts/video_creator/task3_9e/Fall%20Diary%20Reference%20Pilot%200.3%20Task3.9E%20Final.mp4)
- WPF preview r4: [Fall_Diary_WPF_Preview_Revision4.mp4](../../artifacts/video_creator/task3_9e/Fall_Diary_WPF_Preview_Revision4.mp4)
- Project V2 r4: [Fall_Diary_Task3_9E_Project_V2_Revision4.json](../../artifacts/video_creator/task3_9e/Fall_Diary_Task3_9E_Project_V2_Revision4.json)
- Bindings/source hash manifest: [Fall_Diary_Task3_9E_Bindings_Manifest_Revision4.json](../../artifacts/video_creator/task3_9e/Fall_Diary_Task3_9E_Bindings_Manifest_Revision4.json)
- WPF export history: [Fall_Diary_Task3_9E_Export_History_Revision4.json](../../artifacts/video_creator/task3_9e/Fall_Diary_Task3_9E_Export_History_Revision4.json)
- Parity contact sheet: [Fall_Diary_Task3_9E_Preview_Export_Contact_Sheet_Revision4.jpg](../../artifacts/video_creator/task3_9e/Fall_Diary_Task3_9E_Preview_Export_Contact_Sheet_Revision4.jpg)
- Machine-readable parity: [Fall_Diary_Task3_9E_Parity_Report_Revision4.json](../../artifacts/video_creator/task3_9e/Fall_Diary_Task3_9E_Parity_Report_Revision4.json)
- FFprobe/full decode: [Fall_Diary_Task3_9E_FFprobe_FullDecode_Revision4.json](../../artifacts/video_creator/task3_9e/Fall_Diary_Task3_9E_FFprobe_FullDecode_Revision4.json)
- WPF runtime screenshots: [Gallery r4](../../artifacts/video_creator/task3_9e/screenshots/Task3_9E_Gallery_revision4.jpg), [Preview r4 reopened](../../artifacts/video_creator/task3_9e/screenshots/Task3_9E_Preview_revision4_reopened.jpg), [Export success](../../artifacts/video_creator/task3_9e/screenshots/Task3_9E_Export_success_revision4.jpg).

## Đề xuất tiếp

Giữ các cổng fidelity, cutout, audio và ready-for-users ở `false` cho tới khi có asset/quyền và bằng chứng reference phù hợp. Tạo thumbnail derivatives trong runtime QA trước lần nghiệm thu tiếp theo nếu cần đánh giá giao diện grid bằng hình ảnh.
