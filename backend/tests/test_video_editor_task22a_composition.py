from __future__ import annotations

from array import array
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from io import BytesIO
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from uuid import uuid4

from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mediastudio.video_editor.composition import (
    CompositionGraphError, build_composition_graph, clip_is_active, source_time_ticks_at,
)
from mediastudio.video_editor.composition_renderer import (
    build_composition_command, render_composition_project, render_preview_frame,
    render_preview_frame_png,
)
from mediastudio.video_editor.ffmpeg import FFmpegToolchain
from mediastudio.video_editor.jobs import VideoJob
from mediastudio.video_editor.api import install_video_editor_api
from mediastudio.video_editor.project_v2 import (
    TIMEBASE, TimelineClipV2, TimelineTrackV2, TrackStateV2, VideoProjectV2, project_api_payload,
)


@dataclass(frozen=True)
class Media:
    asset_id: str
    kind: str
    duration_ms: int | None
    audio_codec: str | None = None


class FixtureMediaStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.media: dict[str, Media] = {}
        self.paths: dict[str, Path] = {}

    def add(self, name: str, kind: str, path: Path, duration_ms: int | None,
            audio_codec: str | None = None) -> Media:
        asset_id = uuid4().hex
        item = Media(asset_id, kind, duration_ms, audio_codec)
        self.media[asset_id] = item
        self.paths[asset_id] = path
        return item

    def get_metadata(self, asset_id: str) -> Media:
        if asset_id not in self.media:
            raise KeyError(asset_id)
        return self.media[asset_id]

    def get_path(self, asset_id: str) -> Path:
        if asset_id not in self.paths:
            raise KeyError(asset_id)
        return self.paths[asset_id]


class Task22ACompositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ffmpeg = FFmpegToolchain()
        if not cls.ffmpeg.ffmpeg or not cls.ffmpeg.ffprobe:
            raise unittest.SkipTest("FFmpeg/ffprobe are not installed")

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="task22a_")
        self.root = Path(self._temporary.name)
        self.artifact_root = os.environ.get("TASK22A_ARTIFACT_DIR")
        if self.artifact_root:
            self.root = Path(self.artifact_root).resolve()
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / "runtime").mkdir(exist_ok=True)
        self.media_store = FixtureMediaStore(self.root)
        self.assets = self._make_assets()
        self.project = self._project()
        self.project_before = self.project.model_dump(mode="json", by_alias=True)
        self.graph = build_composition_graph(self.project, self.media_store.get_metadata)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _ffmpeg(self, *arguments: str) -> None:
        process = subprocess.run([self.ffmpeg.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                  *arguments], capture_output=True, text=True, check=False, timeout=30)
        self.assertEqual(0, process.returncode, process.stderr)

    def _make_assets(self) -> dict[str, Media]:
        output = self.root / "fixture_media"
        output.mkdir(exist_ok=True)
        red = output / "base_red.mp4"
        self._ffmpeg("-f", "lavfi", "-i", "color=c=red:s=64x64:r=30:d=1",
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", str(red))
        blue = output / "overlay_blue.mp4"
        self._ffmpeg("-f", "lavfi", "-i", "color=c=blue:s=64x64:r=30:d=1",
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", str(blue))
        overlay = output / "overlay_alpha.png"
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        for y in range(64):
            for x in range(22, 43):
                image.putpixel((x, y), (0, 0, 255, 128))
            for x in range(43, 64):
                image.putpixel((x, y), (0, 0, 255, 255))
        image.save(overlay)
        tone_a = output / "tone_440_mono_48k.wav"
        self._ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                     "-ac", "1", str(tone_a))
        tone_b = output / "tone_880_stereo_44k.wav"
        self._ffmpeg("-f", "lavfi", "-i", "sine=frequency=880:sample_rate=44100:duration=1",
                     "-ac", "2", "-ar", "44100", str(tone_b))
        tone_long = output / "tone_440_stereo_48k_2s.wav"
        self._ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
                     "-ac", "2", str(tone_long))
        return {
            "video": self.media_store.add("base_red.mp4", "video", red, 1000),
            "video_overlay": self.media_store.add("overlay_blue.mp4", "video", blue, 1000),
            "image": self.media_store.add("overlay_alpha.png", "image", overlay, None),
            "tone_a": self.media_store.add("tone_440_mono_48k.wav", "audio", tone_a, 1000, "pcm_s16le"),
            "tone_b": self.media_store.add("tone_880_stereo_44k.wav", "audio", tone_b, 1000, "pcm_s16le"),
            "tone_long": self.media_store.add("tone_440_stereo_48k_2s.wav", "audio", tone_long, 2000,
                                               "pcm_s16le"),
        }

    @staticmethod
    def _visual_properties(name: str, **updates: object) -> dict[str, object]:
        result: dict[str, object] = {
            "name": name, "fitMode": "cover", "positionX": 0.0, "positionY": 0.0,
            "scale": 1.0, "rotation": 0.0, "effect": "none", "opacity": 1.0,
            "audioVolume": 1.0, "transition": "cut", "transitionDurationMs": 300,
        }
        result.update(updates)
        return result

    @staticmethod
    def _audio_properties(media_id: str, volume: float = 0.5, fade_in: int = 0,
                          fade_out: int = 0) -> dict[str, object]:
        return {"mediaId": media_id, "volume": volume, "fadeInMs": fade_in, "fadeOutMs": fade_out}

    def _project(self) -> VideoProjectV2:
        visual_base_id, visual_overlay_id, text_id, audio_a_id, audio_b_id = (
            uuid4().hex for _ in range(5)
        )
        tracks = [
            TimelineTrackV2(track_id=visual_base_id, kind="visual", layer_order=0,
                            display_name="Base", clips=[TimelineClipV2(
                                clip_id=uuid4().hex, track_id=visual_base_id, clip_kind="video",
                                timeline_start_ticks=0, source_start_ticks=0, duration_ticks=90_000,
                                media_id=self.assets["video"].asset_id,
                                properties=self._visual_properties("red base"),
                            )]),
            TimelineTrackV2(track_id=visual_overlay_id, kind="visual", layer_order=1,
                            display_name="Image overlay", clips=[TimelineClipV2(
                                clip_id=uuid4().hex, track_id=visual_overlay_id, clip_kind="image",
                                timeline_start_ticks=22_500, source_start_ticks=0, duration_ticks=45_000,
                                media_id=self.assets["image"].asset_id,
                                properties=self._visual_properties("alpha overlay", opacity=0.8),
                            )]),
            TimelineTrackV2(track_id=text_id, kind="text", layer_order=2,
                            display_name="Text", clips=[TimelineClipV2(
                                clip_id=uuid4().hex, track_id=text_id, clip_kind="text",
                                timeline_start_ticks=27_000, source_start_ticks=0, duration_ticks=36_000,
                                media_id=None,
                                properties={"text": "TEST", "x": 0.5, "y": 0.5, "fontSize": 12,
                                            "color": "#FFFFFF", "fontFamily": "Arial", "opacity": 1.0},
                            )]),
            TimelineTrackV2(track_id=audio_a_id, kind="audio", layer_order=3,
                            display_name="Audio A", clips=[TimelineClipV2(
                                clip_id=uuid4().hex, track_id=audio_a_id, clip_kind="audio",
                                timeline_start_ticks=0, source_start_ticks=0, duration_ticks=63_000,
                                media_id=self.assets["tone_a"].asset_id,
                                properties=self._audio_properties(self.assets["tone_a"].asset_id, 0.45),
                            )]),
            TimelineTrackV2(track_id=audio_b_id, kind="audio", layer_order=4,
                            display_name="Audio B", clips=[TimelineClipV2(
                                clip_id=uuid4().hex, track_id=audio_b_id, clip_kind="audio",
                                timeline_start_ticks=22_500, source_start_ticks=9_000, duration_ticks=45_000,
                                media_id=self.assets["tone_b"].asset_id,
                                properties=self._audio_properties(self.assets["tone_b"].asset_id, 0.4,
                                                                  fade_in=100, fade_out=100),
                            )]),
        ]
        return VideoProjectV2(schema_version=2, project_id=uuid4().hex, template_id="task22a-fixture",
                              title="Task 2.2A composition fixture", width=64, height=64,
                              frame_rate_numerator=30, frame_rate_denominator=1, tracks=tracks)

    def _simple_project(self, *, fps_num: int = 30, fps_den: int = 1,
                        tracks: list[TimelineTrackV2] | None = None) -> VideoProjectV2:
        return VideoProjectV2(schema_version=2, project_id=uuid4().hex, template_id="task22a",
                              title="Fixture", width=64, height=64,
                              frame_rate_numerator=fps_num, frame_rate_denominator=fps_den,
                              tracks=tracks or [])

    def _one_visual_track(self, *, start: int = 0, source: int = 0, duration: int = 90_000,
                          media: Media | None = None, properties: dict[str, object] | None = None,
                          track_id: str | None = None) -> TimelineTrackV2:
        owner = track_id or uuid4().hex
        chosen = media or self.assets["video"]
        return TimelineTrackV2(track_id=owner, kind="visual", layer_order=0, display_name="Video",
                               clips=[TimelineClipV2(clip_id=uuid4().hex, track_id=owner,
                                                    clip_kind="image" if chosen.kind == "image" else "video",
                                                    timeline_start_ticks=start, source_start_ticks=source,
                                                    duration_ticks=duration, media_id=chosen.asset_id,
                                                    properties=properties or self._visual_properties("clip"))])

    def test_fixture_01_graph_is_deterministic_and_preserves_v2_ids_and_ticks(self) -> None:
        first = self.graph.to_dict()
        second = build_composition_graph(self.project, self.media_store.get_metadata).to_dict()
        self.assertEqual(first, second)
        self.assertEqual(self.project.project_id, first["projectId"])
        self.assertEqual("ascending-back-to-front", first["layerOrderContract"])
        self.assertEqual(self.project_before, self.project.model_dump(mode="json", by_alias=True))
        self.assertEqual(90_000, self.graph.duration_ticks)

    def test_fixture_02_two_visual_tracks_are_ordered_and_overlap_is_retained(self) -> None:
        visuals = [track for track in self.graph.tracks if track.kind == "visual"]
        self.assertEqual([0, 1], [track.layer_order for track in visuals])
        self.assertLess(visuals[0].clips[0].timeline_start_ticks, visuals[1].clips[0].end_ticks)

    def test_fixture_02b_video_overlay_renders_only_during_its_active_range(self) -> None:
        base = self._one_visual_track(duration=90_000)
        overlay = self._one_visual_track(start=18_000, duration=45_000,
                                         media=self.assets["video_overlay"])
        overlay.layer_order = 1
        graph = build_composition_graph(self._simple_project(tracks=[base, overlay]),
                                        self.media_store.get_metadata)
        active = render_preview_frame_png(graph, self.media_store, self.ffmpeg.ffmpeg, 36_000)
        inactive = render_preview_frame_png(graph, self.media_store, self.ffmpeg.ffmpeg, 72_000)
        with Image.open(BytesIO(active)) as image:
            self.assertGreater(image.convert("RGB").getpixel((32, 32))[2], 150)
        with Image.open(BytesIO(inactive)) as image:
            red, green, blue = image.convert("RGB").getpixel((32, 32))
        self.assertGreater(red, 180)
        self.assertLess(green, 80)
        self.assertLess(blue, 80)
        export_dir = self.root / "video_overlay_export"
        export_dir.mkdir(exist_ok=True)
        job = VideoJob(job_id=uuid4().hex, project_id=graph.project_id)
        render_composition_project(job, graph, self.media_store, self.ffmpeg.ffmpeg, export_dir, "draft",
                                   self.ffmpeg.native_engine)
        self.assertEqual("succeeded", job.state, job.snapshot())
        assert job.output_path is not None
        for frame_index, expect_blue in ((12, True), (24, False)):
            frame_path = export_dir / f"frame_{frame_index}.png"
            process = subprocess.run([self.ffmpeg.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                      "-i", str(job.output_path), "-vf", f"select=eq(n\\,{frame_index})",
                                      "-frames:v", "1", str(frame_path)], capture_output=True,
                                     text=True, check=False, timeout=30)
            self.assertEqual(0, process.returncode, process.stderr)
            with Image.open(frame_path) as image:
                red, green, blue = image.convert("RGB").getpixel((32, 32))
            if expect_blue:
                self.assertGreater(blue, 150)
            else:
                self.assertGreater(red, 180)
                self.assertLess(blue, 80)

    def test_native_preview_uses_compositor_and_exact_v2_ticks(self) -> None:
        native = self.ffmpeg.native_engine
        if native is None or not native.composition_preview_available or not native.tick_decoder_available:
            self.skipTest("Native DLL chưa có preview compositor và tick decoder mới.")
        base = self._one_visual_track(duration=90_000)
        overlay = self._one_visual_track(start=18_000, duration=45_000,
                                         media=self.assets["video_overlay"])
        overlay.layer_order = 1
        graph = build_composition_graph(self._simple_project(tracks=[base, overlay]),
                                        self.media_store.get_metadata)
        frame, renderer = render_preview_frame(graph, self.media_store, self.ffmpeg.ffmpeg, 36_000, native)
        self.assertEqual("native-cpp", renderer)
        with Image.open(BytesIO(frame)) as image:
            red, green, blue = image.convert("RGB").getpixel((32, 32))
        self.assertGreater(blue, 150)
        export_dir = self.root / "native_video_overlay_export"
        export_dir.mkdir(exist_ok=True)
        job = VideoJob(job_id=uuid4().hex, project_id=graph.project_id)
        render_composition_project(job, graph, self.media_store, self.ffmpeg.ffmpeg, export_dir,
                                   "draft", native)
        self.assertEqual("succeeded", job.state, job.snapshot())
        export_frame_path = export_dir / "video_overlay_frame.png"
        process = subprocess.run([self.ffmpeg.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                  "-i", str(job.output_path), "-vf", "select=eq(n\\,12)",
                                  "-frames:v", "1", str(export_frame_path)], capture_output=True,
                                 text=True, check=False, timeout=30)
        self.assertEqual(0, process.returncode, process.stderr)
        with Image.open(export_frame_path) as export_image:
            export = export_image.convert("RGB")
        with Image.open(BytesIO(frame)) as preview_image:
            preview_rgb = preview_image.convert("RGB")
        mae = sum(abs(a - b) for a, b in zip(preview_rgb.tobytes(), export.tobytes())) / (
            preview_rgb.width * preview_rgb.height * 3
        )
        self.assertLessEqual(mae, 18.0)
        reordered = graph.tracks[0]
        overlay_track = graph.tracks[1]
        reordered_overlay = self._one_visual_track(duration=90_000, track_id=overlay_track.track_id,
                                                   media=self.assets["video_overlay"])
        reordered_overlay.layer_order = 0
        reordered_base = self._one_visual_track(duration=90_000, track_id=reordered.track_id,
                                                media=self.assets["video"])
        reordered_base.layer_order = 1
        reordered_graph = build_composition_graph(
            self._simple_project(tracks=[reordered_overlay, reordered_base]), self.media_store.get_metadata,
        )
        reordered_frame, reordered_renderer = render_preview_frame(
            reordered_graph, self.media_store, self.ffmpeg.ffmpeg, 36_000, native,
        )
        self.assertEqual("native-cpp", reordered_renderer)
        with Image.open(BytesIO(reordered_frame)) as image:
            red, green, blue = image.convert("RGB").getpixel((32, 32))
        self.assertGreater(red, 150)
        self.assertLess(blue, 100)

    def test_native_preview_straight_alpha_matches_ffmpeg_export(self) -> None:
        native = self.ffmpeg.native_engine
        if native is None or not native.composition_preview_available or not native.tick_decoder_available:
            self.skipTest("Native DLL chưa có preview compositor và tick decoder mới.")
        base = self._one_visual_track(duration=90_000)
        overlay = self._one_visual_track(start=0, duration=90_000, media=self.assets["image"],
                                         properties=self._visual_properties("alpha", opacity=0.8))
        overlay.layer_order = 1
        graph = build_composition_graph(self._simple_project(tracks=[base, overlay]),
                                        self.media_store.get_metadata)
        preview_bytes, renderer = render_preview_frame(graph, self.media_store, self.ffmpeg.ffmpeg,
                                                      45_000, native)
        self.assertEqual("native-cpp", renderer)
        with Image.open(BytesIO(preview_bytes)) as preview_image:
            preview = preview_image.convert("RGB")
        transparent = preview.getpixel((10, 32))
        half_alpha = preview.getpixel((32, 32))
        opaque = preview.getpixel((54, 32))
        self.assertGreater(transparent[0], 230)
        self.assertLess(transparent[2], 20)
        self.assertGreater(half_alpha[0], 90)
        self.assertGreater(half_alpha[2], 50)
        self.assertLess(opaque[0], 100)
        self.assertGreater(opaque[2], 150)

        export_dir = self.root / "native_alpha_export"
        export_dir.mkdir(exist_ok=True)
        job = VideoJob(job_id=uuid4().hex, project_id=graph.project_id)
        render_composition_project(job, graph, self.media_store, self.ffmpeg.ffmpeg, export_dir,
                                   "draft", native)
        self.assertEqual("succeeded", job.state, job.snapshot())
        export_frame_path = export_dir / "alpha_export_frame.png"
        process = subprocess.run([self.ffmpeg.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                  "-i", str(job.output_path), "-vf", "select=eq(n\\,15)",
                                  "-frames:v", "1", str(export_frame_path)], capture_output=True,
                                 text=True, check=False, timeout=30)
        self.assertEqual(0, process.returncode, process.stderr)
        with Image.open(export_frame_path) as export_image:
            export = export_image.convert("RGB")
        mae = sum(abs(a - b) for a, b in zip(preview.tobytes(), export.tobytes())) / (
            preview.width * preview.height * 3
        )
        self.assertLessEqual(mae, 18.0)

    def test_fixture_09b_visual_gap_renders_black_in_preview_and_export(self) -> None:
        track_id = uuid4().hex
        first = TimelineClipV2(clip_id=uuid4().hex, track_id=track_id, clip_kind="video",
                               timeline_start_ticks=0, source_start_ticks=0, duration_ticks=30_000,
                               media_id=self.assets["video"].asset_id,
                               properties=self._visual_properties("first"))
        second = TimelineClipV2(clip_id=uuid4().hex, track_id=track_id, clip_kind="video",
                                timeline_start_ticks=90_000, source_start_ticks=0, duration_ticks=30_000,
                                media_id=self.assets["video"].asset_id,
                                properties=self._visual_properties("second"))
        track = TimelineTrackV2(track_id=track_id, kind="visual", layer_order=0,
                                display_name="Visual with gap", clips=[first, second])
        graph = build_composition_graph(self._simple_project(tracks=[track]),
                                        self.media_store.get_metadata)
        preview_gap = render_preview_frame_png(graph, self.media_store, self.ffmpeg.ffmpeg, 45_000)
        with Image.open(BytesIO(preview_gap)) as image:
            self.assertEqual((0, 0, 0), image.convert("RGB").getpixel((32, 32)))

        export_dir = self.root / "gap_export"
        export_dir.mkdir(exist_ok=True)
        job = VideoJob(job_id=uuid4().hex, project_id=graph.project_id)
        render_composition_project(job, graph, self.media_store, self.ffmpeg.ffmpeg, export_dir,
                                   "draft", self.ffmpeg.native_engine)
        self.assertEqual("succeeded", job.state, job.snapshot())
        for frame_index, should_be_red in ((15, False), (35, True)):
            frame_path = export_dir / f"gap_frame_{frame_index}.png"
            process = subprocess.run([self.ffmpeg.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                      "-i", str(job.output_path), "-vf",
                                      f"select=eq(n\\,{frame_index})", "-frames:v", "1", str(frame_path)],
                                     capture_output=True, text=True, check=False, timeout=30)
            self.assertEqual(0, process.returncode, process.stderr)
            with Image.open(frame_path) as image:
                red, green, blue = image.convert("RGB").getpixel((32, 32))
            if should_be_red:
                self.assertGreater(red, 180)
                self.assertLess(green, 80)
                self.assertLess(blue, 80)
            else:
                self.assertEqual((0, 0, 0), (red, green, blue))

    def test_native_tick_decoder_does_not_round_60fps_source_time_to_milliseconds(self) -> None:
        native = self.ffmpeg.native_engine
        if native is None or not native.tick_decoder_available:
            self.skipTest("Native DLL chưa có tick decoder mới.")
        video = self.root / "fixture_media" / "60fps_testsrc.mp4"
        self._ffmpeg("-f", "lavfi", "-i", "testsrc2=size=64x64:rate=60:duration=1",
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-fps_mode", "passthrough", str(video))
        width, height, rgba = native.decode_frame_ticks(video, 1_500, TIMEBASE, 64, 64)
        expected = self.root / "fixture_media" / "60fps_frame1.png"
        process = subprocess.run([self.ffmpeg.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                  "-i", str(video), "-vf", "select=eq(n\\,1)", "-frames:v", "1",
                                  str(expected)], capture_output=True, text=True, check=False, timeout=30)
        self.assertEqual(0, process.returncode, process.stderr)
        with Image.open(expected) as image:
            expected_rgba = image.convert("RGBA").tobytes()
        mae = sum(abs(a - b) for a, b in zip(rgba, expected_rgba)) / (64 * 64 * 4)
        self.assertEqual((64, 64), (width, height))
        self.assertLessEqual(mae, 2.0)

    def test_visual_source_offset_matches_preview_and_export_frame(self) -> None:
        video = self.root / "fixture_media" / "moving_source_30fps.mp4"
        self._ffmpeg("-f", "lavfi", "-i", "testsrc2=size=64x64:rate=30:duration=1",
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-fps_mode", "passthrough",
                     str(video))
        media = self.media_store.add("moving_source_30fps.mp4", "video", video, 1000)
        track = self._one_visual_track(source=15_000, duration=30_000, media=media)
        graph = build_composition_graph(self._simple_project(tracks=[track]),
                                        self.media_store.get_metadata)
        preview = render_preview_frame_png(graph, self.media_store, self.ffmpeg.ffmpeg, 0)
        expected_source_frame = self.root / "fixture_media" / "moving_source_frame_5.png"
        process = subprocess.run([self.ffmpeg.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                  "-i", str(video), "-vf", "select=eq(n\\,5)", "-frames:v", "1",
                                  str(expected_source_frame)], capture_output=True, text=True,
                                 check=False, timeout=30)
        self.assertEqual(0, process.returncode, process.stderr)
        with Image.open(BytesIO(preview)) as preview_image, Image.open(expected_source_frame) as source_image:
            preview_rgb = preview_image.convert("RGB")
            source_rgb = source_image.convert("RGB")
        preview_mae = sum(abs(a - b) for a, b in zip(preview_rgb.tobytes(), source_rgb.tobytes())) / (
            preview_rgb.width * preview_rgb.height * 3
        )
        self.assertLessEqual(preview_mae, 18.0)

        export_dir = self.root / "visual_source_offset_export"
        export_dir.mkdir(exist_ok=True)
        job = VideoJob(job_id=uuid4().hex, project_id=graph.project_id)
        render_composition_project(job, graph, self.media_store, self.ffmpeg.ffmpeg, export_dir,
                                   "draft", self.ffmpeg.native_engine)
        self.assertEqual("succeeded", job.state, job.snapshot())
        export_frame_path = export_dir / "source_offset_frame.png"
        process = subprocess.run([self.ffmpeg.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                  "-i", str(job.output_path), "-vf", "select=eq(n\\,0)",
                                  "-frames:v", "1", str(export_frame_path)], capture_output=True,
                                 text=True, check=False, timeout=30)
        self.assertEqual(0, process.returncode, process.stderr)
        with Image.open(export_frame_path) as export_image:
            export_rgb = export_image.convert("RGB")
        export_mae = sum(abs(a - b) for a, b in zip(export_rgb.tobytes(), source_rgb.tobytes())) / (
            export_rgb.width * export_rgb.height * 3
        )
        self.assertLessEqual(export_mae, 18.0)

    def test_fixture_03_image_alpha_asset_is_kept_as_image_overlay(self) -> None:
        overlay = self.graph.tracks[1].clips[0]
        self.assertEqual("image", overlay.media_kind)
        self.assertEqual(self.assets["image"].asset_id, overlay.media_id)
        command, _ = build_composition_command(self.graph, self.media_store, self.ffmpeg.ffmpeg,
                                               self.root / "dry.mp4", self.root / "tmp", "draft")
        graph_arg = command[command.index("-filter_complex") + 1]
        self.assertIn("format=rgba", graph_arg)
        self.assertIn("colorchannelmixer=aa=0.800000000", graph_arg)

    def test_fixture_04_layer_reorder_changes_composition_graph_order(self) -> None:
        reordered = self.project.model_copy(deep=True)
        reordered.tracks[0].layer_order = 1
        reordered.tracks[1].layer_order = 0
        graph = build_composition_graph(reordered, self.media_store.get_metadata)
        self.assertEqual(reordered.tracks[1].track_id,
                         next(track.track_id for track in graph.tracks if track.layer_order == 0))
        original_frame = render_preview_frame_png(self.graph, self.media_store, self.ffmpeg.ffmpeg, 36_000)
        reordered_frame = render_preview_frame_png(graph, self.media_store, self.ffmpeg.ffmpeg, 36_000)
        with Image.open(BytesIO(original_frame)) as original_image, Image.open(BytesIO(reordered_frame)) as reordered_image:
            self.assertNotEqual(original_image.convert("RGB").getpixel((55, 32)),
                                reordered_image.convert("RGB").getpixel((55, 32)))

    def test_fixture_05_text_layer_has_independent_absolute_timing(self) -> None:
        track = next(track for track in self.graph.tracks if track.kind == "text")
        clip = track.clips[0]
        self.assertEqual((27_000, 63_000), (clip.timeline_start_ticks, clip.end_ticks))
        self.assertEqual("TEST", clip.attributes["text"])

    def test_fixture_06_two_audio_tracks_have_simultaneous_sources(self) -> None:
        audio = [track for track in self.graph.tracks if track.kind == "audio"]
        self.assertEqual(2, len(audio))
        self.assertLess(audio[1].clips[0].timeline_start_ticks, audio[0].clips[0].end_ticks)
        command, _ = build_composition_command(self.graph, self.media_store, self.ffmpeg.ffmpeg,
                                               self.root / "dry.mp4", self.root / "tmp", "draft")
        self.assertIn("amix=inputs=2", command[command.index("-filter_complex") + 1])

    def test_fixture_07_audio_source_offset_and_half_open_boundaries(self) -> None:
        clip = next(track.clips[0] for track in self.graph.tracks if track.kind == "audio" and
                    track.clips[0].source_start_ticks != 0)
        self.assertTrue(clip_is_active(clip, clip.timeline_start_ticks))
        self.assertFalse(clip_is_active(clip, clip.end_ticks))
        self.assertEqual(clip.source_start_ticks + 1, source_time_ticks_at(clip, clip.timeline_start_ticks + 1))
        with self.assertRaises(CompositionGraphError):
            source_time_ticks_at(clip, clip.end_ticks)

    def test_fixture_08_mixed_visual_text_audio_preview_and_export(self) -> None:
        if self.artifact_root:
            output_dir = self.root / "runtime"
        else:
            output_dir = self.root / "runtime"
            output_dir.mkdir(exist_ok=True)
        preview_ticks = 36_000  # 0.4s: image + text + both audio sources are active.
        preview = render_preview_frame_png(self.graph, self.media_store, self.ffmpeg.ffmpeg,
                                           preview_ticks)
        preview_path = output_dir / "preview_t_0_4s.png"
        preview_path.write_bytes(preview)
        job = VideoJob(job_id=uuid4().hex, project_id=self.graph.project_id)
        render_composition_project(job, self.graph, self.media_store, self.ffmpeg.ffmpeg,
                                   output_dir, "draft", self.ffmpeg.native_engine)
        self.assertEqual("succeeded", job.state)
        self.assertTrue(job.output_path and job.output_path.is_file())
        export_frame = output_dir / "export_t_0_4s.png"
        process = subprocess.run([self.ffmpeg.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                  "-i", str(job.output_path), "-vf", "select=eq(n\\,12)",
                                  "-frames:v", "1", str(export_frame)], capture_output=True,
                                 text=True, check=False, timeout=30)
        self.assertEqual(0, process.returncode, process.stderr)
        self.assertTrue(export_frame.is_file())
        with Image.open(preview_path) as image:
            preview_rgb = image.convert("RGB")
        with Image.open(export_frame) as image:
            export_rgb = image.convert("RGB")
        self.assertEqual((64, 64), preview_rgb.size)
        self.assertEqual((64, 64), export_rgb.size)
        mae = sum(abs(a - b) for a, b in zip(preview_rgb.tobytes(), export_rgb.tobytes())) / (64 * 64 * 3)
        self.assertLessEqual(mae, 18.0)
        self.assertLess(preview_rgb.getpixel((10, 32))[2], 100)  # fully transparent side stays base red
        self.assertGreater(preview_rgb.getpixel((55, 32))[2], 70)  # half-alpha blue contributes
        def white_pixel_count(frame: Image.Image) -> int:
            return sum(1 for red, green, blue in frame.crop((18, 20, 46, 44)).getdata()
                       if red > 200 and green > 200 and blue > 200)
        for timestamp, should_contain_text in ((18_000, False), (36_000, True), (72_000, False)):
            boundary_png = render_preview_frame_png(self.graph, self.media_store,
                                                    self.ffmpeg.ffmpeg, timestamp)
            with Image.open(BytesIO(boundary_png)) as image:
                count = white_pixel_count(image.convert("RGB"))
            self.assertEqual(should_contain_text, count > 2,
                             f"Text preview boundary mismatch at {timestamp} ticks: {count} pixels")
        for frame_index, should_contain_text in ((6, False), (12, True), (24, False)):
            boundary_path = output_dir / f"text_boundary_{frame_index}.png"
            process = subprocess.run([self.ffmpeg.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                      "-i", str(job.output_path), "-vf",
                                      f"select=eq(n\\,{frame_index})", "-frames:v", "1", str(boundary_path)],
                                     capture_output=True, text=True, check=False, timeout=30)
            self.assertEqual(0, process.returncode, process.stderr)
            with Image.open(boundary_path) as image:
                count = white_pixel_count(image.convert("RGB"))
            self.assertEqual(should_contain_text, count > 2,
                             f"Text export boundary mismatch at frame {frame_index}: {count} pixels")
        if self.artifact_root:
            (self.root / "runtime" / "composition_graph.json").write_text(
                json.dumps(self.graph.to_dict(), indent=2), encoding="utf-8")
            (self.root / "runtime" / "frame_parity.json").write_text(json.dumps({
                "timestampTicks": preview_ticks, "frameIndex": self.graph.frame_index_at(preview_ticks),
                "rgbMae": mae, "threshold": 18.0, "status": "PASS",
            }, indent=2), encoding="utf-8")
            (self.root / "runtime" / "render_job.json").write_text(json.dumps(job.snapshot(), indent=2), encoding="utf-8")

    def test_fixture_09_gap_and_nonzero_start_remain_black_before_clip(self) -> None:
        track = self._one_visual_track(start=30_000, duration=30_000)
        project = self._simple_project(tracks=[track])
        graph = build_composition_graph(project, self.media_store.get_metadata)
        self.assertEqual(60_000, graph.duration_ticks)
        self.assertFalse(clip_is_active(graph.tracks[0].clips[0], 29_999))
        self.assertTrue(clip_is_active(graph.tracks[0].clips[0], 30_000))
        before = render_preview_frame_png(graph, self.media_store, self.ffmpeg.ffmpeg, 22_500)
        active = render_preview_frame_png(graph, self.media_store, self.ffmpeg.ffmpeg, 45_000)
        with Image.open(BytesIO(before)) as image:
            self.assertEqual((0, 0, 0), image.convert("RGB").getpixel((32, 32)))
        with Image.open(BytesIO(active)) as image:
            self.assertGreater(image.convert("RGB").getpixel((32, 32))[0], 180)

    def test_fixture_10_unsupported_transition_is_rejected_explicitly(self) -> None:
        track = self._one_visual_track(properties=self._visual_properties("fade", transition="fade"))
        with self.assertRaisesRegex(CompositionGraphError, "transition"):
            build_composition_graph(self._simple_project(tracks=[track]), self.media_store.get_metadata)

    def test_fixture_11_missing_media_is_not_silently_omitted(self) -> None:
        track = self._one_visual_track()
        with self.assertRaisesRegex(CompositionGraphError, "Không tìm thấy media"):
            build_composition_graph(self._simple_project(tracks=[track]), lambda _asset_id: (_ for _ in ()).throw(KeyError()))

    def test_fixture_12_source_bounds_and_placeholder_validation(self) -> None:
        with self.assertRaisesRegex(CompositionGraphError, "vượt giới hạn"):
            build_composition_graph(self._simple_project(tracks=[self._one_visual_track(
                source=60_000, duration=45_000
            )]), self.media_store.get_metadata)
        placeholder_id = uuid4().hex
        placeholder = TimelineTrackV2(track_id=placeholder_id, kind="visual", layer_order=0,
                                      display_name="Placeholder", clips=[TimelineClipV2(
                                          clip_id=uuid4().hex, track_id=placeholder_id, clip_kind="video",
                                          timeline_start_ticks=0, duration_ticks=90_000,
                                          media_id=None, properties=self._visual_properties("placeholder"),
                                      )])
        with self.assertRaisesRegex(CompositionGraphError, "placeholder"):
            build_composition_graph(self._simple_project(tracks=[placeholder]), self.media_store.get_metadata)

    def test_rational_frame_rate_matrix_and_frame_boundaries(self) -> None:
        for numerator, denominator, expected_ticks in ((24, 1, 3750), (25, 1, 3600), (30, 1, 3000),
                                                        (60, 1, 1500), (30_000, 1001, 3003)):
            with self.subTest(rate=f"{numerator}/{denominator}"):
                project = self._simple_project(fps_num=numerator, fps_den=denominator,
                                               tracks=[self._one_visual_track(duration=90_000)])
                graph = build_composition_graph(project, self.media_store.get_metadata)
                self.assertEqual(expected_ticks, graph.frame_start_ticks(1))
                self.assertEqual(1, graph.frame_index_at(expected_ticks))
                self.assertEqual(0, graph.frame_index_at(expected_ticks - 1))
                clip = graph.tracks[0].clips[0]
                self.assertTrue(clip_is_active(clip, clip.end_ticks - 1))
                self.assertFalse(clip_is_active(clip, clip.end_ticks))

    def test_export_frame_rate_matrix_preserves_rational_rate(self) -> None:
        expected_rates = ((24, 1), (25, 1), (30, 1), (60, 1), (30_000, 1001))
        for numerator, denominator in expected_rates:
            with self.subTest(rate=f"{numerator}/{denominator}"):
                graph = build_composition_graph(
                    self._simple_project(fps_num=numerator, fps_den=denominator,
                                         tracks=[self._one_visual_track(duration=90_000)]),
                    self.media_store.get_metadata,
                )
                export_dir = self.root / f"fps_{numerator}_{denominator}"
                export_dir.mkdir(exist_ok=True)
                job = VideoJob(job_id=uuid4().hex, project_id=graph.project_id)
                render_composition_project(job, graph, self.media_store, self.ffmpeg.ffmpeg,
                                           export_dir, "draft", self.ffmpeg.native_engine)
                self.assertEqual("succeeded", job.state, job.snapshot())
                probe = subprocess.run([self.ffmpeg.ffprobe, "-v", "error", "-select_streams", "v:0",
                                        "-show_entries", "stream=avg_frame_rate,r_frame_rate",
                                        "-of", "json", str(job.output_path)], capture_output=True,
                                       text=True, check=False, timeout=30)
                self.assertEqual(0, probe.returncode, probe.stderr)
                stream = json.loads(probe.stdout)["streams"][0]
                expected = f"{numerator}/{denominator}"
                self.assertEqual(expected, stream["avg_frame_rate"])

    def test_same_track_visual_overlap_and_wrong_media_kind_rejected(self) -> None:
        track = self._one_visual_track(duration=45_000)
        overlap = TimelineClipV2(clip_id=uuid4().hex, track_id=track.track_id, clip_kind="video",
                                 timeline_start_ticks=30_000, duration_ticks=45_000,
                                 media_id=self.assets["video"].asset_id,
                                 properties=self._visual_properties("overlap"))
        track.clips.append(overlap)
        with self.assertRaisesRegex(CompositionGraphError, "chồng lấn"):
            build_composition_graph(self._simple_project(tracks=[track]), self.media_store.get_metadata)

    def test_native_decoder_repeated_seeks_use_independent_fixture_source(self) -> None:
        if self.ffmpeg.native_engine is None:
            self.skipTest("Native engine DLL is not loadable in this environment")
        path = self.media_store.get_path(self.assets["video"].asset_id)
        self.ffmpeg.native_engine.clear_frame_cache()
        overlay_path = self.media_store.get_path(self.assets["video_overlay"].asset_id)
        requests = [(path if index % 2 == 0 else overlay_path, timestamp)
                    for index, timestamp in enumerate((0, 500, 100, 900, 0, 700, 200, 800, 300, 600) * 2)]
        with ThreadPoolExecutor(max_workers=6) as executor:
            frames = list(executor.map(
                lambda item: self.ffmpeg.decode_frame_rgba(item[0], item[1], 64, 64), requests
            ))
        self.assertTrue(all((width, height, len(pixels)) == (64, 64, 64 * 64 * 4)
                            for width, height, pixels in frames))

    def test_audio_analysis_finds_both_tones_in_overlap_and_no_early_second_tone(self) -> None:
        output_dir = self.root / "audio_analysis"
        output_dir.mkdir(exist_ok=True)
        # Reuse the exact project export from fixture 08 when it exists; otherwise render this fixture.
        audio_only_tracks = [track.model_copy(deep=True) for track in self.project.tracks if track.kind == "audio"]
        visual = self._one_visual_track(duration=90_000)
        project = self._simple_project(tracks=[visual, *audio_only_tracks])
        graph = build_composition_graph(project, self.media_store.get_metadata)
        self.assertEqual("sum-gains-no-normalization", graph.audio_mix_policy)
        job = VideoJob(job_id=uuid4().hex, project_id=graph.project_id)
        render_composition_project(job, graph, self.media_store, self.ffmpeg.ffmpeg, output_dir, "draft",
                                   self.ffmpeg.native_engine)
        self.assertEqual("succeeded", job.state)
        process = subprocess.run([self.ffmpeg.ffmpeg, "-hide_banner", "-loglevel", "error", "-i",
                                  str(job.output_path), "-map", "0:a:0", "-ac", "1", "-ar", "44100",
                                  "-f", "f32le", "pipe:1"], capture_output=True, check=False, timeout=30)
        self.assertEqual(0, process.returncode, process.stderr.decode("utf-8", "replace"))
        samples = array("f")
        samples.frombytes(process.stdout[:len(process.stdout) - len(process.stdout) % 4])
        def energy_at(start_seconds: float, frequency: float) -> float:
            start = int(start_seconds * 44_100)
            return energy_at_samples(samples, start_seconds, frequency)
        def energy_at_samples(series: array, start_seconds: float, frequency: float) -> float:
            start = int(start_seconds * 44_100)
            window = series[start:start + 8820]
            if len(window) < 1000:
                return 0.0
            omega = 2 * math.pi * frequency / 44_100
            cosine, sine = math.cos(omega), math.sin(omega)
            coeff, previous, previous2 = 2 * cosine, 0.0, 0.0
            for sample in window:
                current = float(sample) + coeff * previous - previous2
                previous2, previous = previous, current
            power = previous2 * previous2 + previous * previous - coeff * previous * previous2
            return max(0.0, power)
        powers = {"early440": energy_at(0.05, 440), "early880": energy_at(0.05, 880),
                  "overlap440": energy_at(0.40, 440), "overlap880": energy_at(0.40, 880)}
        self.assertGreater(powers["early440"], 1e3)
        self.assertLess(powers["early880"], powers["early440"] * 0.2)
        self.assertGreater(powers["overlap440"], 1e3)
        self.assertGreater(powers["overlap880"], 1e3)
        self.assertLess(powers["overlap880"], powers["overlap440"] * 1.1)
        self.assertLess(energy_at(0.85, 440), 100.0)
        self.assertLess(energy_at(0.85, 880), 100.0)
        self.assertLess(energy_at(0.28, 880), powers["overlap880"] * 0.8)
        self.assertLess(energy_at(0.70, 880), powers["overlap880"] * 0.3)
        source_process = subprocess.run([self.ffmpeg.ffmpeg, "-hide_banner", "-loglevel", "error", "-i",
                                         str(self.media_store.get_path(self.assets["tone_a"].asset_id)),
                                         "-ac", "1", "-ar", "44100", "-f", "f32le", "pipe:1"],
                                        capture_output=True, check=False, timeout=30)
        self.assertEqual(0, source_process.returncode, source_process.stderr.decode("utf-8", "replace"))
        source_samples = array("f")
        source_samples.frombytes(source_process.stdout[:len(source_process.stdout) -
                                                       len(source_process.stdout) % 4])
        rendered_a_gain = math.sqrt(energy_at(0.05, 440) / max(1.0, energy_at_samples(source_samples, 0.05, 440)))
        self.assertGreater(rendered_a_gain, 0.36)
        self.assertLess(rendered_a_gain, 0.54)
        if self.artifact_root:
            (self.root / "audio_analysis" / "audio_metrics.json").write_text(json.dumps({
                "sampleRate": 44100,
                "audioA": {"frequencyHz": 440, "earlyPower": powers["early440"],
                           "overlapPower": powers["overlap440"]},
                "audioB": {"frequencyHz": 880, "earlyPower": powers["early880"],
                           "overlapPower": powers["overlap880"]},
                "gainRatioA": rendered_a_gain,
                "silenceAfterClips": {"440Power": energy_at(0.85, 440), "880Power": energy_at(0.85, 880)},
                "mixPolicy": "sum-gains-no-normalization; no limiter or loudness normalization",
            }, indent=2), encoding="utf-8")

    def test_embedded_video_audio_mixes_with_separate_audio_track(self) -> None:
        output = self.root / "fixture_media" / "video_with_440hz_audio.mp4"
        self._ffmpeg("-f", "lavfi", "-i", "color=c=red:s=64x64:r=30:d=1",
                     "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
                     "-shortest", str(output))
        embedded = self.media_store.add("video_with_440hz_audio.mp4", "video", output, 1000, "aac")
        audio_track_id = uuid4().hex
        separate = TimelineTrackV2(track_id=audio_track_id, kind="audio", layer_order=1,
                                   display_name="Separate 880 Hz", clips=[TimelineClipV2(
                                       clip_id=uuid4().hex, track_id=audio_track_id, clip_kind="audio",
                                       timeline_start_ticks=0, source_start_ticks=0, duration_ticks=90_000,
                                       media_id=self.assets["tone_b"].asset_id,
                                       properties=self._audio_properties(self.assets["tone_b"].asset_id, 0.5),
                                   )])
        visual = self._one_visual_track(duration=90_000, media=embedded)
        graph = build_composition_graph(self._simple_project(tracks=[visual, separate]),
                                        self.media_store.get_metadata)
        self.assertEqual("legacy-input-count-normalization", graph.audio_mix_policy)
        export_dir = self.root / "embedded_audio_export"
        export_dir.mkdir(exist_ok=True)
        job = VideoJob(job_id=uuid4().hex, project_id=graph.project_id)
        render_composition_project(job, graph, self.media_store, self.ffmpeg.ffmpeg, export_dir,
                                   "draft", self.ffmpeg.native_engine)
        self.assertEqual("succeeded", job.state, job.snapshot())
        process = subprocess.run([self.ffmpeg.ffmpeg, "-hide_banner", "-loglevel", "error", "-i",
                                  str(job.output_path), "-map", "0:a:0", "-ac", "1", "-ar", "44100",
                                  "-f", "f32le", "pipe:1"], capture_output=True, check=False, timeout=30)
        self.assertEqual(0, process.returncode, process.stderr.decode("utf-8", "replace"))
        samples = array("f")
        samples.frombytes(process.stdout[:len(process.stdout) - len(process.stdout) % 4])
        def tone_power(frequency: float) -> float:
            window = samples[int(0.2 * 44_100):int(0.4 * 44_100)]
            omega = 2 * math.pi * frequency / 44_100
            coeff, previous, previous2 = 2 * math.cos(omega), 0.0, 0.0
            for sample in window:
                current = float(sample) + coeff * previous - previous2
                previous2, previous = previous, current
            return max(0.0, previous2 * previous2 + previous * previous - coeff * previous * previous2)
        self.assertGreater(tone_power(440), 1e3)
        self.assertGreater(tone_power(880), 1e3)

    def test_legacy_linear_audio_tail_policy_holds_last_visual_frame(self) -> None:
        visual_track = self._one_visual_track(duration=90_000)
        audio_track_id = uuid4().hex
        audio_track = TimelineTrackV2(track_id=audio_track_id, kind="audio", layer_order=1,
                                      display_name="Long audio", clips=[TimelineClipV2(
                                          clip_id=uuid4().hex, track_id=audio_track_id, clip_kind="audio",
                                          timeline_start_ticks=0, source_start_ticks=0, duration_ticks=180_000,
                                          media_id=self.assets["tone_long"].asset_id,
                                          properties=self._audio_properties(self.assets["tone_long"].asset_id),
                                      )])
        graph = build_composition_graph(self._simple_project(tracks=[visual_track, audio_track]),
                                        self.media_store.get_metadata)
        self.assertEqual("legacy-hold-last-visual-through-audio-end", graph.duration_policy)
        self.assertEqual(180_000, graph.duration_ticks)
        frame = render_preview_frame_png(graph, self.media_store, self.ffmpeg.ffmpeg, 135_000)
        with Image.open(BytesIO(frame)) as image:
            red, green, blue = image.convert("RGB").getpixel((32, 32))
        self.assertGreater(red, 180)
        self.assertLess(green, 80)
        self.assertLess(blue, 80)

    def test_track_state_render_semantics(self) -> None:
        visible = self._one_visual_track()
        hidden_state = TrackStateV2(visible=False)
        hidden = visible.model_copy(update={"state": hidden_state})
        locked = self._one_visual_track(track_id=uuid4().hex)
        locked.layer_order = 1
        locked.state.locked = True
        graph = build_composition_graph(self._simple_project(tracks=[hidden, locked]),
                                        self.media_store.get_metadata)
        hidden_graph, locked_graph = graph.tracks
        self.assertFalse(hidden_graph.clips[0].enabled)
        self.assertTrue(locked_graph.clips[0].enabled)

    def test_api_preview_and_render_job_use_project_composition_graph(self) -> None:
        api_root = self.root / "api_runtime"
        app = FastAPI()
        app.state.token = "task22a-test-token"
        install_video_editor_api(app, api_root)
        with TestClient(app) as client:
            headers = {"X-Media-Studio-Token": "task22a-test-token"}
            imported: dict[str, str] = {}
            for name in ("base_red.mp4", "overlay_alpha.png"):
                path = next(path for path in self.root.rglob(name) if path.is_file())
                suffix_type = "video/mp4" if path.suffix == ".mp4" else "image/png"
                response = client.post("/api/v1/video/media", files={
                    "file": (name, path.read_bytes(), suffix_type),
                }, headers=headers)
                self.assertEqual(201, response.status_code, response.text)
                imported[name] = response.json()["assetId"]

            base_track, overlay_track = uuid4().hex, uuid4().hex
            project = self._simple_project(tracks=[
                TimelineTrackV2(track_id=base_track, kind="visual", layer_order=0,
                                display_name="Base", clips=[TimelineClipV2(
                                    clip_id=uuid4().hex, track_id=base_track, clip_kind="video",
                                    timeline_start_ticks=0, source_start_ticks=0, duration_ticks=90_000,
                                    media_id=imported["base_red.mp4"],
                                    properties=self._visual_properties("base"),
                                )]),
                TimelineTrackV2(track_id=overlay_track, kind="visual", layer_order=1,
                                display_name="Overlay", clips=[TimelineClipV2(
                                    clip_id=uuid4().hex, track_id=overlay_track, clip_kind="image",
                                    timeline_start_ticks=22_500, source_start_ticks=0, duration_ticks=45_000,
                                    media_id=imported["overlay_alpha.png"],
                                    properties=self._visual_properties("overlay", opacity=0.8),
                                )]),
            ])
            app.state.video_projects.create(project)
            preview_response = client.get(
                f"/api/v1/video/projects/{project.project_id}/preview/frame",
                params={"timestamp_ticks": 36_000}, headers=headers,
            )
            self.assertEqual(200, preview_response.status_code, preview_response.text)
            self.assertEqual("image/png", preview_response.headers["content-type"])
            self.assertEqual("1", preview_response.headers["x-composition-graph-version"])
            self.assertIn(preview_response.headers["x-composition-renderer"],
                          {"native-cpp", "ffmpeg-filtergraph"})
            unsaved_snapshot = project_api_payload(project)
            unsaved_snapshot["revision"] = 7
            unsaved_snapshot["tracks"][1]["clips"][0]["properties"]["opacity"] = 0.35
            unsaved_snapshot["clips"][1]["opacity"] = 0.35
            snapshot_response = client.post(
                f"/api/v1/video/projects/{project.project_id}/preview/frame",
                params={"timestamp_ticks": 36_000}, json=unsaved_snapshot, headers=headers,
            )
            self.assertEqual(200, snapshot_response.status_code, snapshot_response.text)
            self.assertEqual("7", snapshot_response.headers["x-composition-project-revision"])
            self.assertNotEqual(preview_response.headers["x-composition-source-fingerprint"],
                                snapshot_response.headers["x-composition-source-fingerprint"])
            self.assertNotEqual(preview_response.content, snapshot_response.content)
            mismatched_snapshot = dict(unsaved_snapshot, projectId="different-project")
            mismatch_response = client.post(
                f"/api/v1/video/projects/{project.project_id}/preview/frame",
                params={"timestamp_ticks": 36_000}, json=mismatched_snapshot, headers=headers,
            )
            self.assertEqual(422, mismatch_response.status_code)
            capability_response = client.get("/api/v1/video/capabilities", headers=headers)
            self.assertEqual(200, capability_response.status_code)
            composition_capabilities = capability_response.json()["composition"]
            self.assertEqual(90_000, composition_capabilities["timelineTimebase"])
            self.assertEqual("SUPPORTED_VERIFIED", composition_capabilities["multiTrackPreviewExportParity"])
            self.assertFalse(composition_capabilities["audioMixPolicy"]["limiter"])

            render_response = client.post(
                f"/api/v1/video/projects/{project.project_id}/render-jobs",
                json={"quality": "draft"}, headers=headers,
            )
            self.assertEqual(202, render_response.status_code, render_response.text)
            job_id = render_response.json()["jobId"]
            import time
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                snapshot = client.get(f"/api/v1/video/jobs/{job_id}", headers=headers).json()
                if snapshot["state"] in {"succeeded", "failed", "cancelled"}:
                    break
                time.sleep(0.05)
            self.assertEqual("succeeded", snapshot["state"], snapshot)
            output_response = client.get(f"/api/v1/video/jobs/{job_id}/result", headers=headers)
            self.assertEqual(200, output_response.status_code, output_response.text)
            output_path = self.root / "api_runtime" / "api_composition.mp4"
            output_path.write_bytes(output_response.content)
            project_for_preview = app.state.video_projects.get(project.project_id)
            graph = build_composition_graph(project_for_preview, app.state.video_media.get_metadata)
            with tempfile.TemporaryDirectory() as temp:
                frame_path = Path(temp) / "frame.png"
                process = subprocess.run([self.ffmpeg.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                          "-i", str(output_path), "-vf", "select=eq(n\\,12)",
                                          "-frames:v", "1", str(frame_path)], capture_output=True,
                                         text=True, check=False, timeout=30)
                self.assertEqual(0, process.returncode, process.stderr)
                with Image.open(frame_path) as decoded:
                    export_frame = decoded.convert("RGB")
                with Image.open(BytesIO(preview_response.content)) as preview_image:
                    preview = preview_image.convert("RGB")
                mae = sum(abs(a - b) for a, b in zip(export_frame.tobytes(), preview.tobytes())) / (
                    graph.width * graph.height * 3
                )
                self.assertLessEqual(mae, 18.0)


if __name__ == "__main__":
    unittest.main()

