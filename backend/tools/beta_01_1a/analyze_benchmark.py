from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont
from skimage.color import deltaE_ciede2000, rgb2lab

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
PACK = REPO / "mediastudio_beta_testpack"
OUT = BACKEND / "artifacts" / "contour_preserving" / "beta_01_1a"
sys.path.insert(0, str(BACKEND))

from tools.vectorization_benchmark.svg import render_svg_edge, validate_svg  # noqa: E402
from tools.task_08b_1_1.diagnostics import _lab_neighbor_delta  # noqa: E402

SVG_NS = "http://www.w3.org/2000/svg"
DETAIL_IDS = ["D01_small_colored_islands", "D02_thin_orbits", "D03_corner_spikes", "D04_nested_counters",
              "A01_outline_stroke", "A02_translucent_overlays", "A03_ring_cutout", "A04_transparent_fine_lines"]
ALPHA_IDS = {"A01_outline_stroke", "A02_translucent_overlays", "A03_ring_cutout", "A04_transparent_fine_lines"}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def load_rgba(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"), dtype=np.uint8)


def alpha_iou(a: np.ndarray, b: np.ndarray, threshold: int) -> float:
    am = a[..., 3] > threshold
    bm = b[..., 3] > threshold
    union = int(np.count_nonzero(am | bm))
    return float(np.count_nonzero(am & bm) / max(union, 1))


def bbox(mask: np.ndarray, pad: int = 0) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(mask)
    if not len(xs):
        return None
    h, w = mask.shape[:2]
    return (max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad),
            min(w, int(xs.max()) + 1 + pad), min(h, int(ys.max()) + 1 + pad))


def composite(rgba: np.ndarray, color: str | tuple[int, int, int] = "white") -> np.ndarray:
    base = np.asarray(ImageColor.getrgb(color) if isinstance(color, str) else color, dtype=np.float32)
    alpha = rgba[..., 3:4].astype(np.float32) / 255.0
    return np.rint(rgba[..., :3].astype(np.float32) * alpha + base.reshape(1, 1, 3) * (1.0 - alpha)).clip(0, 255).astype(np.uint8)


def checkerboard(size: tuple[int, int], tile: int = 16) -> Image.Image:
    w, h = size
    yy, xx = np.indices((h, w))
    v = np.where(((xx // tile + yy // tile) % 2) == 0, 230, 190).astype(np.uint8)
    return Image.fromarray(np.repeat(v[..., None], 3, axis=2), "RGB")


def composite_named(rgba: np.ndarray, bg: str) -> Image.Image:
    if bg == "checkerboard":
        base = np.asarray(checkerboard((rgba.shape[1], rgba.shape[0])), dtype=np.uint8)
    else:
        base = np.asarray(ImageColor.getrgb(bg), dtype=np.uint8)
        base = np.broadcast_to(base.reshape(1, 1, 3), rgba.shape[:2] + (3,)).copy()
    alpha = rgba[..., 3:4].astype(np.float32) / 255.0
    return Image.fromarray(np.rint(rgba[..., :3] * alpha + base * (1.0 - alpha)).clip(0, 255).astype(np.uint8), "RGB")


def _edge(mask: np.ndarray) -> np.ndarray:
    return cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0


def _component_count(mask: np.ndarray) -> int:
    return max(0, int(cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)[0]) - 1)


def _hole_count(mask: np.ndarray) -> int:
    contours, hierarchy = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return 0
    return sum(1 for row in hierarchy[0] if row[3] >= 0)


def boundary_metrics(reference: np.ndarray, candidate: np.ndarray, tolerance_px: float = 2.0) -> dict[str, Any]:
    ref = _edge(reference)
    cand = _edge(candidate)
    ref_count, cand_count = int(ref.sum()), int(cand.sum())
    if not ref_count or not cand_count:
        return {"precisionAtTolerance": 0.0, "recallAtTolerance": 0.0, "f1AtTolerance": 0.0,
                "meanSymmetricDistancePx": None, "p95SymmetricDistancePx": None,
                "referenceBoundaryPixels": ref_count, "candidateBoundaryPixels": cand_count,
                "tolerancePx": tolerance_px}
    dist_to_ref = cv2.distanceTransform((~ref).astype(np.uint8), cv2.DIST_L2, 3)
    dist_to_cand = cv2.distanceTransform((~cand).astype(np.uint8), cv2.DIST_L2, 3)
    d_candidate = dist_to_ref[cand]
    d_reference = dist_to_cand[ref]
    precision = float(np.mean(d_candidate <= tolerance_px))
    recall = float(np.mean(d_reference <= tolerance_px))
    f1 = 2 * precision * recall / max(precision + recall, 1e-12)
    distances = np.concatenate([d_candidate.astype(np.float32), d_reference.astype(np.float32)])
    return {"precisionAtTolerance": precision, "recallAtTolerance": recall, "f1AtTolerance": f1,
            "meanSymmetricDistancePx": float(np.mean(distances)), "p95SymmetricDistancePx": float(np.quantile(distances, .95)),
            "referenceBoundaryPixels": ref_count, "candidateBoundaryPixels": cand_count,
            "tolerancePx": tolerance_px}


def _summary(values: np.ndarray) -> dict[str, Any]:
    if values.size == 0:
        return {"count": 0, "mean": None, "p95": None, "maximum": None}
    return {"count": int(values.size), "mean": float(values.mean()), "p95": float(np.quantile(values, .95)),
            "maximum": float(values.max())}


def color_metrics(target: np.ndarray, output: np.ndarray, target_alpha_floor: int = 16) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    target_mask = target[..., 3] > target_alpha_floor
    output_mask = output[..., 3] > target_alpha_floor
    common = target_mask & output_mask
    lab_target = rgb2lab(target[..., :3].astype(np.float32) / 255.0)
    lab_output = rgb2lab(output[..., :3].astype(np.float32) / 255.0)
    de = deltaE_ciede2000(lab_target, lab_output).astype(np.float32)
    selected = de[common]
    out: dict[str, Any] = {
        "colorSpace": "CIEDE2000 (ΔE00)",
        "comparisonTarget": "original reference SVG Edge render" if target_alpha_floor == 16 else "analytic source",
        "commonForegroundPixels": int(common.sum()),
        "meanDeltaE00": _summary(selected)["mean"],
        "p95DeltaE00": _summary(selected)["p95"],
        "maximumDeltaE00": _summary(selected)["maximum"],
        "referenceForegroundPixels": int(target_mask.sum()),
        "outputForegroundPixels": int(output_mask.sum()),
        "sourceCompositeBackground": "not composited; compare native SVG colors on common foreground",
    }
    ref_edge = _edge(target_mask)
    distance = cv2.distanceTransform((~ref_edge).astype(np.uint8), cv2.DIST_L2, 3)
    boundary_band = common & (distance <= 2.0)
    interior = common & (distance > 2.0)
    out["boundaryBandDeltaE00"] = _summary(de[boundary_band])
    out["interiorDeltaE00"] = _summary(de[interior])
    return out, de, common


def analytic_g04() -> np.ndarray:
    y, x = np.mgrid[0:512, 0:512]
    dx = (x.astype(np.float64) - 255.5) / 192.0
    dy = (y.astype(np.float64) - 255.5) / 192.0
    radius = np.sqrt(dx * dx + dy * dy)
    angle = np.arctan2(dy, dx)
    clipped = np.clip(radius, 0.0, 1.0)
    rgb = np.stack((41 + 101 * clipped + 14 * np.sin(2 * angle) * np.exp(-2 * radius * radius),
                    74 + 78 * clipped + 19 * np.sin(angle) * np.cos(2 * radius),
                    120 + 11 * clipped - 35 * np.sin(angle) * np.exp(-radius * radius)), axis=-1)
    alpha = np.clip((200.5 - np.hypot(x - 255.5, y - 255.5)) * 255.0, 0.0, 255.0)
    return np.dstack((np.rint(np.clip(rgb, 0, 255)), np.rint(alpha))).astype(np.uint8)


def parse_svg_fill_colors(path: Path) -> list[str]:
    root = ET.parse(path).getroot()
    values: set[str] = set()
    for element in root.iter():
        fill = element.attrib.get("fill")
        if fill is None:
            style = element.attrib.get("style", "")
            match = re.search(r"(?:^|;)\s*fill\s*:\s*([^;]+)", style, re.I)
            fill = match.group(1).strip() if match else None
        if not fill or fill.lower() == "none" or fill.startswith("url("):
            continue
        try:
            rgb = ImageColor.getrgb(fill.strip())[:3]
            values.add("#{:02X}{:02X}{:02X}".format(*rgb))
        except (ValueError, OSError):
            continue
    return sorted(values)


def flat_color_classes(reference: np.ndarray, output: np.ndarray, svg_path: Path) -> list[dict[str, Any]]:
    ref_lab = rgb2lab(reference[..., :3].astype(np.float32) / 255.0)
    out_lab = rgb2lab(output[..., :3].astype(np.float32) / 255.0)
    alpha = reference[..., 3] > 240
    rows = []
    for fill in parse_svg_fill_colors(svg_path):
        rgb = np.asarray(ImageColor.getrgb(fill), dtype=np.uint8).reshape(1, 1, 3)
        swatch_lab = rgb2lab(rgb.astype(np.float32) / 255.0)[0, 0]
        ref_de = np.linalg.norm(ref_lab - swatch_lab.reshape(1, 1, 3), axis=2)
        region = alpha & (ref_de <= 1.5)
        if not region.any():
            continue
        de00 = deltaE_ciede2000(ref_lab[region], out_lab[region])
        rows.append({"referenceFill": fill, "referenceCorePixelCount": int(region.sum()),
                     "meanDeltaE00": float(np.mean(de00)), "p95DeltaE00": float(np.quantile(de00, .95)),
                     "classDefinition": "reference render pixels within CIE76 1.5 of an explicit solid SVG fill; neighboring same-color elements can share a class"})
    return rows


def make_comparison_sheets(items: dict[str, dict[str, Any]], rendered: dict[str, dict[str, np.ndarray]],
                           references: dict[str, np.ndarray]) -> list[str]:
    out_dir = OUT / "visual_comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    groups = {
        "C_flat_color": [fid for fid in items if fid.startswith("C")],
        "D_detail": [fid for fid in items if fid.startswith("D")],
        "A_transparency_stroke": [fid for fid in items if fid.startswith("A")],
        "G_gradient_stress": [fid for fid in items if fid.startswith("G")],
    }
    written = []
    font = ImageFont.load_default()
    labels = ["SOURCE", "REFERENCE SVG", "SMART V2", "CONTOUR"]
    for group, ids in groups.items():
        panel_w, panel_h, label_h, fixture_h = 232, 232, 26, 24
        row_h = fixture_h + label_h + panel_h
        canvas = Image.new("RGB", (len(labels) * panel_w, len(ids) * row_h), "#ededed")
        draw = ImageDraw.Draw(canvas)
        for row_idx, fid in enumerate(ids):
            y0 = row_idx * row_h
            draw.text((4, y0 + 4), fid, fill="#111111", font=font)
            files = [PACK / str(items[fid]["png_paths"]["512"]), None, None, None]
            source = load_rgba(files[0])
            panes = [composite_named(source, "white")]
            panes.append(composite_named(references[fid], "white") if fid in references else composite_named(analytic_g04(), "white"))
            panes.append(composite_named(rendered[fid]["smart_reconstruction"], "white"))
            panes.append(composite_named(rendered[fid]["contour_preserving"], "white"))
            for col, (label, pane) in enumerate(zip(labels, panes)):
                x0 = col * panel_w
                shown_label = "ANALYTIC 2D REF" if fid == "G04_nonlinear_2d_analytic" and col == 1 else label
                draw.text((x0 + 4, y0 + fixture_h + 5), shown_label, fill="#333333", font=font)
                resized = pane.resize((panel_w, panel_h), Image.Resampling.LANCZOS)
                canvas.paste(resized, (x0, y0 + fixture_h + label_h))
        path = out_dir / f"comparison_{group}.png"
        canvas.save(path)
        written.append(str(path))
    return written


def _diagnostic_images(fid: str, engine: str, source: np.ndarray, target: np.ndarray,
                       output: np.ndarray, de: np.ndarray, common: np.ndarray) -> list[str]:
    base = OUT / "roi_diagnostics" / fid / engine
    base.mkdir(parents=True, exist_ok=True)
    ref_mask = target[..., 3] > 16
    out_mask = output[..., 3] > 16
    xor = ref_mask ^ out_mask
    if common.any():
        threshold = float(np.quantile(de[common], .95))
        color_errors = common & (de >= threshold) if threshold > 0 else np.zeros_like(common)
    else:
        color_errors = np.zeros_like(common)
    error = xor | color_errors
    roi = bbox(error, pad=28) if error.any() else bbox(ref_mask | out_mask, pad=20)
    if roi is None:
        roi = (0, 0, 128, 128)
    x0, y0, x1, y1 = roi

    overlay = composite_named(target, "white").convert("RGB")
    arr = np.asarray(overlay).copy()
    ref_edge = _edge(ref_mask)
    out_edge = _edge(out_mask)
    arr[ref_edge & out_edge] = (255, 220, 0)
    arr[ref_edge & ~out_edge] = (255, 40, 40)
    arr[out_edge & ~ref_edge] = (0, 210, 255)
    Image.fromarray(arr).save(base / "boundary_overlay.png")

    heat = cv2.applyColorMap(np.clip(de * 4.0, 0, 255).astype(np.uint8), cv2.COLORMAP_INFERNO)[..., ::-1]
    heat[~common] = (22, 22, 22)
    Image.fromarray(heat).save(base / "deltaE00_heatmap.png")

    missing_extra = np.zeros((*ref_mask.shape, 3), np.uint8)
    missing_extra[ref_mask & ~out_mask] = (255, 50, 50)
    missing_extra[out_mask & ~ref_mask] = (0, 190, 255)
    missing_extra[ref_mask & out_mask] = (80, 150, 80)
    Image.fromarray(missing_extra).save(base / "missing_extra_pixels.png")

    alpha_diff = np.abs(target[..., 3].astype(np.int16) - output[..., 3].astype(np.int16)).astype(np.uint8)
    Image.fromarray(alpha_diff, "L").save(base / "alpha_difference.png")

    comparison_panels = [composite_named(source, "white"), composite_named(target, "white"), composite_named(output, "white")]
    comparison_labels = ["SOURCE", "REFERENCE", "ENGINE OUTPUT"]
    for scale in (2, 4):
        crops = [panel.crop((x0, y0, x1, y1)).resize(((x1 - x0) * scale, (y1 - y0) * scale), Image.Resampling.NEAREST)
                 for panel in comparison_panels]
        label_h = 24
        board = Image.new("RGB", (sum(image.width for image in crops), max(image.height for image in crops) + label_h), "#efefef")
        draw = ImageDraw.Draw(board)
        cursor = 0
        for label, image in zip(comparison_labels, crops):
            draw.text((cursor + 4, 4), label, fill="#111111", font=ImageFont.load_default())
            board.paste(image, (cursor, label_h))
            cursor += image.width
        board.save(base / f"roi_zoom_{scale}x.png")
    return [str(x) for x in sorted(base.iterdir()) if x.is_file()]


def make_blind_review(items: dict[str, dict[str, Any]], rendered: dict[str, dict[str, np.ndarray]]) -> tuple[str, str]:
    blind_root = OUT / "blind_review"
    blind_root.mkdir(parents=True, exist_ok=True)
    assets_root = blind_root / "assets"
    assets_root.mkdir(exist_ok=True)
    mapping: dict[str, Any] = {"schemaVersion": 1, "mappingIsSeparateFromReviewPages": True, "assignments": {}}
    pages: list[str] = []
    for fid in items:
        folder = assets_root / fid
        folder.mkdir(parents=True, exist_ok=True)
        source_path = PACK / str(items[fid]["png_paths"]["512"])
        shutil.copy2(source_path, folder / "source.png")
        flip = hashlib.sha256(("blind-review|" + fid).encode("utf-8")).digest()[0] & 1
        candidates = ["smart_reconstruction", "contour_preserving"]
        labels: dict[str, str] = {}
        for idx, engine in enumerate(candidates):
            label = ("B" if idx == flip else "A")
            labels[engine] = label
            Image.fromarray(rendered[fid][engine], "RGBA").save(folder / f"candidate_{label}.png")
        mapping["assignments"][fid] = labels
        title = html.escape(fid)
        page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Blind review — {title}</title><style>
body{{font:15px Segoe UI,Arial,sans-serif;margin:18px;background:#f4f4f5;color:#18181b}}header{{position:sticky;top:0;background:#fff;padding:12px;border:1px solid #ddd;z-index:2}}
.row{{display:grid;grid-template-columns:repeat(3,minmax(220px,1fr));gap:12px;margin:12px 0}}.card{{background:#fff;border:1px solid #ddd;border-radius:8px;padding:10px;overflow:auto}}
.viewport{{height:min(75vh,650px);overflow:auto;display:flex;align-items:flex-start;justify-content:flex-start;background:white}}
html[data-bg="black"] .viewport{{background:#111}}html[data-bg="checkerboard"] .viewport{{background-color:#ccc;background-image:linear-gradient(45deg,#eee 25%,transparent 25%),linear-gradient(-45deg,#eee 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#eee 75%),linear-gradient(-45deg,transparent 75%,#eee 75%);background-size:24px 24px;background-position:0 0,0 12px,12px -12px,-12px 0}}
img{{width:calc(512px * var(--zoom,1));height:auto;image-rendering:auto}}small{{color:#52525b}}select{{padding:6px;margin-right:8px}}
</style></head><body data-bg="white"><header><b>Blind visual comparison — {title}</b><div style="margin-top:8px">Background <select id="bg"><option>white</option><option>black</option><option>checkerboard</option></select>
Zoom <select id="zoom"><option value="1">100%</option><option value="2" selected>200%</option><option value="4">400%</option></select> <a href="index.html">All fixtures</a></div></header>
<div class="row"><section class="card"><b>Source</b><div class="viewport"><img src="assets/{fid}/source.png"></div></section>
<section class="card"><b>Candidate A</b><div class="viewport"><img src="assets/{fid}/candidate_A.png"></div></section>
<section class="card"><b>Candidate B</b><div class="viewport"><img src="assets/{fid}/candidate_B.png"></div></section></div>
<p><small>Change background and zoom using the controls. Enter ratings and issue ROIs in the separate blank CSV template. Engine identities are stored separately.</small></p>
<script>const bg=document.getElementById('bg'), zoom=document.getElementById('zoom');bg.onchange=()=>document.documentElement.dataset.bg=bg.value;zoom.onchange=()=>document.documentElement.style.setProperty('--zoom',zoom.value);zoom.onchange();</script></body></html>"""
        rel_page = f"fixtures/{fid}.html"
        (blind_root / rel_page).parent.mkdir(parents=True, exist_ok=True)
        (blind_root / rel_page).write_text(page, encoding="utf-8")
        pages.append(rel_page)
    index_links = "\n".join(f'<li><a href="{html.escape(page)}">{html.escape(Path(page).stem)}</a></li>' for page in pages)
    (blind_root / "index.html").write_text("<!doctype html><html><meta charset='utf-8'><title>Blind review</title>"
        "<body><h1>MediaStudio BETA-01.1A blind A/B review</h1><p>Engine identity is hidden on each review page. "
        "Use the control to inspect white, black and checkerboard backgrounds at 200% or 400%.</p><ul>" + index_links + "</ul></body></html>", encoding="utf-8")
    mapping_path = OUT / "blind_review_identity_mapping.json"
    write_json(mapping_path, mapping)
    template = PACK / "human_review_template.csv"
    copied_template = OUT / "human_review_template.csv"
    shutil.copy2(template, copied_template)
    return str(blind_root / "index.html"), str(mapping_path)


def main() -> int:
    validation = json.loads((OUT / "input_manifest_validation.json").read_text(encoding="utf-8"))
    if not validation.get("inputPackValid"):
        raise RuntimeError("Input pack is invalid; refusing analysis.")
    manifest = json.loads((PACK / "manifest.json").read_text(encoding="utf-8"))
    items = {str(row["id"]): row for row in manifest["items"]}
    matrix = json.loads((OUT / "api_run_matrix.json").read_text(encoding="utf-8"))
    if matrix.get("fullBenchmark", {}).get("status") != "COMPLETE":
        raise RuntimeError("Full 48-case API benchmark has not completed.")
    rows = matrix["cases"]
    expected = [f"{fid}|{engine}" for fid in items for engine in ("smart_reconstruction", "contour_preserving")]
    missing = [key for key in expected if key not in rows]
    if missing:
        raise RuntimeError(f"Missing case records: {missing}")

    references: dict[str, np.ndarray] = {}
    rendered: dict[str, dict[str, np.ndarray]] = {fid: {} for fid in items}
    reference_dir = OUT / "reference_renders"
    reference_dir.mkdir(parents=True, exist_ok=True)
    reference_mapping: list[dict[str, Any]] = []
    analytic = analytic_g04()
    Image.fromarray(analytic, "RGBA").save(reference_dir / "G04_analytic_source.png")
    for fid, item in items.items():
        if item.get("ground_truth_kind") == "source_svg_vector_geometry":
            path = PACK / str(item["reference_svg"])
            rgba = render_svg_edge(path, width=512, height=512)
            references[fid] = rgba
            target_path = reference_dir / f"{fid}_reference_edge.png"
            Image.fromarray(rgba, "RGBA").save(target_path)
            source = load_rgba(PACK / str(item["png_paths"]["512"]))
            mapping16 = alpha_iou(rgba, source, 16)
            mapping128 = alpha_iou(rgba, source, 128)
            reference_mapping.append({"fixtureId": fid, "referenceType": "original_svg_vector_geometry",
                "sourceSha256": item["png_sha256"]["512"], "referenceSvgSha256": item["source_sha256"],
                "edgeRenderPath": str(target_path), "alphaIoUThreshold16": mapping16,
                "alphaIoUThreshold128": mapping128,
                "rgbaMeanAbsoluteDifference": float(np.abs(rgba.astype(np.float32)-source.astype(np.float32)).mean()),
                "rendererBaselineNote": "Reference SVG rendered with Edge at native 512x512; source PNG antialiasing can differ, especially A04 one-pixel alpha strokes."})
        else:
            references[fid] = analytic

    geometry_rows: list[dict[str, Any]] = []
    color_rows: list[dict[str, Any]] = []
    detail_rows: list[dict[str, Any]] = []
    integrity_rows: list[dict[str, Any]] = []
    renderer_rows: list[dict[str, Any]] = []
    resource_rows: list[dict[str, Any]] = []
    false_edge_rows: list[dict[str, Any]] = []
    diagnostic_files: list[str] = []

    for fid, item in items.items():
        target = references[fid]
        truth_mask = target[..., 3] > 16
        source_png = load_rgba(PACK / str(item["png_paths"]["512"]))
        for engine in ("smart_reconstruction", "contour_preserving"):
            key = f"{fid}|{engine}"
            record = rows[key]
            svg_path = Path(record["svgPath"])
            render_path = Path(record["svgIntegrity"]["edgeRender"]["path"])
            output = load_rgba(render_path)
            rendered[fid][engine] = output
            out_mask = output[..., 3] > 16
            is_svg_ref = item.get("ground_truth_kind") == "source_svg_vector_geometry"
            if is_svg_ref:
                geom = boundary_metrics(truth_mask, out_mask, 2.0)
                union = int(np.count_nonzero(truth_mask | out_mask))
                intersection = int(np.count_nonzero(truth_mask & out_mask))
                geometry = {"status": "MEASURED_AGAINST_ORIGINAL_SVG", "silhouetteIoU": intersection / max(union, 1),
                    "referenceForegroundPixels": int(truth_mask.sum()), "candidateForegroundPixels": int(out_mask.sum()),
                    "missingForegroundPixels": int((truth_mask & ~out_mask).sum()),
                    "extraForegroundPixels": int((out_mask & ~truth_mask).sum()),
                    "componentCountReference": _component_count(truth_mask), "componentCountOutput": _component_count(out_mask),
                    "holeCountReference": _hole_count(truth_mask), "holeCountOutput": _hole_count(out_mask),
                    "boundary": geom, "boundaryBaseline": "Edge renders original SVG and output SVG at native 512x512; tolerance is 2 native pixels."}
            else:
                geom = boundary_metrics(truth_mask, out_mask, 2.0)
                union = int(np.count_nonzero(truth_mask | out_mask))
                intersection = int(np.count_nonzero(truth_mask & out_mask))
                geometry = {"status": "ANALYTIC_ALPHA_GEOMETRY_ONLY_NO_SVG_GROUND_TRUTH",
                    "alphaSilhouetteIoU": intersection / max(union, 1),
                    "referenceForegroundPixels": int(truth_mask.sum()), "candidateForegroundPixels": int(out_mask.sum()),
                    "missingForegroundPixels": int((truth_mask & ~out_mask).sum()),
                    "extraForegroundPixels": int((out_mask & ~truth_mask).sum()),
                    "boundary": geom, "note": "G04 has a 2D analytic color/alpha source, not original vector geometry; no semantic geometry was inferred."}
            geometry_rows.append({"fixtureId": fid, "engine": engine, "sourceFamilyId": item["source_family_id"],
                                  "sourceSha256": item["png_sha256"]["512"], **geometry})

            cm, de, common = color_metrics(target, output)
            if fid == "G04_nonlinear_2d_analytic":
                cm["comparisonTarget"] = "manifest analytic 2D source formula"
            flat = flat_color_classes(target, output, PACK / str(item["reference_svg"])) if is_svg_ref else []
            cm["referenceFillColorClasses"] = flat
            cm["referenceFillColorClassCount"] = len(flat)
            cm["flatColorAccuracyStatus"] = "MEASURED_BY_EXPLICIT_REFERENCE_FILL_CLASS" if flat else "NOT_APPLICABLE_OR_NO_EXPLICIT_FLAT_FILL_CLASS"
            color_rows.append({"fixtureId": fid, "engine": engine, "sourceFamilyId": item["source_family_id"],
                               "sourceSha256": item["png_sha256"]["512"], "metrics": cm})

            structural = record["svgIntegrity"]
            api_meta = record.get("engineResultMetadata", {})
            engine_meta = api_meta.get("engineMetadata", {}) if isinstance(api_meta.get("engineMetadata"), dict) else {}
            contour_topology = None
            if engine == "contour_preserving":
                contour_topology = {
                    "geometryValid": engine_meta.get("geometryValid"),
                    "topologyValid": engine_meta.get("topologyValid"),
                    "selfIntersectionCount": engine_meta.get("selfIntersectionCount"),
                    "sharedBoundaryMismatchCount": engine_meta.get("sharedBoundaryMismatchCount"),
                    "wpfPreviewValidated": engine_meta.get("wpfPreviewValidated"),
                    "source": "Contour-Preserving production API resultEngineMetadata",
                }
            status_fields = {
                "apiSuccess": record.get("apiJobStatus") == "SUCCEEDED",
                "validSvg": structural.get("validSvg") is True,
                "visibleSvg": structural.get("visibleSvg") is True,
                "geometryValid": {"svgStructureAndNativeRender": structural.get("geometryValidStatus"),
                    "engineTopology": contour_topology if contour_topology is not None else "NOT_EXPOSED_BY_SMART_V2_API"},
                "fidelityAccepted": False,
                "fidelityStatus": "HUMAN_REVIEW_PENDING; no automatic acceptance threshold was defined by this task.",
            }
            integrity_rows.append({"fixtureId": fid, "engine": engine, "sourceSha256": item["png_sha256"]["512"],
                                   "svgSha256": record.get("svgSha256"), **status_fields,
                                   "vectorOnly": structural.get("vectorOnly"), "svgIntegrity": structural})

            # Renderer consistency: an installed Svg.Skia diagnostic is checked against Edge.
            skia_meta = structural.get("svgSkia", {})
            skia_path = Path(skia_meta.get("outputPath", "")) if skia_meta.get("outputPath") else None
            if skia_meta.get("status") == "PASS" and skia_path and skia_path.is_file():
                skia = load_rgba(skia_path)
                skia_common = (output[..., 3] > 16) & (skia[..., 3] > 16)
                edge_lab = rgb2lab(output[..., :3].astype(np.float32) / 255.0)
                skia_lab = rgb2lab(skia[..., :3].astype(np.float32) / 255.0)
                render_de = deltaE_ciede2000(edge_lab[skia_common], skia_lab[skia_common]) if skia_common.any() else np.asarray([], np.float32)
                renderer_rows.append({"fixtureId": fid, "engine": engine, "rendererA": "Microsoft Edge headless",
                    "rendererB": "Svg.Skia 5.2.3", "status": "BOTH_RENDERED",
                    "alphaIoUThreshold16": alpha_iou(output, skia, 16),
                    "alphaChangedPixelCountExact": int(np.count_nonzero(output[..., 3] != skia[..., 3])),
                    "commonAlphaPixelCount": int(skia_common.sum()), "commonAlphaColorDeltaE00": _summary(render_de),
                    "edgePath": record["svgIntegrity"]["edgeRender"]["path"], "skiaPath": str(skia_path)})
            else:
                renderer_rows.append({"fixtureId": fid, "engine": engine, "rendererA": "Microsoft Edge headless",
                    "rendererB": "Svg.Skia", "status": skia_meta.get("status", "NOT_AVAILABLE"),
                    "reason": skia_meta.get("reason")})

            memory = record.get("memory", {})
            resource_rows.append({"fixtureId": fid, "engine": engine,
                "sourceSha256": item["png_sha256"]["512"], "apiJobStatus": record.get("apiJobStatus"),
                "startUtc": record.get("requestStartedAtUtc"), "endUtc": record.get("requestEndedAtUtc"),
                "runtimeSeconds": record.get("caseRuntimeSeconds"), "apiProcessingTimeMs": record.get("apiProcessingTimeMs"),
                "timeoutApplied": record.get("timeoutApplied"), "peakProcessTreeMemory": memory,
                "svgBytes": record.get("svgIntegrity", {}).get("svgBytes"), "svgPath": str(svg_path),
                "svgSha256": record.get("svgSha256")})

            if fid in DETAIL_IDS:
                ref_alpha = target[..., 3].astype(np.int16)
                out_alpha = output[..., 3].astype(np.int16)
                alpha_delta = np.abs(ref_alpha - out_alpha)
                detail = {"apiSuccess": record.get("apiJobStatus") == "SUCCEEDED",
                    "referenceGroundTruth": "original SVG render" if is_svg_ref else "analytic alpha field",
                    "referenceSourceHash": item["source_sha256"],
                    "alphaFidelity": {"status": "MEASURED", "exactChangedPixelCount": int(np.count_nonzero(alpha_delta)),
                        "meanAbsoluteAlphaDifference": float(alpha_delta.mean()), "p95AbsoluteAlphaDifference": float(np.quantile(alpha_delta, .95)),
                        "maxAbsoluteAlphaDifference": int(alpha_delta.max()),
                        "binaryMaskIoUThreshold16": alpha_iou(target, output, 16),
                        "binaryMaskIoUThreshold128": alpha_iou(target, output, 128),
                        "comparisonAgainstSourcePng": {"exactAlphaChangedPixelCount": int(np.count_nonzero(
                            source_png[..., 3] != output[..., 3])), "binaryMaskIoUThreshold16": alpha_iou(source_png, output, 16),
                            "note": "For opaque white-backed inputs, API background removal is expected to alter alpha; SVG reference alpha is the fidelity ground truth for A transparency fixtures."}},
                    "topology": {"referenceForegroundComponents": _component_count(truth_mask),
                        "outputForegroundComponents": _component_count(out_mask), "referenceHoleCount": _hole_count(truth_mask),
                        "outputHoleCount": _hole_count(out_mask), "referenceForegroundPixels": int(truth_mask.sum()),
                        "outputForegroundPixels": int(out_mask.sum()), "missingPixels": int((truth_mask & ~out_mask).sum()),
                        "extraPixels": int((out_mask & ~truth_mask).sum())},
                    "colorDeltaE00": cm, "detailStatus": "Mask/component/hole metrics only; no semantic labels were invented."}
                detail_rows.append({"fixtureId": fid, "engine": engine, "sourceSha256": item["png_sha256"]["512"], **detail})
                diagnostic_files.extend(_diagnostic_images(fid, engine, source_png, target, output, de, common))

            if fid == "G04_nonlinear_2d_analytic":
                target_rgb = composite(analytic, "white")
                output_rgb = composite(output, "white")
                target_lab = rgb2lab(target_rgb.astype(np.float32) / 255.0)
                out_lab = rgb2lab(output_rgb.astype(np.float32) / 255.0)
                source_response = _lab_neighbor_delta(target_lab)
                output_response = _lab_neighbor_delta(out_lab)
                roi = cv2.erode((analytic[..., 3] > 250).astype(np.uint8), np.ones((3, 3), np.uint8), iterations=1) > 0
                false = roi & (output_response >= 3.0) & (output_response > source_response * 2.5 + 0.75)
                false_edge_rows.append({"fixtureId": fid, "engine": engine, "detector": "CIE76 adjacent-pixel Lab response; candidate >=3 and > source*2.5+0.75; 1px eroded analytic-alpha ROI",
                    "sourceHardBoundary": False, "roiPixelCount": int(roi.sum()), "falseHardEdgePixels": int(false.sum()),
                    "falseHardEdgeFraction": float(false.sum() / max(roi.sum(), 1)),
                    "warning": "This is a stress-control metric only; it does not establish general nonlinear-gradient support."})
                heat = np.zeros((*false.shape, 3), np.uint8)
                heat[roi] = (80, 80, 80); heat[false] = (255, 0, 0)
                false_dir = OUT / "roi_diagnostics" / fid / engine
                false_dir.mkdir(parents=True, exist_ok=True)
                Image.fromarray(heat).save(false_dir / "false_edge_cie76.png")

    comparison_sheets = make_comparison_sheets(items, rendered, references)
    review_index, mapping_path = make_blind_review(items, rendered)

    geometry_json = {"schemaVersion": 1, "groundTruth": "23 original SVGs; G04 analytic 2D alpha only",
        "renderer": "Microsoft Edge headless at 512x512", "boundaryTolerancePx": 2,
        "rendererBaseline": reference_mapping, "metrics": geometry_rows,
        "validityNote": "Boundary metrics use rendered silhouettes; they do not by themselves prove path self-intersection freedom."}
    color_json = {"schemaVersion": 1, "colorMetric": "CIEDE2000 (ΔE00)", "falseEdgeMetric": "CIE76 neighboring-pixel response; reported only for G04 analytic smooth-gradient ROI",
        "metrics": color_rows, "falseEdgeStressControl": false_edge_rows,
        "note": "G01–G04 are stress controls and do not prove general complex-gradient support."}
    detail_json = {"schemaVersion": 1, "fixtures": DETAIL_IDS, "metrics": detail_rows,
        "roiDiagnostics": diagnostic_files, "interpretation": "No semantic labels were inferred; alpha exact differences and binary IoU are reported separately."}
    all_api_ok = all(record.get("apiJobStatus") == "SUCCEEDED" for record in rows.values())
    all_svg_ok = all((record.get("svgIntegrity") or {}).get("validSvg") is True for record in rows.values())
    all_visible = all((record.get("svgIntegrity") or {}).get("visibleSvg") is True for record in rows.values())
    all_vector = all((record.get("svgIntegrity") or {}).get("vectorOnly") is True for record in rows.values())
    primitive_rows = []
    for key, record in rows.items():
        root = ET.parse(record["svgPath"]).getroot()
        counts = {}
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1].lower()
            if tag in {"path", "rect", "polygon", "polyline", "circle", "ellipse", "line", "image", "text", "use"}:
                counts[tag] = counts.get(tag, 0) + 1
        vector_primitive_count = sum(counts.get(tag, 0) for tag in ("path", "rect", "polygon", "polyline", "circle", "ellipse", "line"))
        primitive_rows.append({"caseKey": key, "engine": record.get("engine"), "fixtureId": record.get("fixtureId"),
            "svgSha256": record.get("svgSha256"), "primitiveCounts": counts,
            "vectorPrimitiveCount": vector_primitive_count,
            "highVolumeTileHeuristic": vector_primitive_count >= 1024 or counts.get("rect", 0) >= 256,
            "embeddedImageCount": counts.get("image", 0)})
    tile_heuristic_pass = all(not row["highVolumeTileHeuristic"] and row["embeddedImageCount"] == 0 for row in primitive_rows)
    contour_topology_rows = [{"fixtureId": x.get("fixtureId"), **(x.get("engineResultMetadata", {}).get("engineMetadata") or {})}
                             for x in rows.values() if x.get("engine") == "contour_preserving"]
    svg_json = {"schemaVersion": 1, "apiSuccessCount": sum(1 for x in rows.values() if x.get("apiJobStatus") == "SUCCEEDED"),
        "validSvgCount": sum(1 for x in rows.values() if (x.get("svgIntegrity") or {}).get("validSvg") is True),
        "visibleSvgCount": sum(1 for x in rows.values() if (x.get("svgIntegrity") or {}).get("visibleSvg") is True),
        "vectorOnlyCount": sum(1 for x in rows.values() if (x.get("svgIntegrity") or {}).get("vectorOnly") is True),
        "geometryStatusCounts": dict(Counter((x.get("svgIntegrity") or {}).get("geometryValidStatus") for x in rows.values())),
        "engineGeometryEvidence": {"smartReconstruction": {"status": "NOT_EXPOSED_BY_API",
            "caseCount": 24, "note": "API success metadata omits internal Smart V2 topology/self-intersection fields; no claim is inferred."},
            "contourPreserving": {"reportedCaseCount": sum(1 for x in contour_topology_rows if x.get("geometryValid") is not None),
                "geometryValidCount": sum(1 for x in contour_topology_rows if x.get("geometryValid") is True),
                "topologyValidCount": sum(1 for x in contour_topology_rows if x.get("topologyValid") is True),
                "selfIntersectionCounts": {x["fixtureId"]: x.get("selfIntersectionCount") for x in contour_topology_rows},
                "sharedBoundaryMismatchCounts": {x["fixtureId"]: x.get("sharedBoundaryMismatchCount") for x in contour_topology_rows},
                "wpfPreviewValidatedCount": sum(1 for x in contour_topology_rows if x.get("wpfPreviewValidated") is True)}},
        "fidelityAcceptedCount": 0, "statusesPerFixtureEngine": integrity_rows,
        "aggregate": {"apiSuccess": all_api_ok, "validSvg": all_svg_ok, "visibleSvg": all_visible,
                      "vectorOnly": all_vector, "fidelityAccepted": False},
        "primitiveCountsPerCase": primitive_rows,
        "pixelTileSubstitutionHeuristic": {"status": "NO_EMBEDDED_IMAGE_AND_NO_HIGH_VOLUME_TILE_PATTERN_DETECTED" if tile_heuristic_pass else "REVIEW_REQUIRED",
            "highVolumePrimitiveThreshold": 1024, "highRectCountThreshold": 256,
            "maximumVectorPrimitiveCount": max(row["vectorPrimitiveCount"] for row in primitive_rows),
            "maximumRectElementCount": max(row["primitiveCounts"].get("rect", 0) for row in primitive_rows),
            "embeddedImageCount": sum(row["embeddedImageCount"] for row in primitive_rows),
            "heuristicCannotProveAbsenceOfAnyManuallyTiledVectorConstruction": True,
            "note": "Counts are a raster-tile substitution heuristic, not a formal proof. All actual output SVGs were parsed and inspected for image/data raster elements."}}
    renderer_json = {"schemaVersion": 1, "referenceVsSourceBaseline": reference_mapping,
        "engineRenderComparisons": renderer_rows, "edgeAndSkiaComparedCount": sum(1 for x in renderer_rows if x.get("status") == "BOTH_RENDERED"),
        "edgeAndSkiaUnavailableOrFailedCount": sum(1 for x in renderer_rows if x.get("status") != "BOTH_RENDERED"),
        "manualWpfPreview": "NOT_RUN; this backend benchmark does not constitute manual WPF preview QA"}
    resource_json = {"schemaVersion": 1, "timeoutApplied": False, "cases": resource_rows,
        "byEngine": {engine: {"count": sum(1 for x in resource_rows if x["engine"] == engine),
            "medianRuntimeSeconds": float(np.median([x["runtimeSeconds"] for x in resource_rows if x["engine"] == engine])),
            "maxRuntimeCase": max((x for x in resource_rows if x["engine"] == engine), key=lambda x: x["runtimeSeconds"]),
            "peakProcessTreeMemoryMeasurements": sum(1 for x in resource_rows if x["engine"] == engine and x["peakProcessTreeMemory"].get("status") == "MEASURED")}
            for engine in ("smart_reconstruction", "contour_preserving")}}
    write_json(OUT / "geometry_fidelity.json", geometry_json)
    write_json(OUT / "color_fidelity.json", color_json)
    write_json(OUT / "detail_alpha_fidelity.json", detail_json)
    write_json(OUT / "svg_integrity.json", svg_json)
    write_json(OUT / "renderer_consistency.json", renderer_json)
    write_json(OUT / "resource_usage.json", resource_json)
    write_json(OUT / "visual_comparison_index.json", {"comparisonSheets": comparison_sheets,
        "roiDiagnostics": diagnostic_files, "blindReviewIndex": review_index, "blindIdentityMappingSeparate": mapping_path})

    beta_gaps = {"schemaVersion": 1, "packSyntheticOnly": True, "realArtworkInputRequired": True,
        "realIndependentArtworkFamiliesCount": 0, "requiredMinimumRealRightsClearedIndependentFamilies": 4,
        "recommendedRealFamilies": "8–12 diverse rights-cleared original artworks",
        "humanVisualReviewComplete": False, "humanReviewRowsCompleted": 0,
        "humanReviewTemplate": str(OUT / "human_review_template.csv"),
        "supportedBetaCategoryProven": False,
        "reason": "All 24 fixture families are programmatically authored synthetic cases. The pack establishes technical benchmark evidence only and includes no real human-authored artwork or completed human review."}
    write_json(OUT / "beta_real_artwork_gaps.json", beta_gaps)
    print(json.dumps({"apiSuccessCount": svg_json["apiSuccessCount"], "validSvgCount": svg_json["validSvgCount"],
        "visibleSvgCount": svg_json["visibleSvgCount"], "vectorOnlyCount": svg_json["vectorOnlyCount"],
        "medianRuntime": resource_json["byEngine"], "detailRows": len(detail_rows), "comparisonSheets": comparison_sheets,
        "blindReviewIndex": review_index, "svgSkiaCompared": renderer_json["edgeAndSkiaComparedCount"]}, indent=2, ensure_ascii=False))
    return 0 if all_api_ok and all_svg_ok and all_visible and all_vector and len(geometry_rows) == 48 and len(color_rows) == 48 and len(detail_rows) == 16 else 2


if __name__ == "__main__":
    raise SystemExit(main())
