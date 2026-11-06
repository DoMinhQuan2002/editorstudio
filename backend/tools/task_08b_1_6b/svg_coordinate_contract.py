"""SVG linear-gradient coordinate contract for the isolated 08B.1.6B study.

Coordinates are evaluated at raster pixel centers after mapping the requested
output viewport into the SVG viewBox.  The helper deliberately covers linear
gradients only: that is the frozen prototype's model family.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import numpy as np


_TRANSFORM = re.compile(r"([A-Za-z]+)\s*\(([^)]*)\)")
_NUMBER = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?")


@dataclass(frozen=True)
class SvgViewport:
    view_box: tuple[float, float, float, float]
    width: float
    height: float
    preserve_aspect_ratio: str


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _length(value: str | None, fallback: float) -> float:
    if value is None:
        return fallback
    match = re.match(r"^\s*([-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?)", value)
    if not match:
        return fallback
    return float(match.group(1))


def viewport_from_svg(root: ET.Element, output_shape: tuple[int, int]) -> SvgViewport:
    """Resolve the SVG viewBox to an output pixel viewport, honoring aspect ratio."""
    h, w = output_shape
    raw_vb = root.attrib.get("viewBox") or root.attrib.get("viewbox")
    if raw_vb:
        nums = [float(x) for x in _NUMBER.findall(raw_vb)]
        if len(nums) != 4 or nums[2] <= 0 or nums[3] <= 0:
            raise ValueError(f"Invalid SVG viewBox: {raw_vb!r}")
        vb = tuple(nums)
    else:
        vb = (0.0, 0.0, _length(root.attrib.get("width"), float(w)),
              _length(root.attrib.get("height"), float(h)))
    par = root.attrib.get("preserveAspectRatio", "xMidYMid meet").strip()
    if par.startswith("defer "):
        par = par[6:].strip()
    return SvgViewport(vb, float(w), float(h), par)


def _pixel_to_user(shape: tuple[int, int], viewport: SvgViewport) -> np.ndarray:
    h, w = shape
    min_x, min_y, vb_w, vb_h = viewport.view_box
    align = viewport.preserve_aspect_ratio.split()
    mode = align[0] if align else "xMidYMid"
    meet_or_slice = align[1] if len(align) > 1 else "meet"
    yy, xx = np.indices((h, w), dtype=np.float64)
    px, py = xx + 0.5, yy + 0.5
    if mode.lower() == "none":
        sx, sy = viewport.width / vb_w, viewport.height / vb_h
        ux = min_x + px / sx
        uy = min_y + py / sy
    else:
        scale = (min(viewport.width / vb_w, viewport.height / vb_h)
                 if meet_or_slice != "slice" else
                 max(viewport.width / vb_w, viewport.height / vb_h))
        extra_x = viewport.width - vb_w * scale
        extra_y = viewport.height - vb_h * scale
        ax = 0.0 if "xMin" in mode else extra_x * 0.5 if "xMid" in mode else extra_x
        ay = 0.0 if "YMin" in mode else extra_y * 0.5 if "YMid" in mode else extra_y
        ux = min_x + (px - ax) / scale
        uy = min_y + (py - ay) / scale
    return np.stack((ux, uy), axis=-1)


def _transform_matrix(value: str | None) -> np.ndarray:
    """Parse SVG's affine transform list into a column-vector matrix."""
    out = np.eye(3, dtype=np.float64)
    if not value:
        return out
    consumed = ""
    for name, raw in _TRANSFORM.findall(value):
        args = [float(x) for x in _NUMBER.findall(raw)]
        key = name.lower()
        m = np.eye(3, dtype=np.float64)
        if key == "matrix" and len(args) == 6:
            a, b, c, d, e, f = args
            m = np.array([[a, c, e], [b, d, f], [0.0, 0.0, 1.0]])
        elif key == "translate" and len(args) in (1, 2):
            m[0, 2], m[1, 2] = args[0], args[1] if len(args) == 2 else 0.0
        elif key == "scale" and len(args) in (1, 2):
            m[0, 0], m[1, 1] = args[0], args[1] if len(args) == 2 else args[0]
        elif key == "rotate" and len(args) in (1, 3):
            angle = math.radians(args[0]); c, s = math.cos(angle), math.sin(angle)
            rot = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
            if len(args) == 3:
                x, y = args[1:]
                to_origin = np.array([[1, 0, -x], [0, 1, -y], [0, 0, 1]], dtype=np.float64)
                from_origin = np.array([[1, 0, x], [0, 1, y], [0, 0, 1]], dtype=np.float64)
                m = from_origin @ rot @ to_origin
            else:
                m = rot
        elif key in ("skewx", "skewy") and len(args) == 1:
            tangent = math.tan(math.radians(args[0]))
            if key == "skewx": m[0, 1] = tangent
            else: m[1, 0] = tangent
        else:
            raise ValueError(f"Unsupported or malformed SVG transform: {name}({raw})")
        out = out @ m
    # Do not silently accept a transform string with unparsed syntax.
    normalized = _TRANSFORM.sub("", value).replace(",", "").strip()
    if normalized:
        raise ValueError(f"Unparsed SVG gradientTransform text: {normalized!r}")
    return out


def _coordinate_value(raw: str, axis: int, units: str, viewport: SvgViewport,
                      object_bbox: tuple[float, float, float, float] | None) -> float:
    text = raw.strip()
    percentage = text.endswith("%")
    number = float(text[:-1] if percentage else text)
    if units == "objectBoundingBox":
        return number / 100.0 if percentage else number
    if percentage:
        min_x, min_y, vb_w, vb_h = viewport.view_box
        return (min_x + number * vb_w / 100.0) if axis == 0 else (min_y + number * vb_h / 100.0)
    return number


def linear_gradient_coordinates(root: ET.Element, gradient: ET.Element,
                                output_shape: tuple[int, int], *,
                                object_bbox: tuple[float, float, float, float] | None = None) -> tuple[np.ndarray, dict]:
    """Return normalized `t` for every output pixel using the emitted SVG geometry."""
    if _local_name(gradient.tag) != "linearGradient":
        raise ValueError("The frozen fitting model supports SVG linearGradient elements only")
    viewport = viewport_from_svg(root, output_shape)
    units = gradient.attrib.get("gradientUnits", "objectBoundingBox")
    if units not in {"userSpaceOnUse", "objectBoundingBox"}:
        raise ValueError(f"Unsupported gradientUnits: {units}")
    if units == "objectBoundingBox" and object_bbox is None:
        raise ValueError("object_bbox is required for objectBoundingBox gradients")
    defaults = {"x1": "0%", "y1": "0%", "x2": "100%", "y2": "0%"}
    p0 = np.array([_coordinate_value(gradient.attrib.get("x1", defaults["x1"]), 0, units, viewport, object_bbox),
                   _coordinate_value(gradient.attrib.get("y1", defaults["y1"]), 1, units, viewport, object_bbox)])
    p1 = np.array([_coordinate_value(gradient.attrib.get("x2", defaults["x2"]), 0, units, viewport, object_bbox),
                   _coordinate_value(gradient.attrib.get("y2", defaults["y2"]), 1, units, viewport, object_bbox)])
    transform = _transform_matrix(gradient.attrib.get("gradientTransform"))
    if units == "objectBoundingBox":
        bx, by, bw, bh = object_bbox  # type: ignore[misc]
        bbox_transform = np.array([[bw, 0.0, bx], [0.0, bh, by], [0.0, 0.0, 1.0]])
        local_to_user = bbox_transform @ transform
    else:
        local_to_user = transform
    if abs(float(np.linalg.det(local_to_user))) < 1e-14:
        raise ValueError("Singular gradient coordinate transform")
    points_user = _pixel_to_user(output_shape, viewport)
    flat = np.concatenate((points_user.reshape(-1, 2), np.ones((points_user.shape[0] * points_user.shape[1], 1))), axis=1)
    points_local = (flat @ np.linalg.inv(local_to_user).T)[:, :2].reshape(*output_shape, 2)
    vector = p1 - p0
    denom = float(vector @ vector)
    if denom <= 1e-20:
        raise ValueError("Linear gradient has coincident endpoints")
    raw_t = np.einsum("...i,i->...", points_local - p0, vector) / denom
    spread = gradient.attrib.get("spreadMethod", "pad")
    if spread == "pad":
        t = np.clip(raw_t, 0.0, 1.0)
    elif spread == "repeat":
        t = np.mod(raw_t, 1.0)
    elif spread == "reflect":
        cycle = np.mod(raw_t, 2.0)
        t = np.where(cycle <= 1.0, cycle, 2.0 - cycle)
    else:
        raise ValueError(f"Unsupported spreadMethod: {spread}")
    clip_refs = []
    for node in gradient.iter():
        for key in ("clip-path", "mask"):
            value = node.attrib.get(key, "")
            match = re.fullmatch(r"\s*url\(#([^)]*)\)\s*", value)
            if match:
                clip_refs.append({"attribute": key, "id": match.group(1)})
    metadata = {"gradientId": gradient.attrib.get("id"), "gradientUnits": units,
                "start": p0.tolist(), "end": p1.tolist(), "gradientTransform": gradient.attrib.get("gradientTransform"),
                "spreadMethod": spread, "pixelCenterConvention": "output pixel centers at (x+0.5,y+0.5)",
                "viewBox": list(viewport.view_box), "outputShapeHW": list(output_shape),
                "preserveAspectRatio": viewport.preserve_aspect_ratio,
                "objectBoundingBox": list(object_bbox) if object_bbox else None,
                "clipOrMaskReferencesOnGradientSubtree": clip_refs,
                "coordinateFormula": "t=dot(P_local-P0,P1-P0)/dot(P1-P0,P1-P0), then SVG spreadMethod"}
    return t, metadata


def stop_table(gradient: ET.Element) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    stops = [node for node in gradient if _local_name(node.tag) == "stop"]
    if len(stops) < 2:
        raise ValueError("A linear gradient needs at least two stops")
    offsets = []
    colors = []
    alpha = []
    previous = 0.0
    for node in stops:
        raw = node.attrib.get("offset", "0").strip()
        offset = float(raw[:-1]) / 100.0 if raw.endswith("%") else float(raw)
        offset = float(np.clip(offset, previous, 1.0))
        previous = offset
        color = node.attrib.get("stop-color", "black").strip()
        if color.startswith("#") and len(color) == 7:
            rgb = [int(color[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
        elif color.lower() == "black": rgb = [0.0, 0.0, 0.0]
        elif color.lower() == "white": rgb = [1.0, 1.0, 1.0]
        else: raise ValueError(f"Unsupported stop color in research SVG: {color}")
        opacity = float(node.attrib.get("stop-opacity", "1"))
        offsets.append(offset); colors.append(rgb); alpha.append(opacity)
    return np.asarray(offsets), np.asarray(colors), np.asarray(alpha)


def sample_stops(offsets: np.ndarray, colors: np.ndarray, alpha: np.ndarray,
                 t: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Interpolate ordered SVG stop colors in sRGB; duplicate offsets form hard transitions."""
    values = np.asarray(t, dtype=np.float64)
    flat = values.ravel()
    idx = np.clip(np.searchsorted(offsets, flat, side="right") - 1, 0, len(offsets) - 2)
    width = offsets[idx + 1] - offsets[idx]
    mix = np.divide(flat - offsets[idx], width, out=np.ones_like(flat), where=width > 0)
    mix = np.clip(mix, 0.0, 1.0)
    out = colors[idx] * (1.0 - mix[:, None]) + colors[idx + 1] * mix[:, None]
    out_alpha = alpha[idx] * (1.0 - mix) + alpha[idx + 1] * mix
    return out.reshape(*values.shape, 3), out_alpha.reshape(values.shape)
