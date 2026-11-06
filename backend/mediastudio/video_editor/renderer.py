from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

from mediastudio.video_editor.ffmpeg import FFmpegToolchain, FFmpegUnavailableError
from mediastudio.video_editor.jobs import VideoJob
from mediastudio.video_editor.models import VideoProject
from mediastudio.video_editor.storage import VideoMediaStore


logger = logging.getLogger("mediastudio.video_editor")


class VideoRenderError(RuntimeError):
    pass


def validate_project_media(project: VideoProject, media_store: VideoMediaStore) -> None:
    if not project.clips:
        raise VideoRenderError("Không thể xuất video khi timeline chưa có clip hình.")
    if project.width * project.height > 8_294_400:
        raise VideoRenderError("Độ phân giải kết xuất vượt 8.3 megapixel.")
    if project.duration_ms > 1_800_000:
        raise VideoRenderError("Thời lượng dự án vượt giới hạn 30 phút.")
    for index, clip in enumerate(project.clips, start=1):
        if not clip.media_id:
            raise VideoRenderError(f"Cảnh {index} ({clip.name}) chưa được gán media.")
        try:
            metadata = media_store.get_metadata(clip.media_id)
        except KeyError as error:
            raise VideoRenderError(f"Không tìm thấy media của cảnh {index}.") from error
        if metadata.kind not in {"image", "video"}:
            raise VideoRenderError(f"Media của cảnh {index} phải là ảnh hoặc video.")
        if metadata.kind == "video":
            if metadata.duration_ms is None:
                raise VideoRenderError(f"Không đọc được thời lượng video nguồn của cảnh {index} ({clip.name}).")
            if clip.source_start_ms + clip.duration_ms > metadata.duration_ms:
                raise VideoRenderError(
                    f"Cảnh {index} ({clip.name}) vượt quá thời lượng video nguồn "
                    f"({metadata.duration_ms} ms)."
                )

    for index, track in enumerate(project.audio_tracks, start=1):
        try:
            metadata = media_store.get_metadata(track.media_id)
        except KeyError as error:
            raise VideoRenderError(f"Không tìm thấy tệp của lớp âm thanh {index}.") from error
        if not metadata.audio_codec:
            raise VideoRenderError(f"Tệp của lớp âm thanh {index} không có luồng âm thanh.")
        if metadata.duration_ms is not None and track.source_start_ms + track.duration_ms > metadata.duration_ms:
            raise VideoRenderError(
                f"Lớp âm thanh {index} vượt thời lượng nguồn ({metadata.duration_ms} ms)."
            )


def render_project(
    job: VideoJob,
    project: VideoProject,
    media_store: VideoMediaStore,
    ffmpeg: FFmpegToolchain,
    output_directory: Path,
    quality: str,
) -> None:
    if not ffmpeg.ffmpeg or not ffmpeg.ffprobe:
        raise FFmpegUnavailableError("Cần cài FFmpeg gồm ffmpeg.exe và ffprobe.exe, đồng thời thêm vào PATH.")
    validate_project_media(project, media_store)
    if _has_audible_audio(project, media_store):
        _render_project_with_native_audio(job, project, media_store, ffmpeg, output_directory, quality)
        return

    output_directory.mkdir(parents=True, exist_ok=True)
    final_path = output_directory / f"{project.project_id}_{job.job_id}.mp4"
    partial_path = final_path.with_suffix(".partial.mp4")
    temporary_directory = Path(tempfile.mkdtemp(prefix=f"video_{job.job_id}_", dir=output_directory))
    try:
        command, total_seconds = build_render_command(
            project, media_store, ffmpeg, partial_path, temporary_directory, quality
        )
        job.update(state="processing", progress=1, stage="Đang kết xuất video")
        started = time.perf_counter()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", bufsize=1)
        recent_lines: list[str] = []
        out_time_us = 0
        assert process.stdout is not None
        try:
            for line in process.stdout:
                if job.cancel_event.is_set():
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    job.update(state="cancelled", progress=0, stage="Đã hủy")
                    raise VideoRenderError("Tác vụ kết xuất đã bị hủy.")
                item = line.strip()
                if not item:
                    continue
                if item.startswith("out_time_ms="):
                    try:
                        out_time_us = int(item.partition("=")[2])
                        progress = min(99, max(1, round(out_time_us / (total_seconds * 1_000_000) * 100)))
                        job.update(progress=progress, stage="Đang dựng cảnh video")
                    except (ValueError, ZeroDivisionError):
                        pass
                elif "=" not in item or item.startswith("Error"):
                    recent_lines.append(item)
                    del recent_lines[:-12]
            return_code = process.wait()
        except Exception:
            if process.poll() is None:
                process.kill()
                process.wait()
            raise
        if job.cancel_event.is_set():
            job.update(state="cancelled", progress=0, stage="Đã hủy")
            raise VideoRenderError("Tác vụ kết xuất đã bị hủy.")
        if return_code != 0 or not partial_path.is_file() or partial_path.stat().st_size == 0:
            detail = "\n".join(recent_lines[-6:])
            logger.error("Video job %s failed (%s): %s", job.job_id, return_code, detail)
            raise VideoRenderError("FFmpeg không thể kết xuất video. Kiểm tra codec và cấu hình clip.")
        partial_path.replace(final_path)
        logger.info("Video job %s completed in %.1f seconds", job.job_id, time.perf_counter() - started)
        job.update(state="succeeded", progress=100, stage="Đã xuất video", output_path=final_path)
    finally:
        partial_path.unlink(missing_ok=True)
        for path in temporary_directory.glob("*"):
            path.unlink(missing_ok=True)
        temporary_directory.rmdir()


def _has_audible_audio(project: VideoProject, media_store: VideoMediaStore) -> bool:
    if any(track.volume > 0 for track in project.audio_tracks):
        return True
    for clip in project.clips:
        if clip.audio_volume <= 0 or not clip.media_id:
            continue
        metadata = media_store.get_metadata(clip.media_id)
        if metadata.kind == "video" and metadata.audio_codec:
            return True
    return False


def _render_project_with_native_audio(
    job: VideoJob,
    project: VideoProject,
    media_store: VideoMediaStore,
    ffmpeg: FFmpegToolchain,
    output_directory: Path,
    quality: str,
) -> None:
    engine = ffmpeg.native_engine
    if engine is None:
        raise VideoRenderError("Trộn và xử lý âm thanh yêu cầu native engine C++ đã được build.")
    if not ffmpeg.ffmpeg:
        raise FFmpegUnavailableError("Không tìm thấy ffmpeg.exe.")

    output_directory.mkdir(parents=True, exist_ok=True)
    final_path = output_directory / f"{project.project_id}_{job.job_id}.mp4"
    partial_path = final_path.with_suffix(".partial.mp4")
    temporary_directory = Path(tempfile.mkdtemp(prefix=f"video_{job.job_id}_", dir=output_directory))
    started = time.perf_counter()
    try:
        job.update(state="processing", progress=1, stage="Đang chuẩn bị trộn âm thanh bằng C++")
        engine.render_project(ffmpeg.ffmpeg, partial_path, project, media_store, quality, job, temporary_directory)
        if job.cancel_event.is_set():
            job.update(state="cancelled", progress=0, stage="Đã hủy")
            raise VideoRenderError("Tác vụ kết xuất đã bị hủy.")
        if not partial_path.is_file() or partial_path.stat().st_size == 0:
            raise VideoRenderError("Engine C++ hoàn tất nhưng tệp MP4 đầu ra rỗng hoặc không tồn tại.")
        partial_path.replace(final_path)
        logger.info("Native video job %s completed in %.1f seconds", job.job_id, time.perf_counter() - started)
        job.update(state="succeeded", progress=100, stage="Đã xuất video bằng C++", output_path=final_path)
    except Exception as error:
        if job.cancel_event.is_set():
            job.update(state="cancelled", progress=0, stage="Đã hủy")
            raise VideoRenderError("Tác vụ kết xuất đã bị hủy.") from error
        if isinstance(error, VideoRenderError):
            raise
        from mediastudio.video_editor.native_engine import NativeVideoEngineError
        if isinstance(error, NativeVideoEngineError):
            raise VideoRenderError(str(error)) from error
        raise
    finally:
        partial_path.unlink(missing_ok=True)
        for path in temporary_directory.glob("*"):
            path.unlink(missing_ok=True)
        temporary_directory.rmdir()


def build_render_command(
    project: VideoProject,
    media_store: VideoMediaStore,
    ffmpeg: FFmpegToolchain,
    output_path: Path,
    temporary_directory: Path,
    quality: str,
) -> tuple[list[str], float]:
    if not ffmpeg.ffmpeg:
        raise FFmpegUnavailableError("Không tìm thấy ffmpeg.exe.")
    if _has_audible_audio(project, media_store):
        raise VideoRenderError("Renderer Python chỉ nhận dự án không có âm thanh; hãy dùng native engine C++.")
    command = [ffmpeg.ffmpeg, "-hide_banner", "-y"]
    clip_inputs: list[tuple[int, object]] = []
    for clip in project.clips:
        metadata = media_store.get_metadata(clip.media_id or "")
        path = media_store.get_path(metadata.asset_id)
        duration = clip.duration_ms / 1000
        if metadata.kind == "image":
            command.extend(["-loop", "1", "-framerate", str(project.fps), "-t", f"{duration:.3f}", "-i", str(path)])
        else:
            command.extend(["-ss", f"{clip.source_start_ms / 1000:.3f}",
                            "-t", f"{duration:.3f}", "-i", str(path)])
        clip_inputs.append((len(clip_inputs), clip))

    width, height, fps = project.width, project.height, project.fps
    filters: list[str] = []
    durations: list[float] = []
    for index, clip in clip_inputs:
        duration = clip.duration_ms / 1000
        durations.append(duration)
        scale_mode = "increase" if clip.fit_mode == "cover" else "decrease"
        chain = f"scale={width}:{height}:force_original_aspect_ratio={scale_mode}"
        if clip.fit_mode == "cover":
            chain += f",crop={width}:{height}"
        chain += f",setsar=1,fps={fps},trim=duration={duration:.3f},setpts=PTS-STARTPTS,format=rgba"
        if abs(clip.scale - 1.0) > 1e-6:
            chain += f",scale=w='max(1,iw*{clip.scale:.6f})':h='max(1,ih*{clip.scale:.6f})'"
        if abs(clip.rotation) > 1e-6:
            radians = clip.rotation * 3.141592653589793 / 180.0
            chain += f",rotate={radians:.8f}:ow=rotw(iw):oh=roth(ih):c=none"
        chain += ",format=rgba"
        chain += f",colorchannelmixer=aa={clip.opacity:.4f}[fg{index}]"
        filters.append(f"[{index}:v]{chain}")
        filters.append(f"color=c=black:s={width}x{height}:r={fps}:d={duration:.3f},format=rgba[bg{index}]")
        overlay_x = f"(W-w)/2+W*{clip.position_x:.6f}"
        overlay_y = f"(H-h)/2+H*{clip.position_y:.6f}"
        filters.append(f"[bg{index}][fg{index}]overlay=x='{overlay_x}':y='{overlay_y}':shortest=1:format=auto,format=yuv420p,settb=AVTB[raw{index}]")
        effects = {
            "warm": "colorbalance=rs=0.08:gs=0.02:bs=-0.08",
            "mono": "hue=s=0",
            "vivid": "eq=contrast=1.08:saturation=1.18",
        }
        effect_filter = effects.get(clip.effect)
        filters.append(f"[raw{index}]{effect_filter}[v{index}]" if effect_filter
                       else f"[raw{index}]null[v{index}]")

    # Join scene streams with cuts or short cross-fades. Each transition belongs to the incoming clip.
    current_label = "v0"
    accumulated = durations[0]
    for index in range(1, len(durations)):
        clip = project.clips[index]
        next_label = f"v{index}"
        output_label = f"join{index}"
        transition = min(clip.transition_duration_ms / 1000, durations[index - 1] / 2, durations[index] / 2)
        if clip.transition == "fade" and transition > 0:
            offset = max(0.0, accumulated - transition)
            filters.append(f"[{current_label}][{next_label}]xfade=transition=fade:duration={transition:.3f}:offset={offset:.3f}[{output_label}]")
            accumulated += durations[index] - transition
        else:
            filters.append(f"[{current_label}][{next_label}]concat=n=2:v=1:a=0[{output_label}]")
            accumulated += durations[index]
        current_label = output_label
    total_seconds = accumulated

    text_label_index = 0
    text_capable = bool(ffmpeg.capabilities().get("textOverlay"))
    if project.text_layers and not text_capable:
        raise FFmpegUnavailableError("Bản FFmpeg hiện tại không có bộ lọc drawtext để dựng chữ.")
    for layer in project.text_layers:
        text_path = temporary_directory / f"text_{text_label_index}.txt"
        text_path.write_text(layer.text, encoding="utf-8")
        escaped_path = _escape_filter_value(str(text_path))
        color = layer.color.lstrip("#")
        alpha = layer.opacity
        start = layer.start_ms / 1000
        end = min(total_seconds, (layer.start_ms + layer.duration_ms) / 1000)
        input_label = current_label
        output_label = f"text{ text_label_index }"
        font = _font_file(layer.font_family)
        font_argument = f":fontfile='{_escape_filter_value(font)}'" if font else ""
        filters.append(
            f"[{input_label}]drawtext=textfile='{escaped_path}':expansion=none{font_argument}:fontsize={layer.font_size}:"
            f"fontcolor=0x{color}@{alpha:.3f}:x=(w-text_w)*{layer.x:.5f}:y=(h-text_h)*{layer.y:.5f}:"
            f"enable='between(t,{start:.3f},{end:.3f})'[{output_label}]"
        )
        current_label = output_label
        text_label_index += 1

    filter_graph = ";".join(filters)
    command.extend(["-filter_complex", filter_graph, "-map", f"[{current_label}]", "-an"])
    crf, preset = {"draft": (28, "veryfast"), "standard": (21, "medium"), "high": (17, "slow")}[quality]
    command.extend(["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p"])
    command.extend(["-t", f"{total_seconds:.3f}", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(output_path)])
    return command, total_seconds


def _escape_filter_value(value: str) -> str:
    return (value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
            .replace(",", "\\,").replace("[", "\\[").replace("]", "\\]").replace(";", "\\;"))


def _font_file(family: str) -> str | None:
    # The render subset accepts only families whose exact face can be resolved.
    # Do not silently replace a stored family with Arial/Segoe UI.
    aliases = {
        "arial": "arial.ttf",
        "segoe ui": "segoeui.ttf",
        "times new roman": "times.ttf",
        "courier new": "cour.ttf",
    }
    file_name = aliases.get(family.strip().casefold())
    if file_name is None:
        return None
    candidates = []
    if os.name == "nt":
        candidates.append(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / file_name)
    elif family.strip().casefold() == "arial":
        candidates.extend([Path("/Library/Fonts/Arial.ttf"),
                           Path("/usr/share/fonts/truetype/msttcorefonts/Arial.ttf")])
    return str(next((path for path in candidates if path.is_file()), "")) or None
