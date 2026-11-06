from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mediastudio.video_editor.api import install_video_editor_api  # noqa: E402
from mediastudio.video_editor.ffmpeg import FFmpegToolchain  # noqa: E402
from mediastudio.video_editor.project_v2 import (  # noqa: E402
    TIMEBASE, TimelineClipV2, TimelineTrackV2, VideoProjectV2, project_api_payload,
)


def run_ffmpeg(ffmpeg: str, *arguments: str) -> None:
    result = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *arguments],
                            capture_output=True, text=True, check=False, timeout=90)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "FFmpeg fixture generation failed.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an isolated TASK 2.2B WPF acceptance project.")
    parser.add_argument("--data-directory", required=True, type=Path)
    parser.add_argument("--artifact-directory", required=True, type=Path)
    args = parser.parse_args()

    data_directory = args.data_directory.resolve()
    artifact_directory = args.artifact_directory.resolve()
    if data_directory.exists() and any(data_directory.iterdir()):
        raise SystemExit(f"Refusing to write into non-empty isolated test directory: {data_directory}")
    data_directory.mkdir(parents=True, exist_ok=True)
    artifact_directory.mkdir(parents=True, exist_ok=True)

    ffmpeg = FFmpegToolchain()
    if not ffmpeg.ffmpeg:
        raise SystemExit("FFmpeg is unavailable; cannot create the WPF acceptance fixture.")
    media_directory = artifact_directory / "fixture_media"
    media_directory.mkdir(parents=True, exist_ok=True)
    base_video = media_directory / "task22b_base_with_embedded_audio.mp4"
    audio_a = media_directory / "task22b_audio_a.wav"
    audio_b = media_directory / "task22b_audio_b.wav"
    overlay = media_directory / "task22b_alpha_overlay.png"

    run_ffmpeg(ffmpeg.ffmpeg, "-f", "lavfi", "-i", "testsrc2=size=720x1280:rate=30:duration=5",
               "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=5",
               "-map", "0:v:0", "-map", "1:a:0", "-t", "5", "-c:v", "libx264",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest", str(base_video))
    run_ffmpeg(ffmpeg.ffmpeg, "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
               "-ac", "2", "-ar", "48000", str(audio_a))
    run_ffmpeg(ffmpeg.ffmpeg, "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=6",
               "-ac", "2", "-ar", "48000", str(audio_b))
    image = Image.new("RGBA", (420, 420), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((36, 36, 384, 384), radius=48, fill=(16, 210, 180, 152),
                           outline=(255, 255, 255, 235), width=10)
    draw.ellipse((132, 132, 288, 288), fill=(245, 80, 70, 220))
    image.save(overlay)

    app = FastAPI()
    app.state.token = "task22b-fixture-local-token"
    install_video_editor_api(app, data_directory)
    headers = {"X-Media-Studio-Token": app.state.token}
    imported: dict[str, dict[str, object]] = {}
    with TestClient(app) as client:
        for path in (base_video, overlay, audio_a, audio_b):
            content_type = ("video/mp4" if path.suffix == ".mp4" else
                            "image/png" if path.suffix == ".png" else "audio/wav")
            response = client.post("/api/v1/video/media",
                                   files={"file": (path.name, path.read_bytes(), content_type)},
                                   headers=headers)
            if response.status_code != 201:
                raise RuntimeError(f"Media import failed for {path.name}: {response.text}")
            metadata = response.json()
            imported[path.name] = metadata

        blank = client.post("/api/v1/video/projects/blank", json={"title": "TASK 2.2B — WPF Multitrack"},
                            headers=headers)
        if blank.status_code != 201:
            raise RuntimeError(f"Could not create blank validation project: {blank.text}")
        project_id = blank.json()["projectId"]
        store = app.state.video_projects
        seed = store.get(project_id)
        media = {name: item["assetId"] for name, item in imported.items()}
        visual_base_id, visual_overlay_id, text_track_id, audio_a_track_id, audio_b_track_id = (
            uuid4().hex for _ in range(5)
        )
        base_clip_id, overlay_clip_id, text_clip_id, audio_a_clip_id, audio_b_clip_id = (
            uuid4().hex for _ in range(5)
        )
        visual_properties = {
            "fitMode": "cover", "positionX": 0.0, "positionY": 0.0, "scale": 1.0,
            "rotation": 0.0, "effect": "none", "opacity": 1.0, "audioVolume": 0.35,
            "transition": "cut", "transitionDurationMs": 0,
        }
        tracks = [
            TimelineTrackV2(track_id=visual_base_id, kind="visual", layer_order=0, display_name="Video 1",
                            clips=[TimelineClipV2(clip_id=base_clip_id, track_id=visual_base_id,
                                clip_kind="video", timeline_start_ticks=0, source_start_ticks=0,
                                duration_ticks=5 * TIMEBASE, media_id=media[base_video.name],
                                properties={**visual_properties, "name": "Base with embedded audio"})]),
            TimelineTrackV2(track_id=visual_overlay_id, kind="visual", layer_order=1, display_name="Video 2 · Overlay",
                            clips=[TimelineClipV2(clip_id=overlay_clip_id, track_id=visual_overlay_id,
                                clip_kind="image", timeline_start_ticks=TIMEBASE, source_start_ticks=0,
                                duration_ticks=3_500 * 90, media_id=media[overlay.name],
                                properties={**visual_properties, "name": "PNG alpha overlay", "fitMode": "contain",
                                            "audioVolume": 0.0})]),
            TimelineTrackV2(track_id=text_track_id, kind="text", layer_order=2, display_name="Text 1",
                            clips=[TimelineClipV2(clip_id=text_clip_id, track_id=text_track_id,
                                clip_kind="text", timeline_start_ticks=2 * TIMEBASE, source_start_ticks=0,
                                duration_ticks=2_500 * 90, media_id=None,
                                properties={"text": "TASK 2.2B", "x": 0.5, "y": 0.2,
                                            "fontSize": 58, "color": "#FFFFFF", "fontFamily": "Arial",
                                            "opacity": 1.0})]),
            TimelineTrackV2(track_id=audio_a_track_id, kind="audio", layer_order=3, display_name="Audio 1",
                            clips=[TimelineClipV2(clip_id=audio_a_clip_id, track_id=audio_a_track_id,
                                clip_kind="audio", timeline_start_ticks=0, source_start_ticks=0,
                                duration_ticks=4 * TIMEBASE, media_id=media[audio_a.name],
                                properties={"mediaId": media[audio_a.name], "volume": 0.35,
                                            "fadeInMs": 300, "fadeOutMs": 400})]),
            TimelineTrackV2(track_id=audio_b_track_id, kind="audio", layer_order=4, display_name="Audio 2",
                            clips=[TimelineClipV2(clip_id=audio_b_clip_id, track_id=audio_b_track_id,
                                clip_kind="audio", timeline_start_ticks=2 * TIMEBASE, source_start_ticks=0,
                                duration_ticks=6 * TIMEBASE, media_id=media[audio_b.name],
                                properties={"mediaId": media[audio_b.name], "volume": 0.3,
                                            "fadeInMs": 500, "fadeOutMs": 800})]),
        ]
        project = VideoProjectV2(
            schema_version=2, project_id=seed.project_id, template_id="task22b-validation",
            title="TASK 2.2B — WPF Multitrack", width=720, height=1280,
            frame_rate_numerator=30, frame_rate_denominator=1, timebase=TIMEBASE,
            tracks=tracks, created_at=seed.created_at, updated_at=seed.updated_at, revision=seed.revision,
        )
        save_response = client.put(f"/api/v1/video/projects/{project_id}",
                                   json=project_api_payload(project), headers=headers)
        if save_response.status_code != 200:
            raise RuntimeError(f"Could not persist multitrack validation project: {save_response.text}")
        saved = save_response.json()

    fixture_manifest = {
        "task": "TASK 2.2B",
        "projectId": project_id,
        "revision": saved["revision"],
        "projectFile": str(data_directory / "video_editor" / "projects" / f"{project_id}.json"),
        "tracks": [
            {"trackId": visual_base_id, "kind": "visual", "layerOrder": 0, "clipId": base_clip_id,
             "timelineStartTicks": 0, "durationTicks": 5 * TIMEBASE, "media": base_video.name},
            {"trackId": visual_overlay_id, "kind": "visual", "layerOrder": 1, "clipId": overlay_clip_id,
             "timelineStartTicks": TIMEBASE, "durationTicks": 3_500 * 90, "media": overlay.name},
            {"trackId": text_track_id, "kind": "text", "layerOrder": 2, "clipId": text_clip_id,
             "timelineStartTicks": 2 * TIMEBASE, "durationTicks": 2_500 * 90, "text": "TASK 2.2B"},
            {"trackId": audio_a_track_id, "kind": "audio", "layerOrder": 3, "clipId": audio_a_clip_id,
             "timelineStartTicks": 0, "durationTicks": 4 * TIMEBASE, "media": audio_a.name},
            {"trackId": audio_b_track_id, "kind": "audio", "layerOrder": 4, "clipId": audio_b_clip_id,
             "timelineStartTicks": 2 * TIMEBASE, "durationTicks": 6 * TIMEBASE, "media": audio_b.name},
        ],
        "visualDurationTicks": 5 * TIMEBASE,
        "audioTimelineEndTicks": 8 * TIMEBASE,
        "media": imported,
        "notes": ["Two visual layers; PNG alpha; timed text; two overlapping audio tracks.",
                  "Audio timeline ends 3 seconds after visual timeline.",
                  "The base video also contains embedded audio.",
                  "All data is stored under the supplied isolated test directory."],
    }
    manifest_path = artifact_directory / "task22b_fixture_manifest.json"
    before_path = artifact_directory / "before.json"
    manifest_path.write_text(json.dumps(fixture_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    before_path.write_text(json.dumps(saved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    marker_path = data_directory / "task22b_fixture_manifest.json"
    marker_path.write_text(json.dumps(fixture_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"projectId": project_id, "revision": saved["revision"],
                      "manifest": str(manifest_path), "before": str(before_path),
                      "isolatedDataDirectory": str(data_directory)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
