from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mediastudio.video_editor.api import install_video_editor_api


class Task21ProjectV2ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        app = FastAPI()
        app.state.token = "task21-test-token"
        install_video_editor_api(app, Path(self.temporary.name))
        self.client_context = TestClient(app, client=("127.0.0.1", 50121))
        self.client = self.client_context.__enter__()
        self.headers = {"X-Media-Studio-Token": "task21-test-token"}

    def tearDown(self) -> None:
        self.client_context.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_blank_project_is_v2_persisted_and_compatibility_write_requires_schema(self):
        created = self.client.post("/api/v1/video/projects/blank", json={"title": "Free Editor"}, headers=self.headers)
        self.assertEqual(201, created.status_code, created.text)
        project = created.json()
        self.assertEqual(2, project["schemaVersion"])
        self.assertEqual("free-editor", project["templateId"])
        self.assertEqual([], project["tracks"])
        self.assertEqual([], project["clips"])

        reopened = self.client.get(f"/api/v1/video/projects/{project['projectId']}", headers=self.headers)
        self.assertEqual(200, reopened.status_code)
        self.assertEqual(project["projectId"], reopened.json()["projectId"])
        saved = self.client.put(f"/api/v1/video/projects/{project['projectId']}", json=project,
                                headers=self.headers)
        self.assertEqual(200, saved.status_code, saved.text)
        self.assertEqual(2, saved.json()["schemaVersion"])

    def test_template_creation_persists_placeholder_clips_under_track_entities(self):
        response = self.client.post("/api/v1/video/projects", json={"templateId": "denim-story"},
                                    headers=self.headers)
        self.assertEqual(201, response.status_code, response.text)
        project = response.json()
        self.assertEqual(5, len(project["clips"]))
        visual = [track for track in project["tracks"] if track["kind"] == "visual"]
        self.assertEqual(1, len(visual))
        self.assertEqual(5, len(visual[0]["clips"]))
        self.assertTrue(all(clip["mediaId"] is None and clip["durationTicks"] == 270_000
                            for clip in visual[0]["clips"]))
        disk = Path(self.temporary.name) / "video_editor" / "projects" / f"{project['projectId']}.json"
        self.assertTrue(disk.exists())
        self.assertIn('"schemaVersion": 2', disk.read_text(encoding="utf-8"))

    def test_template_catalog_reports_media_slots_and_real_preview_availability(self):
        response = self.client.get("/api/v1/video/templates", headers=self.headers)
        self.assertEqual(200, response.status_code, response.text)
        templates = response.json()["templates"]
        self.assertEqual(8, len(templates))
        template_ids = [item["templateId"] for item in templates]
        self.assertEqual(len(template_ids), len(set(template_ids)))
        self.assertTrue(all(item["previewAvailable"] is False for item in templates
                            if item["templateId"] != "fall-diary"))
        fall_diary = next(item for item in templates if item["templateId"] == "fall-diary")
        self.assertEqual("PILOT_RENDERABLE", fall_diary["availabilityStatus"])
        self.assertEqual("180:389", fall_diary["aspectRatio"])
        self.assertEqual(1, fall_diary["requiredMediaSlots"])
        self.assertEqual(17200, fall_diary["durationMs"])
        self.assertEqual("0.9.0-reference-overlays", fall_diary["templateDefinitionVersion"])
        self.assertIsNone(fall_diary["posterPath"])
        self.assertIsNone(fall_diary["previewSource"])

    def test_legacy_shape_put_is_refused_without_mutating_project(self):
        response = self.client.post("/api/v1/video/projects/blank", json={"title": "No downgrade"},
                                    headers=self.headers)
        project_id = response.json()["projectId"]
        before = (Path(self.temporary.name) / "video_editor" / "projects" / f"{project_id}.json").read_bytes()
        legacy = {"projectId": project_id, "templateId": "free-editor", "title": "bad", "clips": [],
                  "textLayers": [], "audioTracks": []}
        rejected = self.client.put(f"/api/v1/video/projects/{project_id}", json=legacy, headers=self.headers)
        self.assertEqual(422, rejected.status_code)
        after = (Path(self.temporary.name) / "video_editor" / "projects" / f"{project_id}.json").read_bytes()
        self.assertEqual(before, after)

    def test_stale_project_revision_is_rejected_without_overwriting_newer_save(self):
        created = self.client.post("/api/v1/video/projects/blank", json={"title": "Revision"},
                                   headers=self.headers)
        old_payload = created.json()
        project_id = old_payload["projectId"]
        old_payload["title"] = "Newer save"
        newer = self.client.put(f"/api/v1/video/projects/{project_id}", json=old_payload,
                                headers=self.headers)
        self.assertEqual(200, newer.status_code, newer.text)

        stale_payload = created.json()
        stale_payload["title"] = "Stale overwrite"
        rejected = self.client.put(f"/api/v1/video/projects/{project_id}", json=stale_payload,
                                   headers=self.headers)

        self.assertEqual(409, rejected.status_code, rejected.text)
        reopened = self.client.get(f"/api/v1/video/projects/{project_id}", headers=self.headers)
        self.assertEqual("Newer save", reopened.json()["title"])
        self.assertEqual(newer.json()["revision"], reopened.json()["revision"])

    def test_render_endpoint_accepts_layout_validation_then_rejects_placeholders(self):
        created = self.client.post("/api/v1/video/projects/blank", json={"title": "Guard"},
                                   headers=self.headers)
        project = created.json()
        track_ids = ["1" * 32, "2" * 32]
        clips = []
        tracks = []
        for index, track_id in enumerate(track_ids):
            clip_id = f"{index + 3:x}" * 32
            clip = {"clipId": clip_id, "trackId": track_id, "clipKind": "video",
                    "timelineStartTicks": 0, "sourceStartTicks": 0, "durationTicks": 90_000,
                    "name": f"clip {index}", "mediaId": None, "sourceStartMs": 0,
                    "durationMs": 1000, "fitMode": "cover", "positionX": 0, "positionY": 0,
                    "scale": 1, "rotation": 0, "effect": "none", "opacity": 1,
                    "audioVolume": 1, "transition": "cut", "transitionDurationMs": 0}
            clips.append(clip)
            tracks.append({"trackId": track_id, "kind": "visual", "layerOrder": index,
                           "displayName": f"V{index + 1}",
                           "state": {"visible": True, "locked": False, "muted": False, "solo": False},
                           "clips": [{"clipId": clip_id, "trackId": track_id, "clipKind": "video",
                                      "timelineStartTicks": 0, "sourceStartTicks": 0,
                                      "durationTicks": 90_000, "mediaId": None,
                                      "properties": {}, "templateMetadata": {}}]})
        project["tracks"] = tracks
        project["clips"] = clips
        saved = self.client.put(f"/api/v1/video/projects/{project['projectId']}", json=project,
                                headers=self.headers)
        self.assertEqual(200, saved.status_code, saved.text)

        response = self.client.post(f"/api/v1/video/projects/{project['projectId']}/render-jobs",
                                    json={}, headers=self.headers)
        self.assertEqual(422, response.status_code, response.text)
        self.assertIn("placeholder", response.text.lower())


if __name__ == "__main__":
    unittest.main()
