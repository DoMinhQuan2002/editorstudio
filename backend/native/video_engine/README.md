# MediaStudio native video engine

This C++20 DLL provides native metadata probing, persistent frame decoding,
preview compositing, and render-job orchestration. WPF and the Python render-job
API can call the native MP4 renderer when the FFmpeg executable is available.
Python continues to store projects, media, and job state. Jobs containing audio
require the native engine so audio mixing and processing use the C++/FFmpeg path;
the Python renderer is limited to projects with no audible audio.

## Build on this workstation

Run `configure.ps1` from PowerShell. CMake uses the Visual Studio 2026 C++
toolchain and the adjacent vcpkg manifest to restore FFmpeg. vcpkg builds in
`%LOCALAPPDATA%\MediaStudio\VideoEngineBuild` because its FFmpeg port requires
a source path without spaces. The resulting engine DLL and runtime dependencies
are copied to `build-msvc-x64/Release`. The desktop project copies those files
beside its executable when the native build is present.

To make Python load the DLL from a custom build location, set
`MEDIASTUDIO_VIDEO_ENGINE_PATH` to its full path before starting the backend.
Without a built DLL, Python keeps its ffprobe/ffmpeg fallback for media metadata
and video-only rendering. Audio-bearing render jobs report that the C++ engine
must be built. WPF keeps its MediaElement preview fallback.

## Current native exports

- `msve_probe`: reads duration, dimensions, and audio/video codec metadata.
- `msve_decode_frame_rgba`: seeks and decodes a frame at a timestamp, scales it
  down while preserving aspect ratio, and returns RGBA pixels.
- `msve_decoder_open` / `msve_decoder_decode_bgra` / `msve_decoder_close`:
  keep a video decoder open during timeline playback and return scaled BGRA frames.
- `msve_compose_preview_bgra`: composites transformed, rotated, opacity-adjusted
  media and text surfaces in back-to-front order, including the warm, mono, and
  vivid clip color effects.
- `msve_render_timeline`: builds the FFmpeg filter graph for the timeline and
  runs the native FFmpeg executable with progress reporting and cancellation.
  It renders sequential clips, cut/fade transitions, text overlays, clip audio,
  and additional audio tracks into H.264/AAC MP4. The C++ engine defines the
  trim, volume, delay, fade, padding, and multi-track mix graph; FFmpeg executes
  its native audio filters and AAC encoding.
- The decoder keeps an LRU frame cache capped at 128 MiB per process for the
  existing one-shot thumbnail API.

The interface uses a small C ABI so Python and WPF can call the engine without
exposing C++ object ownership across the boundary. WPF renders text with its
installed fonts into a transparent surface; C++ composes that surface with the
current video or image frame according to the playhead and clip settings.
