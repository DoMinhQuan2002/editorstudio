from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path
import threading
from typing import Any

from mediastudio.video_editor.diagnostics import video_request_id


class NativeVideoEngineError(RuntimeError):
    pass


_logger = logging.getLogger("mediastudio.video_editor.native")


class _MediaInfo(ctypes.Structure):
    _fields_ = [
        ("duration_ms", ctypes.c_int64),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("has_video", ctypes.c_int),
        ("has_audio", ctypes.c_int),
        ("video_codec", ctypes.c_char * 64),
        ("audio_codec", ctypes.c_char * 64),
    ]


class _PreviewLayer(ctypes.Structure):
    _fields_ = [
        ("pixels", ctypes.POINTER(ctypes.c_uint8)),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("stride", ctypes.c_int),
        ("position_x", ctypes.c_double),
        ("position_y", ctypes.c_double),
        ("scale", ctypes.c_double),
        ("rotation_degrees", ctypes.c_double),
        ("opacity", ctypes.c_double),
        ("fit_mode", ctypes.c_int),
        ("premultiplied_alpha", ctypes.c_int),
        ("effect", ctypes.c_int),
    ]


class _RenderClip(ctypes.Structure):
    _fields_ = [
        ("media_path", ctypes.c_wchar_p),
        ("is_image", ctypes.c_int),
        ("source_start_ms", ctypes.c_int64),
        ("duration_ms", ctypes.c_int64),
        ("fit_mode", ctypes.c_int),
        ("effect", ctypes.c_int),
        ("position_x", ctypes.c_double),
        ("position_y", ctypes.c_double),
        ("scale", ctypes.c_double),
        ("rotation_degrees", ctypes.c_double),
        ("opacity", ctypes.c_double),
        ("audio_volume", ctypes.c_double),
        ("transition", ctypes.c_int),
        ("transition_duration_ms", ctypes.c_int64),
        ("has_audio", ctypes.c_int),
    ]


class _RenderTextLayer(ctypes.Structure):
    _fields_ = [
        ("text_file_path", ctypes.c_wchar_p),
        ("color", ctypes.c_wchar_p),
        ("start_ms", ctypes.c_int64),
        ("duration_ms", ctypes.c_int64),
        ("x", ctypes.c_double),
        ("y", ctypes.c_double),
        ("font_size", ctypes.c_int),
        ("opacity", ctypes.c_double),
    ]


class _RenderAudioTrack(ctypes.Structure):
    _fields_ = [
        ("media_path", ctypes.c_wchar_p),
        ("timeline_start_ms", ctypes.c_int64),
        ("source_start_ms", ctypes.c_int64),
        ("duration_ms", ctypes.c_int64),
        ("volume", ctypes.c_double),
        ("fade_in_ms", ctypes.c_int64),
        ("fade_out_ms", ctypes.c_int64),
    ]


_RenderProgressCallback = ctypes.CFUNCTYPE(
    None, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p
)


class NativeVideoEngine:
    """ctypes boundary for the FFmpeg-backed native engine DLL."""

    def __init__(self, library_path: Path) -> None:
        self.library_path = library_path
        self._dll_directory = os.add_dll_directory(str(library_path.parent)) if os.name == "nt" else None
        loader = ctypes.WinDLL if os.name == "nt" else ctypes.CDLL
        self._library = loader(str(library_path))
        self._configure_exports()
        self.composition_runner_available = hasattr(self._library, "msve_render_ffmpeg_arguments")
        self.composition_preview_available = hasattr(self._library, "msve_compose_preview_bgra")
        self.tick_decoder_available = hasattr(self._library, "msve_decode_frame_rgba_ticks")

    @classmethod
    def try_load(cls) -> NativeVideoEngine | None:
        configured = os.environ.get("MEDIASTUDIO_VIDEO_ENGINE_PATH")
        candidates = [Path(configured)] if configured else []
        module_root = Path(__file__).resolve().parents[2]
        native_root = module_root / "native" / "video_engine"
        candidates.extend(
            [
                native_root / "build-msvc-x64" / "Release" / "mediastudio_video_engine.dll",
                native_root / "build-msvc-x64" / "Debug" / "mediastudio_video_engine.dll",
                native_root / "build-msvc-x64" / "mediastudio_video_engine.so",
            ]
        )
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                return cls(candidate)
            except (OSError, AttributeError):
                continue
        return None

    @property
    def available(self) -> bool:
        return True

    def probe(self, path: Path) -> dict[str, Any]:
        info = _MediaInfo()
        error = ctypes.create_string_buffer(1024)
        result = self._library.msve_probe(str(path), ctypes.byref(info), error, len(error))
        if result != 0:
            raise NativeVideoEngineError(self._error_message(error, "Không đọc được metadata media bằng engine C++."))
        return {
            "duration_ms": info.duration_ms if info.duration_ms >= 0 else None,
            "width": info.width or None,
            "height": info.height or None,
            "video_codec": self._decode_text(info.video_codec) if info.has_video else None,
            "audio_codec": self._decode_text(info.audio_codec) if info.has_audio else None,
            "has_video": bool(info.has_video),
            "has_audio": bool(info.has_audio),
        }

    def decode_frame_rgba(
        self, path: Path, timestamp_ms: int, max_width: int, max_height: int
    ) -> tuple[int, int, bytes]:
        correlation_id = video_request_id.get()
        media_id = Path(path).name.split(".", 1)[0].lstrip(".")
        _logger.info(
            "native.frame_decode.begin correlation_id=%s pid=%s thread_id=%s media_id=%s timestamp_ms=%s",
            correlation_id, os.getpid(), threading.get_ident(), media_id, timestamp_ms,
        )
        try:
            result = self._decode_frame_rgba_impl(path, timestamp_ms, max_width, max_height)
        except Exception:
            _logger.exception(
                "native.frame_decode.error correlation_id=%s pid=%s thread_id=%s media_id=%s timestamp_ms=%s",
                correlation_id, os.getpid(), threading.get_ident(), media_id, timestamp_ms,
            )
            raise
        _logger.info(
            "native.frame_decode.end correlation_id=%s pid=%s thread_id=%s media_id=%s "
            "timestamp_ms=%s width=%s height=%s bytes=%s",
            correlation_id, os.getpid(), threading.get_ident(), media_id, timestamp_ms,
            result[0], result[1], len(result[2]),
        )
        return result

    def decode_frame_ticks(
        self, path: Path, timestamp_ticks: int, timebase: int, max_width: int, max_height: int
    ) -> tuple[int, int, bytes]:
        if not self.tick_decoder_available:
            raise NativeVideoEngineError("Native engine chưa hỗ trợ timestamp theo timebase chính xác.")
        return self._decode_frame_rgba_impl(path, timestamp_ticks, max_width, max_height, timebase)

    def _decode_frame_rgba_impl(
        self, path: Path, timestamp: int, max_width: int, max_height: int, timebase: int = 1000
    ) -> tuple[int, int, bytes]:
        error = ctypes.create_string_buffer(1024)
        required = ctypes.c_size_t()
        width = ctypes.c_int()
        height = ctypes.c_int()
        if timebase == 1000:
            decode = self._library.msve_decode_frame_rgba
            common_args = (str(path), timestamp, max_width, max_height)
        else:
            if not self.tick_decoder_available:
                raise NativeVideoEngineError("Native engine chưa hỗ trợ timestamp theo timebase chính xác.")
            decode = self._library.msve_decode_frame_rgba_ticks
            common_args = (str(path), timestamp, timebase, max_width, max_height)
        result = decode(*common_args, None, 0, ctypes.byref(required), ctypes.byref(width), ctypes.byref(height),
                        error, len(error))
        if result not in (0, 1):
            raise NativeVideoEngineError(self._error_message(error, "Không giải mã được frame bằng engine C++."))
        if required.value <= 0:
            raise NativeVideoEngineError("Engine C++ không trả kích thước frame hợp lệ.")
        pixels = (ctypes.c_uint8 * required.value)()
        result = decode(*common_args, pixels, required.value, ctypes.byref(required), ctypes.byref(width),
                        ctypes.byref(height), error, len(error))
        if result != 0:
            raise NativeVideoEngineError(self._error_message(error, "Không lấy được frame RGBA từ engine C++."))
        return width.value, height.value, bytes(pixels)

    def clear_frame_cache(self) -> None:
        self._library.msve_clear_frame_cache()

    def compose_preview_bgra(self, width: int, height: int, layers: list[dict[str, Any]]) -> bytes:
        if not self.composition_preview_available:
            raise NativeVideoEngineError("Native engine chưa có bộ compositing preview.")
        if width < 1 or height < 1 or width > 4096 or height > 4096 or len(layers) > 32:
            raise NativeVideoEngineError("Kích thước canvas hoặc số lớp preview vượt giới hạn native.")

        keepalive: list[Any] = []
        native_layers = (_PreviewLayer * len(layers))()
        effect_ids = {"none": 0, "warm": 1, "mono": 2, "vivid": 3}
        for index, layer in enumerate(layers):
            layer_width = int(layer["width"])
            layer_height = int(layer["height"])
            rgba = bytes(layer["rgba"])
            if layer_width < 1 or layer_height < 1 or len(rgba) != layer_width * layer_height * 4:
                raise NativeVideoEngineError("Pixel buffer của một lớp preview không hợp lệ.")
            bgra = bytearray(rgba)
            for offset in range(0, len(bgra), 4):
                bgra[offset], bgra[offset + 2] = bgra[offset + 2], bgra[offset]
            pixel_buffer = (ctypes.c_uint8 * len(bgra)).from_buffer_copy(bgra)
            keepalive.append(pixel_buffer)
            native_layers[index] = _PreviewLayer(
                ctypes.cast(pixel_buffer, ctypes.POINTER(ctypes.c_uint8)),
                layer_width,
                layer_height,
                layer_width * 4,
                float(layer.get("positionX", 0.0)),
                float(layer.get("positionY", 0.0)),
                float(layer.get("scale", 1.0)),
                float(layer.get("rotation", 0.0)),
                float(layer.get("opacity", 1.0)),
                1 if layer.get("fitMode", "cover") == "cover" else 0,
                0,  # Project media uses straight alpha.
                effect_ids[str(layer.get("effect", "none"))],
            )

        destination = (ctypes.c_uint8 * (width * height * 4))()
        error = ctypes.create_string_buffer(1024)
        result = self._library.msve_compose_preview_bgra(
            width, height, native_layers if layers else None, len(layers),
            destination, len(destination), error, len(error),
        )
        if result != 0:
            raise NativeVideoEngineError(self._error_message(error, "Native engine không ghép được preview."))
        return bytes(destination)

    def render_ffmpeg_arguments(self, ffmpeg_path: str, output_path: Path, arguments: list[str],
                                total_seconds: float, job: Any) -> None:
        if not self.composition_runner_available:
            raise NativeVideoEngineError("Native engine hiện tại chưa có Composition Graph process runner.")
        native_arguments = [str(argument) for argument in arguments]
        argument_array = (ctypes.c_wchar_p * len(native_arguments))(*native_arguments)
        error = ctypes.create_string_buffer(2048)
        cancel_flag = ctypes.c_int32(int(job.cancel_event.is_set()))
        stop_watcher = threading.Event()

        def watch_cancellation() -> None:
            while not stop_watcher.wait(0.05):
                if job.cancel_event.is_set():
                    cancel_flag.value = 1
                    return

        watcher = threading.Thread(target=watch_cancellation, name="native-composition-cancel", daemon=True)
        watcher.start()

        def on_progress(percent: int, stage: bytes | None, _user_data: int) -> None:
            try:
                message = stage.decode("utf-8", errors="replace") if stage else "Đang dựng Composition Graph"
                job.update(state="processing", progress=percent, stage=message)
                if job.cancel_event.is_set():
                    cancel_flag.value = 1
            except Exception:
                return

        callback = _RenderProgressCallback(on_progress)
        try:
            result = self._library.msve_render_ffmpeg_arguments(
                ffmpeg_path, str(output_path), argument_array, len(native_arguments), float(total_seconds),
                ctypes.byref(cancel_flag), callback, None, error, len(error),
            )
        finally:
            stop_watcher.set()
            watcher.join(timeout=1)
        if result == 1 or job.cancel_event.is_set():
            raise NativeVideoEngineError("Đã hủy kết xuất composition.")
        if result != 0:
            raise NativeVideoEngineError(
                self._error_message(error, "Native engine không thể thực thi FFmpeg Composition Graph.")
            )

    def render_project(
        self,
        ffmpeg_path: str,
        output_path: Path,
        project: Any,
        media_store: Any,
        quality: str,
        job: Any,
        temporary_directory: Path,
    ) -> None:
        clips = []
        for clip in project.clips:
            metadata = media_store.get_metadata(clip.media_id or "")
            clips.append(_RenderClip(
                str(media_store.get_path(metadata.asset_id)),
                int(metadata.kind == "image"),
                clip.source_start_ms,
                clip.duration_ms,
                int(clip.fit_mode == "cover"),
                {"none": 0, "warm": 1, "mono": 2, "vivid": 3}[clip.effect],
                clip.position_x,
                clip.position_y,
                clip.scale,
                clip.rotation,
                clip.opacity,
                clip.audio_volume,
                int(clip.transition == "fade"),
                clip.transition_duration_ms,
                int(metadata.kind == "video" and bool(metadata.audio_codec)),
            ))

        text_layers = []
        for index, layer in enumerate(project.text_layers):
            text_path = temporary_directory / f"text_{index}.txt"
            text_path.write_text(layer.text, encoding="utf-8")
            text_layers.append(_RenderTextLayer(
                str(text_path), layer.color, layer.start_ms, layer.duration_ms,
                layer.x, layer.y, layer.font_size, layer.opacity,
            ))

        audio_tracks = []
        for track in project.audio_tracks:
            metadata = media_store.get_metadata(track.media_id)
            audio_tracks.append(_RenderAudioTrack(
                str(media_store.get_path(metadata.asset_id)),
                track.timeline_start_ms,
                track.source_start_ms,
                track.duration_ms,
                track.volume,
                track.fade_in_ms,
                track.fade_out_ms,
            ))

        clip_array = (_RenderClip * len(clips))(*clips)
        text_array = (_RenderTextLayer * len(text_layers))(*text_layers) if text_layers else None
        audio_array = (_RenderAudioTrack * len(audio_tracks))(*audio_tracks) if audio_tracks else None
        error = ctypes.create_string_buffer(2048)
        cancel_flag = ctypes.c_int32(int(job.cancel_event.is_set()))
        stop_watcher = threading.Event()

        def watch_cancellation() -> None:
            while not stop_watcher.wait(0.05):
                if job.cancel_event.is_set():
                    cancel_flag.value = 1
                    return

        watcher = threading.Thread(target=watch_cancellation, name="native-render-cancel", daemon=True)
        watcher.start()

        def on_progress(percent: int, stage: bytes | None, _user_data: int) -> None:
            try:
                message = stage.decode("utf-8", errors="replace") if stage else "Đang kết xuất bằng C++"
                job.update(state="processing", progress=percent, stage=message)
                if job.cancel_event.is_set():
                    cancel_flag.value = 1
            except Exception:
                # A callback must never unwind across the native ABI boundary.
                return

        callback = _RenderProgressCallback(on_progress)
        try:
            result = self._library.msve_render_timeline(
                ffmpeg_path,
                str(output_path),
                project.width,
                project.height,
                project.fps,
                clip_array,
                len(clips),
                text_array,
                len(text_layers),
                audio_array,
                len(audio_tracks),
                {"draft": 0, "standard": 1, "high": 2}[quality],
                ctypes.byref(cancel_flag),
                callback,
                None,
                error,
                len(error),
            )
        finally:
            stop_watcher.set()
            watcher.join(timeout=1)

        if result == 1 or job.cancel_event.is_set():
            raise NativeVideoEngineError("Đã hủy kết xuất video.")
        if result != 0:
            raise NativeVideoEngineError(
                self._error_message(error, "Engine C++ không thể kết xuất video.")
            )

    def _configure_exports(self) -> None:
        self._library.msve_probe.argtypes = [
            ctypes.c_wchar_p, ctypes.POINTER(_MediaInfo), ctypes.c_char_p, ctypes.c_size_t,
        ]
        self._library.msve_probe.restype = ctypes.c_int
        self._library.msve_decode_frame_rgba.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_int64,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint8),
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_char_p,
            ctypes.c_size_t,
        ]
        self._library.msve_decode_frame_rgba.restype = ctypes.c_int
        if hasattr(self._library, "msve_decode_frame_rgba_ticks"):
            self._library.msve_decode_frame_rgba_ticks.argtypes = [
                ctypes.c_wchar_p,
                ctypes.c_int64,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_uint8),
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_size_t),
                ctypes.POINTER(ctypes.c_int),
                ctypes.POINTER(ctypes.c_int),
                ctypes.c_char_p,
                ctypes.c_size_t,
            ]
            self._library.msve_decode_frame_rgba_ticks.restype = ctypes.c_int
        if hasattr(self._library, "msve_compose_preview_bgra"):
            self._library.msve_compose_preview_bgra.argtypes = [
                ctypes.c_int,
                ctypes.c_int,
                ctypes.POINTER(_PreviewLayer),
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_uint8),
                ctypes.c_size_t,
                ctypes.c_char_p,
                ctypes.c_size_t,
            ]
            self._library.msve_compose_preview_bgra.restype = ctypes.c_int
        self._library.msve_clear_frame_cache.argtypes = []
        self._library.msve_clear_frame_cache.restype = None
        self._library.msve_render_timeline.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(_RenderClip),
            ctypes.c_int,
            ctypes.POINTER(_RenderTextLayer),
            ctypes.c_int,
            ctypes.POINTER(_RenderAudioTrack),
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int32),
            _RenderProgressCallback,
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_size_t,
        ]
        self._library.msve_render_timeline.restype = ctypes.c_int
        if hasattr(self._library, "msve_render_ffmpeg_arguments"):
            self._library.msve_render_ffmpeg_arguments.argtypes = [
                ctypes.c_wchar_p,
                ctypes.c_wchar_p,
                ctypes.POINTER(ctypes.c_wchar_p),
                ctypes.c_int,
                ctypes.c_double,
                ctypes.POINTER(ctypes.c_int32),
                _RenderProgressCallback,
                ctypes.c_void_p,
                ctypes.c_char_p,
                ctypes.c_size_t,
            ]
            self._library.msve_render_ffmpeg_arguments.restype = ctypes.c_int

    @staticmethod
    def _decode_text(value: bytes) -> str:
        return value.split(b"\0", 1)[0].decode("ascii", errors="replace")

    @classmethod
    def _error_message(cls, buffer: ctypes.Array[ctypes.c_char], fallback: str) -> str:
        return buffer.value.decode("utf-8", errors="replace") or fallback
