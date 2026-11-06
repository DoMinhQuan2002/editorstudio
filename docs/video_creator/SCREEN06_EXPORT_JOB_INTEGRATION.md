# Screen 06 — export job integration

## API

- `GET /api/v1/video/projects/{projectId}/export-capabilities`
- `POST /api/v1/video/projects/{projectId}/export-jobs`
- `GET /api/v1/video/jobs/{jobId}`
- `DELETE /api/v1/video/jobs/{jobId}`

POST tạo `VideoCreatorExportRequest`: request ID, draft revision, template ID/version, composition fingerprint, committed bindings, quality, output directory/name và overwrite confirmation.

## Validation và renderer

Backend đọc Project V2 từ store, xác thực revision/template/version, rebuild Composition Graph, so fingerprint và bindings, kiểm tra media reference/capability, destination, tên file, writable directory, collision và không ghi đè source media. Sau đó dùng `VideoJobManager` hiện có và `render_composition_project`/FFmpeg graph renderer. WPF không tự chạy FFmpeg và không tạo renderer riêng.

## Progress/lifecycle

Job có trạng thái queued/processing/succeeded/failed/cancelled. Progress đến từ tiến trình FFmpeg và encode stage; UI poll mỗi 450 ms, khóa Export trong lúc job chạy, và 100% chỉ sau probe/decode/publish. Cancel gọi DELETE job. Request ID idempotent ngăn double-click tạo export trùng; retry sau failure tạo request ID mới. Khi mất kết nối, UI giữ ID và truy vấn lại đúng job.

## Runtime evidence

Job thật `7625b9e5ced642f09f6c7f63a16cc931` hoàn tất trong khoảng 24 giây tại runtime. Backend log lưu các GET `/jobs/{jobId}` và renderer completion. Export history sidecar ghi project/revision/fingerprint/settings/path/size/status. Job manager hiện giữ job trong memory; history chỉ ghi record hoàn tất, chưa cung cấp khôi phục job đang chạy sau restart.
