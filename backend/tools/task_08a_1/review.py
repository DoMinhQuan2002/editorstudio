from __future__ import annotations

import csv
import hashlib
import html
import json
import argparse
import shutil
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .dataset import ARTIFACTS, BASE_MANIFEST, MANIFEST, REPOSITORY, write_json
from tools.vectorization_benchmark.metrics import composite_rgba

OLD_RESULTS = BASE_MANIFEST.parent / "per_image_results.json"
RESULTS = ARTIFACTS / "per_image_results.json"
REVIEW_DIR = ARTIFACTS / "review_crops"
SCORES = ("shape_fidelity", "color_fidelity", "gradient_fidelity", "detail_fidelity",
          "typography_fidelity", "alpha_fidelity", "overall_visual_fidelity")


def load_records() -> list[dict[str, Any]]:
    all_rows: dict[str, dict[str, Any]] = {}
    for path in (OLD_RESULTS, RESULTS):
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            for row in data.get("items", []):
                all_rows[row["imageId"]] = row
    return list(all_rows.values())


def _safe_copy(source: str | None, target: Path) -> str | None:
    if not source:
        return None
    path = Path(source)
    if not path.is_file():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return target.relative_to(ARTIFACTS).as_posix()


def _write_contact_sheet(image_id: str, panel_paths: list[tuple[str, Path | None]], path: Path) -> None:
    width, height, header = 320, 320, 34
    canvas = Image.new("RGB", (width * len(panel_paths), height + header), "#f2f3f5")
    draw = ImageDraw.Draw(canvas)
    for i, (label, source) in enumerate(panel_paths):
        x = i * width
        draw.text((x + 8, 10), label, fill="#172033")
        tile = Image.new("RGB", (width, height), "white")
        if source and source.is_file():
            try:
                im = Image.open(source).convert("RGB")
                im.thumbnail((width - 18, height - 18), Image.Resampling.LANCZOS)
                tile.paste(im, ((width - im.width) // 2, (height - im.height) // 2))
            except Exception:
                pass
        canvas.paste(tile, (x, header))
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def _copy_existing_visuals(record: dict[str, Any], source_path: Path | None, blind_mapping: dict[str, str]) -> dict[str, Any]:
    image_id = record.get("imageId", "unknown")
    visuals = record.get("visualDiagnostics", {})
    out: dict[str, Any] = {"colorHeatmaps": {}, "boundaryOverlays": {}, "roiComparisons": [], "gradientComparison": None}
    for alias, engine in blind_mapping.items():
        engine_alias = "smart" if engine == "smart_reconstruction" else "contour"
        color_key = f"{engine_alias}ColorErrorHeatmap"
        boundary_key = f"{engine_alias}BoundaryOverlay"
        for target_key, source_key, folder in (("colorHeatmaps", color_key, "color_error_heatmaps"),
                                               ("boundaryOverlays", boundary_key, "boundary_error_overlays")):
            src = visuals.get(source_key)
            if src:
                rel = _safe_copy(src, ARTIFACTS / folder / f"{image_id}_{alias}.png")
                if rel: out[target_key][alias] = rel
    roi_root = ARTIFACTS / "important_roi_comparisons" / image_id
    for index, roi in enumerate(visuals.get("rois", [])):
        source_key = "smartRenderCrop" if blind_mapping["A"] == "smart_reconstruction" else "contourRenderCrop"
        other_key = "contourRenderCrop" if source_key == "smartRenderCrop" else "smartRenderCrop"
        source_boundary_key = "smartBoundaryOverlay" if blind_mapping["A"] == "smart_reconstruction" else "contourBoundaryOverlay"
        other_boundary_key = "contourBoundaryOverlay" if source_boundary_key == "smartBoundaryOverlay" else "smartBoundaryOverlay"
        sources = {"source": roi.get("sourceCrop"), "outputA": roi.get(source_key), "outputB": roi.get(other_key),
                   "differenceHeatmap": roi.get("differenceHeatmap"), "outputABoundary": roi.get(source_boundary_key),
                   "outputBBoundary": roi.get(other_boundary_key)}
        assets = {key: _safe_copy(src, ARTIFACTS / "review_crops" / image_id / "rois" / f"roi_{index:02d}_{key}.png")
                  for key, src in sources.items()}
        panels = [(label, ARTIFACTS / assets[key] if assets.get(key) else None) for label, key in
                  (("SOURCE", "source"), ("OUTPUT A", "outputA"), ("OUTPUT B", "outputB"), ("ΔE HEATMAP", "differenceHeatmap"))]
        target = roi_root / f"roi_{index:02d}.png"
        _write_contact_sheet(image_id, panels, target)
        out["roiComparisons"].append({"roiIndex": index, "bboxPx": roi.get("bboxPx"), "image": target.relative_to(ARTIFACTS).as_posix(), "assets": assets})
    if source_path and source_path.is_file():
        runs = record.get("engines", {})
        path_a = Path(runs.get(blind_mapping["A"], {}).get("edgeRenderPath", ""))
        path_b = Path(runs.get(blind_mapping["B"], {}).get("edgeRenderPath", ""))
        if path_a.is_file() and path_b.is_file():
            source_rgba = np.asarray(Image.open(source_path).convert("RGBA"), dtype=np.uint8)
            source = composite_rgba(source_rgba, "white")
            output_a = np.asarray(Image.open(path_a).convert("RGBA"), dtype=np.uint8)
            output_b = np.asarray(Image.open(path_b).convert("RGBA"), dtype=np.uint8)
            w, h = output_a.shape[1], output_a.shape[0]
            source = cv2.resize(source, (w, h), interpolation=cv2.INTER_AREA) if source.shape[:2] != (h, w) else source
            source_gray = cv2.cvtColor(source, cv2.COLOR_RGB2GRAY)
            def edge_heat(rgb: np.ndarray) -> np.ndarray:
                gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
                gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3); gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
                mag = cv2.magnitude(gx, gy)
                return cv2.applyColorMap(np.clip(mag * (255.0 / max(float(np.quantile(mag, 0.99)), 1)), 0, 255).astype(np.uint8), cv2.COLORMAP_INFERNO)[..., ::-1]
            source_edge = edge_heat(source)
            output_a_rgb = composite_rgba(output_a, "white"); output_b_rgb = composite_rgba(output_b, "white")
            panel = Image.new("RGB", (w * 3, h + 34), "white")
            draw = ImageDraw.Draw(panel)
            for idx, (label, array) in enumerate((("SOURCE GRADIENT/EDGE", source_edge), ("OUTPUT A · GRADIENT/EDGE", edge_heat(output_a_rgb)), ("OUTPUT B · GRADIENT/EDGE", edge_heat(output_b_rgb)))):
                draw.text((idx * w + 8, 9), label, fill="#172033")
                panel.paste(Image.fromarray(array, "RGB"), (idx * w, 34))
            target = ARTIFACTS / "gradient_error_comparisons" / f"{image_id}_gradient_edge_comparison.png"
            target.parent.mkdir(parents=True, exist_ok=True); panel.save(target)
            out["gradientComparison"] = target.relative_to(ARTIFACTS).as_posix()
    return out


def build_review_package() -> dict[str, Any]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    items = {row["imageId"]: row for row in manifest["items"]}
    records = load_records()
    # Remove stale blind-package exports from earlier generator revisions; never touch human score files or Task 08A.
    for folder in (ARTIFACTS / "review_crops", ARTIFACTS / "color_error_heatmaps", ARTIFACTS / "boundary_error_overlays"):
        if folder.is_dir():
            for stale in folder.rglob("*"):
                if stale.is_file() and any(token in stale.name.casefold() for token in ("smart", "contour")):
                    stale.unlink()
    out = ARTIFACTS / "review_crops"
    out.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, Any] = {}
    index_rows = []
    csv_rows = []
    external_images = []
    for record in records:
        item = items.get(record.get("imageId"), {})
        family = record.get("sourceFamilyId") or item.get("sourceFamilyId") or record.get("imageId")
        # Stable pseudorandom engine assignment by source family; mapping is written separately from review UI.
        flip = int(hashlib.sha256(f"08a1-blind:{family}".encode()).hexdigest()[:2], 16) % 2 == 1
        mapping[family] = {"A": "contour_preserving" if flip else "smart_reconstruction",
                           "B": "smart_reconstruction" if flip else "contour_preserving"}
        copied: dict[str, dict[str, str | None]] = {}
        for engine_key in ("smart_reconstruction", "contour_preserving"):
            run = record.get("engines", {}).get(engine_key, {})
            logical = "A" if mapping[family]["A"] == engine_key else "B"
            copied[logical] = {}
            for background in ("white", "black", "checkerboard"):
                src = None
                vis = record.get("visualDiagnostics", {}).get("renderedComparisons", {}).get(engine_key, {})
                if background == "white":
                    src = vis.get("white") or run.get("edgeRenderPath")
                else:
                    src = vis.get(background)
                copied[logical][background] = _safe_copy(src, out / record["imageId"] / f"{logical}_{background}.png")
        source_path = record.get("sourcePath") or item.get("path")
        if source_path and not Path(source_path).is_absolute():
            source_path = str(REPOSITORY / source_path)
        source_rel = _safe_copy(source_path, out / record["imageId"] / "source.png")
        source_backgrounds = {}
        if source_rel:
            source_rgba = np.asarray(Image.open(ARTIFACTS / source_rel).convert("RGBA"), dtype="uint8")
            for background in ("white", "black", "checkerboard"):
                target = out / record["imageId"] / f"source_{background}.png"
                Image.fromarray(composite_rgba(source_rgba, background), "RGB").save(target)
                source_backgrounds[background] = target.relative_to(ARTIFACTS).as_posix()
        extra_visuals = _copy_existing_visuals(record, Path(source_path) if source_path else None, mapping[family])
        roi_rows = []
        for i, roi in enumerate(record.get("visualDiagnostics", {}).get("rois", [])):
            # Reuse existing actual source/output/heatmap evidence; do not fabricate diagnostic crops.
            refs = next((x["assets"] for x in extra_visuals["roiComparisons"] if x["roiIndex"] == i), {})
            roi_rows.append({"roiIndex": i, "bboxPx": roi.get("bboxPx"), "riskScore": roi.get("combinedRiskScore"),
                             "metricEvidence": roi.get("metrics", {}), "reviewStatus": "pending_human_review", "assets": refs})
        for roi in roi_rows:
            for relative in roi["assets"].values():
                if relative:
                    external_images.append(relative)
        _write_contact_sheet(record["imageId"], [("SOURCE", ARTIFACTS / source_backgrounds.get("white") if source_backgrounds.get("white") else None),
                                                   ("OUTPUT A · white", ARTIFACTS / copied["A"]["white"] if copied["A"]["white"] else None),
                                                   ("OUTPUT B · white", ARTIFACTS / copied["B"]["white"] if copied["B"]["white"] else None),
                                                   ("A · black", ARTIFACTS / copied["A"]["black"] if copied["A"]["black"] else None),
                                                   ("B · checkerboard", ARTIFACTS / copied["B"]["checkerboard"] if copied["B"]["checkerboard"] else None)],
                          ARTIFACTS / "contact_sheets" / f"{record['imageId']}_blind.png")
        warning_aliases = {alias: record.get("engines", {}).get(engine, {}).get("warnings", [])
                           for alias, engine in mapping[family].items()}
        anonymized_quality = {}
        for alias, engine_name in mapping[family].items():
            qm = record.get("engines", {}).get(engine_name, {}).get("qualityMetrics", {})
            geom, color, grad, alpha = (qm.get("geometry", {}), qm.get("color", {}).get("foregroundOrContent", {}),
                                         qm.get("gradient", {}), qm.get("transparency", {}))
            anonymized_quality[alias] = {"geometry": {k: geom.get(k) for k in ("foregroundIoU", "meanSymmetricBoundaryDistancePx", "p95SymmetricBoundaryDistancePx")},
                "color": {k: color.get(k) for k in ("meanDeltaE00", "p95DeltaE00", "maskedSsim")},
                "gradient": {k: grad.get(k) for k in ("directionCosineMean", "falseHardBoundaryFractionInSourceSmoothGradient", "bandingPeakDensityProxy")},
                "alpha": {k: alpha.get(k) for k in ("alphaIoU", "meanAbsoluteAlphaError")},
                "runtimeSeconds": record.get("engines", {}).get(engine_name, {}).get("wallSeconds"),
                "svgBytes": record.get("engines", {}).get(engine_name, {}).get("svgBytes")}
        index_rows.append({"imageId": record["imageId"], "sourceFamilyId": family,
                           "source": source_rel, "sourceBackgrounds": source_backgrounds, "outputs": copied, "rois": roi_rows,
                           "metrics": {"status": record.get("status"), "warnings": warning_aliases,
                                       "outputs": anonymized_quality,
                                       "actualEngineNamesHidden": True},
                           "visualEvidence": extra_visuals,
                           "reviewStatus": "pending_human_review"})
        for alias in ("A", "B"):
            csv_rows.append({"image_id": record["imageId"], "source_family_id": family, "output_alias": alias,
                             **{key: "" for key in SCORES}, "defect_labels": "", "reviewer_id": "",
                             "reviewer_comment": "", "reviewed_at_utc": ""})
    (ARTIFACTS / "human_review_template.csv").parent.mkdir(parents=True, exist_ok=True)
    with (ARTIFACTS / "human_review_template.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_rows[0]) if csv_rows else ["image_id", "source_family_id", "output_alias", *SCORES, "defect_labels", "reviewer_id", "reviewer_comment", "reviewed_at_utc"])
        writer.writeheader(); writer.writerows(csv_rows)
    write_json(ARTIFACTS / "review_engine_mapping.json", {"schemaVersion": 1, "mapping": mapping,
        "seedDescription": "sha256('08a1-blind:' + sourceFamilyId) modulo 2; aliases consistent within source family", "privateToReviewCoordinator": True})
    review_manifest = {"schemaVersion": 1, "imageCount": len(index_rows), "humanScoresPresent": False,
                       "reviewStatus": "pending_human_review", "engineMappingNotEmbedded": True,
                       "scale": "same source-sized canvas; no per-engine enhancement; each pane displayed contain-fit at same scale",
                       "backgrounds": ["white", "black", "checkerboard"], "zoomLevels": [1, 2, 4],
                       "roiCount": sum(len(row["rois"]) for row in index_rows),
                       "files": {"index": "review_index.html", "template": "human_review_template.csv", "instructions": "human_review_instructions.md"}}
    write_json(ARTIFACTS / "review_manifest.json", review_manifest)
    instructions = """# Hướng dẫn đánh giá mù Task 08A.1

Mở `review_index.html` cục bộ, chọn từng ảnh và so sánh SOURCE với OUTPUT A/B. Mỗi ảnh dùng cùng canvas; kiểm tra 100%, 200%, 400% và các nền trắng/đen/checkerboard. Không đoán engine. Chấm độc lập từng output từ 1 đến 5; dùng `not_applicable` khi thuộc tính không xuất hiện ở nguồn. Điểm 1 = sai nghiêm trọng; 2 = khác rõ; 3 = tương đối giống nhưng có lỗi; 4 = gần nguồn với lỗi nhỏ; 5 = rất gần ở mức zoom đã kiểm tra.

Các cột điểm: shape, color, gradient, detail, typography, alpha, overall visual fidelity. Ghi lỗi nhìn thấy và bình luận ngắn vào CSV. Không dùng metric tự động để thay điểm người. Không chấm SVG thiếu/failed như thể đó là ảnh chất lượng thấp; ghi failure trong defect/comments. Hàng mẫu đang để trống có chủ ý. Sau khi chấm, chỉ gửi lại CSV có điểm thật để nhập và kiểm tra.

Một số ảnh có thể không có gradient/chữ/alpha phù hợp; ghi `not_applicable`. Các crop ROI và heatmap là gợi ý vùng cần soi, không phải ground truth. `review_engine_mapping.json` chứa khóa giải mù; không mở trước khi hoàn tất chấm mù.
"""
    (ARTIFACTS / "human_review_instructions.md").write_text(instructions, encoding="utf-8")
    rows_json = json.dumps(index_rows, ensure_ascii=False).replace("</", "<\\/")
    page = f"""<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Task 08A.1 Blind Visual Review</title>
<style>body{{font:15px Segoe UI,Arial;margin:0;background:#f2f4f7;color:#172033}}header{{position:sticky;top:0;background:#fff;padding:14px 20px;border-bottom:1px solid #ccd2dc;z-index:2;display:flex;gap:16px;align-items:center}}select,button{{padding:8px}}main{{max-width:1500px;margin:20px auto;padding:0 16px}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(240px,1fr));gap:12px}}.card{{background:white;border-radius:10px;padding:12px;min-width:0}}.viewport{{background-color:#fff;min-height:300px;display:grid;place-items:center;overflow:auto;background-image:linear-gradient(45deg,#ddd 25%,transparent 25%),linear-gradient(-45deg,#ddd 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#ddd 75%),linear-gradient(-45deg,transparent 75%,#ddd 75%);background-size:24px 24px;background-position:0 0,0 12px,12px -12px,-12px 0}}img{{max-width:100%;height:auto;object-fit:contain}}.controls{{margin:12px 0;display:flex;gap:12px;flex-wrap:wrap}}.roi img{{width:100%}}.muted{{color:#657188}}</style>
<header><b>Đánh giá mù · Task 08A.1</b><label>Ảnh <select id="pick"></select></label><label>Nền <select id="bg"><option>white</option><option>black</option><option>checkerboard</option></select></label><label>Zoom <select id="zoom"><option value="1">100%</option><option value="2">200%</option><option value="4">400%</option></select></label><a href="human_review_template.csv">CSV mẫu</a><a href="human_review_instructions.md">Hướng dẫn</a></header><main><p class="muted">Chỉ hiển thị SOURCE và hai alias ẩn danh. Trang tĩnh không lưu điểm đánh giá.</p><section id="panels" class="grid"></section><h2>Heatmap, biên và gradient</h2><section id="visualEvidence" class="grid"></section><h2>ROI cần xem</h2><section id="rois" class="grid"></section><h2>Metric và trạng thái</h2><pre id="meta"></pre></main>
<script>const rows={rows_json};const pick=document.querySelector('#pick'),bg=document.querySelector('#bg'),zoom=document.querySelector('#zoom');for(const r of rows){{const o=document.createElement('option');o.value=r.imageId;o.textContent=r.imageId;pick.append(o)}}function render(){{const r=rows.find(x=>x.imageId===pick.value);const p=document.querySelector('#panels');p.innerHTML='';for(const [label,src] of [['SOURCE',r.sourceBackgrounds[bg.value]||r.source],['OUTPUT A',r.outputs.A[bg.value]],['OUTPUT B',r.outputs.B[bg.value]]]){{const c=document.createElement('article');c.className='card';const v=document.createElement('div');v.className='viewport';if(bg.value==='white'){{v.style.backgroundImage='none';v.style.backgroundColor='#fff'}}else if(bg.value==='black'){{v.style.backgroundImage='none';v.style.backgroundColor='#000'}}if(src){{const im=document.createElement('img');im.src=src;im.style.width=(100*Number(zoom.value))+'%';v.append(im)}}else v.textContent='Output chưa có artifact';c.innerHTML='<b>'+label+'</b>';c.append(v);p.append(c)}}const ev=document.querySelector('#visualEvidence');ev.innerHTML='';const vi=r.visualEvidence||{{}};const evidence=[];for(const [alias,path] of Object.entries(vi.colorHeatmaps||{{}}))evidence.push(['Color heatmap · '+alias,path]);for(const [alias,path] of Object.entries(vi.boundaryOverlays||{{}}))evidence.push(['Boundary overlay · '+alias,path]);if(vi.gradientComparison)evidence.push(['Gradient/edge comparison',vi.gradientComparison]);for(const item of vi.roiComparisons||[])evidence.push(['ROI '+item.roiIndex+' comparison',item.image]);for(const [label,src] of evidence){{const c=document.createElement('article');c.className='card';c.innerHTML='<b>'+label+'</b>';const im=document.createElement('img');im.src=src;im.loading='lazy';c.append(im);ev.append(c)}}const ro=document.querySelector('#rois');ro.innerHTML='';for(const item of r.rois){{const c=document.createElement('article');c.className='card roi';c.innerHTML='<b>ROI '+item.roiIndex+' · review pending</b><p>'+JSON.stringify(item.bboxPx)+' · risk '+Number(item.riskScore||0).toFixed(3)+'</p><pre>'+JSON.stringify(item.metricEvidence,null,2)+'</pre>';for(const [k,v] of Object.entries(item.assets))if(v){{const im=document.createElement('img');im.src=v;c.append(im)}}ro.append(c)}}document.querySelector('#meta').textContent=JSON.stringify(r.metrics,null,2)}}pick.onchange=bg.onchange=zoom.onchange=render;render();</script></html>"""
    (ARTIFACTS / "review_index.html").write_text(page, encoding="utf-8")
    return {"imageCount": len(index_rows), "roiCount": sum(len(row["rois"]) for row in index_rows), "humanReviewComplete": False}


def validate_review_csv(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    expected = {"image_id", "source_family_id", "output_alias", *SCORES, "defect_labels", "reviewer_id", "reviewer_comment", "reviewed_at_utc"}
    if rows and not expected.issubset(rows[0]):
        return {"status": "FAIL", "reason": "missing columns"}
    invalid = []
    for index, row in enumerate(rows, 2):
        if row.get("output_alias") not in {"A", "B"}:
            invalid.append({"row": index, "reason": "alias must be A/B"})
        for key in SCORES:
            value = row.get(key, "").strip()
            if value and value != "not_applicable":
                try:
                    if float(value) not in (1, 2, 3, 4, 5): raise ValueError()
                except ValueError:
                    invalid.append({"row": index, "field": key, "reason": "score must be 1-5, not_applicable, or blank"})
    completed = bool(rows) and not invalid and all(all(row.get(k, "").strip() for k in SCORES) and
        row.get("reviewer_id", "").strip() and row.get("reviewed_at_utc", "").strip() for row in rows)
    keys = [(row.get("image_id"), row.get("output_alias")) for row in rows]
    duplicate_keys = sorted({key for key in keys if keys.count(key) > 1})
    if duplicate_keys:
        invalid.append({"reason": "duplicate image/alias rows", "keys": duplicate_keys})
    template_path = ARTIFACTS / "human_review_template.csv"
    missing_expected = []
    if template_path.is_file():
        with template_path.open(encoding="utf-8-sig", newline="") as stream:
            expected = {(r["image_id"], r["output_alias"]) for r in csv.DictReader(stream)}
        missing_expected = sorted(expected - set(keys))
    complete = completed and not missing_expected and not duplicate_keys
    return {"status": "PASS" if not invalid else "FAIL", "rowCount": len(rows), "invalidRows": invalid,
            "missingExpectedRows": missing_expected, "HUMAN_VISUAL_REVIEW_COMPLETE": complete}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate/import actual Task 08A.1 human scores")
    parser.add_argument("command", choices=("validate", "import"))
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args()
    result = validate_review_csv(args.csv_path)
    write_json(ARTIFACTS / "human_review_validation.json", result)
    if args.command == "import" and result["status"] == "PASS":
        target = ARTIFACTS / "human_review_results.csv"
        target.write_bytes(args.csv_path.read_bytes())
        result["importedFile"] = target.name
        write_json(ARTIFACTS / "human_review_validation.json", result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
