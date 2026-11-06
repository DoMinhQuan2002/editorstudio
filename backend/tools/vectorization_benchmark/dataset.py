from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

import cv2
import numpy as np
from PIL import Image


BACKEND = Path(__file__).resolve().parents[2]
REPOSITORY = BACKEND.parent
ARTIFACTS = BACKEND / "artifacts" / "contour_preserving" / "task_08a"
TASK072 = BACKEND / "artifacts" / "contour_preserving" / "task_07_2"
MANIFEST_PATH = ARTIFACTS / "benchmark_manifest.json"
SPLIT_PATH = ARTIFACTS / "dataset_split.json"

CATEGORY_NAMES = (
    "flat_logos_icons",
    "gradient_logos",
    "line_art_thin_details",
    "multicolor_illustrations",
    "typography_mixed_artwork",
    "transparency",
    "jpeg_noise_complex_raster",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(encoded)
    os.replace(temporary, path)


def relative_or_absolute(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPOSITORY.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (REPOSITORY / path)


def image_metadata(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        width, height = image.size
        image_format = image.format
        mode = image.mode
        has_alpha = "A" in image.getbands() or "transparency" in image.info
        alpha_range = image.getchannel("A").getextrema() if "A" in image.getbands() else None
    return {
        "width": int(width), "height": int(height), "format": str(image_format or path.suffix.lstrip(".")).upper(),
        "mode": mode, "hasAlphaChannel": bool(has_alpha),
        "alphaExtrema": list(alpha_range) if alpha_range else None,
        "hasNonOpaqueAlpha": bool(alpha_range and alpha_range[0] < 255),
    }


def perceptual_hash(path: Path) -> str:
    with Image.open(path) as image:
        gray = np.asarray(image.convert("L").resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float32)
    dct = cv2.dct(gray)
    block = dct[:8, :8].copy()
    values = block.reshape(-1)[1:]
    median = float(np.median(values))
    bits = (values > median).astype(np.uint8)
    packed = np.packbits(bits, bitorder="big")
    return packed.tobytes().hex()


def hamming_distance(hex_a: str, hex_b: str) -> int:
    return sum((int(a, 16) ^ int(b, 16)).bit_count() for a, b in zip(hex_a, hex_b))


def _categories_for_synthetic(name: str, has_alpha: bool) -> list[str]:
    category: list[str] = []
    flat = {"circle", "ellipse", "rounded_rectangle", "sharp_polygon", "star", "adjacent_colors", "nested_regions", "small_colored_island"}
    gradients = {"linear_gradient", "radial_gradient", "mixed_sharp_soft", "narrow_highlight_near_boundary"}
    thin = {"thin_line", "tapered_curve", "intentional_pixel_staircase", "narrow_highlight_near_boundary"}
    multicolor = {"adjacent_colors", "nested_regions", "small_colored_island", "mixed_sharp_soft", "multiregion_illustration", "jpeg_compressed_illustration", "narrow_highlight_near_boundary"}
    if name in flat:
        category.append("flat_logos_icons")
    if name in gradients:
        category.append("gradient_logos")
    if name in thin:
        category.append("line_art_thin_details")
    if name in multicolor:
        category.append("multicolor_illustrations")
    if has_alpha:
        category.append("transparency")
    if name == "jpeg_compressed_illustration":
        category.append("jpeg_noise_complex_raster")
    return category or ["flat_logos_icons"]


def _export_synthetic_references() -> tuple[dict[str, dict[str, str]], list[str]]:
    validation = json.loads((TASK072 / "synthetic_analytical_validation.json").read_text(encoding="utf-8"))
    generator_path = TASK072 / "synthetic_analytical_validation.py"
    spec = importlib.util.spec_from_file_location("task072_synthetic_fixture_generator", generator_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load analytical fixture generator: {generator_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    reference_dir = ARTIFACTS / "dataset_references" / "synthetic"
    reference_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for name in sorted(validation["fixtures"]):
        item = validation["fixtures"][name]
        source_path = resolve_path(Path(item["source"]).as_posix())
        if not source_path.is_file():
            errors.append(f"missing_synthetic_source:{name}")
            continue
        rgba, semantic = module._shape(name)
        with Image.open(source_path) as image:
            existing = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        if not np.array_equal(existing, rgba):
            errors.append(f"synthetic_generator_source_mismatch:{name}")
            continue
        label_path = reference_dir / f"{name}_semantic_labels.png"
        alpha_truth_path = reference_dir / f"{name}_analytic_alpha.png"
        Image.fromarray(np.asarray(semantic, dtype=np.uint8), mode="L").save(label_path)
        Image.fromarray(np.asarray(rgba[..., 3], dtype=np.uint8), mode="L").save(alpha_truth_path)
        result[name] = {
            "semanticLabelMapPath": relative_or_absolute(label_path),
            "semanticLabelMapSha256": sha256_file(label_path),
            "analyticAlphaMaskPath": relative_or_absolute(alpha_truth_path),
            "analyticAlphaMaskSha256": sha256_file(alpha_truth_path),
            "groundTruthProvenance": "Derived deterministically from the existing Task 07.2 analytical fixture generator; source pixels were array-verified before the sidecars were written.",
        }
    return result, errors


def _make_item(
    image_id: str,
    path: Path,
    *,
    source_family_id: str,
    source_type: str,
    categories: list[str],
    split: str,
    provenance: dict[str, Any],
    reference_type: str,
    has_original_vector_ground_truth: bool,
    has_analytic_mask: bool = False,
    has_analytic_semantic_labels: bool = False,
    reference_paths: dict[str, str] | None = None,
    has_typography: bool = False,
    complexity_notes: str = "",
) -> dict[str, Any]:
    metadata = image_metadata(path)
    return {
        "imageId": image_id,
        "sourceFamilyId": source_family_id,
        "path": relative_or_absolute(path),
        "sha256": sha256_file(path),
        "perceptualHash64": perceptual_hash(path),
        "sourceType": source_type,
        "categories": categories,
        "width": metadata["width"],
        "height": metadata["height"],
        "alpha": {
            "hasAlphaChannel": metadata["hasAlphaChannel"],
            "alphaExtrema": metadata["alphaExtrema"],
            "hasNonOpaqueAlpha": metadata["hasNonOpaqueAlpha"],
        },
        "fileFormat": metadata["format"],
        "sourceProvenance": provenance,
        "licenseStatus": provenance.get("licenseStatus", "unknown"),
        "usagePermission": provenance.get("usagePermission", "unknown"),
        "referenceType": reference_type,
        "hasOriginalVectorGroundTruth": has_original_vector_ground_truth,
        "hasManualValidatedMasks": False,
        "hasAnalyticMask": has_analytic_mask,
        "hasAnalyticSemanticLabels": has_analytic_semantic_labels,
        "referenceFiles": reference_paths or {},
        "hasTypography": has_typography,
        "complexityNotes": complexity_notes,
        "datasetSplit": split,
        "annotationStatus": "analytic_sidecar" if has_analytic_mask else "none",
        "createdBy": "task_08a_dataset_builder",
    }


def build_initial_manifest(*, force: bool = False) -> dict[str, Any]:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if MANIFEST_PATH.exists() and not force:
        raise FileExistsError(f"Manifest already exists; preserve it and use the import workflow: {MANIFEST_PATH}")
    references, reference_errors = _export_synthetic_references()
    validation = json.loads((TASK072 / "synthetic_analytical_validation.json").read_text(encoding="utf-8"))
    fixture_root = BACKEND / "tests" / "fixtures"
    items: list[dict[str, Any]] = []
    real_provenance = {
        "sourceKind": "user_provided_project_fixture",
        "sourceDescription": "ACTIVE FOX raster supplied in the user’s project history and already present as a backend regression fixture.",
        "author": "unknown; user-provided fixture",
        "licenseStatus": "unknown_user_supplied",
        "usagePermission": "local benchmark for this project only; redistribution/publication not authorized by this manifest",
        "provenanceVerified": "The workspace contains the fixture and prior task records identify the upscaled file as user-provided; external creator/license is not recorded.",
    }
    native = fixture_root / "active_fox.jpg"
    upscaled = fixture_root / "active_fox_upscaled_8x.png"
    items.append(_make_item(
        "active-fox-native-jpeg", native, source_family_id="active-fox-family",
        source_type="real_raster_user_provided", categories=["gradient_logos", "multicolor_illustrations", "typography_mixed_artwork", "jpeg_noise_complex_raster"],
        split="development", provenance={**real_provenance, "variant": "native-size JPEG regression fixture"},
        reference_type="real_raster_with_unknown_vector_original", has_original_vector_ground_truth=False,
        has_typography=True, complexity_notes="554px logo with gradient icon and text; JPEG edges are present, but this is not a complex raster/photo sample.",
    ))
    items.append(_make_item(
        "active-fox-upscaled-8x", upscaled, source_family_id="active-fox-family",
        source_type="real_raster_user_provided", categories=["gradient_logos", "multicolor_illustrations", "typography_mixed_artwork"],
        split="development", provenance={**real_provenance, "variant": "8x upscaled project test input", "sourceSha256AtTask072": "734baedc9c20ee680585a28a81f4cc5959d2767e7875f672c8e7516e1429e2bd"},
        reference_type="real_raster_with_unknown_vector_original", has_original_vector_ground_truth=False,
        has_typography=True, complexity_notes="Same ACTIVE FOX source family as native JPEG; upscaling is not counted as an independent real image.",
    ))

    for name, fixture in sorted(validation["fixtures"].items()):
        source_path = resolve_path(Path(fixture["source"]).as_posix())
        if name not in references:
            continue
        meta = image_metadata(source_path)
        split = str(fixture["split"])
        reference_files = {
            key: value for key, value in references[name].items()
            if key.endswith("Path") or key.endswith("Sha256")
        }
        items.append(_make_item(
            f"synthetic-{name}", source_path, source_family_id=f"synthetic-family-{name}",
            source_type="synthetic_analytical_fixture", categories=_categories_for_synthetic(name, meta["hasNonOpaqueAlpha"]),
            split=split, provenance={
                "sourceKind": "generated_in_repository",
                "generatorPath": relative_or_absolute(TASK072 / "synthetic_analytical_validation.py"),
                "generatorFixtureName": name,
                "licenseStatus": "project_generated_internal",
                "usagePermission": "internal project benchmark",
                "provenanceVerified": "Generator parameters and source raster are in the workspace; source pixels were reproduced and compared before sidecar creation.",
            },
            reference_type="synthetic_raster_with_analytic_vector_ground_truth",
            has_original_vector_ground_truth=False, has_analytic_mask=True,
            has_analytic_semantic_labels=True, reference_paths=reference_files,
            complexity_notes=f"Analytical fixture: {name}. Synthetic evidence only; not counted as a real-world design.",
        ))

    manifest = {
        "schemaVersion": 1,
        "datasetId": "mediastudio-vectorization-task-08a",
        "createdAtUtc": utc_now(),
        "datasetPurpose": "Baseline multi-image measurement for Smart Reconstruction V2 and experimental Contour-Preserving; no algorithm tuning or release promotion.",
        "provenancePolicy": "User-provided images remain restricted to this local project benchmark unless a separate license is documented. Synthetic fixtures are labeled and counted separately.",
        "splitPolicy": "Split by sourceFamilyId. ACTIVE FOX native and upscaled variants stay together. Synthetic split reuses the predeclared Task 07.2 analytical split; running it here establishes a baseline and is not blind tuning evidence.",
        "referenceTypes": [
            "real_raster_with_unknown_vector_original",
            "synthetic_raster_with_analytic_vector_ground_truth",
        ],
        "categoryNames": list(CATEGORY_NAMES),
        "syntheticReferenceGenerationErrors": reference_errors,
        "items": items,
    }
    write_json(MANIFEST_PATH, manifest)
    lock_split(manifest)
    return manifest


def lock_split(manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    manifest = manifest or json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    items = manifest.get("items", [])
    family_rows: dict[str, dict[str, Any]] = {}
    for item in items:
        family = str(item.get("sourceFamilyId", ""))
        split = str(item.get("datasetSplit", ""))
        family_rows.setdefault(family, {"split": split, "imageIds": [], "sourceSha256s": []})
        family_rows[family]["imageIds"].append(item.get("imageId"))
        family_rows[family]["sourceSha256s"].append(item.get("sha256"))
        if family_rows[family]["split"] != split:
            family_rows[family]["splitConflict"] = True
    value = {
        "lockId": "task-08a-baseline-v1",
        "lockedAtUtc": utc_now(),
        "manifestSha256": canonical_sha256(manifest),
        "splitUnit": "sourceFamilyId",
        "families": family_rows,
        "heldoutUsage": "The declared held-out synthetic families are evaluated once here to establish the Task 08A baseline. They are not considered blind after this baseline run.",
    }
    write_json(SPLIT_PATH, value)
    return value


def add_image(
    path: Path,
    *,
    image_id: str,
    source_family_id: str,
    category: str,
    source_description: str,
    author: str,
    license_status: str,
    usage_permission: str,
    split: str = "development",
    source_type: str = "real_raster_user_provided",
) -> dict[str, Any]:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{1,79}", image_id):
        raise ValueError("image_id must be 2–80 safe ASCII characters")
    if category not in CATEGORY_NAMES:
        raise ValueError(f"category must be one of {CATEGORY_NAMES}")
    if split not in {"development", "heldout"}:
        raise ValueError("split must be development or heldout")
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if any(row["imageId"] == image_id for row in manifest["items"]):
        raise ValueError(f"imageId already exists: {image_id}")
    if any(row["sourceFamilyId"] == source_family_id and row["datasetSplit"] != split for row in manifest["items"]):
        raise ValueError("All variants in one source family must use the same split")
    item = _make_item(
        image_id, path, source_family_id=source_family_id, source_type=source_type,
        categories=[category], split=split,
        provenance={
            "sourceKind": "locally_imported",
            "sourceDescription": source_description,
            "author": author,
            "licenseStatus": license_status,
            "usagePermission": usage_permission,
            "provenanceVerified": "User-entered import metadata; verify rights before redistribution.",
        },
        reference_type="real_raster_with_unknown_vector_original",
        has_original_vector_ground_truth=False,
        complexity_notes="Imported by local benchmark workflow; no file copied into the repository.",
    )
    manifest["items"].append(item)
    write_json(MANIFEST_PATH, manifest)
    # Import intentionally invalidates the prior lock. The operator must explicitly relock after reviewing family split assignment.
    if SPLIT_PATH.exists():
        old_lock = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
        old_lock["manifestSha256"] = "INVALIDATED_BY_DATASET_IMPORT"
        old_lock["invalidatedAtUtc"] = utc_now()
        old_lock["newImageId"] = image_id
        write_json(SPLIT_PATH, old_lock)
    return item


def validate_dataset(*, require_locked: bool = True) -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    split_lock = json.loads(SPLIT_PATH.read_text(encoding="utf-8")) if SPLIT_PATH.exists() else None
    items = manifest.get("items", [])
    missing: list[str] = []
    hash_mismatches: list[str] = []
    unreadable: list[str] = []
    incomplete_provenance: list[str] = []
    family_split_conflicts: list[str] = []
    exact_duplicates: list[dict[str, str]] = []
    near_duplicate_pairs: list[dict[str, Any]] = []
    observed_hashes: dict[str, str] = {}
    observed_phashes: list[tuple[dict[str, Any], str]] = []
    family_splits: dict[str, set[str]] = {}

    required_provenance = ("sourceKind", "licenseStatus", "usagePermission", "provenanceVerified")
    for item in items:
        image_id = str(item.get("imageId", "<missing-id>"))
        path = resolve_path(str(item.get("path", "")))
        family_splits.setdefault(str(item.get("sourceFamilyId", "")), set()).add(str(item.get("datasetSplit", "")))
        if not path.is_file():
            missing.append(image_id)
            continue
        actual_hash = sha256_file(path)
        if actual_hash != item.get("sha256"):
            hash_mismatches.append(image_id)
        if actual_hash in observed_hashes:
            exact_duplicates.append({"imageIdA": observed_hashes[actual_hash], "imageIdB": image_id, "sameSourceFamily": item.get("sourceFamilyId") == next((x.get("sourceFamilyId") for x in items if x.get("imageId") == observed_hashes[actual_hash]), None)})
        else:
            observed_hashes[actual_hash] = image_id
        try:
            current_metadata = image_metadata(path)
        except Exception as error:
            unreadable.append(f"{image_id}:{type(error).__name__}:{error}")
            continue
        if (current_metadata["width"], current_metadata["height"]) != (item.get("width"), item.get("height")):
            unreadable.append(f"{image_id}:dimensions_changed")
        provenance = item.get("sourceProvenance", {})
        if not all(provenance.get(key) for key in required_provenance):
            incomplete_provenance.append(image_id)
        if item.get("hasAnalyticSemanticLabels"):
            labels = resolve_path(str(item.get("referenceFiles", {}).get("semanticLabelMapPath", "")))
            if not labels.is_file() or sha256_file(labels) != item.get("referenceFiles", {}).get("semanticLabelMapSha256"):
                hash_mismatches.append(f"{image_id}:semantic_labels")
        if item.get("hasAnalyticMask"):
            alpha = resolve_path(str(item.get("referenceFiles", {}).get("analyticAlphaMaskPath", "")))
            if not alpha.is_file() or sha256_file(alpha) != item.get("referenceFiles", {}).get("analyticAlphaMaskSha256"):
                hash_mismatches.append(f"{image_id}:analytic_alpha")
        observed_phashes.append((item, perceptual_hash(path)))

    for family, splits in family_splits.items():
        if len(splits) != 1 or "" in splits:
            family_split_conflicts.append(family)
    for index, (item_a, hash_a) in enumerate(observed_phashes):
        for item_b, hash_b in observed_phashes[index + 1:]:
            distance = hamming_distance(hash_a, hash_b)
            if distance <= 6:
                near_duplicate_pairs.append({
                    "imageIdA": item_a["imageId"], "imageIdB": item_b["imageId"],
                    "sourceFamilyA": item_a["sourceFamilyId"], "sourceFamilyB": item_b["sourceFamilyId"],
                    "sameSourceFamily": item_a["sourceFamilyId"] == item_b["sourceFamilyId"],
                    "splitA": item_a["datasetSplit"], "splitB": item_b["datasetSplit"],
                    "pHashHammingDistance": distance,
                    "splitLeakageCandidate": item_a["datasetSplit"] != item_b["datasetSplit"],
                    "reviewStatus": "same_family_expected" if item_a["sourceFamilyId"] == item_b["sourceFamilyId"] else "manual_review_required",
                })
    lock_matches = bool(split_lock and split_lock.get("manifestSha256") == canonical_sha256(manifest))
    split_leakage = [pair for pair in near_duplicate_pairs if pair["splitLeakageCandidate"]]
    required_missing = bool(missing or hash_mismatches or unreadable or incomplete_provenance or family_split_conflicts)
    valid = not required_missing and not split_leakage and (lock_matches or not require_locked)
    real_families = {row["sourceFamilyId"] for row in items if row.get("sourceType", "").startswith("real_")}
    synthetic_items = [row for row in items if row.get("sourceType", "").startswith("synthetic_")]
    category_rows: dict[str, dict[str, Any]] = {}
    for category in CATEGORY_NAMES:
        selected = [row for row in items if category in row.get("categories", [])]
        category_rows[category] = {
            "imageVariantCount": len(selected),
            "independentRealSourceFamilyCount": len({row["sourceFamilyId"] for row in selected if row.get("sourceType", "").startswith("real_")}),
            "syntheticFixtureCount": sum(row.get("sourceType", "").startswith("synthetic_") for row in selected),
            "targetIndependentRealFamilies": 4,
            "coverageSufficient": len({row["sourceFamilyId"] for row in selected if row.get("sourceType", "").startswith("real_")}) >= 4,
        }
    return {
        "status": "PASS" if valid else "FAIL",
        "datasetManifestPath": relative_or_absolute(MANIFEST_PATH),
        "datasetManifestSha256": canonical_sha256(manifest),
        "splitLockMatchesManifest": lock_matches,
        "splitLocked": bool(split_lock),
        "imageVariantCount": len(items),
        "independentRealImageCount": len(real_families),
        "syntheticFixtureCount": len(synthetic_items),
        "sourceFamilyCount": len({row.get("sourceFamilyId") for row in items}),
        "missingImageIds": missing,
        "hashMismatches": hash_mismatches,
        "unreadableImages": unreadable,
        "incompleteProvenance": incomplete_provenance,
        "sourceFamilySplitConflicts": family_split_conflicts,
        "exactDuplicatePairs": exact_duplicates,
        "nearDuplicateReviewPairs": near_duplicate_pairs,
        "nearDuplicateSplitLeakageCandidates": split_leakage,
        "licenseCaveat": "The user-provided ACTIVE FOX family has unknown external author/license and is restricted to this local project benchmark; no public redistribution is authorized. This caveat is recorded, not treated as a verified open license.",
        "provenanceValid": not incomplete_provenance and not missing and not hash_mismatches,
        "splitValid": not family_split_conflicts and not split_leakage and lock_matches,
        "categoryCoverage": category_rows,
        "independentRealImageTarget": "24-32 images total, at least 4 real source families in each required category group",
    }


def dataset_coverage(validation: dict[str, Any]) -> dict[str, Any]:
    categories = validation["categoryCoverage"]
    coverage_sufficient = validation["independentRealImageCount"] >= 24 and all(row["coverageSufficient"] for row in categories.values())
    return {
        "independentRealImageCount": validation["independentRealImageCount"],
        "syntheticFixtureCount": validation["syntheticFixtureCount"],
        "imageVariantCount": validation["imageVariantCount"],
        "sourceFamilyCount": validation["sourceFamilyCount"],
        "categoryCoverage": categories,
        "DATASET_COVERAGE_SUFFICIENT": coverage_sufficient,
        "missingRealWorldGroups": [name for name, row in categories.items() if not row["coverageSufficient"]],
        "assessment": "Coverage is intentionally insufficient. ACTIVE FOX native and 8x variants are one real source family. Synthetic analytical fixtures are tracked separately and cannot satisfy real-image targets.",
    }


def dataset_inventory(validation: dict[str, Any]) -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    by_type: dict[str, int] = {}
    by_split: dict[str, int] = {}
    by_format: dict[str, int] = {}
    rows = []
    for item in manifest["items"]:
        by_type[item["sourceType"]] = by_type.get(item["sourceType"], 0) + 1
        by_split[item["datasetSplit"]] = by_split.get(item["datasetSplit"], 0) + 1
        by_format[item["fileFormat"]] = by_format.get(item["fileFormat"], 0) + 1
        rows.append({key: item[key] for key in ("imageId", "sourceFamilyId", "path", "sha256", "sourceType", "categories", "width", "height", "fileFormat", "datasetSplit", "referenceType", "hasTypography", "hasAnalyticMask", "hasAnalyticSemanticLabels")})
    return {
        "manifestSha256": validation["datasetManifestSha256"],
        "imageVariantCount": len(rows),
        "independentRealImageCount": validation["independentRealImageCount"],
        "syntheticFixtureCount": validation["syntheticFixtureCount"],
        "countsBySourceType": by_type,
        "countsBySplit": by_split,
        "countsByFormat": by_format,
        "items": rows,
    }
