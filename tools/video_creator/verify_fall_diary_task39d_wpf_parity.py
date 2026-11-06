"""Render and compare an exact WPF-generated Fall Diary Project V2 revision.

The preview input is copied from Media Studio's local draft preview cache. This
script reads the matching Project V2 candidate and media from the isolated
Task 3.9C QA runtime, rebuilds the shared Composition Graph, and exports a
same-revision comparison render. It does not write to the runtime project store
or modify source images.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from mediastudio.video_editor.composition import build_composition_graph  # noqa: E402
from mediastudio.video_editor.composition_renderer import render_composition_project  # noqa: E402
from mediastudio.video_editor.ffmpeg import FFmpegToolchain  # noqa: E402
from mediastudio.video_editor.jobs import VideoJob  # noqa: E402
from mediastudio.video_editor.project_v2 import VideoProjectV2  # noqa: E402
from mediastudio.video_editor.storage import VideoMediaStore  # noqa: E402


TASK = REPO / "artifacts" / "video_creator" / "task3_9d"
RUNTIME = REPO / "artifacts" / "video_creator" / "task3_9c" / "runtime_workspace" / "video_editor"
PROJECT_PATH = TASK / "Fall_Diary_Reference_Pilot_Project_V2.json"
PREVIEW_PATH = TASK / "Fall_Diary_Reference_Pilot_Preview.mp4"
EXPORT_PATH = TASK / "Fall_Diary_Reference_Pilot_Render.mp4"
GRAPH_PATH = TASK / "Fall_Diary_Reference_Pilot_Composition_Graph.json"
MANIFEST_PATH = TASK / "Fall_Diary_Reference_Pilot_Manifest.json"
FRAME_DIR = TASK / "qa" / "wpf_parity_frames"
STAGING = TASK / "qa" / "wpf_parity_staging"


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False)


def probe(path: Path, ffprobe: str) -> dict[str, object]:
    result = run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    if result.returncode:
        raise RuntimeError(f"FFprobe failed for {path}: {result.stderr[-1000:]}")
    data = json.loads(result.stdout)
    video = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), None)
    if video is None:
        raise RuntimeError(f"No video stream in {path}.")
    return {"format": data.get("format", {}), "video": video,
            "audioStreamCount": sum(stream.get("codec_type") == "audio" for stream in data.get("streams", []))}


def full_decode(path: Path, ffmpeg: str) -> dict[str, object]:
    result = run([ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"])
    return {"valid": result.returncode == 0 and not result.stderr.strip(),
            "exitCode": result.returncode, "stderr": result.stderr[-1200:]}


def extract_frame(path: Path, ffmpeg: str, frame_index: int, destination: Path) -> None:
    result = run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path),
                  "-vf", f"select='eq(n,{frame_index})'", "-fps_mode", "passthrough",
                  "-frames:v", "1", "-y", str(destination)])
    if result.returncode or not destination.is_file():
        raise RuntimeError(f"Could not extract frame {frame_index} from {path.name}: {result.stderr[-1000:]}")


def mean_rgb_error(first: Image.Image, second: Image.Image) -> float:
    return sum(ImageStat.Stat(ImageChops.difference(first.convert("RGB"), second.convert("RGB"))).mean) / 3


def compare_all_frames_ssim(ffmpeg: str) -> dict[str, object]:
    stats_path = TASK / "qa" / "wpf_full_ssim_510_frames.txt"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_relative = stats_path.relative_to(TASK).as_posix()
    command = [ffmpeg, "-v", "error", "-i", str(PREVIEW_PATH), "-i", str(EXPORT_PATH),
               "-filter_complex", "[0:v]format=yuv420p[p];"
                                  "[1:v]scale=540:960:flags=lanczos,format=yuv420p[e];"
                                  f"[p][e]ssim=stats_file={stats_relative}[s]",
               "-map", "[s]", "-f", "null", "-"]
    result = subprocess.run(command, cwd=TASK, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
    if result.returncode:
        raise RuntimeError(f"All-frame SSIM failed: {result.stderr[-1000:]}")
    lines = stats_path.read_text(encoding="utf-8").splitlines()
    values: list[float] = []
    for line in lines:
        token = next((part for part in line.split() if part.startswith("All:")), None)
        if token:
            try:
                values.append(float(token.split(":", 1)[1]))
            except ValueError:
                pass
    if len(values) != 510:
        raise RuntimeError(f"Expected 510 aligned SSIM frames, got {len(values)}.")
    return {"framesCompared": len(values), "meanSsim": round(sum(values) / len(values), 8),
            "minSsim": round(min(values), 8), "statsFile": str(stats_path.relative_to(REPO))}


def contact_sheet(rows: list[dict[str, object]], output: Path) -> None:
    sample_w, sample_h, columns = 360, 240, 4
    sheet = Image.new("RGB", (sample_w * columns, sample_h * ((len(rows) + columns - 1) // columns)), "#e9edf4")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 14)
    small = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 11)
    for i, row in enumerate(rows):
        x = (i % columns) * sample_w
        y = (i // columns) * sample_h
        draw.text((x + 4, y + 3), f"frame {row['frameIndex']} · t={row['timeSeconds']:.3f}s", fill="#15233a", font=font)
        preview = Image.open(FRAME_DIR / str(row["previewFrame"])).convert("RGB").resize((108, 192), Image.Resampling.LANCZOS)
        rendered = Image.open(FRAME_DIR / str(row["renderFrame"])).convert("RGB").resize((108, 192), Image.Resampling.LANCZOS)
        difference = Image.open(FRAME_DIR / str(row["differenceFrame"])).convert("RGB").resize((108, 192), Image.Resampling.LANCZOS)
        for j, (label, tile) in enumerate((("WPF preview", preview), ("shared export", rendered), ("abs diff ×4", difference))):
            tile_x = x + 5 + j * 117
            draw.text((tile_x, y + 23), label, fill="#45536a", font=small)
            sheet.paste(tile, (tile_x, y + 41))
    sheet.save(output, quality=94)


def main() -> int:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg/FFprobe are required for the parity verification.")
    if not PROJECT_PATH.is_file() or not PREVIEW_PATH.is_file():
        raise RuntimeError("The WPF revision 2 project candidate and preview MP4 must both exist.")

    project_bytes = PROJECT_PATH.read_bytes()
    project = VideoProjectV2.model_validate_json(project_bytes)
    metadata = project.template_metadata or {}
    if (project.project_id != "73da1503e49b403f9ad5c56f7d4d688c" or project.revision != 2
            or metadata.get("templateId") != "fall-diary"
            or metadata.get("templateDefinitionVersion") != "0.3.0-reference-pilot"):
        raise RuntimeError("Unexpected project ID/revision/template version in WPF candidate.")

    ffmpeg_toolchain = FFmpegToolchain()
    store = VideoMediaStore(RUNTIME, ffmpeg_toolchain)
    bindings = dict(metadata.get("templateBindings", {}))
    if len(bindings) != 11 or set(bindings) != {f"photo-{i:02d}" for i in range(1, 12)}:
        raise RuntimeError("The project does not carry all 11 declared 0.3 slot bindings.")
    if len(set(bindings.values())) != 11:
        raise RuntimeError("The project bindings do not meet the 0.3 unique-fixture QA setup.")

    source_paths = {media_id: store.get_path(media_id) for media_id in bindings.values()}
    source_sha_before = {media_id: hashlib.sha256(path.read_bytes()).hexdigest()
                         for media_id, path in source_paths.items()}
    graph = build_composition_graph(project, store.get_metadata)
    graph_dict = graph.to_dict()
    GRAPH_PATH.write_text(json.dumps(graph_dict, ensure_ascii=False, indent=2), encoding="utf-8")

    STAGING.mkdir(parents=True, exist_ok=True)
    job = VideoJob(job_id=uuid4().hex, project_id=project.project_id,
                   job_type="task3.9d-shared-render-parity")
    render_composition_project(job, graph, store, ffmpeg, STAGING, "high")
    if job.output_path is None or not job.output_path.is_file():
        raise RuntimeError(f"Composition Graph render failed: {job.error}")
    EXPORT_PATH.unlink(missing_ok=True)
    job.output_path.replace(EXPORT_PATH)

    preview_info, render_info = probe(PREVIEW_PATH, ffprobe), probe(EXPORT_PATH, ffprobe)
    preview_decode, render_decode = full_decode(PREVIEW_PATH, ffmpeg), full_decode(EXPORT_PATH, ffmpeg)
    if not preview_decode["valid"] or not render_decode["valid"]:
        raise RuntimeError("Preview or render failed full decode.")
    if preview_info["video"].get("width") != 540 or preview_info["video"].get("height") != 960:
        raise RuntimeError("WPF preview did not use the expected 540x960 proxy canvas.")
    if render_info["video"].get("width") != graph.width or render_info["video"].get("height") != graph.height:
        raise RuntimeError("Render output canvas does not match the Composition Graph.")
    if preview_info["video"].get("r_frame_rate") != graph.fps or render_info["video"].get("r_frame_rate") != graph.fps:
        raise RuntimeError("Preview/render frame rate does not match the Composition Graph.")

    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    selected_frames = [0, 30, 112, 157, 173, 203, 278, 293, 307, 397, 413, 452, 509]
    rows: list[dict[str, object]] = []
    for frame_index in selected_frames:
        ticks = graph.frame_start_ticks(frame_index)
        preview_frame = FRAME_DIR / f"preview_{frame_index:04d}.png"
        render_frame = FRAME_DIR / f"render_{frame_index:04d}.png"
        difference_frame = FRAME_DIR / f"diff_{frame_index:04d}.png"
        extract_frame(PREVIEW_PATH, ffmpeg, frame_index, preview_frame)
        extract_frame(EXPORT_PATH, ffmpeg, frame_index, render_frame)
        with Image.open(preview_frame) as preview_original, Image.open(render_frame) as render_original:
            preview = preview_original.convert("RGB")
            rendered = render_original.convert("RGB").resize(preview.size, Image.Resampling.LANCZOS)
            error = mean_rgb_error(preview, rendered)
            diff = ImageChops.difference(preview, rendered).point(lambda value: min(255, value * 4))
            diff.save(difference_frame)
        rows.append({"frameIndex": frame_index, "timeSeconds": ticks / graph.timebase,
                     "timeTicks": ticks, "meanAbsoluteErrorRgb": round(error, 5),
                     "previewFrame": preview_frame.name, "renderFrame": render_frame.name,
                     "differenceFrame": difference_frame.name})
    all_frame_ssim = compare_all_frames_ssim(ffmpeg)

    comparisons = {
        "projectId": graph.project_id, "projectRevision": graph.project_revision,
        "templateId": metadata["templateId"],
        "templateDefinitionVersion": metadata["templateDefinitionVersion"],
        "slotBindingSha256": hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest(),
        "compositionSourceFingerprint": graph.source_fingerprint,
        "projectTimebase": graph.timebase, "durationTicks": graph.duration_ticks,
        "durationSeconds": graph.duration_ticks / graph.timebase, "frameRate": graph.fps,
        "preview": {"path": str(PREVIEW_PATH.relative_to(REPO)), "probe": preview_info, "fullDecode": preview_decode},
        "render": {"path": str(EXPORT_PATH.relative_to(REPO)), "probe": render_info, "fullDecode": render_decode},
        "comparisonMethod": "Exact same frame indices; 1080x1920 shared Composition Graph render downscaled to WPF preview 540x960 with Lanczos.",
        "framesCompared": len(rows),
        "meanAbsoluteErrorRgb": round(sum(float(row["meanAbsoluteErrorRgb"]) for row in rows) / len(rows), 5),
        "maxMeanAbsoluteErrorRgb": max(float(row["meanAbsoluteErrorRgb"]) for row in rows),
        "allFrameSsim": all_frame_ssim,
        "threshold": {"meanRgbMaeMax": 12, "perFrameRgbMaeMax": 24},
        "passedFrameThreshold": (sum(float(row["meanAbsoluteErrorRgb"]) for row in rows) / len(rows) <= 12
                                 and max(float(row["meanAbsoluteErrorRgb"]) for row in rows) <= 24),
        "samples": rows,
        "sourceFixtureHashesBefore": source_sha_before,
        "sourceFixtureHashesAfter": {media_id: hashlib.sha256(path.read_bytes()).hexdigest()
                                      for media_id, path in source_paths.items()},
        "sourceFixtureFilesUnmodified": source_sha_before == {
            media_id: hashlib.sha256(path.read_bytes()).hexdigest() for media_id, path in source_paths.items()},
        "uiExportScreenVerified": False,
        "notes": ["WPF created the revision 2 draft preview; the final export file was rendered from the exact copied Project V2 and shared graph.",
                  "Screen 6 export interaction was not completed in-app, so six-screen GUI acceptance remains pending.",
                  "Encoder/resolution differences are expected; comparison checks framing and composition at identical frame indices."],
    }
    contact = TASK / "Fall_Diary_WPF_Preview_Export_Comparison.jpg"
    contact_sheet(rows, contact)

    baseline_source = REPO / "artifacts" / "video_creator" / "task3_9c" / "Fall_Diary_Reference_Pilot_Project_V2.json"
    runtime_baseline = RUNTIME / "projects" / "73da1503e49b403f9ad5c56f7d4d688c.json"
    baseline_restored = (hashlib.sha256(baseline_source.read_bytes()).hexdigest()
                         == hashlib.sha256(runtime_baseline.read_bytes()).hexdigest())
    manifest = {
        "task": "3.9D", "projectId": project.project_id, "projectRevision": project.revision,
        "templateId": metadata["templateId"], "templateDefinitionVersion": metadata["templateDefinitionVersion"],
        "compositionGraphFingerprint": graph.source_fingerprint,
        "slotCount": len(bindings), "slotBindingSha256": comparisons["slotBindingSha256"],
        "durationTicks": graph.duration_ticks, "timebase": graph.timebase, "frameRate": graph.fps,
        "canvas": {"width": graph.width, "height": graph.height},
        "previewWasGeneratedByWpf": True, "exportWasGeneratedByInAppScreen": False,
        "previewRenderParity": comparisons,
        "previousTask39cBaselineProjectRestoredByteExact": baseline_restored,
        "cutoutVerified": False, "audioFidelityVerified": False,
        "referenceFidelityVerified": False, "sixScreenGuiVerified": False,
        "readyForUsers": False,
        "outputs": {"preview": str(PREVIEW_PATH.relative_to(REPO)), "render": str(EXPORT_PATH.relative_to(REPO)),
                    "projectV2": str(PROJECT_PATH.relative_to(REPO)), "compositionGraph": str(GRAPH_PATH.relative_to(REPO)),
                    "contactSheet": str(contact.relative_to(REPO))},
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"projectId": graph.project_id, "revision": graph.project_revision,
                      "compositionFingerprint": graph.source_fingerprint,
                      "meanRgbMae": comparisons["meanAbsoluteErrorRgb"],
                      "maxRgbMae": comparisons["maxMeanAbsoluteErrorRgb"],
                      "previewDecode": preview_decode, "renderDecode": render_decode,
                      "sourceMediaUnmodified": comparisons["sourceFixtureFilesUnmodified"],
                      "baselineRestoredByteExact": baseline_restored,
                      "preview": str(PREVIEW_PATH), "render": str(EXPORT_PATH), "contact": str(contact)},
                     ensure_ascii=False, indent=2))
    return 0 if (comparisons["passedFrameThreshold"] and comparisons["sourceFixtureFilesUnmodified"]
                 and baseline_restored) else 2


if __name__ == "__main__":
    raise SystemExit(main())
