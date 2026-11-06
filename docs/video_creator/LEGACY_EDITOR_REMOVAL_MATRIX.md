# Ma trận retire NLE cũ — TASK 3.0A

**Ngày:** 2026-10-22. Phạm vi: WPF desktop shell và các lớp interaction chỉ phục vụ chỉnh sửa thủ công.

Decision chỉ dùng các giá trị yêu cầu: DELETE, EXTRACT_AND_DELETE_OLD_SHELL, REUSE, KEEP_FOR_COMPATIBILITY, PROTECT, INVESTIGATE.

| File / class | Trách nhiệm trước cleanup | Caller đã xác minh | Future use | Decision |
|---|---|---|---|---|
| MainWindow.xaml | Workspace navigation, Image Tools và content Video | App/MainViewModel bindings | Giữ workspace; route video trỏ gallery Video Creator | REUSE |
| MainViewModel | Workspace state, Image Tools và Video Editor VM | App.xaml.cs, MainWindow.xaml | Điều phối Gallery và Image Tools | REUSE |
| MainWorkspaceKind.VideoEditor | ID enum cho workspace video | MainViewModel, XAML | Giữ làm internal route ID | KEEP_FOR_COMPATIBILITY |
| Views/VideoEditorView.xaml | Gallery cộng manual timeline, preview, inspector, toolbar, controls | MainWindow | Không còn; gallery chuyển sang view riêng | DELETE |
| Views/VideoEditorView.xaml.cs | Playback, drag/drop, track, trim, seek, keyboard và event handlers NLE | VideoEditorView.xaml | Không còn consumer | DELETE |
| ViewModels/VideoEditorViewModel.cs | Gallery, Project V2 projection, media, timeline, preview, audio, save/export, undo | MainViewModel, View/code-behind, timeline services | Catalog state đã tách; engine vẫn ở backend | DELETE |
| Views/ReplaceClipDialog.cs | Dialog chọn Replace NLE | VideoEditorView.xaml.cs | Không thuộc template slot binding | DELETE |
| ViewModels/TimelineTrackViewModel.cs | WPF track projection/hit-test/lane controls | VideoEditor VM/View; projection test | Project V2 track entities vẫn ở backend | DELETE |
| Services/TimelineInteractionEngine.cs | Pixel/time ruler, hit test, drag, drop, trim/split, snapping, auto-scroll | View, VM, interaction tests | Không dùng cho Template Compiler; backend TimelineEngineV2 được giữ | DELETE |
| Services/TimelineV2EditCommands.cs | WPF track/clip editing commands và projection DTO | VideoEditor VM, command tests | Backend V2 là nguồn chuẩn | DELETE |
| Services/MediaTimelineRouting.cs / MediaTimelineDropResolver | Media lane routing và vùng drop NLE | VideoEditor View; routing tests | Drop-to-track retire; metadata resolver giữ lại | EXTRACT_AND_DELETE_OLD_SHELL |
| Services/MediaTypeResolver.cs | Phân loại media theo metadata đã probe | Test mới; slot assignment tương lai | Gắn media hợp lệ vào slot | REUSE |
| Services/TimelineDragDiagnostics.cs | Nhật ký pointer session/hover/drop NLE | VideoEditor View | Không còn consumer | DELETE |
| Services/NativeVideoPreviewEngine.cs | WPF wrapper preview native | VideoEditor VM/View | Backend native/API preview được giữ | DELETE |
| Services/NativeVideoRenderEngine.cs | WPF wrapper render editor | VideoEditor VM | Backend FFmpeg/native renderer được giữ | DELETE |
| Services/TemplateCatalogService.cs | Ranh giới service cho template catalog | Gallery VM | Gallery, preview, template instance tương lai | REUSE |
| VideoCreatorGalleryViewModel | Search/category/selection/status catalog | MainViewModel, Gallery View | Gallery và điểm tích hợp Template Instance | REUSE |
| VideoCreatorGalleryView.xaml(.cs) | Gallery-only UI và tải catalog khi hiển thị | MainWindow | Host hiện tại đến khi Task 3.0B thay layout | REUSE |
| MediaStudioApiClient | Typed REST client catalog/media/project/preview/render | BackendProcessHost, Image Tools, Catalog service | API runtime V2 tương lai | KEEP_FOR_COMPATIBILITY |
| VideoTemplateDto / VideoTemplateSceneDto | Catalog và scene metadata | API client/Gallery VM | Template metadata/slot definition | KEEP_FOR_COMPATIBILITY |
| WpfMediaFilePicker | Chọn tệp qua Windows | Trước đây VideoEditor | Import/slot assignment tương lai | KEEP_FOR_COMPATIBILITY |
| Shared Image Tools XAML/templates/styles | Điều hướng và ba workflow ảnh | MainWindow, ImageTools VM | Workspace ảnh độc lập | PROTECT |
| backend/mediastudio/video_editor/api.py | Catalog, media, project, preview và render jobs | WPF client/tests | Runtime nội bộ và legacy recovery | PROTECT |
| backend/mediastudio/video_editor/catalog.py | Template metadata và project initialization | API, V2/catalog tests | Catalog và compiler input | PROTECT |
| project_v2.py / storage.py / timeline_v2.py | Entities, 90k ticks/s, migration, validation, atomic persistence | API, composition graph/tests | Template Compiler output/recovery | PROTECT |
| composition.py / composition_renderer.py / audio_mixer.py / native_engine.py | Graph, native/FFmpeg, preview, audio | Video API/jobs | Runtime template-first | PROTECT |
| backend/native/video_engine | C++ decode/composition runtime | Python native adapter/CMake | Preview/export nội bộ | PROTECT |
| Image Tools WPF/Python/AI/storage/jobs | Upscale, vectorization, die-cut, SVG preview và jobs | MainWindow/API/backend | Workspace mặc định, ngoài scope retire | PROTECT |

## Test shell đã retire

- Xóa TimelineInteractionEngineTests.cs, TimelineTrackProjectionTests.cs, TimelineV2EditCommandTests.cs: kiểm tra gesture/projection/lệnh WPF shell đã bỏ.
- Tách test metadata khỏi MediaTimelineRoutingTests.cs sang MediaTypeResolverTests.cs; test drop-to-lane NLE bị bỏ theo workflow retired.
- Thêm VideoCreatorGalleryViewModelTests.cs kiểm tra catalog, search/category và empty state khi backend không sẵn sàng.
- Backend Project V2/migration/timeline/Composition/Audio/API tests không bị xóa.

Reference scan không còn caller cho các class WPF đã xóa. Không đổi API, schema, engine native hoặc dữ liệu.
