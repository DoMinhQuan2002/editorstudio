# TASK 2.1B — WPF persistent timeline integration

## Kết luận riêng cho WPF

**Trạng thái: PARTIAL / BLOCKED — chưa nghiệm thu tương tác GUI.** WPF build và automated command tests đạt; trong phiên kiểm chứng không có cửa sổ/app WPF khả dụng để chạy thao tác chuột và lưu bằng chứng. Vì thế không đánh dấu `TASK2_1_PERSISTENT_TIMELINE_READY=true`.

## Đường dữ liệu

```text
WPF drop row / ruler
  → resolve TrackId + ticks
  → TimelineV2EditCommands
  → validate kind, placement, canonical IDs
  → API Save V2 with revision
  → VideoProjectStore
  → rebuild WPF rows from stored tracks
```

Một số inspector command vẫn sửa các collection tương thích (`clips[]`, `textLayers[]`, `audioTracks[]`); trước Save, `ApplyEditorProjections` yêu cầu projection đầy đủ, đúng clip ID, đúng track ownership rồi mới dựng `tracks[].clips`. Các clip canonical bị thiếu sẽ làm Save thất bại. Đây là biện pháp chống mất dữ liệu, nhưng chưa đáp ứng mục tiêu “mọi command sửa canonical trực tiếp”.

## Tích hợp đã có trong code

- Nút dự án trống nối tới API Free Editor; API/model test xác nhận schema V2 không chứa clip giả.
- Tạo track loại visual/text/audio bằng persistent Track ID; reorder lưu `LayerOrder`; chỉ xóa track rỗng.
- Drop resolver lấy hàng WPF thực tế làm target, chuyển pointer position qua scroll/zoom/ruler thành vị trí timeline. Add visual/audio dùng lane ID đó; cross-track move giữ clip ID, source range và timestamp do resolver cung cấp.
- Same-track overlap trả `REFERENCE_PENDING` và giữ dữ liệu. Audio không tự chuyển lane để tận dụng khoảng trống.
- Save kiểm tra project schema 2 và projection completeness. Revision cũ nhận conflict thay vì silent overwrite.
- Preview hiển thị cảnh báo và chặn playback khi capability API từ chối layout chưa hỗ trợ.

Các nút track là điều khiển tối thiểu/tạm thời để quản lý persistent tracks. Chúng chưa phải kết luận thiết kế UX CapCut.

## Undo/redo và trim

- WPF undo/redo ghi snapshot project trước thao tác rồi PUT snapshot phục hồi. Nó bảo toàn project snapshot trong code path, nhưng **không gọi history của `TimelineEngineV2`**; điều kiện tích hợp engine trong task chưa đạt.
- Video/audio trim được tính trong ViewModel từ edge delta và source duration, rồi gọi `TimelineV2EditCommands.TrimClip` để cập nhật canonical ticks và compatibility projection. Tests kiểm tra tick range, audio lane identity và overlap refusal. WPF drag thật và source-bound behavior vẫn chờ acceptance.
- Chưa có kiểm thử WPF end-to-end cho hover/cancel/drop invalid, drag qua lane, trim hai mép, undo/redo GUI hoặc Save/Reopen bằng app.

## Persistence evidence độc lập

API/store thử trên project copy: schema V2 sau migration và reopen; revision 8 sau save/reopen; 3 persistent tracks (visual/text/audio), 5 visual clips; IDs/order giữ nguyên. Đây là bằng chứng data model/API, không phải bằng chứng WPF.

## Kiểm thử code

- `dotnet build src/MediaStudio.Desktop/MediaStudio.Desktop.csproj --no-restore`: 0 warning, 0 error.
- `dotnet test src/MediaStudio.Desktop.Tests/MediaStudio.Desktop.Tests.csproj --no-restore`: 122 passed, 0 failed, 0 skipped.
- `TimelineV2EditCommandTests` bao gồm ID/tick cross-track move, reorder/empty-track persistence, cùng-lane overlap refusal, canonical clip thiếu trong projection, và audio lane identity/overlap refusal.

Build và unit tests không thay thế manual WPF acceptance. Danh sách các case còn chờ nằm trong [TASK2_1B_MANUAL_ACCEPTANCE.md](TASK2_1B_MANUAL_ACCEPTANCE.md).
