# Replace video crash — root cause và bằng chứng

Trạng thái: PASS cho chẩn đoán và sửa lỗi; WPF Replace stress vẫn PARTIAL.

## Triệu chứng

Windows Error Reporting ghi Python process thoát với 0xc0000374, fault module ntdll.dll, sau khi Replace video. Mã exception phù hợp với heap corruption nhưng không xác định vị trí ghi hỏng. Không kết luận từ mã exception đơn lẻ.

## Tái hiện và cô lập

Native reproducer dùng một video H.264 360×640. Frame đầu giải mã được. Một lần gọi decode ở 125 ms hoặc 1000 ms đã đủ để tái hiện trên đường buffer cũ, nên concurrent preview/filmstrip không phải điều kiện cần. Trace cho thấy:

1. Decoder mở stream, seek và lấy được frame YUV.
2. sws_scale trả về đủ số dòng đầu ra.
3. Lỗi heap xuất hiện lúc SwsContext được giải phóng, sau khi conversion hoàn tất.
4. Destination là std::vector RGBA/BGRA có đúng width × height × 4 byte, không có phần đệm đuôi.
5. Cấp phát thử nghiệm thêm 64 byte FFmpeg padding sau packed plane, rồi copy row-by-row phần pixel hợp lệ, làm reproducer chạy qua timestamp khác 0 mà không crash.

Kết luận có căn cứ nhất: optimized swscale path ghi/chạm vùng đệm cuối plane vượt qua buffer packed có kích thước chính xác; heap bị hỏng và chỉ phát hiện khi native allocator giải phóng resource tiếp theo. Tài liệu FFmpeg mô tả API scale và quy tắc alignment/padding của frame/buffer, còn việc áp dụng 64 byte đúng với trường hợp này được xác nhận bởi reproducer đối chứng: [libswscale](https://ffmpeg.org/doxygen/trunk/group__libsws.html), [AVFrame](https://www.ffmpeg.org/doxygen/trunk/structAVFrame.html).

Không thu được crash stack WER đầy đủ. Bằng chứng là instrumentation native, lỗi có thể lặp ở một decode duy nhất, và so sánh giữa destination cũ với destination có padding. Concurrent requests được thử riêng sau bản sửa.

## Bản sửa

Trong backend/native/video_engine/src/video_engine.cpp, helper scale_frame_to_packed_32bit:

- Tính packed row bytes và tổng byte pixel.
- Cấp destination bằng av_mallocz(packed_bytes + AV_INPUT_BUFFER_PADDING_SIZE).
- Đưa stride thực tế cho sws_scale và yêu cầu returned rows bằng height.
- Dùng unique_ptr với av_free để giải phóng mọi nhánh lỗi.
- Copy mỗi hàng pixel hợp lệ vào output vector có kích thước chặt khít.
- Được gọi cho cả API decode RGBA và WPF DecoderSession BGRA.

Không sửa bằng retry/restart backend, không bỏ filmstrip hoặc preview, không nuốt lỗi C++.

## Kiểm chứng sau sửa

- backend/tests/test_native_decode_padding_task2.py: timestamp 0, 125, 250, 1000, 1500 ms; concurrent same-source frame decode; persistent BGRA decoder. PASS.
- Native Release x64 build: PASS.
- Native DLL SHA-256: D1745C7F5D2A7F0B974753DE72DE1DBC189F6BEF48F9A3983C49CCCA6D261645. DLL copy trong WPF output cùng hash và được hai process test nạp.
- API stress cuối với thư mục riêng: trace có 20 replace_begin/20 replace_end; 4 lần frame preview chạy đồng thời filmstrip 24 frame; 10 vòng Replace → undo → redo mô phỏng bằng PUT, deep copy và assert mediaId ở từng trạng thái; GET dự án sau save; render H.264 có audio/video; ffprobe xác nhận stream, FFmpeg giải mã toàn bộ. PASS, revision 51. Trace và MP4 nằm trong scratch/backend_stress_phase0_final.

Hai lượt stress thử trước không tính làm bằng chứng: lượt đầu dùng shallow-copy cho undo; lượt kế tiếp cắt nhầm vòng Replace khi sửa history script. Bản cuối được dựng lại từ script gốc và trace xác nhận đủ 20 lần Replace. Đây vẫn là kiểm chứng persistence/API, không thay cho Undo/Redo bằng nút WPF.
- Backend test WPF vẫn sống sau thao tác import/preview/save/reopen/audio; log không có ERROR, traceback hoặc CRITICAL.

Giới hạn: stress 20 lần ở lớp API, không phải 20 lần bấm Replace trên WPF. UI Replace trong project thường và Replace lặp trong Template Editor còn cần nghiệm thu.

## Artifact điều tra

Thư mục D:\MediaStudioTask2Validation_20261021_1328 được giữ nguyên, gồm các native trace, DLL/PDB, logs, test project, stress script và exported.mp4. Không xóa crash evidence hoặc output build cũ.

## Bổ sung kiểm định Task 2.0A — 21-10-2026

Helper `scale_frame_to_packed_32bit` được tăng cường kiểm tra trước cấp phát: kích thước frame dương và trong giới hạn engine, phép tính row bytes/packed bytes không tràn, kích thước cộng padding nằm trong `size_t`, cache limit và `vector::max_size()`; stride đích phải dương và đủ một hàng trước khi copy. `output.resize` bắt lỗi cấp phát/độ dài và để RAII giải phóng buffer FFmpeg cùng `SwsContext`.

Native regression hiện kiểm tra 6 fixture riêng ở `D:\MediaStudioTask2Validation_20261021_1328\scratch\native_matrix_2_0a`: 360×640 có A/V, 640×360 không audio, 1280×720, 1920×1080 có A/V, odd-size 641×359 H.264 4:4:4, và 640×360 A/V 15 giây. Probe xác nhận kích thước/luồng; test decode nhiều timestamp, seek xuôi-ngược trên session BGRA, decode RGBA đồng thời, buffer size, và swizzle RGBA/BGRA theo từng kênh. Release ma trận và AddressSanitizer ma trận đạt.

ASAN dynamic runtime được nạp. Khi test đầu để cache toàn cục chứa frame tới lúc Python tháo DLL, một lượt kết thúc lỗi allocator trong destructor của `g_frame_cache`, sau khi pytest đã hoàn tất. Regression dọn cache tường minh trước khi DLL unload; lượt ma trận ASAN cuối thoát mã 0, không có báo cáo ASAN. Điều này được ghi nhận như host/teardown caveat; không diễn giải nó thành kết quả kiểm thử Replace UI.

DLL Release mới và bản sao trong WPF output cùng SHA-256 `B9CEA237317227B73ECAECCE7F0252689AEC2C11B8CBCB360752D089C584D3DF`. WPF validation app PID 36524 và backend PIDs 21532/15496 đang phản hồi. Log mới không có ERROR, traceback, CRITICAL hoặc backend exit.

Kết quả giao diện vẫn chưa đóng: không có WPF GUI automation trong phiên này. Video drag/drop, Replace stress 20 lượt, thao tác audio đầy đủ, preview/audio sync và export từ WPF tiếp tục BLOCKED; API stress cũ không thay được kiểm tra UI. Ma trận đầy đủ ở `VIDEO_EDITOR_TASK2_0A_WPF_ACCEPTANCE_REPORT.md`.
