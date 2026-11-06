from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from mediastudio.video_editor.ffmpeg import FFmpegToolchain


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pick(row: dict[str, Any], camel: str, snake: str, default: Any = None) -> Any:
    return row.get(camel, row.get(snake, default))


def summarize_project(project: dict[str, Any]) -> dict[str, Any]:
    tracks = []
    for track in project.get("tracks", []):
        clips = []
        for clip in track.get("clips", []):
            clips.append({
                "clipId": pick(clip, "clipId", "clip_id"),
                "trackId": pick(clip, "trackId", "track_id"),
                "clipKind": pick(clip, "clipKind", "clip_kind"),
                "mediaId": pick(clip, "mediaId", "media_id"),
                "timelineStartTicks": pick(clip, "timelineStartTicks", "timeline_start_ticks"),
                "sourceStartTicks": pick(clip, "sourceStartTicks", "source_start_ticks"),
                "durationTicks": pick(clip, "durationTicks", "duration_ticks"),
            })
        tracks.append({
            "trackId": pick(track, "trackId", "track_id"),
            "kind": track.get("kind"),
            "layerOrder": pick(track, "layerOrder", "layer_order"),
            "displayName": pick(track, "displayName", "display_name"),
            "state": track.get("state", {}),
            "clips": clips,
        })
    return {
        "projectId": pick(project, "projectId", "project_id"),
        "revision": project.get("revision"),
        "schemaVersion": pick(project, "schemaVersion", "schema_version"),
        "title": project.get("title"),
        "frameRateNumerator": pick(project, "frameRateNumerator", "frame_rate_numerator"),
        "frameRateDenominator": pick(project, "frameRateDenominator", "frame_rate_denominator"),
        "timebase": project.get("timebase"),
        "tracks": tracks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read isolated WPF TASK 2.2B evidence without editing project data.")
    parser.add_argument("--data-directory", required=True, type=Path)
    parser.add_argument("--artifact-directory", required=True, type=Path)
    parser.add_argument("--backend-log", type=Path)
    parser.add_argument("--export", type=Path)
    parser.add_argument("--phase", choices=("capture", "after"), default="capture",
                        help="Name the project snapshot. Use after only after WPF Save/Reopen.")
    args = parser.parse_args()

    data_directory = args.data_directory.resolve()
    artifact_directory = args.artifact_directory.resolve()
    manifest_path = artifact_directory / "task22b_fixture_manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"Fixture manifest not found: {manifest_path}")
    manifest = read_json(manifest_path)
    project_path = Path(manifest["projectFile"]).resolve()
    if not project_path.is_file():
        raise SystemExit(f"Isolated WPF project is missing: {project_path}")
    project = read_json(project_path)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence_directory = artifact_directory / "collected" / stamp
    evidence_directory.mkdir(parents=True, exist_ok=False)
    before_path = artifact_directory / "before.json"
    if before_path.is_file():
        (evidence_directory / "before.json").write_bytes(before_path.read_bytes())
    snapshot_name = "after.json" if args.phase == "after" else "snapshot.json"
    (evidence_directory / snapshot_name).write_text(
        json.dumps(project, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    log_path = args.backend_log.resolve() if args.backend_log else None
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path and log_path.is_file() else ""
    log_lines = log_text.splitlines()
    interesting = [line for line in log_lines if any(token in line.lower()
                  for token in ("video.project", "video.render", "traceback", "error", "exception", "failed"))]
    log_summary = {
        "path": str(log_path) if log_path else None,
        "exists": bool(log_path and log_path.is_file()),
        "lineCount": len(log_lines),
        "errorLineCount": sum(any(token in line.lower() for token in ("traceback", "error", "exception", "failed"))
                               for line in log_lines),
        "projectOrRenderEventCount": sum("video.project" in line.lower() or "video.render" in line.lower()
                                          for line in log_lines),
        "relevantTail": interesting[-80:],
    }

    export_summary = None
    export_path = args.export.resolve() if args.export else None
    if export_path is not None:
        export_summary = {"path": str(export_path), "exists": export_path.is_file()}
        if export_path.is_file():
            raw = export_path.read_bytes()
            export_summary.update({"sizeBytes": len(raw),
                                   "sha256": hashlib.sha256(raw).hexdigest(),
                                   "mp4Signature": raw[4:8] == b"ftyp"})
            ffmpeg = FFmpegToolchain()
            if ffmpeg.ffprobe:
                result = subprocess.run([ffmpeg.ffprobe, "-v", "error", "-show_format", "-show_streams",
                                         "-of", "json", str(export_path)], capture_output=True,
                                        text=True, check=False, timeout=30)
                export_summary["ffprobeExitCode"] = result.returncode
                if result.returncode == 0:
                    export_summary["probe"] = json.loads(result.stdout)
                else:
                    export_summary["ffprobeError"] = result.stderr[-4000:]
            inspect_script = BACKEND_ROOT.parent / "tools" / "video_editor" / "task2_0b" / "inspect_export.py"
            if inspect_script.is_file() and ffmpeg.ffmpeg and ffmpeg.ffprobe:
                inspect_output = evidence_directory / "inspect-export.json"
                inspected = subprocess.run(
                    [sys.executable, str(inspect_script), "--file", str(export_path),
                     "--ffmpeg", ffmpeg.ffmpeg, "--ffprobe", ffmpeg.ffprobe,
                     "--out", str(inspect_output)],
                    capture_output=True, text=True, check=False, timeout=180,
                )
                export_summary["inspectExportExitCode"] = inspected.returncode
                export_summary["inspectExportReport"] = str(inspect_output) if inspect_output.is_file() else None
                if inspected.returncode != 0:
                    export_summary["inspectExportError"] = (inspected.stderr or inspected.stdout)[-4000:]

    summary = {
        "capturedAtUtc": datetime.now(timezone.utc).isoformat(),
        "fixtureManifest": str(manifest_path),
        "isolatedDataDirectory": str(data_directory),
        "projectFile": str(project_path),
        "snapshotPhase": args.phase,
        "project": summarize_project(project),
        "backendLog": log_summary,
        "export": export_summary,
        "sourceProjectMutation": "none; source JSON and logs were opened read-only",
    }
    summary_path = evidence_directory / "log-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"evidenceDirectory": str(evidence_directory), "summary": str(summary_path),
                      "projectRevision": project.get("revision")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
