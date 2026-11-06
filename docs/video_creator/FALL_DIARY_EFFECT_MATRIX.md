# Fall Diary — effect matrix

> Historical pre-ingest matrix. Task 3.9A's implemented/deferred matrix is in [FALL_DIARY_TASK3_9A_REPORT.md](FALL_DIARY_TASK3_9A_REPORT.md).

“Observed” chỉ dùng khi có bằng chứng MP4. Reference kit hiện vắng nên chưa effect nào được xác nhận là observed.

| Yêu cầu | Bằng chứng từ demo | Backend/compiler hiện tại | Kết quả TASK 3.4 |
|---|---|---|---|
| Thay ảnh full-frame | Chưa có MP4 — UNKNOWN | Visual image clip và fit mode có trong Composition Graph/renderer | Có thể compile subset; chưa gắn Fall Diary |
| Animated image scale | UNKNOWN | Static scale có; keyframes không có semantics trong graph/compiler | PARTIAL; animation chưa hỗ trợ |
| Position animation | UNKNOWN | Static position có; keyframes bị reject | PARTIAL |
| Opacity animation | UNKNOWN | Static opacity có; keyframes bị reject | PARTIAL |
| Quick cuts | UNKNOWN | Các clip nối tiếp/hard cut có thể biểu diễn; transition API báo unsupported | Có capability cơ bản; timing mẫu chưa biết |
| Nhiều overlay | UNKNOWN | Multi-track visual và image alpha overlay được capabilities API báo verified | Có capability backend; chưa được render trên Fall Diary |
| Photo collage | UNKNOWN | Nhiều visual tracks có thể tạo bố cục chồng lớp | Có capability backend; chưa biết bố cục tham chiếu |
| Text overlay | UNKNOWN | Text clip được graph/renderer hỗ trợ; schema compiler có template text | Có capability cơ bản; font/runtime output chưa đối chiếu |
| Foreground cutout | UNKNOWN | Không tìm thấy person segmentation/background-removal phù hợp | BLOCKED; không giả crop hình chữ nhật |
| Audio sync | UNKNOWN | Audio clip/gain/fade có trong engine; demo audio/rights chưa có | UNKNOWN; soundtrack demo không dùng |

`SUPPORTED_VERIFIED` trong API capabilities mô tả engine/runtime subset, không phải xác minh một template cụ thể. Xem [reference analysis](FALL_DIARY_REFERENCE_ANALYSIS.md) và [render comparison](FALL_DIARY_RENDER_COMPARISON.md).
