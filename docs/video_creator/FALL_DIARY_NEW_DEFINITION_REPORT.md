# FALL DIARY — NEW DEFINITION 0.4 REPORT

## Danh tính

- Template ID: fall-diary
- Version: 0.4.0-editorial-motion-pilot
- Schema: TemplateDefinition schema version 1
- Canvas/timebase: 1080×1920, 30/1 fps, 90,000 ticks/s
- Duration: 1,530,000 ticks / 17 giây / 510 frame
- Demo, poster, audio reference: null
- Asset dependencies: rỗng
- Source Media ID hardcode: không
- Availability: PILOT_RENDERABLE, chưa phát hành

Definition nằm tại backend/mediastudio/video_editor/definitions/fall-diary-0.4.0-editorial-motion-pilot.json. Generator tools/video_creator/create_fall_diary_task39g_definition.py tạo version mới từ baseline .3, không ghi đè .1/.2/.3.

## Slot contract

| Slot ID | Kind | Required | Reuse | Missing |
|---|---|---|---|---|
| photo-01…photo-11 | image | true | allow | error |

Các slot là vai trò reusable của pilot QA. 11 không phải số slot đã xác minh của Muse, không suy từ 12 fixture hoặc 36 clip. Card thứ nhất và thứ hai cùng dùng photo-11 theo reuse policy.

## Event contract

- 10 shot event toàn khung liên tiếp: photo-01…photo-10, layerOrder 0, fitMode cover.
- 2 event card độc lập: editorial-card-autumn-figure tại [609,000,834,000) và editorial-card-still-life tại [924,000,1,194,000), cả hai bind vào photo-11, layerOrder 1, fitMode contain.
- 1 title event liên tục 17s gồm 9 glyph text ở layerOrder 20.
- Tổng: 13 events; Composition Graph có 21 clip (12 visual, 9 text).

Keyframe capability dùng shared linear interpolation. Main shot scale phụ thuộc duration theo công thức trong generator. Card dùng X/Y/scale. Không có random transform, easing mới, transition ngoài engine hoặc hardcode Media ID. Mỗi animation là editorial, không phải khôi phục motion của Muse.

## Missing media và compile

11 slot là required; thiếu binding hoặc sai media kind phải fail validation. Reuse chỉ được cho phép đúng theo policy. Version .4 được đăng ký qua registry hiện có, dùng get_template_definition, compile_template, build_composition_graph và Composition Graph renderer dùng chung. Không tạo engine riêng cho FALL DIARY.

## Validation evidence

- Definition 0.1, 0.2, 0.3 vẫn load được; 0.4 là latest.
- Slot ID/count, frame-aligned start/end, reuse, required media, track order, text glyph count và keyframes được kiểm tra bằng tests.
- 0.4 compile thành Project V2 có đúng Template ID/version và binding map; graph giữ 90 kHz, 30 fps, 17 giây, layer orders 0/1/20.
- Preview/Export harness FFprobe và full decode pass.
- WPF Project V2 riêng: project ffa6f7c801c44e20b557263e6f300afa r1, fall-diary / 0.4.0-editorial-motion-pilot; reopen qua Gallery thành công.
- FALL_DIARY_NEW_DEFINITION_READY=true.

## Giới hạn

Definition giữ title giữa khung theo vị trí nhìn thấy trong Muse, nhưng có thể che mặt trong ảnh QA. Không có content-aware placement. Không có cutout, audio, poster hoặc demo. Duration/title end-time 17s là pilot assumption dựa trên metadata; source end chưa xác minh. Không dùng cho phát hành.
