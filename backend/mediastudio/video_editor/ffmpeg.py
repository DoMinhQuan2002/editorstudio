from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from mediastudio.video_editor.native_engine import NativeVideoEngine, NativeVideoEngineError


class FFmpegUnavailableError(RuntimeError):
    pass


class FFmpegToolchain:
    def __init__(self) -> None:
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")
        self.native_engine = NativeVideoEngine.try_load()

    @property
    def available(self) -> bool:
        return bool(self.ffmpeg and self.ffprobe)

    def capabilities(self) -> dict[str, object]:
        result: dict[str, object] = {
            "available": self.available,
            "ffmpegPath": self.ffmpeg,
            "ffprobePath": self.ffprobe,
            "videoFormats": ["mp4"],
            "videoCodec": "h264",
            "h264Encoding": False,
            "aacEncoding": False,
            "audioMixing": False,
            "audioFilterGraph": False,
            "nativeAudioMixing": False,
            "textOverlay": self.available,
            "nativeVideoEngine": self.native_engine is not None,
            "nativePreviewCompositor": bool(self.native_engine and
                                              self.native_engine.composition_preview_available),
            "nativeTickDecoder": bool(self.native_engine and self.native_engine.tick_decoder_available),
            "nativeCompositionRunner": bool(self.native_engine and
                                             self.native_engine.composition_runner_available),
        }
        if not self.ffmpeg or not self.ffprobe:
            result["error"] = "Không tìm thấy ffmpeg.exe hoặc ffprobe.exe trong PATH."
            return result
        try:
            version = subprocess.run([self.ffmpeg, "-version"], capture_output=True, text=True,
                                     timeout=8, check=False)
            result["version"] = version.stdout.splitlines()[0] if version.stdout else "unknown"
            filters = subprocess.run([self.ffmpeg, "-hide_banner", "-filters"], capture_output=True,
                                     text=True, timeout=8, check=False)
            filter_rows = filters.stdout
            result["textOverlay"] = "drawtext" in filter_rows
            result["audioFilterGraph"] = all(f" {name} " in filter_rows for name in ("amix", "adelay", "afade"))
            result["audioMixing"] = result["audioFilterGraph"]
            encoders = subprocess.run([self.ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                                       text=True, timeout=8, check=False)
            result["h264Encoding"] = "libx264" in encoders.stdout
            result["aacEncoding"] = " aac " in encoders.stdout
        except (OSError, subprocess.SubprocessError) as error:
            result["available"] = False
            result["error"] = str(error)
        return result

    def probe(self, path: Path) -> dict[str, Any]:
        if self.native_engine is not None:
            try:
                return self.native_engine.probe(path)
            except NativeVideoEngineError as error:
                if not self.ffprobe:
                    raise ValueError("Media không đọc được bằng engine video C++.") from error
                # Preserve media import for formats the native decoder may not
                # support yet while C++ coverage is being expanded.
        if not self.ffprobe:
            raise FFmpegUnavailableError("Không tìm thấy ffprobe.exe trong PATH.")
        try:
            process = subprocess.run(
                [self.ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                capture_output=True, text=True, timeout=20, check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise ValueError("Không thể đọc metadata media bằng ffprobe.") from error
        if process.returncode != 0:
            raise ValueError("Tệp media hỏng hoặc định dạng không được hỗ trợ.")
        try:
            return json.loads(process.stdout)
        except json.JSONDecodeError as error:
            raise ValueError("ffprobe trả metadata không hợp lệ.") from error

    def decode_frame_rgba(
        self, path: Path, timestamp_ms: int, max_width: int, max_height: int
    ) -> tuple[int, int, bytes]:
        if self.native_engine is None:
            raise FFmpegUnavailableError("Native video engine C++ chưa được build.")
        try:
            return self.native_engine.decode_frame_rgba(path, timestamp_ms, max_width, max_height)
        except NativeVideoEngineError as error:
            raise ValueError(str(error)) from error


def media_stream_info(toolchain: FFmpegToolchain, path: Path) -> dict[str, object]:
    probe = toolchain.probe(path)
    # The native engine returns normalized fields directly; ffprobe returns a
    # container object with a list of streams. Keep both backends behind this
    # common shape so media import does not depend on which probe ran.
    if "streams" not in probe and ("has_video" in probe or "has_audio" in probe):
        return {
            "duration_ms": probe.get("duration_ms"),
            "width": probe.get("width"),
            "height": probe.get("height"),
            "video_codec": probe.get("video_codec"),
            "audio_codec": probe.get("audio_codec"),
            "has_video": bool(probe.get("has_video")),
            "has_audio": bool(probe.get("has_audio")),
        }

    streams = probe.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    format_info = probe.get("format", {})
    duration = None
    for candidate in ((video or {}).get("duration"), (audio or {}).get("duration"), format_info.get("duration")):
        try:
            duration = max(0, round(float(candidate) * 1000))
            break
        except (TypeError, ValueError):
            continue
    return {
        "duration_ms": duration,
        "width": video.get("width") if video else None,
        "height": video.get("height") if video else None,
        "video_codec": video.get("codec_name") if video else None,
        "audio_codec": audio.get("codec_name") if audio else None,
        "has_video": video is not None,
        "has_audio": audio is not None,
    }
