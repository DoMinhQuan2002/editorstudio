from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage.color import deltaE_ciede2000, rgb2lab
from skimage.metrics import structural_similarity

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
ARTIFACTS = BACKEND / "artifacts/contour_preserving/task_08b_1_4"
TASK13 = BACKEND / "artifacts/contour_preserving/task_08b_1_3"
TASK12 = BACKEND / "artifacts/contour_preserving/task_08b_1_2"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tools"))

from task_08b_1_1.diagnostics import gradient_metrics
from vectorization_benchmark.dataset import MANIFEST_PATH
from vectorization_benchmark.svg import validate_svg


def _read(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)


def _white(rgba: np.ndarray) -> np.ndarray:
    a = rgba.astype(np.float32)
    alpha = a[..., 3:4] / 255.0
    return np.rint(a[..., :3] * alpha + 255 * (1 - alpha)).clip(0, 255).astype(np.uint8)


def _de(source: np.ndarray, output: np.ndarray) -> np.ndarray:
    return deltaE_ciede2000(rgb2lab(source.astype(np.float32)/255.0),
                            rgb2lab(output.astype(np.float32)/255.0)).astype(np.float32)


def _summary(values: np.ndarray) -> dict:
    values = np.asarray(values, dtype=np.float64)
    return {"count": int(values.size), "mean": float(values.mean()) if values.size else None,
            "p95": float(np.quantile(values, .95)) if values.size else None,
            "median": float(np.median(values)) if values.size else None}


def _api_record(stage: str) -> dict[str, dict]:
    path = ARTIFACTS / f"api_{stage}.json"
    return {row["imageId"]: row for row in json.loads(path.read_text(encoding="utf-8"))["results"]}


def _api_render(stage: str, image_id: str) -> Path:
    return Path(_api_record(stage)[image_id]["result"]["engines"]["contour_preserving"]["edgeRenderPath"])


def _task13_render(image_id: str) -> Path:
    return TASK13 / "runs/task08b1_3_controlled/outputs" / image_id / "contour_preserving/render_edge.png"


def _task12_render(image_id: str) -> Path:
    return TASK12 / "runs/task08b1_2_api_nonreg/outputs" / image_id / "contour_preserving/render_edge.png"


def _fixture_source(image_id: str) -> tuple[Path, Path | None]:
    if image_id in {"smooth_nonlinear_gradient", "hard_boundary_with_gradient", "low_contrast_multistop_gradient"}:
        folder = TASK13 / "fixtures" / image_id
        return folder / "source.png", folder / "ground_truth_soft_gradient_roi.png"
    variants = json.loads((ARTIFACTS / "controlled_variants.json").read_text(encoding="utf-8"))
    for row in variants["variants"]:
        if row["fixtureId"] == image_id:
            return ARTIFACTS / row["paths"]["source"], ARTIFACTS / row["paths"]["softRoi"]
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    row = next(item for item in manifest["items"] if item["imageId"] == image_id)
    manifest_source = Path(row["path"])
    return (manifest_source if manifest_source.is_absolute() else REPO / manifest_source), None


def _metrics_row(source_rgba: np.ndarray, output_rgba: np.ndarray, roi: np.ndarray | None) -> dict:
    source_rgb, output_rgb = _white(source_rgba), _white(output_rgba)
    content = source_rgba[..., 3] >= 250
    if roi is not None:
        soft = roi
        edge = gradient_metrics(source_rgb, output_rgb, soft)
    else:
        soft = content
        edge = {"roiPixels": int(soft.sum()), "falseHardEdgePixels": None,
                "falseHardEdgeFraction": None, "meanDeltaE00": None, "p95DeltaE00": None,
                "falseHardBoundaryInterpretation": "not applicable: no analytic continuous-gradient ROI"}
    de = _de(source_rgb, output_rgb)
    alpha_truth = source_rgba[..., 3] > 16
    alpha_out = output_rgba[..., 3] > 16
    alpha_iou = float(np.count_nonzero(alpha_truth & alpha_out) / max(np.count_nonzero(alpha_truth | alpha_out), 1))
    return {"colorErrorCIEDE2000Content": _summary(de[content]),
            "colorErrorCIEDE2000SoftROI": _summary(de[soft]) if roi is not None else None,
            "falseEdge": edge, "alphaIoU": alpha_iou,
            "renderDimensions": [int(output_rgba.shape[1]), int(output_rgba.shape[0])],
            "ssimWholeCanvas": float(structural_similarity(source_rgb, output_rgb, channel_axis=2, data_range=255))}


def _load_svg_nodes(path: Path) -> list[ET.Element]:
    root = ET.parse(path).getroot()
    return [node for node in root.iter() if node.tag.rsplit("}", 1)[-1].casefold() == "path"]


def _geometry_d(path: Path) -> dict[str, str]:
    return {node.attrib["id"]: node.attrib.get("d", "") for node in _load_svg_nodes(path)
            if node.attrib.get("id", "").startswith("contour-region-")}


def _production_svg(stage: str, image_id: str) -> Path:
    root = ARTIFACTS / "runs" / f"task08b1_4_{stage}" / "outputs" / image_id / "contour_preserving/output.svg"
    if stage == "task13":
        return TASK13 / "runs/task08b1_3_controlled/outputs" / image_id / "contour_preserving/output.svg"
    return root


def _primary() -> dict:
    fid = "smooth_nonlinear_gradient"
    source_path, roi_path = _fixture_source(fid)
    assert roi_path is not None
    source = _read(source_path)
    roi = np.asarray(Image.open(roi_path).convert("L"), dtype=np.uint8) > 127
    baseline_rgba = _read(_task13_render(fid))
    candidate_rgba = _read(_api_render("candidate", fid))
    baseline_metrics = _metrics_row(source, baseline_rgba, roi)
    candidate_metrics = _metrics_row(source, candidate_rgba, roi)
    baseline_features = json.loads((TASK13 / f"stage_captures/{fid}/contour_preserving/appearance.json").read_text(encoding="utf-8"))
    candidate_features = json.loads((ARTIFACTS / f"stage_captures/task08b1_4_candidate/{fid}/appearance.json").read_text(encoding="utf-8"))
    baseline_count = int(baseline_features["metrics"].get("internal_feature_count", 0))
    candidate_count = sum(len(row["internalFeatures"]) for row in candidate_features["regions"])
    baseline_svg = _production_svg("task13", fid)
    candidate_svg = _production_svg("candidate", fid)
    base_geom, candidate_geom = _geometry_d(baseline_svg), _geometry_d(candidate_svg)
    alpha_diff = np.abs(baseline_rgba[..., 3].astype(np.int16) - candidate_rgba[..., 3].astype(np.int16))
    result = {"sourceSha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "baseline": {"svg": str(baseline_svg), "render": str(_task13_render(fid)), "featureCount": baseline_count, "metrics": baseline_metrics},
        "candidate": {"svg": str(candidate_svg), "render": str(_api_render("candidate", fid)), "featureCount": candidate_count, "metrics": candidate_metrics},
        "geometry": {"baselineRegionPathCount": len(base_geom), "candidateRegionPathCount": len(candidate_geom),
                     "regionPathDIdentical": base_geom == candidate_geom,
                     "baselineRegionPathIds": sorted(base_geom), "candidateRegionPathIds": sorted(candidate_geom)},
        "alpha": {"differentPixelCount": int(np.count_nonzero(alpha_diff)), "maxAbsoluteDifference": int(alpha_diff.max()),
                  "exactlyUnchanged": bool(np.count_nonzero(alpha_diff) == 0)}}
    return result


def _variant_metrics(image_id: str) -> dict:
    source_path, roi_path = _fixture_source(image_id)
    source = _read(source_path)
    roi = np.asarray(Image.open(roi_path).convert("L"), dtype=np.uint8) > 127 if roi_path else None
    baseline = _read(_api_render("baseline", image_id))
    candidate = _read(_api_render("candidate", image_id))
    return {"sourceSha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "baseline": {"metrics": _metrics_row(source, baseline, roi), "render": str(_api_render("baseline", image_id))},
            "candidate": {"metrics": _metrics_row(source, candidate, roi), "render": str(_api_render("candidate", image_id))}}


def _detail_metrics(image_id: str) -> dict:
    source_path, roi_path = _fixture_source(image_id)
    source_rgba = _read(source_path)
    source_rgb = _white(source_rgba)
    baseline_rgba = _read(_api_render("baseline", image_id))
    candidate_rgba = _read(_api_render("candidate", image_id))
    folder = source_path.parent
    mask = np.asarray(Image.open(folder / "detail_mask.png").convert("L"), dtype=np.uint8) > 127
    roi = np.asarray(Image.open(roi_path).convert("L"), dtype=np.uint8) > 127
    annotation = json.loads((ARTIFACTS / "controlled_variants.json").read_text(encoding="utf-8"))
    item = next(x for x in annotation["variants"] if x["fixtureId"] == image_id)
    detail = item["analyticAnnotation"]["details"][0]
    target_rgb = np.asarray(detail["paintRGB"], dtype=np.uint8)
    base_rgb, cand_rgb = _white(baseline_rgba), _white(candidate_rgba)
    base_de, cand_de = _de(source_rgb, base_rgb), _de(source_rgb, cand_rgb)
    target_de_base = _de(np.broadcast_to(target_rgb, source_rgb.shape), base_rgb)
    target_de_candidate = _de(np.broadcast_to(target_rgb, source_rgb.shape), cand_rgb)
    def recall(output: np.ndarray) -> float:
        # Pixel is counted as retained when output is perceptually near the analytic detail paint.
        return float(np.mean(_de(np.broadcast_to(target_rgb, output.shape), output)[mask] <= 10.0)) if mask.any() else 0.0
    return {"detailId": detail["id"], "detailPixels": int(mask.sum()), "targetRGB": detail["paintRGB"],
        "baseline": {"meanDeltaE00ToSourceInDetail": float(base_de[mask].mean()),
                     "meanDeltaE00ToTargetPaint": float(target_de_base[mask].mean()),
                     "paintRecallDeltaE00Le10": recall(base_rgb),
                     "softGradientFalseEdge": gradient_metrics(source_rgb, base_rgb, roi)},
        "candidate": {"meanDeltaE00ToSourceInDetail": float(cand_de[mask].mean()),
                      "meanDeltaE00ToTargetPaint": float(target_de_candidate[mask].mean()),
                      "paintRecallDeltaE00Le10": recall(cand_rgb),
                      "softGradientFalseEdge": gradient_metrics(source_rgb, cand_rgb, roi)},
        "baselineRender": str(_api_render("baseline", image_id)),
        "candidateRender": str(_api_render("candidate", image_id))}


def _regression_metrics(image_ids: list[str]) -> dict:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    lookup = {row["imageId"]: row for row in manifest["items"]}
    rows = {}
    for image_id in image_ids:
        source_path, roi_path = _fixture_source(image_id)
        source = _read(source_path)
        if image_id in {"synthetic-linear_gradient", "synthetic-radial_gradient", "synthetic-multiregion_illustration", "active-fox-native-jpeg"}:
            base_path, cand_path = _task12_render(image_id), _api_render("candidate", image_id)
        else:
            base_path, cand_path = _task13_render(image_id), _api_render("candidate", image_id)
        base_rgba, cand_rgba = _read(base_path), _read(cand_path)
        # Use the same native source canvas. Real ACTIVE FOX is reported as a proxy-only comparison.
        soft = np.asarray(Image.open(roi_path).convert("L"), dtype=np.uint8) > 127 if roi_path else None
        rows[image_id] = {"referenceClass": "REAL_IMAGE_PROXY_NEEDS_HUMAN_REVIEW" if image_id == "active-fox-native-jpeg" else "ANALYTIC_FIXTURE",
            "baselineSource": str(base_path), "candidateRender": str(cand_path),
            "baseline": _metrics_row(source, base_rgba, soft), "candidate": _metrics_row(source, cand_rgba, soft),
            "baselineCandidateRenderDifference": {"rgbMeanAbsoluteError": float(np.abs(_white(base_rgba).astype(np.float32)-_white(cand_rgba).astype(np.float32)).mean()),
                "alphaDifferentPixels": int(np.count_nonzero(base_rgba[...,3] != cand_rgba[...,3]))}}
    return rows


def _svg_validation() -> dict:
    output = {}
    candidate = _api_record("candidate")
    for image_id, row in candidate.items():
        svg_path = Path(row["result"]["engines"]["contour_preserving"]["svgPath"])
        info = validate_svg(svg_path)
        output[image_id] = {k: info[k] for k in ("xmlValid", "svgNamespaceValid", "viewBox", "viewBoxValid", "embeddedRasterElementCount", "embeddedRasterDataUriCount", "editableVector", "resourcePolicyValid")}
        output[image_id]["pass"] = bool(info["xmlValid"] and info["viewBoxValid"] and not info["embeddedRasterElementCount"] and not info["embeddedRasterDataUriCount"] and info["editableVector"])
    return output


def _variant_visuals(primary: dict, details: dict[str, dict]) -> None:
    outdir = ARTIFACTS / "visuals"
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    source = _read(_fixture_source("smooth_nonlinear_gradient")[0])
    base = _read(Path(primary["baseline"]["render"]))
    cand = _read(Path(primary["candidate"]["render"]))
    tiles = [_white(source), _white(base), _white(cand)]
    board = Image.new("RGB", (512 * 3, 548), "white")
    draw = ImageDraw.Draw(board)
    for i, (label, tile) in enumerate(zip(("Source", "Baseline", "Candidate"), tiles)):
        board.paste(Image.fromarray(tile), (512*i, 36))
        draw.text((512*i+10, 8), label, fill="black", font=font)
    board.save(ARTIFACTS / "nonlinear_gradient_before_after.png")

    # Actual SVG path masks on source coordinates; use the serialized feature paths.
    baseline_json = json.loads((TASK13 / "stage_captures/smooth_nonlinear_gradient/contour_preserving/appearance.json").read_text(encoding="utf-8"))
    candidate_json = json.loads((ARTIFACTS / "stage_captures/task08b1_4_candidate/smooth_nonlinear_gradient/appearance.json").read_text(encoding="utf-8"))
    overlay = Image.fromarray(_white(source)).convert("RGB")
    pixels = np.asarray(overlay).copy()
    for data, color in ((baseline_json.get("regions", []), (240, 20, 190)),
                        (candidate_json.get("regions", []), (0, 160, 255))):
        for region in data:
            for feature in region.get("internalFeatures", []):
                for ring in feature.get("contoursProcessing", []):
                    if len(ring) < 2:
                        continue
                    points = np.rint(np.asarray(ring)).astype(np.int32)
                    cv2.polylines(pixels, [points.reshape(-1,1,2)], True, color, thickness=2, lineType=cv2.LINE_AA)
    Image.fromarray(pixels).save(ARTIFACTS / "feature_path_overlay.png")

    # ΔE00 maps use a common 0..20 scale; exact values live in JSON artifacts.
    src_rgb = _white(source)
    base_de = _de(src_rgb, _white(base)); cand_de = _de(src_rgb, _white(cand))
    heat_tiles = []
    for values in (base_de, cand_de):
        gray = np.rint(np.clip(values / 20.0, 0, 1) * 255).astype(np.uint8)
        heat_tiles.append(cv2.cvtColor(cv2.applyColorMap(gray, cv2.COLORMAP_TURBO), cv2.COLOR_BGR2RGB))
    heat_board = Image.new("RGB", (1024, 548), "white")
    hd = ImageDraw.Draw(heat_board)
    for i, (label, tile) in enumerate(zip(("Baseline ΔE00", "Candidate ΔE00"), heat_tiles)):
        heat_board.paste(Image.fromarray(tile), (512*i, 36)); hd.text((512*i+10, 8), label, fill="black", font=font)
    heat_board.save(ARTIFACTS / "deltae00_heatmap.png")

    soft_path = _fixture_source("smooth_nonlinear_gradient")[1]
    soft = np.asarray(Image.open(soft_path).convert("L"), dtype=np.uint8) > 127
    bmeta = gradient_metrics(src_rgb, _white(base), soft)
    cmeta = gradient_metrics(src_rgb, _white(cand), soft)
    false_a = cv2.erode(soft.astype(np.uint8), np.ones((3,3),np.uint8), iterations=1) > 0
    def fmask(candidate: np.ndarray) -> np.ndarray:
        s = rgb2lab(src_rgb.astype(np.float32)/255.0)
        c = rgb2lab(candidate.astype(np.float32)/255.0)
        def nd(lab):
            h=np.linalg.norm(lab[:,1:]-lab[:,:-1],axis=2); v=np.linalg.norm(lab[1:]-lab[:-1],axis=2)
            o=np.zeros(lab.shape[:2],np.float32); o[:,1:]=np.maximum(o[:,1:],h); o[:,:-1]=np.maximum(o[:,:-1],h); o[1:]=np.maximum(o[1:],v); o[:-1]=np.maximum(o[:-1],v); return o
        sd,cd=nd(s),nd(c)
        return false_a & (cd>=3.0) & (cd>sd*2.5+.75)
    f_base, f_cand = fmask(_white(base)), fmask(_white(cand))
    mask_board=Image.new("RGB",(1024,548),"white"); md=ImageDraw.Draw(mask_board)
    for i,(label,fm) in enumerate((("Baseline false-edge pixels",f_base),("Candidate false-edge pixels",f_cand))):
        tile=src_rgb.copy(); tile[fm]=np.array([255,0,0],np.uint8); mask_board.paste(Image.fromarray(tile),(512*i,36)); md.text((512*i+10,8),label,fill="black",font=font)
    mask_board.save(ARTIFACTS / "false_edge_mask_comparison.png")

    detail_board=Image.new("RGB",(1536,548*2),"white"); dd=ImageDraw.Draw(detail_board)
    for row_index, fid in enumerate(("small_sharp_color_detail","thin_highlight")):
        srcp=_fixture_source(fid)[0]; src_rgba=_read(srcp); m=np.asarray(Image.open(srcp.parent/"detail_mask.png").convert("L"))>127
        y,x=np.where(m); x0=max(0,int(x.min())-30); x1=min(512,int(x.max())+31); y0=max(0,int(y.min())-30); y1=min(512,int(y.max())+31)
        rb,rc=_read(Path(details[fid]["baselineRender"])),_read(Path(details[fid]["candidateRender"]))
        crops=[_white(src_rgba)[y0:y1,x0:x1],_white(rb)[y0:y1,x0:x1],_white(rc)[y0:y1,x0:x1]]
        for i,(label,crop) in enumerate(zip(("Source "+fid,"Baseline","Candidate"),crops)):
            scale=3
            im=Image.fromarray(crop).resize(((x1-x0)*scale,(y1-y0)*scale),Image.Resampling.NEAREST)
            xx=i*512; yy=row_index*548+36
            detail_board.paste(im,(xx,yy)); dd.text((xx+8,row_index*548+8),label,fill="black",font=font)
    detail_board.save(ARTIFACTS / "detail_preservation_comparison.png")


def analyze() -> dict:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    primary = _primary()
    variant_rows = {fid: _variant_metrics(fid) for fid in ("smooth_alternate_heldout",)}
    detail_rows = {fid: _detail_metrics(fid) for fid in ("small_sharp_color_detail", "thin_highlight")}
    regression = _regression_metrics(["hard_boundary_with_gradient", "low_contrast_multistop_gradient",
        "synthetic-linear_gradient", "synthetic-radial_gradient", "synthetic-multiregion_illustration", "active-fox-native-jpeg"])
    validation = _svg_validation()
    _variant_visuals(primary, detail_rows)
    (ARTIFACTS / "candidate_measurements.json").write_text(json.dumps({"primary": primary,
        "heldout": variant_rows, "details": detail_rows, "regression": regression,
        "svgValidation": validation}, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return {"primary": primary, "heldout": variant_rows, "details": detail_rows,
            "regression": regression, "svgValidation": validation}


if __name__ == "__main__":
    result = analyze()
    print(json.dumps({"primary": result["primary"], "heldout": result["heldout"], "details": result["details"],
                      "regressionPassCount": sum(x["pass"] for x in result["svgValidation"].values())}, indent=2, ensure_ascii=False))
