# CapCut 9.6.0 — parity baseline

> **RETIRED_PRODUCT_REQUIREMENT (TASK 3.0A):** baseline CapCut UI/interaction được nghỉ. Bảng dưới đây chỉ là hồ sơ tham chiếu lịch sử; không tiếp tục thực hiện pixel parity hoặc hành vi NLE.

> **Cập nhật Task 2.1 (2026-10-21):** đây là baseline tham chiếu tương tác và ảnh/video; cập nhật model bên dưới không được xem là CapCut parity. Dùng phần delta cuối để biết trạng thái triển khai mới.

Trạng thái baseline: PARTIAL. Tài liệu mô tả bằng chứng cục bộ và gap; không dùng phiên bản CapCut khác để bổ sung hành vi.

## Các quan sát được dùng

- Media library có thumbnail và thời lượng.
- Timeline trống có bề mặt drop lớn.
- Visual clip trong lane có thumbnail filmstrip, nhãn và màu turquoise.
- Ảnh/video người dùng chỉ rõ floating media block khi đang kéo ngoài timeline; block này khác clip đã commit trong lane.
- Người dùng chỉ rõ khi đi vào timeline, video chuyển sang block xanh lục có độ dài tương ứng cấu hình timeline.
- Ảnh audio review cho thấy lane audio riêng bên dưới visual.
- CapCut có preview, playhead, timecode, thanh zoom/scroll và các nút toolbar.

Các quan sát về hình ảnh trên không đủ chứng minh chính xác popup Replace, snapping threshold, ripple, liên kết, thứ tự layer, undo/redo, waveform processing hoặc persistence. Những mục này giữ REFERENCE_PENDING trong feature inventory và drag/drop matrix.

## So sánh Media Studio hiện tại

| Khu vực | CapCut reference | Media Studio Phase 0 | Kết luận |
|---|---|---|---|
| Floating drag | Thumbnail/card tách khỏi timeline trước khi drop | WPF có ghost, nhưng artifact trước đây là thanh ngang lớn | PARITY_FAIL về ngoại hình; WPF hiện tại cần kiểm tra lại |
| Drop surface | Toàn bộ vùng timeline nhận hover theo vùng/lane | Có vùng drop và resolver | IMPLEMENTED_UNVERIFIED |
| Main visual | Clip turquoise với nội dung thumbnail và duration | Placeholder và chuỗi visual tuần tự; add bằng plus hoạt động | PARTIAL |
| Độ dài clip | Người dùng mong block xanh phản ánh thời lượng timeline đã cấu hình | Placeholder template có thời lượng; API/video scene tuần tự | Cần chốt mapping cho source duration và template slot |
| Overlay visual | Chưa thấy thao tác overlay đủ rõ | Không có visual track độc lập trong model | PARITY_FAIL đối với multi-track |
| Audio | Lane riêng được thấy trong ảnh review | Lane audio/waveform tạo và lưu/mở WPF được | PASS cho kiểm thử audio cơ bản; parity chưa đủ bằng chứng |
| Preview | Playhead và preview tồn tại | Preview WPF phát; frame fixture khớp file nguồn | PASS cho fixture; audio sync chưa nghiệm thu |
| Save/reopen | Chưa xác minh workflow CapCut từ reference | WPF save/reopen giữ video/text/audio test | PASS cho kịch bản WPF đã thử |
| Export | Chỉ thấy nút Xuất | API native export có audio/video và decode toàn file | PASS API; WPF export pending |

## Trạng thái baseline

- OBSERVED: phần hiển thị trực tiếp trong các ảnh/video tham chiếu hoặc mô tả người dùng được gắn nhãn quan sát.
- REFERENCE_PENDING: semantics yêu cầu frame rõ hơn hoặc thao tác trực tiếp.
- IMPLEMENTED_UNVERIFIED: code có nhưng WPF chưa chạy qua thao tác đó.
- PARITY_FAIL: visual ghost mismatch và thiếu visual multi-track model.
- PARITY_PASS: chưa tuyên bố parity tổng thể nào. Một số hành vi WPF cơ bản đã PASS nhưng đó không đồng nghĩa với parity CapCut.

## Điều kiện đóng baseline

1. Xác nhận CapCut About/build number là 9.6.0 và lưu ảnh.
2. Thu recording rõ pointer và timeline ở các đoạn hover/drop/commit/cancel.
3. Ghi trạng thái trước/sau cho Insert, Replace, Overlay, audio, snap, magnet/linkage/ripple, trim, split, delete và history.
4. Dùng cùng project/media khi so: clip duration ngắn, video dài, image, audio WAV/MP3, text.
5. Chỉ nâng mục lên PARITY_PASS sau khi có hành động reference và WPF result cùng kiểm thử undo/save/reopen.

## Task 2.1 delta — kiến trúc editor

- Backend canonical store/API hiện dùng Project Model V2 persistent tracks và absolute timeline ticks; Free Editor và Template initialization cùng dùng V2.
- WPF đọc persistent track IDs/order/ticks; model/store/API tests và .NET projection tests pass. Không có WPF manual acceptance mới trong Task 2.1.
- Current renderer vẫn chỉ nhận một phần tuyến tính; multitrack preview/export bị từ chối rõ ràng. Chưa tái xuất hoặc so sánh decoded frames/audio của Denim Story V2 với MP4 baseline Task 2.0B.
- Parity reference version/build vẫn chưa xác minh bằng About. Các quan sát/hành vi CapCut chưa được quay rõ tiếp tục `REFERENCE_PENDING`.
- Current Task 2.1 flags: model ready true; persistent timeline ready false; linear render compatible false; CapCut reference complete false; multitrack compositor verified false; product release ready false.
