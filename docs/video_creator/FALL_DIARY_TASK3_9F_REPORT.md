# MEDIA STUDIO — TASK 3.9F REPORT
# FALL DIARY — WPF VIDEO PLAYBACK & MEDIA THUMBNAIL ACCEPTANCE

Ngày chạy: 23-10-2026  
Môi trường GUI: Media Studio WPF, bản publish Release trong workspace cô lập `artifacts/video_creator/task3_9f/`.

## Kết quả nghiệm thu

| Cổng | Kết quả | Bằng chứng |
|---|---|---|
| `TASK3_9F_SCREEN05_PLAYBACK_VERIFIED` | `true` | Screen 5 phát preview từ Project V2 revision 4; ảnh runtime có frame thật và trạng thái “Video preview revision 4 đã được mở và kiểm tra thời lượng.” |
| `TASK3_9F_SCREEN06_PLAYBACK_VERIFIED` | `true` | Screen 6 mở ở 00:00 với poster frame thật; log `MediaOpened` ghi duration 17 giây; Play, Pause, seek và `MediaEnded` được kiểm tra trên WPF. |
| `TASK3_9F_EXPORT_SUCCESS_PREVIEW_VERIFIED` | `true` | WPF báo Export Success; preview vẫn hiển thị và seek tới 00:01 được ngay sau xuất. |
| `TASK3_9F_MEDIA_THUMBNAIL_VERIFIED` | `true` cho media mới nhập | JPEG, PNG dọc, PNG ngang và MP4 được nhập qua WPF/import API; endpoint thumbnail trả 200 và ảnh/video thumbnail thật xuất hiện trong Screen 3. |
| `TASK3_9F_REVISION_PREVIEW_CONSISTENCY_VERIFIED` | `true` | Project ID `73da1503e49b403f9ad5c56f7d4d688c`, revision 4, `fall-diary / 0.3.0-reference-pilot`, fingerprint `8653846be39a2f343772d1b971e2dc2b7823a025de278b64ec3a9280a3d566c7`; Project V2 và 48 file media baseline không đổi. |
| `TASK3_9F_GUI_ACCEPTED` | `true` trong phạm vi Screen 3, 5 và 6 | Đã thao tác WPF thật: nhập media, cuộn lưới, chọn và gán/thay slot trong session, xem preview, phát/tạm dừng/seek, xuất, quay lại và mở lại Screen 6. Không coi unit test hoặc backend harness là nghiệm thu GUI. |

## Nguyên nhân màn hình đen và cách sửa

Kết quả kiểm tra không cho thấy lỗi đường dẫn hay lỗi giải mã. WPF `MediaElement` mở đúng MP4 của revision 4, `MediaOpened` trả duration hợp lệ 17 giây và không có sự kiện `MediaFailed` hoặc `source-error` trong log. Màn hình đen xảy ra khi giao diện đang ở trạng thái tạm dừng trước khi WPF vẽ frame đầu tiên: bề mặt của player khi đó có thể vẫn đen.

Screen 6 nay hiển thị poster frame 0 lấy từ preview đã xác minh trong Composition Graph. `MediaElement` được giữ ẩn cho tới khi phát hoặc seek; trạng thái loading và lỗi được hiển thị riêng. Khi video chạy, player hiện frame giải mã thực. Khi hết video, poster được khôi phục. Đây là xử lý trạng thái hiển thị của WPF; không đổi renderer, Composition Graph hay cấu hình export.

Log runtime ghi:

- `source-set`: đúng project/revision/template, file tồn tại, poster có sẵn.
- `media-opened`: duration 17 giây, vị trí đầu 0.005 giây, muted khi vừa mở.
- `seek`: tới 10 giây và sau xuất tới 1 giây; frame tương ứng hiển thị.
- `play`, `pause`, `media-ended`: trạng thái player được cập nhật; frame poster khôi phục khi kết thúc.
- Không có `media-failed` hoặc `source-error`.

Khi Screen 6 được mở lại sau khi quay về Screen 5, poster frame đầu tiếp tục hiển thị. Play/Pause/Seek vẫn hoạt động. Screenshot sau Export Success cũng cho thấy preview còn phát/seek được mà không rời màn hình.

## Thumbnail và thao tác media trên Screen 3

Đã dùng File Picker của chính ứng dụng để nhập media QA trong workspace cô lập:

| Loại | Tệp | Kết quả |
|---|---|---|
| JPEG | `photo_01.jpg` | Nhập thành công; thumbnail endpoint 200. |
| PNG dọc | `Task3_9F_portrait.png` | Nhập thành công; thumbnail thật hiện trong lưới và panel media đang chọn. |
| PNG ngang | `Task3_9F_landscape.png` | Nhập thành công; thumbnail thật hiện trong lưới và panel media đang chọn. |
| MP4 | `fall-diary-preview.mp4` | Nhập thành công; thumbnail là frame thật của video, thời lượng 17 giây hiện trong lưới. |

Đã cuộn Media Library, chọn ảnh dọc, gán vào `photo-01`, sau đó thay bằng ảnh ngang. Screen 3 cập nhật đúng tên và thumbnail slot; session vẫn hiển thị 11/11 slot. Không bấm “Cập nhật preview” sau thao tác QA, nên không tạo revision mới hay lưu binding thử nghiệm vào Project V2.

Phân biệt dữ liệu cũ và pipeline nhập mới: một số media legacy trong bản sao QA vẫn hiện “Không tải được thumbnail” do thiếu derivative sẵn có. Bốn media nhập mới tạo/đọc derivative qua pipeline thật và hiển thị thành công. Không sửa media nguồn và không vá product code thumbnail vô cớ để che dữ liệu QA cũ.

## Preview, export và bảo toàn revision

- Screen 5 và Screen 6 sử dụng preview draft r4 tại `DraftPreviewCache` có tên gắn project ID, revision và fingerprint.
- Export job: `289dd7cc11954667a33501b1cf6f164a`; trạng thái `SUCCEEDED`.
- Template: `fall-diary / 0.3.0-reference-pilot`.
- Đầu ra: `artifacts/video_creator/task3_9f/Task3_9F_Fall_Diary_WPF_Revision4.mp4`.
- `ffprobe`: H.264, 1080×1920, 30/1 fps, 17.000 giây, 510 frame.
- Full decode: `ffmpeg -v error -i <file> -f null -`, exit code 0, không có lỗi decode.
- SHA-256 đầu ra 3.9F trùng đầu ra cuối 3.9E: `F905D628F3F0040E420B07B37A29F7E05510CC8D1E97830EA9131810CE818F48`.
- WPF handoff kiểm tra project ID, revision, template ID/version, composition fingerprint và file preview tồn tại; fingerprint của Composition Graph được tính từ toàn bộ Project V2 snapshot, bao gồm metadata binding. Export request gửi nguyên media binding map từ capabilities; backend kiểm tra revision, template/version, composition fingerprint và media bindings trước khi nhận job.
- Project V2 JSON trong runtime workspace 3.9E và bản sao 3.9F có cùng SHA-256: `39B3729D1D5AB1962D4D69419F71D0B0BEC86ACC2264B3E30CAF3F0476D765E5`. Cả 48 file media baseline đều cùng hash; 3.9F chỉ thêm media QA/derivatives và export history trong workspace riêng.

## Build và regression

- WPF tests: `dotnet test src/MediaStudio.Desktop.Tests/MediaStudio.Desktop.Tests.csproj --configuration Release ...` — **58 passed, 0 failed**.
- WPF publish: `dotnet publish src/MediaStudio.Desktop/MediaStudio.Desktop.csproj --configuration Release --runtime win-x64 --no-self-contained ...` — **thành công**; chính executable publish được dùng trong thử nghiệm GUI.
- Backend media selection/thumbnail tests: `PYTHONPATH=backend backend/.venv/Scripts/python.exe -m pytest backend/tests/test_media_selection_task33.py -q` — **6 passed**, 1 cảnh báo deprecation Starlette hiện hữu.
- WPF runtime: Gallery → Fall Diary → draft r4 → Screen 5 → Screen 6 → Export Success → Screen 5 → Screen 6; Screen 3 được mở từ “Thay media” để nhập và kiểm tra slot trong session.

## File nguồn được cập nhật

- `src/MediaStudio.Desktop/ViewModels/VideoCreatorDraftPreviewViewModel.cs` — chuyển poster frame 0 cùng handoff preview.
- `src/MediaStudio.Desktop/ViewModels/VideoCreatorExportViewModel.cs` — xác minh preview nguồn, project/revision/template/fingerprint/duration và trạng thái playback.
- `src/MediaStudio.Desktop/Views/VideoCreatorExportView.xaml` và `.xaml.cs` — lớp poster, trạng thái loading/lỗi, MediaOpened/Failed/Ended, Play/Pause/Seek và giải phóng player khi đổi nguồn/unload.
- `src/MediaStudio.Desktop/Services/VideoCreatorRuntimeDiagnostics.cs` — chẩn đoán lifecycle playback.
- `src/MediaStudio.Desktop.Tests/VideoCreatorDraftPreviewViewModelTests.cs` và `VideoCreatorExportViewModelTests.cs` — kiểm tra poster, handoff và xác minh source.
- `backend/tests/test_media_selection_task33.py` — kiểm tra import/thumbnail JPEG, PNG dọc/ngang và MP4 qua pipeline thật.

Không sửa Definition 0.1/0.2/0.3, Template Compiler, Composition Graph, Project V2 schema, User Projects hoặc media nguồn. Không commit/push.

## Runtime artifacts

Ảnh được chụp từ cửa sổ WPF đang chạy:

![Screen 6 — Export Success và preview thật](../../artifacts/video_creator/task3_9f/screenshots/Task3_9F_Screen06_WPF_export_success.jpg)

![Screen 3 — MP4 có thumbnail frame thật](../../artifacts/video_creator/task3_9f/screenshots/Task3_9F_Screen03_video_thumbnail.jpg)

![Screen 3 — ảnh ngang thay binding slot trong session](../../artifacts/video_creator/task3_9f/screenshots/Task3_9F_Screen03_landscape_bound_in_session.jpg)

Các ảnh khác: `artifacts/video_creator/task3_9f/screenshots/`.  
MP4 đầu ra: `artifacts/video_creator/task3_9f/Task3_9F_Fall_Diary_WPF_Revision4.mp4`.  
Log playback và API: `artifacts/video_creator/task3_9f/app/video-creator-task3-2a-runtime.log` và `artifacts/video_creator/task3_9f/backend.log`.

## Giới hạn còn lại

- Các bản ghi media legacy thiếu thumbnail derivative vẫn cần được tái lập/di chuyển bằng quy trình dữ liệu phù hợp; gate thumbnail ở đây chỉ xác nhận media mới nhập qua pipeline.
- Không tạo video thao tác màn hình; có screenshot runtime thật và MP4 đầu ra.
- Các gate không thuộc 3.9F giữ nguyên: `FALL_DIARY_REFERENCE_FIDELITY_VERIFIED=false`, `FALL_DIARY_CUTOUT_VERIFIED=false`, `FALL_DIARY_AUDIO_FIDELITY_VERIFIED=false`, `FALL_DIARY_READY_FOR_USERS=false`.

**Kết luận:** Task 3.9F đạt GUI acceptance cho Screen 3, Screen 5 và Screen 6 trong workspace cô lập. Screen 6 không còn khung đen lúc mở; playback sau export hoạt động. Thumbnail của media mới nhập được xác minh trên WPF và qua API. Bản Project V2 r4 và media baseline được giữ nguyên.
