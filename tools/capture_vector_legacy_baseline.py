"""Capture the unmodified legacy pipeline once, including a source fingerprint."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from xml.etree import ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from PIL import Image
from mediastudio.image_tools.vectorize import VectorizeService
from mediastudio.jobs.manager import Job
from mediastudio.storage.assets import Asset


def main() -> None:
    destination = ROOT / "backend/tests/baselines/vectorization"
    marker = destination / "active_fox_legacy_metrics.json"
    if marker.exists():
        raise SystemExit("Baseline already exists; refusing to overwrite the frozen result.")
    fixture = ROOT / "backend/tests/fixtures/active_fox.jpg"
    renderer = ROOT / "tools/VectorDiagnostics/bin/Debug/net9.0/VectorDiagnostics.dll"
    if not renderer.is_file():
        raise SystemExit("Build tools/VectorDiagnostics before capturing the baseline.")
    legacy_files = sorted(set(
        list((ROOT / "backend/mediastudio").rglob("*.py"))
        + list((ROOT / "backend").glob("requirements*.txt"))
        + [ROOT / "backend/setup.ps1"]
    ))
    fingerprints = {str(p.relative_to(ROOT)).replace("\\", "/"):
                    hashlib.sha256(p.read_bytes()).hexdigest() for p in legacy_files}
    with Image.open(fixture) as image:
        width, height = image.size
        asset = Asset("a" * 32, fixture, fixture.name, width, height,
                      fixture.stat().st_size, image.mode)
        reference = image.convert("RGBA")
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="legacy-baseline-") as directory:
        result = VectorizeService().run(
            Job("baseline", asset.asset_id), asset,
            engine="auto", mode="auto", color_count=None, simplification=None,
            smooth_paths=True, transparent_background=True, output_directory=Path(directory),
        )
        svg_path = destination / "active_fox_legacy.svg"
        shutil.copy2(result[0], svg_path)
    render_path = destination / "active_fox_legacy_render.png"
    subprocess.run(["dotnet", str(renderer), str(svg_path), str(render_path), str(width)], check=True)
    # Existing helper is called unchanged; the baseline algorithm is not patched.
    VectorizeService._remove_border_background(reference).save(destination / "legacy_foreground.png")
    root = ET.parse(svg_path).getroot()
    elements = [element.tag.rsplit("}", 1)[-1] for element in root.iter()]
    with Image.open(render_path) as render:
        render_width, render_height = render.size
    packages = {}
    for name in ("Pillow", "numpy", "opencv-python", "vtracer", "easyocr", "torch", "torchvision"):
        packages[name] = importlib.metadata.version(name)
    metrics = {
        "paths": elements.count("path"),
        "gradients": elements.count("linearGradient") + elements.count("radialGradient"),
        "text_elements": elements.count("text"),
        "svg_size_bytes": svg_path.stat().st_size,
        "render_width": render_width, "render_height": render_height,
        "view_box": root.get("viewBox"), "engine": result[5],
        "legacy_reported_metrics": result[6],
        "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "svg_sha256": hashlib.sha256(svg_path.read_bytes()).hexdigest(),
        "source_sha256": fingerprints, "python": sys.version, "packages": packages,
        "request": {"engine": "auto", "mode": "auto", "color_count": None,
                    "simplification": None, "smooth_paths": True, "transparent_background": True},
    }
    for relative, expected in fingerprints.items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Legacy source changed during capture: {relative}")
    with zipfile.ZipFile(destination / "legacy_source_snapshot.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in legacy_files:
            archive.write(path, path.relative_to(ROOT))
    marker.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: metrics[k] for k in ("paths", "gradients", "text_elements",
                     "svg_size_bytes", "render_width", "render_height")}, indent=2))


if __name__ == "__main__":
    main()
