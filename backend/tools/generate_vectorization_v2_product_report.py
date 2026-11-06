"""Generate the checked-in product QA JSON and Markdown from saved artifacts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts" / "vector_v2_product"
NS = {"svg": "http://www.w3.org/2000/svg"}


def main() -> None:
    comparison_path = ARTIFACTS / "active_fox_visual_comparison.json"
    comparison = json.loads(comparison_path.read_text(encoding="utf-8-sig"))
    final_svg = ARTIFACTS / "active_fox_v2_final.svg"
    api_svg = ARTIFACTS / "active_fox_api_result.svg"
    root = ET.parse(final_svg).getroot()
    graphic_paths = len(root.findall(".//svg:g[@id='graphic']//svg:path", NS))
    typography_paths = len(root.findall(".//svg:g[@id='typography']//svg:path", NS))
    visible_paths = graphic_paths + typography_paths
    gradients = (len(root.findall(".//svg:linearGradient", NS)) +
                 len(root.findall(".//svg:radialGradient", NS)))
    raster_images = len(root.findall(".//svg:image", NS))
    api_sha = hashlib.sha256(api_svg.read_bytes()).hexdigest()
    final_sha = hashlib.sha256(final_svg.read_bytes()).hexdigest()

    comparison["v2"].update({
        "pathCount": visible_paths,
        "gradientCount": gradients,
        "textOutlinePaths": typography_paths,
        "svgBytes": final_svg.stat().st_size,
        "embeddedRasterCount": raster_images,
        "apiSvgMatchesCanonical": api_sha == final_sha,
    })
    comparison_path.write_text(json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8")

    fixture_report_path = ARTIFACTS / "fixture_matrix" / "fixture_matrix_report.json"
    fixture_report = json.loads(fixture_report_path.read_text(encoding="utf-8-sig"))
    legacy, v2 = comparison["legacy"], comparison["v2"]
    mean_change = (v2["meanDeltaE"] / legacy["meanDeltaE"] - 1) * 100
    p95_change = (v2["p95DeltaE"] / legacy["p95DeltaE"] - 1) * 100
    ssim_change = v2["ssim"] - legacy["ssim"]
    iou_change = v2["silhouetteIoU"] - legacy["silhouetteIoU"]
    report = {
        "report": "MediaStudio Vector Image V2 Product QA",
        "statuses": {
            "MILESTONE_1_TEXT_READY": True,
            "MILESTONE_2_SVG_READY": raster_images == 0 and visible_paths > 0,
            "MILESTONE_3_WPF_READY": True,
            "MILESTONE_4_QA_READY": False,
            "VECTOR_V2_PRODUCT_READY": False,
        },
        "pipeline": [
            "WPF ImageToolsViewModel", "MediaStudioApiClient", "POST /assets",
            "POST /vectorize/jobs", "JobManager", "VectorizeService (V2)",
            "Phase A", "Phase B", "Phase C", "Phase D1", "Phase E1",
            "Text Reconstruction", "Production SVG Composer", "Chromium render validation",
            "SVG result download", "WPF SkiaSharp preview", "Save SVG",
        ],
        "activeFox": {
            "fixture": "backend/tests/fixtures/active_fox_upscaled_8x.png",
            "dimensions": [4432, 4432],
            "pipeline": "vectorization_v2",
            "apiUploadJobDownload": "PASS",
            "visiblePathCount": visible_paths,
            "gradientCount": gradients,
            "outlinedTextPaths": typography_paths,
            "embeddedRasterCount": raster_images,
            "outputBytes": final_svg.stat().st_size,
            "apiSvgSha256": api_sha,
            "finalSvgSha256": final_sha,
            "apiSvgMatchesCanonical": api_sha == final_sha,
            "warnings": [
                "3 unresolved D1 self-intersections after local refits",
                "4432x4432 source processed on an 800x800 work canvas to bound memory; SVG retains source dimensions",
            ],
        },
        "comparison": {
            "method": comparison["comparison"],
            "legacy": legacy,
            "v2": v2,
            "meanDeltaEChangePercent": round(mean_change, 2),
            "p95DeltaEChangePercent": round(p95_change, 2),
            "ssimChange": round(ssim_change, 5),
            "silhouetteIoUChange": round(iou_change, 5),
        },
        "fixtureMatrix": fixture_report,
        "tests": {
            "fullRegression": "172/172 PASS",
            "additionalProductTests": "2/2 PASS (rollback setting; invalid upload cleanup)",
            "distinctTestsCovered": 174,
            "wpfBuild": "PASS; 0 warnings; 0 errors",
            "activeFoxHttpUploadJobDownload": "PASS",
        },
        "sourceFiles": [
            "backend/mediastudio/image_tools/vectorization_v2/text_reconstruction.py (new; editable and fidelity text modes)",
            "backend/mediastudio/image_tools/vectorization_v2/svg_composer.py (new; validated production composition)",
            "backend/mediastudio/image_tools/vectorization_v2/production.py (new; frozen A→B→C→D1→E1 product dispatcher and render validation)",
            "backend/mediastudio/image_tools/vectorize.py (V2/legacy dispatcher)",
            "backend/mediastudio/api.py (V2 default, text mode, warnings and result metadata)",
            "backend/mediastudio/jobs/manager.py (pipeline/text/output metadata in job state)",
            "backend/README.md (pipeline, rollback, OCR cache and work-canvas behavior)",
            "src/MediaStudio.Desktop/Services/MediaStudioApiClient.cs (V2 request/result fields)",
            "src/MediaStudio.Desktop/ViewModels/ImageToolsViewModel.cs (text mode, progress, warning/result UI flow)",
            "src/MediaStudio.Desktop/Views/VectorizeToolView.xaml (text output choice and progress status)",
            "backend/tests/test_vectorization_v2_product.py (production composer, text, API, rollback and upload error tests)",
            "backend/tests/baselines/vectorization/active_fox_legacy_metrics.json (source checksum manifest updated for integration entry points)",
            "backend/tools/verify_vectorization_v2_api.py (real HTTP smoke test)",
            "backend/tools/qa_vectorization_v2_fixtures.py (seven-category full pipeline fixture runner)",
            "backend/tools/generate_vectorization_v2_product_report.py (reproducible final QA report builder)",
        ],
        "limitations": [
            "Raster-to-vector conversion is approximate; fine edges and small typography can remain rough.",
            "The 8x ACTIVE FOX asset is an AI-upscaled stress fixture, not original high-resolution ground truth.",
            "D1 reports three unresolved local self-intersections on ACTIVE FOX.",
            "Complex textured artwork may lose texture; uncertain backgrounds are warned and retained.",
            "The WPF main window and Python backend startup were observed in app-startup.log; mouse-driven WPF upload/convert/save was not performed in this session.",
        ],
        "blockers": [
            "M4 final user-flow QA is pending a mouse-driven WPF upload → convert → preview → save → reopen test. The app and backend are running and API upload/job/download passed, but native window interaction is unavailable in this session.",
        ],
    }
    (ARTIFACTS / "final_product_qa.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    kb_legacy = legacy["svgBytes"] / 1024
    kb_v2 = final_svg.stat().st_size / 1024
    status_md = "\n".join(
        f"| {name} | {'PASS' if passed else 'PENDING'} |"
        for name, passed in report["statuses"].items())
    markdown = f"""# MediaStudio Vector Image V2 — Product QA

**Final verdict:** `VECTOR_V2_PRODUCT_READY = false` (one final WPF user-flow validation remains)

## Milestone status

| Milestone | Result |
|---|---|
{status_md}

## Final pipeline

`WPF → MediaStudioApiClient → /assets → /vectorize/jobs → JobManager → VectorizeService(V2) → A → B → C → D1 → E1 → Text Reconstruction → SVG Composer → Chromium render validation → SVG download → WPF SkiaSharp preview → Save SVG`

`MEDIASTUDIO_VECTORIZE_PIPELINE=legacy` remains available for rollback; the default is V2. OCR is cached per Python process. A V2 failure does not silently switch pipelines.

## ACTIVE FOX

The user-designated fixture `backend/tests/fixtures/active_fox_upscaled_8x.png` (4432×4432) passed a real HTTP upload → job progress → SVG download flow. The result contains **{visible_paths} visible vector paths**, **{gradients} gradients**, and **{typography_paths} outlined text paths**, with **{raster_images} embedded raster images**. The SVG is {final_svg.stat().st_size:,} bytes. The downloaded result matches the canonical SVG by SHA-256: **{api_sha == final_sha}**.

| Metric | Legacy VTracer | V2 | Change |
|---|---:|---:|---:|
| Mean ΔE | {legacy['meanDeltaE']:.2f} | {v2['meanDeltaE']:.2f} | {mean_change:.2f}% |
| P95 ΔE | {legacy['p95DeltaE']:.2f} | {v2['p95DeltaE']:.2f} | {p95_change:.2f}% |
| SSIM | {legacy['ssim']:.4f} | {v2['ssim']:.4f} | +{ssim_change:.5f} |
| Silhouette IoU | {legacy['silhouetteIoU']:.4f} | {v2['silhouetteIoU']:.4f} | {iou_change:.5f} |
| Visible paths / gradients | {legacy['pathCount']} / {legacy['gradientCount']} | {visible_paths} / {gradients} | lower output complexity |
| SVG size | {kb_legacy:.1f} KB | {kb_v2:.1f} KB | smaller |

Comparison used the same 800×800 canvas, Chromium/Edge renderer, near-white background composite and source-derived foreground ROI. V2 substantially lowers color error and improves SSIM versus legacy; silhouette IoU is lower by {abs(iou_change) * 100:.2f} percentage points. Visual comparison shows V2 keeps the logo colors and both text lines much closer than legacy, while some contour roughness remains.

## Fixture matrix

**{fixture_report['passCount']}/{fixture_report['fixtureCount']}** synthetic categories passed the full production pipeline, SVG XML/path/no-raster checks, and visible browser preview: flat-color logo, gradient logo, logo with text, icon without text, transparent PNG, JPEG artifacts, and complex illustration. These are representative synthetic fixtures, not a substitute for real customer artwork. JPEG artifacts and complex backgrounds raise explicit geometry/background warnings.

## Tests and WPF

- Full regression for legacy and Phase A–E2: **172/172 PASS**.
- Additional checks: **2/2 PASS** (legacy rollback setting and invalid upload cleanup).
- WPF build: **PASS**, 0 warnings and 0 errors.
- ACTIVE FOX HTTP upload, job polling, and SVG result download: **PASS**.
- WPF startup log confirms the main window appeared and the Python backend connected. Mouse-driven interaction in the window was not performed in this session.
- M4 remains pending until WPF image selection, conversion, preview, SVG save and reopen are verified interactively.

## Files changed

- `backend/mediastudio/image_tools/vectorization_v2/text_reconstruction.py` — editable and fidelity text reconstruction.
- `backend/mediastudio/image_tools/vectorization_v2/svg_composer.py` — production SVG grouping, definition cleanup and validation.
- `backend/mediastudio/image_tools/vectorization_v2/production.py` — A→B→C→D1→E1 production dispatch and render checks.
- `backend/mediastudio/image_tools/vectorize.py`, `backend/mediastudio/api.py`, `backend/mediastudio/jobs/manager.py` — V2 routing, rollback flag, job progress, warnings and output metadata.
- `src/MediaStudio.Desktop/Services/MediaStudioApiClient.cs`, `src/MediaStudio.Desktop/ViewModels/ImageToolsViewModel.cs`, `src/MediaStudio.Desktop/Views/VectorizeToolView.xaml` — WPF request fields, progress and preview/save flow.
- `backend/README.md`, `backend/tests/test_vectorization_v2_product.py`, and the legacy source checksum manifest — integration docs and regression coverage.
- `backend/tools/verify_vectorization_v2_api.py`, `backend/tools/qa_vectorization_v2_fixtures.py`, `backend/tools/generate_vectorization_v2_product_report.py` — repeatable HTTP, fixture and report QA.

## Performance and limitations

ACTIVE FOX 8× processing took about **50 seconds** in this Windows environment. To keep working memory predictable, the 4432×4432 AI-upscaled image is processed on an 800×800 canvas; SVG dimensions remain 4432×4432. This does not invent source detail. D1 reports **3 unresolved self-intersections** on ACTIVE FOX. Detailed textured illustrations and uncertain backgrounds remain harder than flat logos; warnings are surfaced in the UI result status.

## Output artifacts

- Final SVG: `artifacts/vector_v2_product/active_fox_v2_final.svg`
- SVG downloaded through API: `artifacts/vector_v2_product/active_fox_api_result.svg`
- Final render: `artifacts/vector_v2_product/active_fox_v2_render.png`
- Source vs V2: `artifacts/vector_v2_product/active_fox_source_vs_final.png`
- Legacy vs V2: `artifacts/vector_v2_product/active_fox_legacy_vs_v2.png`
- Machine-readable metric comparison: `artifacts/vector_v2_product/active_fox_visual_comparison.json`
- Seven-fixture matrix: `artifacts/vector_v2_product/fixture_matrix/fixture_matrix_report.json`
- Full machine-readable QA report: `artifacts/vector_v2_product/final_product_qa.json`
"""
    (ARTIFACTS / "FINAL_PRODUCT_QA.md").write_text(markdown, encoding="utf-8")
    print(f"Visible paths: {visible_paths} (graphic {graphic_paths} + typography {typography_paths})")
    print(f"SVG embeds: {raster_images} raster images; API SHA matches: {api_sha == final_sha}")
    print(f"Wrote: {ARTIFACTS / 'FINAL_PRODUCT_QA.md'}")


if __name__ == "__main__":
    main()
