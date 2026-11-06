from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Callable, Literal, Mapping

from mediastudio.video_editor.project_v2 import INT64_MAX, TIMEBASE, VideoProjectV2


GRAPH_VERSION = 1
FPS_RATES = ((24, 1), (25, 1), (30, 1), (60, 1), (30_000, 1_001))


class CompositionGraphError(ValueError):
    """Project data cannot be represented by the verified composition subset."""


@dataclass(frozen=True, slots=True)
class CompositionClip:
    clip_id: str
    track_id: str
    kind: Literal["visual", "image", "video", "text", "audio"]
    timeline_start_ticks: int
    source_start_ticks: int
    duration_ticks: int
    media_id: str | None
    media_kind: str | None
    media_has_audio: bool
    enabled: bool
    attributes: Mapping[str, Any]

    @property
    def end_ticks(self) -> int:
        return self.timeline_start_ticks + self.duration_ticks


@dataclass(frozen=True, slots=True)
class CompositionTrack:
    track_id: str
    kind: Literal["visual", "text", "audio"]
    layer_order: int
    display_name: str
    visible: bool
    locked: bool
    muted: bool
    solo: bool
    clips: tuple[CompositionClip, ...]


@dataclass(frozen=True, slots=True)
class CompositionGraph:
    graph_version: int
    project_id: str
    project_revision: int
    width: int
    height: int
    frame_rate_numerator: int
    frame_rate_denominator: int
    timebase: int
    tracks: tuple[CompositionTrack, ...]
    duration_ticks: int
    visual_duration_ticks: int
    duration_policy: str
    audio_mix_policy: str
    source_fingerprint: str

    @property
    def fps(self) -> str:
        return f"{self.frame_rate_numerator}/{self.frame_rate_denominator}"

    def frame_index_at(self, timeline_ticks: int) -> int:
        if timeline_ticks < 0 or timeline_ticks > INT64_MAX:
            raise CompositionGraphError("Thời điểm preview vượt miền số nguyên 64-bit.")
        denominator = self.timebase * self.frame_rate_denominator
        whole, remainder = divmod(timeline_ticks, denominator)
        whole_frames = whole * self.frame_rate_numerator
        if whole_frames > INT64_MAX:
            raise CompositionGraphError("Phép đổi thời gian sang frame bị tràn số.")
        partial_frames = remainder * self.frame_rate_numerator // denominator
        if whole_frames > INT64_MAX - partial_frames:
            raise CompositionGraphError("Phép đổi thời gian sang frame bị tràn số.")
        return whole_frames + partial_frames

    def frame_start_ticks(self, frame_index: int) -> int:
        if frame_index < 0:
            raise CompositionGraphError("Frame index phải không âm.")
        ticks_per_frame = self.timebase * self.frame_rate_denominator
        if ticks_per_frame % self.frame_rate_numerator:
            raise CompositionGraphError("Frame rate không khớp chính xác với timebase 90.000.")
        ticks_per_frame //= self.frame_rate_numerator
        if frame_index > INT64_MAX // ticks_per_frame:
            raise CompositionGraphError("Timestamp frame bị tràn số nguyên 64-bit.")
        return frame_index * ticks_per_frame

    def to_dict(self) -> dict[str, Any]:
        return {
            "graphVersion": self.graph_version,
            "projectId": self.project_id,
            "projectRevision": self.project_revision,
            "width": self.width,
            "height": self.height,
            "frameRateNumerator": self.frame_rate_numerator,
            "frameRateDenominator": self.frame_rate_denominator,
            "timebase": self.timebase,
            "durationTicks": self.duration_ticks,
            "visualDurationTicks": self.visual_duration_ticks,
            "durationPolicy": self.duration_policy,
            "audioMixPolicy": self.audio_mix_policy,
            "sourceFingerprint": self.source_fingerprint,
            "layerOrderContract": "ascending-back-to-front",
            "tracks": [
                {
                    "trackId": track.track_id,
                    "kind": track.kind,
                    "layerOrder": track.layer_order,
                    "displayName": track.display_name,
                    "state": {
                        "visible": track.visible,
                        "locked": track.locked,
                        "muted": track.muted,
                        "solo": track.solo,
                    },
                    "clips": [
                        {
                            "clipId": clip.clip_id,
                            "trackId": clip.track_id,
                            "clipKind": clip.kind,
                            "timelineStartTicks": clip.timeline_start_ticks,
                            "sourceStartTicks": clip.source_start_ticks,
                            "durationTicks": clip.duration_ticks,
                            "mediaId": clip.media_id,
                            "mediaKind": clip.media_kind,
                            "mediaHasAudio": clip.media_has_audio,
                            "enabled": clip.enabled,
                            "attributes": deepcopy(dict(clip.attributes)),
                        }
                        for clip in track.clips
                    ],
                }
                for track in self.tracks
            ],
        }


def clip_is_active(clip: CompositionClip, timeline_ticks: int) -> bool:
    return clip.timeline_start_ticks <= timeline_ticks < clip.end_ticks


def source_time_ticks_at(clip: CompositionClip, timeline_ticks: int) -> int:
    if not clip_is_active(clip, timeline_ticks):
        raise CompositionGraphError(f"Clip {clip.clip_id} không active tại timestamp được yêu cầu.")
    source_ticks = clip.source_start_ticks + (timeline_ticks - clip.timeline_start_ticks)
    if source_ticks > INT64_MAX:
        raise CompositionGraphError(f"Source timestamp clip {clip.clip_id} vượt giới hạn int64.")
    return source_ticks


MediaLookup = Callable[[str], Any]


def build_composition_graph(project: VideoProjectV2, media_lookup: MediaLookup) -> CompositionGraph:
    """Create a deterministic render graph without mutating canonical V2 JSON."""
    if project.timebase != TIMEBASE:
        raise CompositionGraphError(f"Timebase không được hỗ trợ: {project.timebase}.")
    if project.timebase * project.frame_rate_denominator % project.frame_rate_numerator:
        raise CompositionGraphError("Frame rate không biểu diễn chính xác trong timebase của project.")

    project_snapshot = project.model_dump(mode="json", by_alias=True)
    fingerprint = hashlib.sha256(json.dumps(
        project_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()

    any_solo: dict[str, bool] = {
        kind: any(track.kind == kind and track.state.solo for track in project.tracks)
        for kind in ("visual", "text", "audio")
    }
    tracks: list[CompositionTrack] = []
    media_cache: dict[str, Any] = {}
    id_seen: set[str] = set()
    for track in sorted(project.tracks, key=lambda item: item.layer_order):
        if track.track_id in id_seen:
            raise CompositionGraphError(f"Track ID bị trùng: {track.track_id}.")
        id_seen.add(track.track_id)
        state = track.state
        if track.kind in {"visual", "text"} and state.muted:
            raise CompositionGraphError(f"Track {track.track_id} có trạng thái muted chưa có semantics cho {track.kind}.")
        track_active = state.visible if track.kind in {"visual", "text"} else not state.muted
        if any_solo[track.kind]:
            track_active = track_active and state.solo

        clips: list[CompositionClip] = []
        sorted_clips = sorted(track.clips, key=lambda item: (item.timeline_start_ticks, item.clip_id))
        for clip in sorted_clips:
            if clip.clip_id in id_seen:
                raise CompositionGraphError(f"Clip/Track ID bị trùng: {clip.clip_id}.")
            id_seen.add(clip.clip_id)
            if clip.track_id != track.track_id:
                raise CompositionGraphError(f"Clip {clip.clip_id} tham chiếu sai Track ID.")
            _validate_clip_kind(track.kind, clip.clip_kind, clip.clip_id)
            _validate_time_range(clip.timeline_start_ticks, clip.source_start_ticks, clip.duration_ticks,
                                 clip.clip_id)

            media = None
            media_kind = None
            has_audio = False
            if clip.clip_kind == "text":
                attributes = _text_attributes(clip.properties, clip.clip_id)
            else:
                template_asset_reference = clip.properties.get("templateAssetReference")
                if not clip.media_id and template_asset_reference is not None:
                    if (clip.clip_kind != "image" or track.kind != "visual" or clip.source_start_ticks != 0
                            or not isinstance(template_asset_reference, str)):
                        raise CompositionGraphError(f"Static template asset on clip {clip.clip_id} is invalid.")
                    from mediastudio.video_editor.media_selection import resolve_template_asset
                    template_id = clip.properties.get("templateAssetId")
                    template_version = clip.properties.get("templateAssetDefinitionVersion")
                    try:
                        resolve_template_asset(str(template_id), str(template_version), template_asset_reference)
                    except (OSError, ValueError) as error:
                        raise CompositionGraphError(
                            f"Template asset for clip {clip.clip_id} is unavailable: {error}"
                        ) from error
                    media_kind = "image"
                    attributes = _visual_attributes(clip.properties, clip.clip_id, clip.duration_ticks)
                else:
                    if not clip.media_id:
                        raise CompositionGraphError(
                            f"Clip {clip.clip_id} là placeholder chưa gắn media; không thể render hoặc preview composition."
                        )
                    try:
                        if clip.media_id not in media_cache:
                            media_cache[clip.media_id] = media_lookup(clip.media_id)
                        media = media_cache[clip.media_id]
                    except KeyError as error:
                        raise CompositionGraphError(
                            f"Không tìm thấy media {clip.media_id} được clip {clip.clip_id} tham chiếu."
                        ) from error
                    media_kind = str(_read_media_value(media, "kind"))
                    has_audio = bool(_read_media_value(media, "audio_codec"))
                    _validate_media_kind(track.kind, clip.clip_kind, media_kind, clip.clip_id)
                    if clip.properties.get("removeBackground") and media_kind != "image":
                        raise CompositionGraphError(
                            f"Tách nền tự động chỉ hỗ trợ ảnh tĩnh tại clip {clip.clip_id}."
                        )
                    if track.kind == "audio" and not has_audio:
                        raise CompositionGraphError(f"Audio clip {clip.clip_id} trỏ tới media không có audio stream.")
                    media_duration_ms = _read_media_value(media, "duration_ms")
                    _validate_source_bounds(clip.source_start_ticks, clip.duration_ticks, media_duration_ms,
                                            media_kind, clip.clip_id)
                    if media_kind == "image" and clip.source_start_ticks != 0:
                        raise CompositionGraphError(f"Ảnh tĩnh {clip.clip_id} không hỗ trợ sourceStartTicks khác 0.")
                    attributes = (_visual_attributes(clip.properties, clip.clip_id, clip.duration_ticks)
                                  if track.kind == "visual" else _audio_attributes(clip.properties, clip.clip_id))

            enabled = track_active and not (track.kind == "audio" and bool(attributes.get("muted", False)))
            if track.kind == "visual" and not state.visible:
                enabled = False
            clips.append(CompositionClip(
                clip_id=clip.clip_id,
                track_id=clip.track_id,
                kind=clip.clip_kind,
                timeline_start_ticks=clip.timeline_start_ticks,
                source_start_ticks=clip.source_start_ticks,
                duration_ticks=clip.duration_ticks,
                media_id=clip.media_id,
                media_kind=media_kind,
                media_has_audio=has_audio,
                enabled=enabled,
                attributes=attributes,
            ))

        if track.kind == "visual":
            active_visual = [clip for clip in clips if clip.enabled]
            for previous, current in zip(active_visual, active_visual[1:]):
                if current.timeline_start_ticks < previous.end_ticks:
                    raise CompositionGraphError(
                        f"Visual clips {previous.clip_id} và {current.clip_id} chồng lấn trong cùng track; "
                        "semantics này chưa được hỗ trợ."
                    )
        tracks.append(CompositionTrack(
            track_id=track.track_id,
            kind=track.kind,
            layer_order=track.layer_order,
            display_name=track.display_name,
            visible=state.visible,
            locked=state.locked,
            muted=state.muted,
            solo=state.solo,
            clips=tuple(clips),
        ))

    active_ends: list[int] = []
    audio_solo_active = any(track.kind == "audio" and track.solo and not track.muted for track in tracks)
    for track in tracks:
        for clip in track.clips:
            if not clip.enabled:
                continue
            if track.kind == "audio" and clip.attributes.get("volume", 1.0) <= 0:
                continue
            active_ends.append(clip.end_ticks)
            if track.kind == "visual" and clip.media_has_audio and clip.attributes.get("audioVolume", 1.0) > 0 \
                    and not audio_solo_active:
                active_ends.append(clip.end_ticks)

    visual_duration_ticks = max((clip.end_ticks for track in tracks if track.kind == "visual"
                                 for clip in track.clips if clip.enabled), default=0)
    from mediastudio.video_editor.project_v2 import render_capability
    legacy_linear, _ = render_capability(project)
    legacy_tail = legacy_linear and visual_duration_ticks > 0 and any(
        track.kind == "audio" and clip.enabled and clip.attributes.get("volume", 1.0) > 0
        and clip.end_ticks > visual_duration_ticks
        for track in tracks for clip in track.clips
    )
    return CompositionGraph(
        graph_version=GRAPH_VERSION,
        project_id=project.project_id,
        project_revision=project.revision,
        width=project.width,
        height=project.height,
        frame_rate_numerator=project.frame_rate_numerator,
        frame_rate_denominator=project.frame_rate_denominator,
        timebase=project.timebase,
        tracks=tuple(tracks),
        duration_ticks=max(active_ends, default=0),
        visual_duration_ticks=visual_duration_ticks,
        duration_policy=("legacy-hold-last-visual-through-audio-end" if legacy_tail
                         else "black-on-gap-or-outside-visual"),
        audio_mix_policy=("legacy-input-count-normalization" if legacy_linear
                          else "sum-gains-no-normalization"),
        source_fingerprint=fingerprint,
    )


def _read_media_value(media: Any, field: str) -> Any:
    if isinstance(media, Mapping):
        camel = field.split("_")[0] + "".join(part.capitalize() for part in field.split("_")[1:])
        return media.get(field, media.get(camel))
    return getattr(media, field, None)


def _validate_clip_kind(track_kind: str, clip_kind: str, clip_id: str) -> None:
    allowed = {
        "visual": {"visual", "image", "video"},
        "text": {"text"},
        "audio": {"audio"},
    }
    if clip_kind not in allowed.get(track_kind, set()):
        raise CompositionGraphError(f"Clip {clip_id} loại {clip_kind} không tương thích track {track_kind}.")


def _validate_media_kind(track_kind: str, clip_kind: str, media_kind: str, clip_id: str) -> None:
    if track_kind == "audio" and media_kind != "audio":
        raise CompositionGraphError(f"Audio clip {clip_id} phải tham chiếu media audio.")
    if track_kind == "visual" and media_kind not in {"video", "image"}:
        raise CompositionGraphError(f"Visual clip {clip_id} phải tham chiếu media video hoặc image.")
    if clip_kind == "image" and media_kind != "image":
        raise CompositionGraphError(f"Clip {clip_id} khai báo image nhưng media không phải ảnh.")
    if clip_kind == "video" and media_kind != "video":
        raise CompositionGraphError(f"Clip {clip_id} khai báo video nhưng media không phải video.")


def _validate_time_range(start: int, source_start: int, duration: int, clip_id: str) -> None:
    if start < 0 or source_start < 0 or duration <= 0:
        raise CompositionGraphError(f"Clip {clip_id} có timeline/source range không hợp lệ.")
    if start > INT64_MAX - duration or source_start > INT64_MAX - duration:
        raise CompositionGraphError(f"Timestamp clip {clip_id} vượt giới hạn int64.")


def _validate_source_bounds(source_start: int, duration: int, media_duration_ms: Any,
                           media_kind: str, clip_id: str) -> None:
    if media_kind == "image":
        return
    if not isinstance(media_duration_ms, int) or media_duration_ms <= 0:
        raise CompositionGraphError(f"Không đọc được thời lượng nguồn của clip {clip_id}.")
    source_end = source_start + duration
    if source_end > media_duration_ms * 90:
        raise CompositionGraphError(f"Clip {clip_id} vượt giới hạn thời lượng media nguồn.")


def _number(properties: Mapping[str, Any], key: str, default: float,
            minimum: float, maximum: float, clip_id: str) -> float:
    value = properties.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise CompositionGraphError(f"Clip {clip_id} có {key} không phải số hữu hạn.")
    result = float(value)
    if result < minimum or result > maximum:
        raise CompositionGraphError(f"Clip {clip_id} có {key} ngoài miền hỗ trợ.")
    return result


def _integer(properties: Mapping[str, Any], key: str, default: int,
             minimum: int, maximum: int, clip_id: str) -> int:
    value = properties.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or value > maximum:
        raise CompositionGraphError(f"Clip {clip_id} có {key} ngoài miền hỗ trợ.")
    return value


def _visual_attributes(properties: Mapping[str, Any], clip_id: str, duration_ticks: int) -> dict[str, Any]:
    known = {"name", "clipId", "mediaId", "sourceStartMs", "durationMs", "fitMode", "positionX",
             "positionY", "scale", "rotation", "effect", "opacity", "audioVolume", "transition",
             "transitionDurationMs", "keyframes", "removeBackground", "trimTransparentBounds", "subjectCentered",
             "userScale", "userOffsetX", "userOffsetY", "entranceEffect",
             "templateAssetReference", "templateAssetId",
             "templateAssetDefinitionVersion"}
    unsupported = {key for key in properties if key not in known}
    if unsupported:
        raise CompositionGraphError(
            f"Visual clip {clip_id} có thuộc tính chưa được hỗ trợ: {', '.join(sorted(unsupported))}."
        )
    fit_mode = properties.get("fitMode", "cover")
    if fit_mode not in {"cover", "contain"}:
        raise CompositionGraphError(f"Visual clip {clip_id} có fitMode không được hỗ trợ.")
    effect = properties.get("effect", "none")
    if effect not in {"none", "warm", "mono", "vivid"}:
        raise CompositionGraphError(f"Visual clip {clip_id} có effect chưa được hỗ trợ: {effect}.")
    transition = properties.get("transition", "cut")
    if transition != "cut":
        raise CompositionGraphError(
            f"Visual clip {clip_id} dùng transition {transition}; transition đa track hiện chưa có contract."
        )
    keyframes = properties.get("keyframes", [])
    if not isinstance(keyframes, list):
        raise CompositionGraphError(f"Visual clip {clip_id} keyframes must be a list.")
    supported = {"positionX": (-2.0, 2.0), "positionY": (-2.0, 2.0), "scale": (0.1, 5.0),
                 "rotation": (-180.0, 180.0), "opacity": (0.0, 1.0)}
    keyframes_by_property: dict[str, list[tuple[int, float]]] = {prop: [] for prop in supported}
    for key in keyframes:
        if not isinstance(key, Mapping):
            raise CompositionGraphError(f"Visual clip {clip_id} has an invalid keyframe.")
        prop, time_ticks = key.get("property"), key.get("timeTicks")
        if prop not in supported or not isinstance(time_ticks, int) or time_ticks < 0:
            raise CompositionGraphError(f"Visual clip {clip_id} has an invalid keyframe.")
        low, high = supported[prop]
        value = key.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
                or not low <= value <= high:
            raise CompositionGraphError(f"Visual clip {clip_id} keyframe {prop} is outside [{low}, {high}].")
        if key.get("interpolation", "linear") != "linear" or key.get("easing", "linear") != "linear":
            raise CompositionGraphError(f"Visual clip {clip_id} uses unsupported keyframe interpolation/easing.")
        if time_ticks > duration_ticks:
            raise CompositionGraphError(f"Visual clip {clip_id} keyframe {prop} exceeds the clip duration.")
        keyframes_by_property[prop].append((time_ticks, float(value)))
    for prop, keys in keyframes_by_property.items():
        if not keys:
            continue
        times = [time for time, _ in keys]
        if len(times) < 2 or len(times) != len(set(times)) or min(times) != 0 or max(times) != duration_ticks:
            raise CompositionGraphError(
                f"Visual clip {clip_id} keyframes for {prop} must be unique and span the clip duration."
            )
    result = {
        "name": str(properties.get("name", "Visual")),
        "fitMode": fit_mode,
        "positionX": _number(properties, "positionX", 0.0, -2.0, 2.0, clip_id),
        "positionY": _number(properties, "positionY", 0.0, -2.0, 2.0, clip_id),
        "scale": _number(properties, "scale", 1.0, 0.1, 5.0, clip_id),
        "rotation": _number(properties, "rotation", 0.0, -180.0, 180.0, clip_id),
        "effect": effect,
        "opacity": _number(properties, "opacity", 1.0, 0.0, 1.0, clip_id),
        "audioVolume": _number(properties, "audioVolume", 1.0, 0.0, 2.0, clip_id),
        "keyframes": [dict(key) for key in keyframes],
    }
    if properties.get("removeBackground") is True:
        result["removeBackground"] = True
    if properties.get("trimTransparentBounds") is True:
        if properties.get("removeBackground") is not True:
            raise CompositionGraphError(f"Visual clip {clip_id} can trim transparent bounds only after background removal.")
        result["trimTransparentBounds"] = True
    if properties.get("subjectCentered") is True:
        if properties.get("removeBackground") is not True or properties.get("trimTransparentBounds") is True:
            raise CompositionGraphError(
                f"Visual clip {clip_id} can centre its subject only on an untrimmed cut-out."
            )
        if keyframes:
            raise CompositionGraphError(f"Visual clip {clip_id} cannot combine subject centring with keyframes.")
        result["subjectCentered"] = True
    # Manual adjustment made on the edit screen, applied on top of the
    # template placement: a size multiplier and a shift in canvas fractions.
    user_scale = _number(properties, "userScale", 1.0, 0.2, 4.0, clip_id)
    user_offset_x = _number(properties, "userOffsetX", 0.0, -1.0, 1.0, clip_id)
    user_offset_y = _number(properties, "userOffsetY", 0.0, -1.0, 1.0, clip_id)
    if (user_scale != 1.0 or user_offset_x or user_offset_y) and keyframes:
        raise CompositionGraphError(f"Visual clip {clip_id} cannot combine manual placement with keyframes.")
    if "entranceEffect" in properties:
        from mediastudio.video_editor.effects import ENTRANCE_EFFECTS
        name = properties["entranceEffect"]
        if not isinstance(name, str) or name not in ENTRANCE_EFFECTS:
            raise CompositionGraphError(f"Visual clip {clip_id} có hiệu ứng vào cảnh không hỗ trợ: {name!r}.")
        if keyframes:
            raise CompositionGraphError(f"Visual clip {clip_id} cannot combine an entrance effect with keyframes.")
        result["entranceEffect"] = name
    if user_scale != 1.0:
        result["userScale"] = user_scale
    if user_offset_x:
        result["userOffsetX"] = user_offset_x
    if user_offset_y:
        result["userOffsetY"] = user_offset_y
    for key in ("templateAssetReference", "templateAssetId", "templateAssetDefinitionVersion"):
        if key in properties:
            value = properties[key]
            if not isinstance(value, str) or not value:
                raise CompositionGraphError(f"Visual clip {clip_id} has invalid {key}.")
            result[key] = value
    return result


def _text_attributes(properties: Mapping[str, Any], clip_id: str) -> dict[str, Any]:
    known = {"layerId", "text", "startMs", "durationMs", "x", "y", "fontSize", "color",
             "fontFamily", "opacity", "textBox", "textBoxColor", "textBoxOpacity", "textBoxBorderWidth",
             "textBoxBorderColor", "shadowColor", "shadowX", "shadowY", "keyframes"}
    unsupported = {key for key in properties if key not in known}
    if unsupported:
        raise CompositionGraphError(
            f"Text clip {clip_id} có style chưa được hỗ trợ: {', '.join(sorted(unsupported))}."
        )
    text = properties.get("text")
    if not isinstance(text, str) or not text:
        raise CompositionGraphError(f"Text clip {clip_id} chưa có nội dung.")
    color = properties.get("color", "#FFFFFF")
    if not isinstance(color, str) or not len(color) == 7 or color[0] != "#" \
            or any(character not in "0123456789abcdefABCDEF" for character in color[1:]):
        raise CompositionGraphError(f"Text clip {clip_id} có màu không hợp lệ.")
    font_family = properties.get("fontFamily", "Arial")
    if not isinstance(font_family, str) or not font_family.strip():
        raise CompositionGraphError(f"Text clip {clip_id} chưa có font family hợp lệ.")
    for key in ("textBoxColor", "textBoxBorderColor", "shadowColor"):
        value = properties.get(key)
        if value is not None and (not isinstance(value, str) or len(value) != 7 or value[0] != "#"
                                  or any(character not in "0123456789abcdefABCDEF" for character in value[1:])):
            raise CompositionGraphError(f"Text clip {clip_id} có {key} không hợp lệ.")
    text_keyframes = properties.get("keyframes", [])
    if text_keyframes:
        raise CompositionGraphError(f"Text clip {clip_id} keyframes are not supported by the text renderer.")
    return {
        "text": text,
        "x": _number(properties, "x", 0.5, 0.0, 1.0, clip_id),
        "y": _number(properties, "y", 0.5, 0.0, 1.0, clip_id),
        "fontSize": _integer(properties, "fontSize", 52, 8, 300, clip_id),
        "color": color.upper(),
        "fontFamily": font_family.strip(),
        "opacity": _number(properties, "opacity", 1.0, 0.0, 1.0, clip_id),
        "textBox": bool(properties.get("textBox", False)),
        "textBoxColor": str(properties.get("textBoxColor", "#000000")).upper(),
        "textBoxOpacity": _number(properties, "textBoxOpacity", 0.0, 0.0, 1.0, clip_id),
        "textBoxBorderWidth": _integer(properties, "textBoxBorderWidth", 0, 0, 30, clip_id),
        "textBoxBorderColor": str(properties.get("textBoxBorderColor", "#FFFFFF")).upper(),
        "shadowColor": properties.get("shadowColor"),
        "shadowX": _integer(properties, "shadowX", 0, -100, 100, clip_id),
        "shadowY": _integer(properties, "shadowY", 0, -100, 100, clip_id),
        "keyframes": [],
    }


def _audio_attributes(properties: Mapping[str, Any], clip_id: str) -> dict[str, Any]:
    known = {"trackId", "mediaId", "timelineStartMs", "sourceStartMs", "durationMs",
             "volume", "fadeInMs", "fadeOutMs"}
    unsupported = {key for key in properties if key not in known}
    if unsupported:
        raise CompositionGraphError(
            f"Audio clip {clip_id} có thuộc tính chưa được hỗ trợ: {', '.join(sorted(unsupported))}."
        )
    return {
        "volume": _number(properties, "volume", 1.0, 0.0, 2.0, clip_id),
        "fadeInMs": _integer(properties, "fadeInMs", 0, 0, 30_000, clip_id),
        "fadeOutMs": _integer(properties, "fadeOutMs", 0, 0, 30_000, clip_id),
        "muted": False,
    }

