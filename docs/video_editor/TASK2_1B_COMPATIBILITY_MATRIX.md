# TASK 2.1B — Compatibility matrix

| Khả năng | Trạng thái riêng | Bằng chứng | Giới hạn |
|---|---|---|---|
| V1 → V2 migration | PASS automated | Backup hash, migration, source V1 hash không đổi | Bản thử nghiệm cô lập; chưa audit toàn bộ thư mục user |
| V2 API/store Save/Reopen | PASS automated | Revision 8 giữ nguyên; IDs/order/ticks ổn định | Không phải WPF mouse acceptance |
| Revision conflict | PASS automated | stale revision trả HTTP 409, không overwrite | Chưa chạy hai phiên WPF đồng thời |
| Empty persistent tracks | PASS automated | Giữ track rỗng qua API/store | Chưa kiểm tra GUI |
| Free Editor model | PASS API/model | V2 rỗng, không placeholder | Nút WPF đã wire nhưng chưa chạy GUI |
| Denim Story template model | PASS API/model | 5 placeholder 3 s và text; metadata theo model test | Chưa mở/tạo/reopen bằng WPF trong phiên này |
| WPF persistent track rows | PARTIAL | Rows/DTO gắn ID và layer order; build/tests pass | Không có runtime mouse evidence |
| WPF create/reorder/remove-empty track | PARTIAL | Bound commands gọi lệnh V2 | Nút tạm; GUI behavior chưa được chấp nhận |
| WPF add/move theo Track ID | PARTIAL | Resolver và command code; .NET command tests | Chưa xác nhận drag thực tế; same-lane overlap vẫn `REFERENCE_PENDING` |
| WPF trim canonical | PARTIAL | Visual/audio trim gọi V2 command, giữ clip/lane ID và ghi ticks | Unit tests đạt; WPF drag/source-bound behavior chưa được nghiệm thu |
| WPF undo/redo | PARTIAL | Snapshot project save/restore ở ViewModel | Chưa nối history của `TimelineEngineV2`; chưa GUI test |
| API linear export | PASS fixture | API/C++ Denim V2 MP4 khớp baseline byte-for-byte, full decode | Chỉ fixture này; không phải WPF Export |
| WPF preview | BLOCKED | Chưa có session GUI để chạy | Chưa đo preview parity |
| WPF export button | BLOCKED | Chưa có bằng chứng thao tác UI | API export không thay thế |
| Multi-track preview/export | UNSUPPORTED / GUARDED | Capability API từ chối cấu trúc không biểu diễn được | Native compositor/mixer chưa có |
| Audio dài hơn visual | PASS API fixture | 37.608 s audio/container; frame cuối vẫn có tới 37.5 s | Chưa chạy WPF preview/export |
| CapCut 9.6.0 parity | PENDING | Không có complete runtime reference cho toàn bộ semantics | Không suy luận insert/replace/ripple/snap |
| Release readiness | NOT READY | Các gates bên dưới còn pending/false | TASK2_0B và Replace stress chưa đóng |

## Flags hiện tại

```text
TASK2_1_MODEL_READY = true
TASK2_1_PERSISTENT_TIMELINE_READY = false
TASK2_1_LINEAR_RENDER_COMPATIBLE = false
TASK2_0B_RUNTIME_ACCEPTED = false
CAPCUT_9_6_0_REFERENCE_COMPLETE = false
MULTITRACK_COMPOSITOR_VERIFIED = false
VIDEO_EDITOR_RELEASE_READY = false
```

Regression run hiện tại: **122 .NET passed**, **33 Python passed** (25 Project V2/API, 5 audio, 3 timeline).

Các trạng thái ở cột đầu ra không được suy từ một cột khác. Đặc biệt, API linear export PASS không làm WPF Preview/Export PASS.
