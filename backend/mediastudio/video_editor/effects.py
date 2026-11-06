"""Entrance effects for visual clips.

An effect is data, not code: a start state (scale, opacity, offset), a duration,
a delay and an easing curve. The clip animates from the start state to its own
placement. The renderer turns an effect into FFmpeg expressions for export and
into a static state for single-frame previews, so both paths always agree.

Add a new effect by adding an entry to ``ENTRANCE_EFFECTS``; templates refer to
it by name through the ``entranceEffect`` clip property.

``zoom-settle`` was measured on the reference Fall Diary video by registering
every frame of each overlay's first half second against its settled frame
(SIFT + RANSAC similarity, four overlays, 30 fps):

* the overlay appears at full opacity, 1.195x its final size
* it scales about the canvas centre (fixed point 0.500/0.500, no rotation)
* it holds about one frame, then eases out (cubic) to 1.0 in about 0.48 s
* fitted error: 0.004 in scale per frame
"""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True, slots=True)
class EntranceEffect:
    name: str
    duration_seconds: float
    delay_seconds: float = 0.0
    easing: str = "ease-out-cubic"
    from_scale: float = 1.0
    from_opacity: float = 1.0
    # Start offset in canvas fractions (positive = right/down).
    from_offset_x: float = 0.0
    from_offset_y: float = 0.0
    # "canvas-center": scaling also pulls the clip toward/away from the canvas
    # centre, as a camera zoom does. "clip-center": the clip scales in place.
    origin: str = "canvas-center"


ENTRANCE_EFFECTS: dict[str, EntranceEffect] = {
    effect.name: effect for effect in (
        # Fall Diary reference overlay entrance (see module docstring).
        EntranceEffect("zoom-settle", duration_seconds=0.483, delay_seconds=0.042,
                       easing="ease-out-cubic", from_scale=1.195, origin="canvas-center"),
        # General-purpose entrances for other templates.
        EntranceEffect("fade-in", duration_seconds=0.4, easing="ease-out-quad", from_opacity=0.0),
        EntranceEffect("pop-in", duration_seconds=0.45, easing="ease-out-back", from_scale=0.6,
                       from_opacity=0.0, origin="clip-center"),
        EntranceEffect("slide-up", duration_seconds=0.5, easing="ease-out-cubic",
                       from_offset_y=0.12, from_opacity=0.0),
        EntranceEffect("slide-left", duration_seconds=0.5, easing="ease-out-cubic",
                       from_offset_x=0.25, from_opacity=0.0),
        EntranceEffect("zoom-in", duration_seconds=0.5, easing="ease-out-cubic", from_scale=0.85,
                       from_opacity=0.0, origin="clip-center"),
    )
}

EASINGS = ("linear", "ease-out-quad", "ease-out-cubic", "ease-in-out-cubic", "ease-out-back")


def get_entrance_effect(name: str) -> EntranceEffect:
    try:
        return ENTRANCE_EFFECTS[name]
    except KeyError as error:
        raise ValueError(
            f"Hiệu ứng vào cảnh {name!r} không tồn tại. Có: {', '.join(sorted(ENTRANCE_EFFECTS))}."
        ) from error


# ---------------------------------------------------------------- python side

def _ease(easing: str, p: float) -> float:
    p = min(1.0, max(0.0, p))
    if easing == "linear":
        return p
    if easing == "ease-out-quad":
        return 1 - (1 - p) ** 2
    if easing == "ease-out-cubic":
        return 1 - (1 - p) ** 3
    if easing == "ease-in-out-cubic":
        return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2
    if easing == "ease-out-back":
        c1 = 1.70158
        return 1 + (c1 + 1) * (p - 1) ** 3 + c1 * (p - 1) ** 2
    raise ValueError(f"Easing {easing!r} không được hỗ trợ.")


def progress_at(effect: EntranceEffect, local_seconds: float) -> float:
    """Eased progress 0..1 at ``local_seconds`` after the clip starts."""
    if effect.duration_seconds <= 0:
        return 1.0
    return _ease(effect.easing, (local_seconds - effect.delay_seconds) / effect.duration_seconds)


@dataclass(frozen=True, slots=True)
class EffectState:
    scale: float
    opacity: float
    offset_x: float
    offset_y: float
    origin: str


def state_at(effect: EntranceEffect, local_seconds: float) -> EffectState:
    e = progress_at(effect, local_seconds)
    return EffectState(
        scale=effect.from_scale + (1.0 - effect.from_scale) * e,
        opacity=max(0.0, min(1.0, effect.from_opacity + (1.0 - effect.from_opacity) * e)),
        offset_x=effect.from_offset_x * (1.0 - e),
        offset_y=effect.from_offset_y * (1.0 - e),
        origin=effect.origin,
    )


def apply_state(attributes: dict, state: EffectState) -> dict:
    """Fold an effect state into static clip attributes (single-frame previews)."""
    result = dict(attributes)
    result["scale"] = float(result["scale"]) * state.scale
    position_x = float(result["positionX"])
    position_y = float(result["positionY"])
    if state.origin == "canvas-center":
        position_x *= state.scale
        position_y *= state.scale
    result["positionX"] = position_x + state.offset_x
    result["positionY"] = position_y + state.offset_y
    result["opacity"] = float(result["opacity"]) * state.opacity
    return result


# ---------------------------------------------------------------- ffmpeg side

def _ease_expression(easing: str, p: str) -> str:
    if easing == "linear":
        return p
    if easing == "ease-out-quad":
        return f"(1-pow(1-{p},2))"
    if easing == "ease-out-cubic":
        return f"(1-pow(1-{p},3))"
    if easing == "ease-in-out-cubic":
        return f"if(lt({p},0.5),4*pow({p},3),1-pow(-2*{p}+2,3)/2)"
    if easing == "ease-out-back":
        return f"(1+2.70158*pow({p}-1,3)+1.70158*pow({p}-1,2))"
    raise ValueError(f"Easing {easing!r} không được hỗ trợ.")


def progress_expression(effect: EntranceEffect, local_time: str) -> str:
    """FFmpeg expression for eased progress; ``local_time`` is seconds since clip start."""
    if effect.duration_seconds <= 0:
        return "1"
    p = (f"clip(({local_time}-{effect.delay_seconds:.6f})/{effect.duration_seconds:.6f},0,1)")
    return _ease_expression(effect.easing, p)


def scale_expression(effect: EntranceEffect, local_time: str) -> str:
    e = progress_expression(effect, local_time)
    return f"({effect.from_scale:.6f}+{1.0 - effect.from_scale:.6f}*{e})"


def opacity_expression(effect: EntranceEffect, local_time: str) -> str:
    e = progress_expression(effect, local_time)
    return f"clip({effect.from_opacity:.6f}+{1.0 - effect.from_opacity:.6f}*{e},0,1)"


def position_expression(effect: EntranceEffect, base: float, axis: str, local_time: str) -> str:
    """Animated positionX/positionY expression around a static ``base`` value."""
    e = progress_expression(effect, local_time)
    start = effect.from_offset_x if axis == "x" else effect.from_offset_y
    value = f"{base:.9f}"
    if effect.origin == "canvas-center" and not math.isclose(effect.from_scale, 1.0):
        value = f"({value}*{scale_expression(effect, local_time)})"
    if start:
        value = f"({value}+{start:.6f}*(1-{e}))"
    return value


def animates_opacity(effect: EntranceEffect) -> bool:
    return not math.isclose(effect.from_opacity, 1.0)


def animates_scale(effect: EntranceEffect) -> bool:
    return not math.isclose(effect.from_scale, 1.0)
