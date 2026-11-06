"""Compile and render the versioned Fall Diary 0.3 pilot through the shared engine.

Private fixture images are read in place. This harness does not touch the WPF
user-project store and does not copy fixture images into the reusable template.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from uuid import uuid5, NAMESPACE_URL, uuid4

from PIL import Image, ImageChops, ImageStat

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from mediastudio.video_editor.composition import build_composition_graph  # noqa: E402
from mediastudio.video_editor.composition_renderer import (  # noqa: E402
    render_composition_project,
    render_preview_frame_png,
)
from mediastudio.video_editor.jobs import VideoJob  # noqa: E402
from mediastudio.video_editor.media_selection import get_template_definition  # noqa: E402
from mediastudio.video_editor.template_compiler import compile_template  # noqa: E402


class FixtureStore:
    def __init__(self, paths: dict[str, Path]) -> None:
        self.paths = paths
        self.metadata = {
            asset_id: SimpleNamespace(asset_id=asset_id, kind="image", duration_ms=None, audio_codec=None)
            for asset_id in paths
        }

    def get_metadata(self, asset_id: str):
        return self.metadata[asset_id]

    def get_path(self, asset_id: str) -> Path:
        return self.paths[asset_id]


def _asset_id(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()[:32]


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False)


def _probe(path: Path, ffprobe: str) -> dict[str, object]:
    result = _run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    if result.returncode:
        return {"valid": False, "exitCode": result.returncode, "stderr": result.stderr[-2000:]}
    probe = json.loads(result.stdout)
    streams = probe.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    return {"valid": video is not None, "format": probe.get("format", {}),
            "video": video, "audioStreamCount": sum(stream.get("codec_type") == "audio" for stream in streams)}


def _decode(path: Path, ffmpeg: str) -> dict[str, object]:
    result = _run([ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"])
    return {"valid": result.returncode == 0 and not result.stderr.strip(),
            "exitCode": result.returncode, "stderr": result.stderr[-2000:]}


def _render(graph, store: FixtureStore, ffmpeg: str, staging: Path, quality: str) -> Path:
    job = VideoJob(job_id=uuid4().hex, project_id=graph.project_id, job_type="fall-diary-0.3-reference-pilot")
    render_composition_project(job, graph, store, ffmpeg, staging, quality)
    if job.output_path is None or not job.output_path.is_file():
        raise RuntimeError(f"Shared Composition Graph render failed: {job.error}")
    return job.output_path


def _extract_video_frame(path: Path, ffmpeg: str, frame_index: int, destination: Path) -> None:
    result = _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path),
                   "-vf", f"select='eq(n,{frame_index})'", "-fps_mode", "passthrough",
                   "-frames:v", "1", "-y", str(destination)])
    if result.returncode or not destination.is_file():
        raise RuntimeError(f"Could not extract {path.name} frame {frame_index}: {result.stderr[-1000:]}")


def _still_parity(graph, store: FixtureStore, ffmpeg: str, export_path: Path,
                  frame_dir: Path, timestamps: list[float]) -> dict[str, object]:
    rows = []
    for seconds in timestamps:
        ticks = round(seconds * graph.timebase)
        frame_index = graph.frame_index_at(ticks)
        preview_path = frame_dir / f"preview_{seconds:06.3f}.png"
        preview_path.write_bytes(render_preview_frame_png(graph, store, ffmpeg, ticks))
        export_frame = frame_dir / f"export_{seconds:06.3f}.png"
        _extract_video_frame(export_path, ffmpeg, frame_index, export_frame)
        with Image.open(preview_path) as preview, Image.open(export_frame) as rendered:
            first, second = preview.convert("RGB"), rendered.convert("RGB")
            if first.size != second.size:
                raise RuntimeError(f"Preview/export frame dimensions differ at {seconds:.3f}s.")
            channels = ImageStat.Stat(ImageChops.difference(first, second)).mean
        rows.append({"timeSeconds": seconds, "timeTicks": ticks, "frameIndex": frame_index,
                     "meanAbsoluteErrorRgb": round(sum(channels) / 3, 5),
                     "previewFrame": preview_path.name, "exportFrame": export_frame.name})
    mean_error = sum(float(row["meanAbsoluteErrorRgb"]) for row in rows) / len(rows)
    return {"method": "same 1080x1920 still-preview renderer vs exact frame index from H.264 export",
            "framesCompared": len(rows), "meanAbsoluteErrorRgb": round(mean_error, 5),
            "maxMeanAbsoluteErrorRgb": max(float(row["meanAbsoluteErrorRgb"]) for row in rows),
            "passedThreshold": mean_error <= 12 and max(float(row["meanAbsoluteErrorRgb"]) for row in rows) <= 24,
            "samples": rows}


def _ssim(preview_path: Path, export_path: Path, ffmpeg: str, output_dir: Path) -> dict[str, object]:
    stats_path = output_dir / "preview_export_ssim_0_3.txt"
    stats_path.unlink(missing_ok=True)
    result = _run([
        ffmpeg, "-v", "error", "-i", str(preview_path), "-i", str(export_path),
        "-filter_complex", "[0:v]format=yuv420p[p];[1:v]scale=540:960:flags=lanczos,format=yuv420p[e];"
                           f"[p][e]ssim=stats_file={stats_path.name}[s]",
        "-map", "[s]", "-f", "null", "-",
    ], cwd=output_dir)
    lines = stats_path.read_text(encoding="utf-8").splitlines() if stats_path.is_file() else []
    values = []
    for line in lines:
        token = next((part for part in line.split() if part.startswith("All:")), None)
        if token:
            try:
                values.append(float(token.split(":", 1)[1]))
            except ValueError:
                pass
    return {"valid": result.returncode == 0 and bool(values), "exitCode": result.returncode,
            "framesCompared": len(lines), "meanSsim": sum(values) / len(values) if values else None,
            "minSsim": min(values) if values else None, "stderr": result.stderr[-1000:]}


def _frame_comparison(graph, store: FixtureStore, ffmpeg: str, preview_path: Path,
                      render_9a: Path, render_9b: Path, reference_dir: Path,
                      output_dir: Path) -> list[dict[str, object]]:
    # Times straddle visible reference changes and are chosen for side-by-side review only.
    timestamps = [0.5, 3.73, 3.80, 5.23, 5.30, 5.73, 5.80, 6.73, 6.80,
                  9.23, 9.30, 9.73, 9.80, 10.23, 10.30, 13.23, 13.30, 13.73, 13.80]
    reference_frames = list(reference_dir.glob("ref_*.jpg"))
    by_time = {}
    for frame in reference_frames:
        value = float(frame.stem.removeprefix("ref_").replace("_", "."))
        by_time[value] = frame
    output_rows = []
    row_images = []
    comparison_dir = output_dir / "comparison_frames"
    comparison_dir.mkdir(exist_ok=True)
    target_size = (180, 320)
    for seconds in timestamps:
        ticks = round(seconds * graph.timebase)
        frame_index = graph.frame_index_at(ticks)
        sample_0_3 = comparison_dir / f"0_3_{seconds:06.3f}.png"
        _extract_video_frame(preview_path, ffmpeg, graph.frame_index_at(ticks), sample_0_3)
        sample_0_2 = comparison_dir / f"0_2_{seconds:06.3f}.png"
        sample_0_1 = comparison_dir / f"0_1_{seconds:06.3f}.png"
        _extract_video_frame(render_9a, ffmpeg, min(frame_index, 449), sample_0_1)
        _extract_video_frame(render_9b, ffmpeg, min(frame_index, 449), sample_0_2)
        closest_time = min(by_time, key=lambda candidate: abs(candidate - seconds))
        ref = Image.open(by_time[closest_time]).convert("RGB")
        # 14.5/15s source captures show Control Center; requested comparison excludes that UI.
        if closest_time >= 14.5:
            ref = Image.new("RGB", target_size, "#dadde4")
        ref = ref.resize(target_size, Image.Resampling.LANCZOS)
        row = [ref]
        for frame in (sample_0_1, sample_0_2, sample_0_3):
            with Image.open(frame) as image:
                row.append(image.convert("RGB").resize(target_size, Image.Resampling.LANCZOS))
        row_images.append(row)
        output_rows.append({"timeSeconds": seconds, "frameIndex": frame_index,
                            "referenceSampleSeconds": closest_time, "reference": str(by_time[closest_time].relative_to(REPO)),
                            "0_1": str(sample_0_1.relative_to(REPO)), "0_2": str(sample_0_2.relative_to(REPO)),
                            "0_3": str(sample_0_3.relative_to(REPO))})
    sheet = Image.new("RGB", (target_size[0] * 4, 352 * len(row_images)), "#edf0f6")
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(sheet)
    header_font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 14)
    titles = ["Muse preview crop", "3.9A", "3.9B", "0.3 (same 12-photo fixture)"]
    for index, row in enumerate(row_images):
        top = index * 352
        for column, tile in enumerate(row):
            sheet.paste(tile, (column * target_size[0], top + 28))
        draw.text((2, top + 4), f"t={output_rows[index]['timeSeconds']:.2f}s · " + " | ".join(titles),
                  fill="#1c2230", font=header_font)
    sheet.save(output_dir / "Fall_Diary_Reference_vs_0_3_Frame_Comparison.jpg", quality=93)
    return output_rows


def main() -> int:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg and FFprobe are required for 3.9C render validation.")
    definition = get_template_definition("fall-diary", "0.3.0-reference-pilot")
    if definition is None:
        raise RuntimeError("Fall Diary 0.3.0-reference-pilot is not registered.")
    output = REPO / "artifacts" / "video_creator" / "task3_9c"
    output.mkdir(parents=True, exist_ok=True)
    source_dir = REPO / "local_reference" / "fall_diary" / "private_test_media"
    sources = [source_dir / f"photo_{index:02d}.jpg" for index in range(1, 13)]
    if any(not source.is_file() for source in sources):
        raise RuntimeError("The 12 private QA fixture images are incomplete.")
    source_sha_before = {source.name: hashlib.sha256(source.read_bytes()).hexdigest() for source in sources}
    paths = {_asset_id(path.relative_to(REPO).as_posix()): path for path in sources}
    store = FixtureStore(paths)
    bindings = {f"photo-{index:02d}": _asset_id(sources[index - 1].relative_to(REPO).as_posix())
                for index in range(1, len(definition.slots) + 1)}
    project_id = uuid5(NAMESPACE_URL, "mediastudio:fall-diary:task3.9c:reference-pilot-0.3").hex
    compiled = compile_template(definition, bindings, store.get_metadata,
                                project_id=project_id, title="Fall Diary Reference Pilot 0.3")
    graph = build_composition_graph(compiled.project, store.get_metadata)
    project_path = output / "Fall_Diary_Reference_Pilot_Project_V2.json"
    graph_path = output / "Fall_Diary_Reference_Pilot_Composition_Graph.json"
    project_path.write_text(json.dumps(compiled.project.model_dump(mode="json", by_alias=True),
                                       ensure_ascii=False, indent=2), encoding="utf-8")
    graph_path.write_text(json.dumps(graph.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    staging = output / "_render_staging"
    staging.mkdir(exist_ok=True)
    export_tmp = _render(graph, store, ffmpeg, staging, "draft")
    export_path = output / "Fall_Diary_Reference_Pilot_Render.mp4"
    export_path.unlink(missing_ok=True)
    export_tmp.replace(export_path)
    preview_graph = replace(graph, width=540, height=960)
    preview_tmp = _render(preview_graph, store, ffmpeg, staging, "draft")
    preview_path = output / "Fall_Diary_Reference_Pilot_Preview.mp4"
    preview_path.unlink(missing_ok=True)
    preview_tmp.replace(preview_path)

    sample_times = [0.0, 1.5, 3.733333, 3.8, 5.233333, 5.3, 5.733333, 5.8,
                    6.733333, 6.8, 9.233333, 9.3, 9.733333, 9.8, 10.233333,
                    10.3, 13.233333, 13.3, 13.733333, 13.8, 16.5]
    frame_dir = output / "render_frames"
    frame_dir.mkdir(exist_ok=True)
    frame_parity = _still_parity(graph, store, ffmpeg, export_path, frame_dir, sample_times)
    parity = _ssim(preview_path, export_path, ffmpeg, output)
    comparisons = _frame_comparison(
        graph, store, ffmpeg, preview_path,
        REPO / "artifacts/video_creator/task3_9a/Fall_Diary_First_Render.mp4",
        REPO / "artifacts/video_creator/task3_9b/Fall_Diary_Motion_Render.mp4",
        output / "reference_frames", output,
    )
    source_sha_after = {source.name: hashlib.sha256(source.read_bytes()).hexdigest() for source in sources}
    manifest = {
        "task": "3.9C", "templateId": definition.template_id,
        "templateDefinitionVersion": definition.version, "projectId": project_id,
        "projectRevision": compiled.project.revision, "timebase": graph.timebase,
        "durationTicks": graph.duration_ticks, "durationSeconds": graph.duration_ticks / graph.timebase,
        "frameRate": graph.fps, "frameCount": graph.frame_index_at(graph.duration_ticks),
        "canvas": {"width": graph.width, "height": graph.height},
        "sourceFixtureDirectory": "local_reference/fall_diary/private_test_media",
        "sourceFilesCopied": False, "sourceFilesUnmodified": source_sha_before == source_sha_after,
        "sourceSha256Before": source_sha_before, "sourceSha256After": source_sha_after,
        "bindings": bindings, "unassignedFixture": "photo_12.jpg",
        "definition": {
            "slotCount": len(definition.slots), "slotIds": [slot.slot_id for slot in definition.slots],
            "eventCount": len(definition.events),
            "backgroundEvents": [{"eventId": event.event_id, "startTicks": event.timeline_start_ticks,
                                  "durationTicks": event.duration_ticks}
                                 for event in definition.events if event.event_id.startswith("background-")],
            "overlayEvents": [{"eventId": event.event_id, "startTicks": event.timeline_start_ticks,
                               "durationTicks": event.duration_ticks,
                              "layerCount": len(event.layers)}
                              for event in definition.events if event.event_id.startswith("overlay-")],
            "titleEvent": {"startTicks": next(event.timeline_start_ticks for event in definition.events
                                               if event.event_id == "title-graphic"),
                           "durationTicks": next(event.duration_ticks for event in definition.events
                                                 if event.event_id == "title-graphic"),
                           "layerCount": 9, "sourceContinuityConfidence": "high through 13.833s; ending inferred"},
            "animatedLayerCount": sum(bool(layer.keyframes) for event in definition.events for layer in event.layers),
            "audioReference": definition.audio_asset_reference, "cutoutSupported": False,
            "sourceAssetIdsHardcoded": False,
        },
        "referenceInterpretation": {
            "sourceIsScreenRecording": True,
            "isolatedPreviewCrop": {"left": 0, "top": 0, "width": 720, "height": 1215,
                                    "maskedControl": "close button x=24..82 y=91..163"},
            "excludedUi": ["Muse account and music metadata", "Use template", "bookmark", "close button",
                           "home indicator", "Control Center at 14.5s and 15.0s"],
            "titleGraphicConfidence": "high: FALL DIARY tile letters are inside the preview and persist through 13.833s",
            "durationConfidence": "medium: Muse UI reports 17s; source recording ends around 15.067s",
            "timingClassifications": [
                {"candidateSeconds": 3.767, "classification": "confirmed visible change / likely overlay replacement"},
                {"candidateSeconds": 5.267, "classification": "confirmed visible change / likely overlay replacement"},
                {"candidateSeconds": 5.767, "classification": "confirmed visible change / likely background cut"},
                {"candidateSeconds": 6.767, "classification": "confirmed visible change / likely overlay replacement"},
                {"candidateSeconds": 9.267, "classification": "confirmed visible change / likely close-up replacement"},
                {"candidateSeconds": 9.767, "classification": "confirmed visible change / likely scene cut"},
                {"candidateSeconds": 10.267, "classification": "confirmed visible change / likely overlay replacement"},
                {"candidateSeconds": 13.267, "classification": "confirmed visible change / likely scene cut"},
                {"candidateSeconds": 13.767, "classification": "confirmed visible change / likely scene cut"},
                {"candidateSeconds": 15.067, "classification": "unknown / recording boundary shows app Control Center"},
            ],
        },
        "qa": {"previewExportStillParity": frame_parity, "previewExportSsim": parity,
               "previewProbe": _probe(preview_path, ffprobe), "renderProbe": _probe(export_path, ffprobe),
               "previewFullDecode": _decode(preview_path, ffmpeg), "renderFullDecode": _decode(export_path, ffmpeg),
               "audioFidelityVerified": False, "cutoutVerified": False,
               "motionVerified": False, "referenceFidelityVerified": False,
               "frameComparisonRows": comparisons},
        "outputs": {"preview": str(preview_path.relative_to(REPO)).replace("\\", "/"),
                    "render": str(export_path.relative_to(REPO)).replace("\\", "/"),
                    "projectV2": str(project_path.relative_to(REPO)).replace("\\", "/"),
                    "compositionGraph": str(graph_path.relative_to(REPO)).replace("\\", "/"),
                    "comparisonContactSheet": "artifacts/video_creator/task3_9c/Fall_Diary_Reference_vs_0_3_Frame_Comparison.jpg"},
    }
    manifest_path = output / "Fall_Diary_Reference_Pilot_Manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), "preview": str(preview_path), "render": str(export_path),
                      "sourceFilesUnmodified": manifest["sourceFilesUnmodified"],
                      "stillParity": frame_parity, "ssim": parity,
                      "previewDecode": manifest["qa"]["previewFullDecode"],
                      "renderDecode": manifest["qa"]["renderFullDecode"]}, ensure_ascii=False, indent=2))
    if (not manifest["sourceFilesUnmodified"] or not frame_parity["passedThreshold"] or not parity["valid"]
            or not manifest["qa"]["previewFullDecode"]["valid"]
            or not manifest["qa"]["renderFullDecode"]["valid"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
