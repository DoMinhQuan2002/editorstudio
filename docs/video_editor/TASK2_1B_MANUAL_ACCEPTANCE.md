# TASK 2.1B — WPF manual acceptance

## Trạng thái

**BLOCKED — chưa chạy manual WPF acceptance trong phiên này.** Không có ứng dụng/cửa sổ WPF được expose cho công cụ GUI, nên không ghi nhận drag, click, Save/Reopen, preview hay export là đã chạy. Các test .NET/API không thay thế checklist này.

Fixture an toàn có sẵn tại `artifacts/video_editor/task2_1b_validation/`; baseline là `baseline-task2-0b.mp4`, bản JSON thử nghiệm là `evidence/after-reopen.json`. Giữ nguyên thư mục fixture và không dùng project nguồn người dùng.

## Checklist cần thực hiện trên WPF

Mỗi mục cần quay lại thao tác UI và giữ JSON/log trước/sau. Ghi PASS/FAIL/BLOCKED cho từng dòng; đừng gộp kết quả.

| ID | Thao tác | Bằng chứng cần lưu | Hiện trạng |
|---|---|---|---|
| W01 | Mở bản copy V2 Denim Story | project ID/schema/revision, ảnh timeline | BLOCKED |
| W02 | Xác nhận 5 visual clips, 1 text, 1 audio; audio dài hơn visual | snapshot JSON + thời gian UI | BLOCKED |
| W03 | Tạo Free Editor mới | JSON schema 2, tracks rỗng hoặc theo contract, không placeholder/text `jeans` | BLOCKED |
| W04 | Tạo visual/text/audio track | Track ID trước/sau và UI | BLOCKED |
| W05 | Reorder track | IDs và layer order trước/sau | BLOCKED |
| W06 | Xóa track rỗng; thử xóa track có clip | track rỗng mất đúng ID; track có clip bị từ chối | BLOCKED |
| W07 | Kéo media vào một lane đích hợp lệ | video thao tác, target Track ID, clip JSON | BLOCKED |
| W08 | Kéo clip qua lane và tới thời điểm mới | Clip ID giữ nguyên, Track ID/ticks mới; clip khác không đổi | BLOCKED |
| W09 | Drop vào lane sai loại hoặc overlap cùng lane | thông báo rõ; JSON và revision không đổi | BLOCKED |
| W10 | Cancel trong lúc kéo/hover | không có Save/Undo entry, JSON không đổi | BLOCKED |
| W11 | Trim In và Trim Out video/audio | source start, timeline start, duration ticks, source bounds | BLOCKED |
| W12 | Undo rồi Redo các thao tác trên | snapshot sau mỗi bước, IDs/range/order đúng | BLOCKED |
| W13 | Save, đóng project, mở lại độc lập | before/after JSON và cùng Track ID/Clip ID/ticks/order | BLOCKED |
| W14 | Mở cùng project ở hai phiên, Save bản cũ | conflict hiển thị, dữ liệu mới không bị ghi đè | BLOCKED |
| W15 | WPF Preview tại các mốc scene/audio | video capture hoặc frame samples, thông báo capability | BLOCKED |
| W16 | Export bằng nút WPF | log/job, MP4, inspect_export JSON, full decode, so baseline | BLOCKED |

## Quy tắc chấp nhận bằng chứng

- Replace chỉ được tính nếu video cho thấy thao tác UI và JSON cho thấy binding của đúng Clip ID thay đổi. Không dùng số API PUT.
- Drag preview/hover không được làm thay đổi project. Drop cancel hoặc sai target phải giữ dữ liệu và revision.
- Chụp before/after từ project file/API sau lần Save thật và một lần mở mới, không chỉ đọc ViewModel chưa lưu.
- Giữ lại raw video, JSON, backend log, export MP4 và `inspect_export.py` output trong thư mục evidence.
