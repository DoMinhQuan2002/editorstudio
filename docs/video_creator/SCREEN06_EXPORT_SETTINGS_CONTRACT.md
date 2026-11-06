# Screen 06 — export settings contract

## Draft handoff

`Screen6DraftHandoff` mang:

- `DraftProjectId`, `DraftRevision`
- `TemplateId`, `TemplateVersion`
- `CompositionFingerprint`
- media bindings đã commit
- composition reference
- đường dẫn preview cache cùng revision

Override mà Screen 5 hỗ trợ được lưu trong Project V2 canonical; Screen 6 handoff mang revision/fingerprint của graph đó thay vì gửi một override set thứ hai có thể lệch. Nút Next bị khóa nếu draft chưa sẵn sàng, audio còn thay đổi chưa lưu, playback chưa xác minh hoặc fingerprint/preview thiếu. Template runtime đã test không khai báo field chữ editable.

## Capability API

`GET /api/v1/video/projects/{projectId}/export-capabilities` là nguồn cho UI. Payload chứa revision, template/version, fingerprint, bindings, width/height, fps numerator/denominator, duration/timebase, qualities, format/codecs, audio presence, cancel capability và lý do nếu không hỗ trợ.

## Cấu hình được phép hiển thị

| Setting | Hợp đồng |
|---|---|
| Độ phân giải | Giữ nguyên width/height Composition Graph. Runtime: 1080×1920. |
| Frame rate | Giữ nguyên rational fps từ Project V2. Runtime: 30/1. Không resample hoặc đổi duration. |
| Container/video | MP4 + H.264. MOV không được quảng bá. |
| Audio | AAC chỉ khi graph có audio nguồn hợp lệ và encoder AAC có mặt. Không tạo track im lặng giả. |
| Quality | `standard` → CRF 21 / medium; `high` → CRF 17 / slow. Đây là cấu hình encode thật, không phải tên hiển thị cùng cấu hình. |
| File name | Tối đa 120 ký tự, Windows-invalid/reserved names bị chặn, `.mp4` chỉ xuất hiện một lần. |
| Folder | Absolute path; nếu chưa tồn tại, backend chỉ tạo một thư mục con khi parent đã tồn tại. UI hiển thị free space nếu hệ điều hành cung cấp; backend kiểm tra quyền ghi bằng file probe trước khi render. |
| Overwrite | Tên file đã tồn tại yêu cầu xác nhận. Destination được publish sau verify; không xóa bản cũ trước. |

Screen 06 không cho đổi resolution/fps vì endpoint hiện không có scaling/time mapping tương ứng. Capability không đủ hoặc graph có thuộc tính renderer chưa hỗ trợ thì export bị từ chối.
