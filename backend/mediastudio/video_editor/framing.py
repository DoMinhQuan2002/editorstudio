"""Subject-centred placement for cut-out overlays.

The reference Fall Diary template does not shrink a cut-out into a box. It keeps
the whole photo frame, enlarges it so the photo is 1.35x the canvas height, and
slides it so the visible subject sits slightly below the canvas centre. The
slide is limited so that no photo edge moves more than a small margin inside
the canvas. These numbers were measured by registering every reference frame
against its source photo (SIFT + RANSAC similarity):

* photo height / canvas height ............ 1.35 on all seven photos
* subject bounding-box centre ............. (0.50 W, 0.59-0.60 H)
* photo edge may enter the canvas by ...... 0.06 of the canvas (two photos hit it)

Because the photo keeps its transparent margin, this also keeps the cut-out at
its natural size relative to the frame instead of blowing up a small subject.
The result is expressed in the renderer's ``contain`` semantics:
``x = (W - w) / 2 + W * positionX`` after the image is fitted inside W x H and
multiplied by ``scale``.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image

SUBJECT_HEIGHT_RATIO = 1.35
SUBJECT_TARGET_X = 0.50
SUBJECT_TARGET_Y = 0.60
SUBJECT_EDGE_MARGIN = 0.06
# Alpha above this counts as subject when measuring the bounding box; a low
# value would let faint matting haze widen the box.
SUBJECT_ALPHA_THRESHOLD = 32
# Limits accepted by the composition graph validator.
_SCALE_RANGE = (0.1, 5.0)
_POSITION_RANGE = (-2.0, 2.0)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def subject_centered_placement(
    image_size: tuple[int, int],
    subject_box: tuple[float, float, float, float] | None,
    canvas_size: tuple[int, int],
    *,
    height_ratio: float = SUBJECT_HEIGHT_RATIO,
    target: tuple[float, float] = (SUBJECT_TARGET_X, SUBJECT_TARGET_Y),
    edge_margin: float = SUBJECT_EDGE_MARGIN,
) -> tuple[float, float, float]:
    """Return ``(scale, positionX, positionY)`` for a ``contain``-fitted image.

    ``subject_box`` is ``(left, top, right, bottom)`` in image pixels, or
    ``None`` when the image has no visible subject (the photo is then centred).
    """
    image_w, image_h = image_size
    canvas_w, canvas_h = canvas_size
    if image_w <= 0 or image_h <= 0 or canvas_w <= 0 or canvas_h <= 0:
        return 1.0, 0.0, 0.0
    fit = min(canvas_w / image_w, canvas_h / image_h)
    scale = _clamp(height_ratio * canvas_h / (image_h * fit), *_SCALE_RANGE)
    shown_w = image_w * fit * scale / canvas_w  # displayed width in canvas widths
    shown_h = image_h * fit * scale / canvas_h  # displayed height in canvas heights

    if subject_box is None:
        u, v = 0.5, 0.5
        target_x, target_y = 0.5, 0.5
    else:
        left, top, right, bottom = subject_box
        u = (left + right) / 2.0 / image_w
        v = (top + bottom) / 2.0 / image_h
        target_x, target_y = target

    position_x = (target_x - 0.5) + shown_w * (0.5 - u)
    position_y = (target_y - 0.5) + shown_h * (0.5 - v)

    # Keep the photo covering the canvas up to edge_margin on every side. When
    # the photo is narrower than the canvas the allowed range is empty and the
    # photo simply stays centred on that axis.
    limit_x = (shown_w - 1.0) / 2.0 + edge_margin
    limit_y = (shown_h - 1.0) / 2.0 + edge_margin
    position_x = _clamp(position_x, -limit_x, limit_x) if limit_x > 0 else 0.0
    position_y = _clamp(position_y, -limit_y, limit_y) if limit_y > 0 else 0.0
    return (
        scale,
        _clamp(position_x, *_POSITION_RANGE),
        _clamp(position_y, *_POSITION_RANGE),
    )


def subject_box_of(image: Image.Image) -> tuple[int, int, int, int] | None:
    """Bounding box of the clearly opaque pixels of an RGBA image."""
    if image.mode != "RGBA":
        return None
    alpha = image.getchannel("A")
    return alpha.point(lambda value: 255 if value > SUBJECT_ALPHA_THRESHOLD else 0).getbbox()


@lru_cache(maxsize=256)
def _cached_measure(path: str, mtime_ns: int, size: int) -> tuple[tuple[int, int], tuple[int, int, int, int] | None]:
    del mtime_ns, size  # part of the cache key only
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
        return image.size, subject_box_of(image)


# Correction measured on the reference app's own rendered video (2026-10-29).
# The 1.35 / (0.5, 0.6) numbers above came from registering the reference
# against a mis-sized canvas. Registering the reference video directly against
# this app's render - background matched to background, every overlay matched
# to its overlay, six scenes - gave the same similarity for every overlay:
# the reference draws each overlay at 0.741x our size, scaled about the point
# (0.504 W, 0.21 H) of the canvas (spread across scenes 0.740-0.757). Applying
# that map to the placement above reproduces the reference: photo height about
# 1.0x the canvas, subject a little above the middle.
REFERENCE_SCALE = 0.741
REFERENCE_SHIFT_X = 0.001
REFERENCE_SHIFT_Y = -0.0748


def placement_for_file(path: Path, canvas_size: tuple[int, int]) -> tuple[float, float, float]:
    """Subject-centred placement for a cut-out PNG on disk, as the reference app does it."""
    stat = path.stat()
    image_size, box = _cached_measure(str(path), stat.st_mtime_ns, stat.st_size)
    scale, position_x, position_y = subject_centered_placement(image_size, box, canvas_size)
    return (
        _clamp(scale * REFERENCE_SCALE, *_SCALE_RANGE),
        _clamp(REFERENCE_SHIFT_X + REFERENCE_SCALE * position_x, *_POSITION_RANGE),
        _clamp(REFERENCE_SHIFT_Y + REFERENCE_SCALE * position_y, *_POSITION_RANGE),
    )


def apply_subject_placement(attributes: dict, path: Path, canvas_size: tuple[int, int]) -> dict:
    """Resolve the final scale/position of a clip.

    ``subjectCentered`` replaces the stored placement with the reference
    framing. ``userScale``/``userOffsetX``/``userOffsetY`` - the manual edit made
    on the edit screen - are then applied on top: the size is multiplied around
    the image centre and the image is shifted by a fraction of the canvas.
    """
    user_scale = float(attributes.get("userScale", 1.0))
    user_x = float(attributes.get("userOffsetX", 0.0))
    user_y = float(attributes.get("userOffsetY", 0.0))
    centered = attributes.get("subjectCentered") is True
    if not centered and user_scale == 1.0 and not user_x and not user_y:
        return attributes
    resolved = dict(attributes)
    if centered:
        scale, position_x, position_y = placement_for_file(path, canvas_size)
        resolved.update(fitMode="contain", scale=scale, positionX=position_x, positionY=position_y)
    resolved["scale"] = _clamp(float(resolved["scale"]) * user_scale, *_SCALE_RANGE)
    resolved["positionX"] = _clamp(float(resolved["positionX"]) + user_x, *_POSITION_RANGE)
    resolved["positionY"] = _clamp(float(resolved["positionY"]) + user_y, *_POSITION_RANGE)
    return resolved
