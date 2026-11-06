from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

BACKEND = Path(__file__).resolve().parents[2]
ARTIFACTS = BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_3"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def junit_summary(path: Path) -> dict:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    total = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    total_time = 0.0
    for suite in suites:
        for key in total:
            total[key] += int(suite.attrib.get(key, 0))
        total_time += float(suite.attrib.get("time", 0.0))
    total["passed"] = total["tests"] - total["failures"] - total["errors"] - total["skipped"]
    total["durationSeconds"] = round(total_time, 3)
    total["junitPath"] = path.relative_to(ARTIFACTS).as_posix()
    return total


def main() -> None:
    fixture = load(ARTIFACTS / "analytic_gradient_fixtures.json")
    matrix = load(ARTIFACTS / "gradient_banding_matrix.json")
    analysis = load(ARTIFACTS / "false_edge_analysis.json")
    stages = load(ARTIFACTS / "first_failing_stage.json")
    api = load(ARTIFACTS / "api_runs.json")
    controls = load(ARTIFACTS / "false_edge_detector_controls.json")

    old_root = BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_1"
    old_soft = load(old_root / "soft_gradient_analysis.json")
    old_defects = load(old_root / "top_three_defects.json")
    proxy_row = next(row for row in old_defects["defects"]
                     if row.get("fixture") == "active-fox-native-jpeg" and
                     row.get("engine") == "contour_preserving")
    proxy_metrics = old_soft["fixtures"]["active-fox-native-jpeg"]["engines"]["contour_preserving"]
    proxy_smart = old_soft["fixtures"]["active-fox-native-jpeg"]["engines"]["smart_reconstruction"]
    smooth_contour = analysis["fixtures"]["smooth_nonlinear_gradient"]["engines"]["contour_preserving"]
    smooth_smart = analysis["fixtures"]["smooth_nonlinear_gradient"]["engines"]["smart_reconstruction"]
    low_contour = analysis["fixtures"]["low_contrast_multistop_gradient"]["engines"]["contour_preserving"]
    hard_contour = analysis["fixtures"]["hard_boundary_with_gradient"]["engines"]["contour_preserving"]

    proxy_comparison = {
        "status": "PROXY_ONLY",
        "source": "Task 08B.1.1 native ACTIVE FOX JPEG and annotated tail/body ROI",
        "roi": {"annotation": "tail_body_gradient_roi_xyxy", "pixels": 5040,
                "humanReview": "NEEDS_HUMAN_REVIEW"},
        "task08b1_1ContourProxy": {
            "falseEdgePixels": proxy_metrics["falseHardEdgePixels"],
            "falseEdgeFraction": proxy_metrics["falseHardEdgeFraction"],
            "falseEdgePercent": 100 * proxy_metrics["falseHardEdgeFraction"],
            "meanDeltaE00": proxy_metrics["meanDeltaE00"],
            "p95DeltaE00": proxy_metrics["p95DeltaE00"],
            "segmentationRegionsWholeImage": proxy_row["intermediateEvidence"]["regionCount"],
            "segmentationBoundariesInsideROI": proxy_row["intermediateEvidence"]["gradientInternalBoundaryPixels"],
            "segmentationRegionsInsideROI": proxy_metrics["segmentationRegionCount"],
            "falseEdgeNearSegmentationFraction": 0.9362,
            "previousClassification": proxy_row["defect"],
            "previousConfidence": proxy_row["confidence"],
            "basis": proxy_row["evidenceClassification"],
        },
        "analyticFindings": {
            "smoothNonlinearContour": {
                "falseEdgePercent": 100 * smooth_contour["gradientMetrics"]["falseHardEdgeFraction"],
                "softRoiRegions": smooth_contour["segmentation"]["uniqueRegionCountInSoftROI"],
                "segmentationInternalBoundaryPixelsInSoftRoi": smooth_contour["segmentation"]["internalBoundaryPixelCountInSoftROI"],
                "falseEdgeNearSegmentationFraction": smooth_contour["boundaryStageComparison"]["falseVisualEdgeNearSegmentationFraction"],
                "falseEdgeOverlapWithAppearanceFeaturePaths": smooth_contour["boundaryStageComparison"]["falseVisualEdgeOverlapWithInternalAppearanceFeatures"],
                "appearanceToProductionFalseEdgeMaskIoU": smooth_contour["appearanceDiagnosticVsProductionRender"]["falseEdgeMaskIoU"],
            },
            "smoothNonlinearSmart": {
                "falseEdgePercent": 100 * smooth_smart["gradientMetrics"]["falseHardEdgeFraction"],
                "softRoiRegions": smooth_smart["segmentation"]["uniqueRegionCountInSoftROI"],
                "segmentationInternalBoundaryPixelsInSoftRoi": smooth_smart["segmentation"]["internalBoundaryPixelCountInSoftROI"],
                "appearanceToProductionFalseEdgeMaskIoU": smooth_smart["appearanceDiagnosticVsProductionRender"]["falseEdgeMaskIoU"],
            },
            "lowContrastContourFalseEdgePercent": 100 * low_contour["gradientMetrics"]["falseHardEdgeFraction"],
            "hardBoundaryContourSegmentationF1At2px": hard_contour["boundaryStageComparison"]["segmentationVsGroundTruth"]["f1WithinTolerance"],
        },
        "similarity": "Both the ACTIVE FOX proxy and the analytic nonlinear fixture show excess final edge response inside annotated/synthetic soft-gradient areas.",
        "difference": "The analytic Contour case has one segmentation region in its soft ROI and no internal segmentation boundary; 98.17% of false-edge pixels align with fitted internal appearance-feature paths. ACTIVE FOX's 08B.1.1 proxy has eight regions in the ROI and 93.62% of false edges near segmentation boundaries.",
        "limit": "This controlled reproduction proves a related failure mode exists in Contour appearance on a smooth gradient. It does not prove that every ACTIVE FOX boundary is semantically false or that its exact causal stage is the same. Human review remains required.",
    }
    save(ARTIFACTS / "active_fox_proxy_comparison.json", proxy_comparison)

    full_backend_junit = junit_summary(ARTIFACTS / "full_regression_junit.xml")
    full_backend_junit["junitCasesIncludingSubtests"] = full_backend_junit["tests"]
    full_backend_junit["junitSuccessfulEntries"] = full_backend_junit["passed"]
    full_backend_junit["pytestReportedPassedTestCases"] = 339
    full_backend_junit["pytestReportedPassedSubtests"] = 360
    full_backend_junit["pytestWarnings"] = 24
    full_backend_junit["passed"] = 339
    radial_junit = junit_summary(ARTIFACTS / "task_08b_1_2_radial_regression.xml")
    radial_junit["junitCasesIncludingSubtests"] = radial_junit["tests"]
    radial_junit["junitSuccessfulEntries"] = radial_junit["passed"]
    radial_junit["pytestReportedPassedTestCases"] = 3
    radial_junit["pytestReportedPassedSubtests"] = 3
    radial_junit["passed"] = 3
    full_regression = {
        "task": "08B.1.3",
        "fullBackend": full_backend_junit,
        "task08b1_2RadialRegression": radial_junit,
        "task08b1_3DiagnosticTests": junit_summary(ARTIFACTS / "task_08b_1_3_diagnostic_tests.xml"),
        "controlledApiRun": {"fixtures": len(api["results"]),
                             "engineRuns": sum(len(row.get("engines", {})) for row in api["results"]),
                             "allPass": api["allPass"]},
        "detectorControlsPass": controls["pass"],
        "coordinateAlignmentPass": matrix["nativeCoordinateAlignmentPass"],
    }
    full_regression["pass"] = all(
        block["failures"] == 0 and block["errors"] == 0 and block["skipped"] == 0
        for block in (full_regression["fullBackend"], full_regression["task08b1_2RadialRegression"],
                      full_regression["task08b1_3DiagnosticTests"])
    ) and api["allPass"] and controls["pass"] and matrix["nativeCoordinateAlignmentPass"]
    full_regression["pytestOutputSummary"] = "339 passed, 24 warnings, 360 subtests passed in 224.81s"
    save(ARTIFACTS / "full_regression.json", full_regression)

    scope = load(ARTIFACTS / "production_changes.json")
    flags = {
        "CONTROLLED_FIXTURES_VALID": bool(fixture["allValid"]),
        "CONTOUR_FALSE_BOUNDARY_REPRODUCED": bool(stages["results"] and any(
            row["engine"] == "contour_preserving" and row["visualThresholdExceeded"]
            for row in stages["results"])),
        "FIRST_FAILING_STAGE_VERIFIED": stages["firstFailingStageVerified"],
        "SEGMENTATION_CAUSALITY_PROVEN": stages["segmentationCausalityProven"],
        "APPEARANCE_CAUSALITY_PROVEN": stages["appearanceCausalityProven"],
        "GRADIENT_METRICS_VALID": bool(controls["pass"] and matrix["nativeCoordinateAlignmentPass"]),
        "ACTIVE_FOX_PROXY_ONLY": proxy_comparison["status"] == "PROXY_ONLY",
        "SMART_V2_UNCHANGED": bool(scope["productionScopeUnchanged"]),
        "CONTOUR_UNCHANGED": bool(scope["productionScopeUnchanged"]),
        "FULL_REGRESSION_PASS": bool(full_regression["pass"]),
        "TASK_08B_1_3_COMPLETE": bool(full_regression["pass"] and fixture["allValid"] and api["allPass"]),
        "TASK_08B_1_4_READY_FOR_TARGETED_REPAIR": bool(stages["firstFailingStageVerified"] == "true" and stages["appearanceCausalityProven"]),
        "PRODUCTION_RELEASE_READY": False,
    }
    save(ARTIFACTS / "acceptance_status.json", flags)

    table_rows = []
    for row in matrix["rows"]:
        table_rows.append(f"| `{row['fixture']}` | `{row['engine']}` | {row['falseEdgeFractionPercent']:.4f}% | {row['fragmentation']} | `{row['firstFailingStage']}` | `{row['confidence']}` |")
    report = f"""# MediaStudio Task 08B.1.3 — Controlled Gradient Banding Reproduction

## Kết luận

Task này chỉ chẩn đoán. Không có thuật toán production nào bị sửa. Controlled fixtures đã tái hiện false hard edges trong `smooth_nonlinear_gradient` ở cả hai engine. Với Contour-Preserving, lỗi bắt đầu ở appearance reconstruction: segmentation có một region trong soft-gradient ROI và không có biên segmentation nội bộ; appearance diagnostic tạo false-edge fraction 1.5741%, trùng mặt nạ false-edge của SVG production với IoU 1.0000. 98.17% false-edge pixels nằm sát bốn internal-appearance-feature paths. Base paint-only prediction có 0% false edge. Vì vậy đây không phải segmentation split hay SVG-composition seam.

Smart V2 cũng vượt ngưỡng ở cùng fixture (1.5750%); Phase E1 model prediction đã có 1.4048% false edges và mặt nạ false edges trùng final SVG với IoU 0.7756. Đây cũng là lỗi appearance/gradient fit. Hai fixture còn lại không vượt ngưỡng 1%.

## Fixture và phương pháp

- Ba source families cố định, mỗi ảnh 512×512, seed 81313, 4× analytic supersampling rồi Lanczos downsample. Masks, formulas, hashes và validation ở [analytic_gradient_fixtures.json](analytic_gradient_fixtures.json).
- `smooth_nonlinear_gradient`: circle, radial-angular nonlinear continuous color field, không có internal hard boundary.
- `hard_boundary_with_gradient`: ellipse chia đúng hai vùng theo `x=256`; mỗi phía có gradient phi tuyến riêng. Soft ROI loại trừ 16 px quanh biên thật.
- `low_contrast_multistop_gradient`: ellipse với bốn color knots, tương phản cục bộ thấp, không có internal hard boundary.
- Không tạo JPEG variant vì câu hỏi chính là tái hiện trên analytic source; compression không cần thiết cho kết luận này.
- False-edge response dùng CIE76 Euclidean distance trong CIELAB trên cặp pixel liền kề: response ≥3 và lớn hơn source ×2.5 +0.75. False-edge fraction được báo từ 1%. Mọi color-fidelity errors dùng CIEDE2000 (ΔE00), tách biệt với CIE76.
- Hard-boundary precision/recall dùng Task 08B.1.1 distance-transform metric với tolerance 2 px. Segmentation fragmentation, geometry boundaries và visible output banding được đo riêng.

## So sánh engine

| Fixture | Engine | False-edge % | Regions trong soft ROI | First failing stage | Confidence |
|---|---|---:|---:|---|---|
{chr(10).join(table_rows)}

### Ground-truth hard boundary

Trong `hard_boundary_with_gradient`, Smart V2 đạt segmentation precision/recall/F1 **0.9985 / 1.0000 / 0.9993** tại 2 px; Contour-Preserving đạt **1.0000 / 1.0000 / 1.0000**. Không engine nào tạo false edge vượt ngưỡng trong soft-gradient ROIs. `low_contrast_multistop_gradient` cũng có false-edge 0% cho cả hai.

### Color error trong soft-gradient ROIs (CIEDE2000)

| Fixture | Engine | Mean ΔE00 | P95 ΔE00 |
|---|---|---:|---:|
| smooth_nonlinear_gradient | Smart V2 | {smooth_smart['gradientMetrics']['meanDeltaE00']:.3f} | {smooth_smart['gradientMetrics']['p95DeltaE00']:.3f} |
| smooth_nonlinear_gradient | Contour-Preserving | {smooth_contour['gradientMetrics']['meanDeltaE00']:.3f} | {smooth_contour['gradientMetrics']['p95DeltaE00']:.3f} |
| hard_boundary_with_gradient | Smart V2 | {analysis['fixtures']['hard_boundary_with_gradient']['engines']['smart_reconstruction']['gradientMetrics']['meanDeltaE00']:.3f} | {analysis['fixtures']['hard_boundary_with_gradient']['engines']['smart_reconstruction']['gradientMetrics']['p95DeltaE00']:.3f} |
| hard_boundary_with_gradient | Contour-Preserving | {hard_contour['gradientMetrics']['meanDeltaE00']:.3f} | {hard_contour['gradientMetrics']['p95DeltaE00']:.3f} |
| low_contrast_multistop_gradient | Smart V2 | {analysis['fixtures']['low_contrast_multistop_gradient']['engines']['smart_reconstruction']['gradientMetrics']['meanDeltaE00']:.3f} | {analysis['fixtures']['low_contrast_multistop_gradient']['engines']['smart_reconstruction']['gradientMetrics']['p95DeltaE00']:.3f} |
| low_contrast_multistop_gradient | Contour-Preserving | {low_contour['gradientMetrics']['meanDeltaE00']:.3f} | {low_contour['gradientMetrics']['p95DeltaE00']:.3f} |

## Xác định first failing stage

Ở fixture phi tuyến, Contour segmentation tạo sáu region trên toàn ảnh nhưng chỉ **một region trong analytic soft ROI**, với **0 segmentation-boundary pixels** bên trong ROI. Fitted geometry cũng không có boundary bên trong ROI. Base paint-only prediction từ fitted regional gradient có false-edge 0%. Khi áp appearance features, appearance diagnostic đạt **1.5741%** false-edge; production SVG đạt cùng **1.5741%**, false-edge mask IoU **1.0000**, và pixel ΔE00 diagnostic-versus-production bằng 0 trong ROI. **98.17%** false-edge pixels nằm trong vùng lân cận feature paths. Đây là bằng chứng VERIFIED rằng appearance feature fitting tạo các patch phẳng/biên màu giả trên gradient vốn liên tục; segmentation chỉ cung cấp outer shape.

False boundary color comparison trên các cặp pixel liền kề thỏa threshold:

- Contour: source cross-edge CIE76 mean/P95 **1.010 / 1.768**; output cross-edge CIE76 **19.584 / 44.763**. Sai số CIEDE2000 theo hai phía: side A mean/P95 **8.503 / 18.590**, side B **8.728 / 20.052**.
- Smart V2: source cross-edge CIE76 mean/P95 **1.071 / 1.788**; output cross-edge CIE76 **10.824 / 28.298**. Sai số CIEDE2000: side A **5.239 / 9.626**, side B **5.196 / 9.744**.

Negative control source-versus-itself tạo 0 false edge; positive control có step 40 sRGB levels tạo 1.8349% và vượt ngưỡng 1%. [false_edge_detector_controls.json](false_edge_detector_controls.json).

## Đối chiếu ACTIVE FOX — proxy only

Task 08B.1.1 ghi nhận Contour-Preserving có 235/5,040 candidate pixels (**4.6627%**) trong tail/body ROI; 93.62% gần segmentation boundaries, tám region trong ROI và 66 region trên toàn ảnh. Đây là JPEG proxy, không có semantic ground truth và cần human review. Controlled fixture mới cũng tái hiện excess edge response trong gradient liên tục, nhưng khác cấu trúc: chỉ một region trong soft ROI, không có segmentation boundary; 98.17% false pixels nằm gần internal appearance features. Kết quả analytic chứng minh Contour có thể tạo biên màu giả ở appearance stage, nhưng **không chứng minh mọi biên nghi ngờ trên ACTIVE FOX đều sai hoặc cùng nguyên nhân**. Chi tiết ở [active_fox_proxy_comparison.json](active_fox_proxy_comparison.json).

## SVG, render và regression

- 3 fixture families × 2 API engines: **6/6 jobs succeeded**; mỗi SVG có viewBox đúng native canvas 512×512, không embedded raster. Native Edge và Svg.Skia renders đều 512×512; alpha IoU kiểm tra đối chiếu và lưu theo từng engine.
- Task 08B.1.2 radial-gradient regression: **3 passed, 3 subtests passed**.
- Task 08B.1.3 diagnostic tests: **6 passed**.
- Full backend regression: **339 passed, 0 failures, 0 errors, and 360 subtests passed**; 24 dependency/API deprecation warnings. JUnit records 699 successful entries when subtests are expanded. JUnit: [full_regression_junit.xml](full_regression_junit.xml).
- SHA-256 snapshot trước/sau của 36 file Smart V2, Contour, composer và API: không file nào đổi; Task 08B.1.2 `phase_e.py` hash giữ nguyên `{scope['phaseECurrentSha256']}`. Xem [production_changes.json](production_changes.json).

## Visual artifacts

| Fixture | Contact sheet | Overlay boundary/false-edge |
|---|---|---|
| smooth_nonlinear_gradient | [contact sheet](visuals/contact_sheets/smooth_nonlinear_gradient.png) | [overlay](visuals/boundary_overlays/smooth_nonlinear_gradient_contour_preserving.png) |
| hard_boundary_with_gradient | [contact sheet](visuals/contact_sheets/hard_boundary_with_gradient.png) | [overlay](visuals/boundary_overlays/hard_boundary_with_gradient_contour_preserving.png) |
| low_contrast_multistop_gradient | [contact sheet](visuals/contact_sheets/low_contrast_multistop_gradient.png) | [overlay](visuals/boundary_overlays/low_contrast_multistop_gradient_contour_preserving.png) |

SVG outputs và native renders được lưu tại `runs/task08b1_3_controlled/outputs/<fixture>/<engine>/`; intermediate stage captures tại `stage_captures/<fixture>/<engine>/`.

## Acceptance

```text
{chr(10).join(f'{key} = {str(value).lower()}' for key, value in load(ARTIFACTS / 'acceptance_status.json').items())}
```

**Dừng ở Task 08B.1.3.** Kết quả xác định được appearance-stage defect và artifacts sẵn sàng cho người dùng đánh giá trước targeted repair. Không sửa segmentation, appearance, composer hay bất kỳ production module nào trong task này. `PRODUCTION_RELEASE_READY` vẫn `false` cho tới khi targeted repair được giao và nghiệm thu.
"""
    (ARTIFACTS / "task_08b_1_3_report.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
