"""Render same-binding Fall Diary 0.3-0.5 layout comparisons for local QA."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from PIL import Image, ImageDraw, ImageFont, ImageOps

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "tools" / "video_creator"))

from render_fall_diary_task39h import (  # noqa: E402
    FixtureStore,
    TIMEBASE,
    _asset_id,
    _decode,
    _extract,
    _probe,
    _reference_graph_payload,
    _render,
)
from mediastudio.video_editor.composition import build_composition_graph  # noqa: E402
from mediastudio.video_editor.media_selection import get_template_definition  # noqa: E402
from mediastudio.video_editor.template_compiler import TemplateDefinition, compile_template  # noqa: E402


VERSION_03 = "0.3.0-reference-pilot"
VERSION_04 = "0.4.0-editorial-motion-pilot"
VERSION_05 = "0.5.0-layer-structure-pilot"
SAMPLE_TIMES = [3.766667, 5.266667, 6.766667, 9.266667, 10.266667, 13.766667]
PARITY_TIMES = [
    0.5, 3.733333, 3.766667, 5.233333, 5.266667, 5.733333, 5.766667,
    6.733333, 6.766667, 9.233333, 9.266667, 9.733333, 9.766667,
    10.233333, 10.266667, 13.233333, 13.266667, 13.733333, 13.766667,
    15.033333, 15.066667, 16.5,
]
PROFILES = [
    ("0.3 Reference Pilot", "0_3_Reference_Pilot", VERSION_03, False),
    ("0.4 Editorial Motion", "0_4_Editorial_Motion_Pilot", VERSION_04, False),
    ("0.5 Reference Layout QA", "0_5_Reference_Layout_QA", VERSION_05, True),
    ("0.5 Editorial Safe", "0_5_Editorial_Safe", VERSION_05, False),
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _save_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _render_profile(graph, store: FixtureStore, ffmpeg: str, staging: Path,
                    output_dir: Path, suffix: str, label: str, quality: str,
                    width: int, height: int) -> Path:
    target_graph = replace(graph, width=width, height=height)
    rendered = _render(target_graph, store, ffmpeg, staging, quality, label)
    target = output_dir / f"Fall_Diary_3_9I_{suffix}_{'Preview' if quality == 'draft' else 'Export'}.mp4"
    if target.exists():
        target.unlink()
    rendered.replace(target)
    return target


def _comparison_sheet(ffmpeg: str, reference_dir: Path, previews: list[tuple[str, Path]],
                      output_dir: Path) -> list[dict[str, object]]:
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 18)
    tile = (270, 480)
    header_height = 38
    row_height = tile[1] + header_height
    labels = ["Muse reference", *[label for label, _ in previews]]
    sheet = Image.new("RGB", (tile[0] * len(labels), header_height + row_height * len(SAMPLE_TIMES)), "#eef1f7")
    draw = ImageDraw.Draw(sheet)
    for index, label in enumerate(labels):
        draw.text((index * tile[0] + 8, 10), label, fill="#1c2230", font=font)

    rows = []
    for row_index, seconds in enumerate(SAMPLE_TIMES):
        time_label = f"{seconds:.3f}".replace(".", "_")
        reference = reference_dir / f"preview_t{time_label}.jpg"
        if not reference.is_file():
            raise FileNotFoundError(f"Missing isolated Muse frame: {reference}")
        top = header_height + row_index * row_height
        draw.text((8, top + 7), f"t={seconds:.3f}s", fill="#1c2230", font=font)
        with Image.open(reference) as image:
            ref_tile = ImageOps.contain(image.convert("RGB"), tile, Image.Resampling.LANCZOS)
        sheet.paste(ref_tile, (0, top + header_height + (tile[1] - ref_tile.height) // 2))
        frame_index = round(seconds * 30)
        row_record = {"timeSeconds": seconds, "frameIndex": frame_index, "referenceFrame": reference.name}
        for column, (label, video) in enumerate(previews, start=1):
            frame_path = output_dir / "contact_sheet_frames" / f"{column}_{frame_index:04d}.png"
            frame_path.parent.mkdir(parents=True, exist_ok=True)
            _extract(video, ffmpeg, frame_index, frame_path)
            with Image.open(frame_path) as image:
                frame = ImageOps.contain(image.convert("RGB"), tile, Image.Resampling.LANCZOS)
            sheet.paste(frame, (column * tile[0], top + header_height + (tile[1] - frame.height) // 2))
            row_record[label] = {"video": video.name, "frameSha256": _sha256(frame_path)}
        rows.append(row_record)

    sheet_path = output_dir / "Fall_Diary_3_9I_Comparison_Contact_Sheet.jpg"
    sheet.save(sheet_path, quality=94)
    return rows


def _scaled_parity(preview: Path, export: Path, ffmpeg: str, output_dir: Path,
                   suffix: str) -> dict[str, object]:
    from PIL import ImageChops, ImageStat

    measurements = []
    for seconds in PARITY_TIMES:
        frame_index = round(seconds * 30)
        preview_frame = output_dir / "parity_frames" / f"{suffix}_preview_{frame_index:04d}.png"
        export_frame = output_dir / "parity_frames" / f"{suffix}_export_{frame_index:04d}.png"
        preview_frame.parent.mkdir(parents=True, exist_ok=True)
        _extract(preview, ffmpeg, frame_index, preview_frame)
        _extract(export, ffmpeg, frame_index, export_frame)
        with Image.open(preview_frame) as preview_image, Image.open(export_frame) as export_image:
            preview_rgb = preview_image.convert("RGB")
            export_rgb = export_image.convert("RGB").resize(preview_rgb.size, Image.Resampling.LANCZOS)
            mae = sum(ImageStat.Stat(ImageChops.difference(preview_rgb, export_rgb)).mean) / 3
        measurements.append({"frameIndex": frame_index, "timeSeconds": seconds,
                             "meanAbsoluteErrorRgb": round(mae, 5)})
    errors = [item["meanAbsoluteErrorRgb"] for item in measurements]
    return {
        "method": "Matched frame indices; scale 1080x1920 export to 540x960 with Lanczos; RGB MAE",
        "framesCompared": len(measurements),
        "meanAbsoluteErrorRgb": round(sum(errors) / len(errors), 5),
        "maxMeanAbsoluteErrorRgb": max(errors),
        "threshold": {"meanMax": 12, "frameMax": 24},
        "passed": sum(errors) / len(errors) <= 12 and max(errors) <= 24,
        "samples": measurements,
    }


def main() -> int:
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg and FFprobe are required for Task 3.9I.")

    fixture_dir = REPO / "local_reference" / "fall_diary" / "private_test_media"
    sources = [fixture_dir / f"photo_{index:02d}.jpg" for index in range(1, 12)]
    if any(not path.is_file() for path in sources):
        raise RuntimeError("The authorized local QA fixture set is incomplete.")
    source_hashes = {path.name: _sha256(path) for path in sources}
    asset_paths = {_asset_id(path.relative_to(REPO).as_posix()): path for path in sources}
    store = FixtureStore(asset_paths)
    definitions = {
        VERSION_03: get_template_definition("fall-diary", VERSION_03),
        VERSION_04: get_template_definition("fall-diary", VERSION_04),
        VERSION_05: get_template_definition("fall-diary", VERSION_05),
    }
    if any(definition is None for definition in definitions.values()):
        raise RuntimeError("A required Fall Diary 0.3, 0.4, or 0.5 definition is unavailable.")
    bindings = {
        f"photo-{index:02d}": _asset_id(sources[index - 1].relative_to(REPO).as_posix())
        for index in range(1, 12)
    }
    output_dir = REPO / "artifacts" / "video_creator" / "task3_9i"
    output_dir.mkdir(parents=True, exist_ok=True)
    staging = output_dir / "render_staging"
    records = []
    preview_records = []
    parity_records = {}

    for label, suffix, version, reference_layout in PROFILES:
        definition = definitions[version]
        if definition is None:
            raise RuntimeError(f"Definition {version} is unexpectedly missing.")
        if reference_layout:
            definition = TemplateDefinition.model_validate(_reference_graph_payload(definition))
        project_id = uuid5(NAMESPACE_URL, f"mediastudio:fall-diary:task3.9i:{suffix}").hex
        compiled = compile_template(definition, bindings, store.get_metadata,
                                    project_id=project_id, title=f"Fall Diary 3.9I {label}")
        graph = build_composition_graph(compiled.project, store.get_metadata)
        _save_json(output_dir / f"Fall_Diary_3_9I_Project_V2_{suffix}.json",
                   compiled.project.model_dump(mode="json", by_alias=True))
        _save_json(output_dir / f"Fall_Diary_3_9I_Composition_Graph_{suffix}.json", graph.to_dict())
        preview = _render_profile(graph, store, ffmpeg, staging, output_dir, suffix,
                                  f"preview-{suffix}", "draft", 540, 960)
        preview_records.append((label, preview))
        records.append({
            "profile": label,
            "definitionVersion": version,
            "layoutProfile": definition.metadata.get("layoutProfile"),
            "projectId": compiled.project.project_id,
            "projectRevision": compiled.project.revision,
            "preview": preview.relative_to(REPO).as_posix(),
            "previewProbe": _probe(preview, ffprobe),
            "previewFullDecode": _decode(preview, ffmpeg),
            "projectV2": f"Fall_Diary_3_9I_Project_V2_{suffix}.json",
            "compositionGraph": f"Fall_Diary_3_9I_Composition_Graph_{suffix}.json",
        })
        if version == VERSION_05:
            export = _render_profile(graph, store, ffmpeg, staging, output_dir, suffix,
                                     f"export-{suffix}", "standard", 1080, 1920)
            records[-1]["export"] = export.relative_to(REPO).as_posix()
            records[-1]["exportProbe"] = _probe(export, ffprobe)
            records[-1]["exportFullDecode"] = _decode(export, ffmpeg)
            parity_records[label] = _scaled_parity(preview, export, ffmpeg, output_dir, suffix)

    reference_dir = REPO / "artifacts" / "video_creator" / "task3_9c" / "reference_frames" / "isolated"
    comparison_rows = _comparison_sheet(ffmpeg, reference_dir, preview_records, output_dir)
    after_hashes = {path.name: _sha256(path) for path in sources}
    fixture_manifest = {
        "task": "3.9I",
        "fixturePurpose": "Local, private QA only; not for product, package, public artifact, or Git distribution.",
        "sourceFixtureDirectory": fixture_dir.relative_to(REPO).as_posix(),
        "sourceFilesCopied": False,
        "sourceFilesModified": source_hashes != after_hashes,
        "sourceSha256Before": source_hashes,
        "sourceSha256After": after_hashes,
        "timebase": TIMEBASE,
        "frameRate": "30/1",
        "durationSeconds": 17,
        "mediaBindings": {
            slot: {"assetId": asset_id, "sourceFile": asset_paths[asset_id].name}
            for slot, asset_id in bindings.items()
        },
        "profiles": records,
        "previewExportParity": parity_records,
        "comparisonContactSheet": "Fall_Diary_3_9I_Comparison_Contact_Sheet.jpg",
        "comparisonRows": comparison_rows,
    }
    _save_json(output_dir / "Fall_Diary_3_9I_QA_Manifest.json", fixture_manifest)
    return 0 if source_hashes == after_hashes and all(
        record["previewFullDecode"]["valid"]
        and (record.get("exportFullDecode", {}).get("valid", True))
        for record in records
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
