"""Render the Fall Diary 3.9A pilot in an isolated QA artifact directory.

The script references the private test photos in place; it never copies them
into the artifact directory or into a template package.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid5, NAMESPACE_URL


REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from mediastudio.video_editor.composition_renderer import render_composition_project  # noqa: E402
from mediastudio.video_editor.composition import build_composition_graph  # noqa: E402
from mediastudio.video_editor.jobs import VideoJob  # noqa: E402
from mediastudio.video_editor.media_selection import get_template_definition  # noqa: E402
from mediastudio.video_editor.template_compiler import compile_template  # noqa: E402


class QaMediaStore:
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


def _asset_id(path: Path) -> str:
    return hashlib.sha256(path.relative_to(REPO).as_posix().encode("utf-8")).hexdigest()[:32]


def _probe(path: Path, ffprobe: str) -> dict[str, object]:
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    payload: dict[str, object]
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {"raw": result.stdout}
    return {"exitCode": result.returncode, "probe": payload, "stderr": result.stderr[-2000:]}


def _decode(path: Path, ffmpeg: str) -> dict[str, object]:
    result = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    return {
        "exitCode": result.returncode,
        "valid": result.returncode == 0 and not result.stderr.strip(),
        "stderr": result.stderr[-2000:],
    }


def _ssim(preview: Path, export: Path, ffmpeg: str, report_path: Path) -> dict[str, object]:
    if report_path.exists():
        report_path.unlink()
    # Keep the filter option free of Windows drive colons and spaces. The
    # subprocess working directory is the artifact directory, so a basename
    # is enough and the report remains next to the rendered outputs.
    stats_target = report_path.name
    command = [
        ffmpeg, "-v", "error", "-i", str(preview), "-i", str(export),
        "-filter_complex",
        "[0:v]format=yuv420p[preview];[1:v]scale=540:960:flags=lanczos,format=yuv420p[export];"
        "[preview][export]ssim=stats_file=" + stats_target + "[ssim]",
        "-map", "[ssim]", "-f", "null", "-",
    ]
    result = subprocess.run(command, cwd=report_path.parent, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
    lines = [line.strip() for line in report_path.read_text(encoding="utf-8").splitlines()] if report_path.is_file() else []
    values: list[float] = []
    for line in lines:
        for token in line.split():
            if token.startswith("All:"):
                try:
                    values.append(float(token.split(":", 1)[1]))
                except ValueError:
                    pass
    return {
        "exitCode": result.returncode,
        "valid": result.returncode == 0 and bool(values),
        "framesCompared": len(lines),
        "meanSsim": sum(values) / len(values) if values else None,
        "minSsim": min(values) if values else None,
        "stderr": result.stderr[-2000:],
    }


def main() -> int:
    definition = get_template_definition("fall-diary")
    if definition is None:
        raise RuntimeError("Fall Diary pilot definition was not found.")
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg and FFprobe are required for the pilot render.")

    output_dir = REPO / "artifacts" / "video_creator" / "task3_9a"
    output_dir.mkdir(parents=True, exist_ok=True)
    source_dir = REPO / "local_reference" / "fall_diary" / "private_test_media"
    source_paths = {f"photo-{index:02d}": source_dir / f"photo_{index:02d}.jpg" for index in range(1, 13)}
    if any(not path.is_file() for path in source_paths.values()):
        raise RuntimeError("The Fall Diary private test media set is incomplete.")
    assets = {_asset_id(path): path for path in source_paths.values()}
    store = QaMediaStore(assets)
    bindings = {
        f"photo-{index:02d}": _asset_id(source_dir / f"photo_{index:02d}.jpg")
        for index in range(1, 13)
    }
    project_id = uuid5(NAMESPACE_URL, "mediastudio:fall-diary:task3.9a:first-render").hex
    compiled = compile_template(
        definition, bindings, store.get_metadata, project_id=project_id, title="Fall Diary First Render",
    )
    graph_object = build_composition_graph(compiled.project, store.get_metadata)
    graph = graph_object.to_dict()
    project_path = output_dir / "Fall_Diary_Project_V2.json"
    graph_path = output_dir / "Fall_Diary_Composition_Graph.json"
    project_path.write_text(
        json.dumps(compiled.project.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")

    render_dir = output_dir / "_render_staging"
    render_dir.mkdir(parents=True, exist_ok=True)
    export_job = VideoJob(job_id="a" * 32, project_id=project_id, job_type="fall-diary-export")
    render_composition_project(export_job, graph_object, store, ffmpeg, render_dir, "draft")
    if export_job.output_path is None or not export_job.output_path.is_file():
        raise RuntimeError(f"Export render failed: {export_job.error}")
    export_path = output_dir / "Fall_Diary_First_Render.mp4"
    export_job.output_path.replace(export_path)

    preview_graph = replace(graph_object, width=540, height=960)
    preview_job = VideoJob(job_id="b" * 32, project_id=project_id, job_type="fall-diary-preview")
    render_composition_project(preview_job, preview_graph, store, ffmpeg, render_dir, "draft")
    if preview_job.output_path is None or not preview_job.output_path.is_file():
        raise RuntimeError(f"Preview render failed: {preview_job.error}")
    preview_path = output_dir / "Fall_Diary_First_Preview.mp4"
    preview_job.output_path.replace(preview_path)

    ssim_path = output_dir / "preview_export_ssim.log"
    manifest = {
        "task": "3.9A",
        "templateId": definition.template_id,
        "templateDefinitionVersion": definition.version,
        "projectId": project_id,
        "sourceDirectory": "local_reference/fall_diary/private_test_media",
        "sourceFilesCopied": False,
        "bindings": {
            slot: {
                "assetId": asset_id,
                "source": str(store.get_path(asset_id).relative_to(REPO)).replace("\\", "/"),
                "sha256": hashlib.sha256(store.get_path(asset_id).read_bytes()).hexdigest(),
            }
            for slot, asset_id in sorted(bindings.items())
        },
        "definition": {
            "slots": len(definition.slots),
            "events": len(definition.events),
            "visualTracks": len([track for track in compiled.project.tracks if track.kind == "visual"]),
            "textTracks": len([track for track in compiled.project.tracks if track.kind == "text"]),
            "multiLayerEvents": sum(sum(layer.kind in {"image", "video"} for layer in event.layers) > 1
                                     for event in definition.events),
            "supportedCapabilities": list(definition.supported_capabilities),
        },
        "output": {
            "preview": str(preview_path.relative_to(REPO)).replace("\\", "/"),
            "export": str(export_path.relative_to(REPO)).replace("\\", "/"),
            "previewProbe": _probe(preview_path, ffprobe),
            "exportProbe": _probe(export_path, ffprobe),
            "previewFullDecode": _decode(preview_path, ffmpeg),
            "exportFullDecode": _decode(export_path, ffmpeg),
            "previewExportSsim": _ssim(preview_path, export_path, ffmpeg, ssim_path),
        },
    }
    (output_dir / "Fall_Diary_Render_Manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps({
        "project": str(project_path),
        "graph": str(graph_path),
        "preview": str(preview_path),
        "export": str(export_path),
        "manifest": str(output_dir / "Fall_Diary_Render_Manifest.json"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
