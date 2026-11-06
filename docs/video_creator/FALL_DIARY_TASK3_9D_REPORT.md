# FALL DIARY — TASK 3.9D REPORT

**Ngày:** 2026-10-23  
**Trạng thái:** hoàn tất phân tích reference và kiểm tra parity renderer; cutout bị chặn; nghiệm thu WPF sáu màn hình còn `GUI_PENDING`.  
**Definition sử dụng:** `fall-diary / 0.3.0-reference-pilot`. Không tạo Definition 0.4 vì chưa có cutout/effect đã được reference xác nhận và model thử nghiệm chưa an toàn.

## Kết quả

### Reference và foreground

- Video Muse được xử lý như screen recording, không phải project nguồn. Contact sheet tách vùng preview và loại chrome/control của Muse; không dùng UI làm layer.
- Các candidate timestamp được xem trước/sau. Các thay đổi nhìn thấy được phân loại riêng với suy luận về cut/overlay; `15.067s` là ranh giới recording/UI che preview, không phải cut của template. Xem [FALL_DIARY_CUTOUT_REFERENCE_ANALYSIS.md](FALL_DIARY_CUTOUT_REFERENCE_ANALYSIS.md).
- Chưa có bằng chứng người/đối tượng là cutout trong các frame được quan sát. `FALL_DIARY_CUTOUT_VERIFIED=false`.
- Tile chữ `FALL DIARY` bên trong preview có khả năng cao là graphic video, tồn tại qua nhiều scene; Muse header/footer là UI. Không biết source text layer và thời điểm kết thúc chính xác.

### Model và quyết định cutout

- MODNet ONNX đã được đánh giá trên 6 ảnh riêng tư và 2 fixture không phải người. Thời gian CPU đo được 410–781 ms mỗi ảnh.
- Model cho matte có vẻ hợp lý trên một số ảnh chân dung, nhưng tạo matte nhầm cho logo `active_fox.jpg` (alpha >0.05 trên 36.28% ảnh) và biểu tượng lá (16.70%). Model không có nhãn đối tượng hoặc quality/reject signal đủ an toàn.
- Không tích hợp model, không thay đổi nguồn ảnh, không tạo output cutout cho sản phẩm, không thêm compiler riêng và không tạo Definition 0.4. `FALL_DIARY_CUTOUT_VERIFIED=false`.
- Báo cáo và ảnh QA: [VIDEO_CREATOR_SEGMENTATION_MODEL_EVALUATION.md](VIDEO_CREATOR_SEGMENTATION_MODEL_EVALUATION.md), [all_fixture_qa.jpg](../../artifacts/video_creator/task3_9d/qa/modnet/all_fixture_qa.jpg). MODNet upstream/model card nêu Apache-2.0 ([upstream](https://github.com/ZHKKKe/MODNet), [pinned model card](https://huggingface.co/Xenova/modnet/tree/fa2fa546052fba4c08921230a26cc69a333fca12)); license không giải quyết false-positive hoặc quyền với media nguồn.

### Preview và render parity

- WPF tạo draft preview cho Project ID `73da1503e49b403f9ad5c56f7d4d688c`, revision 2; definition version `0.3.0-reference-pilot`, 11 slot binding, timebase 90 kHz, 30 fps, 17 giây. Project V2 snapshot, Composition Graph, và fingerprint được giữ cùng nhau trong `artifacts/video_creator/task3_9d/`.
- Preview WPF: 540×960, H.264, 510 frame, không có audio. Shared Composition Graph render: 1080×1920, H.264, 510 frame, không có audio. FFprobe và full decode đều pass.
- So sánh 13 frame index chính xác: mean RGB MAE **5.8456/255**, max **6.98234/255**. So sánh toàn bộ 510 frame: SSIM mean **0.92632286**, min **0.914221**. Cùng slot-binding SHA-256 và Composition Graph fingerprint `365753eb926ffb71d6d5d0bef37a0eedd24ca12d02b88564684cb1d039eb6e6b`.
- MP4 `Render` được dựng qua renderer chung từ bản Project V2 đã lưu, không phải thao tác WPF Screen 6. Vì vậy renderer parity pass, còn parity của GUI export chưa được nghiệm thu.
- So sánh trực quan: [Fall_Diary_WPF_Preview_Export_Comparison.jpg](../../artifacts/video_creator/task3_9d/Fall_Diary_WPF_Preview_Export_Comparison.jpg). Video: [Preview](../../artifacts/video_creator/task3_9d/Fall_Diary_Reference_Pilot_Preview.mp4), [Render](../../artifacts/video_creator/task3_9d/Fall_Diary_Reference_Pilot_Render.mp4).

## WPF workflow

- Gallery, Details, Media Selection đã quan sát bằng WPF. Details hiển thị pilot, 11 slot từ Definition 0.3, và không có poster/demo được cấp phép.
- Media Selection mở lại draft sẵn có ở chế độ thay media. Slot `photo-11` nhận `photo_11.jpg`, đủ 11/11 slots. WPF tạo preview cho revision 2.
- Sau cập nhật, app quay về Details; Screen 6 Export không mở được trong phiên này. Không tạo hoặc dùng demo video thay cho user draft. Xem [FALL_DIARY_TASK3_9D_MANUAL_QA.md](FALL_DIARY_TASK3_9D_MANUAL_QA.md).
- Project V2 revision 1 của Task 3.9C được khôi phục byte-for-byte từ artifact đã lưu sau lần thử UI; SHA-256 artifact/runtime đều `5e71fe677376ccd32828325498508a89dc68cd3f2648bd8a17affc6cb1eddda7`. Fixture source hashes trước/sau render không đổi.

## Source changes và kiểm thử

- Product compiler, renderer, Project V2 schema, Image Tools và Definition 0.1/0.2/0.3 không bị sửa trong Task 3.9D.
- Bổ sung một QA runner tái dựng graph từ Project V2 WPF và so sánh frame: [verify_fall_diary_task39d_wpf_parity.py](../../tools/video_creator/verify_fall_diary_task39d_wpf_parity.py).
- `dotnet build MediaStudio.sln --no-restore`: thành công, 0 warning, 0 error.
- `dotnet test MediaStudio.sln --no-restore`: **55 passed**, 0 failed.
- Backend suites cho compiler, media selection, Composition Graph, Project V2, export, Fall Diary 3.9A/3.9B/3.9C: **91 passed, 3 skipped**, 1 deprecation warning từ Starlette/AnyIO.
- WPF Export Screen chưa được chạy nên backend tests không được tính là GUI acceptance.

## Cổng nghiệm thu

| Gate | Trạng thái | Cơ sở |
|---|---|---|
| `FALL_DIARY_0_3_DEFINITION_READY` | **true — baseline** | Definition 0.3 và schema chung đã xác thực trong baseline 3.9C; regression suites pass. |
| `FALL_DIARY_REFERENCE_TIMING_REVIEWED` | **true — review** | Candidate trước/sau được phân loại; detector time không được coi là source cut. |
| `FALL_DIARY_LAYOUT_QA_VERIFIED` | **true — geometry only, baseline** | Bounds/safe area/layer order của 0.3 đã kiểm tra ở 3.9C; Task 3.9D không đổi layout. Không có subject/face detection. |
| `FALL_DIARY_MOTION_VERIFIED` | **false** | Definition 0.3 không có keyframe; Task này không thêm motion thiếu bằng chứng. |
| `FALL_DIARY_CUTOUT_VERIFIED` | **false** | Reference không chứng minh cutout; model có non-person false positives. |
| `FALL_DIARY_AUDIO_FIDELITY_VERIFIED` | **false** | Không dùng nhạc Muse; quyền/timing chưa xác minh. Preview/render không có audio. |
| `FALL_DIARY_SIX_SCREEN_GUI_VERIFIED` | **false — GUI_PENDING** | Screen 6 Export chưa được nghiệm thu trong WPF. |
| `FALL_DIARY_PREVIEW_EXPORT_PARITY_VERIFIED` | **false for in-app export** | Same-graph renderer parity pass; WPF Screen 6 export chưa thực hiện. |
| `FALL_DIARY_REFERENCE_FIDELITY_VERIFIED` | **false** | Cutout/motion/audio và timing kết thúc chưa xác minh; pixel parity chỉ so hai render cùng graph. |
| `FALL_DIARY_READY_FOR_USERS` | **false** | Pilot chưa phát hành; demo/poster chưa có quyền, cutout/audio/fidelity còn blocker, GUI export pending. |

## Deliverables

- [WPF preview MP4](../../artifacts/video_creator/task3_9d/Fall_Diary_Reference_Pilot_Preview.mp4)
- [Shared-renderer MP4](../../artifacts/video_creator/task3_9d/Fall_Diary_Reference_Pilot_Render.mp4)
- [Project V2](../../artifacts/video_creator/task3_9d/Fall_Diary_Reference_Pilot_Project_V2.json)
- [Composition Graph](../../artifacts/video_creator/task3_9d/Fall_Diary_Reference_Pilot_Composition_Graph.json)
- [Manifest](../../artifacts/video_creator/task3_9d/Fall_Diary_Reference_Pilot_Manifest.json)
- [Preview/export comparison](../../artifacts/video_creator/task3_9d/Fall_Diary_WPF_Preview_Export_Comparison.jpg)
- [Foreground asset contract status](VIDEO_CREATOR_FOREGROUND_ASSET_CONTRACT.md)

## Đề xuất tiếp

1. Chạy một WPF session với runtime workspace cô lập, mở đúng Project V2 revision/bindings và hoàn tất Screen 5 → Screen 6. Lưu export record từ app rồi lặp lại full decode/parity.
2. Chỉ xét Definition 0.4 sau khi có evidence rằng foreground cutout thuộc video content và một model/quality gate từ chối an toàn non-person, occlusion, low-confidence và runtime/resource failure.
3. Giữ audio fidelity false tới khi có asset được cấp quyền cùng timing đã xác nhận.

