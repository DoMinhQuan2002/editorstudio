"""Shared timebase-aware linear keyframe evaluation for template visual layers."""
from __future__ import annotations

from typing import Any, Mapping

from mediastudio.video_editor.project_v2 import TIMEBASE


def interpolate_keyframes(keyframes: list[Mapping[str, Any]], prop: str, time_ticks: int) -> float | None:
    keys = sorted((k for k in keyframes if k.get("property") == prop), key=lambda k: int(k["timeTicks"]))
    if not keys:
        return None
    if time_ticks <= int(keys[0]["timeTicks"]):
        return float(keys[0]["value"])
    for left, right in zip(keys, keys[1:]):
        start, end = int(left["timeTicks"]), int(right["timeTicks"])
        if time_ticks <= end:
            fraction = (time_ticks - start) / (end - start)
            return float(left["value"]) + (float(right["value"]) - float(left["value"])) * fraction
    return float(keys[-1]["value"])


def keyframe_expression(keyframes: list[Mapping[str, Any]], prop: str, time_seconds: str) -> str | None:
    """Create a bounded linear FFmpeg expression from a local seconds variable."""
    keys = sorted((k for k in keyframes if k.get("property") == prop), key=lambda k: int(k["timeTicks"]))
    if not keys:
        return None
    pairs = [(int(k["timeTicks"]) / TIMEBASE, float(k["value"])) for k in keys]
    result = f"{pairs[-1][1]:.12g}"
    for (start, first), (end, last) in reversed(list(zip(pairs, pairs[1:]))):
        slope = (last - first) / (end - start)
        segment = f"({first:.12g}+({time_seconds}-{start:.12g})*{slope:.12g})"
        result = f"if(lt({time_seconds},{end:.12g}),{segment},{result})"
    return result
