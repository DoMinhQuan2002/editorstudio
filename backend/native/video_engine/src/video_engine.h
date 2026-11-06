#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef _WIN32
#  ifdef MEDIASTUDIO_VIDEO_ENGINE_BUILD
#    define MSVE_API __declspec(dllexport)
#  else
#    define MSVE_API __declspec(dllimport)
#  endif
#else
#  define MSVE_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef struct MSVE_MediaInfo {
    int64_t duration_ms;
    int width;
    int height;
    int has_video;
    int has_audio;
    char video_codec[64];
    char audio_codec[64];
} MSVE_MediaInfo;

// A BGRA surface positioned on the preview canvas. position_x/y are normalized
// offsets from the canvas center; fit_mode is 0=contain or 1=cover.
typedef struct MSVE_PreviewLayer {
    const uint8_t* pixels;
    int width;
    int height;
    int stride;
    double position_x;
    double position_y;
    double scale;
    double rotation_degrees;
    double opacity;
    int fit_mode;
    int premultiplied_alpha;
    int effect;
} MSVE_PreviewLayer;

typedef struct MSVE_RenderClip {
    const wchar_t* media_path;
    int is_image;
    int64_t source_start_ms;
    int64_t duration_ms;
    int fit_mode;
    int effect;
    double position_x;
    double position_y;
    double scale;
    double rotation_degrees;
    double opacity;
    double audio_volume;
    int transition;
    int64_t transition_duration_ms;
    int has_audio;
} MSVE_RenderClip;

typedef struct MSVE_RenderTextLayer {
    const wchar_t* text_file_path;
    const wchar_t* color;
    int64_t start_ms;
    int64_t duration_ms;
    double x;
    double y;
    int font_size;
    double opacity;
} MSVE_RenderTextLayer;

typedef struct MSVE_RenderAudioTrack {
    const wchar_t* media_path;
    int64_t timeline_start_ms;
    int64_t source_start_ms;
    int64_t duration_ms;
    double volume;
    int64_t fade_in_ms;
    int64_t fade_out_ms;
} MSVE_RenderAudioTrack;

typedef void(__cdecl* MSVE_RenderProgressCallback)(int progress,
                                                    const char* stage_utf8,
                                                    void* user_data);

// Returns 0 on success. Errors are UTF-8 encoded and copied into error_buffer.
MSVE_API int msve_probe(const wchar_t* input_path,
                        MSVE_MediaInfo* info,
                        char* error_buffer,
                        size_t error_capacity);

// Decodes the first frame at or after timestamp_ms. The output is RGBA, scaled
// down to fit max_width x max_height without upscaling or changing aspect ratio.
// Pass a null destination (or a zero capacity) to query the required size.
// Returns 0 on success, 1 when the destination is too small, and -1 on error.
MSVE_API int msve_decode_frame_rgba(const wchar_t* input_path,
                                    int64_t timestamp_ms,
                                    int max_width,
                                    int max_height,
                                    uint8_t* destination,
                                    size_t destination_capacity,
                                    size_t* required_capacity,
                                    int* output_width,
                                    int* output_height,
                                    char* error_buffer,
                                    size_t error_capacity);

// Decodes using an exact integer timestamp in the caller's timebase.
MSVE_API int msve_decode_frame_rgba_ticks(const wchar_t* input_path,
                                          int64_t timestamp_ticks,
                                          int timebase,
                                          int max_width,
                                          int max_height,
                                          uint8_t* destination,
                                          size_t destination_capacity,
                                          size_t* required_capacity,
                                          int* output_width,
                                          int* output_height,
                                          char* error_buffer,
                                          size_t error_capacity);

// Persistent decoder session used by WPF preview playback. The returned opaque
// handle must be released with msve_decoder_close.
MSVE_API void* msve_decoder_open(const wchar_t* input_path,
                                 char* error_buffer,
                                 size_t error_capacity);
MSVE_API int msve_decoder_decode_bgra(void* decoder,
                                      int64_t timestamp_ms,
                                      int max_width,
                                      int max_height,
                                      uint8_t* destination,
                                      size_t destination_capacity,
                                      size_t* required_capacity,
                                      int* output_width,
                                      int* output_height,
                                      char* error_buffer,
                                      size_t error_capacity);
MSVE_API void msve_decoder_close(void* decoder);

// Composes media and text surfaces into one BGRA preview frame. Layers are
// processed in array order, from back to front. A null layer array is allowed.
MSVE_API int msve_compose_preview_bgra(int canvas_width,
                                       int canvas_height,
                                       const MSVE_PreviewLayer* layers,
                                       int layer_count,
                                       uint8_t* destination,
                                       size_t destination_capacity,
                                       char* error_buffer,
                                       size_t error_capacity);

// Runs the native FFmpeg render pipeline. quality: 0=draft, 1=standard, 2=high.
// Returns 0 on success, 1 when cancelled, and -1 on failure.
MSVE_API int msve_render_timeline(const wchar_t* ffmpeg_path,
                                  const wchar_t* output_path,
                                  int width,
                                  int height,
                                  int fps,
                                  const MSVE_RenderClip* clips,
                                  int clip_count,
                                  const MSVE_RenderTextLayer* text_layers,
                                  int text_layer_count,
                                  const MSVE_RenderAudioTrack* audio_tracks,
                                  int audio_track_count,
                                  int quality,
                                  const volatile int32_t* cancel_flag,
                                  MSVE_RenderProgressCallback progress_callback,
                                  void* user_data,
                                  char* error_buffer,
                                  size_t error_capacity);

// Runs a validated FFmpeg argument vector generated from a V2 CompositionGraph.
// The native host owns process lifetime, progress reporting and cancellation;
// composition rules remain in the versioned graph contract.
MSVE_API int msve_render_ffmpeg_arguments(const wchar_t* ffmpeg_path,
                                          const wchar_t* output_path,
                                          const wchar_t* const* arguments,
                                          int argument_count,
                                          double total_seconds,
                                          const volatile int32_t* cancel_flag,
                                          MSVE_RenderProgressCallback progress_callback,
                                          void* user_data,
                                          char* error_buffer,
                                          size_t error_capacity);

MSVE_API void msve_clear_frame_cache(void);
MSVE_API const char* msve_version(void);

#ifdef __cplusplus
}
#endif
