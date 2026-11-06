# Screen 06 — failure and recovery

## Hành vi

- Draft/revision/template/fingerprint/binding mismatch: API trả conflict/validation error; UI không khởi tạo renderer và yêu cầu tải lại preview.
- Missing media/unsupported composition/codec: capability hoặc job fail với thông tin nguyên nhân; không publish output thành công.
- Invalid/reserved filename, path không absolute, folder con không tồn tại và parent cũng không tồn tại, folder không writable, destination là directory, output path quá dài, source overwrite: request bị từ chối. Nếu chỉ thiếu folder cuối và parent đã tồn tại, backend tạo đúng một thư mục con rồi thử quyền ghi.
- Existing output: UI hỏi xác nhận overwrite. API không ghi đè nếu `overwrite=false`; publish file mới chỉ sau validate.
- Disk space: UI hiển thị free space nếu đọc được; backend rechecks required space trước publish. Không có ước tính trước encode.
- Renderer/FFmpeg/probe/full-decode error: job failed; staging file được dọn; source project/media không đổi; retry tạo request mới.
- Cancel: DELETE job đặt cancel event; output chỉ được publish sau renderer/probe/decode và kiểm cancel.
- Backend disconnect: UI thử poll lại cùng Job ID; nếu chưa khôi phục được, giữ job ID và khóa nút tạo job mới tới khi reconnect/query.

## Giới hạn còn lại

`VideoJobManager` giữ job runtime trong memory. Reconnect khi backend còn process dùng được cùng ID; sau restart job ID có thể không còn. Export history bền vững chỉ ghi job đã hoàn tất và hiện chưa phục hồi lifecycle running. Disk-full, locked file, cancellation và restart-recovery chưa được chạy manual trong GUI acceptance.

## Lỗi Screen 06 đã sửa

Lần mở đầu gây unhandled WPF exception vì ProgressBar mặc định binding hai chiều tới getter chỉ đọc `ProgressPercent`. Đã đổi `Value`/`IsIndeterminate` sang `Mode=OneWay`, rebuild và xác minh lại mở Screen 06, chạy job thật, nhận kết quả thành công.
