"""Render the isolated Fall Diary 3.9B motion pilot and its QA evidence.

The private photo sources are read in place and are never copied or modified.
The audio track is generated locally as a synthetic verification tone.
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
from uuid import uuid5, NAMESPACE_URL

from PIL import Image, ImageChops, ImageStat

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from mediastudio.video_editor.composition import build_composition_graph  # noqa: E402
from mediastudio.video_editor.composition_renderer import (  # noqa: E402
    render_composition_project, render_preview_frame_png,
)
from mediastudio.video_editor.jobs import VideoJob  # noqa: E402
from mediastudio.video_editor.media_selection import get_template_definition  # noqa: E402
from mediastudio.video_editor.project_v2 import TimelineClipV2, TimelineTrackV2  # noqa: E402
from mediastudio.video_editor.template_compiler import compile_template  # noqa: E402


class QaMediaStore:
    def __init__(self, paths: dict[str, Path]) -> None:
        self.paths = paths
        self.metadata = {
            asset_id: SimpleNamespace(
                asset_id=asset_id,
                kind="audio" if path.suffix.casefold() in {".wav", ".mp3", ".m4a"} else "image",
                duration_ms=15_000 if path.suffix.casefold() in {".wav", ".mp3", ".m4a"} else None,
                audio_codec="pcm_s16le" if path.suffix.casefold() == ".wav" else None,
            )
            for asset_id, path in paths.items()
        }

    def get_metadata(self, asset_id: str):
        return self.metadata[asset_id]

    def get_path(self, asset_id: str) -> Path:
        return self.paths[asset_id]


def _asset_id(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()[:32]


def _run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


def _probe(path: Path, ffprobe: str) -> dict[str, object]:
    result = _run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {"raw": result.stdout}
    return {"exitCode": result.returncode, "probe": payload, "stderr": result.stderr[-2000:]}


def _decode(path: Path, ffmpeg: str) -> dict[str, object]:
    result = _run([ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"])
    return {"exitCode": result.returncode,
            "valid": result.returncode == 0 and not result.stderr.strip(),
            "stderr": result.stderr[-2000:]}


def _ssim(preview: Path, export: Path, ffmpeg: str, report_path: Path) -> dict[str, object]:
    if report_path.exists():
        report_path.unlink()
    result = _run([
        ffmpeg, "-v", "error", "-i", str(preview), "-i", str(export),
        "-filter_complex",
        "[0:v]format=yuv420p[p];[1:v]scale=540:960:flags=lanczos,format=yuv420p[e];"
        "[p][e]ssim=stats_file=" + report_path.name + "[s]",
        "-map", "[s]", "-f", "null", "-",
    ], cwd=report_path.parent)
    lines = report_path.read_text(encoding="utf-8").splitlines() if report_path.is_file() else []
    values = []
    for line in lines:
        token = next((part for part in line.split() if part.startswith("All:")), None)
        if token:
            try:
                values.append(float(token.split(":", 1)[1]))
            except ValueError:
                pass
    return {"exitCode": result.returncode, "valid": result.returncode == 0 and bool(values),
            "framesCompared": len(lines), "meanSsim": sum(values) / len(values) if values else None,
            "minSsim": min(values) if values else None, "stderr": result.stderr[-2000:]}


def _render(job_id: str, graph, store: QaMediaStore, ffmpeg: str, staging: Path) -> Path:
    job = VideoJob(job_id=job_id, project_id=graph.project_id, job_type="fall-diary-motion-qa")
    render_composition_project(job, graph, store, ffmpeg, staging, "draft")
    if job.output_path is None or not job.output_path.is_file():
        raise RuntimeError(f"Composition export failed: {job.error}")
    return job.output_path


def _sample_frames(graph, store: QaMediaStore, ffmpeg: str, output_dir: Path) -> list[dict[str, object]]:
    sample_dir = output_dir / "motion_frames"
    sample_dir.mkdir(parents=True, exist_ok=True)
    times = [0.25, 1.25, 2.25, 3.75, 6.25, 8.75, 11.25, 13.75]
    cards: list[Image.Image] = []
    rows: list[dict[str, object]] = []
    for index, seconds in enumerate(times):
        ticks = int(seconds * graph.timebase)
        data = render_preview_frame_png(graph, store, ffmpeg, ticks)
        image_path = sample_dir / f"frame_{seconds:05.2f}s.png"
        image_path.write_bytes(data)
        with Image.open(image_path) as opened:
            image = opened.convert("RGB")
            cards.append(image.resize((270, 480), Image.Resampling.LANCZOS))
        rows.append({"timeSeconds": seconds, "ticks": ticks, "frameIndex": graph.frame_index_at(ticks),
                     "frame": str(image_path.relative_to(output_dir)).replace("\\", "/"),
                     "sha256": hashlib.sha256(data).hexdigest()})
    contact = Image.new("RGB", (270 * 4, 480 * 2), "#18212d")
    for index, card in enumerate(cards):
        contact.paste(card, ((index % 4) * 270, (index // 4) * 480))
    contact.save(output_dir / "Fall_Diary_Motion_Frame_Evidence.jpg", quality=92)
    return rows


def _frame_parity_samples(graph, ffmpeg: str, export_path: Path,
                          preview_frames: list[dict[str, object]], output_dir: Path) -> dict[str, object]:
    """Compare native still-preview renders against exact export frame indices."""
    errors: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="fall_diary_39b_frame_parity_") as temporary:
        temp_dir = Path(temporary)
        for index, sample in enumerate(preview_frames):
            frame_index = int(sample["frameIndex"])
            export_frame = temp_dir / f"export_{index:02d}.png"
            result = _run([
                ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(export_path),
                "-vf", f"select='eq(n,{frame_index})'", "-fps_mode", "passthrough",
                "-frames:v", "1", "-y", str(export_frame),
            ])
            if result.returncode != 0 or not export_frame.is_file():
                raise RuntimeError(f"Could not extract export frame {frame_index}: {result.stderr[-800:]}")
            preview_frame = output_dir / str(sample["frame"])
            with Image.open(preview_frame) as first, Image.open(export_frame) as second:
                a, b = first.convert("RGB"), second.convert("RGB")
                if a.size != b.size:
                    raise RuntimeError("Preview/export still frame sizes diverged at 1080p.")
                diff = ImageStat.Stat(ImageChops.difference(a, b)).mean
                errors.append({"timeSeconds": sample["timeSeconds"], "frameIndex": frame_index,
                               "meanAbsoluteErrorRgb": round(sum(diff) / 3, 4),
                               "channelMeanAbsoluteError": [round(value, 4) for value in diff]})
    mean_error = sum(float(item["meanAbsoluteErrorRgb"]) for item in errors) / len(errors) if errors else None
    return {"method": "1080x1920 still preview vs exact indexed frame from H.264 export",
            "framesCompared": len(errors), "meanAbsoluteErrorRgb": round(mean_error, 4) if mean_error is not None else None,
            "samples": errors}


def _within_event_motion(preview_frames: list[dict[str, object]], output_dir: Path) -> dict[str, object]:
    # First three captures are at 0.25, 1.25 and 2.25 sec within event scene-01-open.
    candidates = [sample for sample in preview_frames if float(sample["timeSeconds"]) < 2.5]
    if len(candidates) < 3:
        return {"verified": False, "reason": "Insufficient preview samples inside the first event."}
    first, middle, last = candidates[0], candidates[1], candidates[2]
    with Image.open(output_dir / str(first["frame"])) as a, Image.open(output_dir / str(last["frame"])) as b:
        difference = ImageStat.Stat(ImageChops.difference(a.convert("RGB"), b.convert("RGB"))).mean
    mean_difference = sum(difference) / 3
    return {"eventId": "scene-01-open", "sampleSeconds": [first["timeSeconds"], middle["timeSeconds"], last["timeSeconds"]],
            "sampleHashes": [first["sha256"], middle["sha256"], last["sha256"]],
            "firstToLastMeanAbsoluteRgbDifference": round(mean_difference, 4),
            "verified": len({first["sha256"], middle["sha256"], last["sha256"]}) == 3 and mean_difference > 1.0}


def _smoke_second_fixture_set(definition, ffmpeg: str, output_dir: Path) -> dict[str, object]:
    fixture_dir = REPO / "mediastudio_beta_testpack" / "inputs_png_512"
    names = ["D01_small_colored_islands.png", "D02_thin_orbits.png", "D03_corner_spikes.png",
             "D04_nested_counters.png", "C01_three_tone_disc.png", "C03_camera.png",
             "C04_leaf.png", "C05_mountain_sun.png", "C07_coffee.png", "C10_flower.png",
             "A02_translucent_overlays.png", "G03_multistop_gradient.png"]
    sources = [fixture_dir / name for name in names]
    if any(not path.is_file() for path in sources):
        return {"passed": False, "reason": "The varied second QA fixture set is incomplete."}
    paths = {_asset_id("second-set:" + path.name): path for path in sources}
    store = QaMediaStore(paths)
    bindings = {f"photo-{index:02d}": _asset_id("second-set:" + path.name)
                for index, path in enumerate(sources, start=1)}
    project_id = uuid5(NAMESPACE_URL, "mediastudio:fall-diary:task3.9b:second-fixture-smoke").hex
    compiled = compile_template(definition, bindings, store.get_metadata, project_id=project_id,
                                 title="Fall Diary Motion Second Fixture QA")
    graph = build_composition_graph(compiled.project, store.get_metadata)
    sample_ticks = [int(seconds * graph.timebase) for seconds in (1.25, 3.75, 6.25, 8.75, 11.25, 13.75)]
    sample_dir = output_dir / "second_fixture_set"
    sample_dir.mkdir(parents=True, exist_ok=True)
    hashes = []
    for index, ticks in enumerate(sample_ticks):
        path = sample_dir / f"fixture_{index + 1:02d}.png"
        path.write_bytes(render_preview_frame_png(graph, store, ffmpeg, ticks))
        hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
    return {"passed": len(set(hashes)) > 1, "sourceFiles": names, "sourceFilesCopied": False,
            "renderedPreviewFrames": len(hashes), "uniqueFrameHashes": len(set(hashes)),
            "fixtureClass": "varied geometric/icon/gradient PNGs; not portrait photographs"}


def main() -> int:
    definition = get_template_definition("fall-diary", "0.2.0-motion-pilot")
    if definition is None:
        raise RuntimeError("Fall Diary 0.2.0-motion-pilot definition was not found.")
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg and FFprobe are required for the motion pilot render.")

    output_dir = REPO / "artifacts" / "video_creator" / "task3_9b"
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = REPO / "local_reference" / "fall_diary" / "private_test_media"
    source_paths = [source_dir / f"photo_{index:02d}.jpg" for index in range(1, 13)]
    if any(not path.is_file() for path in source_paths):
        raise RuntimeError("The Fall Diary private 12-photo QA set is incomplete.")
    source_hashes_before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}

    audio_path = output_dir / "_synthetic_qa_tone.wav"
    audio_gen = _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                      "sine=frequency=440:sample_rate=48000:duration=15", "-c:a", "pcm_s16le", str(audio_path)])
    if audio_gen.returncode != 0:
        raise RuntimeError("Could not synthesize the local QA audio tone: " + audio_gen.stderr[-1000:])

    source_assets = {_asset_id(path.relative_to(REPO).as_posix()): path for path in source_paths}
    tone_id = _asset_id("qa-synthetic-440hz-tone-15s")
    source_assets[tone_id] = audio_path
    store = QaMediaStore(source_assets)
    bindings = {f"photo-{index:02d}": _asset_id(path.relative_to(REPO).as_posix())
                for index, path in enumerate(source_paths, start=1)}
    project_id = uuid5(NAMESPACE_URL, "mediastudio:fall-diary:task3.9b:motion-pilot-0.2").hex
    compiled = compile_template(definition, bindings, store.get_metadata,
                                project_id=project_id, title="Fall Diary Motion Pilot 0.2")

    # This is a QA-only synthetic tone track; it is not part of the reusable template definition.
    tone_track_id = _asset_id("fall-diary-3.9b-qa-audio-track")
    tone_clip_id = _asset_id("fall-diary-3.9b-qa-audio-clip")
    tone_track = TimelineTrackV2(
        trackId=tone_track_id, kind="audio", layerOrder=max(track.layer_order for track in compiled.project.tracks) + 1,
        displayName="Synthetic QA Tone",
        clips=[TimelineClipV2(clipId=tone_clip_id, trackId=tone_track_id, clipKind="audio",
                              timelineStartTicks=0, sourceStartTicks=0, durationTicks=definition.duration_ticks,
                              mediaId=tone_id, properties={"volume": 0.06, "fadeInMs": 250, "fadeOutMs": 500})],
    )
    project = compiled.project.model_copy(update={"tracks": [*compiled.project.tracks, tone_track], "revision": 2})
    graph_object = build_composition_graph(project, store.get_metadata)
    project_path = output_dir / "Fall_Diary_Motion_Project_V2.json"
    graph_path = output_dir / "Fall_Diary_Motion_Composition_Graph.json"
    project_path.write_text(json.dumps(project.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2),
                            encoding="utf-8")
    graph_path.write_text(json.dumps(graph_object.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    staging = output_dir / "_render_staging"
    staging.mkdir(parents=True, exist_ok=True)
    export_tmp = _render("c" * 32, graph_object, store, ffmpeg, staging)
    export_path = output_dir / "Fall_Diary_Motion_Render.mp4"
    if export_path.exists():
        export_path.unlink()
    export_tmp.replace(export_path)
    preview_graph = replace(graph_object, width=540, height=960)
    preview_tmp = _render("d" * 32, preview_graph, store, ffmpeg, staging)
    preview_path = output_dir / "Fall_Diary_Motion_Preview.mp4"
    if preview_path.exists():
        preview_path.unlink()
    preview_tmp.replace(preview_path)

    motion_evidence = _sample_frames(graph_object, store, ffmpeg, output_dir)
    frame_parity = _frame_parity_samples(graph_object, ffmpeg, export_path, motion_evidence, output_dir)
    within_event_motion = _within_event_motion(motion_evidence, output_dir)
    second_set = _smoke_second_fixture_set(definition, ffmpeg, output_dir)
    before_0_1 = get_template_definition("fall-diary", "0.1.0-pilot")
    if before_0_1 is None or before_0_1.version != "0.1.0-pilot":
        raise RuntimeError("The immutable 0.1.0 baseline is not loadable by its pinned version.")
    source_hashes_after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    parity = _ssim(preview_path, export_path, ffmpeg, output_dir / "preview_export_ssim.log")
    manifest = {
        "task": "3.9B", "templateId": definition.template_id,
        "templateDefinitionVersion": definition.version,
        "baselineDefinitionVersion": before_0_1.version,
        "projectId": project_id,
        "sourceDirectory": "local_reference/fall_diary/private_test_media",
        "sourceFilesCopied": False,
        "sourceFilesUnmodified": source_hashes_before == source_hashes_after,
        "sourceSha256Before": source_hashes_before, "sourceSha256After": source_hashes_after,
        "bindings": {slot: asset_id for slot, asset_id in sorted(bindings.items())},
        "definition": {
            "slots": len(definition.slots), "events": len(definition.events),
            "layerCountByEvent": {event.event_id: len(event.layers) for event in definition.events},
            "animatedLayerCount": sum(bool(layer.keyframes) for event in definition.events for layer in event.layers),
            "allowedMediaKinds": sorted({kind for slot in definition.slots for kind in slot.allowed_media_kinds}),
            "keyframeProperties": sorted({key.property for event in definition.events for layer in event.layers
                                           for key in layer.keyframes}),
            "supportedCapabilities": list(definition.supported_capabilities),
            "cutoutSupported": False,
        },
        "syntheticAudioQa": {"tone": "440 Hz sine", "durationSeconds": 15, "sampleRate": 48000,
                             "fadeInMs": 250, "fadeOutMs": 500, "templateDefinitionContainsAudio": False},
        "motionSamples": motion_evidence,
        "withinEventMotion": within_event_motion,
        "sameResolutionFrameParity": frame_parity,
        "secondFixtureSet": second_set,
        "outputs": {
            "preview": str(preview_path.relative_to(REPO)).replace("\\", "/"),
            "export": str(export_path.relative_to(REPO)).replace("\\", "/"),
            "previewProbe": _probe(preview_path, ffprobe), "exportProbe": _probe(export_path, ffprobe),
            "previewFullDecode": _decode(preview_path, ffmpeg), "exportFullDecode": _decode(export_path, ffmpeg),
            "previewExportSsim": parity,
        },
    }
    manifest_path = output_dir / "Fall_Diary_Motion_Manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"project": str(project_path), "graph": str(graph_path), "preview": str(preview_path),
                      "export": str(export_path), "manifest": str(manifest_path),
                      "previewExportSsim": parity, "secondFixtureSet": second_set}, ensure_ascii=False, indent=2))
    if (not manifest["sourceFilesUnmodified"] or not manifest["outputs"]["previewFullDecode"]["valid"]
            or not manifest["outputs"]["exportFullDecode"]["valid"] or not parity["valid"]
            or not second_set.get("passed")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
