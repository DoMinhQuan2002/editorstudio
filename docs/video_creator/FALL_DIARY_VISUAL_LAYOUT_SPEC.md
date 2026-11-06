# FALL DIARY — VISUAL LAYOUT SPEC 3.9G

## Phạm vi

Đây là bố cục của definition 0.4 editorial pilot. Các layer được khai báo trong Template Definition, không rải tọa độ trong renderer. Renderer và Template Compiler dùng chung; không tạo FallDiaryRenderer.

## Layer và tọa độ

| Layer/event | Thời gian (tick) | Order | Slot | Layout / animation |
|---|---:|---:|---|---|
| 10 shot ảnh toàn khung | Các khoảng liên tục từ 0 đến 1,530,000 | 0 | photo-01…photo-10 | fitMode=cover; position (0,0); rotation 0; opacity 1; scale 1.0→tối đa 1.0452 |
| editorial-card-autumn-figure | [609,000, 834,000) | 1 | photo-11 | contain; normalized offset (0.28,0.30)→(0.24,0.24); scale 0.24→0.27 |
| editorial-card-still-life | [924,000, 1,194,000) | 1 | photo-11 | contain; normalized offset (0.28,0.30)→(0.24,0.24); scale 0.24→0.27 |
| title-graphic / 9 glyph | [0, 1,530,000) | 20 | không dùng media slot | Hai hàng ký tự FALL / DIARY; vector/text nội bộ |

Canvas 1080×1920. Renderer đặt ảnh overlay theo offset tính từ tâm canvas; với ảnh dọc 9:16 và scale card tối đa 0.27, card chiếm xấp xỉ 292×518 px trước phần crop/padding theo aspect ratio nguồn. Trong fixture dọc, card nằm trong vùng dưới-phải canvas. Ảnh ngang có thể tạo card nhỏ hơn theo contain policy.

Title dùng vị trí/kích thước gần reference 0.3: chữ tối, tile sáng, viền tối 3 px, shadow (3,4), font Arial fallback, fontSize 64. Tọa độ glyph đầu từ x=0.405, hàng đầu y=0.57; hàng hai bắt đầu x=0.382, y=0.615. Đây là 9 vector text layer, không phải ảnh UI Muse.

## Timing 10 shot

| Event | Start | End | Duration | Scale |
|---|---:|---:|---:|---:|
| shot-opening | 0 | 339,000 | 339,000 (3.7667s) | 1.0000→1.0452 |
| shot-tea-insert | 339,000 | 474,000 | 135,000 (1.5s) | 1.0000→1.0180 |
| shot-market-basket | 474,000 | 519,000 | 45,000 (0.5s) | 1.0000→1.0060 |
| shot-autumn-wide | 519,000 | 609,000 | 90,000 (1.0s) | 1.0000→1.0120 |
| shot-autumn-figure | 609,000 | 834,000 | 225,000 (2.5s) | 1.0000→1.0300 |
| shot-latte-insert | 834,000 | 879,000 | 45,000 (0.5s) | 1.0000→1.0060 |
| shot-picnic-insert | 879,000 | 924,000 | 45,000 (0.5s) | 1.0000→1.0060 |
| shot-autumn-still-life | 924,000 | 1,194,000 | 270,000 (3.0s) | 1.0000→1.0360 |
| shot-food-detail | 1,194,000 | 1,239,000 | 45,000 (0.5s) | 1.0000→1.0060 |
| shot-flower-ending | 1,239,000 | 1,530,000 | 291,000 (3.2333s) | 1.0000→1.0388 |

Mọi biên event/keyframe nằm trên frame boundary 3,000 ticks. Đây là variable event duration bám theo candidate visible states; không tuyên bố timestamp detector là source cut chính xác. Tất cả animation đều linear và được đánh dấu editorial.

## Layout QA

- Graph có 12 image clip (10 nền, 2 card), 9 text clip; event order nền 0, card 1, title 20.
- Tất cả card bắt đầu/kết thúc ở thời điểm khai báo; fixture samples cho thấy không có frame đen ngoài ý muốn và title/card không mất khi export.
- Full-frame image dùng cover, do đó ảnh ngang/dọc có thể crop chủ động theo aspect ratio; không cố suy đoán subject position.
- Hai card dùng contain; không tự phóng ảnh ra ngoài canvas.
- Frame preview tại 6.8s và 10.3s đã xem trực quan. Card nằm trong canvas, song title giao với mặt người ở fixture; card dưới phải có thể phủ thân người.
- Không có subject/face detection đã xác minh. Không gọi vị trí card là face-aware; không tạo heuristic riêng cho 12 ảnh.
- Kết quả: cấu trúc dynamic layout đạt; **layout QA theo nội dung người chưa đạt**. Cần quyết định dùng vị trí title theo Muse hay một safe-area editorial khác trước khi nâng pilot.

### Gates

- FALL_DIARY_DYNAMIC_LAYOUT_VERIFIED=true về event/layer/timing/bounds trong các fixture đã kiểm tra.
- FALL_DIARY_LAYOUT_QA_VERIFIED=false do overlap title/card với chủ thể trong một số fixture.
- FALL_DIARY_REFERENCE_FIDELITY_VERIFIED=false.
