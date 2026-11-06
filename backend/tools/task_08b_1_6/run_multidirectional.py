from __future__ import annotations
import copy, hashlib, itertools, json, math, statistics, sys, time, xml.etree.ElementTree as ET
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from skimage.color import deltaE_ciede2000, rgb2lab

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
ART = BACKEND / "artifacts/contour_preserving/task_08b_1_6"
TASK13 = BACKEND / "artifacts/contour_preserving/task_08b_1_3"
TASK14 = BACKEND / "artifacts/contour_preserving/task_08b_1_4"
TASK15 = BACKEND / "artifacts/contour_preserving/task_08b_1_5"
sys.path.insert(0, str(BACKEND)); sys.path.insert(0, str(BACKEND / "tools"))
from task_08b_1_1.diagnostics import _lab_neighbor_delta, gradient_metrics
from task_08b_1_5.run_feasibility import (
    NS, XLINK, _detail_geometry_paths, _find_child_id, _frozen_geometry_paths,
    _geometry_paths, _gradient_url, _href, _metrics_for_fixture, _read_tree,
    _region_mask, _region_geometry_paths, _render_timed, _save_svg, _strip_details,
    _svg_complexity, alpha_iou, de_map, jread, load_rgba, validate_svg, white,
)
from vectorization_benchmark.svg import render_svg_edge, render_svg_skia
ET.register_namespace("", NS); ET.register_namespace("xlink", XLINK)
FIXTURES = ("smooth_nonlinear_gradient", "smooth_alternate_heldout", "small_sharp_color_detail",
            "thin_highlight", "hard_boundary_with_gradient", "low_contrast_multistop_gradient")
DEV = "smooth_nonlinear_gradient"
ANGLES = (0.0, 45.0, 90.0, 135.0)
STOPS = 17
OPACITY = 0.5
SMOOTHNESS = 2.0
RENDERER_LIMITS = {"alphaIouMinimum": 0.995, "meanDeltaE00Maximum": 1.0, "p95DeltaE00Maximum": 3.0}

def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()

def paths(fid: str):
    return _metrics_for_fixture(fid)

def img(path: Path, mode="RGBA"):
    with Image.open(path) as im: return np.asarray(im.convert(mode))

def stats(v):
    a = np.asarray(v, dtype=np.float64).ravel()
    if not a.size: return {"count": 0, "mean": None, "p95": None, "rms": None}
    return {"count": int(a.size), "mean": float(a.mean()), "p95": float(np.quantile(a, .95)),
            "rms": float(np.sqrt(np.mean(a*a)))}

def proj(shape, angle, support):
    h,w=shape; yy,xx=np.indices(shape,dtype=np.float32); t=math.radians(angle)
    p=xx*math.cos(t)+yy*math.sin(t); q=p[support]
    return np.clip((p-float(q.min()))/max(float(q.max()-q.min()),1e-6),0,1)

def basis(t, count=STOPS):
    z=np.asarray(t,dtype=np.float64).ravel(); scaled=np.clip(z,0,1)*(count-1)
    lo=np.floor(scaled).astype(np.int32); hi=np.minimum(lo+1,count-1); f=scaled-lo
    out=np.zeros((z.size,count),dtype=np.float64); rows=np.arange(z.size)
    out[rows,lo]+=1-f; out[rows,hi]+=f
    return out

def get_regions(fid):
    source, roi, full, appearance, detail = paths(fid)
    a=jread(appearance)
    return source,roi,full,appearance,detail,a,[r for r in a.get("regions",[]) if r.get("gradient") and r["gradient"].get("kind") in {"linear","radial"}]

def choose_directions():
    source_path,roi_path,_,appearance_path,_=paths(DEV)
    source=load_rgba(source_path); roi=img(roi_path,"L")>127
    base_svg=TASK15/"fixtures"/DEV/"base_paint_only.svg"
    base=render_svg_edge(base_svg,width=512,height=512)
    appearance=jread(appearance_path); region=next(r for r in appearance["regions"] if r.get("gradient"))
    mask=_region_mask(_read_tree(base_svg),int(region["regionId"]),ART/"analysis")
    support=roi & mask & (source[...,3]>=250) & (base[...,3]>=250)
    support=cv2.erode(support.astype(np.uint8),np.ones((3,3),np.uint8),iterations=1).astype(bool)
    s=rgb2lab(white(source).astype(np.float32)/255); b=rgb2lab(white(base).astype(np.float32)/255)
    resid=s-b; resrgb=white(source).astype(np.float64)/255-white(base).astype(np.float64)/255
    yy,xx=np.indices(support.shape,dtype=np.float32)
    cx,cy,rx,ry=[float(x) for x in region["gradient"]["geometrySourceXY"]]
    rad=np.sqrt(((xx-cx)/max(abs(rx),1e-6))**2+((yy-cy)/max(abs(ry),1e-6))**2)
    theta=np.arctan2(yy-cy,xx-cx)
    delta=de_map(white(source),white(base))
    radial=[]; angular=[]
    rb=np.linspace(float(np.quantile(rad[support],.005)),float(np.quantile(rad[support],.995)),25)
    ab=np.linspace(-math.pi,math.pi,37)
    ri=np.clip(np.digitize(rad,rb[1:-1]),0,len(rb)-2); ai=np.clip(np.digitize(theta,ab[1:-1]),0,len(ab)-2)
    for i in range(len(rb)-1):
        m=support&(ri==i); radial.append({"range":[float(rb[i]),float(rb[i+1])],"pixels":int(m.sum()),"residualLab":stats(resid[m]) if m.any() else None})
    for i in range(len(ab)-1):
        m=support&(ai==i); angular.append({"rangeRadians":[float(ab[i]),float(ab[i+1])],"pixels":int(m.sum()),
                                           "meanDeltaE00":float(delta[m].mean()) if m.any() else None,
                                           "residualMeanLab":resid[m].mean(axis=0).tolist() if m.any() else None})
    profile={}; bases={}
    for angle in ANGLES:
        t=proj(support.shape,angle,support); B=basis(t[support]); bases[angle]=B
        bin_id=np.minimum((t*63).astype(int),63); bins=[]; pred=np.zeros_like(resid)
        for i in range(64):
            m=support&(bin_id==i)
            if m.any():
                avg=resid[m].mean(axis=0); pred[m]=avg
                bins.append({"bin":i,"pixels":int(m.sum()),"meanResidualLab":avg.tolist(),"rmsResidualLab":float(np.sqrt(np.mean(resid[m]**2)))})
            else: bins.append({"bin":i,"pixels":0,"meanResidualLab":None,"rmsResidualLab":None})
        variance=float(np.sum((resid[support]-resid[support].mean(axis=0))**2))
        r2=1-float(np.sum((resid[support]-pred[support])**2))/max(variance,1e-12)
        profile[str(int(angle))]={"angleDegrees":angle,"bins":bins,"profileExplainedResidualVariance":r2}
    pair_scores=[]
    y=resrgb[support]
    for a,bangle in itertools.combinations(ANGLES,2):
        A=np.concatenate((bases[a],bases[bangle]),axis=1)
        coef,_,rank,sv=np.linalg.lstsq(A,y,rcond=1e-8); err=y-A@coef
        var=float(np.mean((y-y.mean(axis=0))**2)); mse=float(np.mean(err**2))
        pair_scores.append({"directionsDegrees":[a,bangle],"residualMseRgbNormalized":mse,
                            "varianceExplained":1-mse/max(var,1e-12),"rank":int(rank),
                            "conditionNumber":float(sv[0]/max(sv[-1],1e-12))})
    best=max(pair_scores,key=lambda r:(r["varianceExplained"],-r["residualMseRgbNormalized"],tuple(-v for v in r["directionsDegrees"])))
    # Multi-lag Lab residual autocorrelation and residual gradient scale.
    lag={}
    for n in (1,2,4,8,16):
        for name,dy,dx in (("horizontal",0,n),("vertical",n,0)):
            h,w=support.shape; a=resid[:h-dy or None,:w-dx or None]; b=resid[dy:,dx:]
            m=support[:h-dy or None,:w-dx or None]&support[dy:,dx:]
            corr=float(np.corrcoef(a[m].ravel(),b[m].ravel())[0,1]) if m.sum()>8 else None
            lag[f"{name}_{n}px"]={"pearson":corr,"pairCount":int(m.sum())}
    grad=cv2.Sobel(resid[...,0],cv2.CV_32F,1,0,ksize=3)/8
    grad_y=cv2.Sobel(resid[...,0],cv2.CV_32F,0,1,ksize=3)/8
    hard=img(TASK13/"fixtures/smooth_nonlinear_gradient/ground_truth_hard_boundary.png","L")>127
    analysis={"fixture":DEV,"sourceSha256":sha(source_path),"frozenBaseSvgSha256":sha(base_svg),"supportPixels":int(support.sum()),
              "residualCIEDE2000":stats(delta[support]),"residualLabComponents":{k:stats(resid[...,i][support]) for i,k in enumerate(("L*","a*","b*"))},
              "radialProfile":radial,"angularProfile":angular,"directionalResidualProfiles":profile,
              "directionPairSelection":{"candidates":pair_scores,"selectedDegrees":best["directionsDegrees"],
                 "rule":"highest variance explained by 2 piecewise-linear directional profiles on development residual only"},
              "spatialScale":{"multiLagPearson":lag,"residualLabLumaGradientMagnitude":stats(np.sqrt(grad**2+grad_y**2)[support])},
              "annotatedHardBoundaryPixelsInsideSupport":int((hard&support).sum()),
              "interpretation":"Residual is spatially structured. Direction selection is based only on development data and is evidence for one fixed two-direction prototype, not a general proof."}
    profiles={"fixture":DEV,"coordinateConvention":"image x right/y down, angle from +x, projection normalized over support bbox",
              "directions":profile,"pairSelection":analysis["directionPairSelection"],"radialProfile":radial,"angularProfile":angular}
    return analysis,profiles,source,white(base),support,best["directionsDegrees"]

def fit_stops(source,base_rgb,support,directions):
    B=[basis(proj(support.shape,a,support)[support]) for a in directions]
    weights=[OPACITY*(1-OPACITY)**(len(directions)-1-i) for i in range(len(directions))]
    base_w=(1-OPACITY)**len(directions)
    A=np.concatenate([b*w for b,w in zip(B,weights)],axis=1)
    src=source[support].astype(np.float64)/255
    base=base_rgb[support].astype(np.float64)/255
    y=src-base_w*base
    d2=np.zeros((STOPS-2,STOPS))
    for i in range(STOPS-2): d2[i,i:i+3]=(1,-2,1)
    reg=np.zeros((len(directions)*(STOPS-2),len(directions)*STOPS))
    for i in range(len(directions)): reg[i*(STOPS-2):(i+1)*(STOPS-2),i*STOPS:(i+1)*STOPS]=d2*SMOOTHNESS
    aug=np.vstack((A,reg)); rhs=np.vstack((y,np.zeros((len(reg),3))))
    raw,_,rank,sv=np.linalg.lstsq(aug,rhs,rcond=1e-10); co=np.clip(raw,0,1)
    tables=[co[i*STOPS:(i+1)*STOPS] for i in range(len(directions))]
    pred=base_w*base+sum(w*(b@tbl) for w,b,tbl in zip(weights,B,tables))
    trace={"optimizer":"regularized joint least squares on sRGB stop colors; 2nd-difference penalty; clipped [0,1]",
           "seed":None,"iterations":1,"sampleCount":int(support.sum()),"rank":int(rank),
           "conditionNumber":float(sv[0]/max(sv[-1],1e-12)),"layerOpacity":OPACITY,
           "layerContributionWeights":weights,"baseContributionWeight":base_w,
           "secondDifferenceWeight":SMOOTHNESS,"clippedColorComponents":int(np.count_nonzero(np.abs(raw-co)>1e-9)),
           "fittedRgbRmse":float(np.sqrt(np.mean((pred-src)**2))),
           "stopTables":[x.tolist() for x in tables]}
    return tables,trace

def endpoints(angle,w,h):
    t=math.radians(angle); nx,ny=math.cos(t),math.sin(t)
    p=[x*nx+y*ny for x,y in ((0,0),(w-1,0),(0,h-1),(w-1,h-1))]
    lo,hi=min(p),max(p); return lo*nx,lo*ny,hi*nx,hi*ny

def add_layers(root,appearance,source,base_rgba,work,directions):
    defs=next((x for x in root if x.tag.rsplit("}",1)[-1]=="defs"),None)
    group=_find_child_id(root,"artwork-base-regions")
    if defs is None or group is None: raise ValueError("Frozen SVG missing defs or artwork-base-regions")
    h,w=source.shape[:2]; fits={}; traces={}
    for region in appearance.get("regions",[]):
        grad=region.get("gradient")
        if not grad or grad.get("kind") not in {"radial","linear"}: continue
        rid=int(region["regionId"]); mask=_region_mask(root,rid,work)
        support=mask&(source[...,3]>=250)&(base_rgba[...,3]>=250)
        support=cv2.erode(support.astype(np.uint8),np.ones((3,3),np.uint8),iterations=1).astype(bool)
        if support.sum()<STOPS*4: continue
        tables,trace=fit_stops(source[...,:3],white(base_rgba),support,directions)
        use=next((x for x in group if x.tag.rsplit("}",1)[-1]=="use"
                  and _href(x).lstrip("#") in {f"contour-region-{rid}",f"region-{rid}"}
                  and _gradient_url(x.attrib.get("fill",""))),None)
        if use is None: continue
        index=list(group).index(use); parent_mask=use.attrib.get("mask")
        wrapper=ET.Element(f"{{{NS}}}g",{"data-research-model":"multidirectional-continuous-gradient","data-region-id":str(rid)})
        if parent_mask: wrapper.set("mask",parent_mask)
        base_child=copy.deepcopy(use); base_child.attrib.pop("mask",None); wrapper.append(base_child)
        records=[]
        for li,(angle,table) in enumerate(zip(directions,tables)):
            gid=f"research-multidirectional-r{rid}-d{li}"; x1,y1,x2,y2=endpoints(angle,w,h)
            g=ET.Element(f"{{{NS}}}linearGradient",{"id":gid,"gradientUnits":"userSpaceOnUse",
                  "x1":f"{x1:.6f}","y1":f"{y1:.6f}","x2":f"{x2:.6f}","y2":f"{y2:.6f}",
                  "color-interpolation":"sRGB","data-research-direction-degrees":f"{angle:g}"})
            srec=[]
            for i,c in enumerate(table):
                rgb=np.rint(np.clip(c*255,0,255)).astype(int).tolist(); offset=i/(STOPS-1)
                ET.SubElement(g,f"{{{NS}}}stop",{"offset":f"{offset:.6f}",
                    "stop-color":"#"+"".join(f"{v:02x}" for v in rgb),"stop-opacity":f"{OPACITY:.6f}"})
                srec.append({"offset":offset,"colorRGB":rgb,"opacity":OPACITY})
            defs.append(g)
            child=copy.deepcopy(use); child.attrib.pop("mask",None); child.set("fill",f"url(#{gid})"); child.set("fill-opacity","1")
            wrapper.append(child); records.append({"gradientId":gid,"directionDegrees":angle,"endpoints":[x1,y1,x2,y2],"stops":srec})
        group.remove(use); group.insert(index,wrapper)
        baseid=_gradient_url(use.attrib.get("fill",""))
        fits[str(rid)]={"regionId":rid,"baseGradientId":baseid,"frozenPathId":_href(use).lstrip("#"),
                        "fitPixels":int(support.sum()),"geometrySourceXY":grad.get("geometrySourceXY"),"correctionLayers":records}
        traces[str(rid)]=trace
    return fits,traces

def metrics(source,render,roi):
    sw,out=white(source),white(render); g=gradient_metrics(sw,out,roi)
    interior=cv2.erode(np.asarray(roi,dtype=np.uint8),np.ones((3,3),np.uint8),iterations=1)>0
    if not interior.any(): interior=np.asarray(roi,dtype=bool)
    de=de_map(sw,out)[interior]
    return {"falseEdgeFraction":float(g["falseHardEdgeFraction"]),"falseHardEdgePixels":int(g["falseHardEdgePixels"]),
            "meanDeltaE00":float(g["meanDeltaE00"]),"p95DeltaE00":float(g["p95DeltaE00"]),
            "maxDeltaE00":float(de.max()) if de.size else 0.0,"samplePixels":int(g["roiPixels"])}

def geometry(full,candidate):
    a,b=_frozen_geometry_paths(full),_frozen_geometry_paths(candidate)
    da,db=_detail_geometry_paths(full),_detail_geometry_paths(candidate)
    return {"frozenPathCount":len(a),"geometryPathsIdentical":a==b,"detailPathCount":len(da),
            "detailPathsIdentical":da==db,"changedPathIds":sorted(k for k in a.keys()|b.keys() if a.get(k)!=b.get(k))}

def render_fixture(fid,directions):
    sp,rp,full,ap,dp,appearance,regions=get_regions(fid)
    bas=TASK15/"fixtures"/fid/"base_paint_only.svg"; old=TASK15/"fixtures"/fid/"experimental_continuous.svg"
    src=load_rgba(sp); roi=img(rp,"L")>127
    base=render_svg_edge(bas,width=512,height=512); current=render_svg_edge(full,width=512,height=512)
    oldrgba=render_svg_edge(old,width=512,height=512); folder=ART/"fixtures"/fid; folder.mkdir(parents=True,exist_ok=True)
    root=_read_tree(full); before=time.perf_counter()
    fits,traces=add_layers(root,appearance,src,base,folder,directions); fit_ms=(time.perf_counter()-before)*1000
    candidate=folder/"experimental_multidirectional.svg"; _save_svg(root,candidate)
    base_root=_read_tree(bas); bfits,btraces=add_layers(base_root,appearance,src,base,folder,directions)
    base_candidate=folder/"experimental_multidirectional_base_only.svg"; _save_svg(base_root,base_candidate)
    outputs={}
    timings={}
    for name,svg in (("base",bas),("current",full),("previous",old),("candidate",candidate),("candidateBase",base_candidate)):
        rgba,times=_render_timed(svg,folder/f"{name}_edge.png",1); outputs[name]=rgba
        timings[name]=float(statistics.median(times))
    skia=render_svg_skia(candidate,width=512,height=512,output_path=folder/"multidirectional_skia.png")
    if skia.get("status")=="PASS":
        common=(outputs["candidate"][...,3]>16)&(skia["rgba"][...,3]>16)
        de=de_map(white(outputs["candidate"]),white(skia["rgba"]))[common]
        renderer={"status":"PASS","alphaIoU":alpha_iou(outputs["candidate"],skia["rgba"]),
                  "commonAlphaMeanDeltaE00":float(de.mean()) if de.size else 0.0,
                  "commonAlphaP95DeltaE00":float(np.quantile(de,.95)) if de.size else 0.0}
    else: renderer={"status":skia.get("status"),"reason":skia.get("reason",skia.get("stderr")),"alphaIoU":None,
                    "commonAlphaMeanDeltaE00":None,"commonAlphaP95DeltaE00":None}
    detail=None
    if dp.is_file():
        dm=img(dp,"L")>127
        if dm.any():
            ann=next(v for v in jread(TASK14/"controlled_variants.json")["variants"] if v["fixtureId"]==fid)["analyticAnnotation"]["details"][0]
            target=np.broadcast_to(np.asarray(ann["paintRGB"],dtype=np.uint8),src.shape[:2]+(3,))
            recall=lambda x:float(np.mean(de_map(target,white(x))[dm]<=10))
            detail={"id":ann["id"],"pixels":int(dm.sum()),"targetRGB":ann["paintRGB"],
                    "currentRecall":recall(outputs["current"]),"candidateRecall":recall(outputs["candidate"]),
                    "delta":recall(outputs["candidate"])-recall(outputs["current"])}
    return {"fixture":fid,"sourceHash":sha(sp),"source":str(sp),"fullSvg":str(full),"baseSvg":str(bas),
       "previousSvg":str(old),"candidateSvg":str(candidate),"baseCandidateSvg":str(base_candidate),"roiPixels":int(roi.sum()),
       "metrics":{"base":metrics(src,outputs["base"],roi),"current":metrics(src,outputs["current"],roi),
          "previous1D":metrics(src,outputs["previous"],roi),"multidirectional":metrics(src,outputs["candidate"],roi),
          "multidirectionalBaseOnly":metrics(src,outputs["candidateBase"],roi)},
       "geometry":geometry(full,candidate),
       "alpha":{"candidateCurrentChangedPixels":int(np.count_nonzero(outputs["candidate"][...,3]!=outputs["current"][...,3])),
          "candidateBaseChangedPixels":int(np.count_nonzero(outputs["candidateBase"][...,3]!=outputs["base"][...,3])),
          "candidateCurrentIoU":alpha_iou(outputs["candidate"],outputs["current"]),
          "candidateBaseIoU":alpha_iou(outputs["candidateBase"],outputs["base"])},
       "detailRecall":detail,"validation":validate_svg(candidate),"complexity":_svg_complexity(candidate),
       "timingsMedianMs":timings,"fitTimeMs":fit_ms,"rendererCompatibility":renderer,
       "gradientLayers":fits,"optimizationTrace":traces,
       "renders":{k:str(folder/f"{k}_edge.png") for k in outputs},
       "_arrays":{"source":src,"roi":roi,**outputs}}

def production_scope():
    prior=jread(TASK15/"production_changes.json")["sourceScopeComparison"]["files"]; rows=[]
    for old in prior:
        p=BACKEND/old["path"]; actual=sha(p) if p.is_file() else None; expected=old["baselineSha256"].upper()
        rows.append({"path":old["path"],"baselineSha256":expected,"currentSha256":actual,"unchanged":actual==expected})
    return {"researchOnly":True,"productionFilesChanged":[],"prototypeConnectedToDispatcher":False,
       "sourceScopeFrom":"Task 08B.1.5 approved hash manifest","gitTrackedBaselineReliable":False,
       "unchangedCount":sum(x["unchanged"] for x in rows),"totalCount":len(rows),
       "allUnchanged":all(x["unchanged"] for x in rows),"files":rows}

def board(entries,path,cols=2):
    try: font=ImageFont.truetype("arial.ttf",18)
    except OSError: font=ImageFont.load_default()
    tw,th=512,550; rows=math.ceil(len(entries)/cols); out=Image.new("RGB",(tw*cols,th*rows),"white"); d=ImageDraw.Draw(out)
    for i,(label,arr) in enumerate(entries):
        x,y=i%cols*tw,i//cols*th; d.text((x+8,y+5),label,fill="black",font=font)
        out.paste(Image.fromarray(white(arr)),(x,y+32))
    out.save(path)

def visuals(primary,held,details,directions):
    p=primary["_arrays"]; board([("Source",p["source"]),("Base paint",p["base"]),("Current full",p["current"]),
        ("Task 08B.1.5 1D",p["previous"]),("08B.1.6 multi-direction",p["candidate"])],ART/"source_vs_all_models.png",3)
    board([("Base radial",p["base"]),("1D continuous",p["previous"]),("Multidirectional",p["candidate"]),("Current full",p["current"])],
          ART/"multidirectional_gradient_comparison.png",2)
    err=[]; false=[]
    for label,key in (("Base","base"),("Current","current"),("08B.1.5","previous"),("Multi","candidate")):
        de=de_map(white(p["source"]),white(p[key])); heat=cv2.cvtColor(cv2.applyColorMap(np.uint8(np.clip(de/20,0,1)*255),cv2.COLORMAP_TURBO),cv2.COLOR_BGR2RGB)
        err.append((label+" ΔE00",np.dstack((heat,np.full(heat.shape[:2],255,np.uint8)))))
        sl=rgb2lab(white(p["source"]).astype(np.float32)/255); ol=rgb2lab(white(p[key]).astype(np.float32)/255)
        sd,od=_lab_neighbor_delta(sl),_lab_neighbor_delta(ol); core=cv2.erode(p["roi"].astype(np.uint8),np.ones((3,3),np.uint8))>0
        m=core&(od>=3)&(od>sd*2.5+.75); marked=white(p["source"]).copy(); marked[m]=[255,0,0]
        false.append((label+" false edges",np.dstack((marked,np.full(marked.shape[:2],255,np.uint8)))))
    board(err,ART/"deltae00_comparison.png",2); board(false,ART/"false_edge_comparison.png",2)
    h=held["_arrays"]; board([("Heldout source",h["source"]),("Current",h["current"]),("1D",h["previous"]),("Multi",h["candidate"])],ART/"heldout_comparison.png",2)
    ent=[]
    for fid,row in details.items():
        a=row["_arrays"]; ent += [(fid+" source",a["source"]),(fid+" current",a["current"]),(fid+" multi",a["candidate"])]
    board(ent,ART/"detail_preservation_comparison.png",3)
    layer=Image.new("RGB",(1024,170),"white"); d=ImageDraw.Draw(layer)
    d.text((10,12),"Frozen base radial gradient → correction gradients → shared parent mask",fill="black")
    for i,a in enumerate(directions):
        x=50+i*490; d.rounded_rectangle((x,70,x+430,130),8,fill=(238,235,255),outline=(80,75,220),width=2)
        d.text((x+10,90),f"Native linearGradient · {a:.0f}° · {STOPS} stops · opacity {OPACITY}",fill=(25,25,60))
    layer.save(ART/"gradient_layer_visualization.png")

def run():
    ART.mkdir(parents=True,exist_ok=True); (ART/"analysis").mkdir(exist_ok=True)
    analysis,profiles,src,base,support,directions=choose_directions()
    config={"state":"FROZEN_BEFORE_HELDOUT","developmentFixture":DEV,"selectedDirectionsDegrees":directions,
       "directionSelection":"highest development residual variance explained by two piecewise-linear profiles among 0/45/90/135 degrees",
       "stopsPerGradient":STOPS,"correctionLayersPerGradientRegion":2,"constantStopOpacity":OPACITY,
       "sRGBStopColorFit":True,"secondDifferenceSmoothnessWeight":SMOOTHNESS,
       "sourceOverOrder":"base, correction 1, correction 2; parent mask applied once",
       "limits":{"correctionLayersPerRegion":4,"additionalGradientDefinitionsPerRegion":8,"stopsPerGradient":17},
       "heldoutTuning":False,"seed":None}
    write_json(ART/"residual_2d_analysis.json",analysis)
    write_json(ART/"residual_direction_profiles.json",profiles)
    write_json(ART/"residual_spatial_correlation.json",analysis["spatialScale"])
    write_json(ART/"base_model_limitation_report.json",{"verified":True,"base":"single radial gradient in frozen R5",
       "sourceHardBoundaryPixelsInsideSupport":analysis["annotatedHardBoundaryPixelsInsideSupport"],
       "residual":analysis["residualCIEDE2000"],"directionEvidence":analysis["directionPairSelection"],
       "interpretation":analysis["interpretation"]})
    # Residual visualization from actual frozen source and rendered base.
    delta=de_map(white(src),base); heat=cv2.cvtColor(cv2.applyColorMap(np.uint8(np.clip(delta/18,0,1)*255),cv2.COLORMAP_TURBO),cv2.COLOR_BGR2RGB)
    heat[~support]=white(src)[~support]; Image.fromarray(heat).save(ART/"residual_2d_heatmap.png")
    try: font=ImageFont.truetype("arial.ttf",15)
    except OSError: font=ImageFont.load_default()
    chart=Image.new("RGB",(1000,430),"white"); draw=ImageDraw.Draw(chart)
    for j,(ang,row) in enumerate(profiles["directions"].items()):
        y=j*100; draw.text((8,y+4),f"residual profile {ang}°",fill="black",font=font)
        for b in row["bins"]:
            if b["meanResidualLab"] is None: continue
            v=np.asarray(b["meanResidualLab"]); color=np.clip([128+2*v[0],128+1.5*v[1],128+1.5*v[2]],0,255).astype(int)
            x=135+int(b["bin"]/64*850); draw.rectangle((x,y+30,x+12,y+65),fill=tuple(int(c) for c in color))
    chart.save(ART/"residual_component_visualization.png")
    spec={"model":"low-complexity multi-directional continuous gradient composition","researchOnly":True,
       "productionIntegration":False,"baseRegionalPaintPreserved":True,"directionsDegrees":directions,
       "layers":["frozen radial/linear base paint","native linear correction 1","native linear correction 2"],
       "composite":"ordered SVG source-over; constant gradient-stop opacity; same frozen path; original parent mask applied once",
       "limits":config["limits"],"limitation":"Two 1D fields do not represent arbitrary x-y interaction."}
    write_json(ART/"multidirectional_model_spec.json",spec); write_json(ART/"fitting_configuration.json",config)
    inputs=[]
    for fid in FIXTURES:
        sp,_,full,ap,_=paths(fid); inputs.append({"fixture":fid,"sourceSha256":sha(sp),
          "frozenBaseSvgSha256":sha(TASK15/"fixtures"/fid/"base_paint_only.svg"),
          "currentSvgSha256":sha(full),"appearanceSha256":sha(ap),
          "previousPrototypeSha256":sha(TASK15/"fixtures"/fid/"experimental_continuous.svg")})
    write_json(ART/"reproducibility.json",{"frozenInputs":inputs,"directions":directions,
       "fittingConfigurationSha256":hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest().upper(),
       "randomSeed":None,"heldoutConfigFrozenBeforeRun":True})
    results={}
    for fid in FIXTURES:
        print(f"[08B.1.6] {fid}",flush=True); results[fid]=render_fixture(fid,directions)
    p=results[DEV]; h=results["smooth_alternate_heldout"]
    (ART/"experimental_multidirectional.svg").write_bytes(Path(p["candidateSvg"]).read_bytes())
    write_json(ART/"gradient_layer_parameters.json",{"directions":directions,"regions":p["gradientLayers"]})
    write_json(ART/"optimization_trace.json",{"optimizer":"regularized joint least-squares; sRGB; frozen config",
       "primary":p["optimizationTrace"],"fixtures":{k:v["optimizationTrace"] for k,v in results.items()}})
    pm=p["metrics"]
    names={"SOURCE_SELF":metrics(p["_arrays"]["source"],p["_arrays"]["source"],p["_arrays"]["roi"]),
      "BASE_PAINT_ONLY":pm["base"],"CURRENT_FULL_APPEARANCE":pm["current"],"TASK_08B_1_5_CONTINUOUS":pm["previous1D"],
      "TASK_08B_1_6_MULTIDIRECTIONAL":pm["multidirectional"]}
    write_json(ART/"primary_fidelity_comparison.json",{"fixture":DEV,"canvas":[512,512],"renderer":"Edge/Chromium",
       "sourceSha256":p["sourceHash"],"roiPixels":p["roiPixels"],"metrics":"fixed Task 08B.1.3 false-edge detector + CIEDE2000",
       "models":names,"targets":{"falseEdgeBelow1Percent":pm["multidirectional"]["falseEdgeFraction"]<.01,
       "meanNoWorseThanCurrent":pm["multidirectional"]["meanDeltaE00"]<=pm["current"]["meanDeltaE00"],
       "p95NoWorseThanCurrent":pm["multidirectional"]["p95DeltaE00"]<=pm["current"]["p95DeltaE00"]}})
    write_json(ART/"primary_false_edge_analysis.json",{"models":{k:{"fraction":v["falseEdgeFraction"],"pixels":v["falseHardEdgePixels"]} for k,v in names.items()},
       "detector":"Task 08B.1.3 fixed CIE76 neighboring pixel detector","smoothRoiAnnotatedHardBoundaryPixels":analysis["annotatedHardBoundaryPixelsInsideSupport"]})
    write_json(ART/"primary_color_error_analysis.json",{"metric":"CIEDE2000","models":{k:{n:v[n] for n in ("meanDeltaE00","p95DeltaE00","maxDeltaE00","samplePixels")} for k,v in names.items()}})
    write_json(ART/"primary_geometry_integrity.json",p["geometry"])
    write_json(ART/"primary_alpha_integrity.json",p["alpha"])
    hm=h["metrics"]; held_pass=(hm["multidirectional"]["falseEdgeFraction"]<.01 and
       hm["multidirectional"]["meanDeltaE00"]<=hm["current"]["meanDeltaE00"] and
       hm["multidirectional"]["p95DeltaE00"]<=hm["current"]["p95DeltaE00"])
    write_json(ART/"heldout_validation.json",{"fixture":"smooth_alternate_heldout","sourceSha256":h["sourceHash"],
       "frozenConfigBeforeEvaluation":True,"tunedOnHeldout":False,"current":hm["current"],"previous1D":hm["previous1D"],
       "multidirectional":hm["multidirectional"],"geometryUnchanged":h["geometry"]["geometryPathsIdentical"],
       "alphaChangedPixels":h["alpha"]["candidateCurrentChangedPixels"],"pass":held_pass,
       "generalizationClaim":"One heldout family cannot establish broad generalization."})
    details={fid:results[fid] for fid in ("small_sharp_color_detail","thin_highlight")}
    dr={}
    for fid,row in details.items():
        dr[fid]={"recall":row["detailRecall"],"geometry":row["geometry"],"alpha":row["alpha"],
                 "currentMetrics":row["metrics"]["current"],"candidateMetrics":row["metrics"]["multidirectional"]}
    write_json(ART/"detail_preservation_validation.json",{"fixtures":dr,
       "smallDetailPreserved":bool(dr["small_sharp_color_detail"]["recall"] and dr["small_sharp_color_detail"]["recall"]["candidateRecall"]>=dr["small_sharp_color_detail"]["recall"]["currentRecall"]),
       "thinHighlightPreserved":bool(dr["thin_highlight"]["recall"] and dr["thin_highlight"]["recall"]["candidateRecall"]>=dr["thin_highlight"]["recall"]["currentRecall"]),
       "geometryUnchanged":all(x["geometry"]["detailPathsIdentical"] for x in dr.values()),
       "alphaNonregression":all(x["alpha"]["candidateCurrentChangedPixels"]==0 for x in dr.values())})
    hard=results["hard_boundary_with_gradient"]; ann=img(TASK13/"fixtures/hard_boundary_with_gradient/ground_truth_hard_boundary.png","L")>127
    hard_m={}; hs=white(hard["_arrays"]["source"])
    for key in ("current","candidate"): hard_m[key]=gradient_metrics(hs,white(hard["_arrays"][key]),ann)
    ref=jread(TASK13/"false_edge_analysis.json")["fixtures"]["hard_boundary_with_gradient"]["engines"]["contour_preserving"]["boundaryStageComparison"]["fittedGeometryVsGroundTruth"]
    write_json(ART/"hard_boundary_regression.json",{"fixture":"hard_boundary_with_gradient","geometryBoundaryF1FrozenBaseline":ref,
       "geometryBoundaryF1PreservedByExactPathEquality":hard["geometry"]["geometryPathsIdentical"],
       "currentColorMeanDeltaE00":hard["metrics"]["current"]["meanDeltaE00"],
       "candidateColorMeanDeltaE00":hard["metrics"]["multidirectional"]["meanDeltaE00"],
       "candidateColorFidelityRegression":hard["metrics"]["multidirectional"]["meanDeltaE00"]>hard["metrics"]["current"]["meanDeltaE00"],
       "detectorMetrics":hard_m,"geometryUnchanged":hard["geometry"]["geometryPathsIdentical"]})
    matrix={fid:{"sourceHash":r["sourceHash"],"metrics":r["metrics"],"geometry":r["geometry"],"alpha":r["alpha"],
       "detailRecall":r["detailRecall"],"renderer":r["rendererCompatibility"]} for fid,r in results.items()}
    write_json(ART/"gradient_fixture_matrix.json",{"frozenDirections":directions,"tunedOnHeldout":False,"fixtures":matrix})
    renderer={fid:r["rendererCompatibility"] for fid,r in results.items()}
    renderer_pass=all(x.get("status")=="PASS" and x.get("alphaIoU",0)>=RENDERER_LIMITS["alphaIouMinimum"] and
       x.get("commonAlphaMeanDeltaE00",1e9)<=RENDERER_LIMITS["meanDeltaE00Maximum"] and
       x.get("commonAlphaP95DeltaE00",1e9)<=RENDERER_LIMITS["p95DeltaE00Maximum"] for x in renderer.values())
    write_json(ART/"renderer_compatibility.json",{"primaryRenderer":"Edge/Chromium","secondaryRenderer":"Svg.Skia",
       "limitsFromTask0815":RENDERER_LIMITS,"fixtures":renderer,"pass":renderer_pass})
    structure={}; complexity={}; within=True
    for fid,row in results.items():
        root=_read_tree(Path(row["candidateSvg"])); v=row["validation"]; c=row["complexity"]
        basec=_svg_complexity(Path(row["baseSvg"])); extra=c["gradientDefinitions"]-basec["gradientDefinitions"]
        layer_counts=[len(x["correctionLayers"]) for x in row["gradientLayers"].values()]
        stop_counts=[len(x["stops"]) for v in row["gradientLayers"].values() for x in v["correctionLayers"]]
        counts=[sum(1 for ch in el if ch.tag.rsplit("}",1)[-1]=="stop") for el in root.iter() if el.tag.rsplit("}",1)[-1] in {"linearGradient","radialGradient"}]
        structure[fid]={"validation":v,"complexity":c,"stopsPerGradient":counts}
        complexity[fid]={"base":basec,"candidate":c,"addedGradientDefinitions":extra,
          "maxLayersPerRegion":max(layer_counts,default=0),"maxStopsPerGradient":max(stop_counts,default=0),"renderMedianMs":row["timingsMedianMs"],"fitTimeMs":row["fitTimeMs"]}
        within &= extra<=8 and max(layer_counts,default=0)<=4 and max(stop_counts,default=0)<=17
    vector_only=all(x["validation"].get("xmlValid") and x["validation"].get("embeddedRasterElementCount")==0 and
                    x["validation"].get("embeddedRasterDataUriCount")==0 for x in structure.values())
    write_json(ART/"svg_structure_validation.json",{"fixtures":structure,"vectorOnlyAllFixtures":vector_only})
    write_json(ART/"performance_and_complexity.json",{"budget":{"maxLayersPerRegion":4,"maxAddedGradientDefinitionsPerRegion":8,"maxStops":17},
       "fixtures":complexity,"withinBudget":bool(within),"medianFitTimeMs":float(np.median([r["fitTimeMs"] for r in results.values()])),
       "medianEdgeRenderMs":float(np.median([r["timingsMedianMs"]["candidate"] for r in results.values()]))})
    prod=production_scope(); write_json(ART/"production_changes.json",prod)
    visuals(p,h,details,directions)
    compact={fid:{k:v for k,v in row.items() if k!="_arrays"} for fid,row in results.items()}
    write_json(ART/"fixture_results.json",{"fixtures":compact,"directions":directions})
    return {"results":results,"analysis":analysis,"directions":directions,"rendererPass":renderer_pass,
       "vectorOnly":vector_only,"complexityPass":bool(within),"heldoutPass":held_pass,"production":prod}

if __name__=="__main__":
    r=run(); p=r["results"][DEV]["metrics"]; h=r["results"]["smooth_alternate_heldout"]["metrics"]
    print(json.dumps({"directions":r["directions"],"primary":p,"heldout":h,"rendererPass":r["rendererPass"],
      "vectorOnly":r["vectorOnly"],"complexityPass":r["complexityPass"],"productionUnchanged":r["production"]["allUnchanged"]},indent=2))
