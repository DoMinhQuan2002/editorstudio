from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from mediastudio.video_editor.catalog import get_template
from mediastudio.video_editor.models import AudioTrack, TextLayer, VideoClip, VideoProject
from mediastudio.video_editor.project_v2 import (
    TIMEBASE, TimelineClipV2, TimelineEngineV2, TimelineEditError, TimelineTrackV2,
    VideoProjectV2, apply_api_compatibility_projection, migrate_v1_project,
    project_api_payload, render_capability, to_legacy_project,
)
from mediastudio.video_editor.storage import VideoProjectStore


class Task21ProjectV2Tests(unittest.TestCase):
    def legacy(self, *, template: str = "denim-story", project_id: str = "a" * 32) -> VideoProject:
        created = get_template(template).create_project("Denim V1")  # type: ignore[union-attr]
        project = to_legacy_project(created)
        project.project_id = project_id
        return project

    def test_template_migration_retains_five_unbound_three_second_slots_and_text(self):
        legacy = self.legacy()
        migrated = migrate_v1_project(legacy)
        visuals = [track for track in migrated.tracks if track.kind == "visual"]
        self.assertEqual(1, len(visuals))
        self.assertEqual(5, len(visuals[0].clips))
        self.assertEqual([0, 270_000, 540_000, 810_000, 1_080_000],
                         [clip.timeline_start_ticks for clip in visuals[0].clips])
        self.assertTrue(all(clip.duration_ticks == 270_000 and clip.media_id is None
                            for clip in visuals[0].clips))
        self.assertEqual(1, sum(track.kind == "text" for track in migrated.tracks))
        self.assertEqual(1_350_000, migrated.duration_ticks)
        adapted = to_legacy_project(migrated)
        self.assertEqual([clip.clip_id for clip in legacy.clips], [clip.clip_id for clip in adapted.clips])
        self.assertEqual("jeans", adapted.text_layers[0].text)

    def test_project_api_projection_keeps_v2_background_removal_out_of_legacy_clip(self):
        project = VideoProjectV2(
            schema_version=2, project_id="9" * 32, template_id="fall-diary", title="Fall Diary",
            tracks=[TimelineTrackV2(
                track_id="8" * 32, kind="visual", layer_order=0, display_name="Ảnh phủ",
                clips=[TimelineClipV2(
                    clip_id="7" * 32, track_id="8" * 32, clip_kind="image",
                    timeline_start_ticks=0, duration_ticks=90_000, media_id="6" * 32,
                    properties={"name": "overlay", "removeBackground": True},
                )],
            )],
        )

        payload = project_api_payload(project)

        self.assertTrue(payload["tracks"][0]["clips"][0]["properties"]["removeBackground"])
        self.assertNotIn("removeBackground", payload["clips"][0])

    def test_empty_and_fully_bound_v1_projects_migrate_without_losing_properties(self):
        empty = VideoProject(project_id="e" * 32, template_id="free-editor", title="Empty V1", clips=[])
        migrated_empty = migrate_v1_project(empty)
        self.assertEqual([], migrated_empty.tracks[0].clips)

        legacy = VideoProject(
            project_id="f" * 32, template_id="free-editor", title="Bound V1",
            clips=[VideoClip(clip_id="1" * 32, name="Bound scene", media_id="2" * 32,
                source_start_ms=125, duration_ms=2_500, fit_mode="contain", position_x=0.25,
                position_y=-0.1, scale=1.2, rotation=3, effect="warm", opacity=0.8,
                audio_volume=0.5, transition="fade", transition_duration_ms=200)],
            text_layers=[TextLayer(layer_id="3" * 32, text="kept", start_ms=750,
                duration_ms=1_200, x=0.2, y=0.8, font_size=40, color="#123456",
                font_family="Arial", opacity=0.7)],
            audio_tracks=[AudioTrack(track_id="4" * 32, media_id="5" * 32,
                timeline_start_ms=700, source_start_ms=300, duration_ms=4_000,
                volume=0.6, fade_in_ms=150, fade_out_ms=250)],
        )
        migrated = migrate_v1_project(legacy)
        adapted = to_legacy_project(migrated)
        self.assertEqual(legacy.clips[0].model_dump(), adapted.clips[0].model_dump())
        self.assertEqual(legacy.text_layers[0].model_dump(), adapted.text_layers[0].model_dump())
        self.assertEqual(legacy.audio_tracks[0].model_dump(), adapted.audio_tracks[0].model_dump())
        self.assertEqual(2_500 * 90, migrated.tracks[0].clips[0].duration_ticks)
        self.assertEqual(750 * 90, next(track for track in migrated.tracks if track.kind == "text").clips[0].timeline_start_ticks)

    def test_project_store_save_reopen_preserves_multitrack_ids_order_and_absolute_ticks(self):
        with tempfile.TemporaryDirectory() as folder:
            store = VideoProjectStore(Path(folder))
            project = VideoProjectV2.blank("Persistent tracks", fps_num=30_000, fps_den=1_001)
            engine = TimelineEngineV2(project)
            video = engine.create_track("visual", "V1")
            overlay = engine.create_track("visual", "V2")
            text = engine.create_track("text", "Text 1")
            audio = engine.create_track("audio", "Audio 1")
            engine.add_clip(video.track_id, TimelineClipV2(clip_id="a" * 32,
                track_id=video.track_id, clip_kind="video", timeline_start_ticks=123,
                source_start_ticks=456, duration_ticks=90_000, media_id="b" * 32))
            engine.add_clip(overlay.track_id, TimelineClipV2(clip_id="c" * 32,
                track_id=overlay.track_id, clip_kind="image", timeline_start_ticks=123,
                duration_ticks=45_000, media_id="d" * 32))
            engine.add_clip(text.track_id, TimelineClipV2(clip_id="e" * 32,
                track_id=text.track_id, clip_kind="text", timeline_start_ticks=1_000,
                duration_ticks=9_000))
            engine.add_clip(audio.track_id, TimelineClipV2(clip_id="f" * 32,
                track_id=audio.track_id, clip_kind="audio", timeline_start_ticks=2_000,
                source_start_ticks=3_000, duration_ticks=180_000, media_id="1" * 32))
            engine.reorder_track(overlay.track_id, 0)
            store.create(engine.project)
            store.save(project.project_id, engine.project)
            reopened = store.get(project.project_id)
            self.assertEqual(engine.project.model_dump(), reopened.model_dump())
            self.assertEqual([overlay.track_id, video.track_id, text.track_id, audio.track_id],
                             [track.track_id for track in sorted(reopened.tracks, key=lambda track: track.layer_order)])
            reopened_overlay = next(track for track in reopened.tracks if track.track_id == overlay.track_id).clips[0]
            self.assertEqual((overlay.track_id, "c" * 32, 123),
                             (reopened_overlay.track_id, reopened_overlay.clip_id,
                              reopened_overlay.timeline_start_ticks))

    def test_timebase_exactly_represents_supported_frame_rates_and_fractional_frame_rate(self):
        for numerator, denominator in ((24, 1), (25, 1), (30, 1), (60, 1), (30_000, 1_001)):
            project = VideoProjectV2(schema_version=2, project_id="b" * 32, template_id="free-editor", title="fps", tracks=[],
                frame_rate_numerator=numerator, frame_rate_denominator=denominator)
            self.assertEqual(0, project.timebase * denominator % numerator)
        self.assertEqual(3_003, TIMEBASE * 1_001 // 30_000)

    def test_absolute_positions_support_non_frame_aligned_start_gaps_and_cross_track_same_start(self):
        project = VideoProjectV2(schema_version=2, project_id="c" * 32, template_id="free-editor", title="gaps", tracks=[])
        engine = TimelineEngineV2(project)
        first = engine.create_track("visual", "V1")
        second = engine.create_track("visual", "V2")
        a = TimelineClipV2(clip_id="1" * 32, track_id=first.track_id, clip_kind="video",
                           timeline_start_ticks=1_001, source_start_ticks=3, duration_ticks=90_000)
        b = TimelineClipV2(clip_id="2" * 32, track_id=second.track_id, clip_kind="image",
                           timeline_start_ticks=1_001, duration_ticks=90_000)
        engine.add_clip(first.track_id, a)
        engine.add_clip(second.track_id, b)
        self.assertEqual(91_001, engine.project.duration_ticks)
        self.assertTrue(render_capability(engine.project)[0] is False)
        self.assertEqual(1_001, engine.project.tracks[0].clips[0].timeline_start_ticks)

    def test_audio_migration_assigns_persistent_lane_ids_and_preserves_longer_tail(self):
        legacy = VideoProject(project_id="d" * 32, template_id="free-editor", title="audio",
            clips=[VideoClip(clip_id="e" * 32, name="v", duration_ms=3_000)],
            audio_tracks=[AudioTrack(track_id="f" * 32, media_id="1" * 32,
                                     timeline_start_ms=0, source_start_ms=250, duration_ms=37_608)])
        migrated = migrate_v1_project(legacy)
        audio_track = next(track for track in migrated.tracks if track.kind == "audio")
        self.assertNotEqual("f" * 32, audio_track.track_id)
        self.assertEqual("f" * 32, audio_track.clips[0].clip_id)
        self.assertEqual(250 * 90, audio_track.clips[0].source_start_ticks)
        self.assertEqual(37_608 * 90, migrated.duration_ticks)
        self.assertEqual(37_608, to_legacy_project(migrated).duration_ms)
        self.assertEqual((True, None), render_capability(migrated))

    def test_store_migrates_only_opened_project_backups_hash_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            store = VideoProjectStore(Path(folder))
            legacy = self.legacy()
            path = Path(folder) / f"{legacy.project_id}.json"
            original = legacy.model_dump_json(indent=2, by_alias=True).encode()
            path.write_bytes(original)
            listed = store.list()
            self.assertEqual(2, listed[0].schema_version)
            self.assertEqual(original, path.read_bytes())  # listing is read-only
            migrated = store.get(legacy.project_id)
            self.assertEqual(2, migrated.schema_version)
            backups = list(Path(folder).glob("*.v1.*.bak"))
            self.assertEqual(1, len(backups))
            self.assertEqual(hashlib.sha256(original).hexdigest(), hashlib.sha256(backups[0].read_bytes()).hexdigest())
            self.assertEqual(migrated.model_dump(), store.get(legacy.project_id).model_dump())
            self.assertEqual(1, len(list(Path(folder).glob("*.v1.*.bak"))))

    def test_failed_migration_preserves_original_and_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            store = VideoProjectStore(Path(folder))
            legacy = self.legacy(project_id="9" * 32)
            path = Path(folder) / f"{legacy.project_id}.json"
            original = legacy.model_dump_json(indent=2, by_alias=True).encode()
            path.write_bytes(original)
            with patch.object(VideoProjectStore, "_write", side_effect=OSError("simulated interrupted replace")):
                with self.assertRaisesRegex(ValueError, "project gốc được giữ nguyên"):
                    store.get(legacy.project_id)
            self.assertEqual(original, path.read_bytes())
            self.assertEqual(1, len(list(Path(folder).glob("*.v1.*.bak"))))
            self.assertEqual([], list(Path(folder).glob("*.v2.tmp")))

    def test_rollback_restores_exact_v1_and_refuses_after_first_save(self):
        with tempfile.TemporaryDirectory() as folder:
            store = VideoProjectStore(Path(folder))
            legacy = self.legacy(project_id="8" * 32)
            path = Path(folder) / f"{legacy.project_id}.json"
            original = legacy.model_dump_json(indent=2, by_alias=True).encode()
            path.write_bytes(original)
            project = store.get(legacy.project_id)
            store.rollback_migration(legacy.project_id)
            self.assertEqual(original, path.read_bytes())
            path.write_bytes(original)
            project = store.get(legacy.project_id)
            store.save(legacy.project_id, project)
            with self.assertRaisesRegex(ValueError, "trước lần Save đầu tiên"):
                store.rollback_migration(legacy.project_id)

    def test_unsupported_schema_and_malformed_v1_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            store = VideoProjectStore(Path(folder))
            unsupported = Path(folder) / f"{'7' * 32}.json"
            unsupported.write_text(json.dumps({"schemaVersion": 9, "projectId": "7" * 32}))
            before = unsupported.read_bytes()
            with self.assertRaises(ValueError):
                store.get("7" * 32)
            self.assertEqual(before, unsupported.read_bytes())
            malformed = Path(folder) / f"{'6' * 32}.json"
            malformed.write_text("{bad json")
            before = malformed.read_bytes()
            with self.assertRaises(ValueError):
                store.get("6" * 32)
            self.assertEqual(before, malformed.read_bytes())

    def test_engine_move_trim_undo_redo_keeps_clip_and_track_identity(self):
        project = VideoProjectV2(schema_version=2, project_id="5" * 32, template_id="free-editor", title="engine", tracks=[])
        engine = TimelineEngineV2(project)
        visual = engine.create_track("visual", "V1")
        overlay = engine.create_track("visual", "V2")
        clip = TimelineClipV2(clip_id="4" * 32, track_id=visual.track_id, clip_kind="video",
                             timeline_start_ticks=90, source_start_ticks=180, duration_ticks=90_000)
        engine.add_clip(visual.track_id, clip)
        engine.move_clip_to_track(clip.clip_id, overlay.track_id, 300)
        moved = engine.project.tracks[1].clips[0]
        self.assertEqual(clip.clip_id, moved.clip_id)
        self.assertEqual(300, moved.timeline_start_ticks)
        engine.trim_source(clip.clip_id, 450, 45_000)
        self.assertTrue(engine.undo())
        moved = engine.project.tracks[1].clips[0]
        self.assertEqual(180, moved.source_start_ticks)
        self.assertTrue(engine.redo())
        moved = engine.project.tracks[1].clips[0]
        self.assertEqual(450, moved.source_start_ticks)
        self.assertEqual(overlay.track_id, moved.track_id)

    def test_engine_persists_empty_tracks_and_rejects_wrong_kind_moves(self):
        project = VideoProjectV2.blank("empty")
        engine = TimelineEngineV2(project)
        audio = engine.create_track("audio", "Music")
        visual = engine.create_track("visual", "V1")
        clip = TimelineClipV2(clip_id="3" * 32, track_id=visual.track_id, clip_kind="image",
                             timeline_start_ticks=0, duration_ticks=90_000)
        engine.add_clip(visual.track_id, clip)
        with self.assertRaises(TimelineEditError):
            engine.move_clip_to_track(clip.clip_id, audio.track_id)
        serialized = VideoProjectV2.model_validate(engine.project.model_dump())
        self.assertEqual(audio.track_id, serialized.tracks[0].track_id)
        self.assertEqual([], serialized.tracks[0].clips)

    def test_same_track_overlap_is_reference_pending_not_implicit_ripple_or_replace(self):
        project = VideoProjectV2.blank("overlap")
        engine = TimelineEngineV2(project)
        visual = engine.create_track("visual", "V1")
        first = TimelineClipV2(clip_id="a" * 32, track_id=visual.track_id, clip_kind="video",
                               timeline_start_ticks=0, duration_ticks=1000)
        second = TimelineClipV2(clip_id="b" * 32, track_id=visual.track_id, clip_kind="video",
                                timeline_start_ticks=500, duration_ticks=1000)
        engine.add_clip(visual.track_id, first)
        status = engine.validate_clip_placement(visual.track_id, second)
        self.assertEqual("REFERENCE_PENDING", status["status"])
        with self.assertRaisesRegex(TimelineEditError, "chờ xác minh"):
            engine.add_clip(visual.track_id, second)

    def test_renderer_refuses_unverified_audio_track_mixing(self):
        project = VideoProjectV2.blank("audio render guard")
        engine = TimelineEngineV2(project)
        first_track = engine.create_track("audio", "Music")
        second_track = engine.create_track("audio", "Voice")
        for index, track in enumerate((first_track, second_track)):
            engine.add_clip(track.track_id, TimelineClipV2(
                clip_id=f"{index + 1:x}" * 32, track_id=track.track_id,
                clip_kind="audio", timeline_start_ticks=0, duration_ticks=90_000,
                media_id=f"{index + 3:x}" * 32))
        supported, reason = render_capability(engine.project)
        self.assertFalse(supported)
        self.assertIn("Trộn nhiều audio track", reason or "")

    def test_linear_renderer_ignores_empty_persistent_tracks(self):
        project = VideoProjectV2.blank("empty lane render")
        engine = TimelineEngineV2(project)
        visual = engine.create_track("visual", "V1")
        engine.create_track("visual", "V2 empty")
        engine.create_track("text", "T1 empty")
        engine.create_track("audio", "A1 empty")
        engine.add_clip(visual.track_id, TimelineClipV2(
            clip_id="e" * 32, track_id=visual.track_id, clip_kind="video",
            timeline_start_ticks=0, duration_ticks=90_000, media_id="f" * 32))

        self.assertEqual((True, None), render_capability(engine.project))

    def test_legacy_audio_overlaps_are_stored_in_distinct_stable_tracks(self):
        legacy = VideoProject(project_id="2" * 32, template_id="free-editor", title="mix",
            clips=[VideoClip(clip_id="1" * 32, name="v", duration_ms=3_000)],
            audio_tracks=[
                AudioTrack(track_id="a" * 32, media_id="b" * 32, duration_ms=4_000),
                AudioTrack(track_id="c" * 32, media_id="d" * 32, duration_ms=4_000),
            ])
        migrated = migrate_v1_project(legacy)
        tracks = [track for track in migrated.tracks if track.kind == "audio"]
        self.assertEqual(2, len(tracks))
        self.assertNotEqual(tracks[0].track_id, tracks[1].track_id)
        self.assertEqual({"a" * 32, "c" * 32}, {clip.clip_id for track in tracks for clip in track.clips})

    def test_api_compatibility_edits_update_canonical_track_without_changing_ids(self):
        migrated = migrate_v1_project(self.legacy(project_id="0" * 32))
        payload = project_api_payload(migrated)
        visual = next(track for track in migrated.tracks if track.kind == "visual")
        payload["clips"][1]["timelineStartTicks"] = 300_123
        payload["clips"][1]["positionX"] = 0.25
        updated = apply_api_compatibility_projection(payload)
        track = next(track for track in updated.tracks if track.track_id == visual.track_id)
        clip = next(clip for clip in track.clips if clip.clip_id == payload["clips"][1]["clipId"])
        self.assertEqual(visual.track_id, clip.track_id)
        self.assertEqual(300_123, clip.timeline_start_ticks)
        self.assertEqual(0.25, clip.properties["positionX"])
        self.assertEqual(payload["clips"][1]["clipId"], clip.clip_id)

    def test_api_write_rejects_legacy_payload_that_could_drop_tracks(self):
        with self.assertRaisesRegex(ValueError, "schemaVersion 2"):
            apply_api_compatibility_projection({
                "projectId": "0" * 32,
                "templateId": "legacy",
                "clips": [],
                "textLayers": [],
                "audioTracks": [],
            })

    def test_api_write_rejects_incomplete_v2_compatibility_projection(self):
        project = VideoProjectV2.blank("projection")
        payload = project.model_dump(mode="json", by_alias=True)
        with self.assertRaisesRegex(ValueError, "Thiếu projection"):
            apply_api_compatibility_projection(payload)

    def test_free_editor_blank_project_save_and_reopen_remains_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            store = VideoProjectStore(Path(folder))
            blank = VideoProjectV2.blank("Empty", fps_num=30_000, fps_den=1_001)
            store.create(blank)
            reopened = store.get(blank.project_id)
            self.assertEqual(2, reopened.schema_version)
            self.assertEqual("free-editor", reopened.template_id)
            self.assertEqual([], reopened.tracks)
            self.assertEqual(0, reopened.duration_ticks)


if __name__ == "__main__":
    unittest.main()
