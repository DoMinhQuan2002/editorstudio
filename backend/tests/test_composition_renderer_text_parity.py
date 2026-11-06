from __future__ import annotations

import os
import json
import re
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from mediastudio.video_editor.composition import build_composition_graph
from mediastudio.video_editor.composition_renderer import (
    _canvas_font_size,
    build_composition_command,
    render_preview_frame,
    render_composition_project,
)
from mediastudio.video_editor.ffmpeg import FFmpegToolchain
from mediastudio.video_editor.jobs import VideoJob
from mediastudio.video_editor.project_v2 import TimelineClipV2, TimelineTrackV2, VideoProjectV2


def _text_graph(width: int, height: int):
    track_id = "a" * 32
    clip_id = "b" * 32
    project = VideoProjectV2(
        schema_version=2,
        project_id="c" * 32,
        template_id="text-parity-fixture",
        title="Text parity fixture",
        width=width,
        height=height,
        tracks=[TimelineTrackV2(
            track_id=track_id,
            kind="text",
            layer_order=1,
            display_name="Text",
            clips=[TimelineClipV2(
                clip_id=clip_id,
                track_id=track_id,
                clip_kind="text",
                timeline_start_ticks=0,
                duration_ticks=90_000,
                properties={
                    "text": "PARITY",
                    "x": 0.2,
                    "y": 0.2,
                    "fontSize": 80,
                    "color": "#FFFFFF",
                    "fontFamily": "Arial",
                    "opacity": 1.0,
                },
            )],
        )],
    )
    return build_composition_graph(project, lambda _asset_id: None)


def _font_size_from_command(graph, tmp_path: Path, *, preview: bool, ffmpeg_path: str) -> int:
    temp_dir = tmp_path / f"temp_{graph.width}x{graph.height}_{preview}"
    command, _ = build_composition_command(
        graph,
        media_store=None,
        ffmpeg_path=ffmpeg_path,
        output_path=tmp_path / ("preview.png" if preview else "export.mp4"),
        temporary_directory=temp_dir,
        quality="draft",
        frame_ticks=0 if preview else None,
        include_audio=False,
    )
    filter_graph = command[command.index("-filter_complex") + 1]
    match = re.search(r"fontsize=(\d+)", filter_graph)
    assert match is not None
    return int(match.group(1))


def _text_bounds(png_bytes: bytes) -> tuple[int, int]:
    from io import BytesIO

    image = Image.open(BytesIO(png_bytes)).convert("RGB")
    mask = image.convert("L").point(lambda value: 255 if value > 32 else 0)
    bounds = mask.getbbox()
    assert bounds is not None
    return bounds[2] - bounds[0], bounds[3] - bounds[1]


def test_preview_and_export_font_sizes_scale_to_the_same_display_size(tmp_path):
    toolchain = FFmpegToolchain()
    if not toolchain.ffmpeg or not toolchain.ffprobe:
        pytest.skip("FFmpeg/ffprobe are not installed")

    standard_export = _text_graph(1080, 1920)
    standard_preview = _text_graph(540, 960)
    assert _canvas_font_size(80, 540, 960) * 2 == _canvas_font_size(80, 1080, 1920)
    assert _font_size_from_command(standard_preview, tmp_path, preview=True, ffmpeg_path=toolchain.ffmpeg) == 40
    assert _font_size_from_command(standard_export, tmp_path, preview=False, ffmpeg_path=toolchain.ffmpeg) == 80

    preview_png, preview_renderer = render_preview_frame(
        standard_preview, None, toolchain.ffmpeg, 0, native_engine=None,
    )
    export_size = _canvas_font_size(80, standard_export.width, standard_export.height)
    export_png, export_renderer = render_preview_frame(
        standard_export, None, toolchain.ffmpeg, 0, native_engine=None,
    )
    assert preview_renderer == export_renderer == "ffmpeg-filtergraph"
    preview_bounds = _text_bounds(preview_png)
    export_bounds = _text_bounds(export_png)
    assert abs(export_bounds[0] - preview_bounds[0] * 2) <= 2
    assert abs(export_bounds[1] - preview_bounds[1] * 2) <= 2

    # When requested by the prompt verification run, retain comparison frames.
    artifact_dir = os.environ.get("AGENT_PROMPT_ARTIFACT_DIR")
    if artifact_dir:
        output = Path(artifact_dir)
        output.mkdir(parents=True, exist_ok=True)
        (output / "preview_540x960.png").write_bytes(preview_png)
        (output / "export_1080x1920.png").write_bytes(export_png)

    # The template canvas is 720x1556; preview dimensions must preserve its
    # aspect ratio, so text remains the same relative size after display scale.
    template_export = _text_graph(720, 1556)
    template_preview = _text_graph(444, 960)
    assert _canvas_font_size(80, 720, 1556) == 53
    assert _canvas_font_size(80, 444, 960) == 33
    preview_png, _ = render_preview_frame(template_preview, None, toolchain.ffmpeg, 0, native_engine=None)
    export_png, _ = render_preview_frame(template_export, None, toolchain.ffmpeg, 0, native_engine=None)
    preview_bounds = _text_bounds(preview_png)
    export_bounds = _text_bounds(export_png)
    scale_x = template_export.width / template_preview.width
    scale_y = template_export.height / template_preview.height
    # Compare normalized glyph dimensions: both canvases are portrait, but the
    # output proxy has a slightly different aspect ratio and fontsize rounds to
    # an integer pixel on each canvas.
    assert abs(export_bounds[0] / template_export.width - preview_bounds[0] / template_preview.width) <= 0.005
    assert abs(export_bounds[1] / template_export.height - preview_bounds[1] / template_preview.height) <= 0.005
    if artifact_dir:
        output = Path(artifact_dir)
        (output / "preview_444x960.png").write_bytes(preview_png)
        (output / "export_720x1556.png").write_bytes(export_png)


def test_720x1556_composition_exports_at_graph_dimensions_and_matches_preview(tmp_path):
    toolchain = FFmpegToolchain()
    if not toolchain.ffmpeg or not toolchain.ffprobe:
        pytest.skip("FFmpeg/ffprobe are not installed")
    if not toolchain.capabilities().get("h264Encoding"):
        pytest.skip("Local FFmpeg does not have an H.264 encoder")

    graph = _text_graph(720, 1556)
    preview_png, _ = render_preview_frame(graph, None, toolchain.ffmpeg, 9_000, native_engine=None)
    job = VideoJob(job_id="f" * 32, project_id=graph.project_id)
    render_composition_project(job, graph, None, toolchain.ffmpeg, tmp_path, "draft")
    assert job.state == "succeeded"
    assert job.output_path is not None

    probe_process = subprocess.run(
        [toolchain.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_type,width,height", "-of", "json", str(job.output_path)],
        capture_output=True, text=True, check=False,
    )
    assert probe_process.returncode == 0, probe_process.stderr
    probe = json.loads(probe_process.stdout)
    video = next(stream for stream in probe["streams"] if stream.get("codec_type") == "video")
    assert (video["width"], video["height"]) == (720, 1556)

    decoded = subprocess.run(
        [toolchain.ffmpeg, "-v", "error", "-i", str(job.output_path), "-ss", "0.1",
         "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True, check=False,
    )
    assert decoded.returncode == 0, decoded.stderr.decode("utf-8", errors="replace")
    preview_bounds = _text_bounds(preview_png)
    export_bounds = _text_bounds(decoded.stdout)
    assert all(abs(preview - exported) <= 3 for preview, exported in zip(preview_bounds, export_bounds))

    artifact_dir = os.environ.get("AGENT_PROMPT_ARTIFACT_DIR")
    if artifact_dir:
        output = Path(artifact_dir)
        output.mkdir(parents=True, exist_ok=True)
        (output / "fall_diary_preview_720x1556.png").write_bytes(preview_png)
        (output / "fall_diary_export_frame_720x1556.png").write_bytes(decoded.stdout)
        (output / "fall_diary_canvas_export.mp4").write_bytes(job.output_path.read_bytes())
        (output / "canvas_verification.json").write_text(json.dumps({
            "compositionGraph": {"width": graph.width, "height": graph.height},
            "ffprobe": {"codecType": video["codec_type"], "width": video["width"],
                        "height": video["height"]},
            "previewTextBoundsPx": preview_bounds,
            "exportTextBoundsPx": export_bounds,
            "maximumBoundsDeltaPx": max(abs(preview - exported)
                                         for preview, exported in zip(preview_bounds, export_bounds)),
        }, indent=2), encoding="utf-8")
