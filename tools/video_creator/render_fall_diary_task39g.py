"""Render and validate Fall Diary 0.4 through the shared compiler/graph renderer."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5, uuid4

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

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
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    return {"valid": video is not None, "format": payload.get("format", {}), "video": video,
            "audioStreamCount": sum(stream.get("codec_type") == "audio" for stream in streams)}


def _decode(path: Path, ffmpeg: str) -> dict[str, object]:
    result = _run([ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"])
    return {"valid": result.returncode == 0 and not result.stderr.strip(),
            "exitCode": result.returncode, "stderr": result.stderr[-2000:]}


def _render(graph, store: FixtureStore, ffmpeg: str, staging: Path, quality: str, label: str) -> Path:
    job = VideoJob(job_id=uuid4().hex, project_id=graph.project_id, job_type=label)
    render_composition_project(job, graph, store, ffmpeg, staging, quality)
    if job.output_path is None or not job.output_path.is_file():
        raise RuntimeError(f"Shared Composition Graph render failed: {job.error}")
    return job.output_path


def _extract(path: Path, ffmpeg: str, frame_index: int, destination: Path) -> None:
    result = _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path),
                   "-vf", f"select='eq(n,{frame_index})'", "-fps_mode", "passthrough",
                   "-frames:v", "1", "-y", str(destination)])
    if result.returncode or not destination.is_file():
        raise RuntimeError(f"Could not extract frame {frame_index} from {path.name}: {result.stderr[-1000:]}")


def _still_parity(graph, store: FixtureStore, ffmpeg: str, export_path: Path,
                  output: Path, seconds_list: list[float]) -> dict[str, object]:
    samples = []
    for seconds in seconds_list:
        frame_index = graph.frame_index_at(round(seconds * graph.timebase))
        preview = output / f"still_preview_{seconds:06.3f}.png"
        preview.write_bytes(render_preview_frame_png(graph, store, ffmpeg, round(seconds * graph.timebase)))
        exported = output / f"still_export_{seconds:06.3f}.png"
        _extract(export_path, ffmpeg, frame_index, exported)
        with Image.open(preview) as first, Image.open(exported) as second:
            left, right = first.convert("RGB"), second.convert("RGB")
            if left.size != right.size:
                raise RuntimeError(f"Still renderer/export dimensions differ at {seconds:.3f}s.")
            channels = ImageStat.Stat(ImageChops.difference(left, right)).mean
        samples.append({"timeSeconds": seconds, "frameIndex": frame_index,
                        "meanAbsoluteErrorRgb": round(sum(channels) / 3, 5)})
    errors = [row["meanAbsoluteErrorRgb"] for row in samples]
    return {"method": "same Composition Graph still renderer vs exact H.264 export frame index",
            "framesCompared": len(samples), "meanAbsoluteErrorRgb": round(sum(errors) / len(errors), 5),
            "maxMeanAbsoluteErrorRgb": max(errors), "samples": samples,
            "passedThreshold": sum(errors) / len(errors) <= 12 and max(errors) <= 24}


def _ssim(preview: Path, export: Path, ffmpeg: str, output: Path) -> dict[str, object]:
    stats = output / "preview_export_ssim.log"
    stats.unlink(missing_ok=True)
    result = _run([ffmpeg, "-v", "error", "-i", str(preview), "-i", str(export),
                   "-filter_complex", "[0:v]format=yuv420p[p];[1:v]scale=540:960:flags=lanczos,format=yuv420p[e];"
                                      f"[p][e]ssim=stats_file={stats.name}[s]",
                   "-map", "[s]", "-f", "null", "-"], cwd=output)
    values = []
    if stats.is_file():
        for line in stats.read_text(encoding="utf-8").splitlines():
            token = next((part for part in line.split() if part.startswith("All:")), None)
            if token:
                try:
                    values.append(float(token.split(":", 1)[1]))
                except ValueError:
                    continue
    return {"valid": result.returncode == 0 and bool(values), "exitCode": result.returncode,
            "framesCompared": len(values), "meanSsim": sum(values) / len(values) if values else None,
            "minSsim": min(values) if values else None, "stderr": result.stderr[-1000:]}


def _comparison_sheet(ffmpeg: str, preview_02: Path, preview_03: Path,
                      preview_04: Path, reference_dir: Path, output: Path) -> list[dict[str, object]]:
    timestamps = [0.5, 3.73, 3.80, 5.23, 5.30, 5.73, 5.80, 6.73, 6.80,
                  9.23, 9.30, 9.73, 9.80, 10.23, 10.30, 13.23, 13.30, 13.73, 13.80]
    reference_frames = list(reference_dir.glob("preview_t*.jpg"))
    by_time: dict[float, Path] = {}
    for frame in reference_frames:
        token = frame.stem.removeprefix("preview_t").replace("_", ".")
        by_time[float(token)] = frame
    if not by_time:
        raise RuntimeError("Isolated Muse preview samples were not found.")

    target = (180, 320)
    rows: list[list[Image.Image]] = []
    records = []
    frame_dir = output / "comparison_frames"
    frame_dir.mkdir(exist_ok=True)
    videos = [("0.2 motion pilot", preview_02), ("0.3 reference pilot", preview_03),
              ("0.4 editorial pilot", preview_04)]
    for seconds in timestamps:
        closest = min(by_time, key=lambda time: abs(time - seconds))
        reference = Image.open(by_time[closest]).convert("RGB").resize(target, Image.Resampling.LANCZOS)
        row = [reference]
        media_paths = []
        index = round(seconds * 30)
        for short_name, video in videos:
            frame = frame_dir / f"{short_name.split()[0]}_{seconds:06.3f}.png"
            _extract(video, ffmpeg, index, frame)
            with Image.open(frame) as image:
                row.append(image.convert("RGB").resize(target, Image.Resampling.LANCZOS))
            media_paths.append({"version": short_name, "path": frame.relative_to(REPO).as_posix()})
        rows.append(row)
        records.append({"timeSeconds": seconds, "frameIndex": index,
                        "isolatedReferenceSeconds": closest,
                        "referencePath": by_time[closest].relative_to(REPO).as_posix(),
                        "renderFrames": media_paths})

    sheet = Image.new("RGB", (target[0] * 4, 352 * len(rows)), "#edf0f6")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 14)
    labels = ["Muse preview crop", "0.2 motion", "0.3 reference", "0.4 editorial"]
    for row_index, row in enumerate(rows):
        y = row_index * 352
        draw.text((4, y + 5), f"t={timestamps[row_index]:.2f}s · " + " | ".join(labels),
                  fill="#1c2230", font=font)
        for column, image in enumerate(row):
            sheet.paste(image, (column * target[0], y + 28))
    sheet.save(output / "Fall_Diary_3_9G_Reference_Comparison_Contact_Sheet.jpg", quality=93)
    return records


def _preview_export_sheet(ffmpeg: str, preview: Path, export: Path, output: Path) -> None:
    times = [0.5, 3.73, 3.80, 5.30, 6.80, 9.80, 10.30, 13.30, 13.80, 16.5]
    target = (270, 480)
    sheet = Image.new("RGB", (target[0] * 2, (target[1] + 28) * len(times)), "#edf0f6")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 16)
    for row, seconds in enumerate(times):
        index = round(seconds * 30)
        for column, (label, video) in enumerate((("Preview 540×960", preview), ("Export 1080×1920", export))):
            frame = output / f"parity_{row}_{column}.png"
            _extract(video, ffmpeg, index, frame)
            with Image.open(frame) as image:
                tile = image.convert("RGB").resize(target, Image.Resampling.LANCZOS)
            sheet.paste(tile, (column * target[0], row * (target[1] + 28) + 28))
            draw.text((column * target[0] + 4, row * (target[1] + 28) + 5),
                      f"t={seconds:.2f}s · {label}", fill="#1c2230", font=font)
    sheet.save(output / "Fall_Diary_3_9G_Preview_Export_Contact_Sheet.jpg", quality=92)


def _second_fixture_qa(definition, ffmpeg: str, output: Path) -> dict[str, object]:
    fixture_dir = REPO / "artifacts/video_creator/task3_9b/second_fixture_set"
    sources = [fixture_dir / f"fixture_{index:02d}.png" for index in range(1, 7)]
    if any(not path.is_file() for path in sources):
        return {"available": False, "passed": False, "reason": "3.9B second fixture set is incomplete."}
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    paths = {_asset_id(path.relative_to(REPO).as_posix()): path for path in sources}
    store = FixtureStore(paths)
    bindings = {slot.slot_id: _asset_id(sources[index % len(sources)].relative_to(REPO).as_posix())
                for index, slot in enumerate(definition.slots)}
    compiled = compile_template(definition, bindings, store.get_metadata,
                                project_id=uuid5(NAMESPACE_URL, "mediastudio:fall-diary:task3.9g:second-fixtures").hex,
                                title="Fall Diary 3.9G second-fixture QA")
    graph = build_composition_graph(compiled.project, store.get_metadata)
    staging = output / "second_fixture_staging"
    staging.mkdir(exist_ok=True)
    preview_graph = replace(graph, width=540, height=960)
    tmp = _render(preview_graph, store, ffmpeg, staging, "draft", "task3.9g-second-fixture")
    preview = output / "Fall_Diary_3_9G_Second_Fixture_QA.mp4"
    preview.unlink(missing_ok=True)
    tmp.replace(preview)
    samples = []
    for index, seconds in enumerate((1.0, 4.0, 8.0, 11.0, 14.0, 16.0)):
        image_path = output / f"second_fixture_{index}.png"
        frame = render_preview_frame_png(graph, store, ffmpeg, round(seconds * graph.timebase))
        image_path.write_bytes(frame)
        with Image.open(image_path) as image:
            samples.append({"timeSeconds": seconds, "size": list(image.size),
                            "sha256": hashlib.sha256(frame).hexdigest()})
    tiles = [Image.open(output / f"second_fixture_{index}.png").convert("RGB").resize((180, 320), Image.Resampling.LANCZOS)
             for index in range(len(samples))]
    contact = Image.new("RGB", (len(tiles) * 180, 352), "#edf0f6")
    draw = ImageDraw.Draw(contact)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 13)
    for index, (seconds, tile) in enumerate(zip((1.0, 4.0, 8.0, 11.0, 14.0, 16.0), tiles)):
        contact.paste(tile, (index * 180, 28))
        draw.text((index * 180 + 4, 5), f"Synthetic fixture · {seconds:.1f}s", fill="#1c2230", font=font)
    contact.save(output / "Fall_Diary_3_9G_Second_Fixture_Contact_Sheet.jpg", quality=92)
    after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    decode = _decode(preview, shutil.which("ffmpeg") or ffmpeg)
    return {"available": True, "passed": before == after and decode["valid"],
            "fixtureDirectory": fixture_dir.relative_to(REPO).as_posix(), "fixtureMediaCount": len(sources),
            "sourceFilesCopied": False, "sourceFilesUnmodified": before == after, "slotCount": len(bindings),
            "durationTicks": graph.duration_ticks, "frameRate": graph.fps,
            "preview": preview.relative_to(REPO).as_posix(), "fullDecode": decode, "frames": samples}


def main() -> int:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg and FFprobe are required for Task 3.9G.")
    definition = get_template_definition("fall-diary", "0.4.0-editorial-motion-pilot")
    if definition is None:
        raise RuntimeError("Fall Diary 0.4.0-editorial-motion-pilot is not registered.")
    output = REPO / "artifacts/video_creator/task3_9g"
    output.mkdir(parents=True, exist_ok=True)
    fixture_dir = REPO / "local_reference/fall_diary/private_test_media"
    sources = [fixture_dir / f"photo_{index:02d}.jpg" for index in range(1, 12)]
    if any(not path.is_file() for path in sources):
        raise RuntimeError("The private 3.9G photo fixture set is incomplete.")
    source_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    paths = {_asset_id(path.relative_to(REPO).as_posix()): path for path in sources}
    store = FixtureStore(paths)
    bindings = {slot.slot_id: _asset_id(sources[index].relative_to(REPO).as_posix())
                for index, slot in enumerate(definition.slots)}
    project_id = uuid5(NAMESPACE_URL, "mediastudio:fall-diary:task3.9g:editorial-motion-0.4").hex
    compiled = compile_template(definition, bindings, store.get_metadata,
                                project_id=project_id, title="Fall Diary Editorial Motion Pilot 0.4")
    graph = build_composition_graph(compiled.project, store.get_metadata)
    project_path = output / "Fall_Diary_3_9G_Project_V2.json"
    graph_path = output / "Fall_Diary_3_9G_Composition_Graph.json"
    project_path.write_text(json.dumps(compiled.project.model_dump(mode="json", by_alias=True),
                                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    graph_path.write_text(json.dumps(graph.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    staging = output / "render_staging"
    staging.mkdir(exist_ok=True)
    export_tmp = _render(graph, store, ffmpeg, staging, "standard", "task3.9g-export")
    export = output / "Fall_Diary_3_9G_Export.mp4"
    export.unlink(missing_ok=True)
    export_tmp.replace(export)
    preview_graph = replace(graph, width=540, height=960)
    preview_tmp = _render(preview_graph, store, ffmpeg, staging, "draft", "task3.9g-preview")
    preview = output / "Fall_Diary_3_9G_Preview.mp4"
    preview.unlink(missing_ok=True)
    preview_tmp.replace(preview)

    sample_times = [0.5, 3.733333, 3.8, 5.233333, 5.3, 5.733333, 5.8,
                    6.733333, 6.8, 9.233333, 9.3, 9.733333, 9.8,
                    10.233333, 10.3, 13.233333, 13.3, 13.733333, 13.8, 16.5]
    still_parity = _still_parity(graph, store, ffmpeg, export, output, sample_times)
    ssim = _ssim(preview, export, ffmpeg, output)
    _preview_export_sheet(ffmpeg, preview, export, output)
    comparisons = _comparison_sheet(
        ffmpeg,
        REPO / "artifacts/video_creator/task3_9b/Fall_Diary_Motion_Preview.mp4",
        REPO / "artifacts/video_creator/task3_9c/Fall_Diary_Reference_Pilot_Preview.mp4",
        preview,
        REPO / "artifacts/video_creator/task3_9c/reference_frames/isolated",
        output,
    )
    second_fixture = _second_fixture_qa(definition, ffmpeg, output)
    after_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    events = [event for event in definition.events if event.event_id.startswith("shot-")]
    keyframes = []
    for event in definition.events:
        for layer in event.layers:
            if not layer.keyframes:
                continue
            property_values = {}
            for key in layer.keyframes:
                item = property_values.setdefault(key.property, {})
                item["from" if key.time_ticks == 0 else "to"] = key.value
            keyframes.append({"eventId": event.event_id, "layerId": layer.layer_id,
                              "startTicks": event.timeline_start_ticks,
                              "endTicks": event.timeline_start_ticks + event.duration_ticks,
                              "properties": property_values, "classification": "editorial"})
    manifest = {
        "task": "3.9G", "templateId": definition.template_id,
        "templateDefinitionVersion": definition.version, "projectId": project_id,
        "projectRevision": compiled.project.revision, "timebase": graph.timebase,
        "durationTicks": graph.duration_ticks, "durationSeconds": graph.duration_ticks / graph.timebase,
        "frameRate": graph.fps, "frameCount": graph.frame_index_at(graph.duration_ticks),
        "canvas": {"width": graph.width, "height": graph.height},
        "sourceFixtureDirectory": fixture_dir.relative_to(REPO).as_posix(),
        "sourceFilesCopied": False, "sourceFilesUnmodified": source_hashes == after_hashes,
        "sourceSha256Before": source_hashes, "sourceSha256After": after_hashes,
        "bindings": bindings,
        "definition": {"slotCount": len(definition.slots), "slotIds": [slot.slot_id for slot in definition.slots],
                       "sceneEventCount": len(events),
                       "editorialCardEvents": [event.event_id for event in definition.events
                                               if event.event_id.startswith("editorial-card-")],
                       "titleTextLayerCount": 9, "totalEventCount": len(definition.events), "keyframes": keyframes,
                       "audioReference": None, "cutoutSupported": False,
                       "demoAssetReference": None, "posterAssetReference": None,
                       "sourceAssetIdsHardcoded": False},
        "referenceAnalysis": {"sourceIsScreenRecording": True,
                              "isolatedPreviewCrop": {"left": 0, "top": 0, "width": 720, "height": 1215,
                                                      "maskedControl": "close button x=24..82 y=91..163"},
                              "uiExcludedFromReference": True,
                              "motionEvidence": "continuous movement belongs to the recorded footage; original template keyframes cannot be isolated",
                              "editorialMotionUsed": True, "referenceMotionVerified": False,
                              "sourceEndKnown": False},
        "qa": {"stillPreviewExportParity": still_parity, "previewExportSsim": ssim,
               "previewProbe": _probe(preview, ffprobe), "exportProbe": _probe(export, ffprobe),
               "previewFullDecode": _decode(preview, ffmpeg), "exportFullDecode": _decode(export, ffmpeg),
               "previewExportParityVerified": still_parity["passedThreshold"] and ssim["valid"],
               "keyframeMotionVerified": len(keyframes) == 12 and all(row["properties"] for row in keyframes),
               "secondFixture": second_fixture,
               "referenceFidelityVerified": False, "cutoutVerified": False, "audioFidelityVerified": False,
               "wpfIntegrationVerified": False, "guiStatus": "GUI_PENDING",
               "comparisonRows": comparisons},
        "outputs": {"preview": preview.relative_to(REPO).as_posix(), "export": export.relative_to(REPO).as_posix(),
                    "projectV2": project_path.relative_to(REPO).as_posix(),
                    "compositionGraph": graph_path.relative_to(REPO).as_posix(),
                    "referenceContactSheet": "artifacts/video_creator/task3_9g/Fall_Diary_3_9G_Reference_Comparison_Contact_Sheet.jpg",
                    "previewExportContactSheet": "artifacts/video_creator/task3_9g/Fall_Diary_3_9G_Preview_Export_Contact_Sheet.jpg",
                    "secondFixtureContactSheet": "artifacts/video_creator/task3_9g/Fall_Diary_3_9G_Second_Fixture_Contact_Sheet.jpg"},
    }
    manifest_path = output / "Fall_Diary_3_9G_Manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), "preview": str(preview), "export": str(export),
                      "sourceFilesUnmodified": manifest["sourceFilesUnmodified"],
                      "previewExportParity": still_parity, "ssim": ssim,
                      "previewDecode": manifest["qa"]["previewFullDecode"],
                      "exportDecode": manifest["qa"]["exportFullDecode"],
                      "secondFixture": second_fixture}, ensure_ascii=False, indent=2))
    if (not manifest["sourceFilesUnmodified"] or not still_parity["passedThreshold"] or not ssim["valid"]
            or not manifest["qa"]["previewFullDecode"]["valid"]
            or not manifest["qa"]["exportFullDecode"]["valid"] or not second_fixture["passed"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
