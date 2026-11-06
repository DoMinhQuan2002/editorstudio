import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from PIL import Image

from mediastudio.video_editor.models import MediaMetadata, VideoProject
from mediastudio.video_editor.renderer import VideoRenderError, validate_project_media
from mediastudio.video_editor.storage import VideoMediaStore


class TimelineTask1DBackendTests(unittest.TestCase):
    def test_project_can_persist_an_empty_video_track_after_delete_all(self):
        project = VideoProject(
            project_id="a" * 32,
            template_id="test-template",
            title="Timeline delete all test",
            clips=[],
        )

        self.assertEqual([], project.clips)
        self.assertEqual(0, project.duration_ms)

    def test_empty_project_is_editable_but_not_renderable(self):
        project = VideoProject(
            project_id="a" * 32,
            template_id="test-template",
            title="Timeline delete all test",
            clips=[],
        )

        with self.assertRaisesRegex(VideoRenderError, "chưa có clip hình"):
            validate_project_media(project, media_store=None)  # type: ignore[arg-type]

    def test_source_frame_preview_uses_requested_time_and_clamps_to_video_end(self):
        class FrameDecoder:
            decoded_timestamp_ms = None

            def decode_frame_rgba(self, source, timestamp_ms, max_width, max_height):
                self.decoded_timestamp_ms = timestamp_ms
                return 2, 1, bytes((255, 0, 0, 255, 0, 255, 0, 255))

        with TemporaryDirectory() as directory:
            decoder = FrameDecoder()
            store = VideoMediaStore(Path(directory), decoder)  # type: ignore[arg-type]
            store.get_metadata = Mock(return_value=MediaMetadata(
                asset_id="a" * 32,
                file_name="source.mp4",
                kind="video",
                content_type="video/mp4",
                byte_size=1024,
                duration_ms=4000,
            ))
            store.get_path = Mock(return_value=Path(directory) / "source.mp4")

            frame = store.frame_jpeg("a" * 32, 9000)

            self.assertEqual(3999, decoder.decoded_timestamp_ms)
            with Image.open(BytesIO(frame)) as decoded:
                self.assertEqual((2, 1), decoded.size)
                self.assertEqual("JPEG", decoded.format)


if __name__ == "__main__":
    unittest.main()
