# TASK 3.0B handoff

TASK 3.0B có thể bắt đầu dựng Gallery theo thiết kế poster dọc 9:16 đã duyệt. Handoff này không triển khai lại gallery trong TASK 3.0A.

## Entry points

- View: src/MediaStudio.Desktop/Views/VideoCreatorGalleryView.xaml và .xaml.cs.
- ViewModel: src/MediaStudio.Desktop/ViewModels/VideoCreatorGalleryViewModel.cs.
- Catalog service: src/MediaStudio.Desktop/Services/TemplateCatalogService.cs.
- Typed client method: MediaStudioApiClient.GetVideoTemplatesAsync.
- DTO: VideoTemplateDto và VideoTemplateSceneDto trong VideoEditorApiModels.cs.
- Navigation: MainWorkspaceKind.VideoEditor là internal ID; MainWindow.xaml hiển thị Video Creator và Gallery.

## Tái sử dụng

- Search theo tên, mô tả, category.
- Category options được tạo từ catalog backend.
- Selection state và summary.
- Duration, scene count, aspect ratio, scene metadata.
- ItemsControl/UniformGrid có thể thay poster/art/layout theo thiết kế được duyệt.
- PreviewAvailable phải phản ánh backend; artwork không được gọi là video preview.
- MediaTypeResolver và WpfMediaFilePicker dành cho import/binding về sau.

## Nút Dùng mẫu cần nối ở phase sau

Chỉ bật khi có end-to-end:

1. TemplateInstanceService tạo instance theo TemplateId.
2. MediaBindingService hiển thị slot và validation theo template.
3. Media import/probe và binding bằng stable asset ID, không chỉ filename.
4. Instance Save/Reopen giữ nguyên binding.
5. TemplateCompiler tạo Project V2 từ instance/bindings.
6. Preview và export dùng cùng snapshot và được kiểm tra qua nhiều template.

Nếu thiếu bước nào, nút vẫn phải disabled/báo trạng thái và không tạo placeholder project.

## Route đã loại bỏ

Manual NLE view/blank project editor, saved-project open vào timeline, timeline commands/projection/ruler, drag/drop, trim/split/replace và inspector đã retire. Project API/backend vẫn tồn tại; Gallery không có nút mở route cũ.

## Shared UI / modules cần bảo vệ

- Giữ Image Tools navigation, default workspace, WPF views/ViewModels, Python backend lifecycle, loopback token và theme resources.
- Không đổi Image Tools Python/WPF, Real-ESRGAN, vectorization, contour/die-cut, SVG preview, CUDA/model, jobs hoặc dữ liệu ảnh.
- Không đổi Project V2 schema, store/migration, Composition Graph, native ABI, audio mixer, preview/render/jobs hoặc media stores.
- Giữ client DTO/DLL staging cần cho backend.
- Không scan/sửa legacy project/media ở %LOCALAPPDATA%/MediaStudio/workspace.

## Acceptance TASK 3.0B

- Gallery dùng catalog backend thật, không fallback.
- Poster dọc 9:16 rõ ở DPI/window size hỗ trợ.
- Search/category/selection hoạt động.
- Chỉ phát preview khi backend có source thật.
- Dùng mẫu đi qua slot assignment/persistence/compiler, không mở NLE.
- Image Tools vẫn mặc định; Gallery không tạo project cho đến khi workflow được triển khai.
