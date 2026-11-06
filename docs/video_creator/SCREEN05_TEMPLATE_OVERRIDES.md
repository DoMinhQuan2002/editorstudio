# Screen 05 — Template Overrides

## Nguồn dữ liệu chuẩn

Template Definition/version là cấu trúc gốc. Project V2 là representation đã compile cho preview/export và giữ metadata template instance cùng media bindings. Không thêm store override song song có thể ghi đè lên Project V2.

## Thay media

- Binding canonical nằm trong templateMetadata.templateBindings.
- Mỗi clip được đối chiếu qua templateMetadata.slotId.
- Chỉ clip có slot binding đổi media ID mới bị cập nhật; slot không đổi giữ media ID, source timing và thuộc tính hiện tại.
- Tên mẫu, Template ID, definition version, project ID, event, timing và style không đổi.

## Audio

Với đúng một audio track, volume được lưu vào trường volume của audio track trong Project V2; mute được lưu trên lane track canonical. Thay đổi được lưu trong cùng project với revision kế tiếp.

Khi không có track hoặc có nhiều track không được hỗ trợ, chỉnh sửa audio bị khóa. Mute/unmute trong player chỉ là mute khi xem và không được coi là audio override.

## Text, sticker và style

Denim Story hiện hành chưa khai báo text field editable. UI không tạo text override hay sửa chữ raster. Sticker, layout, crop và style cũng không mở nếu Template Definition/renderer chưa công bố capability tương ứng.

## Revision

Mọi commit giữ nguyên Project ID, Template ID và Template Definition version. Backend xác thực và tăng revision; khi nhận conflict, client không ghi đè dữ liệu mới hơn.
