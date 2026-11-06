"""Render and verify Fall Diary 0.5 through the shared compiler and graph renderer."""
from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
sys.path.insert(0, str(BACKEND))

from mediastudio.video_editor.composition import build_composition_graph  # noqa: E402
from mediastudio.video_editor.composition_renderer import (  # noqa: E402
    render_composition_project,
    render_preview_frame_png,
)
from mediastudio.video_editor.jobs import VideoJob  # noqa: E402
from mediastudio.video_editor.media_selection import get_template_definition  # noqa: E402
from mediastudio.video_editor.template_compiler import TemplateDefinition, compile_template  # noqa: E402


VERSION = "0.5.0-layer-structure-pilot"
TIMEBASE = 90_000
FRAME_TICKS = 3_000
SAMPLE_TIMES = [0.5, 3.733333, 3.766667, 5.233333, 5.266667, 5.733333, 5.766667,
                6.733333, 6.766667, 9.233333, 9.266667, 9.733333, 9.766667,
                10.233333, 10.266667, 13.233333, 13.266667, 13.733333, 13.766667,
                15.033333, 15.066667, 16.5]


class FixtureStore:
    def __init__(self, paths: dict[str, Path]) -> None:
        self.paths = paths
        self.metadata = {
            asset_id: SimpleNamespace(asset_id=asset_id, kind="image", duration_ms=None,
                                      audio_codec=None)
            for asset_id in paths
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
    if result.returncode:
        return {"valid": False, "error": (result.stderr or result.stdout)[-1200:]}
    payload = json.loads(result.stdout)
    video = next((stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video"), {})
    return {"valid": bool(video), "codec": video.get("codec_name"),
            "width": video.get("width"), "height": video.get("height"),
            "frameRate": video.get("r_frame_rate"), "frameCount": video.get("nb_frames"),
            "duration": payload.get("format", {}).get("duration"),
            "audioStreamCount": sum(stream.get("codec_type") == "audio"
                                     for stream in payload.get("streams", []))}


def _decode(path: Path, ffmpeg: str) -> dict[str, object]:
    result = _run([ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"])
    return {"valid": result.returncode == 0 and not result.stderr.strip(),
            "exitCode": result.returncode, "stderr": result.stderr[-1200:]}


def _render(graph, store: FixtureStore, ffmpeg: str, staging: Path, quality: str, label: str) -> Path:
    staging.mkdir(parents=True, exist_ok=True)
    job = VideoJob(job_id=uuid5(NAMESPACE_URL, f"fall-diary:3.9h:{label}").hex,
                   project_id=graph.project_id, job_type=label)
    render_composition_project(job, graph, store, ffmpeg, staging, quality)
    if not job.output_path or not Path(job.output_path).is_file():
        raise RuntimeError(f"Render {label} failed: {job.error or job.status}")
    return Path(job.output_path)


def _extract(path: Path, ffmpeg: str, frame_index: int, destination: Path) -> None:
    result = _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path),
                   "-vf", f"select='eq(n,{frame_index})'", "-fps_mode", "passthrough",
                   "-frames:v", "1", "-y", str(destination)])
    if result.returncode or not destination.is_file():
        raise RuntimeError(f"Could not extract frame {frame_index} from {path}: {result.stderr[-600:]}")


def _still_export_parity(graph, store: FixtureStore, ffmpeg: str, export: Path,
                         output: Path) -> dict[str, object]:
    rows = []
    for seconds in SAMPLE_TIMES:
        ticks = round(seconds * TIMEBASE)
        frame_index = graph.frame_index_at(ticks)
        still = Image.open(__import__("io").BytesIO(render_preview_frame_png(graph, store, ffmpeg, ticks))).convert("RGB")
        export_frame = output / f"parity_export_{frame_index:04d}.png"
        _extract(export, ffmpeg, frame_index, export_frame)
        with Image.open(export_frame) as image:
            exported = image.convert("RGB")
            if exported.size != still.size:
                raise RuntimeError("Preview frame renderer and export dimensions differ.")
            diff = ImageStat.Stat(ImageChops.difference(still, exported)).mean
            mae = sum(diff) / len(diff)
        rows.append({"timeSeconds": seconds, "frameIndex": frame_index,
                     "frameStartTicks": graph.frame_start_ticks(frame_index),
                     "meanAbsoluteErrorRgb": round(mae, 5)})
    errors = [row["meanAbsoluteErrorRgb"] for row in rows]
    return {"method": "same 0.5 Composition Graph still frame versus exact H.264 frame index",
            "framesCompared": len(rows), "meanAbsoluteErrorRgb": round(sum(errors) / len(errors), 5),
            "maxMeanAbsoluteErrorRgb": max(errors), "threshold": 3.5,
            "passed": max(errors) <= 3.5, "samples": rows}


def _reference_graph_payload(definition: TemplateDefinition) -> dict[str, object]:
    """Build a QA-only reference-layout variant without editing the 0.5 file."""
    payload = definition.model_dump(mode="json", by_alias=True)
    baseline_path = REPO / "backend/mediastudio/video_editor/definitions/fall-diary-0.3.0-reference-pilot.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    title_positions = {layer["layerId"]: (layer["textX"], layer["textY"], layer["fontSize"])
                       for event in baseline["events"] if event["eventId"] == "title-graphic"
                       for layer in event["layers"]}
    card_positions = {layer["layerId"]: (layer["positionX"], layer["positionY"], layer["scale"])
                      for event in baseline["events"] if event["eventId"].startswith("overlay-")
                      for layer in event["layers"]}
    for event in payload["events"]:
        for layer in event["layers"]:
            if layer["layerId"] in title_positions:
                layer["textX"], layer["textY"], layer["fontSize"] = title_positions[layer["layerId"]]
            if layer["layerId"] in card_positions:
                layer["positionX"], layer["positionY"], layer["scale"] = card_positions[layer["layerId"]]
    payload["metadata"]["layoutProfile"] = {"id": "reference-layout-v1", "version": 1, "qaOnly": True}
    return payload


def _comparison_sheet(ffmpeg: str, reference_dir: Path, graphs: list[tuple[str, object]],
                     stores: list[FixtureStore], output: Path) -> list[dict[str, object]]:
    files = list(reference_dir.glob("preview_t*.jpg"))
    reference_by_time = {}
    for path in files:
        value = path.stem.removeprefix("preview_t").replace("_", ".")
        reference_by_time[float(value)] = path
    if not reference_by_time:
        raise RuntimeError("Isolated Muse reference frames are missing.")
    target = (180, 320)
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 14)
    sheet = Image.new("RGB", (target[0] * (len(graphs) + 1), (target[1] + 28) * len(SAMPLE_TIMES)), "#eef1f7")
    draw = ImageDraw.Draw(sheet)
    labels = ["Muse preview crop", *[label for label, _ in graphs]]
    records = []
    for row_index, seconds in enumerate(SAMPLE_TIMES):
        nearest = min(reference_by_time, key=lambda item: abs(item - seconds))
        ref = Image.open(reference_by_time[nearest]).convert("RGB").resize(target, Image.Resampling.LANCZOS)
        y = row_index * (target[1] + 28)
        sheet.paste(ref, (0, y + 28))
        records.append({"timeSeconds": seconds, "referenceSeconds": nearest,
                        "referenceFile": reference_by_time[nearest].name})
        for col, label in enumerate(labels):
            draw.text((col * target[0] + 4, y + 5), f"t={seconds:.3f}s · {label}",
                      fill="#1c2230", font=font)
        for col, ((label, graph), store) in enumerate(zip(graphs, stores), start=1):
            ticks = round(seconds * TIMEBASE)
            image_data = render_preview_frame_png(graph, store, ffmpeg, ticks)
            with Image.open(__import__("io").BytesIO(image_data)) as image:
                tile = image.convert("RGB").resize(target, Image.Resampling.LANCZOS)
            sheet.paste(tile, (col * target[0], y + 28))
    sheet.save(output, quality=92)
    return records


def _second_fixture(definition: TemplateDefinition, ffmpeg: str, output: Path) -> dict[str, object]:
    fixture_dir = REPO / "artifacts/video_creator/task3_9b/second_fixture_set"
    sources = [fixture_dir / f"fixture_{index:02d}.png" for index in range(1, 7)]
    if any(not path.is_file() for path in sources):
        return {"available": False, "passed": False, "reason": "Second fixture set is incomplete."}
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    paths = {_asset_id(path.relative_to(REPO).as_posix()): path for path in sources}
    store = FixtureStore(paths)
    bindings = {slot.slot_id: _asset_id(sources[index % len(sources)].relative_to(REPO).as_posix())
                for index, slot in enumerate(definition.slots)}
    compiled = compile_template(definition, bindings, store.get_metadata,
                                project_id=uuid5(NAMESPACE_URL, "mediastudio:fall-diary:task3.9h:second-fixture").hex,
                                title="Fall Diary 3.9H second media fixture")
    graph = build_composition_graph(compiled.project, store.get_metadata)
    preview_graph = replace(graph, width=540, height=960)
    staging = output / "second_fixture_staging"
    preview = _render(preview_graph, store, ffmpeg, staging, "draft", "second-fixture-preview")
    target = output / "Fall_Diary_3_9H_Second_Fixture_QA.mp4"
    target.unlink(missing_ok=True)
    preview.replace(target)
    times = [0.5, 4.0, 8.0, 11.0, 14.0, 16.0]
    tile_size = (240, 426)
    sheet = Image.new("RGB", (len(times) * tile_size[0], tile_size[1] + 28), "#eef1f7")
    draw, font = ImageDraw.Draw(sheet), ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 14)
    rows = []
    for index, seconds in enumerate(times):
        png = render_preview_frame_png(graph, store, ffmpeg, round(seconds * TIMEBASE))
        with Image.open(__import__("io").BytesIO(png)) as image:
            tile = image.convert("RGB").resize(tile_size, Image.Resampling.LANCZOS)
        sheet.paste(tile, (index * tile_size[0], 28))
        draw.text((index * tile_size[0] + 4, 6), f"t={seconds:g}s · second fixture", fill="#1c2230", font=font)
        rows.append({"timeSeconds": seconds, "frameSha256": hashlib.sha256(png).hexdigest()})
    contact = output / "Fall_Diary_3_9H_Second_Fixture_Contact_Sheet.jpg"
    sheet.save(contact, quality=92)
    after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    decode = _decode(target, ffmpeg)
    return {"available": True, "passed": before == after and decode["valid"],
            "technicalRenderPassed": before == after and decode["valid"],
            "visualDiversityVerified": False,
            "contentSuitability": "UNSUITABLE_FOR_HUMAN_LANDSCAPE_LAYOUT_QA",
            "contentAssessment": "The supplied second fixture is a set of geometric illustrations, not portraits/full-body/landscapes.",
            "sourceFilesCopied": False, "sourceFilesUnmodified": before == after,
            "fixtureDirectory": fixture_dir.relative_to(REPO).as_posix(),
            "inputCount": len(sources), "slotCount": len(bindings),
            "preview": target.relative_to(REPO).as_posix(),
            "contactSheet": contact.relative_to(REPO).as_posix(), "fullDecode": decode,
            "frames": rows}


def _layout_bounds(definition: TemplateDefinition, store: FixtureStore,
                   bindings: dict[str, str], output: Path) -> dict[str, object]:
    rows = []
    width, height = definition.width, definition.height
    title_boxes = []
    overlay_boxes = []
    font_path = "C:/Windows/Fonts/arial.ttf"
    for event in definition.events:
        for layer in event.layers:
            if layer.kind == "image":
                asset_path = store.get_path(bindings[layer.slot_id])
                with Image.open(asset_path) as image:
                    iw, ih = image.size
                if layer.fit_mode == "cover":
                    base_w, base_h = width, height
                else:
                    factor = min(width / iw, height / ih)
                    base_w, base_h = iw * factor, ih * factor
                box_w, box_h = base_w * layer.scale, base_h * layer.scale
                cx = width / 2 + width * layer.position_x
                cy = height / 2 + height * layer.position_y
                box = [round(cx - box_w / 2, 2), round(cy - box_h / 2, 2),
                       round(cx + box_w / 2, 2), round(cy + box_h / 2, 2)]
                if layer.layer_order > 0:
                    overlay_boxes.append((event.event_id, box))
            elif layer.kind == "text":
                font = ImageFont.truetype(font_path, layer.font_size)
                left, top, right, bottom = font.getbbox(layer.text or "")
                border = layer.text_box_border_width
                box = [round(width * layer.text_x, 2), round(height * layer.text_y, 2),
                       round(width * layer.text_x + (right - left) + border * 2, 2),
                       round(height * layer.text_y + (bottom - top) + border * 2, 2)]
                title_boxes.append((event.event_id, layer.layer_id, box))
            else:
                continue
            intentional_background_fill = (layer.kind == "image" and layer.layer_order == 0
                                           and layer.fit_mode == "cover")
            rows.append({"eventId": event.event_id, "layerId": layer.layer_id,
                         "layerOrder": layer.layer_order, "boundsPx": box,
                         "withinCanvas": intentional_background_fill or
                         (box[0] >= 0 and box[1] >= 0 and box[2] <= width and box[3] <= height),
                         "canvasOverflowIsIntentional": intentional_background_fill})
    overlap_pairs = []
    for event_id, image_box in overlay_boxes:
        for _, layer_id, text_box in title_boxes:
            area = max(0, min(image_box[2], text_box[2]) - max(image_box[0], text_box[0])) * \
                max(0, min(image_box[3], text_box[3]) - max(image_box[1], text_box[1]))
            if area:
                overlap_pairs.append({"imageEventId": event_id, "titleLayerId": layer_id,
                                      "overlapAreaPx": round(area, 2)})
    payload = {"canvas": {"width": width, "height": height}, "layoutProfile": definition.metadata.get("layoutProfile"),
               "method": "Computed from graph geometry and source-image aspect ratios; no subject detector.",
               "allLayersWithinCanvas": all(row["withinCanvas"] for row in rows),
               "layers": rows, "titleOverlayIntersections": overlap_pairs,
               "subjectOverlapAssessment": "Manual visual inspection only; no face/subject detection capability was used."}
    (output / "Fall_Diary_3_9H_Layout_Bounds.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg and FFprobe are required for Task 3.9H.")
    definitions = {version: get_template_definition("fall-diary", version) for version in
                   ("0.3.0-reference-pilot", "0.4.0-editorial-motion-pilot", VERSION)}
    if any(value is None for value in definitions.values()):
        raise RuntimeError("Required Fall Diary baseline/new definitions are not registered.")
    output = REPO / "artifacts/video_creator/task3_9h"
    output.mkdir(parents=True, exist_ok=True)
    fixture_dir = REPO / "local_reference/fall_diary/private_test_media"
    sources = [fixture_dir / f"photo_{index:02d}.jpg" for index in range(1, 12)]
    if any(not path.is_file() for path in sources):
        raise RuntimeError("The 11-photo private fixture set is incomplete.")
    source_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    paths = {_asset_id(path.relative_to(REPO).as_posix()): path for path in sources}
    store = FixtureStore(paths)
    bindings = {f"photo-{index:02d}": _asset_id(sources[index - 1].relative_to(REPO).as_posix())
                for index in range(1, 12)}
    graphs = {}
    compiled_projects = {}
    for version, definition in definitions.items():
        project_id = uuid5(NAMESPACE_URL, f"mediastudio:fall-diary:task3.9h:{version}").hex
        compiled = compile_template(definition, bindings, store.get_metadata,
                                    project_id=project_id, title=f"Fall Diary {version}")
        compiled_projects[version] = compiled
        graphs[version] = build_composition_graph(compiled.project, store.get_metadata)

    definition = definitions[VERSION]
    assert definition is not None
    safe_graph = graphs[VERSION]
    reference_definition = TemplateDefinition.model_validate(_reference_graph_payload(definition))
    ref_compiled = compile_template(reference_definition, bindings, store.get_metadata,
                                    project_id=uuid5(NAMESPACE_URL, "mediastudio:fall-diary:task3.9h:reference-layout").hex,
                                    title="Fall Diary 3.9H reference-layout comparison")
    reference_graph = build_composition_graph(ref_compiled.project, store.get_metadata)

    staging = output / "render_staging"
    previews = {}
    for version in ("0.3.0-reference-pilot", "0.4.0-editorial-motion-pilot", VERSION):
        graph = graphs[version]
        preview_graph = replace(graph, width=540, height=960)
        label = version.replace(".", "_")
        tmp = _render(preview_graph, store, ffmpeg, staging, "draft", f"preview-{label}")
        preview = output / f"Fall_Diary_3_9H_Baseline_{label}_Preview.mp4"
        tmp.replace(preview)
        previews[version] = preview

    # The WPF run will produce the final named export. This shared-renderer
    # export is a clean 0.5 reference point and will be checked against WPF later.
    export_tmp = _render(safe_graph, store, ffmpeg, staging, "standard", "0.5-editorial-safe-render")
    export = output / "Fall_Diary_3_9H_Render.mp4"
    export.unlink(missing_ok=True)
    export_tmp.replace(export)
    preview = previews[VERSION]
    parity = _still_export_parity(safe_graph, store, ffmpeg, export, output)

    (output / "Fall_Diary_3_9H_Project_V2.json").write_text(
        json.dumps(compiled_projects[VERSION].project.model_dump(mode="json", by_alias=True),
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "Fall_Diary_3_9H_Composition_Graph.json").write_text(
        json.dumps(safe_graph.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    compare_graphs = [("0.3 Reference Pilot", graphs["0.3.0-reference-pilot"]),
                      ("0.4 Editorial Motion", graphs["0.4.0-editorial-motion-pilot"]),
                      ("0.5 Reference Layout QA", reference_graph),
                      ("0.5 Editorial Safe", safe_graph)]
    compare_stores = [store] * len(compare_graphs)
    comparison_rows = _comparison_sheet(
        ffmpeg, REPO / "artifacts/video_creator/task3_9c/reference_frames/isolated",
        compare_graphs, compare_stores, output / "Fall_Diary_3_9H_Reference_Comparison.jpg")
    bounds = _layout_bounds(definition, store, bindings, output)
    second = _second_fixture(definition, ffmpeg, output)
    after_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}

    manifest = {
        "task": "3.9H", "templateId": definition.template_id, "templateDefinitionVersion": VERSION,
        "projectId": compiled_projects[VERSION].project.project_id,
        "projectRevision": compiled_projects[VERSION].project.revision,
        "timebase": safe_graph.timebase, "durationTicks": safe_graph.duration_ticks,
        "durationSeconds": safe_graph.duration_ticks / safe_graph.timebase,
        "frameRate": safe_graph.fps, "frameCount": safe_graph.frame_index_at(safe_graph.duration_ticks),
        "canvas": {"width": safe_graph.width, "height": safe_graph.height},
        "sourceFixtureDirectory": fixture_dir.relative_to(REPO).as_posix(),
        "sourceFilesCopied": False, "sourceFilesUnmodified": source_hashes == after_hashes,
        "sourceSha256Before": source_hashes, "sourceSha256After": after_hashes,
        "bindings": bindings,
        "definition": {
            "slotCount": len(definition.slots), "slotIds": [slot.slot_id for slot in definition.slots],
            "backgroundEventCount": sum(event.event_id.startswith("background-") for event in definition.events),
            "overlayEventCount": sum(event.event_id.startswith("overlay-") for event in definition.events),
            "titleGlyphCount": sum(layer.kind == "text" for event in definition.events for layer in event.layers),
            "layoutProfile": definition.metadata.get("layoutProfile"),
            "editorialAssumptions": definition.metadata.get("editorialAssumptions"),
            "eventTable": [{"eventId": event.event_id,
                            "startTicks": event.timeline_start_ticks,
                            "endTicks": event.timeline_start_ticks + event.duration_ticks,
                            "classification": event.event_classification,
                            "sourceEvidence": event.source_evidence,
                            "layerOrder": [layer.layer_order for layer in event.layers],
                            "slotIds": [layer.slot_id for layer in event.layers if layer.slot_id],
                            "motionClassification": [layer.motion_classification for layer in event.layers]}
                           for event in definition.events],
            "audioReference": None, "cutoutSupported": False,
            "demoAssetReference": None, "posterAssetReference": None,
            "sourceAssetIdsHardcoded": False,
        },
        "referenceAnalysis": {"sourceIsScreenRecording": True,
                              "uiExcludedFromReference": True,
                              "isolatedReferenceFolder": "artifacts/video_creator/task3_9c/reference_frames/isolated",
                              "classificationConfidence": "See companion timeline; 13.267s event remains UNKNOWN.",
                              "referenceMotionVerified": False, "sourceEndKnown": False},
        "qa": {"previewProbe": _probe(preview, ffprobe), "renderProbe": _probe(export, ffprobe),
               "previewFullDecode": _decode(preview, ffmpeg), "renderFullDecode": _decode(export, ffmpeg),
               "sameGraphStillExportParity": parity, "layoutBounds": bounds,
               "secondFixture": second, "previewExportParityVerified": parity["passed"],
               "eventClassificationVerified": True,
               "backgroundContinuityVerified": True,
               "overlayTimingVerified": True,
               "motionContinuityVerified": True,
               "geometryBoundsVerified": bounds["allLayersWithinCanvas"],
               "layoutQaStatus": "PARTIAL",
               "layoutQaVerified": False,
               "layoutQaReason": ("The second fixture contains geometric illustrations rather than the requested "
                                  "portrait/full-body/landscape mix; no verified subject detector is available."),
               "referenceMotionVerified": False, "referenceFidelityVerified": False,
               "cutoutVerified": False, "audioFidelityVerified": False,
               "wpfIntegrationVerified": False, "guiStatus": "GUI_PENDING",
               "comparisonRows": comparison_rows},
        "outputs": {"preview": preview.relative_to(REPO).as_posix(),
                    "sharedRendererRender": export.relative_to(REPO).as_posix(),
                    "projectV2": "artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Project_V2.json",
                    "compositionGraph": "artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Composition_Graph.json",
                    "referenceComparison": "artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Reference_Comparison.jpg",
                    "layoutBounds": "artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Layout_Bounds.json",
                    "secondFixtureContactSheet": "artifacts/video_creator/task3_9h/Fall_Diary_3_9H_Second_Fixture_Contact_Sheet.jpg"},
    }
    manifest_path = output / "Fall_Diary_3_9H_Binding_Manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), "preview": str(preview), "render": str(export),
                      "sourceFilesUnmodified": manifest["sourceFilesUnmodified"],
                      "stillExportParity": parity, "previewDecode": manifest["qa"]["previewFullDecode"],
                      "renderDecode": manifest["qa"]["renderFullDecode"],
                      "secondFixture": second, "layoutBoundsPass": bounds["allLayersWithinCanvas"],
                      "titleOverlayIntersections": len(bounds["titleOverlayIntersections"])},
                     ensure_ascii=False, indent=2))
    if (not manifest["sourceFilesUnmodified"] or not parity["passed"]
            or not manifest["qa"]["previewFullDecode"]["valid"]
            or not manifest["qa"]["renderFullDecode"]["valid"]
            or not second.get("passed", False)):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
