# Screen 04 → Screen 05 handoff

## Dữ liệu bàn giao

Khi job thực sự thành công, snapshot cung cấp:

- draftProjectId: ID của Project V2 đã lưu.
- compositionReference: endpoint đọc Project V2/Composition Graph.
- previewReference: endpoint dựng frame preview.
- templateId/templateVersion, selectionSessionId và bindingFingerprint để xác nhận danh tính.

Ví dụ runtime: draftProjectId cffbe37b7b85453483b650883fb70851. Runtime dùng Denim Story với một ảnh logo test được phép reuse cho năm vị trí. Stage nhạc được SKIPPED vì definition không khai báo audio track.

## Điều kiện chấp nhận handoff

Screen 05 chỉ nên nhận draft khi jobStatus là SUCCEEDED, prepare_preview là COMPLETED, draft ID/references trỏ cùng project, Project V2 có đúng template/version/bindings và preview endpoint trả PNG hợp lệ. WPF hiện thực việc xác minh này trước khi hiển thị success.

## Trạng thái sản phẩm hiện tại

Screen 05 chưa triển khai. Screen 04 hiển thị SCREEN05_PENDING và draft ID; không mở trang trắng, không tạo editor giả và không render MP4. Tích hợp tiếp theo có thể dùng draftProjectId cùng các references này để mở project vào màn xem/chỉnh sửa nhẹ.

Job polling hiện chỉ bền trong tuổi thọ tiến trình backend. Handoff project đã lưu, nhưng nối lại một phiên job sau backend restart chưa hỗ trợ.
