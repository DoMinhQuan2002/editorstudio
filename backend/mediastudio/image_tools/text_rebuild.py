"""Rebuild text lines with real fonts instead of tracing them.

OCR (EasyOCR, already shipped with the app) finds each text line and its string.
For every line the text is rendered with candidate fonts, fitted to the ink
(height, width/tracking, position) and scored against the traced letters; the
best match replaces the traced pixels with clean, sharp glyph outlines.
If OCR or fonts are unavailable, nothing changes and the traced text is kept.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("mediastudio.vector.text")

FONT_DIR = Path(__file__).resolve().parent / "fonts"
WINDOWS_FONTS = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
CANDIDATE_FONTS = [
    FONT_DIR / "Poppins-Regular.ttf", FONT_DIR / "Poppins-Medium.ttf", FONT_DIR / "Poppins-Bold.ttf",
    WINDOWS_FONTS / "GOTHIC.TTF", WINDOWS_FONTS / "GOTHICB.TTF",          # Century Gothic
    WINDOWS_FONTS / "segoeui.ttf", WINDOWS_FONTS / "segoeuib.ttf", WINDOWS_FONTS / "seguibl.ttf",
    WINDOWS_FONTS / "arial.ttf", WINDOWS_FONTS / "arialbd.ttf", WINDOWS_FONTS / "ariblk.ttf",
    WINDOWS_FONTS / "verdana.ttf", WINDOWS_FONTS / "verdanab.ttf",
    WINDOWS_FONTS / "tahoma.ttf", WINDOWS_FONTS / "tahomabd.ttf",
    WINDOWS_FONTS / "bahnschrift.ttf",
]
MIN_SCORE = 0.90          # IoU needed before a rendered line replaces the trace

_reader = None
_reader_failed = False
_lock = threading.Lock()


@dataclass(slots=True)
class TextLine:
    text: str
    box: tuple[int, int, int, int]     # x0, y0, x1, y1 in working pixels
    hires: np.ndarray                  # glyph mask rendered at SUPER x the ink box
    origin: tuple[int, int]            # top-left of the ink box in working pixels
    font: str
    score: float


SUPER = 4


def _get_reader(model_dir: Path | None):
    global _reader, _reader_failed
    with _lock:
        if _reader is not None or _reader_failed:
            return _reader
        try:
            import easyocr  # type: ignore
            try:
                import torch
                gpu = torch.cuda.is_available()
            except Exception:
                gpu = False
            kwargs = {"gpu": gpu, "verbose": False}
            if model_dir is not None:
                kwargs.update(model_storage_directory=str(model_dir), download_enabled=False)
            _reader = easyocr.Reader(["en"], **kwargs)
        except Exception:
            logger.exception("OCR unavailable; text will be traced instead of rebuilt")
            _reader_failed = True
        return _reader


def detect_lines(rgb: np.ndarray, model_dir: Path | None) -> list[tuple[str, tuple[int, int, int, int]]]:
    reader = _get_reader(model_dir)
    if reader is None:
        return []
    try:
        results = reader.readtext(rgb, detail=1, paragraph=False)
    except Exception:
        logger.exception("OCR failed")
        return []
    lines = []
    for quad, text, conf in results:
        text = " ".join(str(text).split())
        if conf < 0.45 or sum(ch.isalnum() for ch in text) < 2:
            continue
        xs = [p[0] for p in quad]; ys = [p[1] for p in quad]
        lines.append((text, (int(min(xs)), int(min(ys)), int(max(xs)) + 1, int(max(ys)) + 1)))
    return lines


def _render(text: str, font_path: Path, cap_px: float, tracking: float) -> np.ndarray | None:
    """Render text tightly; returns a binary ink mask (no padding)."""
    try:
        probe = ImageFont.truetype(str(font_path), 200)
    except Exception:
        return None
    # scale font so that ink height of the text (caps/x-height mix) matches cap_px
    bbox = probe.getbbox(text)
    ink_h = max(1, bbox[3] - bbox[1])
    size = max(6, int(round(200 * cap_px / ink_h)))
    font = ImageFont.truetype(str(font_path), size)
    advances = [font.getlength(ch) for ch in text]
    width = int(sum(advances) + tracking * max(0, len(text) - 1) + size * 2)
    height = int(size * 2)
    canvas = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(canvas)
    x = size * 0.5
    for ch, adv in zip(text, advances):
        draw.text((x, size * 0.3), ch, font=font, fill=255)
        x += adv + tracking
    arr = np.asarray(canvas) > 127
    ys, xs = np.nonzero(arr)
    if len(xs) == 0:
        return None
    return arr[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _match_score(a: np.ndarray, b: np.ndarray) -> float:
    """Overlap with a small tolerance (anti-aliasing, 1-2 px JPEG wobble)."""
    tol = max(1, int(round(a.shape[0] / 40)))
    kernel = np.ones((2 * tol + 1, 2 * tol + 1), np.uint8)
    da = cv2.dilate(a.astype(np.uint8), kernel).astype(bool)
    db = cv2.dilate(b.astype(np.uint8), kernel).astype(bool)
    hit = np.logical_and(a, db).sum() + np.logical_and(b, da).sum()
    return float(hit / max(1, a.sum() + b.sum()))


def _fit_line(text: str, target: np.ndarray, fonts: list[Path]):
    """target: binary ink mask cropped to its ink bbox. Returns (font_path, tracking_frac, IoU)."""
    th, tw = target.shape
    best = None
    for font_path in fonts:
        for tracking_frac in (-0.05, 0.0, 0.05, 0.1, 0.18, 0.28):
            r = _render(text, font_path, th, tracking_frac * th)
            if r is None:
                continue
            ratio = tw / r.shape[1]
            if not 0.9 <= ratio <= 1.1:       # big stretch = wrong font or spacing
                continue
            fitted = cv2.resize(r.astype(np.uint8), (tw, th), interpolation=cv2.INTER_NEAREST).astype(bool)
            iou = _match_score(fitted, target)
            if best is None or iou > best[2]:
                best = (font_path, tracking_frac, float(iou))
    return best


def _glyph_boxes(target: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Letter boxes (x0, y0, x1, y1) left to right; parts overlapping in x are merged."""
    count, _, stats, _ = cv2.connectedComponentsWithStats(target.astype(np.uint8), connectivity=8)
    min_area = max(4, target.shape[0] ** 2 // 400)
    boxes = sorted((int(x), int(y), int(x + bw), int(y + bh)) for x, y, bw, bh, a in stats[1:] if a >= min_area)
    merged: list[list[int]] = []
    for b in boxes:
        if merged and b[0] < merged[-1][2] - 0.3 * (b[2] - b[0]):
            m = merged[-1]
            m[0], m[1], m[2], m[3] = min(m[0], b[0]), min(m[1], b[1]), max(m[2], b[2]), max(m[3], b[3])
        else:
            merged.append(list(b))
    return [tuple(m) for m in merged]


def _render_char(ch: str, font_path: Path, w: int, h: int) -> np.ndarray | None:
    r = _render(ch, font_path, 200, 0)
    if r is None or w < 1 or h < 1:
        return None
    return cv2.resize(r.astype(np.uint8) * 255, (w, h), interpolation=cv2.INTER_AREA) >= 128


def _fit_glyphs(text: str, target: np.ndarray, fonts: list[Path]):
    """Per-letter fit: keeps the exact position and size of every traced letter and
    swaps only its shape for the font's. Returns (font_path, boxes, score) or None."""
    chars = [c for c in text if not c.isspace()]
    boxes = _glyph_boxes(target)
    # Letters that touch (e.g. "CT" in heavy type) come out as one blob: split
    # the widest blob at its thinnest column until the counts agree.
    while 0 < len(boxes) < len(chars):
        widths = [b[2] - b[0] for b in boxes]
        i = int(np.argmax(widths))
        x0, y0, x1, y1 = boxes[i]
        if widths[i] < 1.4 * np.median(widths):
            break
        column = target[y0:y1, x0:x1].sum(0).astype(float)
        lo, hi = int(len(column) * 0.3), int(len(column) * 0.7)
        cut = x0 + lo + int(np.argmin(column[lo:hi]))
        parts = []
        for a, b in ((x0, cut), (cut, x1)):
            ys = np.nonzero(target[y0:y1, a:b].any(1))[0]
            parts.append((a, y0 + int(ys.min()), b, y0 + int(ys.max()) + 1) if len(ys) else (a, y0, b, y1))
        boxes[i:i + 1] = parts
    if len(boxes) != len(chars):
        return None
    best = None
    for font_path in fonts:
        total = 0.0
        for ch, (x0, y0, x1, y1) in zip(chars, boxes):
            g = _render_char(ch, font_path, x1 - x0, y1 - y0)
            if g is None:
                total = -1
                break
            total += _match_score(g, target[y0:y1, x0:x1])
        score = total / len(chars)
        if best is None or score > best[2]:
            best = (font_path, boxes, score)
    return best


def _render_glyphs(text: str, font_path: Path, boxes, shape) -> np.ndarray:
    chars = [c for c in text if not c.isspace()]
    out = np.zeros((shape[0] * SUPER, shape[1] * SUPER), bool)
    for ch, (x0, y0, x1, y1) in zip(chars, boxes):
        g = _render_char(ch, font_path, (x1 - x0) * SUPER, (y1 - y0) * SUPER)
        if g is not None:
            out[y0 * SUPER:y1 * SUPER, x0 * SUPER:x1 * SUPER] |= g
    return out


def _render_fitted(text: str, font_path: Path, tracking_frac: float, th: int, tw: int) -> np.ndarray:
    big_h, big_w = th * SUPER, tw * SUPER
    r = _render(text, font_path, big_h, tracking_frac * big_h)
    r = cv2.resize(r.astype(np.uint8) * 255, (big_w, big_h), interpolation=cv2.INTER_AREA)
    return r >= 128


def rebuild(rgb: np.ndarray, labels: np.ndarray, palette: np.ndarray,
            model_dir: Path | None = None, lines=None) -> list[tuple[TextLine, int]]:
    """Find text, fit fonts. Returns [(line, palette_index)] for lines good enough to replace."""
    fonts = [p for p in CANDIDATE_FONTS if p.is_file()]
    if not fonts:
        return []
    if lines is None:
        lines = detect_lines(rgb, model_dir)
    h, w = labels.shape
    out = []
    for text, (x0, y0, x1, y1) in lines:
        pad = max(2, (y1 - y0) // 6)
        x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
        x1, y1 = min(w, x1 + pad), min(h, y1 + pad)
        crop = labels[y0:y1, x0:x1]
        valid = crop[crop >= 0]
        if valid.size == 0:
            continue
        # text colour = the darkest/most frequent cluster that is not the surrounding colour
        counts = np.bincount(valid, minlength=len(palette))
        index = int(np.argmax(counts))
        ink = crop == index
        ys, xs = np.nonzero(ink)
        if len(xs) < 30:
            continue
        iy0, iy1, ix0, ix1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        target = ink[iy0:iy1, ix0:ix1]
        glyph_fit = _fit_glyphs(text, target, fonts)
        if glyph_fit is not None and glyph_fit[2] >= MIN_SCORE:
            fit = (glyph_fit[0], None, glyph_fit[2])
            hires = _render_glyphs(text, glyph_fit[0], glyph_fit[1], target.shape)
        else:
            fit = _fit_line(text, target, fonts)
            if fit is None or fit[2] < MIN_SCORE:
                logger.info("Text '%s' kept as trace (best score %.2f / glyph %.2f)", text,
                            0 if fit is None else fit[2], 0 if glyph_fit is None else glyph_fit[2])
                continue
            hires = _render_fitted(text, fit[0], fit[1], target.shape[0], target.shape[1])
        out.append((TextLine(text, (x0, y0, x1, y1), hires, (x0 + ix0, y0 + iy0), fit[0].stem, fit[2]), index))
        logger.info("Text '%s' rebuilt with %s (IoU %.2f)", text, fit[0].stem, fit[2])
    return out
