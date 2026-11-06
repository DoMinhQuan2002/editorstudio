# TASK 2.1B — Linear V2 render comparison

## Kết luận riêng cho rendering

- **API/C++ linear export: PASS cho fixture Denim Story cô lập.**
- **WPF Preview: BLOCKED — chưa chạy được trên GUI trong phiên này.**
- **WPF Export button: BLOCKED — chưa chạy trên GUI.**
- **Multi-track preview/export: NOT SUPPORTED; capability guard từ chối layout chưa được compositor hỗ trợ.**

Do exit criteria yêu cầu Preview và Export qua WPF, status `TASK2_1_LINEAR_RENDER_COMPATIBLE` vẫn **false**.

## Fixture và bảo toàn nguồn

V1 project ID nguồn: `3a257ef6868a4806a4bab01eaad8fe49`; bản thử nghiệm cô lập sau clone/migration: `32e8d68cc8a248b884b7dd1bb08619ee`. Không chỉnh project nguồn. Hash V1 và migration backup đều là:

```text
7cf50e30bc8afcbb35be6350d241caafd178b9e7bef05ceb1484868454a8188e
```

Sau Save và mở store/API mới: schema 2, revision 8, Track ID/order và Clip ID ổn định. Có 5 cảnh visual × 3000 ms (0–15 s), text `jeans` và audio kết thúc ở 37.608 s.

## Baseline so sánh

| Thuộc tính | Task 2.0B baseline | API V2 candidate | Kết quả |
|---|---:|---:|---|
| File size | 4,657,751 bytes | 4,657,751 bytes | bằng nhau |
| Video | H.264, 1080×1920, 30/1 fps | H.264, 1080×1920, 30/1 fps | bằng nhau |
| Video stream duration | 37.600000 s | 37.600000 s | bằng nhau |
| Audio | AAC, 44,100 Hz, stereo | AAC, 44,100 Hz, stereo | bằng nhau |
| Audio/container duration | 37.608005 s | 37.608005 s | bằng nhau |
| Full decode | exit 0, không có stderr | exit 0, không có stderr | PASS |
| SHA-256 | `14b5f2ea84269bb9362883ba98ef4747b06f24d8b7f8cae21bd33c7a4f79d370` | giống baseline | byte-identical fixture |

Candidate được tạo bằng API render job, với stage `Đã xuất video bằng C++`. Không phải WPF export.

## Nội dung hình và tiếng

Đã lấy frame ở 13 mốc: 0.0, 2.9, 3.1, 5.9, 6.1, 8.9, 9.1, 11.9, 12.1, 14.9, 15.1, 20.0 và 37.5 giây. Tất cả có RGB MAE = 0, pixel-identical với baseline. Các mốc 15.1, 20.0 và 37.5 xác nhận frame cuối tiếp tục xuất hiện sau visual 15 giây.

Đã so sánh 4 cửa sổ audio 0.4 giây, bắt đầu tại 0.2, 5.0, 15.2 và 36.5 giây. Correlation lần lượt là 0.9999998929, 1.0, 1.0, 1.0; RMS từng cửa sổ trùng baseline. Audio không bị cắt xuống 15 giây.

## Artefacts

Các file sinh ra trong `artifacts/video_editor/task2_1b_validation/`:

- `baseline-task2-0b.mp4`
- `evidence/denim-task2-1b-v2-api.mp4`
- `evidence/before-v1.json`, `migrated-v2.json`, `after-save.json`, `after-reopen.json`
- `evidence/linear-v2-summary.json`
- `evidence/baseline-inspect.json`, `v2-api-inspect.json`

Script kiểm chứng: `tools/video_editor/task2_1b/validate_linear_v2.py`. Công cụ `tools/video_editor/task2_0b/inspect_export.py` xác nhận metadata và full decode cho hai file.

## Phạm vi của PASS

Fixture tạo byte-identical output, nên metric bằng nhau ở các mốc đã lấy mẫu. Điều này chứng minh adapter/API V2 tuyến tính giữ được output trong fixture đó, bao gồm audio dài hơn visual. Nó không chứng minh mọi V2 project, preview-time WPF playback, WPF export route hoặc multi-track composition. Những hạng mục đó vẫn chờ.
