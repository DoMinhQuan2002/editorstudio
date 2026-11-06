# FALL DIARY — 0.4 VS 0.5 STRUCTURE

## So sánh

| Thuộc tính | 0.4.0-editorial-motion-pilot | 0.5.0-layer-structure-pilot |
|---|---|---|
| Definition | Giữ nguyên baseline | File mới, không ghi đè .1/.2/.3/.4 |
| Slots | 11, reusable | 11, reusable; không suy slot count từ scene/clip |
| Nền | 10 full-frame shot events | 5 background events liên tục qua overlay changes |
| Overlay | 2 editorial card events; cùng dùng `photo-11` | 6 independent replacement events dùng `photo-06`…`photo-11` |
| Text | 9 glyph vector/text layers | Giữ 9 glyph; vị trí chuyển sang `editorial-safe-v1` |
| Definition events | 13 (10 shot + 2 card + title) | 12 (5 background + 6 overlay + title) |
| Graph clips | 21 (12 visual + 9 text) | 20 (11 visual + 9 text) |
| Motion | Linear push-in/carda motion editorial | Background scale 1.0→1.012 linear/editorial; overlay static, motion unverified |
| Timing | Main sequence breaks at all 10 states | Background timeline split only at likely cut candidates/unknown insert; overlays independent |
| Engine | Shared Template Compiler + Composition Graph | Cùng shared compiler/graph renderer; không có FallDiaryRenderer |

## 0.5 event map

| Track layer | Event ID | Timeline (s) | Binding | Mục đích |
|---:|---|---:|---|---|
| 0 | `background-opening` | 0–5.767 | `photo-01` | Nền giữ qua 3.767 và 5.267 |
| 0 | `background-autumn-park` | 5.767–9.767 | `photo-02` | Nền park giữ qua overlay 6.767 và 9.267 |
| 0 | `background-picnic` | 9.767–13.267 | `photo-03` | Nền picnic giữ qua overlay 10.267 |
| 0 | `background-food-insert` | 13.267–13.767 | `photo-04` | Candidate shot/insert còn UNKNOWN |
| 0 | `background-bouquet-close` | 13.767–17.000 | `photo-05` | Likely closing cut |
| 1 | `overlay-pour-replacement` | 3.767–5.267 | `photo-06` | Thay insert trên opening background |
| 1 | `overlay-basket-replacement` | 5.267–6.767 | `photo-07` | Thay insert trước cut nền |
| 1 | `overlay-park-figure` | 6.767–9.267 | `photo-08` | Replacement trên park background |
| 1 | `overlay-coffee-close` | 9.267–9.767 | `photo-09` | Replacement trước picnic cut |
| 1 | `overlay-picnic-transition` | 9.767–10.267 | `photo-10` | Event độc lập tại ranh giới chưa tách được lớp nguồn |
| 1 | `overlay-market-figure` | 10.267–13.267 | `photo-11` | Replacement trên picnic background |
| 20 | `title-graphic` | 0–17.000 | Text vector | 9 glyph; end 17s là giả định pilot |

## Root cause đã sửa

Trong 0.4, mỗi visible-state detector event trở thành full-frame shot. Vì vậy các overlay replacement candidates biến thành full-frame cuts và reset background scale animation. 0.5 tạo hai timeline layer riêng: background cut chỉ tại các mốc được biểu diễn như nền mới; replacement layer bắt đầu/kết thúc độc lập. Tại candidate 9.767 hai event cùng bắt đầu vì reference cho thấy thay đổi nền và insert gần đồng thời, nhưng evidence không đủ tách hai nguyên nhân hoàn toàn.

## Giữ lại baseline và giới hạn

Registry vẫn đọc được 0.1, 0.2, 0.3, 0.4 và 0.5; tests xác nhận các version trước không bị thay thế. Cấu trúc mới tốt hơn cho background continuity, nhưng 0.5 vẫn là pilot: nguồn Muse không có timeline editable, background đoạn 13.267s chưa biết có phải cut, overlay transforms nguồn không khôi phục, và safe layout là editorial lựa chọn.
