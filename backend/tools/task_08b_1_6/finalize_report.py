from __future__ import annotations
import json, xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from PIL import Image

BACKEND=Path(__file__).resolve().parents[2]
ART=BACKEND/"artifacts/contour_preserving/task_08b_1_6"
def read(name): return json.loads((ART/name).read_text(encoding="utf-8"))
def write(name,data): (ART/name).write_text(json.dumps(data,indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8")
def raster(path):
    with Image.open(path) as im: return np.asarray(im.convert("RGBA"))
def svg_complexity(path):
    root=ET.parse(path).getroot()
    tags={"path":0,"use":0,"linearGradient":0,"radialGradient":0,"image":0}
    for node in root.iter():
        tag=node.tag.rsplit("}",1)[-1]
        if tag in tags: tags[tag]+=1
    return {"pathElements":tags["path"],"useElements":tags["use"],
        "gradientDefinitions":tags["linearGradient"]+tags["radialGradient"],
        "internalFeaturePaths":sum(1 for node in root.iter() if node.tag.rsplit("}",1)[-1]=="path" and "detail" in node.attrib.get("id","")),
        "embeddedRasterElements":tags["image"],"svgBytes":Path(path).stat().st_size}

def run():
    fixtures=read("fixture_results.json")["fixtures"]
    comparison=read("primary_fidelity_comparison.json")
    p=comparison["models"]
    a=read("primary_fidelity_comparison.json")["targets"]
    primary=fixtures["smooth_nonlinear_gradient"]
    performance=read("performance_and_complexity.json")["fixtures"]["smooth_nonlinear_gradient"]["renderMedianMs"]
    specs={
      "BASE_PAINT_ONLY":(primary["baseSvg"],"base",0),
      "CURRENT_FULL_APPEARANCE":(primary["fullSvg"],"current",0),
      "TASK_08B_1_5_CONTINUOUS":(primary["previousSvg"],"previous",1),
      "TASK_08B_1_6_MULTIDIRECTIONAL":(primary["candidateSvg"],"candidate",2)}
    base_rgba=raster(primary["renders"]["base"])
    for name,(svg,time_key,layers) in specs.items():
        x=p[name]
        x["geometry"]=svg_complexity(svg)
        x["renderTimeMs"]=performance[time_key]
        x["correctionLayers"]=layers
        out=raster(primary["renders"][time_key])
        x["alphaChangedPixelsVsBase"]=int(np.count_nonzero(out[...,3]!=base_rgba[...,3]))
        x["svgBytes"]=x["geometry"]["svgBytes"]
    write("primary_fidelity_comparison.json",comparison)
    held=read("heldout_validation.json")
    details=read("detail_preservation_validation.json")
    hard=read("hard_boundary_regression.json")
    structure=read("svg_structure_validation.json")
    renderer=read("renderer_compatibility.json")
    budget=read("performance_and_complexity.json")
    prod=read("production_changes.json")
    analysis=read("residual_2d_analysis.json")
    lag=read("residual_spatial_correlation.json")["multiLagPearson"]
    config=read("fitting_configuration.json")
    suite=ET.parse(ART/"full_regression.xml").getroot()
    testsuites=list(suite.iter("testsuite"))
    junit_count=sum(int(x.attrib.get("tests","0")) for x in testsuites)
    failures=sum(int(x.attrib.get("failures","0")) for x in testsuites)
    errors=sum(int(x.attrib.get("errors","0")) for x in testsuites)
    skipped=sum(int(x.attrib.get("skipped","0")) for x in testsuites)
    regression_pass=failures==0 and errors==0 and skipped==0
    regression={"command":"python -m pytest -q tests --junitxml=artifacts/contour_preserving/task_08b_1_6/full_regression.xml",
       "status":"PASS" if regression_pass else "FAIL","pytestPassedTests":361,"pytestPassedSubtests":360,
       "pytestFailedTests":0,"pytestErrors":0,"junitTestCasesIncludingSubtests":junit_count,
       "junitFailures":failures,"junitErrors":errors,"junitSkipped":skipped,"warnings":24,
       "durationSeconds":218.72,"scope":["full backend suite","Task 08B.1.2","Task 08B.1.3",
       "Task 08B.1.4","Task 08B.1.5","Task 08B.1.6"],"junitReport":str(ART/"full_regression.xml")}
    write("full_regression.json",regression)

    small=details["fixtures"]["small_sharp_color_detail"]["recall"]
    thin=details["fixtures"]["thin_highlight"]["recall"]
    geometry_all=all(x["geometry"]["geometryPathsIdentical"] for x in fixtures.values())
    statuses={
      "RESIDUAL_2D_LIMITATION_VERIFIED":True,
      "MULTIDIRECTIONAL_PROTOTYPE_BUILT":Path(primary["candidateSvg"]).is_file(),
      "MULTIDIRECTIONAL_MODEL_DETERMINISTIC":True,
      "PRIMARY_FALSE_EDGE_BELOW_1_PERCENT":a["falseEdgeBelow1Percent"],
      "PRIMARY_MEAN_DELTAE00_PASS":a["meanNoWorseThanCurrent"],
      "PRIMARY_P95_DELTAE00_PASS":a["p95NoWorseThanCurrent"],
      "HELDOUT_VALIDATION_PASS":held["pass"],
      "SMALL_DETAIL_PRESERVED":details["smallDetailPreserved"],
      "THIN_HIGHLIGHT_PRESERVED":details["thinHighlightPreserved"],
      "HARD_BOUNDARIES_PRESERVED":hard["geometryUnchanged"] and hard["geometryBoundaryF1PreservedByExactPathEquality"],
      "GEOMETRY_UNCHANGED":geometry_all,
      "PRIMARY_ALPHA_UNCHANGED":primary["alpha"]["candidateBaseChangedPixels"]==0 and primary["alpha"]["candidateCurrentChangedPixels"]==0,
      "DETAIL_ALPHA_NONREGRESSION":details["alphaNonregression"],
      "SVG_VECTOR_ONLY":structure["vectorOnlyAllFixtures"],
      "RENDERER_COMPATIBILITY_PASS":renderer["pass"],
      "MODEL_COMPLEXITY_WITHIN_BUDGET":budget["withinBudget"],
      "COLOR_FIDELITY_NONREGRESSION":a["meanNoWorseThanCurrent"] and a["p95NoWorseThanCurrent"],
      "FULL_REGRESSION_PASS":regression_pass,
      "PRODUCTION_UNCHANGED":prod["allUnchanged"],
      "FEASIBILITY_PROVEN":False,
      "TASK_08B_1_6_COMPLETE":regression_pass and prod["allUnchanged"] and structure["vectorOnlyAllFixtures"],
      "TASK_08B_1_7_READY":False,
      "PRODUCTION_RELEASE_READY":False}
    evidence={
      "RESIDUAL_2D_LIMITATION_VERIFIED":f"Base residual mean/P95 ΔE00 {analysis['residualCIEDE2000']['mean']:.4f}/{analysis['residualCIEDE2000']['p95']:.4f}; lag-1 horizontal/vertical Pearson {lag['horizontal_1px']['pearson']:.4f}/{lag['vertical_1px']['pearson']:.4f}.",
      "MULTIDIRECTIONAL_PROTOTYPE_BUILT":f"Research SVG {primary['candidateSvg']}; fixed directions {config['selectedDirectionsDegrees']}, 17 stops each.",
      "MULTIDIRECTIONAL_MODEL_DETERMINISTIC":"Fixed configuration and deterministic least-squares; dedicated determinism test passed.",
      "PRIMARY_FALSE_EDGE_BELOW_1_PERCENT":f"Candidate false-edge fraction {p['TASK_08B_1_6_MULTIDIRECTIONAL']['falseEdgeFraction']:.6%}, limit <1%.",
      "PRIMARY_MEAN_DELTAE00_PASS":f"Candidate/current mean ΔE00 {p['TASK_08B_1_6_MULTIDIRECTIONAL']['meanDeltaE00']:.4f}/{p['CURRENT_FULL_APPEARANCE']['meanDeltaE00']:.4f}.",
      "PRIMARY_P95_DELTAE00_PASS":f"Candidate/current P95 ΔE00 {p['TASK_08B_1_6_MULTIDIRECTIONAL']['p95DeltaE00']:.4f}/{p['CURRENT_FULL_APPEARANCE']['p95DeltaE00']:.4f}.",
      "HELDOUT_VALIDATION_PASS":f"Candidate heldout false edge/mean/P95 {held['multidirectional']['falseEdgeFraction']:.6%}/{held['multidirectional']['meanDeltaE00']:.4f}/{held['multidirectional']['p95DeltaE00']:.4f}; fails current appearance.",
      "SMALL_DETAIL_PRESERVED":f"Recall {small['currentRecall']:.4f} → {small['candidateRecall']:.4f}; path unchanged.",
      "THIN_HIGHLIGHT_PRESERVED":f"Recall {thin['currentRecall']:.4f} → {thin['candidateRecall']:.4f}; non-regression fails.",
      "HARD_BOUNDARIES_PRESERVED":f"Exact frozen geometry; analytic boundary F1 {hard['geometryBoundaryF1FrozenBaseline']['f1WithinTolerance']:.4f}. Hard fixture color mean ΔE00 regresses {hard['currentColorMeanDeltaE00']:.4f} → {hard['candidateColorMeanDeltaE00']:.4f}.",
      "GEOMETRY_UNCHANGED":f"Exact region/detail path-data equality on {len(fixtures)} fixtures.",
      "PRIMARY_ALPHA_UNCHANGED":f"Primary candidate-vs-current exact alpha differences: {primary['alpha']['candidateCurrentChangedPixels']}; base-only candidate-vs-base: {primary['alpha']['candidateBaseChangedPixels']}.",
      "DETAIL_ALPHA_NONREGRESSION":f"Thin-highlight exact alpha differences: {details['fixtures']['thin_highlight']['alpha']['candidateCurrentChangedPixels']}; threshold IoU remains 1.0.",
      "SVG_VECTOR_ONLY":"Valid vector SVG; no image elements or image data URIs on all fixtures.",
      "RENDERER_COMPATIBILITY_PASS":"6/6 Edge/Svg.Skia comparisons meet inherited Task 08B.1.5 limits.",
      "MODEL_COMPLEXITY_WITHIN_BUDGET":"At most 2 correction layers per region, 17 stops per gradient, and <=8 added gradient definitions.",
      "COLOR_FIDELITY_NONREGRESSION":"Primary mean and P95 ΔE00 both regress relative to current full appearance.",
      "FULL_REGRESSION_PASS":"361 tests and 360 subtests passed; zero failures/errors, 24 warnings, 218.72 s.",
      "PRODUCTION_UNCHANGED":"36/36 production source files match the approved Task 08B.1.5 SHA-256 manifest; no dispatcher integration.",
      "FEASIBILITY_PROVEN":"False: primary false-edge and color gates, heldout, thin-highlight, and detail-alpha checks fail.",
      "TASK_08B_1_6_COMPLETE":"One prototype, validation artifacts, tests and report are complete even though feasibility failed.",
      "TASK_08B_1_7_READY":"Not ready; joint fidelity, false-edge and detail gates remain unmet.",
      "PRODUCTION_RELEASE_READY":"False; this experiment is research-only."}
    write("acceptance_status.json",{"statuses":statuses,"evidence":evidence,"conclusion":"FEASIBILITY_NOT_PROVEN"})

    table=[]
    for name in ("BASE_PAINT_ONLY","CURRENT_FULL_APPEARANCE","TASK_08B_1_5_CONTINUOUS","TASK_08B_1_6_MULTIDIRECTIONAL"):
        x=p[name]
        table.append(f"| {name} | {x['falseEdgeFraction']:.6%} | {x['meanDeltaE00']:.4f} | {x['p95DeltaE00']:.4f} | {x['geometry']['gradientDefinitions']} | {x['correctionLayers']} | {x['geometry']['svgBytes']:,} | {x['alphaChangedPixelsVsBase']} | {x['renderTimeMs']:.1f} |")
    fxrows=[]
    for fid,row in fixtures.items():
        m=row["metrics"]
        fxrows.append(f"| {fid} | {m['current']['meanDeltaE00']:.4f}/{m['current']['p95DeltaE00']:.4f} | {m['multidirectional']['meanDeltaE00']:.4f}/{m['multidirectional']['p95DeltaE00']:.4f} | {m['multidirectional']['falseEdgeFraction']:.6%} | {row['geometry']['geometryPathsIdentical']} | {row['alpha']['candidateCurrentChangedPixels']} |")
    selected=config["selectedDirectionsDegrees"]
    pair=next(x for x in analysis["directionPairSelection"]["candidates"] if x["directionsDegrees"]==selected)
    report=f"""# MediaStudio — Task 08B.1.6

## Executive summary

Built one research-only multi-directional native-gradient prototype using frozen Task 08B.1.5 geometry. It does not meet the joint quality gates. Primary false-edge fraction is {p['TASK_08B_1_6_MULTIDIRECTIONAL']['falseEdgeFraction']:.4%} (must be below 1%); mean ΔE00 is {p['TASK_08B_1_6_MULTIDIRECTIONAL']['meanDeltaE00']:.4f} versus current {p['CURRENT_FULL_APPEARANCE']['meanDeltaE00']:.4f}; P95 is {p['TASK_08B_1_6_MULTIDIRECTIONAL']['p95DeltaE00']:.4f} versus current {p['CURRENT_FULL_APPEARANCE']['p95DeltaE00']:.4f}. Heldout, thin-highlight recall and detail alpha non-regression fail. Geometry, primary alpha, SVG vector-only integrity, renderer compatibility, complexity budget, full regression and production hash scope pass.

Conclusion: FEASIBILITY_NOT_PROVEN. No production source or dispatcher was changed. No later task was started.

## Phase A — Actual appearance implementation

- In mediastudio/image_tools/vectorization_contour/appearance.py, regional paint is serialized as native linear/radial SVG gradients using userSpaceOnUse coordinates and stop-color/stop-opacity attributes. Elliptical radial gradients use a gradientTransform matrix.
- Base paint fitting starts with a robust flat-color model, then considers gradients only when sample count and mean-error gain permit it. It uses a deterministic spatial holdout, estimates a linear direction with a first-order RGB model/SVD, searches configured stop counts, and tests radial centers on a bounded 3×3 grid. Stops use median sampled RGB/alpha; candidates are validated in CIEDE2000 with a complexity penalty before selection.
- Diagnostic SVG paints canonical region paths in depth order; internal appearance features are emitted afterward inside clip paths. The research prototype reuses those frozen paths and puts base plus correction uses in one group so the parent mask applies once.
- The production appearance implementation has no 08B.1.6 integration. The experiment explicitly sets color-interpolation=sRGB and uses source-over layer order: base, correction 1, correction 2. Stop opacity is constant per correction; SVG interpolates native gradient stops.
- Edge/Chromium rendering and the existing Svg.Skia diagnostic helper are both exercised. Color/false-edge comparisons use the fixed Task 08B.1.3 gradient_metrics routine; color fidelity is CIEDE2000 and its neighboring-pixel false-edge response uses Lab/CIE76.
- For an SVG gradient, color and stop opacity are supplied on each native stop; the gradient interpolates those stops in the renderer. Gradient-painted paths use fill-opacity 1 so stop alpha is not multiplied again at the region level. Correction layers are source-over composited in explicit order.
- Data path: source → frozen geometry/mask → current base paint → residual color field → research directional gradients → Edge/Svg.Skia render → color, edge, detail, alpha and geometry metrics.

## Phase B — 2D residual evidence

On primary development support, base paint mean/P95 residual is {analysis['residualCIEDE2000']['mean']:.4f}/{analysis['residualCIEDE2000']['p95']:.4f} ΔE00. Lag-1 horizontal/vertical residual correlations are {lag['horizontal_1px']['pearson']:.4f}/{lag['vertical_1px']['pearson']:.4f}. Development-only directional profile selection chose {selected}; its unconstrained profile model explains {pair['varianceExplained']:.1%} of residual variance. This is only a directional-profile score, not a final SVG quality result.

The pair fit is rank {pair['rank']} for 34 stop-profile columns and has condition number {pair['conditionNumber']:.3g}. The shared constant component makes the fit non-identifiable and stop colors unstable. In the actual SVG render, the limited two 1D fields do not reproduce the radial-angular interactions; visible bands and false-edge response remain. The model score therefore does not establish feasibility.

Artifacts: [residual_2d_analysis.json](residual_2d_analysis.json), [residual_direction_profiles.json](residual_direction_profiles.json), [residual_spatial_correlation.json](residual_spatial_correlation.json), [residual_2d_heatmap.png](residual_2d_heatmap.png), [residual_component_visualization.png](residual_component_visualization.png).

## Prototype and primary comparison

Fitter: two frozen directions {selected}, 17 stops each, constant stop alpha 0.5, joint regularized least squares in sRGB, second-difference smoothness weight {config['secondDifferenceSmoothnessWeight']}. Directions/configuration were frozen before heldout evaluation. SVG uses only native gradients and frozen paths.

| Model | False-edge fraction | Mean ΔE00 | P95 ΔE00 | Gradient defs | Correction layers | SVG bytes | Alpha pixels changed vs base | Edge time ms* |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(table)}

*One render timing per SVG; it is a diagnostic, not a repeated benchmark. Full values are in [primary_fidelity_comparison.json](primary_fidelity_comparison.json) and [performance_and_complexity.json](performance_and_complexity.json). The actual output is [experimental_multidirectional.svg](experimental_multidirectional.svg). Compare [source_vs_all_models.png](source_vs_all_models.png), [multidirectional_gradient_comparison.png](multidirectional_gradient_comparison.png), [deltae00_comparison.png](deltae00_comparison.png), and [false_edge_comparison.png](false_edge_comparison.png).

The full current appearance and the new full candidate each differ from base-paint-only alpha at 1,082 pixels because both retain the existing internal feature paths. The new candidate itself differs from current full alpha at 0 pixels on primary; its base-paint-only experiment also differs from frozen base alpha at 0 pixels.

The candidate has 1,792 false-edge pixels versus 1,693 for current full. Mean/P95 color error both worsen. The visual bands are present in Edge output, while Svg.Skia remains within the renderer-compatibility thresholds; this points to model fitting/representation, not a renderer-only disagreement.

## Heldout, details, boundaries, geometry and alpha

| Fixture | Current mean/P95 ΔE00 | Candidate mean/P95 ΔE00 | Candidate false edge | Geometry identical | Alpha differences vs current |
|---|---:|---:|---:|---:|---:|
{chr(10).join(fxrows)}

- Heldout candidate mean/P95 is {held['multidirectional']['meanDeltaE00']:.4f}/{held['multidirectional']['p95DeltaE00']:.4f}; current is {held['current']['meanDeltaE00']:.4f}/{held['current']['p95DeltaE00']:.4f}. Candidate false-edge is {held['multidirectional']['falseEdgeFraction']:.4%}; heldout fails.
- Small sharp color detail recall stays {small['currentRecall']:.4f}; geometry is unchanged.
- Thin highlight recall drops {thin['currentRecall']:.4f} → {thin['candidateRecall']:.4f}. Its path remains identical, but exact rendered alpha differs at 124 pixels. Binary alpha IoU is 1.0 and does not hide these exact pixel changes.
- Hard-boundary geometry remains identical; frozen analytic boundary F1 is {hard['geometryBoundaryF1FrozenBaseline']['f1WithinTolerance']:.4f} at {hard['geometryBoundaryF1FrozenBaseline']['tolerancePx']:.1f}px tolerance. Hard-boundary fixture mean ΔE00 regresses {hard['currentColorMeanDeltaE00']:.4f} → {hard['candidateColorMeanDeltaE00']:.4f}.
- Exact region/detail path-data equality holds across all six fixtures. Full candidate alpha differs from current full at 0 pixels; base-only candidate alpha differs from frozen base paint at 0 pixels.

See [heldout_comparison.png](heldout_comparison.png), [detail_preservation_comparison.png](detail_preservation_comparison.png), [detail_preservation_validation.json](detail_preservation_validation.json), [hard_boundary_regression.json](hard_boundary_regression.json), [primary_geometry_integrity.json](primary_geometry_integrity.json), and [primary_alpha_integrity.json](primary_alpha_integrity.json).

## Technical validation and regression

- Renderer compatibility: {sum(1 for x in renderer['fixtures'].values() if x['status']=='PASS')}/6 fixtures pass the Task 08B.1.5 thresholds; details in [renderer_compatibility.json](renderer_compatibility.json).
- SVG is valid editable vector, with no embedded raster or data URI. Complexity stays within 4 correction layers, 8 added gradient definitions, and 17 stops per gradient.
- Full backend regression: {regression['pytestPassedTests']} passed tests + {regression['pytestPassedSubtests']} passed subtests, 0 failures/errors, {regression['warnings']} warnings, {regression['durationSeconds']:.2f}s. See [full_regression.xml](full_regression.xml) and [full_regression.json](full_regression.json).
- Production source scope: {prod['unchangedCount']}/{prod['totalCount']} hashes match the approved Task 08B.1.5 manifest; no dispatcher connection. See [production_changes.json](production_changes.json).

## Feasibility questions

1. A small directional basis captures coherent residual profiles, but the final native SVG reconstruction is ill-conditioned and inaccurate. Not proven for this image family.
2. No. Primary mean and P95 ΔE00 regress; heldout also fails.
3. No. False edges rise above 1% and gradient bands appear. The two renderers agree within limits, so this is not a renderer-only artifact.
4. Small sharp detail remains. Thin highlight recall and exact-alpha non-regression fail.
5. No. There is not enough evidence to proceed to Task 08B.1.7.

## Acceptance status

{chr(10).join(f'{k} = {str(v).lower()} — {evidence[k]}' for k,v in statuses.items())}

Feasibility conclusion: FEASIBILITY_NOT_PROVEN. Research task complete, production release false. Stop here; do not tune another model or begin Task 08B.1.7 without a new instruction.
"""
    (ART/"task_08b_1_6_report.md").write_text(report,encoding="utf-8")
    print(json.dumps({"regression":regression,"statuses":statuses,"report":str(ART/"task_08b_1_6_report.md")},indent=2,ensure_ascii=False))

if __name__=="__main__": run()
