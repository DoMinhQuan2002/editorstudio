#!/usr/bin/env python3
"""Read-only project/media inventory and before/after comparison for WPF acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def camel(mapping: dict[str, Any], name: str, default: Any = None) -> Any:
    if name in mapping:
        return mapping[name]
    snake = []
    for char in name:
        if char.isupper():
            snake.extend(("_", char.lower()))
        else:
            snake.append(char)
    return mapping.get("".join(snake), default)


def project_summary(path: Path, raw: bytes, media_ids: set[str]) -> dict[str, Any]:
    data = json.loads(raw.decode("utf-8"))
    clips = camel(data, "clips", []) or []
    audio = camel(data, "audioTracks", []) or []
    seen_clip_ids: set[str] = set()
    duplicate_clip_ids: list[str] = []
    video_clips: list[dict[str, Any]] = []
    visual_cursor = 0
    missing_bindings: list[str] = []
    placeholder_clip_ids: list[str] = []
    for clip in clips:
        clip_id = str(camel(clip, "clipId", ""))
        if clip_id in seen_clip_ids:
            duplicate_clip_ids.append(clip_id)
        seen_clip_ids.add(clip_id)
        media_id = camel(clip, "mediaId")
        if not media_id:
            placeholder_clip_ids.append(clip_id)
        elif media_id not in media_ids:
            missing_bindings.append(f"clip:{clip_id}->{media_id}")
        duration = int(camel(clip, "durationMs", 0) or 0)
        video_clips.append({
            "clipId": clip_id,
            "mediaId": media_id,
            "name": camel(clip, "name"),
            "timelineStartMsDerived": visual_cursor,
            "sourceStartMs": camel(clip, "sourceStartMs", 0),
            "durationMs": duration,
        })
        visual_cursor += duration
    audio_tracks: list[dict[str, Any]] = []
    seen_audio_ids: set[str] = set()
    duplicate_audio_ids: list[str] = []
    for track in audio:
        track_id = str(camel(track, "trackId", ""))
        if track_id in seen_audio_ids:
            duplicate_audio_ids.append(track_id)
        seen_audio_ids.add(track_id)
        media_id = camel(track, "mediaId")
        if media_id and media_id not in media_ids:
            missing_bindings.append(f"audio:{track_id}->{media_id}")
        audio_tracks.append({
            "trackId": track_id,
            "mediaId": media_id,
            "timelineStartMs": camel(track, "timelineStartMs", 0),
            "sourceStartMs": camel(track, "sourceStartMs", 0),
            "durationMs": camel(track, "durationMs", 0),
            "volume": camel(track, "volume", 1.0),
        })
    return {
        "projectId": camel(data, "projectId"),
        "title": camel(data, "title"),
        "templateId": camel(data, "templateId"),
        "revision": camel(data, "revision"),
        "width": camel(data, "width"),
        "height": camel(data, "height"),
        "fps": camel(data, "fps"),
        "projectJsonPath": str(path),
        "projectJsonSha256": hashlib.sha256(raw).hexdigest(),
        "clipCount": len(video_clips),
        "placeholderClipIds": placeholder_clip_ids,
        "videoDurationMsDerived": visual_cursor,
        "clips": video_clips,
        "audioTrackCount": len(audio_tracks),
        "audioTracks": audio_tracks,
        "textLayerCount": len(camel(data, "textLayers", []) or []),
        "duplicateClipIds": duplicate_clip_ids,
        "duplicateAudioTrackIds": duplicate_audio_ids,
        "mediaBindingsMissingMetadata": missing_bindings,
    }


def scan(data_directory: Path, project_id: str | None) -> dict[str, Any]:
    video_root = data_directory / "video_editor"
    projects_dir = video_root / "projects"
    media_dir = video_root / "media"
    metadata: dict[str, dict[str, Any]] = {}
    for path in sorted(media_dir.glob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            metadata[str(camel(item, "assetId", ""))] = {
                "kind": camel(item, "kind"),
                "fileName": camel(item, "fileName"),
                "durationMs": camel(item, "durationMs"),
                "width": camel(item, "width"),
                "height": camel(item, "height"),
                "videoCodec": camel(item, "videoCodec"),
                "audioCodec": camel(item, "audioCodec"),
            }
        except (OSError, json.JSONDecodeError):
            continue
    projects: list[dict[str, Any]] = []
    invalid_projects: list[dict[str, str]] = []
    for path in sorted(projects_dir.glob("*.json")):
        try:
            raw = path.read_bytes()
            summary = project_summary(path, raw, set(metadata))
            if project_id and summary["projectId"] != project_id:
                continue
            projects.append(summary)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            invalid_projects.append({"path": str(path), "error": str(error)})
    counts: dict[str, int] = {}
    for item in metadata.values():
        kind = str(item.get("kind") or "unknown")
        counts[kind] = counts.get(kind, 0) + 1
    return {
        "dataDirectory": str(data_directory),
        "projectCount": len(projects),
        "mediaMetadataCount": len(metadata),
        "mediaCountsByKind": counts,
        "media": [{"mediaId": key, **value} for key, value in sorted(metadata.items())],
        "projects": projects,
        "invalidProjectJson": invalid_projects,
        "sourceProjectJsonWasNotModified": True,
    }


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    old = {item.get("projectId"): item for item in before.get("projects", [])}
    new = {item.get("projectId"): item for item in after.get("projects", [])}
    changes = []
    for project_id in sorted(set(old) | set(new)):
        previous = old.get(project_id)
        current = new.get(project_id)
        if previous is None:
            changes.append({"projectId": project_id, "change": "new_project", "newRevision": current.get("revision")})
            continue
        if current is None:
            changes.append({"projectId": project_id, "change": "project_absent_after"})
            continue
        old_clips = {clip.get("clipId"): clip for clip in previous.get("clips", [])}
        new_clips = {clip.get("clipId"): clip for clip in current.get("clips", [])}
        changed_bindings = []
        for clip_id in sorted(set(old_clips) | set(new_clips)):
            old_clip, new_clip = old_clips.get(clip_id), new_clips.get(clip_id)
            if old_clip is None:
                changed_bindings.append({"clipId": clip_id, "change": "clip_added", "newMediaId": new_clip.get("mediaId")})
            elif new_clip is None:
                changed_bindings.append({"clipId": clip_id, "change": "clip_removed", "oldMediaId": old_clip.get("mediaId")})
            elif old_clip.get("mediaId") != new_clip.get("mediaId"):
                changed_bindings.append({"clipId": clip_id, "change": "media_binding_changed", "oldMediaId": old_clip.get("mediaId"), "newMediaId": new_clip.get("mediaId")})
        changes.append({
            "projectId": project_id,
            "change": "changed" if previous.get("projectJsonSha256") != current.get("projectJsonSha256") else "unchanged",
            "oldRevision": previous.get("revision"),
            "newRevision": current.get("revision"),
            "clipBindingChanges": changed_bindings,
            "audioTrackCountBefore": previous.get("audioTrackCount"),
            "audioTrackCountAfter": current.get("audioTrackCount"),
        })
    return {"projectChanges": changes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-directory", required=True, type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--baseline", type=Path, help="Prior summary JSON, not a project file")
    parser.add_argument("--snapshot-out", type=Path, help="Write summary JSON outside the project data directory")
    args = parser.parse_args()
    if not args.data_directory.is_dir():
        parser.error(f"Data directory not found: {args.data_directory}")
    summary = scan(args.data_directory, args.project_id)
    if args.baseline:
        try:
            prior = json.loads(args.baseline.read_text(encoding="utf-8-sig"))
            summary["comparison"] = compare(prior, summary)
        except (OSError, json.JSONDecodeError) as error:
            parser.error(f"Could not read baseline summary: {error}")
    if args.snapshot_out:
        args.snapshot_out.parent.mkdir(parents=True, exist_ok=True)
        args.snapshot_out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
