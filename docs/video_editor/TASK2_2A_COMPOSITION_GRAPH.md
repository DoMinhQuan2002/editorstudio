# TASK 2.2A — Composition Graph contract

Ngày kiểm chứng: 2026-10-22. Graph được tạo từ `VideoProjectV2`; JSON chuẩn không bị biến đổi.

## Luồng

```text
VideoProjectV2 (canonical, timebase 90,000)
        ↓ build_composition_graph + validation
CompositionGraph v1 (immutable render snapshot + source fingerprint)
        ├── Native C++ visual preview subset
        ├── FFmpeg filter graph preview (text/effects/fallback)
        └── FFmpeg filter graph export, optionally launched by C++ process runner
```

Graph giữ `projectId`, revision, `trackId`, `clipId`, media ID, absolute timeline/source ticks, duration, layer order, track state và các thuộc tính render. Track được sắp theo `layerOrder`; clip trong track theo `(timelineStartTicks, clipId)`. Quy ước lớp: số order nhỏ ở sau, số lớn ở trước. Không suy timeline từ vị trí mảng.

## Thời gian

```text
active(T) = timelineStartTicks <= T < timelineStartTicks + durationTicks
source(T) = sourceStartTicks + (T - timelineStartTicks)
```

Mọi phép tính giữ số nguyên 64-bit và kiểm tra tràn. Các frame rate 24, 25, 30, 60 và 30000/1001 biểu diễn chính xác trong timebase này; frame duration lần lượt là 3750, 3600, 3000, 1500 và 3003 ticks. Không snap timestamp khi đọc project. Visual clip cùng track overlap, transition khác `cut`, placeholder, media thiếu, source bounds sai và thuộc tính lạ bị từ chối.

## Duration và gap

Duration composition lấy max end time của các clip enabled có tham gia render. Gap ngoài visual là đen. Riêng project tuyến tính được `render_capability()` chấp nhận, khi audio dài hơn visual graph dùng `legacy-hold-last-visual-through-audio-end`; fixture Denim giữ đúng frame cuối tới hết audio. Chính sách này không lan sang layout mới.

## Quy tắc audio nằm trong graph

- Project thuộc linear compatibility subset: `audioMixPolicy=legacy-input-count-normalization`, giữ mức trộn baseline cũ.
- Project đa track mới: `audioMixPolicy=sum-gains-no-normalization`, cộng gain clip trực tiếp.
- Không limiter và không loudness normalization. Graph fingerprint xác định trên snapshot V2 đã canonical hóa.

## Validation và bằng chứng

Validation kiểm tra ID clip/track duy nhất, ownership, loại track/clip/media, media tồn tại, source bounds, duration dương, overflow, properties, state và semantics chưa hỗ trợ. Tests bao phủ graph xác định, giữ IDs/ticks, track order, gaps/boundaries, source offset, trạng thái track, placeholder/media lỗi, frame rate matrix và project V2 không bị mutate.

Bộ kiểm tra: [test_video_editor_task22a_composition.py](../../backend/tests/test_video_editor_task22a_composition.py). Graph và output fixture cuối: `artifacts/video_editor/task2_2a_validation/fixture_matrix_final_with_outputs_20261022/`.
