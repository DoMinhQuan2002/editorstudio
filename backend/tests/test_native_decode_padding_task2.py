from __future__ import annotations

import os
import ctypes
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from mediastudio.video_editor.native_engine import NativeVideoEngine, NativeVideoEngineError


def _runtime_fixtures() -> tuple[Path, tuple[Path, ...]]:
    engine_path = os.environ.get("MEDIASTUDIO_VIDEO_ENGINE_PATH")
    media_paths = tuple(
        Path(value) for value in os.environ.get("MEDIASTUDIO_NATIVE_REGRESSION_MEDIA", "").split(os.pathsep)
        if value.strip()
    )
    if not engine_path or not media_paths:
        pytest.skip("Set native DLL and MP4 fixture paths to run the native regression test.")
    engine = Path(engine_path)
    if not engine.is_file() or not all(media.is_file() for media in media_paths):
        pytest.skip("Native DLL or MP4 regression fixture is unavailable.")
    return engine, media_paths


def test_nonzero_frame_decode_keeps_rgba_buffer_packed_and_heap_safe() -> None:
    engine_path, media_paths = _runtime_fixtures()
    engine = NativeVideoEngine(engine_path)
    expected_matrix = {
        "v360x640_av.mp4": ((360, 640), True),
        "v640x360_video.mp4": ((640, 360), False),
        "v1280x720_video.mp4": ((1280, 720), False),
        "v1920x1080_av.mp4": ((1920, 1080), True),
        "v641x359_odd.mp4": ((641, 359), False),
        "v640x360_long_av.mp4": ((640, 360), True),
    }

    for media_path in media_paths:
        media_info = engine.probe(media_path)
        assert media_info["has_video"]
        if media_path.name in expected_matrix:
            (expected_width, expected_height), expected_audio = expected_matrix[media_path.name]
            assert (media_info["width"], media_info["height"]) == (expected_width, expected_height)
            assert media_info["has_audio"] is expected_audio
        duration_ms = media_info["duration_ms"] or 1500
        timestamps = sorted({0, min(125, duration_ms - 1), duration_ms // 2, max(0, duration_ms - 1)})

        def decode(timestamp_ms: int) -> tuple[int, int, bytes]:
            engine.clear_frame_cache()
            return engine.decode_frame_rgba(media_path, timestamp_ms, 640, 640)

        # 125 ms previously reproduced 0xc0000374 in the native process.
        for timestamp_ms in timestamps:
            width, height, pixels = decode(timestamp_ms)
            assert width > 0 and height > 0
            assert len(pixels) == width * height * 4
            assert any(pixels)

        # Public decode limits must reject dimensions before any native allocation.
        with pytest.raises(NativeVideoEngineError):
            engine.decode_frame_rgba(media_path, timestamps[0], 8193, 640)

        # Replace can overlap source preview and filmstrip work; independent FFmpeg
        # contexts must remain safe when requests decode the same asset together.
        if media_path == media_paths[0]:
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(decode, timestamps[:4]))
            assert all(len(pixels) == width * height * 4 for width, height, pixels in results)

    if os.name != "nt":
        pytest.skip("The native WPF preview-session export uses the Windows x64 ABI.")
    library = ctypes.WinDLL(str(engine_path))
    library.msve_decoder_open.argtypes = [ctypes.c_wchar_p, ctypes.c_char_p, ctypes.c_size_t]
    library.msve_decoder_open.restype = ctypes.c_void_p
    library.msve_decoder_close.argtypes = [ctypes.c_void_p]
    library.msve_decoder_close.restype = None
    decode_bgra = library.msve_decoder_decode_bgra
    decode_bgra.argtypes = [
        ctypes.c_void_p, ctypes.c_int64, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int), ctypes.c_char_p, ctypes.c_size_t,
    ]
    decode_bgra.restype = ctypes.c_int

    error = ctypes.create_string_buffer(1024)
    for media_path in media_paths:
        media_info = engine.probe(media_path)
        duration_ms = media_info["duration_ms"] or 1500
        timestamps = sorted({0, min(125, duration_ms - 1), duration_ms // 2, max(0, duration_ms - 1)})
        decoder = library.msve_decoder_open(str(media_path), error, len(error))
        assert decoder, error.value.decode("utf-8", errors="replace")
        try:
            # Reuse the WPF decoder session while moving forward and then backward.
            for timestamp_ms in timestamps + list(reversed(timestamps)):
                required = ctypes.c_size_t()
                width = ctypes.c_int()
                height = ctypes.c_int()
                result = decode_bgra(
                    decoder, timestamp_ms, 640, 640, None, 0,
                    ctypes.byref(required), ctypes.byref(width), ctypes.byref(height), error, len(error),
                )
                assert result == 1, error.value.decode("utf-8", errors="replace")
                pixels = (ctypes.c_uint8 * required.value)()
                result = decode_bgra(
                    decoder, timestamp_ms, 640, 640, pixels, required.value,
                    ctypes.byref(required), ctypes.byref(width), ctypes.byref(height), error, len(error),
                )
                assert result == 0, error.value.decode("utf-8", errors="replace")
                assert required.value == width.value * height.value * 4

                rgba_width, rgba_height, rgba = engine.decode_frame_rgba(
                    media_path, timestamp_ms, 640, 640
                )
                bgra = bytes(pixels)
                assert (width.value, height.value) == (rgba_width, rgba_height)
                assert bgra[0::4] == rgba[2::4]
                assert bgra[1::4] == rgba[1::4]
                assert bgra[2::4] == rgba[0::4]
                assert bgra[3::4] == rgba[3::4]
        finally:
            library.msve_decoder_close(decoder)

    # Release process-global decoded frames while the native library is still
    # loaded; this also exercises the cache's allocator pairing under ASAN.
    engine.clear_frame_cache()
