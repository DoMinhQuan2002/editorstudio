# FALL DIARY — DEFINITION 0.3 REPORT

## Danh tính và tương thích

- `templateId`: `fall-diary`
- `version`: `0.3.0-reference-pilot`
- Schema dùng chung: version 1 (`TemplateDefinition`)
- Canvas: 1080×1920, 30/1 fps, 90,000 ticks/s
- Duration: 1,530,000 ticks / 17 giây / 510 frame
- Demo, poster, audio reference: `null`
- 0.1.0-pilot và 0.2.0-motion-pilot vẫn giữ trong registry; không ghi đè definition cũ.

## Slots

Có 11 Slot ID pilot ổn định `photo-01`…`photo-11`. Đây là vai trò đầu vào cho definition kiểm thử, **không phải số slot đã xác minh của Muse** và không suy từ 12 ảnh fixture hay 36 clip. Mỗi slot bắt buộc, chỉ nhận `image`, `reusePolicy=allow`, `missingSlotPolicy=error`. Cho phép một media được dùng lại theo policy. Definition không chứa source Media ID hay đường dẫn fixture; `assetDependencies=[]`.

## Timeline và layer order

| Event | Start (tick) | Duration (tick) | Layer order |
|---|---:|---:|---:|
| background-opening | 0 | 519,000 | 0 |
| background-autumn-park | 519,000 | 360,000 | 0 |
| background-picnic | 879,000 | 315,000 | 0 |
| background-food-insert | 1,194,000 | 45,000 | 0 |
| background-bouquet-close | 1,239,000 | 291,000 | 0 |
| overlay-pour-replacement | 339,000 | 135,000 | 1 |
| overlay-basket-replacement | 474,000 | 135,000 | 1 |
| overlay-park-figure | 609,000 | 225,000 | 1 |
| overlay-coffee-close | 834,000 | 45,000 | 1 |
| overlay-picnic-transition | 879,000 | 45,000 | 1 |
| overlay-market-figure | 924,000 | 270,000 | 1 |
| title-graphic | 0 | 1,530,000 | 20 |

Tất cả biên thời gian nằm trên frame boundary 3,000 ticks. Các overlay event được định thời độc lập với background. Các ảnh overlay dùng `contain`, scale 0.27–0.28, opacity 1, rotation 0; nền dùng `cover`. Thay đổi tạo hard cut/replacement theo event. Không thêm transition, filter màu hay biến đổi ngẫu nhiên.

## Animation và capability

Definition hỗ trợ `full_frame_image`, `hard_cut`, `multi_layer_collage`, `independent_visual_event_timing_90khz`, `independent_overlay_event_timing_90khz`, `letter_tile_text_graphic`, `preview_export_shared_renderer`, `safe_area_contain_cards`, `image_slot_reuse`.

Các `keyframes` đều rỗng; `animatedLayerCount=0`. Shared engine 3.9B hỗ trợ linear X/Y/scale/rotation/opacity khi một definition khai báo, nhưng 0.3 không dùng vì chưa xác định được chuyển động cụ thể từ nguồn. Không silent fallback; motion fidelity gate giữ false. Easing phi tuyến và transition phức tạp không nằm trong capability set.

## Missing media và compiler

Slot thiếu binding hoặc sai loại media làm validation thất bại; không tạo slot rỗng thay thế. Không chạy compiler riêng cho FALL DIARY: dùng `compile_template`, `build_composition_graph` và renderer chung. Màn 3 chỉ tạo slot binding payload. WPF Processing job là nơi áp dụng definition; mở Màn 3 không tạo project.

## Validation

- Definition được load/validate; kiểm tra Slot ID, duration, tick/frame alignment, overlap events, layer order, bounds và không hardcode source ID.
- Binding reuse được cho phép; thiếu slot bắt buộc và sai `allowedMediaKinds` bị từ chối.
- Tests kiểm tra tương thích 0.1/0.2 và biến thiên event timing 0.3.
- Output compiler harness có 5 background, 6 overlay và 9 title layers; Project V2/Composition Graph 0.3 được xuất riêng.

**Cổng:** `FALL_DIARY_0_3_DEFINITION_READY=true`. Reference fidelity và ready-for-users vẫn false do duration/title ending uncertainty, motion chưa xác minh, cutout/audio chưa có và chưa có demo/poster được cấp quyền.
