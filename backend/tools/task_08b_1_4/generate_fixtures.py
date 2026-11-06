from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

BACKEND = Path(__file__).resolve().parents[2]
ARTIFACTS = BACKEND / "artifacts/contour_preserving/task_08b_1_4"
FIXTURES = ARTIFACTS / "fixtures"
SIZE = 512
SSAA = 4


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _color(t: np.ndarray, knots: list[tuple[float, tuple[int, int, int]]]) -> np.ndarray:
    positions = np.asarray([row[0] for row in knots], dtype=np.float64)
    colors = np.asarray([row[1] for row in knots], dtype=np.float64)
    return np.stack([np.interp(t, positions, colors[:, i]) for i in range(3)], axis=-1)


def _common_field(cx: float = 256.0, cy: float = 256.0, radius: float = 192.0,
                  phase: float = 0.73) -> tuple[np.ndarray, np.ndarray, str]:
    y, x = np.indices((SIZE * SSAA, SIZE * SSAA), dtype=np.float64)
    x = (x + 0.5) / SSAA
    y = (y + 0.5) / SSAA
    dx, dy = x - cx, y - cy
    r = np.sqrt((dx / radius) ** 2 + (dy / radius) ** 2)
    theta = np.arctan2(dy, dx)
    inside = r <= 1.0
    t = np.clip(.74 * r ** 1.55 + .26 * r * (.5 + .5 * np.cos(2.2 * theta + phase)), 0, 1) ** 1.18
    rgb = _color(t, [(0.0, (32, 67, 138)), (.45, (38, 157, 183)), (1.0, (244, 190, 91))])
    return rgb, inside, "t=clip(0.74*r^1.55+0.26*r*(0.5+0.5*cos(2.2*theta+0.73)),0,1)^1.18; three-stop piecewise-linear RGB"


def _make_base(fid: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    if fid == "smooth_alternate_heldout":
        y, x = np.indices((SIZE * SSAA, SIZE * SSAA), dtype=np.float64)
        x = (x + .5) / SSAA
        y = (y + .5) / SSAA
        dx, dy = x - 242.0, y - 268.0
        radius = 178.0
        r = np.sqrt((dx / radius) ** 2 + (dy / radius) ** 2)
        theta = np.arctan2(dy, dx)
        inside = r <= 1.0
        t = np.clip(.60 * r ** 1.83 + .40 * r * (.5 + .5 * np.sin(3.0 * theta + 1.17)), 0, 1) ** 1.31
        rgb = _color(t, [(0., (72, 43, 126)), (.31, (41, 139, 183)), (.72, (233, 113, 86)), (1., (249, 217, 121))])
        formula = "held-out: center=(242,268), radius=178; t=clip(0.60*r^1.83+0.40*r*(0.5+0.5*sin(3*theta+1.17)),0,1)^1.31; four-stop RGB"
    else:
        rgb, inside, formula = _common_field()
    alpha = np.where(inside, 255, 0).astype(np.uint8)
    rgba_hi = np.dstack([np.rint(rgb).clip(0, 255).astype(np.uint8), alpha])
    source = np.asarray(Image.fromarray(rgba_hi, "RGBA").resize((SIZE, SIZE), Image.Resampling.LANCZOS), dtype=np.uint8).copy()
    content = source[..., 3] >= 250
    truth = np.zeros((SIZE, SIZE), dtype=np.uint8)
    annotation: dict = {"details": [], "heldout": fid == "smooth_alternate_heldout"}

    if fid == "small_sharp_color_detail":
        y, x = np.indices((SIZE, SIZE))
        spot = ((x - 270) / 10.0) ** 2 + ((y - 218) / 7.0) ** 2 <= 1.0
        spot &= content
        source[spot, :3] = np.array([28, 31, 64], dtype=np.uint8)
        truth[spot] = 255
        annotation["details"].append({"id": "small_sharp_color_detail", "mask": "detail_mask.png",
            "shape": "ellipse center=(270,218), radii=(10,7), clipped to foreground",
            "paint": "solid RGB [28,31,64]", "isHeldout": False})
    elif fid == "thin_highlight":
        high = np.zeros((SIZE * SSAA, SIZE * SSAA), dtype=np.uint8)
        points = []
        for t in np.linspace(0, 1, 96):
            px = 213.0 + 84.0 * t
            py = 205.0 + 18.0 * t + 12.0 * np.sin(np.pi * t)
            points.append([int(round(px * SSAA)), int(round(py * SSAA))])
        cv2.polylines(high, [np.asarray(points, np.int32)], False, 255, thickness=9, lineType=cv2.LINE_AA)
        highlight_hi = (high > 127) & (np.asarray(Image.fromarray(np.where(inside, 255, 0).astype(np.uint8)).resize((SIZE*SSAA, SIZE*SSAA), Image.Resampling.NEAREST)) > 127)
        mask_native = np.asarray(Image.fromarray(highlight_hi.astype(np.uint8) * 255).resize((SIZE, SIZE), Image.Resampling.LANCZOS), dtype=np.uint8) > 127
        source[mask_native, :3] = np.array([255, 242, 199], dtype=np.uint8)
        truth[mask_native] = 255
        annotation["details"].append({"id": "thin_highlight", "mask": "detail_mask.png",
            "shape": "analytic quadratic-like curve sampled at 96 points; 2.25px nominal width; foreground clipped",
            "paint": "solid RGB [255,242,199]", "isHeldout": False})

    soft = cv2.erode(content.astype(np.uint8), np.ones((9, 9), np.uint8), iterations=1) > 0
    if truth.any():
        excluded = cv2.dilate(truth.astype(np.uint8), np.ones((13, 13), np.uint8), iterations=1) > 0
        soft &= ~excluded
    annotation["sourceFormula"] = formula
    annotation["canvas"] = [SIZE, SIZE]
    annotation["supersampling"] = SSAA
    annotation["foreground"] = "analytic circle, independent from the internal color/detail annotation"
    return source, content, soft, {**annotation, "detailMask": truth}


def generate() -> dict:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    records = []
    for fid in ("smooth_alternate_heldout", "small_sharp_color_detail", "thin_highlight"):
        source, content, soft, annotation = _make_base(fid)
        target = FIXTURES / fid
        target.mkdir(parents=True, exist_ok=True)
        source_path = target / "source.png"
        alpha_path = target / "ground_truth_alpha.png"
        soft_path = target / "ground_truth_soft_gradient_roi.png"
        detail_path = target / "detail_mask.png"
        labels_path = target / "semantic_labels.png"
        detail_mask = annotation.pop("detailMask")
        labels = np.zeros((SIZE, SIZE), dtype=np.uint8)
        labels[content] = 1
        labels[detail_mask.astype(bool)] = 2
        Image.fromarray(source, "RGBA").save(source_path)
        Image.fromarray(content.astype(np.uint8) * 255, "L").save(alpha_path)
        Image.fromarray(soft.astype(np.uint8) * 255, "L").save(soft_path)
        Image.fromarray(detail_mask, "L").save(detail_path)
        Image.fromarray(labels, "L").save(labels_path)
        row = {"fixtureId": fid, "split": "heldout" if fid == "smooth_alternate_heldout" else "targeted_validation",
               "sourceSha256": _hash(source_path), "size": [SIZE, SIZE], "formula": annotation["sourceFormula"],
               "analyticAnnotation": annotation, "paths": {"source": source_path.relative_to(ARTIFACTS).as_posix(),
                   "alpha": alpha_path.relative_to(ARTIFACTS).as_posix(), "softRoi": soft_path.relative_to(ARTIFACTS).as_posix(),
                   "detailMask": detail_path.relative_to(ARTIFACTS).as_posix(),
                   "semanticLabels": labels_path.relative_to(ARTIFACTS).as_posix()},
               "validation": {"contentPixels": int(content.sum()), "softRoiPixels": int(soft.sum()),
                   "detailPixels": int(np.asarray(Image.open(detail_path)).astype(bool).sum()),
                   "hasInternalDetail": bool(fid != "smooth_alternate_heldout")}}
        records.append(row)
    output = {"schemaVersion": 1, "task": "08B.1.4", "maxSyntheticVariantCount": 3,
              "variants": records, "allValid": all(row["validation"]["contentPixels"] > 10000 and row["validation"]["softRoiPixels"] > 10000 for row in records)}
    (ARTIFACTS / "controlled_variants.json").write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output


if __name__ == "__main__":
    print(json.dumps(generate(), indent=2, ensure_ascii=False))
