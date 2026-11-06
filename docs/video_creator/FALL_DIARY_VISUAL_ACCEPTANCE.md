# FALL DIARY — VISUAL ACCEPTANCE 3.9I

## Phạm vi nghiệm thu

Đánh giá có giới hạn cho 0.5 pilot, không phải release acceptance. Cùng 11 bindings được dùng cho bốn preview: 0.3, 0.4, 0.5 Reference Layout QA và 0.5 Editorial Safe. Project V2/Composition Graph được lưu cho từng profile. Hai biến thể 0.5 có preview/export cặp riêng.

## Kết quả kỹ thuật

| Kiểm tra | Kết quả |
|---|---|
| Definition compatibility | Regression `test_fall_diary_task39h.py`: 5 passed; kiểm tra registry .1–.5, slot count, timeline, compiler và safe layout. |
| Project V2 / Composition Graph | Compile thành công cho bốn profile; 11 slot bindings thống nhất; event boundaries theo graph giữ nguyên. |
| Preview media | Bốn MP4: H.264, 540×960, 30/1 fps, 17.000s, 510 frames, không audio; FFprobe và full decode thành công. |
| Export media | Hai MP4 của 0.5: H.264, 1080×1920, 30/1 fps, 17.000s, 510 frames, không audio; FFprobe và full decode thành công. |
| Black-frame scan | `blackdetect` (d=0.033, pix_th=0.10, pic_th=0.98) không báo interval trên 6 MP4 được tạo. |
| Preview/Export parity — Reference | 22 frame quanh mở đầu, event boundaries và cuối timeline; MAE trung bình **5.06722/255**, lớn nhất **6.89339/255**; dưới threshold 12/24. |
| Preview/Export parity — Safe | 22 frame; MAE trung bình **4.79610/255**, lớn nhất **6.82597/255**; dưới threshold 12/24. |
| Background continuity | Background events độc lập overlay replacement trong graph; không có blackdetect interval. Candidate 13.267s vẫn UNKNOWN. |
| Text/card geometry | Safe layout từ Task 3.9H: 20 layer boxes nằm trong canvas, 0 title/card geometry intersections. Điều này không đo subject overlap. |
| WPF GUI | Không chạy cho variant mới; không tuyên bố GUI acceptance hoặc Save/Reopen ở Task 3.9I. |

Các chỉ số parity so sánh output của cùng profile/bindings sau khi scale export 1080p xuống 540p bằng Lanczos; chúng không đo similarity với Muse. Contact sheet là 6 điểm thời gian để review, không thay cho annotation hoặc kiểm tra semantic toàn bộ media.

## Gates

| Gate | Trạng thái |
|---|---|
| `FALL_DIARY_MULTI_MEDIA_QA_VERIFIED` | **false — FIXTURE_MISSING** |
| `FALL_DIARY_LAYOUT_QA_VERIFIED` | **false — PARTIAL** |
| `FALL_DIARY_REFERENCE_LAYOUT_REVIEWED` | **true — QA only** |
| `FALL_DIARY_SAFE_LAYOUT_REVIEWED` | **true — QA only** |
| `FALL_DIARY_OVERLAY_MOTION_ANALYZED` | **true — limited evidence** |
| `FALL_DIARY_BACKGROUND_CONTINUITY_VERIFIED` | **true — structural/render scope** |
| `FALL_DIARY_PREVIEW_EXPORT_PARITY_VERIFIED` | **true — shared-renderer scope** |
| `FALL_DIARY_0_6_DECISION_READY` | **true — decision: defer 0.6** |
| `FALL_DIARY_REFERENCE_MOTION_VERIFIED` | **false** |
| `FALL_DIARY_REFERENCE_FIDELITY_VERIFIED` | **false** |
| `FALL_DIARY_AUDIO_FIDELITY_VERIFIED` | **false** |
| `FALL_DIARY_CUTOUT_VERIFIED` | **false** |
| `FALL_DIARY_READY_FOR_USERS` | **false** |

## Handoff

Giữ file MP4/contact sheet và QA manifest trong phạm vi nội bộ/local. Chờ người dùng duyệt layout và cung cấp fixture hợp lệ trước khi mở rộng QA hoặc cân nhắc thay đổi Definition. Không tự chạy task tiếp theo.

