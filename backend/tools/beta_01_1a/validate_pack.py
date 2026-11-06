from __future__ import annotations

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from PIL import Image
import numpy as np

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))
from tools.vectorization_benchmark.svg import render_svg_edge  # noqa: E402

PACK = REPO / "mediastudio_beta_testpack"
OUT = BACKEND / "artifacts" / "contour_preserving" / "beta_01_1a"
SVG_NS = "http://www.w3.org/2000/svg"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = PACK / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    items = manifest.get("items")
    if not isinstance(items, list):
        raise ValueError("manifest.items must be an array")

    problems: list[dict[str, str]] = []
    def issue(code: str, detail: str) -> None:
        problems.append({"code": code, "detail": detail})

    expected = {
        "sourceArtworkCount": 24,
        "png512Count": 24,
        "png256Count": 24,
        "jpegVariantCount": 4,
        "referenceSvgCount": 23,
        "analyticReferenceCount": 1,
    }
    ids = [str(item.get("id", "")) for item in items]
    counts = {
        "sourceArtworkCount": len(items),
        "png512Count": len(list((PACK / "inputs_png_512").glob("*.png"))),
        "png256Count": len(list((PACK / "inputs_png_256").glob("*.png"))),
        "jpegVariantCount": len(list((PACK / "jpeg_variants_512").glob("*.jpg"))),
        "referenceSvgCount": len(list((PACK / "reference_svg").glob("*.svg"))),
        "analyticReferenceCount": len(list((PACK / "reference_analytic").glob("*.json"))),
    }
    for key, want in expected.items():
        if counts[key] != want:
            issue("COUNT_MISMATCH", f"{key}: expected {want}, actual {counts[key]}")
    if len(set(ids)) != len(ids):
        issue("DUPLICATE_FIXTURE_ID", "manifest has duplicate fixture IDs")

    family_ids = [str(item.get("source_family_id", "")) for item in items]
    if any(not value for value in family_ids) or len(set(family_ids)) != len(family_ids):
        issue("SOURCE_FAMILY_MAPPING", "source_family_id missing or duplicated among fixture families")
    if manifest.get("source_family_count") != 24 or manifest.get("synthetic_source_families") != 24:
        issue("FAMILY_COUNT_MISMATCH", "manifest family totals do not declare 24 synthetic families")
    if manifest.get("real_independent_design_families") != 0 or manifest.get("status") != "synthetic_only":
        issue("PROVENANCE_CLASSIFICATION", "manifest must classify this pack synthetic-only with zero real families")

    file_checks: list[dict[str, Any]] = []
    reference_map: list[dict[str, Any]] = []
    required_preflight = {"C01_three_tone_disc", "C06_rocket", "D01_small_colored_islands", "A04_transparent_fine_lines"}
    if not required_preflight.issubset(set(ids)):
        issue("PREFLIGHT_FIXTURES_MISSING", f"missing IDs: {sorted(required_preflight - set(ids))}")

    for item in items:
        fid = str(item["id"])
        row: dict[str, Any] = {"fixtureId": fid, "sourceFamilyId": item.get("source_family_id"), "files": []}
        if item.get("origin") != "programmatically_authored_synthetic" or item.get("beta_real_family_eligible") is not False:
            issue("SYNTHETIC_PROVENANCE", f"{fid} is not explicitly marked synthetic and ineligible as real artwork")
        ref_rel = item.get("reference_svg")
        ref_path = PACK / str(ref_rel) if ref_rel else None
        if item.get("ground_truth_kind") == "analytic_2d_color_field":
            if ref_path is not None or item.get("reference_analytic") != "reference_analytic/G04_nonlinear_2d_analytic.json":
                issue("ANALYTIC_REFERENCE_MAPPING", f"{fid}: expected its analytic reference mapping")
            row["referenceSvg"] = None
            row["analyticReference"] = item.get("reference_analytic")
        elif ref_path is not None and ref_path.is_file():
            actual_hash = sha256(ref_path)
            expected_hash = item.get("source_sha256")
            hash_ok = actual_hash == expected_hash
            try:
                root = ET.parse(ref_path).getroot()
                xml_ok = root.tag == f"{{{SVG_NS}}}svg"
                view_box = [float(x) for x in root.attrib.get("viewBox", "").replace(",", " ").split()]
                view_box_ok = len(view_box) == 4 and view_box[2] > 0 and view_box[3] > 0
            except Exception as exc:
                xml_ok, view_box_ok = False, False
                issue("REFERENCE_SVG_PARSE", f"{fid}: {exc}")
                root, view_box = None, []
            if not hash_ok:
                issue("REFERENCE_SVG_HASH", f"{fid}: manifest {expected_hash}, actual {actual_hash}")
            if not xml_ok or not view_box_ok:
                issue("REFERENCE_SVG_DIMENSIONS", f"{fid}: SVG root/viewBox invalid")
            row["referenceSvg"] = {"path": str(ref_path), "sha256Expected": expected_hash,
                "sha256Actual": actual_hash, "hashMatches": hash_ok, "xmlValid": xml_ok,
                "viewBox": view_box, "viewBoxValid": view_box_ok}
        else:
            issue("REFERENCE_SVG_MISSING", f"{fid}: {ref_rel}")
            row["referenceSvg"] = {"path": str(ref_path) if ref_path else None, "exists": False}

        for size, expected_size in (("512", (512, 512)), ("256", (256, 256))):
            rel = item.get("png_paths", {}).get(size)
            path = PACK / str(rel) if rel else None
            expected_png_hash = item.get("png_sha256", {}).get(size)
            result: dict[str, Any] = {"sizeClass": size, "path": str(path) if path else None, "exists": bool(path and path.is_file())}
            if not path or not path.is_file():
                issue("PNG_MISSING", f"{fid} {size}: {rel}")
            else:
                actual_png_hash = sha256(path)
                try:
                    with Image.open(path) as im:
                        im.verify()
                    with Image.open(path) as im:
                        w, h = im.size
                        bands = im.getbands()
                        fmt = im.format
                        alpha_extrema = im.getchannel("A").getextrema() if "A" in bands else None
                        rgba = np.asarray(im.convert("RGBA"), dtype=np.uint8)
                        alpha_valid = rgba.shape == (expected_size[1], expected_size[0], 4) and np.isfinite(rgba).all()
                    dims_ok = (w, h) == expected_size
                    hash_ok = actual_png_hash == expected_png_hash
                except Exception as exc:
                    issue("PNG_DECODE", f"{fid} {size}: {exc}")
                    w = h = 0; bands = (); fmt = None; alpha_extrema = None; dims_ok = hash_ok = alpha_valid = False
                if not hash_ok:
                    issue("PNG_HASH", f"{fid} {size}: expected {expected_png_hash}, actual {actual_png_hash}")
                if not dims_ok:
                    issue("PNG_DIMENSIONS", f"{fid} {size}: expected {expected_size}, actual {(w, h)}")
                if not alpha_valid:
                    issue("PNG_ALPHA_INVALID", f"{fid} {size}: decoded RGBA/alpha is invalid")
                result.update({"sha256Expected": expected_png_hash, "sha256Actual": actual_png_hash,
                    "hashMatches": hash_ok, "width": w, "height": h, "dimensionsMatch": dims_ok,
                    "format": fmt, "bands": list(bands), "alphaExtrema": list(alpha_extrema) if alpha_extrema else None,
                    "alphaValid": bool(alpha_valid)})
            row["files"].append(result)

        jpeg = item.get("jpeg_variant")
        if jpeg:
            path = PACK / str(jpeg.get("path"))
            actual = sha256(path) if path.is_file() else None
            hash_ok = actual == jpeg.get("sha256")
            try:
                with Image.open(path) as im:
                    im.verify()
                with Image.open(path) as im:
                    dims_ok = im.size == (512, 512)
                    mode, fmt = im.mode, im.format
            except Exception as exc:
                dims_ok = False; mode = fmt = None
                issue("JPEG_DECODE", f"{fid}: {exc}")
            if not hash_ok:
                issue("JPEG_HASH", f"{fid}: expected {jpeg.get('sha256')}, actual {actual}")
            if not dims_ok or fmt != "JPEG":
                issue("JPEG_DIMENSIONS_FORMAT", f"{fid}: size/format mismatch")
            row["jpegVariant"] = {"path": str(path), "sha256Expected": jpeg.get("sha256"),
                "sha256Actual": actual, "hashMatches": hash_ok, "width": 512 if dims_ok else None,
                "height": 512 if dims_ok else None, "format": fmt, "mode": mode, "notIndependent": jpeg.get("not_independent")}
        else:
            row["jpegVariant"] = None

        # Render the mapped source SVG in the same native browser and compare it to the 512 PNG.
        if (item.get("ground_truth_kind") == "source_svg_vector_geometry" and ref_path and ref_path.is_file()
                and row["files"] and row["files"][0].get("exists")):
            try:
                reference_rgba = render_svg_edge(ref_path, width=512, height=512)
                with Image.open(PACK / str(item["png_paths"]["512"])) as im:
                    source_rgba = np.asarray(im.convert("RGBA"), dtype=np.uint8)
                reference_alpha = reference_rgba[..., 3] > 16
                source_alpha = source_rgba[..., 3] > 16
                union = int(np.count_nonzero(reference_alpha | source_alpha))
                intersection = int(np.count_nonzero(reference_alpha & source_alpha))
                alpha_iou = intersection / max(union, 1)
                source_alpha_128 = source_rgba[..., 3] > 128
                reference_alpha_128 = reference_rgba[..., 3] > 128
                union_128 = int(np.count_nonzero(reference_alpha_128 | source_alpha_128))
                intersection_128 = int(np.count_nonzero(reference_alpha_128 & source_alpha_128))
                alpha_iou_128 = intersection_128 / max(union_128, 1)
                def bbox(mask: np.ndarray) -> list[int] | None:
                    yy, xx = np.where(mask)
                    return [int(xx.min()), int(yy.min()), int(xx.max() + 1), int(yy.max() + 1)] if len(xx) else None
                source_bbox = bbox(source_alpha_128)
                reference_bbox = bbox(reference_alpha_128)
                mae_rgba = float(np.abs(reference_rgba.astype(np.float32) - source_rgba.astype(np.float32)).mean())
                # A04 is an antialiased fine-line image. The pack and Edge may
                # differ at coverage pixels even when the mapped geometry/bbox
                # and opaque-core mask agree. Preserve both thresholds as baseline.
                ref_vs_input_ok = alpha_iou_128 >= 0.97 and source_bbox == reference_bbox and mae_rgba <= 4.0
                reference_map.append({"fixtureId": fid, "renderer": "Microsoft Edge headless, native 512x512",
                    "alphaIoUThreshold16": alpha_iou, "alphaIoUThreshold128": alpha_iou_128,
                    "sourceOpaqueCoreBBox": source_bbox, "referenceOpaqueCoreBBox": reference_bbox,
                    "rgbaMeanAbsoluteDifference": mae_rgba,
                    "mappingConsistent": ref_vs_input_ok,
                    "note": "Mapping compares the manifest-linked source PNG and reference SVG using Edge at 512x512. Both alpha thresholds and RGBA MAE are retained because fine-line antialiasing differs between source rasterization and Edge."})
                if not ref_vs_input_ok:
                    issue("RASTER_REFERENCE_MAPPING", f"{fid}: alphaIoU@128={alpha_iou_128:.6f}, sourceBBox={source_bbox}, referenceBBox={reference_bbox}, rgbaMAE={mae_rgba:.4f}")
            except Exception as exc:
                issue("REFERENCE_RENDER", f"{fid}: {exc}")

        file_checks.append(row)

    analytic = PACK / "reference_analytic" / "G04_nonlinear_2d_analytic.json"
    analytic_ok = analytic.is_file()
    if analytic_ok:
        try:
            analytic_data = json.loads(analytic.read_text(encoding="utf-8"))
            analytic_valid = isinstance(analytic_data, dict) and bool(analytic_data)
        except Exception as exc:
            analytic_valid = False
            issue("ANALYTIC_REFERENCE_PARSE", str(exc))
    else:
        analytic_valid = False
        issue("ANALYTIC_REFERENCE_MISSING", str(analytic))
    if not analytic_valid:
        issue("ANALYTIC_REFERENCE_INVALID", "analytic reference is absent, empty, or invalid JSON")

    # The package's only real design family count must remain zero; variants are never independent.
    family_check = {
        "declaredSourceFamilyCount": manifest.get("source_family_count"),
        "uniqueManifestFamilyCount": len(set(family_ids)),
        "manifestItemCount": len(items),
        "jpegVariantCount": sum(1 for item in items if item.get("jpeg_variant")),
        "variantsCountDeclared": manifest.get("variants_count"),
        "allOriginsSynthetic": all(item.get("origin") == "programmatically_authored_synthetic" for item in items),
        "allVariantsMarkedNotIndependent": all(item.get("variants_not_independent") is True for item in items),
        "realIndependentArtworkFamilies": manifest.get("real_independent_design_families"),
        "duplicateSourceFamilyIds": sorted({x for x in family_ids if family_ids.count(x) > 1}),
    }
    family_valid = (family_check["declaredSourceFamilyCount"] == 24 and family_check["uniqueManifestFamilyCount"] == 24
        and family_check["allOriginsSynthetic"] and family_check["allVariantsMarkedNotIndependent"]
        and family_check["realIndependentArtworkFamilies"] == 0 and not family_check["duplicateSourceFamilyIds"])
    if not family_valid:
        issue("SOURCE_FAMILY_VALIDATION", "manifest source-family and variant relationships are inconsistent")

    pack_valid = not problems
    result = {
        "schemaVersion": 1,
        "packPath": str(PACK),
        "manifestPath": str(manifest_path),
        "datasetId": manifest.get("dataset_id"),
        "classification": manifest.get("status"),
        "expectedCounts": expected,
        "actualCounts": counts,
        "fixtureIds": ids,
        "files": file_checks,
        "referenceRasterMapping": reference_map,
        "sourceFamilyValidation": family_check,
        "sourceFamilyValidationPassed": family_valid,
        "analyticReference": {"path": str(analytic), "exists": analytic_ok, "validJson": analytic_valid},
        "issues": problems,
        "inputPackValid": pack_valid,
        "renderer": "Microsoft Edge headless",
        "policy": "No manifest or source files were modified by validation.",
    }
    write_json(OUT / "input_manifest_validation.json", result)
    write_json(OUT / "source_family_validation.json", {**family_check, "validationPassed": family_valid,
        "sourceRows": [{"fixtureId": item.get("id"), "sourceFamilyId": item.get("source_family_id"),
            "origin": item.get("origin"), "betaRealFamilyEligible": item.get("beta_real_family_eligible"),
            "variantsNotIndependent": item.get("variants_not_independent"),
            "jpegVariant": item.get("jpeg_variant")} for item in items]})
    print(json.dumps({"INPUT_PACK_VALID": pack_valid, "counts": counts, "familyValidation": family_valid,
        "referenceMappingsCompared": len(reference_map), "mappingFailures": [x for x in reference_map if not x["mappingConsistent"]],
        "issues": problems}, indent=2, ensure_ascii=False))
    return 0 if pack_valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
