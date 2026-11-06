# Screen 04 — Backend integration

## Luồng

1. MediaSelectionViewModel kiểm tra binding bằng endpoint prepare hiện có. Nút Tiếp theo chỉ bật khi đủ binding hợp lệ.
2. VideoCreatorGalleryViewModel tạo/giữ selection session và chuyển request/template version/bindings vào VideoCreatorProcessingViewModel.
3. WPF gọi POST /api/v1/video/processing-jobs rồi poll GET mỗi khoảng 700 ms; khi có lỗi kết nối, retry poll chậm hơn.
4. FastAPI tiền kiểm template catalog, version, payload, metadata và file. API dùng VideoJobManager hiện có với job_type template-processing.
5. Worker gọi prepare_payload và generic compile_template, xác minh Project V2, build Composition Graph, kiểm tra audio và dùng renderer hiện có để tạo PNG frame.
6. Worker lưu Project V2 và đọc lại. Sau khi stage prepare_preview completed, job mới chuyển sang SUCCEEDED/100.
7. WPF đọc Project V2 qua API, xác thực ID/template/version/bindings/references, rồi gọi preview API và kiểm tra chữ ký PNG. Chỉ khi bước này thành công VM mới hiển thị handoff thành công.

## Phạm vi template

Task 3.3 đã xác minh mapping legacy rõ ràng cho Denim Story, Travel Reel và Product Intro; các mapping nằm trong media_selection và giữ nhãn 1.0.0-legacy. Chúng được chuyển thành Template Definition hợp lệ để dùng generic compiler của Task 3.4. Không suy diễn mapping scene sang slot cho template khác. Fall Diary và template REFERENCE_ONLY vẫn bị từ chối.

## Dịch vụ được dùng lại

- Template Catalog và Template Compiler hiện có.
- Project V2 model/store.
- Composition Graph builder và preview frame renderer.
- VideoJobManager riêng của Video Editor.
- API client WPF hiện có cho project và preview.

Không thay đổi schema Project V2 và không dùng Image Tools job manager. Giai đoạn này không gọi final MP4 render.

## Bằng chứng

Runtime Denim Story đã hoàn tất, trả draft project cffbe37b7b85453483b650883fb70851. WPF xác nhận Project V2 và render preview qua API trước khi hiển thị success. Regression suite riêng có kiểm thử payload, idempotency, binding change, reference-only/missing-media rejection, graph/project persistence và handoff.
