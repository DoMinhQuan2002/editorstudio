# Project Model V2 — migration risk assessment

Trạng thái: PASS cho audit và kế hoạch; migration chưa thực hiện.

## Mô hình hiện tại

| Thành phần | Biểu diễn hiện tại | Hạn chế/rủi ro |
|---|---|---|
| Video clip | VideoClip lưu clip_id, media_id nullable, source_start_ms, duration_ms, transform/effect/volume/transition. | Không có timeline start; backend duration là tổng duration các clip. WPF đặt start theo tổng các clip trước. Không biểu diễn overlap trực quan bằng schema. |
| Visual track | WPF chiếu visualItems thành một MainVisual lane có ID tĩnh cho UI. | ID projection không phải ID lưu trong JSON; không có Track entity, layer order hay trạng thái track. |
| Text | TextLayer lưu layer_id, start_ms, duration_ms, vị trí, font, màu, opacity. | Không có track_id hoặc layer order bền vững. Danh sách đơn không thể mô tả text tracks riêng và compositing thứ tự tùy chọn. |
| Audio | Mỗi AudioTrack lưu track_id, media_id, timeline/source start, duration, volume, fades. | track_id gắn với audio item; không có AudioTrack entity với lane/order/lock/mute. UI lane được phân first-fit và có thể đổi lane khi dữ liệu đổi. |
| Thứ tự/lớp | Thứ tự clips/text_layers trong JSON. | Thứ tự mảng không mô tả rõ thứ tự layer đồng thời hoặc track z-order. |
| Project settings | project_id, template_id, title, width, height, fps, created/updated, revision. | Không có schema_version hoặc migration marker. |
| Persistence | Một JSON mỗi project; ghi file tạm cùng thư mục rồi replace. | Không lưu snapshot backup lịch sử tự động, không có forward/backward migration version. |
| Preview | WPF chọn scene theo start tính tuần tự, decode qua native engine. | Không có compositor timeline cho nhiều visual layers. |
| Export | Native/API render nhận dãy clip scene tuần tự, text layers và audio tracks riêng. | Không chứng minh được overlay video đồng thời hoặc track z-order. |
| Template | Placeholder là VideoClip không có media_id, với duration/name/configuration template. | Migration phải giữ slot, clip ID, duration, transform, transition, thứ tự và template_id. |

## Đề xuất đích V2

Project nên có metadata, settings, media asset references, template metadata và tracks[]. Track giữ track_id, kind, layer_order, display/state và clips[]. Mỗi clip giữ clip_id, media_id nullable, timeline_start_ms, source_start_ms, duration_ms, transform, video/audio properties. Clip placeholder cần cờ/metadata rõ nhưng phải giữ media_id null và thời lượng scene cũ.

Đây là khung hướng dẫn; chưa phải schema cuối. Trước triển khai cần quyết định frame/timebase, inclusive/exclusive end, audio lane identity, layer ordering, nested template scenes, transitions, gaps, ripple behavior và xử lý file media bị thiếu.

## Kế hoạch migration an toàn

1. Đọc JSON cũ theo model hiện hành, giữ nguyên bytes, SHA-256, project ID và tạo backup bất biến bên cạnh bản đích trước khi ghi.
2. Validate đủ scene, placeholder, text, audio và file media. Dữ liệu không hợp lệ hoặc thiếu asset dừng migration, giữ bản gốc nguyên trạng.
3. Tạo bản V2 tạm: chuyển mỗi clip video sang visual track chính, timeline start là tổng duration trước đó; giữ thứ tự, IDs, media/source start, duration, transform, transition và placeholder.
4. Map text theo start/duration/ID, đặt vào text track mặc định và giữ list order thành layer_order ổn định.
5. Chuyển audio sang audio tracks/clips với timeline/source start/duration/fades/volume. Lane hiện suy ra first-fit; xác định lane khi overlap bằng quy tắc cũ và ghi mapping tường minh, không đổi timeline timestamp.
6. Đặt schema_version cho target mới. Migration chỉ được chạy một lần trên bản tạm; kiểm tra idempotency và không ghi lên source nếu parse/render/validation bất kỳ bước nào thất bại.
7. Chạy regression fixture trên toàn bộ project cũ và so trước/sau: project ID/template, số scene, clip ID/media, placeholder, timestamp, text, audio, duration preview và output render tuần tự.
8. Ghi target file và backup cùng volume; thay thế nguyên tử sau khi tất cả kiểm tra đạt. Có lệnh rollback khôi phục đúng bytes/hash cũ.
9. Mở dự án bằng reader tương thích V2; phiên bản ứng dụng cũ không được ghi đè V2 nếu không hiểu schema. Cần backup/restore và thông báo rõ.

## Rủi ro cần quản lý

| Rủi ro | Tác động | Giảm thiểu |
|---|---|---|
| Timestamps video hiện ngầm định qua duration | Lệch cut khi đổi sang timeline start tường minh | Map start bằng tổng chính xác theo ms; test tổng thời lượng và frame boundary. |
| Placeholder bị biến thành clip rỗng hoặc mất | Template không mở đúng scene | Giữ clip ID, name, duration, thứ tự, transition và media_id null. |
| Text đổi thứ tự/compositing | Preview/export khác project cũ | Ánh xạ thứ tự mảng thành layer_order ổn định; kiểm tra ảnh render. |
| Audio lane suy ra | Clip có thể đổi lane sau migration | Chốt deterministic lane assignment, giữ start/duration và kiểm tra overlap. |
| Renderer chưa multi-track | Timeline mới lưu được nhưng preview/export không khớp | Migration không phát hành trước compositor hỗ trợ track/layer; capability/version gate. |
| Project V2 mở bởi binary cũ | Có thể mất field khi save | schema_version bắt buộc, reject write bởi reader không tương thích, backup tự động. |
| JSON lỗi hoặc media thiếu | Hỏng project | Validate toàn bộ trước khi commit; rollback theo bytes/hash. |
| Thay đổi frame/time semantics | lệch vài ms/frame | Chốt rational frame timebase và quy ước biên; test 24/25/30/60 fps. |

## Điều chưa làm trong Task 2.0

Không có schema V2, JSON migration, renderer multi-track hay UI redesign nào được thêm. Thực hiện các phần đó chỉ sau khi WPF runtime Phase 0 đầy đủ và CapCut reference matrix đóng các mục đang chờ.
