# CapCut 9.6.0 — drag/drop reference matrix

> **RETIRED_PRODUCT_REQUIREMENT (TASK 3.0A):** yêu cầu mô phỏng CapCut 9.6.0 và drag/drop NLE đã bị hủy. Nội dung dưới đây là lịch sử reference, không còn là tiêu chí phát triển sản phẩm.

> **Cập nhật Task 2.1 (2026-10-21):** matrix reference bên dưới vẫn phản ánh bằng chứng CapCut có sẵn. Phần trạng thái triển khai hiện tại được bổ sung cuối tài liệu; không diễn giải thay đổi model là thay đổi semantics CapCut.

Trạng thái: PARTIAL. Matrix phân biệt bằng chứng đang có với thao tác chưa được xác minh. CapCut 9.6.0 là phiên bản chuẩn theo yêu cầu người dùng; số build chưa xác minh độc lập.

| Tình huống | CapCut 9.6.0: trạng thái/hành động/kết quả thấy được | Media Studio hiện tại | Trạng thái |
|---|---|---|---|
| Kéo media ra ngoài timeline | Video tham chiếu cho thấy media thumbnail được giữ dưới con trỏ như floating item, nằm ngoài lane; người dùng chỉ rõ đây chưa phải clip đã commit. | WPF có ghost nhưng ảnh kiểm tra trước đây cho thấy một thanh ngang teal lớn phủ qua editor, không giống card thumbnail nổi. | PARITY_FAIL về ghost; hover chưa nghiệm thu trên bản hiện tại. |
| Kéo vào toàn vùng timeline | Người dùng nêu timeline là toàn bộ vùng được khoanh, không chỉ hàng video; clip mới chỉ đổi trạng thái khi pointer vào timeline. | Vùng drop được resolve theo track/position bởi View.xaml.cs và MediaTimelineDropResolver; chưa thử trực tiếp video drag trên WPF lượt này. | IMPLEMENTED_UNVERIFIED |
| Kéo vào Main Visual trống | Tham chiếu thấy block visual turquoise và thumbnail trong lane. Chưa xác minh chính xác thời điểm preview đổi từ floating card sang timeline block. | Main visual và empty drop surface có trong projection; thêm media bằng nút cộng đã chạy, drag chưa chạy. | OBSERVED / IMPLEMENTED_UNVERIFIED |
| Clip thay thế placeholder | Template Media Studio giữ slot rỗng, tên scene, thời lượng 3 giây. Người dùng muốn clip sau khi thả vào slot có độ dài theo thời lượng timeline đã cấu hình. CapCut drop semantics cần quay rõ. | API/VM insert và Replace handler tồn tại; stress API gán media vào scene. UI thả vào slot chưa kiểm tra. | REFERENCE_PENDING / IMPLEMENTED_UNVERIFIED |
| Kéo lên clip đang có | Phần hiện có chưa chứng minh hover target, viền, replace popup hay vùng commit/cancel. | Replace dialog có handler; chưa kiểm tra chuột WPF. | REFERENCE_PENDING |
| Kéo vào gap giữa clip | Chưa có frame rõ để xác nhận insert làm clip sau dịch, tạo overlap hay ripple. | Resolver tính vị trí timeline; video model API chưa lưu start độc lập nên chuỗi clip vẫn tuần tự. | REFERENCE_PENDING |
| Drop lên visual track thứ hai | Chưa có bằng chứng trực quan đủ rõ. | Chưa có multi-track visual model. | BLOCKED |
| Kéo audio lên visual | CapCut tham chiếu cho thấy audio được đưa vào lane audio riêng ở timeline. Chi tiết lane target và waveform chưa đủ rõ. | Metadata audio được route sang audio; WPF test WAV qua nút cộng đã tạo Âm thanh 1, nhưng kéo từ media library chưa thử. | OBSERVED / IMPLEMENTED_UNVERIFIED |
| Kéo file không hỗ trợ | Chưa quan sát. | Resolver từ chối metadata không hợp lệ và hiển thị mô tả. | REFERENCE_PENDING |
| Drop ngoài vùng hợp lệ | Hành vi cancel khi thả chuột ngoài chưa thấy rõ. | Có logic resolution/cancel; UI chưa xác nhận trạng thái dự án sau thả. | REFERENCE_PENDING |
| Drag preview theo pointer | Contact sheet có trạng thái media nổi ngoài lane; không đủ độ phân giải để kết luận duration/hover feedback theo từng frame. | WPF ghost visual và status message có; visual mismatch được ghi ở hàng đầu. | PARTIAL |
| Snap khi đặt clip | Không có khoảng cách snap/guide rõ trong nguồn hiện lưu. | TimelineInteractionEngine cung cấp snap candidate; chưa so trực tiếp trên WPF. | REFERENCE_PENDING |
| Undo/Redo sau drop | Toolbar thấy nút undo/redo, nhưng chưa có chuỗi drop→undo→redo trong reference. | API stress chỉ PUT state mô phỏng. WPF audio move→undo đã thử; video drop undo/redo chưa thử. | REFERENCE_PENDING |

## Hợp đồng hành vi cần chốt bằng reference

1. Khi giữ chuột ở ngoài timeline, media hiện là floating preview riêng; nó chưa được tính là clip trong timeline.
2. Khi con trỏ đi vào vùng timeline được chấp nhận, feedback phải chuyển sang dự báo vị trí/lane nhận. Người dùng mô tả block video trong lane có màu xanh lục và độ dài tương ứng cấu hình thời lượng tại timeline. Giữ đây là yêu cầu tham chiếu, chưa biến thành quy tắc cho mọi loại media.
3. Chỉ khi nhả chuột trên target hợp lệ thì thay đổi project mới commit; khi thả sai vùng hoặc hủy, project không đổi. Cần video CapCut xác nhận chi tiết điểm 2–3 và feedback cụ thể.
4. Kiểm tra hành vi riêng cho placeholder template, gap visual, clip body Replace, audio lane và vùng ngoài timeline. Không suy diễn rằng mọi drop vào timeline đều là Insert.
5. Sau commit, ghi lại playhead, selected clip, thumbnail/filmstrip, preview, duration/start, project revision và Undo/Redo.

## Cảnh cần quay để hoàn tất

- Mở project test nhỏ với một visual clip và một placeholder.
- Bắt đầu kéo từ media card; đi chậm qua khoảng trống ngoài timeline, track header, lane, clip body và cạnh clip; giữ con trỏ đủ lâu mỗi vùng để ghi hover.
- Nhả ở từng vùng riêng; chụp timeline trước/sau và preview.
- Thực hiện Cancel, Undo và Redo sau mỗi thao tác.
- Quay một lần với video, image và audio; ghi timecode và độ dài từng item.
- Quay Replace lúc filmstrip/preview đang tải.
- Mở About CapCut và chụp version/build.

## Task 2.1 delta — trạng thái kỹ thuật hiện tại

- Project V2 và API lưu clip theo track ID và timeline ticks tuyệt đối; V1 timeline được migrate thành visual track tuyến tính.
- Domain engine có lệnh move giữa track và test giữ clip ID/start. WPF chưa có luồng UI đầy đủ để người dùng thực hiện/kiểm chứng move này; hàng `Drop lên visual track thứ hai` vẫn `BLOCKED/PENDING` về parity.
- WPF dựng các hàng track từ persisted track entities và giữ empty tracks; đây là kiểm thử projection, chưa phải thao tác chuột.
- Renderer trả unsupported cho multitrack layouts chưa hỗ trợ, không flatten.
- Tất cả pending semantics trong bảng (Insert/Replace/hover/ghost/snap/ripple/undo-redo) vẫn pending. `TASK2_1_PERSISTENT_TIMELINE_READY=false`, `VIDEO_EDITOR_RELEASE_READY=false`.
