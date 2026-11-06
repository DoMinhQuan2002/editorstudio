# Screen 05 — Save & Reopen

## Commit

- Thay media bắt đầu từ bindings của draft đang mở, validate media qua Media Selection rồi cập nhật cùng Project V2.
- Chỉ slot đổi media ID bị cập nhật; slot khác giữ ID, source timing và thuộc tính.
- Audio chỉ commit nếu đúng một track được hỗ trợ và volume/mute khác hiện trạng.
- Cập nhật gửi đến PUT /api/v1/video/projects/{projectId}. Response phải có cùng Project ID và revision kế tiếp trước khi client nhận commit.
- Sau commit, frame và video proxy được dựng lại theo revision mới. UI không tuyên bố hoàn tất khi render hoặc kiểm chứng playback lỗi.

## Conflict và lỗi

- HTTP 409: giữ nguyên bản trên server, không ghi đè; yêu cầu mở lại revision mới.
- Media/template validation hoặc render thất bại: báo lỗi, không đánh dấu preview mới hợp lệ.
- Request frame cũ hoàn tất muộn: request ID/revision guard bỏ kết quả.
- Project V2 và file source không bị xóa khi user quay lại hoặc mở preview lỗi.

## Mở lại

- Gallery tìm bản nháp template đã lưu gần nhất, mở Project ID hiện có rồi tải lại Project V2 từ backend.
- Template ID/version, bindings và revision lấy từ snapshot đã lưu; không dựng bản sao và không silent downgrade.
- Preview proxy có thể được dựng lại từ Project V2; proxy cache không phải nguồn dữ liệu chuẩn.
- Nếu media reference thiếu, backend trả lỗi rõ ràng và preview không được tuyên bố hợp lệ.

Job processing đang chạy không thể khôi phục sau khi backend khởi động lại vì job manager lưu trạng thái trong bộ nhớ. Project V2 đã lưu vẫn mở lại được qua mục Bản nháp.
