from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage.color import deltaE_ciede2000, rgb2lab

from .dataset import ARTIFACTS, BACKEND, REPOSITORY, sha256, write_json

FONT_PATH = ARTIFACTS / "typography" / "fonts" / "Roboto[wdth,wght].ttf"
FIXTURE_DIR = ARTIFACTS / "typography" / "fixtures"
PATTERNS = [
    ("bold_geometric", "ACTIVE FOX", 74, 700, "#2f0b3a", "#ffffff"),
    ("thin_sans", "Vector Fidelity", 54, 300, "#222222", "#ffffff"),
    ("small_tagline", "YOUR TAGLINE", 30, 400, "#34113f", "#ffffff"),
    ("rounded_glyphs", "OQG 806", 68, 500, "#f27613", "#fff9e9"),
    ("tight_spacing", "VECTOR", 66, 600, "#45204d", "#ffffff"),
    ("text_over_art", "TEXT OVER ART", 48, 700, "#ffffff", "#ffffff"),
    ("transparent_text", "ALPHA TYPE", 60, 500, "#2c1034", None),
]


def _font(size: int, weight: int) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT_PATH), size=size)
    try:
        font.set_variation_by_axes([100.0, float(weight)])
    except (AttributeError, OSError, ValueError):
        pass
    return font


def _edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def typography_metrics(reference: np.ndarray, candidate: np.ndarray, expected_text: str,
                       recognized_text: str | None = None) -> dict[str, Any]:
    ref = np.asarray(reference, dtype=np.uint8) > 0
    out = np.asarray(candidate, dtype=np.uint8) > 0
    if ref.shape != out.shape:
        out = cv2.resize(out.astype(np.uint8), (ref.shape[1], ref.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    inter = int(np.count_nonzero(ref & out)); union = int(np.count_nonzero(ref | out))
    ref_edge = cv2.Canny(ref.astype(np.uint8) * 255, 50, 150) > 0
    out_edge = cv2.Canny(out.astype(np.uint8) * 255, 50, 150) > 0
    dist_ref = cv2.distanceTransform((~ref_edge).astype(np.uint8), cv2.DIST_L2, 3)
    dist_out = cv2.distanceTransform((~out_edge).astype(np.uint8), cv2.DIST_L2, 3)
    boundary = (float(dist_out[ref_edge].mean()) + float(dist_ref[out_edge].mean())) / 2 if ref_edge.any() and out_edge.any() else None
    def holes(mask: np.ndarray) -> int:
        contours, hierarchy = cv2.findContours(mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        return sum(1 for row in (hierarchy[0] if hierarchy is not None else []) if row[3] >= 0)
    skeleton = cv2.ximgproc.thinning(ref.astype(np.uint8) * 255) if hasattr(cv2, "ximgproc") else cv2.erode(ref.astype(np.uint8), np.ones((3, 3), np.uint8))
    dist = cv2.distanceTransform(ref.astype(np.uint8), cv2.DIST_L2, 5)
    widths = 2 * dist[skeleton > 0]
    cer = None
    if recognized_text is not None:
        cer = _edit_distance(expected_text, recognized_text) / max(len(expected_text), 1)
    def bounds(mask: np.ndarray) -> list[int] | None:
        points = cv2.findNonZero(mask.astype(np.uint8))
        if points is None: return None
        x, y, w, h = cv2.boundingRect(points)
        return [int(x), int(y), int(x + w), int(y + h)]
    ref_box, out_box = bounds(ref), bounds(out)
    ref_columns = np.flatnonzero(ref.any(axis=0)); out_columns = np.flatnonzero(out.any(axis=0))
    def run_gaps(columns: np.ndarray) -> list[int]:
        if not columns.size: return []
        cuts = np.where(np.diff(columns) > 1)[0]
        return [int(columns[b + 1] - columns[a] - 1) for a, b in zip(cuts[:-1], cuts[1:])]
    ref_gaps, out_gaps = run_gaps(ref_columns), run_gaps(out_columns)
    ref_baseline = int(np.flatnonzero(ref.any(axis=1))[-1]) if ref.any() else None
    out_baseline = int(np.flatnonzero(out.any(axis=1))[-1]) if out.any() else None
    return {"expectedText": expected_text, "recognizedText": recognized_text,
            "characterErrorRate": cer, "glyphMaskIoU": inter / max(union, 1),
            "glyphBoundaryMeanSymmetricDistancePx": boundary,
            "referenceStrokeWidthMedianPx": float(np.median(widths)) if widths.size else None,
            "referenceStrokeWidthP10Px": float(np.quantile(widths, 0.1)) if widths.size else None,
            "referenceStrokeWidthP90Px": float(np.quantile(widths, 0.9)) if widths.size else None,
            "referenceStrokeWidthCoefficientOfVariation": float(np.std(widths) / max(float(np.mean(widths)), 1e-6)) if widths.size else None,
            "counterCountReference": holes(ref), "counterCountCandidate": holes(out),
            "counterCountDelta": holes(out) - holes(ref),
            "layout": {"referenceGlyphBBox": ref_box, "candidateGlyphBBox": out_box,
                       "bboxDeltaPx": [out_box[i] - ref_box[i] for i in range(4)] if ref_box and out_box else None,
                       "referenceBaselineY": ref_baseline, "candidateBaselineY": out_baseline,
                       "baselineDeltaPx": out_baseline - ref_baseline if out_baseline is not None and ref_baseline is not None else None,
                       "referenceColumnRunCount": int(len(np.split(ref_columns, np.where(np.diff(ref_columns) > 1)[0] + 1))) if ref_columns.size else 0,
                       "candidateColumnRunCount": int(len(np.split(out_columns, np.where(np.diff(out_columns) > 1)[0] + 1))) if out_columns.size else 0,
                       "referenceMeanInterRunGapPx": float(np.mean(ref_gaps)) if ref_gaps else None,
                       "candidateMeanInterRunGapPx": float(np.mean(out_gaps)) if out_gaps else None,
                       "note": "Projection-based rough spacing proxy; not a font kerning ground truth."},
            "recognitionAndGeometryAreSeparate": True}


def text_color_metrics(reference_rgb: np.ndarray, candidate_rgb: np.ndarray, glyph_mask: np.ndarray) -> dict[str, Any]:
    ref = np.asarray(reference_rgb, dtype=np.uint8)
    out = np.asarray(candidate_rgb, dtype=np.uint8)
    mask = np.asarray(glyph_mask, dtype=np.uint8) > 0
    if ref.shape != out.shape or ref.shape[:2] != mask.shape:
        raise ValueError("Color metric inputs must share dimensions.")
    eroded = cv2.erode(mask.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    if not eroded.any(): eroded = mask
    ref_lab, out_lab = rgb2lab(ref.astype(np.float32) / 255.0), rgb2lab(out.astype(np.float32) / 255.0)
    delta = deltaE_ciede2000(ref_lab, out_lab)
    return {"interiorPixelCount": int(eroded.sum()), "medianDeltaE00": float(np.median(delta[eroded])) if eroded.any() else None,
            "p95DeltaE00": float(np.quantile(delta[eroded], 0.95)) if eroded.any() else None,
            "referenceMedianRgb": [int(x) for x in np.median(ref[eroded], axis=0)] if eroded.any() else None,
            "candidateMedianRgb": [int(x) for x in np.median(out[eroded], axis=0)] if eroded.any() else None,
            "groundTruthStatus": "exact generated synthetic fixture mask"}


def create_fixtures() -> dict[str, Any]:
    if not FONT_PATH.is_file():
        raise FileNotFoundError(FONT_PATH)
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    for fixture_id, text, size, weight, color, background in PATTERNS:
        width, height = 1000, 260
        mode = "RGBA" if background is None else "RGB"
        canvas = Image.new(mode, (width, height), (0, 0, 0, 0) if mode == "RGBA" else background)
        if fixture_id == "text_over_art":
            pix = np.zeros((height, width, 3), dtype=np.uint8)
            for y in range(height):
                for x in range(width):
                    pix[y, x] = (int(30 + 180 * x / width), int(40 + 120 * y / height), int(80 + 80 * (x + y) / (width + height)))
            canvas = Image.fromarray(pix, "RGB")
        draw = ImageDraw.Draw(canvas)
        mask = Image.new("L", (width, height), 0)
        mask_draw = ImageDraw.Draw(mask)
        font = _font(size, weight)
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=0)
        x = (width - (bbox[2] - bbox[0])) // 2 - bbox[0]
        y = (height - (bbox[3] - bbox[1])) // 2 - bbox[1]
        draw.text((x, y), text, font=font, fill=color)
        mask_draw.text((x, y), text, font=font, fill=255)
        if fixture_id == "tight_spacing":
            # Explicitly spaced glyph placement; preserve the mask as true ground truth.
            canvas = Image.new("RGB", (width, height), background or "white")
            mask = Image.new("L", (width, height), 0)
            draw, mask_draw = ImageDraw.Draw(canvas), ImageDraw.Draw(mask)
            widths = [draw.textlength(ch, font=font) for ch in text]
            gap = -2.0
            total = sum(widths) + gap * (len(text) - 1)
            x = (width - total) / 2
            y = (height - size) / 2
            for ch, advance in zip(text, widths):
                draw.text((round(x), round(y)), ch, font=font, fill=color)
                mask_draw.text((round(x), round(y)), ch, font=font, fill=255)
                x += advance + gap
        stem = FIXTURE_DIR / fixture_id
        stem.mkdir(parents=True, exist_ok=True)
        source_path, mask_path = stem / "source.png", stem / "glyph_mask.png"
        canvas.save(source_path)
        mask.save(mask_path)
        # Character boxes are derived from font advances; ground truth is annotation for this generated fixture.
        chars, cursor = [], (width - draw.textlength(text, font=font)) / 2
        baseline = y + font.getmetrics()[0] if fixture_id == "tight_spacing" else (height + (bbox[3] - bbox[1])) / 2
        for ch in text:
            adv = float(draw.textlength(ch, font=font))
            chars.append({"character": ch, "advancePx": adv, "approximateX0": cursor, "approximateX1": cursor + adv})
            cursor += adv
        records.append({"fixtureId": fixture_id, "expectedText": text, "fontFile": str(FONT_PATH.relative_to(ARTIFACTS)),
                        "fontSha256": sha256(FONT_PATH), "fontFamily": "Roboto", "fontWeightRequested": weight,
                        "fontSizePx": size, "sourceImage": str(source_path.relative_to(ARTIFACTS)),
                        "glyphMask": str(mask_path.relative_to(ARTIFACTS)), "sourceSha256": sha256(source_path),
                        "maskSha256": sha256(mask_path), "textBboxPx": list(mask.getbbox() or (0, 0, 0, 0)),
                        "baselineYApprox": baseline, "perCharacterAdvanceAnnotations": chars,
                        "groundTruthStatus": "exact synthetic raster mask from same font/render call; not a real-image source"})
    validation_rows = []
    comparison_dir = ARTIFACTS / "typography"
    for record in records:
        mask = np.asarray(Image.open(ARTIFACTS / record["glyphMask"]).convert("L")) > 0
        shifted = np.zeros_like(mask)
        shifted[:, 2:] = mask[:, :-2]
        metrics = typography_metrics(mask, mask, record["expectedText"], record["expectedText"])
        shifted_metrics = typography_metrics(mask, shifted, record["expectedText"], record["expectedText"][:-1])
        source_rgb = np.asarray(Image.open(ARTIFACTS / record["sourceImage"]).convert("RGB"), dtype=np.uint8)
        shifted_rgb = source_rgb.copy()
        # A deterministic, explicitly synthetic color perturbation on glyph pixels.
        shifted_rgb[mask] = np.clip(shifted_rgb[mask].astype(np.int16) + np.array([12, 4, -8]), 0, 255).astype(np.uint8)
        metrics["textFillColorIdentity"] = text_color_metrics(source_rgb, source_rgb, mask)
        metrics["textFillColorControlledShift"] = text_color_metrics(source_rgb, shifted_rgb, mask)
        validation_rows.append({"fixtureId": record["fixtureId"], "identityMetrics": metrics,
                                "controlledDefectMetrics": shifted_metrics,
                                "passesSanity": metrics["glyphMaskIoU"] == 1.0 and metrics["characterErrorRate"] == 0.0 and shifted_metrics["glyphMaskIoU"] < 1.0 and shifted_metrics["characterErrorRate"] > 0.0})
    # Two actual, labeled comparison plates from the fixture masks.
    first = records[0]
    ref = Image.open(ARTIFACTS / first["glyphMask"]).convert("L")
    shift = Image.new("L", ref.size, 0); shift.paste(ref.crop((0, 0, ref.width - 2, ref.height)), (2, 0))
    plate = Image.new("RGB", (1000, 300), "white")
    plate.paste(ref.convert("RGB"), (0, 20)); plate.paste(shift.convert("RGB"), (0, 160))
    plate.save(comparison_dir / "glyph_boundary_comparison.png")
    layout = Image.new("RGB", (1000, 300), "#fafafa")
    layout.paste(Image.open(ARTIFACTS / first["sourceImage"]).convert("RGB"), (0, 20))
    layout.paste(Image.open(ARTIFACTS / records[2]["sourceImage"]).convert("RGB").resize((1000, 130)), (0, 160))
    layout.save(comparison_dir / "text_layout_comparison.png")
    write_json(comparison_dir / "typography_benchmark.json", {"schemaVersion": 1, "fontSha256": sha256(FONT_PATH),
        "fontLicense": "SIL Open Font License 1.1; see fonts/OFL.txt", "syntheticFixtureCount": len(records),
        "fixtures": records, "evaluation": "OCR recognition is not inferred from masks. Exact OCR/geometry metrics shown only on controlled fixture labels."})
    all_pass = all(row["passesSanity"] for row in validation_rows)
    write_json(comparison_dir / "typography_reference_validation.json", {"status": "PASS" if all_pass else "FAIL", "rows": validation_rows,
        "groundTruthIsSynthetic": True, "realImageTypographyGroundTruthCount": 0})
    write_json(comparison_dir / "typography_error_summary.json", {"status": "partial", "groundTruthSyntheticFixtures": len(records),
        "realKnownTextFamilies": ["active-fox-family"], "activeFoxStrings": ["ACTIVE FOX", "YOUR TAGLINE"],
        "activeFoxRecognition": "OCR prediction pending/not promoted to ground truth; OCR output must be measured separately from glyph geometry.",
        "realGlyphReference": "unavailable; no original font/vector ground truth"})
    return {"fixtures": len(records), "validationPass": all_pass}


def evaluate_active_fox_ocr() -> dict[str, Any]:
    """Run the existing local OCR adapter on source/render images; never treat predictions as mask truth."""
    import os
    from mediastudio.image_tools.vectorization_v2.phase_b import get_process_ocr_engine

    source_path = BACKEND / "tests" / "fixtures" / "active_fox.jpg"
    source_image = Image.open(source_path).convert("RGB")
    annotations = {"schemaVersion": 1, "imageId": "active-fox-native-jpeg", "sourceSha256": sha256(source_path),
        "canvas": list(source_image.size), "annotationKind": "fixture-level expected transcription and coarse text ROI",
        "geometryGroundTruth": False, "regions": [
            {"regionId": "title-line", "expectedText": "ACTIVE FOX", "bboxPx": [97, 343, 463, 407],
             "bboxSource": "source OCR detection box, coarse ROI only", "glyphMaskReference": None},
            {"regionId": "tagline", "expectedText": "YOUR TAGLINE", "bboxPx": [192, 408, 362, 438],
             "bboxSource": "source OCR detection box, coarse ROI only", "glyphMaskReference": None}]}
    annotations_dir = ARTIFACTS / "typography" / "active_fox_annotations"
    annotations_dir.mkdir(parents=True, exist_ok=True)
    for item in annotations["regions"]:
        x0, y0, x1, y1 = item["bboxPx"]
        source_image.crop((x0, y0, x1, y1)).save(annotations_dir / f"{item['regionId']}_source_crop.png")
    write_json(ARTIFACTS / "typography" / "active_fox_text_annotations.json", annotations)
    candidates = {"source": source_path}
    old_run = ARTIFACTS.parent / "task_08a" / "runs" / "task08a-2309888c6fd20984" / "outputs" / "active-fox-native-jpeg"
    for engine in ("smart_reconstruction", "contour_preserving"):
        candidates[engine] = old_run / engine / "render_edge.png"
    results = {}
    engine = get_process_ocr_engine()
    for label, path in candidates.items():
        if not path.is_file():
            results[label] = {"status": "unavailable", "reason": "source/render artifact missing"}
            continue
        try:
            image = Image.open(path).convert("RGBA")
            white = Image.new("RGBA", image.size, "white"); white.alpha_composite(image)
            rgb = np.asarray(white.convert("RGB"), dtype=np.uint8)
            detections = engine.detect_and_recognize(rgb)
            results[label] = {"status": engine.status,
                "detections": [{"text": d.raw_text, "confidence": float(d.confidence),
                                "bbox": [float(d.polygon[:, 0].min()), float(d.polygon[:, 1].min()),
                                         float(d.polygon[:, 0].max()), float(d.polygon[:, 1].max())]} for d in detections],
                "predictionOnly": True, "warnings": list(engine.warnings)}
        except Exception as exc:
            results[label] = {"status": "OCR_FALLBACK", "reason": f"{type(exc).__name__}: {exc}", "predictionOnly": True}
    expected = ["ACTIVE FOX", "YOUR TAGLINE"]
    for label, row in results.items():
        if row.get("detections") is not None:
            recognized = " ".join(d["text"] for d in row["detections"]).upper()
            row["expectedText"] = expected
            row["characterErrorRateAgainstKnownFixtureTranscription"] = _edit_distance(" ".join(expected), recognized) / max(len(" ".join(expected)), 1)
            row["recognizedConcatenation"] = recognized
            row["recognitionCaveat"] = "Recognition score only; no glyph-boundary/font/layout ground truth for the real image."
    source_detections = results.get("source", {}).get("detections", [])
    for label in ("smart_reconstruction", "contour_preserving"):
        row = results.get(label, {})
        if row.get("detections") is None or source_detections is None: continue
        deltas = []
        for expected in expected:
            src = next((d for d in source_detections if d["text"].casefold() == expected.casefold()), None)
            dst = next((d for d in row["detections"] if d["text"].casefold() == expected.casefold()), None)
            if src and dst:
                deltas.append({"text": expected, "ocrBBoxDeltaPx": [round(dst["bbox"][i] - src["bbox"][i], 3) for i in range(4)],
                               "sourceConfidence": src["confidence"], "outputConfidence": dst["confidence"]})
        row["ocrBoxLayoutComparison"] = deltas
        row["layoutComparisonCaveat"] = "OCR detector boxes are coarse layout proxies, not glyph-boundary or baseline ground truth."
    status = "OCR_READY" if engine.status == "OCR_READY" else engine.status
    result = {"status": status, "engineClass": type(engine).__name__, "modelDirectory": str(engine.model_directory),
              "outputs": results, "expectedTranscriptionSource": "user-provided fixture annotation for ACTIVE FOX and YOUR TAGLINE",
              "doesNotImplyGlyphFidelity": True}
    write_json(ARTIFACTS / "typography" / "active_fox_ocr_predictions.json", result)
    return result

