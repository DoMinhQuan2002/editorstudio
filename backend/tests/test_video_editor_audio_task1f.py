from __future__ import annotations

import asyncio
import struct
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import UploadFile

from mediastudio.video_editor.models import AudioTrack, MediaMetadata, VideoClip, VideoProject
from mediastudio.video_editor.renderer import VideoRenderError, validate_project_media
from mediastudio.video_editor.storage import VideoMediaStore


class Task1FAudioBackendTests(unittest.TestCase):
    def test_audio_extends_project_duration_without_changing_video_sequence(self):
        project = VideoProject(
            project_id="a" * 32,
            template_id="template",
            title="Audio tail",
            clips=[VideoClip(name="scene", duration_ms=3000)],
            audio_tracks=[AudioTrack(media_id="b" * 32, timeline_start_ms=5000, duration_ms=4000)],
        )

        self.assertEqual(3000, sum(clip.duration_ms for clip in project.clips))
        self.assertEqual(9000, project.duration_ms)

    def test_audio_tracks_validate_source_range_and_do_not_require_video_kind(self):
        project = VideoProject(
            project_id="a" * 32,
            template_id="template",
            title="Audio routing",
            clips=[VideoClip(name="scene", media_id="b" * 32, duration_ms=3000)],
            audio_tracks=[AudioTrack(media_id="c" * 32, timeline_start_ms=5000,
                                     source_start_ms=1000, duration_ms=2000)],
        )
        media_store = Mock()
        media_store.get_metadata.side_effect = [
            MediaMetadata(asset_id="b" * 32, file_name="scene.mp4", kind="video",
                          content_type="video/mp4", byte_size=100, duration_ms=5000, video_codec="h264"),
            MediaMetadata(asset_id="c" * 32, file_name="music.mp3", kind="audio",
                          content_type="audio/mpeg", byte_size=100, duration_ms=5000, audio_codec="mp3"),
        ]

        validate_project_media(project, media_store)

    def test_audio_track_outside_source_duration_is_rejected(self):
        project = VideoProject(
            project_id="a" * 32,
            template_id="template",
            title="Invalid source range",
            clips=[VideoClip(name="scene", media_id="b" * 32, duration_ms=3000)],
            audio_tracks=[AudioTrack(media_id="c" * 32, source_start_ms=4000, duration_ms=2000)],
        )
        media_store = Mock()
        media_store.get_metadata.side_effect = [
            MediaMetadata(asset_id="b" * 32, file_name="scene.mp4", kind="video",
                          content_type="video/mp4", byte_size=100, duration_ms=5000, video_codec="h264"),
            MediaMetadata(asset_id="c" * 32, file_name="music.mp3", kind="audio",
                          content_type="audio/mpeg", byte_size=100, duration_ms=5000, audio_codec="mp3"),
        ]

        with self.assertRaisesRegex(VideoRenderError, "vượt thời lượng nguồn"):
            validate_project_media(project, media_store)

    def test_waveform_returns_cached_real_peak_values(self):
        class FakeToolchain:
            ffmpeg = "ffmpeg"
            native_engine = None

        with tempfile.TemporaryDirectory() as directory:
            store = VideoMediaStore(Path(directory), FakeToolchain())  # type: ignore[arg-type]
            store.get_metadata = Mock(return_value=MediaMetadata(
                asset_id="c" * 32, file_name="tone.wav", kind="audio",
                content_type="audio/wav", byte_size=200, duration_ms=100,
                audio_codec="pcm_s16le",
            ))
            store.get_path = Mock(return_value=Path(directory) / "tone.wav")
            pcm = struct.pack("<100h", *([16384, -8192] * 50))
            completed = Mock(returncode=0, stdout=pcm)

            with patch("mediastudio.video_editor.storage.subprocess.run", return_value=completed) as decode:
                samples = store.waveform_samples("c" * 32, 100)
                self.assertEqual(100, len(samples))
                self.assertEqual(0.5, samples[0])
                self.assertEqual(0.25, samples[1])
                cached = store.waveform_samples("c" * 32, 100)

            self.assertEqual(samples, cached)
            decode.assert_called_once()

    def test_media_import_routes_video_with_audio_as_video_and_audio_only_as_audio(self):
        class FakeToolchain:
            ffmpeg = None
            native_engine = None

        async def import_asset(store: VideoMediaStore, filename: str) -> MediaMetadata:
            upload = UploadFile(filename=filename, file=BytesIO(b"valid-media-bytes"))
            return await store.import_upload(upload)

        async def run() -> tuple[MediaMetadata, MediaMetadata]:
            with tempfile.TemporaryDirectory() as directory:
                store = VideoMediaStore(Path(directory), FakeToolchain())  # type: ignore[arg-type]
                probes = iter([
                    {"has_video": False, "has_audio": True, "duration_ms": 6000,
                     "width": None, "height": None, "video_codec": None, "audio_codec": "aac"},
                    {"has_video": True, "has_audio": True, "duration_ms": 6000,
                     "width": 720, "height": 1280, "video_codec": "h264", "audio_codec": "aac"},
                ])

                with patch("mediastudio.video_editor.storage.media_stream_info",
                           side_effect=lambda *_: next(probes)):
                    audio = await import_asset(store, "audio.mp4")
                    video = await import_asset(store, "video.mp4")
                return audio, video

        audio, video = asyncio.run(run())
        self.assertEqual("audio", audio.kind)
        self.assertEqual("video", video.kind)
        self.assertEqual("aac", video.audio_codec)


if __name__ == "__main__":
    unittest.main()
