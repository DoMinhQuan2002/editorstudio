# Tương thích project legacy

## Cam kết an toàn

- Không đọc danh sách project cá nhân ở %LOCALAPPDATA%/MediaStudio/workspace/video_editor/projects.
- Không mở, ghi, đổi tên, xóa hoặc batch migrate JSON.
- Không sửa media, preview, result, asset/job của Image Tools.
- Runtime Task 3.0A dùng artifacts/video_creator/task3_0a/runtime/workspace riêng.
- Runtime log mới ghi backend start, capabilities và GET /api/v1/video/templates; không gọi project list/get/save/render.

## Nhãn phân loại phase sau

| Loại | Ý nghĩa | Cách xử lý hiện tại |
|---|---|---|
| Legacy Template Project | Project tạo từ catalog cũ, có thể chứa placeholder/media binding | Không scan/open trong Gallery; giữ V2/store cho recovery/import tương lai. |
| Legacy Free/NLE Project | Project do editor thủ công cũ tạo | Không mở trong UI mới; giữ nguyên trên disk, không batch migrate. |
| Future Template Instance | Project từ Media Binding + Template Compiler mới | Contract/flow chưa tồn tại trong Task 3.0A. |
| UNKNOWN | Không đủ metadata để phân biệt loại legacy | Mặc định bảo toàn; không suy luận từ title/tên folder. |

## Hành vi chuyển tiếp

- Route public mở project cũ vào NLE đã bị loại.
- Gallery không có combobox Mở dự án hay Dự án trống.
- Backend GET /api/v1/video/projects/{project_id}, save và V1→V2 migration vẫn được giữ; Task 3.0A không gọi chúng trên dữ liệu cá nhân.
- Project Library tương lai phải báo unsupported/UNKNOWN và từ chối mutation; migration/import cần backup, hash và test riêng.

Không tuyên bố đã phân loại từng project hiện có vì Task không quét workspace cá nhân.
