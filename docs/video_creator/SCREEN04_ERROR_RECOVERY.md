# Screen 04 — Lỗi và phục hồi

## Lỗi trước khi tạo job

Template không khả dụng/version đã đổi, thiếu binding, media không tồn tại hoặc media rỗng/không đọc được trả HTTP 422. WPF giữ ở Màn 3 và hiển thị lỗi theo flow hiện có; không có job giả hoặc draft rỗng.

## Lỗi trong job

Job trả FAILED, errorCode/errorMessage và đánh dấu stage đang chạy là FAILED. Các nhóm hiện có gồm UNSUPPORTED_FEATURE, MISSING_MEDIA, PREVIEW_UNAVAILABLE, PREVIEW_FAILED và PROCESSING_FAILED. Media gốc/binding được giữ trong UI; không xóa asset.

WPF có nút Thử lại cho lỗi preview/renderer/processing có thể thử lại và lỗi khởi tạo. Job FAILED có thể submit lại bằng cùng session/fingerprint; manager không dùng lại job đã thất bại và job mới có thể có Job ID khác. Lỗi feature/missing media cần đổi template hoặc sửa lựa chọn ở Màn 3, không được tự bỏ qua.

## Mất kết nối khi poll

VM hiển thị thông báo đang kết nối lại, tiếp tục poll với khoảng chờ tăng lên 2 giây, rồi trở về khoảng 700 ms khi kết nối lại. Lỗi poll không đổi thành success.

## Handoff không hợp lệ

Nếu identity job không khớp, thiếu stage hoàn tất/draft ID, metadata khác binding hoặc preview không phải PNG hợp lệ, VM chặn trạng thái thành công với JOB_IDENTITY_MISMATCH hoặc INVALID_HANDOFF.

## Giới hạn restart

Job state nằm trong RAM. Nếu backend dừng/khởi động lại, job không thể poll tiếp và VM chưa có cơ chế resume từ job ID. Project đã lưu có thể còn trong project store, nhưng mở lại từ UI và nối lại job thuộc công việc sau. Không tự tạo job thay thế khi chưa có phản hồi xác thực từ backend.

Hiện chưa có deadline cho toàn bộ job hoặc endpoint hủy template-processing. Lỗi/timeout ở request HTTP được xử lý như mất kết nối và tiếp tục poll; không có nút Cancel.
