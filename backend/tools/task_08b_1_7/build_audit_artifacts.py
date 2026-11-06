"""Assemble the read-only Task 08B.1.7 audit artifacts from repository evidence."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BACKEND = Path(__file__).resolve().parents[2]
ROOT = BACKEND.parent
ART = BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_7"
SVG_NS = "http://www.w3.org/2000/svg"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(name: str, value: Any) -> None:
    (ART / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(name: str, value: str) -> None:
    (ART / name).write_text(value.rstrip() + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def source_hash_manifest() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    scopes = [
        ("backend/mediastudio", ROOT / "backend" / "mediastudio"),
        ("wpf/src/MediaStudio.Desktop", ROOT / "src" / "MediaStudio.Desktop"),
    ]
    extensions = {".py", ".cs", ".xaml", ".csproj", ".props", ".targets", ".json", ".config"}
    for label, directory in scopes:
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in extensions:
                continue
            rows.append({
                "scope": label,
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            })
    return {
        "task": "08B.1.7",
        "snapshot": "after_validation",
        "scope": ["backend/mediastudio source files", "src/MediaStudio.Desktop source/config files"],
        "fileCount": len(rows),
        "files": rows,
    }


def svg_scan() -> dict[str, Any]:
    manifest_root = BACKEND / "artifacts" / "contour_preserving"
    records: list[dict[str, Any]] = []
    unique_paths: dict[str, dict[str, Any]] = {}
    for task in ("task_08a", "task_08a_1"):
        result = read_json(manifest_root / task / "per_image_results.json")
        for item in result.get("items", []):
            for engine, engine_result in item.get("engines", {}).items():
                if engine_result.get("status") != "SUCCEEDED":
                    continue
                validation = engine_result.get("svgValidation", {})
                raw_path = validation.get("path") or engine_result.get("svgPath")
                path = Path(raw_path) if raw_path else None
                record: dict[str, Any] = {
                    "sourceTask": task,
                    "imageId": item.get("imageId"),
                    "sourceFamilyId": item.get("sourceFamilyId"),
                    "engine": engine,
                    "status": "NOT_TESTED",
                    "path": str(path) if path else None,
                }
                if path is None or not path.is_file():
                    record["status"] = "FILE_MISSING"
                    records.append(record)
                    continue
                resolved = str(path.resolve()).casefold()
                if resolved in unique_paths:
                    record["status"] = "REUSED_IDENTICAL_ARTIFACT"
                    record["sha256"] = unique_paths[resolved]["sha256"]
                    records.append(record)
                    continue
                payload = path.read_bytes()
                try:
                    root = ET.fromstring(payload)
                    xml_valid = True
                except ET.ParseError:
                    root = None
                    xml_valid = False
                ns = {"s": SVG_NS}
                images = root.findall(".//s:image", ns) if root is not None else []
                paths = root.findall(".//s:path", ns) if root is not None else []
                gradients = (root.findall(".//s:linearGradient", ns) + root.findall(".//s:radialGradient", ns)) if root is not None else []
                id_values = [element.get("id") for element in root.iter() if element.get("id")] if root is not None else []
                all_ids = set(id_values)
                refs = set(re.findall(r"url\(#([^)]+)\)", payload.decode("utf-8", "replace")))
                href_values = [
                    value for element in (root.iter() if root is not None else [])
                    for key, value in element.attrib.items()
                    if key.endswith("href")
                ]
                refs.update(value[1:] for value in href_values if value.startswith("#"))
                external = [value for value in href_values if not value.startswith("#")]
                external += re.findall(r"url\((?!#)([^)]+)\)", payload.decode("utf-8", "replace"))
                unresolved = sorted(refs - all_ids)
                unique_ids = len(id_values) == len(all_ids)
                valid = bool(
                    xml_valid and root is not None and root.tag == f"{{{SVG_NS}}}svg"
                    and root.get("width") and root.get("height") and root.get("viewBox")
                    and not images and b"data:image/" not in payload.lower()
                    and not external and not unresolved and unique_ids
                )
                row = {
                    "sourceTask": task,
                    "imageId": item.get("imageId"),
                    "sourceFamilyId": item.get("sourceFamilyId"),
                    "engine": engine,
                    "status": "PASS" if valid else "ISSUE",
                    "path": str(path),
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "xmlValid": xml_valid,
                    "rootTag": root.tag if root is not None else None,
                    "width": root.get("width") if root is not None else None,
                    "height": root.get("height") if root is not None else None,
                    "viewBox": root.get("viewBox") if root is not None else None,
                    "pathCount": len(paths),
                    "gradientCount": len(gradients),
                    "embeddedRasterElementCount": len(images),
                    "embeddedRasterDataUriCount": payload.lower().count(b"data:image/"),
                    "externalResourceReferences": external,
                    "unresolvedLocalReferences": unresolved,
                    "uniqueIds": unique_ids,
                    "recordedWorkerSvgValidationStatus": validation.get("status"),
                    "recordedBrowserRenderPath": engine_result.get("edgeRenderPath"),
                    "recordedBrowserRenderHash": engine_result.get("edgeRenderSha256"),
                    "recordedRendererCheck": engine_result.get("skiaRendererCheck"),
                }
                unique_paths[resolved] = row
                record.update({key: row[key] for key in ("status", "bytes", "sha256", "pathCount", "gradientCount")})
                records.append(record)
    unique_rows = list(unique_paths.values())
    return {
        "schemaVersion": 1,
        "method": "parse actual SVGs referenced by Task 08A and 08A.1 results; check dimensions, viewBox, unique IDs, local references, raster embedding and external resources",
        "benchmarkResultReferences": len(records),
        "uniqueSavedSvgFiles": len(unique_rows),
        "missingSavedFiles": sum(row["status"] == "FILE_MISSING" for row in records),
        "uniqueSvgStatusCounts": dict(Counter(row["status"] for row in unique_rows)),
        "allUniqueSvgStructurallyValidVectorOnly": all(row["status"] == "PASS" for row in unique_rows),
        "embeddedRasterElementCount": sum(row["embeddedRasterElementCount"] for row in unique_rows),
        "embeddedRasterDataUriCount": sum(row["embeddedRasterDataUriCount"] for row in unique_rows),
        "externalResourceReferenceCount": sum(len(row["externalResourceReferences"]) for row in unique_rows),
        "unresolvedLocalReferenceCount": sum(len(row["unresolvedLocalReferences"]) for row in unique_rows),
        "vectorEditabilityCaveat": "Path-based SVG is technically vector; this audit does not establish semantic editability, clean object grouping, or editable text semantics.",
        "renderEvidenceCaveat": "Worker browser validation and saved renderer records are separate from manual WPF-window QA.",
        "records": records,
        "uniqueFileDetails": unique_rows,
    }


def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    manifest = read_json(BACKEND / "artifacts" / "contour_preserving" / "task_08a_1" / "real_dataset_manifest.json")
    dataset_items = manifest["items"]
    task08a_inventory = read_json(BACKEND / "artifacts" / "contour_preserving" / "task_08a" / "dataset_inventory.json")
    task08a1_coverage = read_json(BACKEND / "artifacts" / "contour_preserving" / "task_08a_1" / "dataset_coverage.json")
    task08a1_results = read_json(BACKEND / "artifacts" / "contour_preserving" / "task_08a_1" / "per_image_results.json")
    full_regression_xml = ET.parse(ART / "full_regression.xml").getroot()
    smoke = read_json(ART / "beta_smoke_test_results.json")
    task16b = read_json(BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_6b" / "acceptance_status.json")
    task16b_status = task16b["statuses"]

    human_review_csv = BACKEND / "artifacts" / "contour_preserving" / "task_08a" / "human_review_results.csv"
    with human_review_csv.open("r", encoding="utf-8-sig", newline="") as stream:
        human_rows = list(csv.DictReader(stream))
    real_items = [row for row in dataset_items if not str(row.get("sourceType", "")).startswith("synthetic_")]
    synthetic_items = [row for row in dataset_items if str(row.get("sourceType", "")).startswith("synthetic_")]
    real_families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    synthetic_families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in real_items:
        real_families[str(item["sourceFamilyId"])].append(item)
    for item in synthetic_items:
        synthetic_families[str(item["sourceFamilyId"])].append(item)

    family_audit = []
    for family_id, variants in sorted(real_families.items()):
        family_audit.append({
            "sourceFamilyId": family_id,
            "sourceType": variants[0].get("sourceType"),
            "variantCount": len(variants),
            "imageIds": [row.get("imageId") for row in variants],
            "categories": sorted({category for row in variants for category in row.get("categories", [])}),
            "paths": [row.get("path") for row in variants],
            "sha256s": [row.get("sha256") for row in variants],
            "referenceTypes": sorted({row.get("referenceType") for row in variants}),
            "sourceVectorReferenceAvailable": any(bool(row.get("hasOriginalVectorGroundTruth")) for row in variants),
            "analyticGroundTruthAvailable": any(bool(row.get("hasAnalyticMask") or row.get("hasAnalyticSemanticLabels")) for row in variants),
            "humanReviewStatus": "not_completed",
            "provenanceOrGroupingNote": next((row.get("complexityNotes") for row in variants if row.get("complexityNotes")), None),
        })

    category_raw: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "realSourceFamilies": set(), "realVariants": 0,
        "syntheticSourceFamilies": set(), "syntheticVariants": 0,
        "realImageIds": [], "syntheticImageIds": [],
    })
    for item in dataset_items:
        synthetic = str(item.get("sourceType", "")).startswith("synthetic_")
        for category in item.get("categories", []):
            row = category_raw[category]
            if synthetic:
                row["syntheticSourceFamilies"].add(item["sourceFamilyId"])
                row["syntheticVariants"] += 1
                row["syntheticImageIds"].append(item["imageId"])
            else:
                row["realSourceFamilies"].add(item["sourceFamilyId"])
                row["realVariants"] += 1
                row["realImageIds"].append(item["imageId"])
    category_counts = {
        key: {
            "realSourceFamilyCount": len(row["realSourceFamilies"]),
            "realVariantCount": row["realVariants"],
            "syntheticFixtureFamilyCount": len(row["syntheticSourceFamilies"]),
            "syntheticFixtureVariantCount": row["syntheticVariants"],
            "realSourceFamilyIds": sorted(row["realSourceFamilies"]),
            "syntheticFixtureIds": row["syntheticImageIds"],
        }
        for key, row in category_raw.items()
    }

    per_image_rows = task08a1_results.get("items", [])
    real_outcomes: dict[str, Any] = {}
    for engine in ("smart_reconstruction", "contour_preserving"):
        outcomes = []
        for item in per_image_rows:
            result = item.get("engines", {}).get(engine, {})
            outcomes.append({
                "imageId": item.get("imageId"),
                "sourceFamilyId": item.get("sourceFamilyId"),
                "sourceType": item.get("sourceType"),
                "categories": item.get("categories", []),
                "status": result.get("status"),
                "failureCode": result.get("failureCode"),
                "failureReason": result.get("failureReason"),
                "wallSeconds": result.get("wallSeconds"),
                "peakCombinedWorkingSetBytes": result.get("memory", {}).get("peakCombinedWorkingSetBytes"),
                "svgValidationStatus": result.get("svgValidation", {}).get("status"),
            })
        success = sum(row["status"] == "SUCCEEDED" for row in outcomes)
        real_outcomes[engine] = {
            "variantCount": len(outcomes),
            "succeededVariants": success,
            "failedVariants": len(outcomes) - success,
            "outcomes": outcomes,
        }

    category_definitions: list[dict[str, Any]] = [
        {
            "categoryId": "flat_logos_icons", "label": "Flat logos and icons", "formalCategory": "flat_logos_icons",
            "status": "NOT_VALIDATED", "scopeMatchedRealFamilies": 0, "relatedRealFamilies": 1,
            "reason": "Eight synthetic shape/color fixtures exist, but the only real related sample is the alpha horse icon and both engine jobs failed. No approved source vector or completed human review exists.",
            "knownSamples": ["horse: Smart and Contour jobs failed in Task 08A.1; failure was surfaced as job failure, not accepted SVG success."],
        },
        {
            "categoryId": "simple_gradient_logos", "label": "Simple gradient logos", "formalCategory": "gradient_logos",
            "status": "NOT_VALIDATED", "scopeMatchedRealFamilies": 0, "relatedRealFamilies": 1,
            "reason": "Synthetic linear/radial gradient fixtures pass specific analytic checks, including Smart V2 radial repair, but there is no real simple-gradient-logo family: ACTIVE FOX is complex multicolor artwork. Synthetic-only results and no human review do not validate this category.",
            "knownSamples": ["Task 08B.1.2 radial synthetic fixture: same ROI mean ΔE00 1.7865→0.5905 and P95 5.6706→1.1655; held-out synthetic radial variants pass. This does not prove real-logo generalization."],
        },
        {
            "categoryId": "complex_multicolor_logos", "label": "Complex multicolor logos", "formalCategory": "multicolor_illustrations",
            "status": "LIMITED_SUPPORT", "scopeMatchedRealFamilies": 1, "relatedRealFamilies": 1,
            "reason": "ACTIVE FOX is one real source family with native and 8× variants, not two independent logos. Both production engines create vector-only SVGs, but visual approval and broad logo coverage are absent; the latest nonlinear-gradient gate fails.",
            "knownSamples": ["ACTIVE FOX is the only real multicolor logo family; there is no source-vector ground truth or completed blind human score."],
        },
        {
            "categoryId": "vector_style_illustrations", "label": "Vector-style illustrations", "formalCategory": "multicolor_illustrations",
            "status": "NOT_VALIDATED", "scopeMatchedRealFamilies": 0, "relatedRealFamilies": 1,
            "reason": "Seven synthetic illustration fixtures are available. The only real source assigned to the multicolor illustration label is a logo, not an independent illustration family; no real illustration ground truth or human approval is present.",
            "knownSamples": [],
        },
        {
            "categoryId": "thin_line_art", "label": "Thin line art and strokes", "formalCategory": "line_art_thin_details",
            "status": "NOT_VALIDATED", "scopeMatchedRealFamilies": 0, "relatedRealFamilies": 0,
            "reason": "Four synthetic line/stroke fixtures test geometry contracts, but there are no independent real line-art source families. The Task 08B.1.6B candidate also fails thin-highlight non-regression.",
            "knownSamples": ["Task 08B.1.6B reports THIN_HIGHLIGHT_PRESERVED=false for the rejected research candidate; this does not establish the same failure for every production input."],
        },
        {
            "categoryId": "typography_mixed_artwork", "label": "Typography and mixed text/artwork", "formalCategory": "typography_mixed_artwork",
            "status": "LIMITED_SUPPORT", "scopeMatchedRealFamilies": 1, "relatedRealFamilies": 2,
            "reason": "ACTIVE FOX and one raster-text sample make two real families, but exact source vector/transcription/glyph truth and human review are missing; the standalone text sample failed in both engines. Outlined glyph paths are node-editable shapes, not semantic editable text.",
            "knownSamples": ["Task 08A.1 standalone text sample failed for Smart and Contour. ACTIVE FOX text appears in SVG output, but glyph fidelity has no authoritative vector/text reference."],
        },
        {
            "categoryId": "transparent_png_artwork", "label": "Transparent PNG artwork", "formalCategory": "transparency",
            "status": "NOT_VALIDATED", "scopeMatchedRealFamilies": 0, "relatedRealFamilies": 1,
            "reason": "Eighteen synthetic alpha fixtures are present; the only real alpha-channel example is the horse sample (alpha 110–255, no fully transparent pixels recorded), and both engines failed on it. Synthetic alpha success cannot establish real transparent-artwork coverage.",
            "knownSamples": ["Task 08A.1 horse alpha sample: both engines failed; 18 formal synthetic alpha fixtures have analytic references."],
        },
        {
            "categoryId": "photographs_textured", "label": "Photographs and textured images", "formalCategory": "jpeg_noise_complex_raster",
            "status": "KNOWN_UNSUPPORTED_OR_FAILED", "scopeMatchedRealFamilies": 0, "relatedRealFamilies": 7,
            "reason": "Seven independent public photograph families were actually processed. Smart succeeded on 2/7; Contour on 3/7. Multiple failures were visible-SVG rejection or GEOS topology errors. This is affirmative failed-benchmark evidence for these photo samples, not a claim that every photo is impossible.",
            "knownSamples": ["Task 08A.1 photo benchmark: Smart 2/7 succeeded; Contour 3/7; five/four failed jobs respectively."],
        },
        {
            "categoryId": "complex_nonlinear_gradients", "label": "Complex nonlinear gradient artwork", "formalCategory": "gradient_logos",
            "status": "KNOWN_UNSUPPORTED_OR_FAILED", "scopeMatchedRealFamilies": 1, "relatedRealFamilies": 1,
            "reason": "The smooth nonlinear-gradient production benchmark is a verified failure for both existing engines. Task 08B.1.6B fixes coordinate mismatch in research but its frozen candidate misses false-edge, mean/P95 color and held-out gates, so it was not integrated.",
            "knownSamples": ["Task 08B.1.6B current production: false-edge 1.5741%, mean ΔE00 4.3173, P95 8.9644; candidate false-edge 1.5081%, mean 4.5603, P95 10.4506; all primary candidate gates fail."],
        },
    ]

    for category in category_definitions:
        formal = category_counts.get(category["formalCategory"], {})
        category["datasetCoverage"] = {
            "rawManifestRealFamilyCount": formal.get("realSourceFamilyCount", 0),
            "scopeMatchedRealFamilyCount": category["scopeMatchedRealFamilies"],
            "relatedRealFamilyCount": category["relatedRealFamilies"],
            "realVariantCount": formal.get("realVariantCount", 0),
            "formalSyntheticFixtureFamilyCount": formal.get("syntheticFixtureFamilyCount", 0),
            "formalSyntheticVariantCount": formal.get("syntheticFixtureVariantCount", 0),
        }
        category["evidenceLevels"] = {
            "jobSucceeded": "mixed; see per-engine outcomes and sample scope",
            "svgStructurallyValid": "PASS for audited successful SVG artifacts; see svg_quality_audit.json",
            "svgVisible": "worker browser render validation exists for recorded successful outputs; not WPF-window evidence",
            "geometryAccurate": "limited to named analytic fixtures/annotated ROIs; no broad real vector ground truth",
            "colorAccurate": "limited to analytic synthetic tests and one real family; complex gradient gates fail",
            "detailsPreserved": "specific synthetic detail tests only; no broad real-image approval",
            "humanApprovedFidelity": False,
        }
        category["evidenceFiles"] = [
            "artifacts/contour_preserving/task_08a_1/real_dataset_manifest.json",
            "artifacts/contour_preserving/task_08a_1/per_image_results.json",
            "artifacts/contour_preserving/task_08a_1/per_image_review_summary.json",
            "artifacts/contour_preserving/task_08b_1_6b/acceptance_status.json",
        ]

    full_regression = {
        "command": ".venv\\Scripts\\python.exe -m pytest tests -q --junitxml=artifacts/contour_preserving/task_08b_1_7/full_regression.xml",
        "status": "PASS",
        "pytestPassedTests": 378,
        "pytestPassedSubtests": 360,
        "pytestFailedTests": 0,
        "pytestErrors": 0,
        "pytestSkipped": 0,
        "warnings": 24,
        "durationSeconds": 210.55,
        "junitTestCaseElements": sum(1 for node in full_regression_xml.iter() if node.tag == "testcase"),
        "junitFailures": sum(1 for node in full_regression_xml.iter() if node.tag in {"failure", "error"}),
        "junitReport": "artifacts/contour_preserving/task_08b_1_7/full_regression.xml",
        "summary": "378 passed, 24 warnings, 360 subtests passed in 210.55s",
        "notes": [
            "This confirms automated backend regression, not WPF manual end-to-end QA or image-class fidelity.",
            "The 24 warnings are deprecations from Starlette/FastAPI lifecycle APIs and a SciPy import path; see test log/output context.",
        ],
    }
    write_json("full_regression.json", full_regression)

    smoke = read_json(ART / "beta_smoke_test_results.json")
    svg_audit = svg_scan()
    write_json("svg_quality_audit.json", svg_audit)

    source_families_json = {
        "schemaVersion": 1,
        "formalDataset": "Task 08A.1 real_dataset_manifest.json, SHA-256 41b656051391f31f134136214ddb9c6301c5cac401e965a3367de434fd54af6c",
        "variantCount": len(dataset_items),
        "realVariantCount": len(real_items),
        "independentRealSourceFamilyCount": len(real_families),
        "syntheticFixtureVariantCount": len(synthetic_items),
        "syntheticFixtureFamilyCount": len(synthetic_families),
        "humanReviewCompleted": bool(human_rows),
        "humanReviewScoreRows": len(human_rows),
        "humanReviewCsvHeaderOnly": len(human_rows) == 0,
        "familySplitUnit": "sourceFamilyId",
        "familySplitConflicts": task08a1_coverage.get("sourceFamilySplitConflicts", []),
        "nearDuplicateSyntheticReviewFlags": task08a1_coverage.get("nearDuplicateReviewPairs", []),
        "realFamilies": family_audit,
        "syntheticDatasetSummary": {
            "sourceFamilyCount": len(synthetic_families),
            "fixtureVariantCount": len(synthetic_items),
            "hasAnalyticReferences": all(row.get("referenceType") == "synthetic_raster_with_analytic_vector_ground_truth" for row in synthetic_items),
            "countsAsRealWorldCoverage": False,
        },
        "notes": [
            "The two ACTIVE FOX resolutions are one family, not two independent examples.",
            "The 08A.1 added set has nine independent public/user-provided families; most public samples are photographs.",
            "ACTIVE FOX provenance/license is user-provided with unknown external license; local benchmark only, no redistribution authorization recorded.",
        ],
    }
    write_json("source_family_audit.json", source_families_json)

    formal_coverage = {
        "schemaVersion": 1,
        "datasetManifestSha256": task08a1_coverage.get("manifestSha256"),
        "variantCount": len(dataset_items),
        "independentRealSourceFamilies": len(real_families),
        "realRasterVariants": len(real_items),
        "syntheticFixtureVariants": len(synthetic_items),
        "categories": category_counts,
        "supplementalTask08BAnalyticCases": {
            "count": 6,
            "fixtureIds": ["hard_boundary_with_gradient", "low_contrast_multistop_gradient", "smooth_nonlinear_gradient", "small_sharp_color_detail", "smooth_alternate_heldout", "thin_highlight"],
            "classification": "synthetic controlled/analytic cases, some reused across 08B.1.3–08B.1.6B; not added independent real families and not all are images in the frozen 08A dataset",
        },
        "humanReview": {"complete": False, "scoreRows": len(human_rows), "reviewManifestImageCount": 29, "reviewManifestRoiCount": 160},
        "assessment": "Real coverage is insufficient for broad Beta support. A formal 4-independent-real-family-per-category milestone is unmet by every target design category; photos are the one adequate count but are mostly failed and outside the target design-artwork scope.",
    }
    write_json("dataset_coverage_matrix.json", formal_coverage)

    missing = []
    for category in category_definitions:
        count = category["scopeMatchedRealFamilies"]
        missing.append({
            "categoryId": category["categoryId"],
            "requiredIndependentRealFamiliesForEvidenceMilestone": 4,
            "scopeMatchedIndependentRealFamilies": count,
            "familyGap": max(0, 4 - count),
            "missingEvidence": [
                "independent real source families with hashes and documented usage permission",
                "source vector or reliable pixel/semantic annotations appropriate to the metric",
                "completed blind human visual review on source-scale comparisons",
            ],
            "categorySpecific": category["reason"],
        })
    write_json("missing_beta_evidence.json", {
        "schemaVersion": 1,
        "coverageMilestoneSource": "Task 08A/08A.1 dataset targets four independent real source families per category; synthetic fixtures do not satisfy it.",
        "humanReviewComplete": False,
        "sourceVectorReferenceFamilies": 0,
        "items": missing,
    })
    write_json("supported_image_matrix.json", {
        "schemaVersion": 1,
        "policy": "A successful job or structurally valid SVG is not sufficient for SUPPORTED_WITH_EVIDENCE; claims also require representative quality evidence and human review.",
        "supportedWithEvidenceCategoryCount": sum(row["status"] == "SUPPORTED_WITH_EVIDENCE" for row in category_definitions),
        "categories": category_definitions,
        "supportedBetaScopeToday": [],
        "proposedScopeStatement": "Do not claim general-purpose raster-to-vector support. Keep Smart V2 as the default workflow but describe outputs as best-effort until at least one real artwork category passes the evidence gates. Keep Contour labelled experimental. Exclude photographs and complex nonlinear-gradient fidelity claims from a first Beta.",
    })

    # Build scoped real-image outcome summaries and use explicit task evidence for quality metrics.
    photo_rows = [row for row in per_image_rows if str(row.get("sourceFamilyId", "")).startswith("photo-")]
    photo_summary = {}
    for engine in ("smart_reconstruction", "contour_preserving"):
        passed = sum(row.get("engines", {}).get(engine, {}).get("status") == "SUCCEEDED" for row in photo_rows)
        photo_summary[engine] = {"photoImageCount": len(photo_rows), "succeeded": passed, "failed": len(photo_rows) - passed}
    task08a_categories = read_json(BACKEND / "artifacts" / "contour_preserving" / "task_08a" / "per_category_summary.json")
    flat_summary = task08a_categories.get("categories", {}).get("flat_logos_icons", {}).get("engineSummaries", {})
    radial = read_json(BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_2" / "radial_gradient_before_after.json")
    primary = task16b["evidence"]["primaryMetrics"]
    task071_roi = read_json(BACKEND / "artifacts" / "contour_preserving" / "task_07_1" / "roi_visual_metrics.json")
    icon_roi = task071_roi.get("rois", {}).get("foxIcon", {})
    text_roi = task071_roi.get("rois", {}).get("tagline", {})
    smart_perf, contour_perf = {}, {}
    for engine, destination in (("smart_reconstruction", smart_perf), ("contour_preserving", contour_perf)):
        successful = [row.get("engines", {}).get(engine, {}) for row in per_image_rows]
        successful = [row for row in successful if row.get("status") == "SUCCEEDED"]
        times = [row["wallSeconds"] for row in successful if isinstance(row.get("wallSeconds"), (int, float))]
        memories = [row["memory"]["peakCombinedWorkingSetBytes"] for row in successful if row.get("memory", {}).get("peakCombinedWorkingSetBytes")]
        all_times = [row.get("engines", {}).get(engine, {}).get("wallSeconds") for row in per_image_rows]
        all_times = [value for value in all_times if isinstance(value, (int, float))]
        destination.update({
            "successfulJobCount": len(successful),
            "medianSuccessfulWallSeconds": round(sorted(times)[len(times)//2], 3) if times else None,
            "maxObservedWallSecondsAllAttempts": round(max(all_times), 3) if all_times else None,
            "medianSuccessfulPeakSampledWorkingSetBytes": sorted(memories)[len(memories)//2] if memories else None,
            "maxSuccessfulPeakSampledWorkingSetBytes": max(memories) if memories else None,
            "samplingCaveat": "Task 08A.1 samples combined root/live descendants every 0.2 s; short-lived peaks can be missed.",
        })

    engine_capability = {
        "schemaVersion": 1,
        "evidenceRule": "Metric claims are scoped to the named real fixture or synthetic analytic fixture; no row is a universal engine guarantee.",
        "productionDefault": "smart_reconstruction / Vectorization V2",
        "experimentalEngine": "contour_preserving; opt-in flag defaults off and pinned scikit-image 0.26.0 is required",
        "realApiBenchmark08A1": {
            "variantCount": len(per_image_rows),
            "sameAssetUsedByBothEngines": all(row.get("sameAssetIdUsedByBothEngines") is True for row in per_image_rows),
            "bothEnginesSucceededVariantCount": sum(all(row.get("engines", {}).get(engine, {}).get("status") == "SUCCEEDED" for engine in ("smart_reconstruction", "contour_preserving")) for row in per_image_rows),
            "smart": real_outcomes["smart_reconstruction"],
            "contour": real_outcomes["contour_preserving"],
            "photoSummary": photo_summary,
        },
        "syntheticFlatGeometryMedians": {
            engine: {
                "syntheticFixtureCount": flat_summary.get(engine, {}).get("successfulImageCount"),
                "medianGeometryIoU": flat_summary.get(engine, {}).get("median_geometryIoU"),
                "medianBoundaryP95Px": flat_summary.get(engine, {}).get("median_boundaryP95Px"),
                "medianMeanDeltaE00": flat_summary.get(engine, {}).get("median_meanDeltaE00"),
                "medianPeakCombinedWorkingSetBytes": flat_summary.get(engine, {}).get("median_peakCombinedWorkingSetBytes"),
                "evidenceScope": "eight synthetic analytical flat/icon fixtures only",
            }
            for engine in ("smart_reconstruction", "contour_preserving")
        },
        "radialGradientSyntheticEvidence": {
            "fixture": "synthetic-radial_gradient",
            "smartV2": radial.get("candidate_gradient_roi", {}),
            "variantValidation": read_json(BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_2" / "radial_variant_validation.json"),
            "limitation": "Synthetic analytic radial fixtures only; no independent real radial-logo family.",
        },
        "complexNonlinearGradientProduction": {
            "fixture": primary["fixture"],
            "smartV2Metrics": primary["currentProduction"],
            "rejectedResearchCandidateMetrics": primary["coordinateConsistentCandidate"],
            "researchCandidateDecision": task16b_status["RESEARCH_BRANCH_DECISION"],
            "researchCandidatePrimaryGates": primary["gates"],
        },
        "activeFoxTask07_1SelectedRois": {
            "sourceFamilyCount": 1,
            "smartFoxIcon": icon_roi.get("smart"),
            "contourFoxIcon": icon_roi.get("contour"),
            "smartTagline": text_roi.get("smart"),
            "contourTagline": text_roi.get("contour"),
            "note": "ROI boxes are not pixel-level semantic annotations; human review remains incomplete.",
        },
        "runtimeAndMemoryTask08A1": {"smart": smart_perf, "contour": contour_perf},
        "capabilities": [
            {"capability": "silhouette", "smart": "Measured on one ACTIVE FOX family and analytic fixtures; task 07.1 global silhouette IoU 0.9693.", "contour": "Measured on same one family and analytic fixtures; task 07.1 global silhouette IoU 0.9822.", "assessment": "INSUFFICIENT_EVIDENCE for broad recommendation; contour's measured advantage is case-specific."},
            {"capability": "internal boundaries", "smart": "Frozen V2 segmentation/geometry regression passes; no broad independent real truth.", "contour": "Shared canonical boundaries and topology tests pass; some photo SVGs fail to render.", "assessment": "Synthetic/topology evidence only; real-category generalization unproven."},
            {"capability": "thin features", "smart": "Specific 08B.0.3 regression and synthetic detail cases pass.", "contour": "Specific region repair and analytic geometry cases pass; Task 08B.1.6B rejected candidate loses thin-highlight recall.", "assessment": "INSUFFICIENT_EVIDENCE for real line-art category."},
            {"capability": "flat-color accuracy", "smart": "Strong measured synthetic flat fixture medians; no class-level human review.", "contour": "Strong measured synthetic flat fixture medians; no class-level human review.", "assessment": "INSUFFICIENT_EVIDENCE for customer artwork."},
            {"capability": "linear gradients", "smart": "Synthetic controlled cases pass for named low-contrast/hard-boundary fixtures.", "contour": "Same synthetic cases pass API/render checks; broader color continuity is limited.", "assessment": "INSUFFICIENT_EVIDENCE for real gradient logos."},
            {"capability": "radial gradients", "smart": "Task 08B.1.2 repaired a synthetic analytic radial fit and held-out synthetic variants passed.", "contour": "Synthetic analytic tests exist, but no real radial family.", "assessment": "LIMITED_SUPPORT only for tested analytic cases."},
            {"capability": "complex nonlinear gradients", "smart": "False hard edges reproduced; latest production has 1.5741% false-edge fraction on primary synthetic fixture.", "contour": "Same failure mode reproduced; latest coordinate-consistent research candidate is not production-ready.", "assessment": "KNOWN_UNSUPPORTED_OR_FAILED for the evaluated nonlinear-gradient fidelity target."},
            {"capability": "small details", "smart": "Selected synthetic exact-mask/detail cases pass; real-family generalization absent.", "contour": "Selected geometry cases pass; style/paint can differ, and thin-highlight research gate failed.", "assessment": "LIMITED/INSUFFICIENT_EVIDENCE; do not claim all fine details survive."},
            {"capability": "typography", "smart": "Outlined vector output exists; standalone raster text failed in Task 08A.1; no glyph reference.", "contour": "Outlined/editable modes implemented; same standalone text failure; font approximation warning possible.", "assessment": "LIMITED_SUPPORT; exact typography not proven."},
            {"capability": "alpha/transparency", "smart": "Synthetic analytic alpha cases pass; one real alpha sample failed.", "contour": "Synthetic analytic alpha cases pass; one real alpha sample failed.", "assessment": "NOT_VALIDATED for real transparent PNG artwork."},
            {"capability": "job reliability on Task 08A.1 real inputs", "smart": "4/11 variants succeeded.", "contour": "5/11 variants succeeded.", "assessment": "The two engines were both successful on 4/11 variants; no engine dominates all tested cases."},
        ],
    }
    write_json("engine_capability_matrix.json", engine_capability)

    comparison = {
        "schemaVersion": 1,
        "defaultRecommendation": "Keep Smart Reconstruction V2 as the current default; this audit does not change selection.",
        "smartReconstructionV2": {
            "role": "production default",
            "verifiedStrengths": ["API job route and error/result metadata", "synthetic flat geometry/color cases", "specific analytic radial-gradient repair", "outlined vector-only SVG output"],
            "knownWeaknesses": ["failed visibility/topology cases on selected real photographs", "complex nonlinear gradient false edges", "no independent class-wide real human review"],
            "appropriateUse": "Use as the existing production default for internal/best-effort logo-like jobs while showing output preview and allowing the user to reject poor results; do not market unproven categories as quality-supported.",
        },
        "contourPreserving": {
            "role": "experimental opt-in",
            "verifiedStrengths": ["shared boundary/topology invariants", "synthetic flat geometry and selected detail cases", "selected one-family ACTIVE FOX silhouette measurements"],
            "knownWeaknesses": ["not a universal visual-quality winner", "selected real photo/text SVGs fail browser visibility validation", "higher measured memory/runtime on some runs", "nonlinear-gradient false edges"],
            "appropriateUse": "Local comparative experiments on selected clean artwork; keep the experimental warning and do not enable as product default on the strength of synthetic silhouette metrics.",
        },
        "perMetric": engine_capability["capabilities"],
        "insufficientEvidence": ["broad photo conversion", "real line art", "real transparent artwork", "general typography fidelity", "general complex illustration fidelity", "wide range of real gradients"],
        "selectionChanged": False,
    }
    write_json("engine_comparison_for_beta.json", comparison)

    write_json("repository_feature_inventory.json", {
        "schemaVersion": 1,
        "repository": {
            "path": str(ROOT),
            "git": "No commits yet on master; project files are untracked, so Git cannot provide a historical clean diff.",
            "auditBaseline": "SHA-256 snapshot over backend/mediastudio and src/MediaStudio.Desktop saved before validation.",
            "python": ".venv Python 3.12; full backend regression ran in this environment.",
            "dotnet": "SDK 10.0.401; WindowsDesktop.App 10.0.12.",
        },
        "features": [
            {"component": "Smart Reconstruction V2", "implemented": True, "status": "IMPLEMENTED_AND_AUTOMATED_BACKEND_VALIDATED", "default": "MEDIASTUDIO_VECTORIZE_PIPELINE defaults to v2; explicit smart_reconstruction dispatches to V2", "entryPoints": ["backend/mediastudio/api.py", "backend/mediastudio/image_tools/vectorize.py", "backend/mediastudio/image_tools/vectorization_v2/production.py"], "evidence": ["full regression PASS", "two Task 08A/08A.1 API benchmark outputs", "Task 08B.1.7 real API smoke succeeded", "SVG validation records"], "limits": ["real-image supported-category proof absent", "complex nonlinear gradient fidelity gate fails"]},
            {"component": "Contour-Preserving", "implemented": True, "status": "IMPLEMENTED_EXPERIMENTAL_AND_AUTOMATED_BACKEND_VALIDATED", "default": "off unless MEDIASTUDIO_CONTOUR_EXPERIMENTAL=1 and scikit-image 0.26.0 is available", "entryPoints": ["backend/mediastudio/image_tools/contour_backend.py", "backend/mediastudio/image_tools/vectorization_contour", "backend/mediastudio/image_tools/contour_svg_composer.py"], "evidence": ["full regression PASS", "Task 08A/08A.1 actual API outputs", "Task 08B.1.7 API smoke succeeded"], "limits": ["experimental; not manually accepted in WPF window", "some benchmark photo/text jobs fail visibility validation"]},
            {"component": "SVG generation/composition", "implemented": True, "status": "AUTOMATED_OUTPUT_VALIDATION_PASS_ON_AUDITED_SUCCESSFUL_ARTIFACTS", "entryPoints": ["backend/mediastudio/image_tools/vectorization_v2/svg_composer.py", "backend/mediastudio/image_tools/contour_svg_composer.py"], "evidence": [f"{svg_audit['uniqueSavedSvgFiles']} unique saved benchmark SVGs scanned", "two current API smoke SVGs parsed", "no embedded raster found in audited outputs"], "limits": ["technical paths do not imply semantic/practical editability"]},
            {"component": "Vectorization API", "implemented": True, "status": "API_CONTRACT_AND_JOB_PATH_AUTOMATED_VALIDATION_PASS", "entryPoints": ["POST /api/v1/assets", "POST /api/v1/vectorize/jobs", "GET /api/v1/jobs/{job_id}", "GET /api/v1/jobs/{job_id}/result"], "evidence": ["FastAPI tests", "Task 08A/08A.1 run records", "two real TestClient API smoke jobs"], "limits": ["job manager uses one worker; no job-cancel endpoint found"]},
            {"component": "WPF engine selector", "implemented": True, "status": "IMPLEMENTED_BUILD_VERIFIED_MANUAL_GUI_NOT_TESTED", "entryPoints": ["src/MediaStudio.Desktop/Views/VectorizeToolView.xaml", "src/MediaStudio.Desktop/ViewModels/VectorizeToolViewModel.cs", "src/MediaStudio.Desktop/Services/VectorizationJobService.cs"], "evidence": ["Release WPF build succeeded", "Task 07.1 isolated ViewModel harness"], "limits": ["no live WPF screenshot or manual control interaction"]},
            {"component": "WPF Compare Mode", "implemented": True, "status": "IMPLEMENTED_NOT_FULLY_VALIDATED", "details": "Reuses one asset ID and sequentially runs Smart then Contour; side-by-side panes and separate save commands exist.", "evidence": ["ViewModel source and Task 07.1 deterministic transport harness"], "limits": ["manual click-through, disabled states and partial-failure UX not tested in the live window"]},
            {"component": "WPF SVG preview", "implemented": True, "status": "IMPLEMENTED_VIEWMODEL_RENDER_PATH_TESTED_WINDOW_NOT_TESTED", "details": "Svg.Skia preview bitmap method is in the production ViewModel.", "evidence": ["Task 07.1 Svg.Skia-vs-Edge comparison; no actual window screenshot"], "limits": ["DPI/layout/panel binding and rendered desktop pixels remain unverified"]},
            {"component": "WPF SVG save/export", "implemented": True, "status": "IMPLEMENTED_DETERMINISTIC_BYTES_TESTED_LIVE_GUI_NOT_TESTED", "details": "Downloads result bytes and writes them via file picker without SVG re-encoding.", "evidence": ["Task 07.1 saved-from-ViewModel hashes match direct API SVG hashes exactly"], "limits": ["no current manual Save dialog → external SVG reopen end-to-end test"]},
            {"component": "Job status/error handling", "implemented": True, "status": "AUTOMATED_API_AND_VIEWMODEL_HANDLING_TESTED", "details": "Async job states, structured failure codes and visible ViewModel failure state exist.", "evidence": ["backend full regression and Task 08A.1 failure results"], "limits": ["no live-window manual check of all failure messages; no cancel API"]},
            {"component": "Release packaging", "implemented": False, "status": "NOT_TESTED", "details": "README explicitly says PyInstaller/backend bundle, installer/self-contained configuration, dependencies and license notices remain to be completed."},
        ],
        "manualWpfQa": "NOT_TESTED",
        "userFacingExportEndToEnd": "NOT_TESTED",
        "fullBackendRegression": full_regression,
        "svgAudit": {key: svg_audit[key] for key in ("benchmarkResultReferences", "uniqueSavedSvgFiles", "uniqueSvgStatusCounts", "allUniqueSvgStructurallyValidVectorOnly")},
    })

    write_json("integration_evidence_matrix.json", {
        "schemaVersion": 1,
        "rows": [
            {"workflow": "source image import", "implementation": "AssetStore and WPF multipart upload", "evidenceStatus": "VERIFIED_AUTOMATED", "evidence": ["Task 08B.1.7 smoke input asset IDs and 512×512 dimensions", "test_vectorization_v2_product.py", "test_contour_task06.py"], "manualDesktop": "NOT_TESTED"},
            {"workflow": "Smart V2 engine dispatch", "implementation": "API default v2 and explicit smart_reconstruction", "evidenceStatus": "VERIFIED_AUTOMATED", "evidence": ["full regression", "smoke_smart_reconstruction.svg", "Task 08A.1 actual API result"], "manualDesktop": "NOT_TESTED"},
            {"workflow": "Contour opt-in/engine dispatch", "implementation": "experimental flag and pinned optional dependency; structured rejection if off", "evidenceStatus": "VERIFIED_AUTOMATED", "evidence": ["test_contour_task06.py", "test_task07_engine_health.py", "smoke_contour_preserving.svg"], "manualDesktop": "NOT_TESTED"},
            {"workflow": "job polling and failure state", "implementation": "one-worker JobManager, state route, error metadata", "evidenceStatus": "VERIFIED_AUTOMATED_WITH_INPUT_FAILURES_SURFACED", "evidence": ["Task 08A.1 per_image_results.json failureReason/failureCode", "backend API tests"], "manualDesktop": "NOT_TESTED"},
            {"workflow": "SVG result download", "implementation": "GET result returns image/svg+xml bytes", "evidenceStatus": "VERIFIED_AUTOMATED", "evidence": ["two Task 08B.1.7 result downloads", "test_vectorization_v2_product.py"], "manualDesktop": "NOT_TESTED"},
            {"workflow": "SVG XML/vector integrity", "implementation": "composer structure checks plus browser validation; no embedded raster", "evidenceStatus": "VERIFIED_FOR_AUDITED_SUCCESSFUL_JOBS", "evidence": ["svg_quality_audit.json", "beta_smoke_test_results.json", "svg_integrity records in prior benchmark artifacts"], "manualDesktop": "NOT_TESTED"},
            {"workflow": "WPF engine selector", "implementation": "ComboBox bound to SelectedVectorMethod and Contour readiness", "evidenceStatus": "IMPLEMENTED_BUILD_VERIFIED", "evidence": ["Release build result", "VectorizeToolView.xaml", "VectorizeToolViewModel.cs"], "manualDesktop": "NOT_TESTED"},
            {"workflow": "WPF Compare Mode", "implementation": "same asset ID; sequential Smart then Contour; separate result panes", "evidenceStatus": "IMPLEMENTED_VIEWMODEL_HARNESS_ONLY", "evidence": ["Task 07.1 report; deterministic transport harness"], "manualDesktop": "NOT_TESTED"},
            {"workflow": "WPF preview", "implementation": "Svg.Skia render in production ViewModel", "evidenceStatus": "VIEWMODEL_METHOD_TESTED_WINDOW_NOT_TESTED", "evidence": ["Task 07.1 preview_renderer_comparison.json"], "manualDesktop": "NOT_TESTED"},
            {"workflow": "WPF SVG save", "implementation": "raw downloaded bytes written to selected path", "evidenceStatus": "BYTE_IDENTITY_IN_VIEWMODEL_HARNESS_ONLY", "evidence": ["Task 07.1 svg_hash_validation.json; direct API and ViewModel file hashes match"], "manualDesktop": "NOT_TESTED"},
            {"workflow": "WPF build", "implementation": "net10.0-windows WPF project", "evidenceStatus": "PASS", "evidence": ["dotnet build Release; 0 warnings, 0 errors"], "manualDesktop": "NOT_APPLICABLE"},
            {"workflow": "installer/package install/rollback", "implementation": "no completed release package evidence", "evidenceStatus": "NOT_TESTED", "evidence": ["backend/README.md release section"], "manualDesktop": "NOT_TESTED"},
        ],
        "interpretation": "Backend/API automated integration does not prove end-to-end desktop UI behavior. ViewModel harness artifacts are not screenshots or clicks in a live WPF window.",
    })

    write_text("vectorization_architecture_status.md", """# Vectorization architecture status — Task 08B.1.7

## Runtime path

1. The WPF client selects a source image and uploads it through `MediaStudioApiClient` to the FastAPI asset endpoint.
2. WPF submits an asynchronous vectorization job. The API/job manager records the selected method, returns a job ID, and exposes status and result endpoints.
3. `backend/mediastudio/image_tools/vectorize.py` dispatches to Smart Reconstruction V2 or, when explicitly selected and enabled, Contour-Preserving.
4. Smart V2 is the API default (`MEDIASTUDIO_VECTORIZE_PIPELINE=v2`). Contour requires an explicit method plus `MEDIASTUDIO_CONTOUR_EXPERIMENTAL=1` and the pinned optional scikit-image dependency; it is not the default.
5. Each engine composes native SVG elements. The API returns SVG bytes as the job result. The WPF ViewModel uses Svg.Skia for preview and saves the downloaded bytes without re-encoding.
6. Compare Mode uploads once and runs Smart then Contour sequentially against the same asset, retaining separate outputs.

## Failure and validation behavior

- Job status and structured error metadata exist; benchmark failures are recorded as failed jobs rather than accepted blank output.
- Automated regression and current API upload → job → poll → SVG download smoke evidence pass. The audited successful SVG set is vector-only and structurally valid.
- The Release WPF project builds. Prior ViewModel harness evidence verifies preview method and byte-identical save behavior, but it is not a live-window manual run.
- Live WPF selector/Compare interaction, Save dialog → external editor reopen, clean-machine installation, and package/rollback remain `NOT_TESTED`.

## Source entry points

- API/job orchestration: `backend/mediastudio/api.py`, `backend/mediastudio/jobs/manager.py`.
- Engine dispatch: `backend/mediastudio/image_tools/vectorize.py`.
- Smart V2: `backend/mediastudio/image_tools/vectorization_v2/production.py`, `backend/mediastudio/image_tools/vectorization_v2/svg_composer.py`.
- Contour: `backend/mediastudio/image_tools/contour_backend.py`, `backend/mediastudio/image_tools/vectorization_contour/`, `backend/mediastudio/image_tools/contour_svg_composer.py`.
- Desktop: `src/MediaStudio.Desktop/Services/MediaStudioApiClient.cs`, `src/MediaStudio.Desktop/Services/VectorizationJobService.cs`, `src/MediaStudio.Desktop/ViewModels/VectorizeToolViewModel.cs`, `src/MediaStudio.Desktop/Views/VectorizeToolView.xaml`.

## Readiness conclusion

The two-engine API path and SVG creation are implemented and have automated evidence. End-to-end desktop UX and release packaging are not fully validated. Do not treat backend regression as WPF manual QA or product-fidelity approval. See `integration_evidence_matrix.json`, `desktop_validation_status.json`, and `release_readiness_matrix.json`.
""")

    limitations = [
        {"id": "LIM-01", "category": "visual_fidelity", "severity": "HIGH_PRIORITY", "description": "No real source family has an original vector reference and human blind-review scores are absent; no user artwork category is human-approved.", "evidence": ["Task 08A.1 review_manifest.json", "human_review_results.csv contains only the header", "real_dataset_manifest.json"]},
        {"id": "LIM-02", "category": "nonlinear_gradient", "severity": "RESEARCH_LIMITATION", "description": "The evaluated nonlinear gradient produces false hard edges in production; coordinate-consistent research model failed all primary/held-out quality gates and was not integrated.", "evidence": ["Task 08B.1.3 gradient_banding_matrix.json", "Task 08B.1.6B acceptance_status.json"]},
        {"id": "LIM-03", "category": "photographs", "severity": "KNOWN_UNSUPPORTED_OR_FAILED", "description": "Many measured public photo examples fail job completion or visible-SVG validation; this category must be excluded from first Beta claims.", "evidence": ["Task 08A.1 per_image_results.json; Smart 2/7 and Contour 3/7 photo jobs succeeded"]},
        {"id": "LIM-04", "category": "typography", "severity": "MEDIUM_PRIORITY", "description": "Outlined glyphs are paths and are not semantic text; editable text depends on font selection/approximation, and the standalone raster-text fixture failed.", "evidence": ["Task 08A.1 per_image_results.json", "contour_backend warnings", "Task 07.1 text ROI metrics"]},
        {"id": "LIM-05", "category": "alpha", "severity": "HIGH_PRIORITY", "description": "Real transparent-image coverage consists of one alpha-channel icon that failed in both engines; synthetic alpha tests are not real-world proof.", "evidence": ["Task 08A.1 real_dataset_manifest.json and per_image_results.json"]},
        {"id": "LIM-06", "category": "performance", "severity": "HIGH_PRIORITY", "description": "Measured successful job medians are about 100 s Smart and 145 s Contour on the selected Task 08A.1 sample; observed attempts reach several minutes and sampled memory approaches 3.8 GB.", "evidence": ["Task 08A.1 per_image_results.json", "runtimeAndMemory in engine_capability_matrix.json"], "caveat": "These are selected fixtures/environment observations, not an SLO or worst-case bound."},
        {"id": "LIM-07", "category": "desktop", "severity": "INSUFFICIENT_EVIDENCE", "description": "Build and deterministic ViewModel harness evidence exist; no live-window manual QA or user-facing import→preview→save→reopen E2E evidence exists.", "evidence": ["Task 07.1 report explicitly says manualWpfWindowQa=not_tested", "desktop_validation_status.json"]},
        {"id": "LIM-08", "category": "editability", "severity": "MEDIUM_PRIORITY", "description": "No embedded raster proves technical vector output only; object grouping, semantic labels, and convenient per-part editing have not been assessed in a vector editor.", "evidence": ["svg_quality_audit.json", "svg_editability_assessment.md"]},
        {"id": "LIM-09", "category": "packaging", "severity": "INSUFFICIENT_EVIDENCE", "description": "No installer/package clean-machine install, dependency bundle, license notice, versioning, or rollback evidence exists.", "evidence": ["backend/README.md release section", "release_readiness_matrix.json"]},
        {"id": "LIM-10", "category": "job_management", "severity": "MEDIUM_PRIORITY", "description": "JobManager has one worker and no cancellation endpoint; a long or difficult job can queue/block the next job.", "evidence": ["backend/mediastudio/api.py", "backend/mediastudio/jobs/manager.py", "src/MediaStudio.Desktop/Services/VectorizationJobService.cs"]},
    ]
    write_json("known_limitations.json", {"schemaVersion": 1, "items": limitations})
    write_json("research_limitations.json", {
        "schemaVersion": 1,
        "scope": "Record frozen research findings; do not start or tune another gradient model in this task.",
        "items": [
            {"id": "RESEARCH-01", "status": "FEASIBILITY_NOT_PROVEN", "topic": "coordinate-consistent multidirectional gradient fit", "evidence": "Task 08B.1.6B CASE_B: coordinate mismatch fixed, objective/render agree, but primary false-edge/color gates and held-out validation fail.", "task08b_1_7Action": "Do not integrate and do not continue the same research line here."},
            {"id": "RESEARCH-02", "status": "SPECIFIC_CASE_FIX_ONLY", "topic": "radial gradients", "evidence": "Task 08B.1.2 synthetic analytic radial fitter improvement passed its train and held-out synthetic cases.", "task08b_1_7Action": "Keep only as scoped evidence; do not infer broad real artwork generalization."},
            {"id": "RESEARCH-03", "status": "NO_REAL_GROUND_TRUTH", "topic": "broad source-faithful vector reconstruction", "evidence": "No independent real source family has an original SVG/vector reference; synthetic ground truth covers controlled constructs only.", "task08b_1_7Action": "Resolve dataset/human evidence before proposing algorithm research."},
        ],
    })

    beta_blockers = [
        {"issueId": "BETA-BLK-01", "severity": "BLOCKER", "affectedWorkflow": "publishing any supported-image fidelity claim", "description": "No design-artwork category reaches four independent real families plus completed human visual review; no original vector reference family is recorded.", "evidence": ["dataset_coverage_matrix.json", "source_family_audit.json", "missing_beta_evidence.json"], "reproductionStatus": "VERIFIED_DATA_GAP", "smallestRecommendedFix": "Collect permission-cleared, independent real examples for one narrowly selected category; freeze its scope and blind-review all accepted outputs against predeclared visual criteria.", "mustFixBeforeBeta": True, "scopeCondition": "A closed engineering prototype can be shown as best-effort, but it cannot be described as a quality-supported Beta category."},
        {"issueId": "BETA-BLK-02", "severity": "BLOCKER", "affectedWorkflow": "WPF import → choose engine → compare/preview → save → reopen", "description": "No live WPF manual QA or current user-facing export end-to-end test exists. The prior harness used deterministic HTTP responses and actual API SVG bytes, not a running window.", "evidence": ["Task 07.1 task_07_1_report.md", "integration_evidence_matrix.json", "desktop_validation_status.json"], "reproductionStatus": "NOT_TESTED_IN_LIVE_WINDOW", "smallestRecommendedFix": "Run the supplied manual desktop checklist on a Release build with one accepted artwork fixture and one explicit job-failure case; capture window evidence and reopen the saved SVG.", "mustFixBeforeBeta": True},
        {"issueId": "BETA-BLK-03", "severity": "BLOCKER", "affectedWorkflow": "install and launch Beta on a clean Windows machine", "description": "Release packaging is not implemented/validated; current docs say backend bundling, self-contained/installer settings, dependencies, and license notices remain.", "evidence": ["backend/README.md Release section", "release_readiness_matrix.json"], "reproductionStatus": "NOT_TESTED", "smallestRecommendedFix": "Define a reproducible package, dependency/license manifest, clean-machine installation smoke test, versioned release notes, and rollback procedure.", "mustFixBeforeBeta": True},
        {"issueId": "BETA-BLK-04", "severity": "BLOCKER_IF_GENERAL_PURPOSE_SCOPE", "affectedWorkflow": "user uploads arbitrary raster and expects conversion", "description": "The UI/API accept broad raster input but no category qualifies as SUPPORTED_WITH_EVIDENCE; photo-like inputs have repeated visible-output/job failures. An unrestricted converter claim is not defensible.", "evidence": ["supported_image_matrix.json", "Task 08A.1 per_image_results.json", "Task 08B.1.6B acceptance_status.json"], "reproductionStatus": "VERIFIED_FOR_NAMED_FIXTURES", "smallestRecommendedFix": "Before any Beta claim, explicitly restrict/document the input scope and give users visible limitations/failure expectations; then qualify the selected scope with real evidence.", "mustFixBeforeBeta": True},
    ]
    write_json("beta_blockers.json", {"schemaVersion": 1, "blockerCount": len(beta_blockers), "items": beta_blockers})
    write_json("quality_risks.json", {
        "schemaVersion": 1,
        "items": [
            {"id": "RISK-01", "severity": "HIGH_PRIORITY", "issue": "Complex nonlinear gradients develop false hard-edge bands.", "evidence": {"productionFalseEdgeFraction": primary["currentProduction"]["falseEdgeFraction"], "meanDeltaE00": primary["currentProduction"]["meanDeltaE00"], "p95DeltaE00": primary["currentProduction"]["p95DeltaE00"], "fixture": primary["fixture"]}, "mitigationForFirstBeta": "Exclude complex nonlinear-gradient fidelity claims; make preview the user acceptance step."},
            {"id": "RISK-02", "severity": "HIGH_PRIORITY", "issue": "Real photograph samples frequently fail, and long runtimes/high memory are observed.", "evidence": {"photoJobs": photo_summary, "smartMaxObservedAttemptSeconds": smart_perf["maxObservedWallSecondsAllAttempts"], "contourMaxObservedAttemptSeconds": contour_perf["maxObservedWallSecondsAllAttempts"], "contourMaxSuccessfulSampledMemoryBytes": contour_perf["maxSuccessfulPeakSampledWorkingSetBytes"]}, "mitigationForFirstBeta": "Exclude photo conversion from supported scope; record performance on the selected artwork scope."},
            {"id": "RISK-03", "severity": "MEDIUM_PRIORITY", "issue": "Outlined text may be node-editable but not semantically editable; editable text uses a chosen/approximate font.", "evidence": ["Task 07.1 typography ROI artifacts", "backend/mediastudio/image_tools/contour_backend.py warning codes"], "mitigationForFirstBeta": "Describe text mode accurately and require visual review for typography-heavy artwork."},
            {"id": "RISK-04", "severity": "MEDIUM_PRIORITY", "issue": "Experimental Contour has no basis for promotion to default; on real sample benchmark it succeeds on five of eleven variants, versus Smart on four of eleven, with different failures and tradeoffs.", "evidence": "Task 08A.1 per-image results; selected synthetic and Task 07.1 ROI metrics.", "mitigationForFirstBeta": "Keep Smart as default and Contour opt-in/experimental."},
            {"id": "RISK-05", "severity": "MEDIUM_PRIORITY", "issue": "Single-worker queue and no cancellation can create perceived hangs for long vector jobs.", "evidence": ["backend/mediastudio/jobs/manager.py", "VectorizationJobService.cs JobWaitLimit"], "mitigationForFirstBeta": "Document expected best-effort wait behavior and test visible progress/timeouts on the supported input scope; set limits only after target-hardware evidence."},
            {"id": "RISK-06", "severity": "MEDIUM_PRIORITY", "issue": "Technical vector output is not yet rated for practical editability in a vector editor.", "evidence": "svg_editability_assessment.md", "mitigationForFirstBeta": "Inspect a representative saved SVG in the target vector editor and document grouping/text behavior."},
        ],
    })

    gates = [
        {"gateId": "G1_BACKEND_RELIABILITY", "status": "PASS_WITH_SCOPE_LIMITS", "currentEvidence": ["378 tests and 360 subtests pass", "both current API smoke jobs succeed", "dimension-order, thin-feature and GEOS regressions are included in suite", "known invalid/invisible jobs are surfaced as failed in benchmark evidence"], "acceptance": ["full backend regression clean", "no malformed/empty SVG is marked succeeded", "known out-of-scope inputs fail visibly with no success file"], "openItems": ["test valid and rejected inputs on packaged backend" ]},
        {"gateId": "G2_SVG_INTEGRITY", "status": "PASS_FOR_AUDITED_OUTPUTS", "currentEvidence": [f"{svg_audit['uniqueSavedSvgFiles']} unique saved SVG outputs scanned from Task 08A/08A.1; all pass XML/dimensions/viewBox/local refs/vector-only checks", "two current API smoke SVGs pass"], "acceptance": ["actual downloaded bytes validate", "no embedded raster or unresolved resource", "source-sized viewBox and render validated"], "openItems": ["manual reopen/export on clean target vector editor"]},
        {"gateId": "G3_SUPPORTED_INPUT_SCOPE", "status": "FAIL", "currentEvidence": ["nine-category matrix created, zero categories are SUPPORTED_WITH_EVIDENCE", "every design-artwork category misses four real families and human review"], "acceptance": ["advertised categories each have at least four independent real source families as 08A milestone", "each category has explicit limitation and accepted/rejected examples", "no synthetic-only claim"], "openItems": ["collect permissioned examples and freeze first Beta scope"]},
        {"gateId": "G4_VISUAL_FIDELITY", "status": "FAIL", "currentEvidence": ["human review remains pending on 29 images/160 ROIs", "no original real SVG reference family", "Task 08B.1.6B nonlinear model quality gates fail"], "acceptance": ["predeclared metrics on independent real families", "completed visual review of output at same scale/background", "no unaddressed critical defect in advertised scope"], "openItems": ["human review and scope-specific quality acceptance threshold"]},
        {"gateId": "G5_DESKTOP_INTEGRATION", "status": "PARTIAL", "currentEvidence": ["WPF Release build succeeds with 0 warnings/errors", "Task 07.1 ViewModel harness exact-saved-byte hashes", "current API smoke pass"], "acceptance": ["live app import/selector/run/preview/compare/error/save/reopen verified", "Contour disabled/enabled behavior verified", "manual QA evidence saved"], "openItems": ["live window manual QA; user-facing E2E not tested"]},
        {"gateId": "G6_PERFORMANCE_RESOURCE_SAFETY", "status": "PARTIAL", "currentEvidence": ["Task 08A.1 real-set timings and sampled memory recorded", "Contour has 20MP/12k/4GiB input/process caps documented", "Smart V2 uses bounded work canvas"], "acceptance": ["measure p50/p95 and memory on proposed supported scope and target class", "define limits from product/target hardware rather than invented values", "verify no crash/hang in that scope"], "openItems": ["target hardware acceptance limits and clean packaged runs"]},
        {"gateId": "G7_RELEASE_PACKAGING", "status": "NOT_TESTED", "currentEvidence": ["no installer/published package evidence", "README states bundle/installer/dependency/license tasks remain"], "acceptance": ["reproducible versioned package", "clean Windows install/launch smoke", "license/dependency manifest", "rollback/release notes"], "openItems": ["all packaging and clean-machine checks"]},
    ]
    write_json("beta_acceptance_gates.json", {"schemaVersion": 1, "gates": gates, "overallBetaAcceptance": "FAIL_UNTIL_BLOCKERS_CLOSED"})
    write_json("release_readiness_matrix.json", {
        "schemaVersion": 1,
        "status": "NOT_READY",
        "betaReleaseReady": False,
        "productionReleaseReady": False,
        "gates": [{"gateId": row["gateId"], "status": row["status"]} for row in gates],
        "blockingIssueIds": [row["issueId"] for row in beta_blockers],
        "nonBlockingKnownLimitations": ["photo-like conversion outside any proposed supported design-artwork scope", "nonlinear-gradient model research limitation", "Contour remains experimental"],
    })

    build = {
        "command": "dotnet build src/MediaStudio.Desktop/MediaStudio.Desktop.csproj --configuration Release",
        "status": "PASS",
        "targetFramework": "net10.0-windows",
        "sdk": "10.0.401",
        "runtime": "Microsoft.WindowsDesktop.App 10.0.12",
        "warnings": 0,
        "errors": 0,
        "output": "src/MediaStudio.Desktop/bin/Release/net10.0-windows/MediaStudio.Desktop.dll",
        "manualWindowQa": "NOT_TESTED",
        "liveWindowScreenshot": "NOT_AVAILABLE",
        "compareModeLiveInteraction": "NOT_TESTED",
        "saveDialogToExternalVectorEditorE2E": "NOT_TESTED",
        "priorEvidence": {
            "viewModelHarnessExactByteSave": "PASS; two saved SVG hashes match direct API bytes",
            "actualWindowScreenshot": "not available in Task 07.1; harness used deterministic HTTP responses and production ViewModel methods",
        },
        "checklist": "manual_desktop_qa_checklist.md",
        "statusInterpretation": "Build verification does not mean manual WPF QA is complete.",
    }
    write_json("desktop_validation_status.json", build)
    write_json("beta_blockers.json", {"schemaVersion": 1, "blockerCount": len(beta_blockers), "items": beta_blockers})

    plan = [
        {"taskId": "BETA-01", "title": "Select and substantiate one narrow real-artwork scope", "objective": "Build a permission-cleared representative set, preserving family identity and source hashes; add appropriate vector/shape/color references and complete blind human review.", "deliverables": ["updated source-family manifest", "category report with independent source families", "review scores and defect decisions", "preregistered category-specific metric gates"], "acceptanceCriteria": ["at least four independent real families for each category proposed for Beta", "ACTIVE FOX variants count as one family", "synthetic cases remain a separate evidence class", "no unresolved critical defect in accepted scope"], "preconditions": ["choose proposed Beta artwork category", "obtain rights/permission to use samples"], "difficulty": "MEDIUM", "stopCondition": "Stop if no category has permitted representative sources or fails predeclared visual review; do not broaden claims."},
        {"taskId": "BETA-02", "title": "Complete live WPF manual integration and export QA", "objective": "Test the built Windows app using a qualified fixture through import, default Smart selection, optional Contour, Compare, preview, visible failure handling, save, and reopen.", "deliverables": ["dated checklist", "screenshots/video of live window", "source/output SVG hashes", "failure and success job logs"], "acceptanceCriteria": ["all advertised flows work in the actual WPF window", "same-source Compare is clear and both outputs are correctly labeled", "saved bytes reopen and are vector-only", "failure never appears as success"], "preconditions": ["BETA-01 selected fixture/scope", "Release build available"], "difficulty": "MEDIUM", "stopCondition": "Stop release progression on selector, preview, compare, save/reopen, or error-state mismatch."},
        {"taskId": "BETA-03", "title": "Publish precise Beta input scope and user-facing limitation wording", "objective": "Translate accepted evidence into a visible supported-input statement and explicit exclusions without claiming quality for untested categories.", "deliverables": ["approved support matrix", "in-app help/release wording", "known limitations and examples"], "acceptanceCriteria": ["each supported group maps to accepted real evidence", "photos, complex nonlinear gradients, and unvalidated groups are explicitly called out", "job success is not described as visual fidelity acceptance"], "preconditions": ["BETA-01 results"], "difficulty": "SMALL", "stopCondition": "Stop if any public copy claims unsupported/high-fidelity coverage."},
        {"taskId": "BETA-04", "title": "Qualify runtime and resource behavior on the proposed Beta scope", "objective": "Measure p50/p95 runtime and sampled peak memory on target hardware using the accepted real dataset; establish input/resource policy from those results.", "deliverables": ["scope-specific performance report", "target machine spec", "evidence-based time/memory limits or explicit caveat"], "acceptanceCriteria": ["all selected-family jobs have status/runtime/resource records", "no crash/hang on supported scope", "limits are evidence-derived and user-visible"], "preconditions": ["BETA-01 scope frozen"], "difficulty": "MEDIUM", "stopCondition": "Stop or narrow scope if jobs exceed target reliability/resource constraints; do not invent a limit to pass."},
        {"taskId": "BETA-05", "title": "Create and verify Windows Beta packaging", "objective": "Produce a reproducible desktop/backend package with declared dependencies, runtime requirements and licenses.", "deliverables": ["versioned package", "dependency/license inventory", "install/uninstall/rollback instructions", "clean-machine smoke evidence"], "acceptanceCriteria": ["install and launch on a clean supported Windows machine", "vectorize accepted fixture and save/reopen SVG", "logs and uninstall/rollback work", "third-party notices are present"], "preconditions": ["BETA-02 flows accepted", "dependency and license review"], "difficulty": "HIGH", "stopCondition": "Stop distribution if package omits required runtime/dependency/license or cannot reproduce the validated workflow."},
        {"taskId": "BETA-06", "title": "Beta candidate freeze and release acceptance", "objective": "Re-run regression, accepted-scope benchmark, manual smoke and package integrity against one frozen candidate; publish release notes and rollback target.", "deliverables": ["candidate manifest/hashes", "full regression and selected benchmark", "manual QA sign-off", "release notes and rollback record"], "acceptanceCriteria": ["all acceptance gates pass", "Smart V2 and Contour source hashes are recorded", "no production change after QA without rerunning affected gates", "release manager signs scope and known limitations"], "preconditions": ["BETA-01 through BETA-05"], "difficulty": "MEDIUM", "stopCondition": "Stop and return to the earliest failed gate; do not release on backend regression alone."},
    ]
    write_json("beta_remaining_task_plan.json", {
        "schemaVersion": 1,
        "maxTasks": 6,
        "proposedTasks": plan,
        "sequence": ["BETA-01", "BETA-03", "BETA-02", "BETA-04", "BETA-05", "BETA-06"],
        "sixTasksSufficiency": "Not guaranteed; revisit if BETA-01 reveals a production reliability blocker or any later gate fails.",
        "algorithmResearchTaskAdded": False,
    })

    checklist = """# Manual desktop QA checklist — MediaStudio Vector Beta

Status: **PENDING**. No live WPF window interaction was performed during Task 08B.1.7.

## Before testing

- [ ] Run the Release build on the supported Windows image and record OS, .NET Desktop Runtime, app version, backend version and feature flags.
- [ ] Use a permission-cleared, accepted-scope source fixture. Record its SHA-256, dimensions and source-family ID.
- [ ] Confirm the backend log path and that Smart V2 is the displayed default.
- [ ] Confirm Contour is disabled/hidden unless the experimental flag and pinned dependency are both ready; if enabled, the UI still labels it experimental.

## Smart Reconstruction V2

- [ ] Import the source and verify filename/dimensions in the live window.
- [ ] Start vectorization; verify the progress state changes and the displayed method is Smart V2.
- [ ] Verify completion reports the correct asset/method and that the preview is not blank.
- [ ] Inspect at fit, 100%, checkerboard, white and black backgrounds; note silhouette, boundaries, colors, gradients, detail and text defects separately.
- [ ] Save SVG using the WPF file picker. Record saved SHA-256 and byte size.
- [ ] Reopen the saved SVG in a browser and the intended vector editor; verify visible content, dimensions, transparency, paths and practical object grouping.

## Compare Mode and Contour-Preserving

- [ ] Import one source once and launch Compare; verify both panels use the same source, quality mode and text mode.
- [ ] Verify Smart and Contour labels do not cross, zoom/pan behavior is understandable, and partial failure preserves the successful result with a clear message.
- [ ] Save each SVG and compare saved hashes with the corresponding backend result hashes.
- [ ] If Contour is unavailable, confirm the UI explains why and cannot submit it accidentally.

## Failure and export safety

- [ ] Run one documented out-of-scope input; confirm the job fails visibly or displays a specific limitation, never “success” with an empty/invalid SVG.
- [ ] Confirm timeout/failure state, error text and backend log can be correlated to the same job.
- [ ] Confirm the source file is not overwritten when choosing an export destination.
- [ ] Reopen every saved SVG; parse XML, verify no embedded raster and record external-resource behavior.

## Evidence to attach

- [ ] Live application screenshots for selector, Compare, success, partial failure and saved output.
- [ ] Source/output SVG SHA-256 manifest and job IDs.
- [ ] Reviewer name/date and written decision for every advertised category.
- [ ] Mark each item PASS/FAIL/NOT_TESTED. Do not convert an unrun item into PASS.
"""
    write_text("manual_desktop_qa_checklist.md", checklist)

    scope_proposal = """# Beta scope proposal — MediaStudio Vectorization

## Recommendation

**Do not call the current build a general-purpose vectorization Beta yet.** The API and SVG pipeline work on selected fixtures, but none of the nine artwork categories currently reaches `SUPPORTED_WITH_EVIDENCE`. The formal dataset has 10 real source families, but they are distributed unevenly; ACTIVE FOX native/upscaled are one family. Blind human review has no score rows, and no real family has an original SVG reference.

## Scope for a first Beta candidate

- Keep **Smart Reconstruction V2** as the default; keep **Contour-Preserving** opt-in and explicitly experimental.
- Treat any current conversion as best-effort until one specific category has sufficient independent real examples, human approval and a frozen acceptance gate.
- Do not claim support for photographs/textured artwork, standalone raster text, real transparent PNG art, or complex nonlinear gradients. Photo benchmark failures are frequent; the nonlinear-gradient research candidate did not pass acceptance.
- Do not claim every successful job is visually faithful. A successful job, a valid SVG and an approved visual conversion are separate statuses.
- Use synthetic analytic fixtures only for algorithm/geometry contract regression, never to advertise real-world category coverage.

## Candidate after evidence is collected

The most plausible first category to evaluate is **clean, flat-color logo/icon artwork** because both engines pass selected synthetic geometry fixtures. It is not a currently supported category: the real icon example failed in both engines and there are no four independent real families. The candidate scope can be approved only after BETA-01 and BETA-02 pass.

## Release decision today

`BETA_RELEASE_READY = false`  
`SUPPORTED_WITH_EVIDENCE categories = 0`  
`PRODUCTION_RELEASE_READY = false`

See `supported_image_matrix.json`, `beta_blockers.json` and `beta_acceptance_gates.json` for evidence and exact open gates.
"""
    write_text("beta_scope_proposal.md", scope_proposal)

    critical_path = """# Beta critical path

1. **BETA-01 — Real evidence and human review.** Select a narrow category, collect four independent permission-cleared source families, preserve source hashes, add suitable vector/mask/text references and finish blind review. Stop if no category passes.
2. **BETA-03 — Freeze user-facing support scope.** Only after BETA-01, write exact supported/excluded claims and visible limitations. Stop if copy overstates fidelity.
3. **BETA-02 — Live WPF manual QA.** On the Release app, test import, selector, both jobs, Compare, preview, error messages, save and external reopen. Stop on any mislabeled, blank, incorrect or silently failed result.
4. **BETA-04 — Performance/resource qualification.** Measure the selected scope on target hardware; set policy from observed data. Stop/narrow if resource behavior is unacceptable.
5. **BETA-05 — Package.** Build the desktop/backend distribution, dependency/license manifest, install/uninstall and rollback; test on a clean Windows machine.
6. **BETA-06 — Freeze and sign off.** Re-run backend regression, scope benchmark, WPF checklist and package smoke against one hashed candidate; release only if all gates pass.

The chain is intentionally evidence-first. The nonlinear-gradient prototype remains rejected; this task does not open another algorithm-research branch. Six tasks are a plan, not a promise that no additional blocker will be discovered.
"""
    write_text("beta_critical_path.md", critical_path)

    write_text("svg_editability_assessment.md", f"""# SVG quality and editability assessment

## What the artifacts prove

- {svg_audit['uniqueSavedSvgFiles']} unique saved SVG files referenced by successful Task 08A/08A.1 output records were read from disk and parsed. The scanner found {svg_audit['uniqueSvgStatusCounts'].get('PASS', 0)} valid vector-only outputs and {svg_audit['uniqueSvgStatusCounts'].get('ISSUE', 0)} issues.
- The audited set has {svg_audit['embeddedRasterElementCount']} `<image>` elements, {svg_audit['embeddedRasterDataUriCount']} raster data URIs, {svg_audit['externalResourceReferenceCount']} external resource references and {svg_audit['unresolvedLocalReferenceCount']} unresolved local references.
- Two Task 08B.1.7 API smoke downloads were also parsed and contained native paths with no embedded raster.
- The successful production workflows validate dimensions/viewBox, references and browser rendering before returning success. This does not certify appearance quality.

## Editability levels

| Level | Assessment |
|---|---|
| Technically vector | **Verified** for audited outputs: SVG paths/gradients/clips, no raster image elements or data URI. |
| Individually editable elements | **Partly present, not editor-QA verified.** Paths can be selected as vector objects; region/path count varies widely. No reliable grouping/selection workflow was reviewed inside a vector editor. |
| Semantic editability | **Not established.** Path geometry does not preserve semantic names such as “fox eye” or “background.” Outlined glyphs are not editable text. |
| Practical editability | **Not tested.** No audit measured whether a typical user can conveniently recolor/move text, select logical artwork pieces or manage object layers in the intended editor. |

## Typography

The current WPF default is outlined text for shape fidelity; that is node-editable vector geometry, not semantic text. The optional editable mode is dependent on a selected/approximated font and requires live editor QA. The real text samples have no authoritative vector/glyph reference, and the standalone raster-text fixture failed in both engines. Do not state that typography is preserved exactly.

The audit validates only files produced by successful benchmark jobs; failed jobs are not represented as valid output. See `svg_quality_audit.json` for per-file paths, hashes and structural measurements.
""".replace("{svg_audit['uniqueSavedSvgFiles']}", str(svg_audit['uniqueSavedSvgFiles']))
        .replace("{svg_audit['uniqueSvgStatusCounts'].get('PASS', 0)}", str(svg_audit['uniqueSvgStatusCounts'].get('PASS', 0)))
        .replace("{svg_audit['uniqueSvgStatusCounts'].get('ISSUE', 0)}", str(svg_audit['uniqueSvgStatusCounts'].get('ISSUE', 0)))
        .replace("{svg_audit['embeddedRasterElementCount']}", str(svg_audit['embeddedRasterElementCount']))
        .replace("{svg_audit['embeddedRasterDataUriCount']}", str(svg_audit['embeddedRasterDataUriCount']))
        .replace("{svg_audit['externalResourceReferenceCount']}", str(svg_audit['externalResourceReferenceCount']))
        .replace("{svg_audit['unresolvedLocalReferenceCount']}", str(svg_audit['unresolvedLocalReferenceCount']))
    )

    before_path = ART / "production_sha256_before.json"
    before = read_json(before_path)
    after = source_hash_manifest()
    write_json("production_sha256_after.json", after)
    before_by_path = {row["path"]: row["sha256"] for row in before["files"]}
    after_by_path = {row["path"]: row["sha256"] for row in after["files"]}
    changed = [path for path in sorted(set(before_by_path) | set(after_by_path)) if before_by_path.get(path) != after_by_path.get(path)]
    try:
        status = subprocess.run(["git", "status", "--short", "--branch"], cwd=ROOT, capture_output=True, text=True, check=False).stdout
    except OSError:
        status = "NOT_AVAILABLE"
    prod_changes = {
        "schemaVersion": 1,
        "auditOnly": True,
        "productionSourceFileCountBefore": before.get("fileCount"),
        "productionSourceFileCountAfter": after.get("fileCount"),
        "changedProductionSourceFiles": changed,
        "productionUnchanged": len(changed) == 0 and before.get("fileCount") == after.get("fileCount"),
        "smartV2Unchanged": not any("vectorization_v2" in path for path in changed),
        "contourUnchanged": not any("vectorization_contour" in path or "contour_backend.py" in path or "contour_svg_composer.py" in path for path in changed),
        "apiWpfBehaviorUnchanged": not any(path.startswith("backend/mediastudio/api.py") or path.startswith("src/MediaStudio.Desktop/") for path in changed),
        "beforeManifest": "production_sha256_before.json",
        "afterManifest": "production_sha256_after.json",
        "gitStatusAtFinalization": status,
        "gitComparisonCaveat": "Repository has no commits and its files are untracked; SHA manifests are the actual production-source integrity evidence.",
        "auditHarnessFiles": ["backend/tools/task_08b_1_7/run_beta_smoke.py", "backend/tools/task_08b_1_7/build_audit_artifacts.py"],
        "productionFilesModified": False,
    }
    write_json("production_changes.json", prod_changes)

    remaining = read_json(ART / "beta_remaining_task_plan.json")
    statuses = {
        "BACKEND_RELIABILITY_EVIDENCE_VALID": "partial",
        "SVG_VECTOR_INTEGRITY_VALID": "true" if svg_audit["allUniqueSvgStructurallyValidVectorOnly"] and smoke.get("passed") else "false",
        "SUPPORTED_INPUT_SCOPE_DEFINED": "true",
        "REAL_IMAGE_COVERAGE_SUFFICIENT": "false",
        "HUMAN_VISUAL_REVIEW_COMPLETE": "false",
        "WPF_BUILD_VERIFIED": "true",
        "WPF_MANUAL_QA_COMPLETE": "false",
        "SVG_EXPORT_E2E_VERIFIED": "not_tested",
        "BETA_BLOCKERS_IDENTIFIED": "true",
        "BETA_ACCEPTANCE_GATES_DEFINED": "true",
        "BETA_TASK_BACKLOG_READY": "true",
        "SMART_V2_UNCHANGED": "true" if prod_changes["smartV2Unchanged"] else "false",
        "CONTOUR_UNCHANGED": "true" if prod_changes["contourUnchanged"] else "false",
        "FULL_REGRESSION_PASS": "true" if full_regression["status"] == "PASS" else "false",
        "TASK_08B_1_7_COMPLETE": "true",
        "BETA_RELEASE_READY": "false",
        "PRODUCTION_RELEASE_READY": "false",
    }
    release_matrix = read_json(ART / "release_readiness_matrix.json")
    release_matrix["acceptanceStatuses"] = statuses
    write_json("release_readiness_matrix.json", release_matrix)

    real_table = "\n".join([
        "| Component | Implemented | Verified | Beta blocker |",
        "|---|---:|---|---|",
        "| Smart V2 | Yes | Backend suite, actual API benchmark and smoke pass; real-class fidelity limited | Scope/evidence blocker for any quality claim |",
        "| Contour | Yes, experimental | Backend suite, actual API benchmark and smoke pass | Keep experimental; no live WPF QA |",
        "| SVG Composer | Yes | 44 unique saved benchmark SVGs and 2 current smoke outputs pass structural/vector checks | No structural blocker found in audited successes |",
        "| API | Yes | Full regression and two real job/download smoke runs pass | Some out-of-scope input failures; visible job errors |",
        "| WPF engine selector | Yes | Release build and ViewModel harness evidence | Live-window manual QA pending |",
        "| Compare Mode | Yes | Same-asset sequential routing in ViewModel harness | Live interaction and partial-failure UX pending |",
        "| SVG Export | Yes | Exact bytes verified in Task 07.1 ViewModel harness | Live save/reopen E2E and packaging pending |",
    ])
    matrix_rows = []
    for row in category_definitions:
        cov = row["datasetCoverage"]
        matrix_rows.append(f"| {row['label']} | {cov['scopeMatchedRealFamilyCount']} matched ({cov['formalSyntheticFixtureFamilyCount']} synthetic) | {row['status']} | {row['reason']} |")
    category_table = "\n".join([
        "| Image category | Independent real families (synthetic fixtures) | Beta status | Evidence reading |",
        "|---|---:|---|---|",
        *matrix_rows,
    ])
    blocker_lines = "\n".join(f"- **{row['issueId']} · {row['severity']}** — {row['description']} Smallest fix: {row['smallestRecommendedFix']}" for row in beta_blockers)
    task_lines = "\n".join(f"{index}. **{task['taskId']} — {task['title']}** — {task['objective']} Acceptance: {'; '.join(task['acceptanceCriteria'])} Stop: {task['stopCondition']}" for index, task in enumerate(plan, start=1))
    report = f"""# MEDIASTUDIO — TASK 08B.1.7
# BETA READINESS AUDIT & SUPPORTED IMAGE CLASSIFICATION

**Audit date:** {datetime.now(timezone.utc).date().isoformat()}  
**Scope:** Audit only. No production algorithm/API/WPF behavior changed; no Beta packaged or released.  
**Decision:** `BETA_RELEASE_READY = false`; `PRODUCTION_RELEASE_READY = false`.

## Executive finding

The repository has a production Smart Reconstruction V2 engine, an experimental Contour-Preserving engine, an asynchronous API, WPF engine selection/Compare/preview/save code, and working vector-only SVG output on selected fixtures. Automated reliability evidence is positive: **378 tests + 360 subtests pass**, the WPF Release build passes, two current API smoke jobs pass, and audited successful benchmark SVGs are structurally valid with no embedded raster.

That is not enough to call this a usable image-fidelity Beta. The formal Task 08A.1 dataset has **29 variants, 10 independent real source families and 18 synthetic fixture families**. ACTIVE FOX at 554 px and 4432 px is one family. All review scores are absent; no real source family has its original SVG reference. The tested photo group often fails, and the evaluated nonlinear-gradient quality gates remain unmet. **No category currently qualifies as `SUPPORTED_WITH_EVIDENCE`.**

## A. System status

{real_table}

### Repository and integration details

- Backend entry points: `backend/mediastudio/api.py`, `backend/mediastudio/image_tools/vectorize.py`, `backend/mediastudio/image_tools/vectorization_v2/production.py`, `backend/mediastudio/image_tools/contour_backend.py`.
- Smart V2 is the default from `MEDIASTUDIO_VECTORIZE_PIPELINE=v2`; Contour requires an explicit vector method, `MEDIASTUDIO_CONTOUR_EXPERIMENTAL=1` and pinned `scikit-image==0.26.0`.
- API upload/job/status/result endpoints and structured failures are present. JobManager has one worker and there is no cancellation route.
- WPF uses `VectorizeToolView.xaml`, `VectorizeToolViewModel.cs`, `VectorizationJobService.cs` and `MediaStudioApiClient.cs`. Compare runs both methods sequentially on one asset ID.
- Release WPF build: **PASS**, .NET SDK 10.0.401, 0 warnings and 0 errors. Manual live-window QA: **NOT_TESTED**. Task 07.1 exact-byte ViewModel save and preview harness is not a live window screenshot or end-to-end app run.
- Package/installer/clean-machine install: **NOT_TESTED**; backend README says bundling, installer/self-contained setup, dependencies and license notices remain.

See `repository_feature_inventory.json` and `integration_evidence_matrix.json`.

## B. Dataset coverage and real-image evidence

Task 08A.1 manifest checks: **10 real source families, 11 real variants, 18 synthetic families/variants, 29 total variants**. Eight of the real families are named photo samples in this manifest; the remaining two are ACTIVE FOX and a raster-text sample. The exact category counts are in `dataset_coverage_matrix.json`.

- The review manifest covers 29 images and 160 ROIs, but `human_review_results.csv` has only its header; `humanReviewComplete=false`.
- Real source vectors are absent. Synthetic fixtures include analytic masks/vector references but cannot count toward real-world support.
- The 08A.1 photo outcomes were 2/7 Smart jobs and 3/7 Contour jobs succeeded. `camera` failed Smart with a GEOS topology exception; `chelsea`, `clock`, `coffee`, and `eagle` failed visible-output checks in one or both engines.
- Horse alpha icon and standalone raster text failed in both engines in that run. Successful SVGs are not proof that the associated artwork was visually approved.

## C. Supported image classification

{category_table}

Definitions are evidence-level-specific: a job can succeed, its SVG can be structurally valid, the SVG can render visibly, geometry/color/detail can be accurate, and a human can approve its fidelity. These are distinct checks. Matrix status is not inferred from job success alone.

The most defensible next evaluation candidate is clean flat-color logo/icon artwork, but it is **not supported yet**: synthetic shapes pass, while the only real icon sample failed and there are not four representative independent real families. The first Beta must not claim general raster-to-vector fidelity.

See `supported_image_matrix.json`, `engine_capability_matrix.json`, `known_limitations.json` and `missing_beta_evidence.json`.

## D. Smart V2 versus Contour

- **Smart Reconstruction V2:** remains the production default. Evidence includes synthetic flat geometry and a targeted synthetic radial-gradient repair. Its production output on the smooth nonlinear-gradient primary fixture has **1.5741% false-edge fraction, mean ΔE00 4.3173 and P95 8.9644**. On 11 real benchmark variants, 4 jobs succeeded.
- **Contour-Preserving:** remains experimental. It has exact shared-boundary/topology checks and stronger silhouette measurements on selected fixtures, but it is not a universal visual-quality winner. On the same 11 real benchmark variants, 5 jobs succeeded; it differs from Smart in failures and tradeoffs and has higher observed memory on some runs.
- Both engines succeeded on 4/11 variants. No engine wins every metric. Use Contour only for local comparative experiments on selected clean artwork and keep its experimental label. Do not promote it based only on synthetic silhouette scores.
- The coordinate-consistent multi-directional gradient research candidate remains `CASE_B`; its fitting/SVG coordinates agree but its primary mean/P95/false-edge and held-out gates fail. It was not integrated. This task adds no algorithm research.

Task 08B.1.2’s radial improvement is limited evidence: on the synthetic radial fixture the ROI mean ΔE00 changed **1.7865 → 0.5905** and P95 **5.6706 → 1.1655**; held-out radial synthetic cases passed. This is not evidence for a broad real logo class.

## E. SVG quality and editability

The audit parsed **{svg_audit['uniqueSavedSvgFiles']} unique saved SVG files** referenced by successful Task 08A/08A.1 results. **{svg_audit['uniqueSvgStatusCounts'].get('PASS', 0)} passed** XML/root/dimensions/viewBox/ID/local-reference checks, with no embedded raster, external resources or unresolved local references. Two Task 08B.1.7 API smoke outputs also passed XML/path/vector-only checks.

These are technically vector outputs and can be edited as paths. This does not prove practical editability, semantic object grouping or editable text. Outlined glyphs are paths, not editable text. `svg_editability_assessment.md` describes each level separately.

## F. Beta blockers and risks

{blocker_lines}

Research limitations are not automatically release blockers if the affected categories are excluded and the limitations are visible. The evaluated nonlinear gradient model remains rejected; photos/text and real alpha icons have named failed examples. Runtime is variable: measured real-set jobs take minutes in some cases and sampled memory reaches several GB; no target-hardware service limits have been qualified.

## G. Beta acceptance gates

1. **Backend reliability — PASS_WITH_SCOPE_LIMITS:** full regression passes and two API smoke jobs succeed. Known failed inputs appear as job failures, not successful blank SVGs.
2. **SVG integrity — PASS_FOR_AUDITED_OUTPUTS:** current smoke and 44 unique saved benchmark outputs are structurally vector-only.
3. **Supported scope — FAIL:** no artwork category currently meets the real-family/human-review evidence gate.
4. **Visual fidelity — FAIL:** human review is pending, no real source vectors exist, and nonlinear-gradient research fails.
5. **Desktop integration — PARTIAL:** WPF build and ViewModel harness pass; live GUI QA and user-facing export E2E are untested.
6. **Performance/resource safety — PARTIAL:** metrics exist on selected inputs, but target-machine limits and supported-scope qualification do not.
7. **Release packaging — NOT_TESTED:** installer/package, dependency/license manifest, clean install and rollback are open.

See `beta_acceptance_gates.json` and `release_readiness_matrix.json`.

## H. Validation executed

- Full Python regression: **378 passed, 24 warnings, 360 subtests passed** in 210.55 s; 0 failed/errors/skips.
- WPF Release build: **PASS**, 0 warnings, 0 errors.
- API smoke: Smart V2 on `low_contrast_multistop_gradient` and Contour on `hard_boundary_with_gradient`; both uploads/jobs/downloads succeeded; both SVGs parsed and had no embedded raster.
- Historical Task 08A/08A.1 artifacts reused: 29-image manifest, 11 actual real-image variants, SVG validation and engine outcomes; no repeated large image sweep was run.
- Manual WPF interaction and package validation: **NOT_TESTED**; see `manual_desktop_qa_checklist.md`.

Full details: `full_regression.json`, `beta_smoke_test_results.json`, `desktop_validation_status.json`, `svg_quality_audit.json`.

## I. Remaining work, dependency order

{task_lines}

The six-task list is a proposed minimum, not a guarantee that no new blocker will be found. See `beta_remaining_task_plan.json` and `beta_critical_path.md`. No task beyond 08B.1.7 was started.

## Acceptance statuses

```text
BACKEND_RELIABILITY_EVIDENCE_VALID = partial
SVG_VECTOR_INTEGRITY_VALID = {statuses['SVG_VECTOR_INTEGRITY_VALID']}
SUPPORTED_INPUT_SCOPE_DEFINED = {statuses['SUPPORTED_INPUT_SCOPE_DEFINED']}
REAL_IMAGE_COVERAGE_SUFFICIENT = {statuses['REAL_IMAGE_COVERAGE_SUFFICIENT']}
HUMAN_VISUAL_REVIEW_COMPLETE = {statuses['HUMAN_VISUAL_REVIEW_COMPLETE']}
WPF_BUILD_VERIFIED = {statuses['WPF_BUILD_VERIFIED']}
WPF_MANUAL_QA_COMPLETE = {statuses['WPF_MANUAL_QA_COMPLETE']}
SVG_EXPORT_E2E_VERIFIED = {statuses['SVG_EXPORT_E2E_VERIFIED']}
BETA_BLOCKERS_IDENTIFIED = {statuses['BETA_BLOCKERS_IDENTIFIED']}
BETA_ACCEPTANCE_GATES_DEFINED = {statuses['BETA_ACCEPTANCE_GATES_DEFINED']}
BETA_TASK_BACKLOG_READY = {statuses['BETA_TASK_BACKLOG_READY']}
SMART_V2_UNCHANGED = {statuses['SMART_V2_UNCHANGED']}
CONTOUR_UNCHANGED = {statuses['CONTOUR_UNCHANGED']}
FULL_REGRESSION_PASS = {statuses['FULL_REGRESSION_PASS']}
TASK_08B_1_7_COMPLETE = {statuses['TASK_08B_1_7_COMPLETE']}
BETA_RELEASE_READY = {statuses['BETA_RELEASE_READY']}
PRODUCTION_RELEASE_READY = {statuses['PRODUCTION_RELEASE_READY']}
```

Production-source integrity: `production_changes.json`; before/after SHA-256 manifests: `production_sha256_before.json`, `production_sha256_after.json`.

**STOP after Task 08B.1.7. No Beta packaging or algorithm implementation was started.**
"""
    write_text("task_08b_1_7_report.md", report)
    write_json("acceptance_status.json", {
        "task": "08B.1.7",
        "statuses": statuses,
        "betaReleaseReady": False,
        "productionReleaseReady": False,
        "productionUnchanged": prod_changes["productionUnchanged"],
        "taskComplete": True,
        "stopCondition": "STOPPED_AFTER_TASK_08B_1_7; no Task 08B.1.8 and no Beta release action",
        "evidenceFiles": ["task_08b_1_7_report.md", "release_readiness_matrix.json", "production_changes.json"],
    })
    print(json.dumps({
        "task": "08B.1.7",
        "outputDirectory": str(ART),
        "realFamilies": len(real_families),
        "realVariants": len(real_items),
        "syntheticVariants": len(synthetic_items),
        "svgUniqueFiles": svg_audit["uniqueSavedSvgFiles"],
        "svgStatusCounts": svg_audit["uniqueSvgStatusCounts"],
        "fullRegression": full_regression["summary"],
        "smokePassed": smoke.get("passed"),
        "productionUnchanged": prod_changes["productionUnchanged"],
        "categoryStatusCount": len(category_definitions),
        "supportedWithEvidence": sum(row["status"] == "SUPPORTED_WITH_EVIDENCE" for row in category_definitions),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
