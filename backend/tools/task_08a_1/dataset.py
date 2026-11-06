from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
import cv2
from PIL import Image

BACKEND = Path(__file__).resolve().parents[2]
REPOSITORY = BACKEND.parent
ARTIFACTS = BACKEND / "artifacts" / "contour_preserving" / "task_08a_1"
SOURCE_ROOT = ARTIFACTS / "acquired" / "scikit_image"
MANIFEST = ARTIFACTS / "real_dataset_manifest.json"
BASE_MANIFEST = BACKEND / "artifacts" / "contour_preserving" / "task_08a" / "benchmark_manifest.json"
CATEGORIES = (
    "flat_logos_icons", "gradient_logos", "line_art_thin_details",
    "multicolor_illustrations", "typography_mixed_artwork", "transparency",
    "jpeg_noise_complex_raster",
)
SAMPLE_META = {
    "astronaut": ("photo-astronaut", ["jpeg_noise_complex_raster"], "NASA/Great Images in NASA", "public_domain", "https://flic.kr/p/r9qvLn"),
    "camera": ("photo-camera", ["jpeg_noise_complex_raster"], "Lav Varshney", "CC0", "https://scikit-image.org/docs/stable/api/skimage.data.html"),
    "chelsea": ("photo-chelsea-cat", ["jpeg_noise_complex_raster"], "Stefan van der Walt", "CC0", "https://scikit-image.org/docs/stable/api/skimage.data.html"),
    "clock": ("photo-clock", ["jpeg_noise_complex_raster"], "Stefan van der Walt", "public_domain", "https://scikit-image.org/docs/stable/api/skimage.data.html"),
    "coffee": ("photo-coffee", ["jpeg_noise_complex_raster"], "Rachel Michetti / Pikolo", "CC0", "https://scikit-image.org/docs/stable/api/skimage.data.html"),
    "eagle": ("photo-eagle", ["jpeg_noise_complex_raster"], "Dayane Machado", "CC0", "https://scikit-image.org/docs/stable/api/skimage.data.html"),
    "horse": ("icon-horse-alpha", ["flat_logos_icons", "transparency"], "Andreas Preuss (marauder), OpenClipart", "CC0", "https://scikit-image.org/docs/stable/api/skimage.data.html"),
    "retina": ("photo-retina", ["jpeg_noise_complex_raster"], "scikit-image sample dataset contributors", "CC0", "https://scikit-image.org/docs/stable/api/skimage.data.html"),
    "text": ("raster-text-sample", ["typography_mixed_artwork"], "Wikipedia / scikit-image sample data", "public_domain", "https://scikit-image.org/docs/stable/api/skimage.data.html"),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def perceptual_hash64(path: Path) -> str:
    """Task 08A-compatible 64-bit DCT perceptual hash."""
    with Image.open(path) as im:
        gray = np.asarray(im.convert("L").resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float32)
    block = cv2.dct(gray)[:8, :8].copy()
    values = block.reshape(-1)[1:]
    bits = values > float(np.median(values))
    return f"{sum(int(v) << i for i, v in enumerate(bits.flat)):016x}"


def hamming(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _item(image_id: str, family: str, path: str, source_type: str, categories: list[str],
          author: str, license_status: str, provenance_url: str, split: str,
          description: str, *, variant: str = "original") -> dict[str, Any]:
    p = REPOSITORY / path
    with Image.open(p) as image:
        fmt = (image.format or p.suffix.lstrip(".")).upper()
        has_alpha = "A" in image.getbands() or "transparency" in image.info
        alpha_extrema = image.getchannel("A").getextrema() if "A" in image.getbands() else None
        width, height = image.size
    return {
        "imageId": image_id, "sourceFamilyId": family, "variantId": variant,
        "path": p.relative_to(REPOSITORY).as_posix(), "sha256": sha256(p), "perceptualHash64": perceptual_hash64(p),
        "sourceType": source_type, "categories": categories, "width": width, "height": height,
        "fileFormat": fmt, "alpha": {"hasAlphaChannel": has_alpha, "alphaExtrema": alpha_extrema,
                                       "hasNonOpaqueAlpha": bool(alpha_extrema and alpha_extrema[0] < 255)},
        "sourceProvenance": {"sourceKind": "public_sample_dataset" if source_type == "real_public_sample" else "user_provided_project_fixture",
                             "sourceDescription": description, "author": author,
                             "licenseStatus": license_status, "provenanceUrl": provenance_url,
                             "usagePermission": "public dataset license recorded; retain attribution/provenance",
                             "provenanceVerified": "Documented by the upstream scikit-image sample-data documentation; this does not imply category representativeness."},
        "licenseStatus": license_status, "provenanceUrl": provenance_url,
        "referenceType": "real_raster_without_vector_ground_truth", "hasOriginalVectorGroundTruth": False,
        "hasManualValidatedMasks": False, "hasAnalyticMask": False, "hasAnalyticSemanticLabels": False,
        "referenceFiles": {}, "hasTypography": "typography_mixed_artwork" in categories,
        "datasetSplit": split, "annotationStatus": "pending_or_unavailable",
        "groundTruthStatus": "source raster only; no verified vector reference",
    }


def build_manifest() -> dict[str, Any]:
    old = json.loads(BASE_MANIFEST.read_text(encoding="utf-8"))
    items = []
    for row in old["items"]:
        clone = dict(row)
        if row.get("sourceType") == "real_raster_user_provided":
            clone["datasetSplit"] = "development"
            clone["sourceFamilyId"] = "active-fox-family"
            clone["sourceType"] = "real_raster_user_provided"
            clone["groundTruthStatus"] = "source raster only; vector reference unknown"
            clone["provenanceUrl"] = "local://user-provided-fixture-no-redistribution"
        else:
            # Carry the Task 08A analytical fixtures forward as a separate evidence class.
            clone["sourceType"] = "synthetic_analytical_fixture"
            clone["groundTruthStatus"] = "synthetic analytical source with Task 07.2 analytic reference; previously exposed in Task 08A"
        items.append(clone)
    for name, (family, categories, author, license_status, url) in SAMPLE_META.items():
        filename = f"{name}.png" if name != "retina" else "retina.jpg"
        rel = (SOURCE_ROOT / filename).relative_to(REPOSITORY).as_posix()
        items.append(_item(name, family, rel, "real_public_sample", categories, author, license_status,
                           url, "review_analysis", f"Upstream scikit-image sample {name}; image used as-is."))
    return {"schemaVersion": 1, "datasetId": "mediastudio-vectorization-task-08a-1-real",
            "createdAtUtc": datetime.now(timezone.utc).isoformat(),
            "purpose": "Task 08A.1 real raster evaluation and review package. Dataset expansion is evidence only; no vectorization algorithm changes.",
            "splitPolicy": "Split by sourceFamilyId. ACTIVE FOX native/upscaled remain development. Newly acquired samples are review_analysis and are not blind held-out data.",
            "sourcePolicy": "No personal-drive scanning. Public sample provenance/license recorded per image; user fixture remains local-only.",
            "items": items}


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    items = manifest.get("items", [])
    missing, bad_hash, incomplete, exact, near, split_conflicts, invalid_provenance = [], [], [], [], [], [], []
    family_split: dict[str, set[str]] = {}
    hashes: dict[str, str] = {}
    for item in items:
        path = REPOSITORY / item.get("path", "")
        if not path.is_file():
            missing.append(item.get("imageId")); continue
        actual = sha256(path)
        if actual != item.get("sha256"):
            bad_hash.append({"imageId": item.get("imageId"), "expected": item.get("sha256"), "actual": actual})
        required = ("sourceFamilyId", "datasetSplit", "categories")
        if item.get("sourceType", "").startswith("real_"):
            required += ("licenseStatus", "provenanceUrl", "sourceProvenance")
        if any(not item.get(key) for key in required):
            incomplete.append(item.get("imageId"))
        if item.get("sourceType", "").startswith("real_"):
            provenance = str(item.get("provenanceUrl", ""))
            parsed = urlparse(provenance)
            author = item.get("sourceProvenance", {}).get("author")
            if parsed.scheme not in {"http", "https", "local"} or not author:
                invalid_provenance.append({"imageId": item.get("imageId"), "provenanceUrl": provenance,
                                           "authorPresent": bool(author)})
        family_split.setdefault(item["sourceFamilyId"], set()).add(item["datasetSplit"])
        if actual in hashes:
            exact.append({"imageA": hashes[actual], "imageB": item["imageId"], "sha256": actual})
        else:
            hashes[actual] = item["imageId"]
    for family, splits in family_split.items():
        if len(splits) > 1:
            split_conflicts.append({"sourceFamilyId": family, "splits": sorted(splits)})
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a.get("sourceFamilyId") == b.get("sourceFamilyId"):
                continue
            distance = hamming(a["perceptualHash64"], b["perceptualHash64"])
            if distance <= 5:
                near.append({"imageA": a["imageId"], "imageB": b["imageId"], "hammingDistance": distance,
                             "sameSplit": a["datasetSplit"] == b["datasetSplit"], "status": "review_required"})
    families = {item["sourceFamilyId"] for item in items if item["sourceType"].startswith("real_")}
    synthetic = [item for item in items if item["sourceType"] == "synthetic_analytical_fixture"]
    cat = {}
    for category in CATEGORIES:
        matched = [i for i in items if i["sourceType"].startswith("real_") and category in i["categories"]]
        cat[category] = {"familyCount": len({i["sourceFamilyId"] for i in matched}),
                         "imageVariantCount": len(matched), "targetFamilies": 4,
                         "coverageSufficient": len({i["sourceFamilyId"] for i in matched}) >= 4,
                         "imageIds": [i["imageId"] for i in matched]}
    coverage = len(families) >= 8 and all(row["coverageSufficient"] for row in cat.values())
    provenance_ok = not (missing or bad_hash or incomplete or exact or invalid_provenance)
    split_ok = not split_conflicts
    return {"status": "PASS" if provenance_ok and split_ok else "FAIL", "manifestSha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
            "variantCount": len(items), "independentRealImageCount": len(families),
            "syntheticFixtureCount": len(synthetic), "sourceFamilyCount": len({i["sourceFamilyId"] for i in items}),
            "missingImageIds": missing, "hashMismatches": bad_hash, "incompleteProvenance": incomplete,
            "invalidProvenance": invalid_provenance,
            "exactDuplicatePairs": exact, "nearDuplicateReviewPairs": near, "sourceFamilySplitConflicts": split_conflicts,
            "categoryCoverage": cat, "DATASET_COVERAGE_SUFFICIENT": coverage,
            "REAL_WORLD_GENERALIZATION_PROVEN": False,
            "notes": ["Near duplicates are review flags, not automatic merge decisions.", "Public samples are heterogeneous; most are photos, so no unsupported logo/line-art coverage is claimed."]}


def split_lock(manifest: dict[str, Any]) -> dict[str, Any]:
    return {"schemaVersion": 1, "lockedAtUtc": datetime.now(timezone.utc).isoformat(),
            "manifestSha256": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
            "assignments": {i["sourceFamilyId"]: i["datasetSplit"] for i in manifest["items"]},
            "blindHoldoutFamilies": [],
            "warning": "All Task 08A and 08A.1 samples have been exposed to analysis; do not call any of them blind for Task 08B."}


def import_source(source: Path, category: str, family_id: str, license_status: str,
                  provenance_url: str, author: str, split: str = "review_analysis") -> dict[str, Any]:
    source = source.resolve()
    if not source.is_file() or category not in CATEGORIES or not all((family_id, license_status, provenance_url, author)):
        raise ValueError("Source file, known category, family ID, author, license status, and provenance URL are required.")
    with Image.open(source) as image:
        image.verify()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    digest = sha256(source)
    if any(i["sha256"] == digest for i in manifest["items"]):
        raise ValueError("Exact source duplicate already exists in the dataset.")
    existing_family = [i for i in manifest["items"] if i.get("sourceFamilyId") == family_id]
    if existing_family and any(i.get("datasetSplit") != split for i in existing_family):
        raise ValueError("All variants in a source family must use one split; resolve the family split before importing.")
    dest_dir = ARTIFACTS / "imported"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{digest[:12]}{source.suffix.lower()}"
    if not dest.exists():
        dest.write_bytes(source.read_bytes())
    row = _item(f"import-{digest[:12]}", family_id, dest.relative_to(REPOSITORY).as_posix(), "real_user_import",
                [category], author, license_status, provenance_url, split, "Imported by Task 08A.1 CLI.")
    manifest["items"].append(row)
    write_json(MANIFEST, manifest)
    return {"imported": row["imageId"], "familyId": family_id, "sha256": digest,
            "nearDuplicates": [i for i in manifest["items"] if i["imageId"] != row["imageId"] and hamming(row["perceptualHash64"], i["perceptualHash64"]) <= 5]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Task 08A.1 dataset import and provenance validation")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("validate")
    imp = sub.add_parser("import")
    imp.add_argument("--source", type=Path, required=True)
    imp.add_argument("--category", choices=CATEGORIES, required=True)
    imp.add_argument("--source-family-id", required=True)
    imp.add_argument("--license-status", required=True)
    imp.add_argument("--provenance-url", required=True)
    imp.add_argument("--author", required=True)
    imp.add_argument("--split", choices=("development", "review_analysis", "heldout"), default="review_analysis")
    args = parser.parse_args()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if args.command == "init":
        if not MANIFEST.exists():
            write_json(MANIFEST, build_manifest())
        m = json.loads(MANIFEST.read_text(encoding="utf-8"))
        v = validate_manifest(m)
        write_json(ARTIFACTS / "dataset_split_lock.json", split_lock(m))
    elif args.command == "import":
        print(json.dumps(import_source(args.source, args.category, args.source_family_id, args.license_status,
                                       args.provenance_url, args.author, args.split), indent=2, ensure_ascii=False)); return 0
    else:
        m = json.loads(MANIFEST.read_text(encoding="utf-8")); v = validate_manifest(m)
    write_json(ARTIFACTS / "dataset_import_report.json", {"status": "initialized", "builtInNewPublicSources": 9,
                                                           "userImports": sum(i["sourceType"] == "real_user_import" for i in m["items"])})
    write_json(ARTIFACTS / "source_family_validation.json", {"status": "PASS" if not v["exactDuplicatePairs"] and not v["sourceFamilySplitConflicts"] else "FAIL",
                                                              "exactDuplicatePairs": v["exactDuplicatePairs"], "nearDuplicateReviewPairs": v["nearDuplicateReviewPairs"],
                                                              "sourceFamilySplitConflicts": v["sourceFamilySplitConflicts"]})
    write_json(ARTIFACTS / "dataset_split_validation.json", {"status": "PASS" if not v["sourceFamilySplitConflicts"] else "FAIL",
                                                               "assignments": split_lock(m)["assignments"], "blindHoldoutFamilies": []})
    write_json(ARTIFACTS / "dataset_coverage.json", v)
    write_json(ARTIFACTS / "missing_dataset_categories.json", {"missingCategories": [k for k, x in v["categoryCoverage"].items() if not x["coverageSufficient"]],
                                                                 "coverage": v["categoryCoverage"], "target": "4 independent source families per category; Task 08A.1 target 8-12 families is only an intermediate milestone"})
    print(json.dumps({"validation": v, "manifest": str(MANIFEST)}, indent=2, ensure_ascii=False))
    return 0 if v["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
