# Screen 04 — Processing job contract

## Tạo job

POST /api/v1/video/processing-jobs trả HTTP 202 và snapshot hiện tại. Request fields:

| Field | Ý nghĩa | Quy tắc |
|---|---|---|
| templateId | ID từ catalog | Bắt buộc |
| templateDefinitionVersion | Phiên bản definition đã chọn | Bắt buộc, phải khớp catalog |
| selectionSessionId | Session của Màn 3 | 32 ký tự hex chữ thường |
| bindings | Map slot ID → media asset ID | Bắt buộc; phải bao phủ đúng slot bắt buộc |

Server xác thực availability/version, payload Màn 3, metadata, loại media, đường dẫn file và khả năng đọc file trước khi submit. Template REFERENCE_ONLY bị từ chối; lỗi tiền kiểm trả HTTP 422. Không tạo job nếu tiền kiểm thất bại.

## Poll job

GET /api/v1/video/processing-jobs/{job_id} trả snapshot. Các field chính:

- jobId, projectId, jobType, jobStatus, progress/progressPercent, stage, currentStage.
- templateId, templateVersion, selectionSessionId, bindingFingerprint.
- stages: stageId, name, status, message, errorCode.
- errorCode/errorMessage khi lỗi.
- draftProjectId, compositionReference, previewReference sau khi lưu bản nháp.
- createdAt, updatedAt.

Các trạng thái public viết hoa: QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED. Job template-processing giữ progressPercent null trong lúc chạy; 100 chỉ được gán sau khi frame preview PNG và Project V2 đã lưu thành công.

## Idempotency và identity

Fingerprint SHA-256 tính từ template ID, version và bindings đã sắp xếp theo slot ID. Idempotency key ghép selectionSessionId và fingerprint. WPF kiểm tra job ID, template/version/session/fingerprint trước khi áp dụng snapshot. Binding thay đổi tạo fingerprint khác và job khác.

## Handoff references

- compositionReference trỏ tới GET /api/v1/video/projects/{draftProjectId}.
- previewReference trỏ tới /api/v1/video/projects/{draftProjectId}/preview/frame?timestamp_ticks=0.
- Handoff chỉ được WPF chấp nhận khi job succeeded, stage prepare_preview completed, draft ID hiện diện, metadata/bindings khớp và endpoint preview trả PNG hợp lệ.

## Tuổi thọ

VideoJobManager lưu job/future/idempotency map trong bộ nhớ. Poll job không tồn tại sau khi backend restart. Project V2 được tạo qua project store đang dùng; khả năng mở project từ các màn Dự án/Screen 05 chưa thuộc task này.
