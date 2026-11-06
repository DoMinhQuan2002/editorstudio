from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
import logging
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time
from typing import Any

from PIL import Image

from mediastudio.video_editor.composition import (
    CompositionClip, CompositionGraph, CompositionGraphError, clip_is_active, source_time_ticks_at,
)
from mediastudio.video_editor import effects as entrance_effects
from mediastudio.video_editor.framing import apply_subject_placement
from mediastudio.video_editor.jobs import VideoJob
from mediastudio.video_editor.native_engine import NativeVideoEngineError
from mediastudio.video_editor.project_v2 import TIMEBASE
from mediastudio.video_editor.renderer import VideoRenderError, _escape_filter_value, _font_file
from mediastudio.video_editor.template_keyframes import interpolate_keyframes, keyframe_expression


logger = logging.getLogger("mediastudio.video_editor.composition")
INTERNAL_AUDIO_RATE = 48_000
DESIGN_WIDTH = 1080
DESIGN_HEIGHT = 1920


def _seconds(ticks: int) -> str:
    value = (Decimal(ticks) / Decimal(TIMEBASE)).quantize(Decimal("0.000000001"), rounding=ROUND_HALF_UP)
    return format(value, ".9f")


def _samples(ticks: int, sample_rate: int = INTERNAL_AUDIO_RATE) -> int:
    return int((Decimal(ticks * sample_rate) / Decimal(TIMEBASE)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _canvas_font_size(font_size: int, width: int, height: int) -> int:
    """Scale design-space text for portrait render and preview canvases.

    Text sizes are authored on a 1080x1920 design canvas. Scale by the smaller
    axis so a low-resolution preview, or a portrait template with a different
    aspect ratio, displays at the same relative size when compared with export.
    Keep square and landscape legacy/unit canvases in their authored pixel space.
    """
    if width <= 0 or height <= 0 or width >= height:
        return max(1, int(round(font_size)))
    scale = min(width / DESIGN_WIDTH, height / DESIGN_HEIGHT)
    return max(1, int(round(font_size * scale)))


def _quote_filter_path(path: str | Path) -> str:
    return _escape_filter_value(str(path))


def _ffmpeg_expression(value: str) -> str:
    """Escape expression punctuation for FFmpeg filter option values."""
    return value.replace("\\", "\\\\").replace(":", "\\:").replace(",", "\\,")


def _frame_attributes(clip: CompositionClip, frame_ticks: int) -> dict[str, Any]:
    """Resolve animated values for one preview frame with the export interpolator."""
    attributes = dict(clip.attributes)
    keyframes = attributes.get("keyframes", [])
    local_ticks = max(0, frame_ticks - clip.timeline_start_ticks)
    for prop in ("positionX", "positionY", "scale", "rotation", "opacity"):
        value = interpolate_keyframes(keyframes, prop, local_ticks)
        if value is not None:
            attributes[prop] = value
    # The single-frame preview is rendered as a static frame after resolution.
    attributes["keyframes"] = []
    return attributes


def _clip_file(clip: CompositionClip, media_store: Any) -> Path:
    if clip.media_id is None:
        reference = clip.attributes.get("templateAssetReference")
        template_id = clip.attributes.get("templateAssetId")
        template_version = clip.attributes.get("templateAssetDefinitionVersion")
        if not all(isinstance(value, str) and value for value in (reference, template_id, template_version)):
            raise VideoRenderError(f"Clip {clip.clip_id} không có media hoặc asset template hợp lệ.")
        from mediastudio.video_editor.media_selection import resolve_template_asset
        try:
            return resolve_template_asset(template_id, template_version, reference)
        except (OSError, ValueError) as error:
            raise VideoRenderError(f"Không tìm thấy template asset cho clip {clip.clip_id}: {error}") from error
    try:
        source_path = Path(media_store.get_path(clip.media_id))
        if clip.attributes.get("removeBackground") is True:
            if clip.media_kind != "image":
                raise VideoRenderError(f"Clip {clip.clip_id} yêu cầu tách nền nhưng không phải ảnh.")
            from mediastudio.video_editor.cutout import (
                BackgroundRemovalError, ensure_background_removed_image,
            )
            crop_transparent_bounds = clip.attributes.get("trimTransparentBounds") is True
            cutout_path = Path(media_store.get_cutout_path(clip.media_id))
            if crop_transparent_bounds:
                cutout_path = cutout_path.with_name(f"{cutout_path.stem}_trimmed-v1.png")
            model_home = Path(media_store.root).parent / "models" / "rembg"
            try:
                return ensure_background_removed_image(
                    source_path, cutout_path, model_home,
                    crop_transparent_bounds=crop_transparent_bounds,
                )
            except BackgroundRemovalError as error:
                raise VideoRenderError(str(error)) from error
        return source_path
    except KeyError as error:
        raise VideoRenderError(f"Không tìm thấy tệp media {clip.media_id} của clip {clip.clip_id}.") from error


_FFMPEG_MAJOR: dict[str, int] = {}


def _ffmpeg_major(ffmpeg_path: str) -> int:
    if ffmpeg_path not in _FFMPEG_MAJOR:
        major = 0
        try:
            out = subprocess.run([ffmpeg_path, "-hide_banner", "-version"], capture_output=True,
                                 text=True, timeout=10).stdout
            token = out.split()[2] if out else ""
            digits = "".join(ch for ch in token.lstrip("n").split(".")[0] if ch.isdigit())
            major = int(digits) if digits else 0
        except Exception:
            major = 0
        _FFMPEG_MAJOR[ffmpeg_path] = major
    return _FFMPEG_MAJOR[ffmpeg_path]


def _filter_script_option(ffmpeg_path: str, script_path: Path) -> list[str]:
    # FFmpeg 7+ reads any option value from a file with the "-/" prefix;
    # older builds use -filter_complex_script. Unknown/dev builds: assume new.
    major = _ffmpeg_major(ffmpeg_path)
    if 0 < major < 7:
        return ["-filter_complex_script", str(script_path)]
    return ["-/filter_complex", str(script_path)]


def build_composition_command(
    graph: CompositionGraph,
    media_store: Any,
    ffmpeg_path: str,
    output_path: Path,
    temporary_directory: Path,
    quality: str,
    *,
    frame_ticks: int | None = None,
    include_audio: bool = True,
) -> tuple[list[str], bool]:
    """Compile one validated graph to an FFmpeg native filter graph.

    Export and single-frame preview share layer ordering, source-time mapping,
    alpha, fit, transform, effect and text filter builders. Preview narrows the
    graph to clips active at one exact output frame.
    """
    if not ffmpeg_path:
        raise VideoRenderError("Không tìm thấy FFmpeg để dựng composition.")
    if quality not in {"draft", "standard", "high"}:
        raise VideoRenderError("Preset chất lượng kết xuất không hợp lệ.")
    is_preview = frame_ticks is not None
    if is_preview:
        frame_index = graph.frame_index_at(frame_ticks)
        frame_ticks = graph.frame_start_ticks(frame_index)
        if frame_ticks >= graph.duration_ticks:
            raise CompositionGraphError("Timestamp preview nằm ngoài duration của composition.")
        ticks_per_frame = graph.timebase * graph.frame_rate_denominator // graph.frame_rate_numerator
        frame_duration_ticks = max(1, ticks_per_frame)
        total_ticks = frame_duration_ticks
    else:
        if graph.duration_ticks <= 0:
            raise CompositionGraphError("Composition chưa có nội dung active để kết xuất.")
        total_ticks = graph.duration_ticks

    active_visual: list[tuple[Any, CompositionClip]] = []
    active_text: list[tuple[Any, CompositionClip]] = []
    active_audio: list[tuple[Any, CompositionClip, int, int, float, int, int]] = []
    preview_visual_ticks = frame_ticks
    legacy_tail_clip_id: str | None = None
    if graph.duration_policy == "legacy-hold-last-visual-through-audio-end" and graph.visual_duration_ticks > 0:
        visual_clips = [clip for track in graph.tracks if track.kind == "visual"
                        for clip in track.clips if clip.enabled]
        if visual_clips:
            last_visual = max(visual_clips, key=lambda clip: (clip.end_ticks, clip.timeline_start_ticks, clip.clip_id))
            legacy_tail_clip_id = last_visual.clip_id
            if is_preview and frame_ticks >= graph.visual_duration_ticks:
                frame_denominator = graph.timebase * graph.frame_rate_denominator
                end_frame_exclusive = (graph.visual_duration_ticks * graph.frame_rate_numerator +
                                       frame_denominator - 1) // frame_denominator
                last_visual_frame = max(0, end_frame_exclusive - 1)
                preview_visual_ticks = graph.frame_start_ticks(last_visual_frame)
                preview_visual_ticks = max(last_visual.timeline_start_ticks, preview_visual_ticks)
    any_audio_solo = any(track.kind == "audio" and track.solo and not track.muted for track in graph.tracks)
    for track in graph.tracks:
        for clip in track.clips:
            if not clip.enabled:
                continue
            if track.kind == "visual":
                legacy_hold = (is_preview and frame_ticks is not None and
                               frame_ticks >= graph.visual_duration_ticks and
                               clip.clip_id == legacy_tail_clip_id)
                if is_preview and not legacy_hold and not (clip.timeline_start_ticks <= frame_ticks < clip.end_ticks):
                    continue
                active_visual.append((track, clip))
                if include_audio and clip.media_has_audio and clip.attributes.get("audioVolume", 1.0) > 0 \
                        and not any_audio_solo:
                    source_at = clip.source_start_ticks
                    if is_preview:
                        source_at += frame_ticks - clip.timeline_start_ticks
                    active_audio.append((track, clip, clip.timeline_start_ticks, source_at,
                                         float(clip.attributes["audioVolume"]), 0, 0))
            elif track.kind == "text":
                if is_preview and not (clip.timeline_start_ticks <= frame_ticks < clip.end_ticks):
                    continue
                active_text.append((track, clip))
            elif track.kind == "audio" and include_audio:
                volume = float(clip.attributes.get("volume", 1.0))
                if volume <= 0:
                    continue
                if is_preview:
                    continue
                active_audio.append((track, clip, clip.timeline_start_ticks, clip.source_start_ticks,
                                     volume, int(clip.attributes.get("fadeInMs", 0)),
                                     int(clip.attributes.get("fadeOutMs", 0))))

    if is_preview:
        active_audio.clear()
        total_ticks = graph.timebase * graph.frame_rate_denominator // graph.frame_rate_numerator
    else:
        # Content that is muted or hidden must not lengthen the output.
        participating_ends = [clip.end_ticks for track, clip in active_visual]
        participating_ends.extend(clip.end_ticks for track, clip in active_text)
        participating_ends.extend(start + clip.duration_ticks for track, clip, start, *_ in active_audio)
        total_ticks = max(participating_ends, default=0)
        if total_ticks <= 0:
            raise CompositionGraphError("Composition chưa có nội dung active để kết xuất.")

    text_capable = _ffmpeg_has_drawtext(ffmpeg_path)
    if active_text and not text_capable:
        raise CompositionGraphError("Bản FFmpeg hiện tại không có drawtext để dựng text layer.")
    text_assets: dict[str, Path] = {}
    for _, clip in active_text:
        font_path = _font_file(str(clip.attributes["fontFamily"]))
        if font_path is None:
            raise CompositionGraphError(
                f"Font '{clip.attributes['fontFamily']}' của text clip {clip.clip_id} không có file font tương ứng."
            )
        text_assets[clip.clip_id] = Path(font_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_directory.mkdir(parents=True, exist_ok=True)
    width, height, rate = graph.width, graph.height, graph.fps
    total_seconds = _seconds(total_ticks)
    if is_preview:
        color_duration = _seconds(max(1, total_ticks))
    else:
        color_duration = total_seconds
    command = [ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y", "-filter_complex_threads", "1",
               "-filter_threads", "1", "-threads", "1",
               "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r={rate}:d={color_duration}"]
    input_index: dict[str, int] = {}
    input_paths: dict[str, Path] = {}
    media_clips: dict[str, CompositionClip] = {}
    for _, clip in active_visual:
        if clip.clip_id not in media_clips:
            media_clips[clip.clip_id] = clip
    for _, clip, *_ in active_audio:
        if clip.clip_id not in media_clips:
            media_clips[clip.clip_id] = clip
    for clip_id, clip in media_clips.items():
        path = _clip_file(clip, media_store)
        input_paths[clip_id] = path
        if clip.media_kind == "image" and clip.kind != "audio":
            command.extend(["-loop", "1", "-framerate", rate, "-i", str(path)])
        else:
            command.extend(["-i", str(path)])
        input_index[clip_id] = len(input_index) + 1

    filters: list[str] = [
        f"[0:v]settb=AVTB,setpts=PTS-STARTPTS,format=rgba[canvas0]"
    ]
    current_canvas = "canvas0"
    operation_index = 0
    # Track order is the V2 contract: ascending values render from back to front.
    layer_ops: list[tuple[int, int, str, Any, CompositionClip]] = []
    for track, clip in active_visual:
        layer_ops.append((track.layer_order, clip.timeline_start_ticks, "visual", track, clip))
    for track, clip in active_text:
        layer_ops.append((track.layer_order, clip.timeline_start_ticks, "text", track, clip))
    layer_ops.sort(key=lambda item: (item[0], item[1], item[4].clip_id, item[2]))

    for layer_order, _, kind, track, clip in layer_ops:
        if kind == "visual":
            index = input_index[clip.clip_id]
            source_ticks = clip.source_start_ticks
            if is_preview:
                active_visual_ticks = preview_visual_ticks if clip.clip_id == legacy_tail_clip_id else frame_ticks
                source_ticks += active_visual_ticks - clip.timeline_start_ticks
            attributes = _frame_attributes(clip, int(frame_ticks)) if is_preview else clip.attributes
            attributes = apply_subject_placement(attributes, input_paths[clip.clip_id], (width, height))
            entrance = (entrance_effects.get_entrance_effect(attributes["entranceEffect"])
                      if attributes.get("entranceEffect") else None)
            if entrance is not None and is_preview:
                # A single frame: fold the effect's state at this moment into
                # static values, exactly what the export expression evaluates to.
                local_seconds = max(0, int(frame_ticks) - clip.timeline_start_ticks) / graph.timebase
                attributes = entrance_effects.apply_state(
                    attributes, entrance_effects.state_at(entrance, local_seconds))
                entrance = None
            chain = "setpts=PTS-STARTPTS"
            if clip.media_kind == "video":
                chain += f",trim=start={_seconds(source_ticks)}"
                if not is_preview:
                    chain += f":duration={_seconds(clip.duration_ticks)}"
            elif not is_preview:
                chain += f",trim=duration={_seconds(clip.duration_ticks)}"
            chain += ",setpts=PTS-STARTPTS"
            if is_preview:
                chain += ",trim=end_frame=1"
            chain += f",fps=fps={rate}:round=near,scale={width}:{height}:force_original_aspect_ratio="
            chain += "increase" if attributes["fitMode"] == "cover" else "decrease"
            if attributes["fitMode"] == "cover":
                chain += f",crop={width}:{height}"
            chain += ",setsar=1,format=rgba"
            start_seconds = _seconds(clip.timeline_start_ticks)
            scale_expression = None if is_preview else keyframe_expression(
                attributes.get("keyframes", []), "scale", "t")
            scale = float(attributes["scale"])
            if scale_expression is None and entrance is not None and entrance_effects.animates_scale(entrance):
                # Local stream time: this input was reset to PTS zero above.
                scale_expression = f"{scale:.9f}*{entrance_effects.scale_expression(entrance, 't')}"
            if scale_expression is not None:
                expr = _ffmpeg_expression(scale_expression)
                chain += f",scale=w='max(1,iw*({expr}))':h='max(1,ih*({expr}))':eval=frame"
            elif abs(scale - 1.0) > 1e-9:
                chain += f",scale=w='max(1,iw*{scale:.9f})':h='max(1,ih*{scale:.9f})'"
            rotation_expression = None if is_preview else keyframe_expression(
                attributes.get("keyframes", []), "rotation", "t")
            rotation = float(attributes["rotation"])
            if rotation_expression is not None:
                expr = _ffmpeg_expression(rotation_expression)
                chain += f",rotate=angle='({expr})*PI/180':ow=rotw(iw):oh=roth(ih):c=black@0"
            elif abs(rotation) > 1e-9:
                chain += f",rotate={rotation * math.pi / 180.0:.12f}:ow=rotw(iw):oh=roth(ih):c=black@0"
            effect = attributes["effect"]
            effects = {
                "warm": "colorbalance=rs=0.08:gs=0.02:bs=-0.08",
                "mono": "hue=s=0",
                "vivid": "eq=contrast=1.08:saturation=1.18",
            }
            if effect in effects:
                chain += "," + effects[effect]
            # Export inputs are decoded from source time, then trimmed and reset
            # to PTS zero. Move each resulting stream onto its absolute timeline
            # position before overlaying it onto the shared composition canvas.
            # A single-frame preview intentionally stays at PTS zero because its
            # canvas represents only the requested frame.
            if not is_preview and clip.timeline_start_ticks:
                chain += f",setpts=PTS+{_seconds(clip.timeline_start_ticks)}/TB"
            opacity_expression = None if is_preview else keyframe_expression(
                attributes.get("keyframes", []), "opacity", f"(T-{start_seconds})")
            if opacity_expression is None and entrance is not None and entrance_effects.animates_opacity(entrance):
                opacity_expression = (f"{float(attributes['opacity']):.9f}*"
                                      f"{entrance_effects.opacity_expression(entrance, f'(T-{start_seconds})')}")
            if opacity_expression is not None:
                expr = _ffmpeg_expression(opacity_expression)
                chain += (f",geq=r='r(X\\,Y)':g='g(X\\,Y)':b='b(X\\,Y)':"
                          f"a='alpha(X\\,Y)*({expr})'[fg{operation_index}]")
            else:
                chain += f",colorchannelmixer=aa={float(attributes['opacity']):.9f}[fg{operation_index}]"
            if not is_preview and clip.clip_id == legacy_tail_clip_id and total_ticks > clip.end_ticks:
                tail_ticks = total_ticks - clip.end_ticks
                chain = chain.replace(
                    f"[fg{operation_index}]",
                    f",tpad=stop_mode=clone:stop_duration={_seconds(tail_ticks)}[fg{operation_index}]",
                )
            filters.append(f"[{index}:v]{chain}")
            if is_preview:
                start_seconds = "0"
                end_seconds = color_duration
            else:
                start_seconds = _seconds(clip.timeline_start_ticks)
                end_seconds = _seconds(total_ticks if clip.clip_id == legacy_tail_clip_id
                                       else clip.end_ticks)
            x_expression = None if is_preview else keyframe_expression(
                attributes.get("keyframes", []), "positionX", f"(t-{start_seconds})")
            y_expression = None if is_preview else keyframe_expression(
                attributes.get("keyframes", []), "positionY", f"(t-{start_seconds})")
            if entrance is not None and x_expression is None:
                x_expression = entrance_effects.position_expression(
                    entrance, float(attributes["positionX"]), "x", f"(t-{start_seconds})")
            if entrance is not None and y_expression is None:
                y_expression = entrance_effects.position_expression(
                    entrance, float(attributes["positionY"]), "y", f"(t-{start_seconds})")
            x_value = _ffmpeg_expression(x_expression) if x_expression is not None \
                else f"{float(attributes['positionX']):.9f}"
            y_value = _ffmpeg_expression(y_expression) if y_expression is not None \
                else f"{float(attributes['positionY']):.9f}"
            x = f"(W-w)/2+W*({x_value})"
            y = f"(H-h)/2+H*({y_value})"
            next_canvas = f"canvas{operation_index + 1}"
            enable = "" if is_preview else \
                f":enable='gte(t,{start_seconds})*lt(t,{end_seconds})'"
            filters.append(
                f"[{current_canvas}][fg{operation_index}]overlay=x='{x}':y='{y}':"
                f"eof_action=pass:repeatlast=0:shortest=0:format=auto{enable},format=rgba[{next_canvas}]"
            )
            current_canvas = next_canvas
            operation_index += 1
        else:
            attributes = clip.attributes
            text_file = temporary_directory / f"text_{clip.clip_id}.txt"
            text_file.write_text(str(attributes["text"]), encoding="utf-8")
            escaped_text = _quote_filter_path(text_file)
            font_file = _quote_filter_path(text_assets[clip.clip_id])
            start_seconds = _seconds(clip.timeline_start_ticks)
            end_seconds = _seconds(clip.end_ticks)
            enable = "" if is_preview else f":enable='gte(t,{start_seconds})*lt(t,{end_seconds})'"
            color = str(attributes["color"]).lstrip("#")
            next_canvas = f"canvas{operation_index + 1}"
            filters.append(
                f"[{current_canvas}]drawtext=textfile='{escaped_text}':expansion=none:fontfile='{font_file}':"
                f"fontsize={_canvas_font_size(int(attributes['fontSize']), width, height)}:"
                f"fontcolor=0x{color}@{float(attributes['opacity']):.9f}:"
                f"x=(w-text_w)*{float(attributes['x']):.9f}:y=(h-text_h)*{float(attributes['y']):.9f}"
                f":box={1 if attributes.get('textBox') else 0}"
                f":boxcolor=0x{str(attributes.get('textBoxColor', '#000000')).lstrip('#')}@{float(attributes.get('textBoxOpacity', 0.0)):.9f}"
                f":boxborderw={int(attributes.get('textBoxBorderWidth', 0))}"
                + (f":bordercolor=0x{str(attributes['textBoxBorderColor']).lstrip('#')}"
                   if int(attributes.get("textBoxBorderWidth", 0)) > 0 else "")
                + (f":shadowcolor=0x{str(attributes['shadowColor']).lstrip('#')}"
                   f":shadowx={int(attributes.get('shadowX', 0))}:shadowy={int(attributes.get('shadowY', 0))}"
                   if attributes.get("shadowColor") else "")
                + f"{enable}[{next_canvas}]"
            )
            current_canvas = next_canvas
            operation_index += 1

    if is_preview:
        filters.append(f"[{current_canvas}]trim=end_frame=1,format=rgba[vout]")
    else:
        filters.append(f"[{current_canvas}]trim=duration={total_seconds},setpts=PTS-STARTPTS,fps=fps={rate},format=yuv420p[vout]")

    audio_labels: list[str] = []
    if include_audio and not is_preview and active_audio:
        audio_solo = any(track.kind == "audio" and track.solo and not track.muted for track in graph.tracks)
        for source_index, (track, clip, timeline_start, source_start, volume, fade_in_ms, fade_out_ms) in enumerate(active_audio):
            if track.kind == "visual" and audio_solo:
                continue
            input_idx = input_index[clip.clip_id]
            duration = clip.duration_ticks
            chain = f"asetpts=PTS-STARTPTS,atrim=start={_seconds(source_start)}:duration={_seconds(duration)}"
            chain += f",asetpts=PTS-STARTPTS,aresample={INTERNAL_AUDIO_RATE}:async=0"
            chain += ",aformat=sample_fmts=fltp:channel_layouts=stereo"
            chain += f",volume={volume:.9f}"
            fade_in_ticks = min(duration, max(0, fade_in_ms * 90))
            fade_out_ticks = min(duration, max(0, fade_out_ms * 90))
            if fade_in_ticks > 0:
                chain += f",afade=t=in:st=0:d={_seconds(fade_in_ticks)}"
            if fade_out_ticks > 0:
                fade_start = max(0, duration - fade_out_ticks)
                chain += f",afade=t=out:st={_seconds(fade_start)}:d={_seconds(fade_out_ticks)}"
            chain += f",adelay={_samples(timeline_start)}S:all=1,apad,atrim=duration={total_seconds}[a{source_index}]"
            filters.append(f"[{input_idx}:a]{chain}")
            audio_labels.append(f"[a{source_index}]")
        if audio_labels:
            # Keep the measured legacy linear gain law for the existing V1
            # compatibility subset. New multitrack projects use a direct sum
            # of per-clip gains; no limiter or loudness normalization is added.
            normalize = ("1" if graph.audio_mix_policy == "legacy-input-count-normalization" else "0")
            filters.append("".join(audio_labels) +
                           f"amix=inputs={len(audio_labels)}:duration=longest:dropout_transition=0:normalize={normalize},"
                           f"aresample=44100:async=0,aformat=sample_fmts=fltp:sample_rates=44100:"
                           f"channel_layouts=stereo,atrim=duration={total_seconds},asetpts=PTS-STARTPTS[aout]")

    graph_text = ";".join(filters)
    if len(graph_text) > 6000:
        # Windows limits a command line to ~32k characters; long templates
        # (e.g. 40 frames + cut-out bridges) pass the filter graph as a file.
        script_path = temporary_directory / "filter_graph.txt"
        script_path.write_text(graph_text, encoding="utf-8")
        command.extend([*_filter_script_option(ffmpeg_path, script_path), "-map", "[vout]"])
    else:
        command.extend(["-filter_complex", graph_text, "-map", "[vout]"])
    if audio_labels:
        command.extend(["-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2"])
    else:
        command.append("-an")
    if is_preview:
        command.extend(["-frames:v", "1", "-c:v", "png", "-pix_fmt", "rgba", "-f", "image2", str(output_path)])
    else:
        crf, preset = {"draft": (28, "veryfast"), "standard": (21, "medium"), "high": (17, "slow")}[quality]
        command.extend(["-r", rate, "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                        "-pix_fmt", "yuv420p", "-t", total_seconds, "-movflags", "+faststart",
                        "-progress", "pipe:1", "-nostats", str(output_path)])
    return command, bool(audio_labels)


def _ffmpeg_has_drawtext(ffmpeg_path: str) -> bool:
    try:
        result = subprocess.run([ffmpeg_path, "-hide_banner", "-filters"], capture_output=True,
                                text=True, timeout=8, check=False)
        return result.returncode == 0 and "drawtext" in result.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def _native_preview_layers(graph: CompositionGraph, media_store: Any, native_engine: Any,
                          frame_ticks: int) -> list[dict[str, Any]]:
    visual_ticks = frame_ticks
    legacy_tail_clip_id: str | None = None
    if graph.duration_policy == "legacy-hold-last-visual-through-audio-end" \
            and frame_ticks >= graph.visual_duration_ticks > 0:
        visual_clips = [clip for track in graph.tracks if track.kind == "visual"
                        for clip in track.clips if clip.enabled]
        if visual_clips:
            last_visual = max(visual_clips, key=lambda clip: (clip.end_ticks, clip.timeline_start_ticks, clip.clip_id))
            frame_denominator = graph.timebase * graph.frame_rate_denominator
            end_frame_exclusive = (graph.visual_duration_ticks * graph.frame_rate_numerator +
                                   frame_denominator - 1) // frame_denominator
            last_visual_frame = max(0, end_frame_exclusive - 1)
            visual_ticks = max(last_visual.timeline_start_ticks, graph.frame_start_ticks(last_visual_frame))
            legacy_tail_clip_id = last_visual.clip_id

    layers: list[dict[str, Any]] = []
    for track in graph.tracks:
        if track.kind != "visual":
            continue
        for clip in track.clips:
            if not clip.enabled:
                continue
            if clip.clip_id != legacy_tail_clip_id and not clip_is_active(clip, frame_ticks):
                continue
            if clip.attributes.get("keyframes"):
                raise CompositionGraphError("Native preview does not evaluate animated visual keyframes.")
            if clip.attributes["effect"] != "none":
                raise CompositionGraphError("Native preview hiện chỉ xác minh được visual không có effect.")
            path = _clip_file(clip, media_store)
            placed = apply_subject_placement(clip.attributes, path, (graph.width, graph.height))
            if placed.get("entranceEffect"):
                effect = entrance_effects.get_entrance_effect(placed["entranceEffect"])
                local_seconds = max(0, visual_ticks - clip.timeline_start_ticks) / graph.timebase
                placed = entrance_effects.apply_state(placed, entrance_effects.state_at(effect, local_seconds))
            if clip.media_kind == "image":
                with Image.open(path) as source_image:
                    image = source_image.convert("RGBA")
                    image.thumbnail((graph.width, graph.height), Image.Resampling.LANCZOS)
                    rgba = image.tobytes()
                    image_width, image_height = image.size
            else:
                source_ticks = source_time_ticks_at(clip, visual_ticks)
                if not getattr(native_engine, "tick_decoder_available", False):
                    raise NativeVideoEngineError("Native preview cần decoder theo timestamp ticks chính xác.")
                image_width, image_height, rgba = native_engine.decode_frame_ticks(
                    path, source_ticks, graph.timebase, graph.width, graph.height,
                )
            layers.append({
                "width": image_width,
                "height": image_height,
                "rgba": rgba,
                "fitMode": placed["fitMode"],
                "positionX": placed["positionX"],
                "positionY": placed["positionY"],
                "scale": placed["scale"],
                "rotation": clip.attributes["rotation"],
                "opacity": placed["opacity"],
                "effect": clip.attributes["effect"],
            })
    return layers


def render_native_preview_frame_png(graph: CompositionGraph, media_store: Any, native_engine: Any,
                                    timeline_ticks: int) -> bytes:
    frame_index = graph.frame_index_at(timeline_ticks)
    frame_ticks = graph.frame_start_ticks(frame_index)
    if frame_ticks >= graph.duration_ticks:
        raise CompositionGraphError("Timestamp preview nằm ngoài duration của composition.")
    if any(track.kind == "text" and clip.enabled and clip_is_active(clip, frame_ticks)
           for track in graph.tracks for clip in track.clips):
        raise CompositionGraphError("Native preview chưa dựng text; cần dùng graph renderer FFmpeg.")
    if sum(1 for track in graph.tracks if track.kind == "visual"
           for clip in track.clips if clip.enabled and clip_is_active(clip, frame_ticks)) > 32:
        raise CompositionGraphError("Native preview hỗ trợ tối đa 32 visual layer đang hoạt động.")
    layers = _native_preview_layers(graph, media_store, native_engine, frame_ticks)
    bgra = native_engine.compose_preview_bgra(graph.width, graph.height, layers)
    image = Image.frombytes("RGBA", (graph.width, graph.height), bgra, "raw", "BGRA")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def render_preview_frame(graph: CompositionGraph, media_store: Any, ffmpeg_path: str,
                         timeline_ticks: int, native_engine: Any | None = None,
                         timeout_seconds: int = 60) -> tuple[bytes, str]:
    frame_index = graph.frame_index_at(timeline_ticks)
    frame_ticks = graph.frame_start_ticks(frame_index)
    if frame_ticks >= graph.duration_ticks:
        raise CompositionGraphError("Timestamp preview nằm ngoài duration của composition.")
    if native_engine is not None and getattr(native_engine, "composition_preview_available", False):
        try:
            frame = render_native_preview_frame_png(graph, media_store, native_engine, frame_ticks)
            return frame, "native-cpp"
        except (NativeVideoEngineError, CompositionGraphError, OSError, ValueError) as error:
            logger.info("Native composition preview fallback frame=%s reason=%s", frame_index, error)
    with tempfile.TemporaryDirectory(prefix="video_composition_preview_") as temporary:
        temp_dir = Path(temporary)
        output = temp_dir / "preview.png"
        command, _ = build_composition_command(
            graph, media_store, ffmpeg_path, output, temp_dir, "draft",
            frame_ticks=frame_ticks, include_audio=False,
        )
        process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=timeout_seconds, check=False)
        if process.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            detail = (process.stderr or process.stdout).strip()[-1200:]
            logger.error("Composition preview failed frame=%s: %s", frame_index, detail)
            raise VideoRenderError(f"FFmpeg không dựng được preview frame: {detail or 'lỗi không rõ'}")
        return output.read_bytes(), "ffmpeg-filtergraph"


def render_preview_frame_png(graph: CompositionGraph, media_store: Any, ffmpeg_path: str,
                             timeline_ticks: int, native_engine: Any | None = None) -> bytes:
    return render_preview_frame(graph, media_store, ffmpeg_path, timeline_ticks, native_engine)[0]


def render_composition_project(job: VideoJob, graph: CompositionGraph, media_store: Any,
                               ffmpeg_path: str, output_directory: Path, quality: str,
                               native_engine: Any | None = None, *, defer_success: bool = False) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    final_path = output_directory / f"{graph.project_id}_{job.job_id}.mp4"
    partial_path = final_path.with_suffix(".partial.mp4")
    temporary_directory = Path(tempfile.mkdtemp(prefix=f"composition_{job.job_id}_", dir=output_directory))
    try:
        command, has_audio = build_composition_command(
            graph, media_store, ffmpeg_path, partial_path, temporary_directory, quality
        )
        job.update(state="processing", progress=1, stage="Đang dựng composition V2 bằng FFmpeg")
        started = time.perf_counter()
        recent_lines: list[str] = []
        if native_engine is not None and getattr(native_engine, "composition_runner_available", False):
            try:
                native_engine.render_ffmpeg_arguments(
                    ffmpeg_path, partial_path, command[1:], graph.duration_ticks / TIMEBASE, job,
                )
            except NativeVideoEngineError as error:
                if job.cancel_event.is_set():
                    job.update(state="cancelled", progress=0, stage="Đã hủy")
                    raise VideoRenderError("Tác vụ composition đã bị hủy.") from error
                raise VideoRenderError(f"Native engine composition thất bại: {error}") from error
            return_code = 0
        else:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding="utf-8", errors="replace", bufsize=1)
            assert process.stdout is not None
            try:
                for raw_line in process.stdout:
                    if job.cancel_event.is_set():
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        job.update(state="cancelled", progress=0, stage="Đã hủy")
                        raise VideoRenderError("Tác vụ composition đã bị hủy.")
                    line = raw_line.strip()
                    if not line:
                        continue
                    if line.startswith("out_time_ms="):
                        try:
                            elapsed = int(line.partition("=")[2])
                            total = graph.duration_ticks / TIMEBASE
                            job.update(progress=min(99, max(1, round(elapsed / (total * 1_000_000) * 100))),
                                       stage="Đang dựng video và trộn audio" if has_audio else "Đang dựng video nhiều lớp")
                        except (ValueError, ZeroDivisionError):
                            continue
                    elif "=" not in line or line.startswith("Error"):
                        recent_lines.append(line)
                        del recent_lines[:-12]
                return_code = process.wait()
            except Exception:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                raise
            finally:
                process.stdout.close()
        if job.cancel_event.is_set():
            job.update(state="cancelled", progress=0, stage="Đã hủy")
            raise VideoRenderError("Tác vụ composition đã bị hủy.")
        if return_code != 0 or not partial_path.is_file() or partial_path.stat().st_size == 0:
            detail = "\n".join(recent_lines[-8:])
            logger.error("Composition render job %s failed (%s): %s", job.job_id, return_code, detail)
            raise VideoRenderError(f"FFmpeg composition thất bại: {detail or 'không rõ nguyên nhân'}")
        partial_path.replace(final_path)
        logger.info("Composition job %s completed in %.2f seconds", job.job_id, time.perf_counter() - started)
        if defer_success:
            # Screen 06 validates the finalized container and fully decodes it
            # before publishing to the user-selected destination.
            job.update(state="processing", progress=99, stage="Đang kiểm tra và công bố file MP4", output_path=final_path)
        else:
            job.update(state="succeeded", progress=100, stage="Đã xuất composition V2", output_path=final_path)
    finally:
        partial_path.unlink(missing_ok=True)
        for path in temporary_directory.glob("*"):
            path.unlink(missing_ok=True)
        temporary_directory.rmdir()

