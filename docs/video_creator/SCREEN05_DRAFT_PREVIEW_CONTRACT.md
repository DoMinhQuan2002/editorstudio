# Screen 05 — Draft Preview Contract

## Nguồn và tính hợp lệ

Nguồn preview là Project V2 đã được processing job lưu ở Screen 04. WPF tải project theo projectId, rồi xác minh Project ID, Template ID/version, media references và khả năng dựng Composition Graph từ snapshot hiện tại. Template demo, poster hay ảnh mẫu không được dùng thay composed draft.

## API

| Mục đích | Giao kèo |
| --- | --- |
| Đọc draft | GET /api/v1/video/projects/{projectId} |
| Dựng frame/timestamp | POST /api/v1/video/projects/{projectId}/preview/frame?timestamp_ticks={ticks} với snapshot Project V2 |
| Dựng video playback | POST /api/v1/video/projects/{projectId}/preview/video với snapshot Project V2 |
| Lưu draft | PUT /api/v1/video/projects/{projectId} với Project V2 và revision hiện tại |

Endpoint video mới dùng Composition Graph/renderer hiện có. Nó tạo MP4 proxy tạm tối đa 540×960, giữ timing, layers, text/overlay và audio theo graph; proxy không phải file export cuối. Response có content type video/mp4, signature ftyp, revision và source fingerprint. Tệp proxy được cache trong thư mục ứng dụng của user, không ghi đè Project V2 hay source media.

Endpoint frame trả PNG cùng graph version, frame index, source fingerprint, renderer và revision.

## Chống kết quả cũ

- Mỗi request frame có request ID tăng dần và cancellation token. Chỉ request mới nhất của cùng revision cập nhật UI.
- Kết quả frame có revision khác snapshot hiện tại bị bỏ qua.
- Sau khi lưu, preview được dựng lại từ snapshot mới; MediaElement phải mở file và duration phải khớp duration graph trong sai số một giây.
- Lỗi 409 khi project đã đổi ở nơi khác không được ghi đè. UI yêu cầu tải lại phiên bản mới.
- Draft chưa hợp lệ, đang render hoặc còn thay đổi chưa commit không được đưa sang Screen 06.
