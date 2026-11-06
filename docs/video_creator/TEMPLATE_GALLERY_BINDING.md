# Video Template Gallery — Data Binding

## Luồng dữ liệu

```text
MainWindow / MainViewModel
  → VideoCreatorGalleryView
  → VideoCreatorGalleryViewModel.LoadCatalogAsync()
  → TemplateCatalogService.GetTemplatesAsync()
  → MediaStudioApiClient.GetVideoTemplatesAsync()
  → GET /api/v1/video/templates
  → backend catalog
```

Gallery không có fallback template cục bộ. Lỗi backend để trống danh sách và hiển thị trạng thái lỗi.

## DTO và hiển thị

| DTO / catalog field | WPF binding | Ý nghĩa và quy tắc |
|---|---|---|
| `templateId` | `VideoTemplateCardViewModel.TemplateId` | Stable key để truyền vào workflow tạo instance trong task sau. Hiện chỉ dùng nhận diện selection. |
| `name` | `Name`, card và action bar | Tên mẫu lấy từ catalog. |
| `description` | `Description`, search/card | Mô tả và một trường được search. |
| `category` | `Category`, category filter/search | Danh sách category được suy ra từ template hiện có. |
| `durationMs` | `Duration` | Hiển thị `mm:ss`, không dùng số demo từ UI. |
| `sceneCount` | `SceneCount` | Số cảnh hiển thị ở badge card. |
| `requiredMediaSlots` | `RequiredMediaSlots`, action bar/card | Backend chỉ đếm slot được khai báo rõ trong `mediaSlotRequirements`; không suy ra số slot từ event/scene. Giá trị 0 cùng danh sách rỗng có nghĩa là chưa khai báo. |
| `width`, `height`, `aspectRatio` | `AspectRatio` | Catalog hiện trả 1080×1920 và `9:16`; poster frame vẫn cố định portrait 9:16 theo UI spec. |
| `posterPath` | `PosterPath` → `LocalPosterImageConverter` | Optional local path. Converter không tải URL mạng; file mất/hỏng sẽ quay về placeholder. Cache tối đa 64 ảnh, tải lười. |
| `previewSource`, `previewAvailable` | `PreviewSource`, `PreviewAvailable`, `PreviewStatus` | Badge đổi theo `previewAvailable`; card không tự phát video. Không có player gallery trong TASK này. |
| `isNew` | `IsNew` | Badge New chỉ hiện khi catalog đánh dấu true; thiếu field mặc định false. |
| `scenes` | scene metadata hiện chưa render thành slot UI | Cần dùng để tạo chi tiết slot trong Media Slot Assignment. |

`requiredMediaSlots` và `mediaSlotRequirements` là metadata của catalog; chúng không sửa schema dự án V2 hoặc dữ liệu đã lưu. Event có thể tham chiếu một slot nhiều lần và một event có thể chứa nhiều layer.

## Command và state

- `SearchText` gọi `UpdateVisibleTemplates()` sau mỗi thay đổi.
- `SelectCategoryCommand` cập nhật một category và áp dụng cùng search.
- `SelectTemplateCommand` chỉ cập nhật `SelectedTemplate` và `IsSelected`; không gọi service tạo project.
- `SelectedTemplateName`, `SelectedTemplateSummary`, `SelectedTemplateHasPoster` cung cấp dữ liệu action bar.
- `HasNoVisibleTemplates`, `EmptyStateTitle`, `EmptyStateDescription`, `CatalogStatus` biểu diễn empty/loading/error/catalog metadata.
- Button `Dùng mẫu` và `Mở dự án` cố ý chưa có command và đang disabled. Không có request tạo project khi người dùng chỉ chọn card.

## Hợp đồng cho Media Slot Assignment

Workflow tiếp theo cần nhận `TemplateId`, đọc `scenes[]`, và tạo view slot có stable scene/slot IDs. Mỗi binding cần trỏ tới stable media asset ID, validate media type, duration/crop và khả năng preview. Sau Save/Reopen cần bảo toàn template ID cùng slot bindings. Chỉ sau khi instance service, persistence và compiler hoạt động mới nối `Dùng mẫu` sang Template Details → Slot Assignment → Template Instance.

