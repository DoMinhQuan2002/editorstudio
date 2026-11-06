# TASK 2.2B — Runtime Safety

## Validation build identity

One Release `win-x64` publish was prepared at `artifacts/video_editor/task2_2b_validation/desktop-build`.

```text
MediaStudio.Desktop.exe
SHA-256 2E360765E399A7075A3F30C8F96A20C16F128EC032FBD6CA2B7B6848B09D31C9

mediastudio_video_engine.dll
SHA-256 6BA825EAFB642DE35BFDE932E5484485DE58224476037ADE35F9B65AAD10A6DA
```

The WPF launcher sets a dedicated `MEDIASTUDIO_DATA_DIRECTORY`, a per-run backend log path and the DLL from this build. It does not use the user's default projects directory. The fixture generator refuses a non-empty data directory.

## Checks and remaining risks

- .NET tests: 126 passed, 0 failed.
- Selected Python Composition Graph suite: 24 passed, 3 skipped, 10 subtests passed.
- Release publish succeeded; the published app and DLL hashes were recorded.
- No WPF process-level stress, native soak, cancellation race, memory/CPU measurement, repeated project open/close, backend restart or missing-media GUI test was run.
- The current preview cancellation can suppress stale UI updates without guaranteeing cancellation of backend FFmpeg work.
- WPF audio uses multiple players and has unmeasured headroom/synchronization behavior.

Keep runtime safety and the release gate open pending manual high-load coverage and representative hardware measurements.
