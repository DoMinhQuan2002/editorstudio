# CapCut Desktop 9.6.0 — feature inventory

> **RETIRED_PRODUCT_REQUIREMENT (TASK 3.0A):** các yêu cầu parity CapCut 9.6.0 không còn thuộc phạm vi sản phẩm. Giữ inventory này làm lịch sử kỹ thuật; các kiểm tra engine/data correctness vẫn được theo dõi riêng.

> **Cập nhật Task 2.1 (2026-10-21):** các cột Media Studio phía dưới là trạng thái baseline trước Project Model V2. Mục liên quan cấu trúc dữ liệu/track đã được cập nhật ở phần “Task 2.1 delta”; chúng không nâng mức xác minh hành vi CapCut.

Trạng thái tài liệu: PARTIAL. Target version do người dùng chỉ định; file tham chiếu chưa cho thấy About/build number rõ ràng. OBSERVED dưới đây chỉ áp dụng cho những gì thấy trong video, contact sheet, ảnh hoặc mô tả trực tiếp của người dùng. Không lấy hành vi từ phiên bản CapCut khác.

Trạng thái Media Studio:

- OBSERVED: hành vi tham chiếu thấy được.
- REFERENCE_PENDING: cần thêm bằng chứng CapCut để mô tả hành vi chính xác.
- IMPLEMENTED_UNVERIFIED: có code hoặc UI nhưng chưa nghiệm thu đủ trên WPF.
- PARITY_PASS/PARITY_FAIL: đã so trực tiếp và đạt/không đạt.
- BLOCKED: chưa kiểm tra được.

| # | Chức năng | CapCut 9.6.0 hiện thấy | Media Studio hiện tại | Gap / bằng chứng cần |
|---|---|---|---|---|
| 1 | Timeline toolbar | Ảnh có toolbar với thêm, undo/redo, split/delete và các biểu tượng điều khiển. Ý nghĩa và phím tắt từng nút chưa được quay rõ. REFERENCE_PENDING | Các lệnh add, undo/redo, split có trong WPF view model. IMPLEMENTED_UNVERIFIED | Quay từng nút và tooltip, trạng thái enable, phím tắt. |
| 2 | Track header | Ảnh cho thấy header track và controls ở cạnh track visual. OBSERVED | TimelineTracks là projection động: Main Visual, Text, Audio và empty drop surface. Không phải model track bền vững. IMPLEMENTED_UNVERIFIED | Kiểm tra lock, hide, mute, menu, đổi thứ tự và lưu trạng thái. |
| 3 | Media library kéo thả | Contact sheet có media card và một khối media nổi khi kéo. OBSERVED | Media card, plus action, ghost và routing có trong WPF. Ghost trong ảnh Media Studio là thanh ngang lớn, không cùng hình dạng với card nổi CapCut. PARITY_FAIL về ngoại hình; drop chưa xác minh WPF. | Quay bắt đầu kéo đến trước khi nhả chuột, kể cả con trỏ ngoài timeline. |
| 4 | Insert clip | Ảnh/video cho thấy clip visual turquoise với thumbnail trong timeline. OBSERVED | Insert tại timeline position có trong view model. Thao tác kéo thực tế chưa kiểm tra ở lượt Phase 0. IMPLEMENTED_UNVERIFIED | Drop ở đầu, giữa gap, cuối timeline; kiểm tra start, duration, thumbnail và preview. |
| 5 | Replace | Người dùng cung cấp ngữ cảnh Replace; khung ảnh/contact hiện có chưa ghi rõ hover, popup, confirm/cancel. REFERENCE_PENDING | Có handler Replace dialog và API stress 20 lần gán media; WPF Replace chưa lặp kiểm tra. IMPLEMENTED_UNVERIFIED | Quay hover target, trạng thái preview, commit/cancel, undo/redo và filmstrip đồng thời. |
| 6 | Overlay | Chưa có đủ cảnh cho thao tác thả visual lên lớp phía trên. REFERENCE_PENDING | Không có multi-track video model hoàn chỉnh. BLOCKED về parity | Quay clip chồng clip và track đích được chọn. |
| 7 | Nhiều visual track | Một số ảnh chỉ thấy lane visual; chưa có bằng chứng đủ về tạo/đổi track. REFERENCE_PENDING | Video hiện lưu chuỗi scene tuần tự, chỉ một Main Visual projection. PARITY_FAIL về tính năng V2 | Quan sát tạo lane visual thứ hai và thứ tự lớp. |
| 8 | Nhiều text track | Chưa xác minh số lượng và thao tác track text. REFERENCE_PENDING | Lưu text_layers phẳng, projection Text duy nhất. BLOCKED về parity đa track | Quay thêm text track, kéo lớp, chồng thời gian, lưu/mở. |
| 9 | Nhiều audio track | Ảnh audio cho thấy lane audio tách khỏi visual; thêm track mới và quy tắc lane chưa rõ. OBSERVED một lane riêng | WPF có AudioTrack, lane được phân first-fit; import WAV tạo Audio 1. IMPLEMENTED_UNVERIFIED | Kéo hai audio chồng thời gian, kiểm tra lane mới và track ID sau reopen. |
| 10 | Selection | Có clip được viền chọn trong ảnh CapCut. OBSERVED | Có clip selection/inspector. IMPLEMENTED_UNVERIFIED | Kiểm tra click, multi-select, phím modifiers, selection sau scroll. |
| 11 | Snapping | Chưa thấy guide hoặc thời điểm bắt dính đủ rõ trong reference hiện lưu. REFERENCE_PENDING | Có TimelineInteractionEngine và snap metadata trong resolver. IMPLEMENTED_UNVERIFIED | Quay gần đầu clip, playhead và cạnh clip; ghi khoảng hút và guide. |
| 12 | Magnet | Có biểu tượng dạng magnet/link trên toolbar nhưng chưa thấy bật/tắt và hậu quả. REFERENCE_PENDING | Chưa xác nhận control parity. BLOCKED | Ghi trạng thái nút và clip gap/di chuyển trước-sau. |
| 13 | Linkage | Chưa thấy thao tác liên kết audio/video hoặc di chuyển cùng nhau. REFERENCE_PENDING | Không có quan hệ clip group trong schema hiện tại. BLOCKED | Tạo linked media, kéo một clip và xem clip kia. |
| 14 | Ripple | Chưa có bằng chứng xóa/di chuyển làm các clip phía sau trượt. REFERENCE_PENDING | Video được sắp liên tiếp theo scene; ripple semantics UI chưa xác minh. BLOCKED | Quay delete/trim gap và vị trí các clip sau thao tác. |
| 15 | Trim/Split/Delete | Toolbar và clip handles nhìn thấy trong ảnh, nhưng thao tác và snapping chưa ghi đầy đủ. REFERENCE_PENDING | Có split, audio trim/delete logic trong code. WPF audio trim/delete chưa kiểm tra lượt này. IMPLEMENTED_UNVERIFIED | Quay thao tác từng cạnh, split tại playhead, xóa và undo. |
| 16 | Undo/Redo | Hai nút undo/redo nhìn thấy; chưa đủ chuỗi thao tác cụ thể. OBSERVED controls, semantics REFERENCE_PENDING | Undo audio move đã thử và phục hồi 0 ms; redo chưa xác nhận. PARTIAL | Quay thao tác, undo, redo, save/reopen và revision. |
| 17 | Audio waveform | Ảnh tham chiếu audio cho thấy audio lane; hình waveform chi tiết và cách tính chưa đủ nét. REFERENCE_PENDING | WPF gọi API waveform; 480 mẫu render trong lane WAV đã kiểm tra. PASS cho hiển thị WPF, chưa phải parity. | Tham chiếu rõ waveform trên CapCut và các thao tác trim/move. |
| 18 | Text layering | Chưa quan sát được text nằm giữa các visual layer nào. REFERENCE_PENDING | Text được render như layer danh sách riêng, không có layer order bền vững. IMPLEMENTED_UNVERIFIED | Quay text overlay, thứ tự và vùng preview. |
| 19 | Preview | Khung preview, playhead/timecode và play/pause thấy được. OBSERVED | WPF preview đã phát tới 1,496 ms trong test. PASS cho một fixture teal, chưa xác minh sync audio. | Ghi xử lý seek, frame khi kéo, audio sync và stale frame. |
| 20 | Save/Reopen | Không có bằng chứng đủ để phân biệt autosave và explicit save. REFERENCE_PENDING | WPF lưu, rời editor, mở lại template; video/text/audio được giữ. PASS cho kịch bản test. | CapCut evidence cho autosave, trạng thái dirty, recovery. |
| 21 | Export | Nút xuất thấy ở ảnh; cài đặt/render/result chưa quan sát. OBSERVED button, flow REFERENCE_PENDING | API native export có kiểm tra audio+video; WPF export chưa chạy trong Phase 0. IMPLEMENTED_UNVERIFIED | Quay dialog, codec, progress, hoàn tất và file output. |

## Interaction contract theo từng chức năng

Các ô REFERENCE_PENDING có nghĩa là recording hiện có không cho phép kết luận chắc chắn. Hành vi WPF cũng ghi rõ khi chưa được thao tác thực tế.

| Chức năng | Trạng thái trước và hành động | Hover / kết quả sau hành động | Ảnh hưởng tới clip khác và preview | Undo/Redo | Evidence, trạng thái Media Studio và gap |
|---|---|---|---|---|---|
| Timeline toolbar | Timeline mở; click từng icon hoặc dùng shortcut. | Icon/tooltip và kết quả từng nút chưa xác nhận. | Ảnh hưởng phụ thuộc lệnh; preview sau lệnh chưa xác minh. | Nút history thấy được; semantics chưa rõ. | Toolbar thấy trong CapCut screenshot; WPF có command add/undo/redo/split, IMPLEMENTED_UNVERIFIED. Cần quay tooltip và từng kết quả. |
| Track header | Có track visual; click control hoặc menu track. | Hover menu/state chưa rõ. | Lock/visibility/mute/order chưa được quan sát; preview effect pending. | Chưa quan sát. | Ảnh CapCut chỉ cho thấy header/control. WPF track là projection, IMPLEMENTED_UNVERIFIED; cần kiểm tra controls. |
| Media library drag | Media card trong library; giữ chuột và kéo ra ngoài timeline. | Floating thumbnail thấy được; điểm chuyển sang target chưa đủ frame. | Trước commit clip timeline không đổi theo mô tả người dùng; preview timeline chưa thấy thay đổi. | Cancel/history semantics pending. | Contact sheet CapCut và user explanation; WPF ghost khác ngoại hình, PARITY_FAIL. Cần quay đầy đủ pointer. |
| Insert | Timeline và target lane/gap; thả media vào vị trí. | Clip turquoise có thumbnail nhìn thấy; hover threshold và snap pending. | Ảnh hưởng clip lân cận và preview sau thả chưa rõ. | Chưa có drop undo/redo được quay. | CapCut screenshot; WPF insert method có, nhưng WPF video drag chưa thử, IMPLEMENTED_UNVERIFIED. |
| Replace | Clip đang có; kéo media lên clip body hoặc mở Replace. | Viền target, popup, confirm/cancel chưa có bằng chứng. | Độ dài scene, clip kế tiếp và preview sau thay chưa xác nhận. | Chưa quan sát trên CapCut. | WPF handler/API stress có; WPF dialog chưa thử, IMPLEMENTED_UNVERIFIED. Cần ghi media ID và duration trước/sau. |
| Overlay | Visual clip đã có; kéo clip thứ hai lên track khác. | Vị trí nhận/ghost chưa quan sát. | Overlap, layer order, compositing preview chưa quan sát. | Chưa quan sát. | Không có ảnh reference đủ; WPF không có visual track V2, BLOCKED. |
| Multi-track | Timeline có media; thêm hoặc kéo clip sang track mới. | Tạo lane tự động hay thủ công chưa rõ. | Z-order và tương tác với clip khác chưa rõ. | Chưa quan sát. | Chưa có reference sequence; WPF model chỉ có một MainVisual, BLOCKED về parity. |
| Selection | Timeline có một hoặc nhiều clip; click hoặc dùng modifier. | Viền/handles thấy trên một clip; multi-select hover chưa rõ. | Preview selection/transform effect pending. | Selection history pending. | Ảnh CapCut có clip viền chọn; WPF selection/inspector có, IMPLEMENTED_UNVERIFIED. Cần thử modifier và multi-select. |
| Snapping | Kéo clip gần mốc/clip edge/playhead. | Guide, vùng hút và threshold chưa rõ. | Clip đích có dịch hay không chưa rõ; preview pending. | Snap có được lưu thành move hay không pending. | WPF resolver tạo snap candidate, IMPLEMENTED_UNVERIFIED. Cần video con trỏ chậm và timecode. |
| Magnet | Toggle magnet rồi kéo clip qua gap. | Trạng thái on/off và icon feedback chưa rõ. | Gap/ripple và vị trí các clip sau pending. | Chưa quan sát. | Icon trong toolbar ảnh CapCut; ý nghĩa chưa được xác minh, REFERENCE_PENDING. |
| Linkage | Có video/audio liên quan; kéo một clip. | Badge/link hover chưa rõ. | Clip liên kết đi cùng hay tách chưa quan sát; preview pending. | Chưa quan sát. | Chưa có recording; Media Studio chưa có group relationship, BLOCKED. |
| Ripple | Có clip sau clip bị sửa; delete hoặc kéo tạo gap. | Hover chưa rõ. | Việc clip sau trượt/lấp gap chưa quan sát. | Chưa quan sát. | CapCut reference pending; WPF tuần tự hóa visual nhưng thao tác ripple chưa xác minh. |
| Trim/Split/Delete | Chọn clip; kéo handle, split ở playhead hoặc delete. | Handle/tooltip/snap chưa rõ. | Thời lượng, source range, vị trí clip kế và preview chưa ghi nhận. | Chưa quan sát CapCut. | WPF có split và audio trim/delete code; audio trim/delete chưa test runtime, IMPLEMENTED_UNVERIFIED. |
| Undo/Redo | Thực hiện một edit; click undo rồi redo. | Disabled/enabled feedback chưa quay rõ. | Clip, preview và selection sau mỗi bước pending. | Hai icon hiện diện; kết quả cụ thể chưa xác minh. | WPF audio move→undo đã PASS một lần; redo pending. Cần chuỗi WPF thật. |
| Audio waveform | Thả audio vào timeline. | Waveform hover/loading chưa rõ; ảnh audio lane riêng thấy được. | Waveform theo trim/volume và audio sync pending. | Chưa quan sát CapCut. | WPF WAV tạo lane và 480 mẫu/bar, PASS hiển thị. Kéo từ library và trim chưa test. |
| Text layering | Thêm text; kéo qua clip/layer. | Vùng nhận và handles chưa rõ. | Thứ tự text so với visual và preview pending. | Chưa quan sát. | WPF giữ text layer mẫu, nhưng track/order riêng không có; IMPLEMENTED_UNVERIFIED. |
| Preview | Project có media; seek/play/pause. | Hover control và frame trong lúc drag pending. | Frame/playhead thấy đồng bộ trực quan; audio sync chưa xác minh. | Seek history pending. | WPF playback một fixture tới 1.496 s, frame nguồn khớp màu; PASS giới hạn fixture. |
| Save/Reopen | Có chỉnh sửa; save, rời project rồi mở lại. | Dirty/autosave indicator chưa thấy đủ. | Clip/text/audio giữ qua reopen trên WPF test. | History có được giữ sau reopen chưa rõ. | CapCut reference pending; Media Studio Template save/reopen giữ 5 scene, text, video, audio, PASS cho test. |
| Export | Project có media; click Xuất. | Dialog/options/progress chưa được quay. | File đầu ra và preview sau export chưa rõ từ CapCut source. | Không áp dụng hoặc chưa xác minh. | WPF API export PASS, WPF nút export chưa thử; CapCut flow REFERENCE_PENDING. |

## Các quyết định sản phẩm đã chốt

- Free Editor bắt đầu từ timeline trống; người dùng tự nhập và sắp media.
- Template Editor giữ placeholder, nội dung text và thời lượng mẫu.
- Cả hai dùng chung timeline engine.
- Media route dựa trên metadata stream, không chỉ phần mở rộng tên file.
- Nhiều visual/text/audio track là mục tiêu Phase 1 trở đi; chưa tuyên bố đã có parity.

## Nguồn tham chiếu đã lưu

- capcut-reference-4s.png
- capcut-reference-5-to-8.png
- capcut-reference-9s.png
- capcut-reference-sheet.png
- media-studio-drag-contact.png và các ảnh drag detail
- Video CapCut do người dùng cung cấp trong thư mục Captures, gồm 14-20-55 và 14-37-42 ngày 20-10-2026.
- CapCut_Audio_Timeline_Review.png

Để đóng các mục REFERENCE_PENDING, cần video rõ con trỏ và toàn bộ timeline cho: drag ngoài timeline → vào vùng hợp lệ → nhả; Replace có/không xác nhận; overlay; tạo track; snapping/magnet/linkage/ripple; trim/split/delete/undo/redo; audio waveform; save/reopen; export. Cần một ảnh About để xác minh version/build cụ thể.

## Task 2.1 delta — trạng thái cấu trúc hiện tại

- Project V2 hiện có persistent visual/text/audio track IDs, layer order, empty tracks, clip IDs và absolute ticks. Đây là PASS ở schema/domain/API test; không phải bằng chứng về semantics CapCut.
- WPF đọc và chiếu các track đã lưu theo ID. GUI chưa được thao tác thủ công trong Task 2.1; move clip qua lane qua WPF vẫn pending.
- V1 audio first-fit chỉ được dùng làm mapping một lần khi migrate; V2 lane identity được giữ sau edit/load. Không kết luận CapCut dùng cùng quy tắc.
- Multi-track compositor chưa được xác minh; API từ chối layout ngoài capability hiện tại.
- Các quan sát Insert/Replace/overlay/snap/ripple/linkage/keyboard vẫn giữ `REFERENCE_PENDING`; không dùng model V2 để suy ra hành vi.

Trạng thái mới nhất: `TASK2_1_MODEL_READY=true`, `TASK2_1_PERSISTENT_TIMELINE_READY=false`, `CAPCUT_9_6_0_REFERENCE_COMPLETE=false`.
