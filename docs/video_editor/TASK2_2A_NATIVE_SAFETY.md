# TASK 2.2A — Native safety and resources

## Ownership and synchronization

The timestamp decoder opens local FFmpeg format/codec/scaler contexts per decode request and copies its result into the existing bounded frame cache. Cache lookup/insert/copy is synchronized; the cache key now includes path, timestamp, timebase and output dimensions so 90 kHz requests cannot collide with millisecond requests. The native composition API validates dimensions, strides, alpha/effect/fit values, layer count (≤32), and destination capacity before touching buffers. ctypes owns each copied BGRA source buffer through the synchronous C call. The output buffer is allocated for the exact RGBA canvas size.

Export cancellation remains connected to the native process runner and API job cancellation flag. Temporary output is written as `.partial.mp4` and only moved to final output after success. Error and cancellation paths remove the partial output/temp files. Missing media is rejected by graph construction before a job can report success.

## AddressSanitizer run

Built a separate MSVC 2026 Release DLL with `/fsanitize=address` at:

`C:\Users\Quan\AppData\Local\MediaStudio\VideoEngineTask2_2A_ASAN_20261022\Release\mediastudio_video_engine.dll`

Instrumented modules: `backend/native/video_engine/src/video_engine.cpp` and `video_render.cpp`, including exact-tick decode, concurrent repeated seek, BGRA composition, layer validation and native process hosting. The full TASK 2.2A test module passed **27 tests, 10 subtests** under that DLL with `halt_on_error=1`; no ASan heap/bounds/use-after-free diagnostic was emitted. ASan leak detection was disabled because the host is Python and FFmpeg has process-global allocations; the run therefore does not establish leak-freedom. The DLL was built without debug information, so an ASan diagnostic would have reduced source stack detail.

FFmpeg executables and the prebuilt FFmpeg DLLs/libraries were **not instrumented**. The ASan result applies to the project C++ module at its ABI boundary, not to FFmpeg internals. Build/test log: `artifacts/video_editor/task2_2a_validation/asan_task22a_final_20261022.log`.

## Other stress coverage and limits

- 20 native decoder requests alternating two video files and seeking forward/backward, run through a 6-worker pool.
- Simultaneous base/overlay decode and native composition; repeated 60 fps timestamp test at 1,500 ticks confirms frame 1 without millisecond rounding.
- Image alpha and video preview/export parity; cancelled/error paths are covered by API/job regression where existing tests exercise them.
- No soak test across hours, memory high-water benchmark, forced cancellation under heavy native decode, or FFmpeg ASan build was performed. Those remain follow-up items.

The ordinary Release build and ASan build are separate; the ASan DLL was placed outside the source tree and did not replace historical repo/runtime DLLs.
