# Video Creator — architecture baseline sau TASK 3.0A

**Ngày:** 2026-10-22.  
**Định hướng:** Template-Based Video Creator. Người dùng khám phá mẫu → chọn mẫu → gắn media vào slot → tạo video tự động → preview → export → lưu template instance. Timeline/track/segment chỉ là representation runtime nội bộ.

## Desktop hiện hành

MainWindow
→ VideoCreatorGalleryView
→ VideoCreatorGalleryViewModel
→ TemplateCatalogService
→ MediaStudioApiClient
→ GET /api/v1/video/templates

- MainWorkspaceKind.VideoEditor vẫn là internal enum value để giữ route ID; label/header UI đổi thành Video Creator.
- MainWindow.xaml bind workspace video tới Gallery View, không còn VideoEditorView.
- Gallery VM giữ search/category/selection/status; category lấy từ template metadata backend.
- Không có local fallback template. Backend lỗi/list rỗng thì UI báo lỗi/empty state.
- DTO gồm TemplateId, tên/mô tả/category, duration, kích thước/aspect ratio, scene count, PreviewAvailable và scene Name/DurationMs.
- Các mẫu hiện có previewAvailable=false; artwork card là minh họa metadata/style, không phải video preview.
- Nút Dùng mẫu bị disable; không tạo project giả. Media slot assignment chưa có.
- WpfMediaFilePicker giữ cho import/slot binding về sau, chưa có action import trong Gallery.

## Engine/backend hiện hành

WPF Gallery → typed REST client và loopback backend/session token → catalog/media APIs, Project V2/store/migration, Composition Graph/preview, native compositor/audio mixer/FFmpeg renderer/jobs.

Backend giữ package tên video_editor vì đó là tên module lịch sử. Project V2, schema, atomic storage, V1 migration, 90k ticks/s và composition/native/audio/render APIs không đổi. Chi tiết: reusable engine inventory.

## Ranh giới phase

| Module | Vai trò |
|---|---|
| Template Gallery | Catalog/search/category/selection hiện có |
| Template Preview | Chưa có preview video thật trong catalog hiện nay |
| Media Slot Assignment | Chưa triển khai |
| Project Library | Chưa triển khai trong Gallery; backend API vẫn có |
| Template Instance/Media Binding Service | Phase sau; chưa tạo placeholder interface |
| Template Compiler | Phase sau: map template scenes/slots thành Project V2 |
| Engine | Project V2, Composition Graph, native preview, audio và FFmpeg |

Manual timeline/ruler/tracks, drag/drop edit, trim/split/ripple/replace, inspector NLE, editing undo/redo và project-open route đã retire khỏi UI. Track/clip object và engine backend vẫn được giữ.

Image Tools tiếp tục là workspace mặc định; Gallery không mutate legacy projects. VIDEO_CREATOR_RELEASE_READY=false.
