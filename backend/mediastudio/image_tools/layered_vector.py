"""Layered colour tracing: the single vectorisation method of Media Studio.

Pipeline
  1. Foreground mask  - alpha channel if present, else the background colour is
     flood-filled in from the image border; enclosed background-coloured holes
     (letter counters, gaps) are decided with an optional AI matte (rembg/u2net).
  2. Palette          - k-means in Lab space on foreground pixels, close colours merged.
  3. Layers           - stacked layers ordered from largest to smallest area; each
     layer covers its own pixels plus those of every layer drawn above it, so the
     stack has no hairline gaps between colours.
  4. Curves           - contours are simplified and turned into smooth cubic Beziers,
     keeping sharp corners sharp.
Only numpy + OpenCV are required; rembg is used when installed.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger("mediastudio.vector")

WORK_MAX_SIDE = 2048
WORK_MIN_SIDE = 1024


@dataclass(slots=True)
class LayeredVectorResult:
    svg: str
    width: int
    height: int
    path_count: int
    colors: list[str]
    background: str           # "alpha" | "border" | "none"
    ai_matte: bool
    seconds: float
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- helpers
def _to_lab(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)


def _hex(rgb) -> str:
    r, g, b = (int(round(float(v))) for v in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _remove_small(mask: np.ndarray, min_area: int) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = np.zeros(count, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_area
    return keep[labels]


# ---------------------------------------------------------------- 1. foreground
_AI_MODEL = "isnet-general-use"
_REMBG_SESSION = None
_DOWNLOAD_STARTED = False


def _model_file() -> Path:
    import os
    home = os.environ.get("U2NET_HOME") or os.path.join(
        os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~"), ".u2net")
    return Path(home) / f"{_AI_MODEL}.onnx"


def _download_model_in_background() -> None:
    """Fetch the AI model once, off the job thread, so no vector job waits on the network."""
    global _DOWNLOAD_STARTED
    if _DOWNLOAD_STARTED:
        return
    _DOWNLOAD_STARTED = True

    def worker() -> None:
        try:
            from rembg import new_session  # type: ignore
            new_session(_AI_MODEL)
            logger.info("Background matte model downloaded: %s", _model_file())
        except Exception:
            logger.exception("Background matte model download failed")

    import threading
    threading.Thread(target=worker, name="rembg-download", daemon=True).start()


def _ai_matte(rgb: np.ndarray) -> np.ndarray | None:
    global _REMBG_SESSION
    try:
        from rembg import new_session, remove  # type: ignore
    except Exception:
        return None
    if _REMBG_SESSION is None and not _model_file().is_file():
        # Model not on disk yet: never block the job on a download.
        _download_model_in_background()
        return None
    try:
        if _REMBG_SESSION is None:
            _REMBG_SESSION = new_session(_AI_MODEL)
        out = remove(Image.fromarray(rgb), session=_REMBG_SESSION, only_mask=True)
        return np.asarray(out.convert("L"), dtype=np.float32) / 255.0
    except Exception:
        logger.exception("AI background matte failed; continuing without it")
        return None


def foreground_mask(rgba: np.ndarray, use_ai: bool = True) -> tuple[np.ndarray, str, bool, str | None]:
    """Returns (mask, source, ai_used, background_hex)."""
    h, w = rgba.shape[:2]
    alpha = rgba[..., 3]
    if (alpha < 250).mean() > 0.01:
        return alpha >= 128, "alpha", False, None

    rgb = rgba[..., :3]
    lab = _to_lab(rgb)
    border = np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])
    bg = np.median(border, axis=0)
    border_dist = np.linalg.norm(border - bg, axis=1)
    if (border_dist < 12).mean() < 0.6:
        # Busy border (photo, full-bleed art): no background to remove.
        return np.ones((h, w), bool), "none", False, None

    # Background may be a soft gradient/vignette: estimate it locally from the
    # first rough pass, then compare each pixel to the background *near it*.
    rough = np.linalg.norm(lab - bg, axis=2) < 18
    weight = cv2.GaussianBlur(rough.astype(np.float32), (0, 0), max(h, w) / 40)
    field = np.stack([cv2.GaussianBlur(lab[..., c] * rough, (0, 0), max(h, w) / 40) for c in range(3)], -1)
    local_bg = np.where(weight[..., None] > 1e-3, field / np.maximum(weight[..., None], 1e-3), bg)
    diff = lab - local_bg
    # Light logo parts (cream, pale yellow) differ from a grey/white background
    # mostly in hue, so chroma differences count three times as much as lightness.
    dist = np.sqrt(diff[..., 0] ** 2 + 9.0 * (diff[..., 1] ** 2 + diff[..., 2] ** 2))
    candidate = (dist < 10).astype(np.uint8)
    count, labels = cv2.connectedComponents(candidate, connectivity=4)
    edge_ids = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    edge_ids = edge_ids[edge_ids != 0]
    outer_bg = np.isin(labels, edge_ids)

    fg = ~outer_bg
    # Enclosed background-coloured pockets: holes (letter counters) or real
    # white parts of the logo (eyes, highlights)? Ask the AI matte when present,
    # otherwise treat clean, pure-background pockets as holes.
    pockets = (candidate.astype(bool)) & fg
    pocket_count, pocket_labels, pocket_stats, _ = cv2.connectedComponentsWithStats(
        pockets.astype(np.uint8), connectivity=4)
    matte = _ai_matte(rgb) if (use_ai and pocket_count > 1) else None
    min_pocket = max(12, int(h * w * 0.00002))
    for index in range(1, pocket_count):
        if pocket_stats[index, cv2.CC_STAT_AREA] < min_pocket:
            continue
        region = pocket_labels == index
        if False:
            pass
        else:
            # Without AI: a pocket inside dark strokes (letter counters) is a hole;
            # a pocket inside light/colourful art (an eye, a highlight) is kept.
            # look past the pale JPEG halo that hugs the pocket: 3-8 px out
            r_in = max(3, max(h, w) // 600)
            near = cv2.dilate(region.astype(np.uint8), np.ones((2 * r_in + 1,) * 2, np.uint8)).astype(bool)
            far = cv2.dilate(region.astype(np.uint8), np.ones((6 * r_in + 1,) * 2, np.uint8)).astype(bool)
            ring = far & ~near & fg
            ring_l = float(lab[..., 0][ring].mean()) if ring.any() else 255.0
            is_hole = float(dist[region].mean()) < 9.0 and ring_l < 0.6 * float(bg[0])
            if matte is not None and float(matte[region].mean()) >= 0.5:
                is_hole = False          # the AI matte sees artwork here (eye, highlight)
        if is_hole:
            fg &= ~region

    # JPEG ringing leaves a pale, colourless halo around shapes. Drop neutral,
    # background-like pixels that touch the outside background.
    chroma = np.sqrt(diff[..., 1] ** 2 + diff[..., 2] ** 2)
    halo = (fg & (chroma < 3.5) & (np.abs(diff[..., 0]) < 28)).astype(np.uint8)
    halo_count, halo_labels = cv2.connectedComponents(halo, connectivity=8)
    if halo_count > 1:
        touching = cv2.dilate(outer_bg.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
        ids = np.unique(halo_labels[touching & (halo_labels > 0)])
        fg &= ~np.isin(halo_labels, ids)

    # Clean the mask: drop specks, fill pin-holes, smooth the edge.
    k = max(3, (max(h, w) // 400) | 1)
    fg = cv2.morphologyEx(fg.astype(np.uint8), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    fg = cv2.medianBlur(fg * 255, k + 2) > 127
    fg = _remove_small(fg, max(16, int(h * w * 0.00003)))
    holes = _remove_small(~fg, max(16, int(h * w * 0.00003)))
    fg = ~holes
    return fg, "border", matte is not None, _hex(np.median(rgb[outer_bg], axis=0))


# ---------------------------------------------------------------- 2. palette
def build_palette(rgb: np.ndarray, mask: np.ndarray, colors: int, merge_distance: float = 15.0) -> tuple[np.ndarray, np.ndarray]:
    """k-means in Lab on foreground pixels. Returns (labels HxW (-1 = bg), palette RGB Kx3)."""
    lab = _to_lab(rgb)
    pixels = lab[mask]
    if len(pixels) == 0:
        return np.full(mask.shape, -1, np.int32), np.zeros((0, 3))
    rng = np.random.default_rng(7)
    sample = pixels[rng.choice(len(pixels), min(len(pixels), 60_000), replace=False)]
    k = max(2, min(colors, len(np.unique(sample.astype(np.int16), axis=0))))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.5)
    _, _, centers = cv2.kmeans(sample, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)

    # merge near-identical centres (OpenCV 8-bit Lab units, about 2x CIE delta E)
    merged: list[np.ndarray] = []
    for c in centers:
        if all(np.linalg.norm(c - m) >= merge_distance for m in merged):
            merged.append(c)
    centers = np.array(merged, np.float32)

    flat = lab.reshape(-1, 3)
    labels = np.empty(len(flat), np.int32)
    for start in range(0, len(flat), 1_000_000):
        chunk = flat[start:start + 1_000_000]
        labels[start:start + len(chunk)] = np.argmin(
            ((chunk[:, None, :] - centers[None]) ** 2).sum(-1), axis=1)
    labels = labels.reshape(mask.shape)

    # Anti-aliasing fringes form thin "edge-only" clusters (dark outlines between
    # colours). Drop clusters that do not survive a small opening and reassign
    # their pixels to the nearest solid colour.
    keep = []
    for i in range(len(centers)):
        region = ((labels == i) & mask).astype(np.uint8)
        area = int(region.sum())
        solid = int(cv2.morphologyEx(region, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)).sum())
        keep.append(area > 0 and solid >= 0.5 * area)
    if any(keep) and not all(keep):
        kept = np.flatnonzero(keep)
        centers = centers[kept]
        flat_mask = mask.reshape(-1)
        idx = np.flatnonzero(flat_mask)
        sub = flat[idx]
        relabel = np.empty(len(sub), np.int32)
        for start in range(0, len(sub), 1_000_000):
            chunk = sub[start:start + 1_000_000]
            relabel[start:start + len(chunk)] = np.argmin(
                ((chunk[:, None, :] - centers[None]) ** 2).sum(-1), axis=1)
        new = np.zeros(len(flat), np.int32)
        new[idx] = relabel
        labels = new.reshape(mask.shape)
    # Majority filter removes salt-and-pepper speckle at colour boundaries.
    labels = cv2.medianBlur(labels.astype(np.uint8), 5).astype(np.int32)
    # Thin fringes (<= 2 px wide) where two colours meet take the colour of the
    # nearest solid region, so no coloured outline appears around shapes/letters.
    fringe = np.zeros(mask.shape, bool)
    for i in range(len(centers)):
        region = ((labels == i) & mask).astype(np.uint8)
        fringe |= region.astype(bool) & ~cv2.morphologyEx(region, cv2.MORPH_OPEN,
                                                          np.ones((3, 3), np.uint8)).astype(bool)
    solid = mask & ~fringe
    if fringe.any() and solid.any():
        _, nearest = cv2.distanceTransformWithLabels((~solid).astype(np.uint8), cv2.DIST_L2, 3,
                                                     labelType=cv2.DIST_LABEL_PIXEL)
        ys, xs = np.nonzero(solid)
        lookup = np.zeros(int(nearest.max()) + 1, np.int32)
        lookup[nearest[ys, xs]] = labels[ys, xs]
        labels[fringe] = lookup[nearest[fringe]]
    labels[~mask] = -1
    pal_lab = centers.reshape(-1, 1, 3).clip(0, 255).astype(np.uint8)
    palette = cv2.cvtColor(pal_lab, cv2.COLOR_LAB2RGB).reshape(-1, 3)
    return labels, palette


# ---------------------------------------------------------------- 4. curves
def _denoise_points(points: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian-smooth a closed contour (removes pixel jaggies / JPEG wobble)."""
    pts = points.reshape(-1, 2).astype(np.float64)
    n = len(pts)
    if sigma < 0.5 or n < 8:
        return points
    radius = int(min(n // 2 - 1, round(sigma * 3)))
    if radius < 1:
        return points
    k = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    k /= k.sum()
    padded = np.concatenate([pts[-radius:], pts, pts[:radius]])
    out = np.stack([np.convolve(padded[:, i], k, mode="valid") for i in range(2)], 1)
    return out.reshape(-1, 1, 2).astype(np.float32)


def _smooth_contour(points: np.ndarray, epsilon: float, corner_deg: float = 55.0) -> str:
    pts = cv2.approxPolyDP(points, epsilon, True).reshape(-1, 2).astype(np.float64)
    n = len(pts)
    if n < 3:
        return ""
    # Sharp corners stay as straight joins; others get Catmull-Rom tangents.
    prev, nxt = np.roll(pts, 1, 0), np.roll(pts, -1, 0)
    a, b = prev - pts, nxt - pts
    cos = (a * b).sum(1) / (np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1) + 1e-9)
    angle = np.degrees(np.arccos(np.clip(cos, -1, 1)))      # 180 = straight
    sharp = angle < (180 - corner_deg)
    tangent = (nxt - prev) / 6.0
    tangent[sharp] = 0.0
    f = lambda p: f"{p[0]:.1f} {p[1]:.1f}"
    parts = [f"M{f(pts[0])}"]
    for i in range(n):
        j = (i + 1) % n
        c1, c2 = pts[i] + tangent[i], pts[j] - tangent[j]
        if sharp[i] and sharp[j]:
            parts.append(f"L{f(pts[j])}")
        else:
            parts.append(f"C{f(c1)} {f(c2)} {f(pts[j])}")
    parts.append("Z")
    return "".join(parts)


def _mask_to_path(mask: np.ndarray, scale: float, epsilon: float, min_area: float, sigma: float = 0.6,
                  point_sigma: float = 0.0) -> str:
    # Supersample-free smoothing: blur the binary mask a little before contouring.
    soft = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), sigma)
    binary = (soft >= 0.5).astype(np.uint8)
    contours, _ = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    segments = []
    for contour in contours:
        if abs(cv2.contourArea(contour)) < min_area:
            continue
        d = _smooth_contour(_denoise_points(contour.astype(np.float32), point_sigma) * scale, epsilon * scale)
        if d:
            segments.append(d)
    return "".join(segments)


def _fit_fill(colors: np.ndarray, xs: np.ndarray, ys: np.ndarray, scale: float, gid: str,
              fallback) -> tuple[str, str | None]:
    """Fit colour = a + b*x + c*y; return a linearGradient when the region is shaded."""
    if len(colors) < 30:
        return _hex(fallback), None
    if len(colors) > 40_000:
        pick = np.random.default_rng(1).choice(len(colors), 40_000, replace=False)
        colors, xs, ys = colors[pick], xs[pick], ys[pick]
    x = xs.astype(np.float64); y = ys.astype(np.float64)
    cx, cy = x.mean(), y.mean()
    A = np.stack([np.ones_like(x), x - cx, y - cy], 1)
    coef, *_ = np.linalg.lstsq(A, colors.astype(np.float64), rcond=None)   # 3x3
    lum = np.array([0.299, 0.587, 0.114])
    gx, gy = coef[1] @ lum, coef[2] @ lum
    # use the direction of strongest overall colour change
    gvec = np.array([np.linalg.norm(coef[1]), np.linalg.norm(coef[2])]) * np.sign([gx or 1, gy or 1])
    norm = np.hypot(*gvec)
    mean = coef[0]
    if norm < 1e-6:
        return _hex(np.clip(mean, 0, 255)), None
    ux, uy = gvec / norm
    t = (x - cx) * ux + (y - cy) * uy
    t0, t1 = np.percentile(t, 2), np.percentile(t, 98)
    c0 = mean + coef[1] * (t0 * ux) + coef[2] * (t0 * uy)
    c1 = mean + coef[1] * (t1 * ux) + coef[2] * (t1 * uy)
    if np.abs(c1 - c0).max() < 10:          # barely shaded: a flat fill is enough
        return _hex(np.clip(mean, 0, 255)), None
    c0, c1 = np.clip(c0, 0, 255), np.clip(c1, 0, 255)
    x1, y1 = (cx + t0 * ux) * scale, (cy + t0 * uy) * scale
    x2, y2 = (cx + t1 * ux) * scale, (cy + t1 * uy) * scale
    grad = (f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{x1:.1f}" y1="{y1:.1f}" '
            f'x2="{x2:.1f}" y2="{y2:.1f}"><stop offset="0" stop-color="{_hex(c0)}"/>'
            f'<stop offset="1" stop-color="{_hex(c1)}"/></linearGradient>')
    return f"url(#{gid})", grad


# ---------------------------------------------------------------- public API
def vectorize(image: Image.Image, *, colors: int = 16, detail: int = 50,
              remove_background: bool = True, use_ai: bool = True,
              ocr_dir: Path | None = None, rebuild_text: bool = True,
              text_lines=None) -> LayeredVectorResult:
    """detail 0..100: higher = more colours kept, finer curves, smaller specks kept."""
    started = time.perf_counter()
    image = image.convert("RGBA")
    width, height = image.size
    side = max(width, height)
    factor = WORK_MAX_SIDE / side if side > WORK_MAX_SIDE else (WORK_MIN_SIDE / side if side < WORK_MIN_SIDE else 1.0)
    work = image.resize((round(width * factor), round(height * factor)), Image.LANCZOS) if factor != 1 else image
    rgba = np.asarray(work)
    rgb = rgba[..., :3]
    # Edge-preserving denoise flattens JPEG noise and soft glows into clean flats.
    rgb = cv2.bilateralFilter(rgb, 5, 25, 5)
    # Mean-shift flattens JPEG/upscale noise into clean colour areas while
    # keeping edges sharp (less speckle, cleaner layer outlines).
    rgb = cv2.pyrMeanShiftFiltering(np.ascontiguousarray(rgb), 6, 14)

    warnings: list[str] = []
    if remove_background:
        mask, bg_source, ai_used, _ = foreground_mask(rgba, use_ai)
        if bg_source == "none":
            warnings.append("Không tìm thấy nền đồng màu; giữ nguyên toàn bộ ảnh.")
    else:
        mask, bg_source, ai_used = np.ones(rgba.shape[:2], bool), "none", False

    detail = int(np.clip(detail, 0, 100))
    labels, palette = build_palette(rgb, mask, colors, merge_distance=20 - detail / 100 * 12)
    h, w = labels.shape
    if remove_background and bg_source == "border" and len(palette):
        # A near-white, colourless layer hugging the outline is JPEG fringe, not
        # artwork: strip it where it touches the transparent background. Enclosed
        # whites (eyes, highlights) are kept.
        pal_lab = cv2.cvtColor(palette.reshape(-1, 1, 3).astype(np.uint8), cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(float)
        outside = cv2.dilate((labels < 0).astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
        for i, c in enumerate(pal_lab):
            if c[0] > 200 and np.hypot(c[1] - 128, c[2] - 128) < 8:
                region = labels == i
                count, comp = cv2.connectedComponents(region.astype(np.uint8), connectivity=8)
                hits = np.unique(comp[outside & region])
                touching = np.isin(comp, hits[hits > 0])
                # only the thin rim is fringe; solid white artwork (tail tips,
                # highlights) survives a wide opening and is kept
                solid = cv2.morphologyEx(touching.astype(np.uint8), cv2.MORPH_OPEN,
                                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))).astype(bool)
                labels[touching & ~solid] = -1
        # pixel-level: neutral near-white pixels right at the outer edge are halo
        lab_px = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
        neutral_light = (lab_px[..., 0] > 205) & (np.hypot(lab_px[..., 1] - 128, lab_px[..., 2] - 128) < 7)
        near_out = cv2.dilate((labels < 0).astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
        labels[near_out & neutral_light] = -1
        mask = labels >= 0
    scale = 1.0 / factor
    epsilon = 1.6 - detail / 100 * 1.2              # 1.6 px (smooth) .. 0.4 px (exact)
    min_area = max(4.0, h * w * (0.00006 - detail / 100 * 0.00005))

    # Text: replace traced letters with real font outlines when a font matches.
    text_paths: list[str] = []
    if rebuild_text and len(palette):
        try:
            try:
                from . import text_rebuild  # type: ignore
            except ImportError:
                import text_rebuild  # type: ignore
            for line, index in text_rebuild.rebuild(rgb, labels, palette, ocr_dir, lines=text_lines):
                x0, y0, x1, y1 = line.box
                crop = labels[y0:y1, x0:x1]
                ring = np.concatenate([crop[0], crop[-1], crop[:, 0], crop[:, -1]])
                if (ring < 0).mean() > 0.85:
                    crop[:] = -1          # text on plain background: clear the whole line box
                else:
                    crop[crop == index] = -1
                contours, _ = cv2.findContours(line.hires.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
                ox, oy = line.origin
                k = text_rebuild.SUPER
                parts = []
                for contour in contours:
                    if abs(cv2.contourArea(contour)) < 4 * k * k:
                        continue
                    pts = (contour.astype(np.float32) / k + np.array([ox, oy], np.float32)) * scale
                    d = _smooth_contour(pts, 0.25 * scale, corner_deg=35.0)
                    if d:
                        parts.append(d)
                if parts:
                    text_paths.append(f'<path fill="{_hex(palette[index])}" fill-rule="evenodd" d="{"".join(parts)}"/>')
                    warnings.append(f"Chữ \"{line.text}\" được dựng lại bằng font {line.font}.")
            mask = labels >= 0
        except Exception:
            logger.exception("Text rebuild failed; keeping traced text")
    areas = np.array([(labels == i).sum() for i in range(len(palette))])
    order = [i for i in np.argsort(-areas) if areas[i] > 0]
    paths: list[str] = []
    defs: list[str] = []
    used: list[str] = []
    sigma = 2.2 - detail / 100 * 1.8
    point_sigma = max(h, w) / 2048 * (6.0 - detail / 100 * 5.0)
    yy, xx = np.mgrid[0:h, 0:w]
    source = rgb.astype(np.float32)
    grad_id = 0
    for rank, index in enumerate(order):
        # stacked: this colour + everything drawn above it (no gaps between colours)
        layer = np.isin(labels, order[rank:])
        own = labels == index
        count, comps, stats, _ = cv2.connectedComponentsWithStats(layer.astype(np.uint8), connectivity=8)
        for c in range(1, count):
            if stats[c, cv2.CC_STAT_AREA] < min_area:
                continue
            region = comps == c
            d = _mask_to_path(region, scale, epsilon, min_area, sigma=sigma, point_sigma=point_sigma)
            if not d:
                continue
            pixels = region & own
            # Sample colours away from edges: anti-aliased rims pull thin shapes
            # (letters, outlines) towards the background colour.
            core = cv2.erode(pixels.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
            if core.sum() >= 30:
                pixels = core
            elif pixels.sum() < 20:
                pixels = region
            if core.sum() < 0.25 * max(1, (region & own).sum()):
                # mostly thin strokes: a flat fill in the cluster colour looks crisper
                used.append(_hex(palette[index]))
                paths.append(f'<path fill="{_hex(palette[index])}" d="{d}"/>')
                continue
            fill, gradient = _fit_fill(source[pixels], xx[pixels], yy[pixels], scale, f"g{grad_id}",
                                       palette[index])
            if gradient:
                defs.append(gradient)
                grad_id += 1
            used.append(_hex(palette[index]))
            paths.append(f'<path fill="{fill}" d="{d}"/>')
    used = list(dict.fromkeys(used))
    paths.extend(text_paths)

    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}">\n'
           + (("<defs>\n" + "\n".join(defs) + "\n</defs>\n") if defs else "")
           + "\n".join(paths) + "\n</svg>\n")
    return LayeredVectorResult(svg, width, height, len(paths), used, bg_source, ai_used,
                               time.perf_counter() - started, warnings)


if __name__ == "__main__":
    import sys
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    result = vectorize(Image.open(src), colors=int(sys.argv[3]) if len(sys.argv) > 3 else 16)
    dst.write_text(result.svg, encoding="utf-8")
    print(result.path_count, result.background, result.ai_used if hasattr(result, "ai_used") else result.ai_matte,
          f"{result.seconds:.1f}s", len(result.svg) // 1024, "KB", result.colors)


# ---------------------------------------------------------------- cut-out mode
@dataclass(slots=True)
class CutoutResult:
    svg: str
    png: bytes
    width: int
    height: int
    background: str
    ai_matte: bool
    seconds: float
    warnings: list[str] = field(default_factory=list)


def cutout(image: Image.Image, *, use_ai: bool = True) -> CutoutResult:
    """Keep the logo's original pixels and make the background transparent.

    Same logo/background detection as the vector mode; edges get a soft 1 px
    alpha and the background colour is removed from edge pixels so no pale halo
    shows on dark backgrounds. Output: PNG plus an SVG that embeds it.
    """
    import base64
    import io

    started = time.perf_counter()
    rgba = np.asarray(image.convert("RGBA")).copy()
    h, w = rgba.shape[:2]
    # Detect at >= 2048 px (thin strokes survive the clean-up), then bring the
    # mask back to the original size: the down-sampling gives a natural soft edge.
    factor = max(1, int(np.ceil(2048 / max(h, w))))
    big = cv2.resize(rgba, (w * factor, h * factor), interpolation=cv2.INTER_CUBIC) if factor > 1 else rgba
    big_mask, source, ai_used, bg_hex = foreground_mask(big, use_ai)
    soft = cv2.resize(big_mask.astype(np.float32), (w, h), interpolation=cv2.INTER_AREA) if factor > 1 \
        else cv2.GaussianBlur(big_mask.astype(np.float32), (0, 0), 0.7)
    mask = soft >= 0.5
    warnings: list[str] = []
    if source == "none":
        warnings.append("Không tìm thấy nền đồng màu; giữ nguyên toàn bộ ảnh.")
    if source == "alpha":
        alpha = rgba[..., 3].astype(np.float32) / 255.0
    else:
        alpha = np.clip((soft - 0.1) / 0.8, 0.0, 1.0)
    if source == "border" and bg_hex:
        # Colour matting along the outline: every edge pixel is a mix of the
        # logo colour F (taken from the nearest solid logo pixel) and the
        # background B. Solve for the mix -> true alpha, and keep only F, so no
        # pale JPEG/anti-alias halo shows on dark backgrounds.
        bg = np.array([int(bg_hex[i:i + 2], 16) for i in (1, 3, 5)], np.float32)
        rgb = rgba[..., :3].astype(np.float32)
        band_r = max(2, max(h, w) // 220)
        # Only the rim that touches the transparent outside is matted; light
        # artwork inside the logo (eye, chest fur, tail tip) is never thinned.
        inside_depth = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 3)
        far_from_bg = np.linalg.norm(rgb - bg, axis=2) > 70
        core = mask & ((inside_depth > band_r + 1) | far_from_bg)
        band = cv2.dilate(mask.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & ~core
        if core.any() and band.any():
            _, nearest = cv2.distanceTransformWithLabels((~core).astype(np.uint8), cv2.DIST_L2, 3,
                                                         labelType=cv2.DIST_LABEL_PIXEL)
            ys, xs = np.nonzero(core)
            lookup = np.zeros((int(nearest.max()) + 1, 3), np.float32)
            lookup[nearest[ys, xs]] = rgb[ys, xs]
            F = lookup[nearest[band]]
            P = rgb[band]
            FB = F - bg
            denom = (FB * FB).sum(1)
            a = np.where(denom > 400, ((P - bg) * FB).sum(1) / np.maximum(denom, 1e-6), alpha[band])
            a = np.clip(a, 0.0, 1.0)
            a[a < 0.08] = 0.0
            alpha[band] = np.where(denom > 400, a, alpha[band])
            alpha[core] = 1.0
            rgb[band] = np.where((denom > 400)[:, None], F, rgb[band])
            rgba[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
        # Leftover pale specks along the outline (JPEG ringing that survived):
        # small, background-coloured blobs that touch the transparent outside.
        pale = (alpha > 0.3) & (np.linalg.norm(rgb - bg, axis=2) < 30)
        count, comp, stats, _ = cv2.connectedComponentsWithStats(pale.astype(np.uint8), connectivity=8)
        if count > 1:
            outside = cv2.dilate((alpha < 0.3).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
            limit = max(6, int(h * w * 0.0006))
            touching = np.unique(comp[outside & (comp > 0)])
            small = [i for i in touching if stats[i, cv2.CC_STAT_AREA] < limit]
            alpha[np.isin(comp, small)] = 0.0
    rgba[..., 3] = (alpha * 255).round().astype(np.uint8)

    buffer = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buffer, "PNG", optimize=True)
    png = buffer.getvalue()
    data = base64.b64encode(png).decode("ascii")
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n'
           f'<image width="{w}" height="{h}" href="data:image/png;base64,{data}" '
           f'xlink:href="data:image/png;base64,{data}"/>\n</svg>\n')
    return CutoutResult(svg, png, w, h, source, ai_used, time.perf_counter() - started, warnings)
