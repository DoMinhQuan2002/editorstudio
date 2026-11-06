# Template Compiler — kiến trúc hiện thực

## Luồng đã có trong backend

```text
TemplateDefinition v1 + slotId → media assetId
                    ↓
        schema, binding, type, bounds validation
                    ↓
             Template Compiler
                    ↓
 Project V2 tracks/clips + template metadata
                    ↓
       Composition Graph validation
                    ↓
       existing preview / FFmpeg export
```

`compile_template()` là pure in-memory compiler. Nó không import media, copy tệp, lưu project hay gọi renderer. Caller cần đưa media lookup vào và tự quyết định khi nào persist/render.

## Các bảo đảm của compiler

- Template metadata có `schemaVersion` và `version`; mỗi media slot, event và layer có stable ID.
- Kiểm tra toàn bộ slot binding, media kind, reuse policy, video/audio source bounds và optional-slot policy trước khi trả project.
- Tính timeline bằng integer 90 kHz ticks; giữ FPS rational; không chuyển timeline canonical sang milliseconds.
- Mỗi layer order dùng track V2 tương ứng; ID clip/track hợp lệ; clip metadata giữ `templateId`, definition version, `eventId`, `layerId` và `slotId`.
- Project metadata giữ `templateBindings` theo asset ID để lớp persistence có thể Save/Reopen mà không nhân bản tệp nguồn.
- Sau khi tạo Project V2, compiler gọi `build_composition_graph()` và chỉ trả kết quả nếu graph validation thành công.
- Media type, missing required media, binding lạ, nguồn vượt duration, renderer feature chưa hỗ trợ hoặc dependency cần preprocessing đều gây lỗi rõ.

## Subset renderer hiện compiler chấp nhận

Template duration phải khớp event cuối vì Composition Graph chưa có contract giữ phần đuôi timeline trống. Nếu policy bỏ optional event làm output ngắn hơn, compiler phát warning và ghi duration definition trong project metadata.

- Image/video/text/audio clip, canvas/FPS, exact event ticks, layer ordering.
- Static fit mode, scale, position, rotation, opacity và một số effect tĩnh mà Composition Graph nhận.
- Text layer được khai báo như template content, không OCR từ ảnh.
- Reuse media theo slot policy; cùng slot có thể được dùng ở nhiều event.
- Audio layer/volume/fade được đưa vào Project V2 và Composition Graph nếu asset là audio hợp lệ.

## Giới hạn và điểm tích hợp còn thiếu

- Keyframes, custom masks, person cutout, sticker preprocessing, dependency bundling và transition khác hard cut bị từ chối.
- Rate source khác 1:1 bị từ chối vì renderer graph đang ánh xạ source time theo thời gian timeline 1:1.
- Text font cần file font mà renderer tìm được; compile graph không chứng minh font đã render đúng.
- Compiler chưa được gọi bởi FastAPI endpoint hay WPF. Catalog không có definition Fall Diary hợp lệ và Màn 3 chưa bind media.
- Project store hỗ trợ Project V2; round-trip definition/bindings qua app workflow chưa được kiểm thử.
- Native transform parity được capabilities API ghi `SUPPORTED_UNVERIFIED`; bằng chứng compiler test không nâng status parity.

Definition fixture và tests chỉ xác minh contract compiler. Chúng không phải evidence rằng Fall Diary dựng đúng demo.
