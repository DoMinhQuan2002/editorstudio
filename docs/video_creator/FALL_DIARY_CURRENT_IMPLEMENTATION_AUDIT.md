# MEDIA STUDIO — FALL DIARY CURRENT IMPLEMENTATION AUDIT

> Historical baseline captured before Task 3.9A. The completed ingest, pilot definition, render artifacts and current gates are documented in [FALL_DIARY_TASK3_9A_REPORT.md](FALL_DIARY_TASK3_9A_REPORT.md).

**Ngày kiểm tra:** 23/10/2026  
**Repository root:** C:\Users\Quan\Documents\ChatGPT\Unkown app  
**Phạm vi:** kiểm tra source, catalog, definition/compiler/binding, Project V2/Composition Graph, preview/export, WPF sáu màn hình, tests và tài liệu Fall Diary hiện có. Không sửa source, không tạo definition/video/fixture, không mở hay giải mã media cá nhân.

## A. Executive Summary

Fall Diary hiện chỉ có **một catalog entry ở trạng thái REFERENCE_ONLY**. Entry giữ identity và metadata mô tả sơ bộ, nhưng duration bằng 0, không có scene, slot, definition version, poster, demo source hay render capability. Không tìm thấy Template Definition thực tế hoặc nguồn lưu definition riêng cho Fall Diary.

- **Demo:** chưa xem/phát được. Catalog không khai báo demo hoặc poster; không tìm thấy asset tương ứng và không có endpoint demo riêng. WPF Details chỉ phát file preview cục bộ đã tồn tại.
- **Chọn media:** chưa thể. Fall Diary khai báo 0 slot và không đạt eligibility của Screen 03.
- **Compile:** chưa thể cho Fall Diary. Compiler dùng chung tồn tại, nhưng không có definition Fall Diary; binding layer chỉ nhận các mapping legacy được khai báo tường minh cho template khác. Request Fall Diary bị từ chối.
- **Video thật:** chưa có Project V2, Composition Graph, preview MP4 hoặc final MP4 nào của Fall Diary được xác minh.
- **Blocker chính:** thiếu reference kit/assets và definition có slot/event thật. Vì vậy không có đầu vào để compile hoặc kiểm chứng render theo mẫu.

Pipeline Project V2 và renderer dùng chung đã có các khả năng tĩnh như ảnh/video, transform, overlay, text, hard cut và audio. Đó là năng lực nền của engine, không phải bằng chứng Fall Diary đã chạy qua pipeline. Báo cáo Task 3.8 ngày 23/10 ghi nhận Denim Story chạy sáu màn hình và có sai lệch cỡ chữ title giữa preview/export; mã hiện tại vẫn dùng nguyên fontSize khi preview được hạ xuống 540×960. Kết quả Denim Story không được tính là nghiệm thu Fall Diary.

## B. Source Inventory

| Component | Source Path | Implementation Status | Evidence | Blocker |
|---|---|---|---|---|
| Repository root | C:\Users\Quan\Documents\ChatGPT\Unkown app | Đã xác định | Git root trỏ tới workspace này; các module dưới đây nằm trong repository. | Không. |
| Video Creator Catalog | backend/mediastudio/video_editor/catalog.py:35-79,143-146 | Có metadata reference cho Fall Diary | Entry ID fall-diary, status REFERENCE_ONLY; public metadata lấy duration/canvas/scenes/slots/preview từ entry và mapping. | Metadata rỗng ở các trường cần để dùng mẫu. |
| Template Definition storage | backend/mediastudio/video_editor/template_compiler.py:35-188 | Có schema/model dùng chung; không thấy definition Fall Diary hoặc registry/storage riêng | Có model slot/layer/event/definition, nhưng tìm kiếm Fall Diary không tìm ra instance definition. | Không có dữ liệu cụ thể về slot, event, timeline, version hoặc dependencies. |
| Media Slot Binding | backend/mediastudio/video_editor/media_selection.py:8-75 | Có mapping legacy cho template khác; Fall Diary không có mapping | prepare_payload() tra LEGACY_PLACEHOLDERS, yêu cầu definition version 1.0.0-legacy; mapping không có fall-diary. | Fall Diary bị từ chối trước bước compile/binding. |
| Template Compiler | backend/mediastudio/video_editor/template_compiler.py:197-270,375-440 | Compiler tổng quát có thật; chưa tích hợp definition Fall Diary | Kiểm tra slot/media/event/layer rồi dựng Project V2; fixture compiler hiện có là dữ liệu tổng hợp khác. | Không có definition/assets để compile. Keyframes, mask/cutout, sticker và transition khác cut bị reject. |
| Project V2 / Composition Graph | backend/mediastudio/video_editor/project_v2.py; backend/mediastudio/video_editor/composition.py:164-220,381-440 | Engine tổng quát có thật; không có graph Fall Diary | Graph xác thực media, track/clip, timing, layer order, transform và text. | Chưa có project Fall Diary đầu vào. |
| Preview renderer | backend/mediastudio/video_editor/api.py:864-912; backend/mediastudio/video_editor/composition_renderer.py:50-330,460-490 | Có preview frame/video tổng quát; chưa có preview Fall Diary | Endpoint video preview nhận snapshot Project V2 và dựng proxy từ graph. | Chưa có project/graph Fall Diary; không có demo endpoint. |
| Export renderer | backend/mediastudio/video_editor/api.py:671-717,1000-1019; backend/mediastudio/video_editor/composition_renderer.py:460-490 | Có export tổng quát; chưa có final MP4 Fall Diary | Export gắn với project/graph và kiểm tra thông tin output. | Chưa có project/graph Fall Diary để xuất. |
| WPF Screens 01–06 | src/MediaStudio.Desktop/ViewModels/VideoCreatorTemplateDetailsViewModel.cs; src/MediaStudio.Desktop/ViewModels/MediaSelectionViewModel.cs; các Video Creator ViewModels/Views liên quan | UI và API client dùng chung có thật; Fall Diary chỉ đi được tới reference state | Gallery nhận catalog; Details phân giải poster/demo; Media Selection lọc eligibility; API client có các lời gọi catalog/prepare/job/project preview/export. | Eligibility và API backend chặn Fall Diary trước project. |
| Tests | backend/tests/test_template_compiler_task34.py; backend/tests/test_media_selection_task33.py; backend/tests/test_template_processing_task35.py; backend/tests/test_video_editor_project_v2_api_task21.py | Có test xác nhận catalog và từ chối workflow Fall Diary; không có test compile/render Fall Diary thành công | Xem mục G. | Không có definition/media nên chưa thể có positive end-to-end test. |

## C. Template Definition

### Dữ liệu Fall Diary thật trong Catalog

| Field | Giá trị hiện tại |
|---|---|
| Template ID / name | fall-diary / Fall Diary |
| Category | Story |
| Description | Nhật ký hình ảnh với collage và chuyển cảnh nhanh. |
| Duration | 0 ms / 0 s |
| Canvas | 1080 × 1920, tỉ lệ 9:16 |
| Frame rate | **Không được khai báo trong catalog/definition Fall Diary.** VideoTemplate.create_project() có giá trị mặc định 30/1 cho project trống nói chung; đó không phải FPS được xác minh hoặc cấu hình riêng cho Fall Diary. |
| Definition version | null |
| Availability | REFERENCE_ONLY |
| Scene count | 0 |
| Required media slots | 0 |
| Media slot requirements | [] |
| Poster / demo | posterPath=null, posterSource=null, previewSource=null, demoSource=null, previewAvailable=false |
| Render capabilities / text layers | [] / [] |

Nguồn dữ liệu là catalog entry ở catalog.py:143-146; cách public metadata được tạo ở catalog.py:52-79. Không có file definition Fall Diary riêng, không có definition record được tra ra trong code, và không có registration nào đưa Fall Diary vào LEGACY_PLACEHOLDERS.

### Schema tổng quát không đồng nghĩa với dữ liệu mẫu

template_compiler.py định nghĩa các field dùng chung:

- Slot: ID, media kinds được phép, required/optional, reuse policy, missing-slot policy (:35-48).
- Layer: kind, layer order, slot reference, source time, fit, vị trí, scale, rotation, effect, opacity, volume, text và các field animation/mask/cutout (:57-90).
- Timeline event và Template Definition: event/layer/timeline cùng metadata, version, duration và slot collection (:102-188).
- Compiler kiểm tra bindings và event/layer rồi dựng Project V2 (:197-270).

Các field/schema này chưa được điền bằng dữ liệu Fall Diary. Số clip/event của tài liệu tham khảo, kể cả con số 36 được nhắc trong task history, **không thể coi là 36 media slot**. Số slot được khai báo hiện tại trong source là **0**.

### Luồng binding hiện tại

media_selection.py:8-23 tạo slot requirements từ mapping legacy; prepare_payload() tìm mapping và kiểm tra version ở :38-75. Do không có mapping Fall Diary, test xác nhận request bị từ chối. /media-selection/prepare trả 422 khi nhận lỗi này; /processing-jobs chỉ nhận template ở PILOT_RENDERABLE hoặc READY_FOR_USERS có version khớp (api.py:334-360).

## D. Effect Capability Matrix

Các trạng thái dưới đây là đánh giá **cho Fall Diary**. Engine capability được phân biệt với hiệu ứng đã chạy trên definition/asset Fall Diary.

| Effect | Schema / Definition | Compiler → Project V2 / Graph | Preview | Export | Verified status | Gap / evidence |
|---|---|---|---|---|---|---|
| Full-frame image replacement | Fall Diary không có layer/event. Schema cho image/video layer và fit mode. | Generic visual clip có cover/contain, timing và media binding. | FFmpeg path scale/crop/overlay có thể dựng visual clip. | Cùng graph renderer có thể xuất visual clip. | IMPLEMENTED_NOT_VERIFIED | Có đường dựng ảnh nền tổng quát, nhưng không có layer/media Fall Diary hoặc render đối chứng. composition.py:381-411; composition_renderer.py:225-267. |
| Animated scale | Schema có scale tĩnh và field keyframes. Không có keyframe data Fall Diary. | Scale tĩnh được map; compiler reject keyframes (template_compiler.py:375-386). | Chỉ scale tĩnh trong graph. | Chỉ scale tĩnh trong graph. | PARTIALLY_IMPLEMENTED | Chưa có nội suy keyframe/easing; cần xác định animation từ reference kit. |
| Animated position | Schema có position tĩnh và keyframes. | Position tĩnh được map; keyframes bị reject. | Position tĩnh có thể preview. | Position tĩnh có thể export. | PARTIALLY_IMPLEMENTED | Không có chuyển động vị trí theo thời gian trong compiler/graph hiện tại. |
| Opacity animation | Schema có opacity tĩnh và keyframes. | Opacity tĩnh được map; keyframes bị reject. | Alpha tĩnh được renderer áp dụng bằng colorchannelmixer. | Alpha tĩnh được renderer áp dụng tương tự. | PARTIALLY_IMPLEMENTED | Chưa có opacity animation; không có timeline Fall Diary để thử. |
| Quick cuts | Không có event/timing Fall Diary. | Hard cut (cut) đi được qua graph; transition khác cut bị từ chối. | Generic preview theo cùng graph/timing. | Generic export theo cùng graph/timing. | IMPLEMENTED_NOT_VERIFIED | Hard cuts tổng quát có thể dựng; nhịp cut của Fall Diary chưa có định nghĩa và chưa đo từ demo. |
| Photo collage | Không có layout/layer/event Fall Diary. | Nhiều visual clip/layer và layer order tĩnh có trong graph. | Renderer overlay tuần tự các layer hình ảnh. | Export dùng cùng filtergraph cho layer. | IMPLEMENTED_NOT_VERIFIED | Chưa có geometry, crop, timing hoặc output cụ thể Fall Diary. Không thể kết luận collage mẫu gốc khớp. |
| Multiple overlays | Không có overlay Fall Diary khai báo. | Visual/text clips và layer order tĩnh có thể đi vào graph. | Renderer xử lý overlay alpha và text tĩnh. | Renderer xử lý các layer tương ứng khi export. | IMPLEMENTED_NOT_VERIFIED | Chưa có definition hoặc output Fall Diary; Task 3.8 là Denim Story. |
| Foreground cutout | Schema có mask_reference / cutout_reference, nhưng không phải năng lực chạy được. | Compiler reject mask/cutout; không thấy tích hợp segmentation trong template pipeline. | Không có mask/cutout được dựng qua template compiler. | Không có mask/cutout được dựng qua template compiler. | NOT_IMPLEMENTED | Cần artifact segmentation/mask và tích hợp pipeline. Image Tools riêng không được tính là hỗ trợ trong template renderer. |
| Text overlay | Fall Diary không khai báo text layer. | Text tĩnh được map sang clip/graph. | Text tĩnh render được, nhưng video preview dùng canvas 540×960 trong khi fontsize giữ nguyên số pixel (api.py:888-899, composition_renderer.py:281-284). | Export render cùng graph ở kích thước đầy đủ. | PARTIALLY_IMPLEMENTED | Task 3.8 báo chữ jeans lớn hơn trong preview sau khi scale về cùng kích thước; code hiện tại vẫn giữ nguyên fontsize. Nếu Fall Diary có text thì parity cần xử lý và kiểm tra lại. |
| Audio synchronization | Không có audio slot/source/event Fall Diary; manifest ghi audio source null. | Schema/compiler hỗ trợ audio clip, source/timeline mapping, volume và fades. | Video preview gọi renderer composition đầy đủ; audio single-frame preview không áp dụng. | Renderer tạo delay/fade/mix và AAC khi graph có audio (composition_renderer.py:294-329). | IMPLEMENTED_NOT_VERIFIED | Có engine path tổng quát, không có audio Fall Diary, source/rights hoặc đồng bộ mẫu để xác minh. |

**Lưu ý:** FALL_DIARY_EFFECT_MATRIX.md và capability flags mô tả giới hạn/năng lực engine dùng chung, không chứng minh một hiệu ứng Fall Diary đã chạy. Test compiler về keyframes/cutout/transition dùng fixture tổng hợp.

## E. Screen Integration Matrix

| Screen | Screen đã có? | Trạng thái Fall Diary | Evidence | Blocker |
|---|---|---|---|---|
| 01 — Gallery | Có | PARTIAL | Catalog trả về entry fall-diary; Gallery mở Details theo catalog. | Chỉ hiển thị reference; không đủ điều kiện áp dụng/chọn media. |
| 02 — Template Details | Có | PARTIAL | Details hiện metadata/status và placeholder khi thiếu poster/demo. ResolvePlayablePreview() yêu cầu preview available, path cục bộ hợp lệ/tồn tại và extension được hỗ trợ (VideoCreatorTemplateDetailsViewModel.cs:162-205). | Catalog không có preview/poster. Không có demo endpoint; chưa có playback thật cho Fall Diary. |
| 03 — Media Selection | Có | BLOCKED | MediaSelectionViewModel.IsEligible() yêu cầu availability cho phép, definition version và ít nhất một slot (MediaSelectionViewModel.cs:49-64). | Fall Diary có REFERENCE_ONLY, version null, 0 slot. |
| 04 — Processing | Có | BLOCKED | /processing-jobs kiểm tra status/version; test trực tiếp kỳ vọng 422 và không tạo job (api.py:341-360; test Task 3.5). | Không có definition/binding hợp lệ; job bị chặn. |
| 05 — Draft Preview | Có cho Project V2 nói chung | NOT_IMPLEMENTED cho Fall Diary | Endpoint preview nhận Project V2 snapshot rồi dựng proxy MP4 từ Composition Graph (api.py:864-912). | Chưa có Project V2/graph Fall Diary. Không có preview video Fall Diary. |
| 06 — Export | Có cho Project V2 nói chung | NOT_IMPLEMENTED cho Fall Diary | Export tổng quát nhận project/graph và sinh MP4; WPF flow không có đầu vào Fall Diary hợp lệ. | Chưa có Project V2/graph Fall Diary. Không có final MP4 Fall Diary. |

Không có màn nào được đánh dấu PASS cho Fall Diary dựa trên việc Denim Story chạy được.

## F. Missing Assets

Manifest hiện có tại docs/video_creator/fall-diary-asset-manifest.json tự ghi nhận:

| Asset | Kết quả hiện tại |
|---|---|
| FALL_DIARY_Reference_Kit.zip | found=false; SHA-256 manifest chưa xác minh; README chưa đọc. |
| Demo video | source null, không tìm thấy; quyền sử dụng chưa xác minh. |
| Poster | source null, không tìm thấy; quyền sử dụng chưa xác minh. |
| Audio | source null, không tìm thấy; quyền sử dụng chưa xác minh. |
| 12 private test fixtures | tìm thấy 0/12; không publishable. |
| Packaged personal assets | danh sách rỗng. |

Kiểm tra tên/tài liệu được giới hạn trong workspace repository và C:\Users\Quan\.codex\attachments; không tìm thấy reference ZIP hoặc video Fall Diary theo tên. Không mở, giải mã hoặc sao chép media. Tài liệu FALL_DIARY_REFERENCE_ANALYSIS.md cũng ghi nhận kit không có trong các vị trí đó; đây là tài liệu trạng thái, không thay cho việc kiểm tra lại video.

**Cần có trước khi kiểm tra tính đúng mẫu:** reference kit theo đúng nguồn; README/hash và quyền dùng; demo MP4; poster nếu có; 12 fixture nếu được phép dùng; audio nếu thuộc mẫu. Không tự tạo/thay thế bất kỳ file nào.

## G. Existing Tests

### Bài test liên quan trực tiếp

- backend/tests/test_template_compiler_task34.py::test_catalog_registers_fall_diary_once_as_reference_only: xác nhận đúng một entry, status REFERENCE_ONLY, previewAvailable=false, 0 required slot, duration 0, demo/poster null.
- backend/tests/test_template_compiler_task34.py::test_catalog_does_not_treat_scene_events_as_media_slots: kiểm tra nguyên tắc tách event khỏi slot; không chứng minh Fall Diary compile.
- backend/tests/test_media_selection_task33.py::test_invalid_bindings_and_unavailable_definition: xác nhận prepare_payload() từ chối fall-diary.
- backend/tests/test_template_processing_task35.py::test_processing_rejects_reference_only_templates_and_bad_media_before_job_creation: xác nhận request Fall Diary nhận 422 và job store rỗng.
- backend/tests/test_video_editor_project_v2_api_task21.py catalog test: xác nhận status, tỉ lệ 9:16, 0 slot/duration và poster/preview null.
- Các test còn lại trong compiler suite dùng fixture tổng hợp khác (ví dụ compiler-fixture) để kiểm tra generic mapping hoặc reject keyframes/cutout/transition. Chúng không phải test compile Fall Diary.
- WPF tests hiện có kiểm tra view/XAML và hành vi đường dẫn preview tổng quát; không tìm thấy test phát demo Fall Diary thực tế.

### Kết quả chạy trực tiếp trong lần audit này

Chạy bốn file test backend liên quan từ backend/ bằng Python -B và pytest -p no:cacheprovider:

**31 passed, 1 warning in 3.14s.**

Warning là deprecation warning của AnyIO. Các test chứng minh catalog/reference-only, từ chối binding/job và khả năng tổng quát của compiler/API; **không** chứng minh render Fall Diary.

### Tài liệu và kết quả lịch sử

- VIDEO_CREATOR_TASK3_8_END_TO_END_REPORT.md — **HISTORICAL, Denim Story**. Ghi nhận WPF sáu màn hình, Project V2 revision 2, 5 media bindings, preview/export MP4 và full decode; cũng ghi rõ chữ jeans lớn hơn trong preview sau khi quy về 540×960 và parity gate false. Không phải bằng chứng Fall Diary.
- docs/video_creator/FALL_DIARY_REFERENCE_ANALYSIS.md, FALL_DIARY_RENDER_COMPARISON.md, FALL_DIARY_EFFECT_MATRIX.md, FALL_DIARY_FFPROBE_REPORT.json — tài liệu phân tích/trạng thái trước đó. Không có video Fall Diary để probe/render; các kết luận về blocker được đối chiếu lại với source hiện tại. FFprobe report không phải probe output của demo MP4.

## H. Remaining Work — theo thứ tự phụ thuộc

1. **Nhận đúng reference kit** và xác nhận README, SHA-256, quyền dùng từng loại asset; xác định 12 ảnh có thể dùng cho test hay chỉ là private reference.
2. **Phân tích demo gốc**: thông số video/audio, mốc cut, thời lượng, bố cục collage, overlay, text, cutout và quan hệ với audio. Giữ phân biệt số lần xuất hiện clip với số slot cần người dùng cấp.
3. **Tạo definition có version** với canvas/FPS/duration, dependencies, slot IDs/policies, timeline events, source mapping, layers/z-order, fit/transform/text/audio. Không đánh dấu slot từ nhãn clip nếu chưa xác định yêu cầu reuse.
4. **Đăng ký binding/eligibility cho Fall Diary** và xác định rõ capability boundary. Dùng compiler hiện có cho phần được hỗ trợ; quyết định riêng cách xử lý animation/cutout thay vì để các field schema bị hiểu nhầm là đã chạy được.
5. **Sinh Project V2 và Composition Graph Fall Diary thật** từ definition và fixture được phép dùng; thêm test compilation Fall Diary với dữ liệu thật đã kiểm duyệt.
6. **Dựng first preview và final MP4** từ cùng snapshot; kiểm tra FFprobe, full decode, frame rate/duration/audio, các cut/layer/text và preview/export parity; lưu evidence cho chính Fall Diary.
7. **Nghiệm thu WPF sáu màn hình Fall Diary** bằng project được tạo qua workflow; kiểm tra demo Details, binding, processing, draft preview và export. Sau đó mới mở rộng animation/cutout và so sánh fidelity với reference.

## I. Recommended Next Task

**Task kế tiếp đề xuất:** “Fall Diary — ingest reference kit, tạo versioned MVP definition và chứng minh first render.”

Phạm vi nhỏ nhất để tạo video Fall Diary đầu tiên:

1. Đưa reference kit được phép sử dụng vào workspace và xác minh hash/README/quyền dùng.
2. Từ kit, tạo definition có thật với slot/event tối thiểu cần thiết cho một phiên bản render tĩnh có hard cuts và các overlay tĩnh mà renderer hiện hỗ trợ.
3. Đăng ký binding Fall Diary, compile sang Project V2/Graph, render preview và MP4 từ fixture được phép.
4. Thêm test Fall Diary-specific cho definition → graph → render; xác minh output bằng FFprobe/full decode và so preview/export.
5. Ghi rõ animated transforms và foreground cutout còn thiếu nếu MVP chưa hỗ trợ chúng.

Đây là **first validated render**, chưa phải hoàn thiện hiệu ứng và chưa phải nghiệm thu sản phẩm. Hoàn thiện keyframe/cutout fidelity và đối chiếu toàn bộ demo là các bước sau; nghiệm thu sản phẩm cần đi hết sáu màn hình WPF bằng Fall Diary thật. Không nên lập lại compiler, Project V2, graph hay renderer đã có; cần nối definition/assets Fall Diary vào các thành phần đó.

## Kết quả cuối cùng

1. **Fall Diary hiện hoàn thành gì?** Có catalog identity, metadata reference tối thiểu, UI có thể hiển thị trạng thái reference và test xác nhận catalog/guard từ chối workflow.
2. **Thành phần nào mới chỉ có dạng code/schema?** Definition schema và compiler tổng quát; field cho event/layer/keyframe/mask/audio không phải definition Fall Diary. Project V2/Graph/renderer có code dùng chung nhưng chưa nhận dữ liệu Fall Diary.
3. **Hiệu ứng nào đã hoạt động thật?** Chưa có hiệu ứng nào được xác minh trên Fall Diary. Ảnh/video tĩnh, hard cut, transform/alpha tĩnh, text tĩnh, overlay và audio có đường chạy tổng quát trong engine; Task 3.8 chỉ chứng minh một số phần trên Denim Story/fixture.
4. **Hiệu ứng nào chưa hoạt động?** Animation scale/position/opacity theo keyframe chưa được compiler hỗ trợ; mask/cutout chưa tích hợp; các transition ngoài cut bị từ chối. Các hiệu ứng này chưa được kiểm tra trên Fall Diary.
5. **Đã dựng video từ media người dùng cho Fall Diary chưa?** Chưa. Binding và job Fall Diary hiện bị chặn; không có project, graph, preview hoặc final MP4 Fall Diary được xác minh.
6. **Còn thiếu tài nguyên nào?** Reference ZIP, README/hash đã xác minh, demo video, poster, 12 private test fixtures và audio nếu mẫu yêu cầu; quyền sử dụng còn chưa xác minh.
7. **Task tiếp theo?** Nhận/xác minh kit, lập definition MVP có version, nối binding/compiler và tạo first render có test, FFprobe/full decode và preview/export comparison.

FALL_DIARY_CATALOG_STATUS = REFERENCE_ONLY — entry tồn tại nhưng chưa đủ để dùng (catalog.py:143-146).

FALL_DIARY_DEMO_READY = FALSE — MISSING_ASSET; source null, file không tìm thấy, không có playback evidence.

FALL_DIARY_DEFINITION_READY = FALSE — không có definition/version/event/slot Fall Diary; slot count hiện tại 0.

FALL_DIARY_COMPILER_READY = FALSE_FOR_FALL_DIARY — compiler tổng quát có thật, nhưng Fall Diary không có definition/binding và bị từ chối trước compile.

FALL_DIARY_RENDER_READY = FALSE_FOR_FALL_DIARY — renderer tổng quát có thật nhưng chưa có Project V2/Composition Graph Fall Diary.

FALL_DIARY_END_TO_END_VERIFIED = FALSE — chưa có workflow sáu màn hình, demo, render hay export được xác minh cho Fall Diary.
