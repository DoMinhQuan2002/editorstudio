# Thành phần engine được giữ — Video Creator

TASK 3.0A retire UI chỉnh sửa thủ công. Project V2, Composition Graph, media handling, preview, render, audio và persistence tiếp tục là runtime nội bộ.

| Module | Vị trí | Vai trò giữ lại | Trạng thái |
|---|---|---|---|
| Template catalog | backend/mediastudio/video_editor/catalog.py | Danh sách template metadata và scene timing | Bảy template hiện có; không thêm template giả. previewAvailable hiện false. |
| Catalog API | GET /api/v1/video/templates | Nạp catalog cho WPF | Gallery VM/service gọi endpoint này. |
| Template DTO | VideoTemplateDto, VideoTemplateSceneDto trong VideoEditorApiModels.cs | Truyền template/scene metadata | Giữ; mở rộng slot metadata khi có use case. |
| Project V2 | backend/mediastudio/video_editor/project_v2.py | Project, track/clip ID, timing, validation | Giữ nguyên schema và 90.000 ticks/giây. |
| Timeline Engine V2 | project_v2.py | Tạo/kiểm tra track/clip entities | Engine nội bộ, không phải timeline người dùng. |
| Project Store | backend/mediastudio/video_editor/storage.py | Atomic save/open, V1 migration và backup | Giữ; Task 3.0A không scan/mutate project cá nhân. |
| Composition Graph | composition.py | Tạo graph render từ Project V2 | Giữ cho compiler và preview/export. |
| Native compositor | backend/native/video_engine/, native_engine.py | Decode/composition native trong capability subset | Không sửa C++/ABI; native ASan không chạy lại. |
| FFmpeg renderer | composition_renderer.py và video editor FFmpeg modules | Render MP4 và text/media subset | Giữ; chạy regression backend subset. |
| Audio mixer | audio_mixer.py | Mix audio track và source timing | Giữ; không đổi audio policy. |
| Preview | GET/POST /api/v1/video/projects/{project_id}/preview/frame | Tạo preview frame nội bộ | Giữ; Gallery hiện không trình bày preview mẫu. |
| Render jobs | /render-jobs, /jobs/{job_id}, result | Export bất đồng bộ, status và result | Giữ; Gallery chưa có nút export. |
| Media import/probe | api.py, media services/store | Upload, metadata, thumbnail/frame/filmstrip/waveform/content | Giữ; import UI/slot assignment chưa expose. |
| Media type resolver | MediaTypeResolver.cs | Dùng metadata xác thực thay vì suffix file | Tách khỏi NLE drop resolver để dùng sau. |
| Typed API client | MediaStudioApiClient.cs | Catalog/media/project/preview/render/jobs REST client | Giữ endpoint và session token. |
| Backend host | BackendProcessHost | Spawn/stop FastAPI loopback, token và health | Không đổi; smoke dùng data directory riêng. |
| DLL copy rule | MediaStudio.Desktop.csproj | Đặt native DLL cạnh packaged desktop khi có | Giữ vì backend native loader cần; WPF wrapper riêng đã retire. |

## API hiện có được giữ

Router thực tế cung cấp capabilities, template catalog, media upload/list/detail/thumbnail/frame/filmstrip/waveform/content, project list/create/blank/get/save, preview GET/POST, render-job create/status/cancel/result. Không endpoint hay auth nào bị xóa/đổi. Project mutation API vẫn còn nhưng Gallery không gọi create/open/edit.

## Còn thiếu trước khi compiler hoàn chỉnh

- Slot DTO: kiểu chấp nhận, required/optional, crop/fit constraints.
- Template instance lưu binding bền vững.
- TemplateInstanceService/MediaBindingService.
- Compiler tạo Project V2 từ scenes/slots.
- Preview/export parity với nhiều template/media.

Không tạo placeholder service/interface trong Task 3.0A; ranh giới phase sau có trong architecture baseline và handoff.
