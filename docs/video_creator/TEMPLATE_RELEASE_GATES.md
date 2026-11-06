# Video Creator — release gates sau TASK 3.4

## Fall Diary

| Gate | Trạng thái | Điều kiện còn thiếu |
|---|---|---|
| `FALL_DIARY_CATALOG_READY` | `false` | Catalog ID đã có ở trạng thái reference-only, nhưng chưa có poster/demo thực và hợp lệ để dùng trong UI. |
| `FALL_DIARY_TEMPLATE_COMPILABLE` | `false` | Generic compiler đã có; chưa có definition thật, binding service hoặc workflow Màn 3. |
| `FALL_DIARY_RENDER_VERIFIED` | `false` | Chưa có MP4, fixture, preview/export hay comparison. Cutout và animated keyframes cũng chưa được hỗ trợ. |
| `VIDEO_CREATOR_RELEASE_READY` | `false` | Một template pilot không nâng release gate; các gate sản phẩm hiện hữu vẫn còn. |

## Trạng thái dự án tổng thể

Release gates hiện hành của Gallery và Video Creator vẫn được giữ. Source cho Gallery và Details tồn tại; Details CTA tới media selection vẫn disable; các flow import/binding/persistence/compiler-to-UI chưa hoàn thành. Không đánh dấu TASK 3.2/3.3 đã hoàn tất chỉ dựa vào brief.

## Điều kiện nâng trạng thái Fall Diary

1. Catalog có metadata đúng, poster và demo source truy cập được; asset rights đã xác minh. Tệp kit và artwork cá nhân không được đóng gói/phát hành nếu chưa được phép.
2. Definition có version, canvas/FPS/duration, slot requirements, events/layers và manifest dependencies đã đối chiếu reference.
3. Slot binding giữ stable asset IDs, kiểm tra media kind, thay/bỏ, reuse/missing policies, và Save/Reopen.
4. Compiler tạo Project V2/Composition Graph đầy đủ; feature unsupported được báo, không bị loại âm thầm.
5. Preview/export được tạo từ fixture thật và đối chiếu theo timestamp; MP4 decode và regressions đạt.
6. Cutout chỉ được pass khi alpha mask/foreground RGBA có bằng chứng segmentation thật và được kiểm tra halo.
7. `READY_FOR_USERS` chỉ sau end-to-end test với bộ fixture khác và xác nhận không phụ thuộc 12 ảnh private test.
