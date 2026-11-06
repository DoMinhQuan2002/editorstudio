"""Versioned template definitions and a loss-aware Project V2 compiler.

This module is deliberately independent of any one catalog entry. It compiles
the explicitly supported definition features into canonical V2 tracks and a
Composition Graph; unsupported timing/effect features fail with an actionable
error instead of being silently discarded.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any, Callable, Literal, Mapping
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import Field, model_validator

from mediastudio.video_editor.composition import CompositionGraph, build_composition_graph
from mediastudio.video_editor.models import StrictModel
from mediastudio.video_editor.project_v2 import (
    MAX_TIME_TICKS,
    TIMEBASE,
    TimelineClipV2,
    TimelineTrackV2,
    VideoProjectV2,
)


MediaKind = Literal["image", "video", "audio"]
LayerKind = Literal["image", "video", "text", "audio"]


class TemplateCompilerError(ValueError):
    """The definition, bindings, or requested renderer features are invalid."""


class TemplateMediaSlot(StrictModel):
    slot_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    allowed_media_kinds: list[MediaKind] = Field(min_length=1, max_length=3)
    required: bool = True
    reuse_policy: Literal["allow", "unique_asset"] = "allow"
    missing_slot_policy: Literal["error", "skip_event"] = "error"

    @model_validator(mode="after")
    def validate_policy(self) -> "TemplateMediaSlot":
        if len(self.allowed_media_kinds) != len(set(self.allowed_media_kinds)):
            raise ValueError(f"Slot {self.slot_id} repeats an allowed media kind.")
        if self.required and self.missing_slot_policy != "error":
            raise ValueError(f"Required slot {self.slot_id} must use missingSlotPolicy=error.")
        return self

    def public_dict(self) -> dict[str, object]:
        return {
            "slotId": self.slot_id,
            "allowedMediaKinds": list(self.allowed_media_kinds),
            "required": self.required,
            "reusePolicy": self.reuse_policy,
            "missingSlotPolicy": self.missing_slot_policy,
        }


class SourceTimeMapping(StrictModel):
    source_start_ticks: int = Field(default=0, ge=0, le=MAX_TIME_TICKS)
    rate_numerator: int = Field(default=1, ge=1, le=1000)
    rate_denominator: int = Field(default=1, ge=1, le=1000)


class TemplateKeyframe(StrictModel):
    property: Literal["positionX", "positionY", "scale", "rotation", "opacity"]
    time_ticks: int = Field(ge=0, le=MAX_TIME_TICKS)
    value: float
    interpolation: Literal["linear"] = "linear"
    easing: Literal["linear"] = "linear"


class TemplateLayer(StrictModel):
    layer_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    kind: LayerKind
    layer_order: int = Field(ge=0, le=10_000)
    slot_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    asset_reference: str | None = Field(default=None, min_length=1, max_length=256)
    source_time_mapping: SourceTimeMapping = Field(default_factory=SourceTimeMapping)

    # Fields with renderer semantics today.
    fit_mode: Literal["cover", "contain"] = "cover"
    position_x: float = Field(default=0.0, ge=-2.0, le=2.0)
    position_y: float = Field(default=0.0, ge=-2.0, le=2.0)
    scale: float = Field(default=1.0, ge=0.1, le=5.0)
    rotation: float = Field(default=0.0, ge=-180.0, le=180.0)
    effect: Literal["none", "warm", "mono", "vivid"] = "none"
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    audio_volume: float = Field(default=1.0, ge=0.0, le=2.0)
    text: str | None = Field(default=None, min_length=1, max_length=500)
    text_x: float = Field(default=0.5, ge=0.0, le=1.0)
    text_y: float = Field(default=0.5, ge=0.0, le=1.0)
    font_size: int = Field(default=52, ge=8, le=300)
    color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    font_family: str = Field(default="Arial", min_length=1, max_length=80)
    volume: float = Field(default=1.0, ge=0.0, le=2.0)
    fade_in_ms: int = Field(default=0, ge=0, le=30_000)
    fade_out_ms: int = Field(default=0, ge=0, le=30_000)

    # Explicitly modeled so an incomplete renderer cannot silently lose them.
    keyframes: list[TemplateKeyframe] = Field(default_factory=list, max_length=256)
    text_box: bool = False
    text_box_color: str = Field(default="#000000", pattern=r"^#[0-9A-Fa-f]{6}$")
    text_box_opacity: float = Field(default=0.0, ge=0.0, le=1.0)
    text_box_border_width: int = Field(default=0, ge=0, le=30)
    text_box_border_color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    shadow_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    shadow_x: int = Field(default=0, ge=-100, le=100)
    shadow_y: int = Field(default=0, ge=-100, le=100)
    mask_reference: str | None = None
    cutout_reference: str | None = None
    sticker_reference: str | None = None
    remove_background: bool = False
    trim_transparent_bounds: bool = False
    # Place the cut-out like the reference template: photo at 1.35x canvas
    # height, visible subject centred slightly below the middle (see framing.py).
    subject_centered: bool = False
    # Name of an entry in effects.ENTRANCE_EFFECTS, e.g. "zoom-settle".
    entrance_effect: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,47}$")
    transition: Literal["cut", "fade", "wipe", "unknown"] | None = None
    motion_classification: Literal["REFERENCE_OBSERVED", "EDITORIAL_MOTION", "UNVERIFIED"] = "UNVERIFIED"

    @model_validator(mode="after")
    def validate_media_reference(self) -> "TemplateLayer":
        if self.asset_reference is not None:
            asset_path = PurePosixPath(self.asset_reference)
            if (self.kind != "image" or self.slot_id is not None or "\\" in self.asset_reference
                    or ":" in self.asset_reference or asset_path.is_absolute()
                    or any(part in {"", ".", ".."} for part in asset_path.parts)):
                raise ValueError(
                    f"Layer {self.layer_id} template asset must be a relative image path without traversal."
                )
        if self.kind == "text":
            if self.slot_id is not None or self.asset_reference is not None:
                raise ValueError(f"Text layer {self.layer_id} cannot bind a media slot.")
            if self.text is None:
                raise ValueError(f"Text layer {self.layer_id} requires text content.")
        elif self.slot_id is None and self.asset_reference is None:
            raise ValueError(f"Media layer {self.layer_id} requires a slotId.")
        if self.remove_background and (self.kind != "image" or self.slot_id is None):
            raise ValueError(f"Layer {self.layer_id} background removal requires a bound image slot.")
        if self.trim_transparent_bounds and not self.remove_background:
            raise ValueError(f"Layer {self.layer_id} can trim transparent bounds only after background removal.")
        if self.entrance_effect is not None:
            from mediastudio.video_editor.effects import ENTRANCE_EFFECTS
            if self.entrance_effect not in ENTRANCE_EFFECTS:
                raise ValueError(f"Layer {self.layer_id} uses unknown entrance effect {self.entrance_effect!r}.")
            if self.kind == "text" or self.keyframes:
                raise ValueError(f"Layer {self.layer_id} entrance effects apply to image/video layers without keyframes.")
        if self.subject_centered and (not self.remove_background or self.trim_transparent_bounds):
            raise ValueError(
                f"Layer {self.layer_id} subject centring needs an untrimmed background-removed image."
            )
        return self


class TemplateTimelineEvent(StrictModel):
    event_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    timeline_start_ticks: int = Field(ge=0, le=MAX_TIME_TICKS)
    duration_ticks: int = Field(gt=0, le=MAX_TIME_TICKS)
    layers: list[TemplateLayer] = Field(min_length=1, max_length=64)
    event_classification: Literal[
        "BACKGROUND_CUT", "OVERLAY_REPLACEMENT", "OVERLAY_APPEAR", "OVERLAY_DISAPPEAR",
        "LAYOUT_CHANGE", "OBSERVED_MOTION", "UNKNOWN",
    ] = "UNKNOWN"
    source_evidence: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_end(self) -> "TemplateTimelineEvent":
        if self.timeline_start_ticks + self.duration_ticks > MAX_TIME_TICKS:
            raise ValueError(f"Event {self.event_id} exceeds the Project V2 timeline limit.")
        layer_ids = [layer.layer_id for layer in self.layers]
        if len(layer_ids) != len(set(layer_ids)):
            raise ValueError(f"Event {self.event_id} repeats a layer ID.")
        return self


class TemplateAssetDependency(StrictModel):
    asset_id: str = Field(min_length=1, max_length=256)
    kind: Literal["image", "sticker", "mask", "font_style", "licensed_audio", "effect"]
    license_reference: str | None = Field(default=None, max_length=512)


class TemplateDefinition(StrictModel):
    schema_version: Literal[1] = 1
    template_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-z0-9.-]+)?$")
    name: str = Field(min_length=1, max_length=120)
    width: int = Field(ge=64, le=3840, multiple_of=2)
    height: int = Field(ge=64, le=3840, multiple_of=2)
    frame_rate_numerator: int = Field(ge=1, le=240_000)
    frame_rate_denominator: int = Field(ge=1, le=100_000)
    duration_ticks: int = Field(gt=0, le=MAX_TIME_TICKS)
    demo_asset_reference: str | None = None
    poster_asset_reference: str | None = None
    audio_asset_reference: str | None = None
    supported_capabilities: list[str] = Field(default_factory=list, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)
    slots: list[TemplateMediaSlot] = Field(min_length=1, max_length=256)
    events: list[TemplateTimelineEvent] = Field(min_length=1, max_length=1000)
    asset_dependencies: list[TemplateAssetDependency] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def validate_references_and_ranges(self) -> "TemplateDefinition":
        if TIMEBASE * self.frame_rate_denominator % self.frame_rate_numerator:
            raise ValueError("Frame rate cannot be represented exactly by the Project V2 timebase.")
        slot_by_id = {slot.slot_id: slot for slot in self.slots}
        if len(slot_by_id) != len(self.slots):
            raise ValueError("Template definition contains duplicate slot IDs.")
        event_ids = [event.event_id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("Template definition contains duplicate event IDs.")
        last_event_tick = max(event.timeline_start_ticks + event.duration_ticks for event in self.events)
        if last_event_tick != self.duration_ticks:
            raise ValueError(
                "Template duration must end at its last render event; explicit background/tail semantics are unsupported."
            )
        used_slots: set[str] = set()
        order_kinds: dict[int, str] = {}
        for event in self.events:
            if event.timeline_start_ticks + event.duration_ticks > self.duration_ticks:
                raise ValueError(f"Event {event.event_id} extends beyond the template duration.")
            for layer in event.layers:
                by_property: dict[str, list[TemplateKeyframe]] = defaultdict(list)
                for key in layer.keyframes:
                    by_property[key.property].append(key)
                    low, high = {"positionX": (-2, 2), "positionY": (-2, 2), "scale": (0.1, 5),
                                 "rotation": (-180, 180), "opacity": (0, 1)}[key.property]
                    if not low <= key.value <= high:
                        raise ValueError(f"Keyframe {key.property} value is outside [{low}, {high}].")
                for prop, keys in by_property.items():
                    keys.sort(key=lambda key: key.time_ticks)
                    times = [key.time_ticks for key in keys]
                    if len(times) < 2 or times[0] != 0 or times[-1] != event.duration_ticks:
                        raise ValueError(f"Layer {layer.layer_id} keyframes for {prop} must start at 0 and end at the event duration.")
                    if len(times) != len(set(times)):
                        raise ValueError(f"Layer {layer.layer_id} repeats a {prop} keyframe timestamp.")
                    if any(time > event.duration_ticks for time in times):
                        raise ValueError(f"Layer {layer.layer_id} keyframe exceeds event duration.")
                if layer.kind == "text":
                    lane_kind = "text"
                elif layer.kind == "audio":
                    lane_kind = "audio"
                else:
                    lane_kind = "visual"
                prior_kind = order_kinds.setdefault(layer.layer_order, lane_kind)
                if prior_kind != lane_kind:
                    raise ValueError(f"Layer order {layer.layer_order} is used by more than one track kind.")
                if layer.asset_reference is not None:
                    if layer.kind != "image":
                        raise ValueError(f"Layer {layer.layer_id} uses a static asset for a non-image layer.")
                    continue
                if layer.slot_id is None:
                    continue
                slot = slot_by_id.get(layer.slot_id)
                if slot is None:
                    raise ValueError(f"Layer {layer.layer_id} references unknown slot {layer.slot_id}.")
                used_slots.add(slot.slot_id)
                required_kind = layer.kind
                if required_kind not in slot.allowed_media_kinds:
                    raise ValueError(
                        f"Layer {layer.layer_id} requires {required_kind}, but slot {slot.slot_id} does not allow it."
                    )
        unused_slots = sorted(set(slot_by_id) - used_slots)
        if unused_slots:
            raise ValueError(f"Template definition contains unreferenced media slots: {', '.join(unused_slots)}.")
        return self


MediaLookup = Callable[[str], Any]


class CompiledTemplate(StrictModel):
    project: VideoProjectV2
    composition_graph: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)


def compile_template(
    definition: TemplateDefinition | Mapping[str, Any],
    bindings: Mapping[str, str],
    media_lookup: MediaLookup,
    *,
    project_id: str | None = None,
    title: str | None = None,
) -> CompiledTemplate:
    """Validate bindings and compile the explicitly supported subset into V2.

    No media is copied or mutated. Canonical timeline timestamps stay in 90 kHz
    ticks; millisecond fields inside properties exist only for compatibility.
    """
    try:
        template = definition if isinstance(definition, TemplateDefinition) else TemplateDefinition.model_validate(definition)
    except Exception as error:
        raise TemplateCompilerError(f"Invalid template definition: {error}") from error

    unknown_bindings = sorted(set(bindings) - {slot.slot_id for slot in template.slots})
    if unknown_bindings:
        raise TemplateCompilerError(f"Bindings reference unknown slots: {', '.join(unknown_bindings)}.")

    resolved: dict[str, Any] = {}
    media_for_slot: dict[str, str] = {}
    missing_optional_slots: set[str] = set()
    warnings: list[str] = []
    unique_assets: dict[str, str] = {}
    for slot in template.slots:
        media_id = bindings.get(slot.slot_id)
        if not media_id:
            if slot.required or slot.missing_slot_policy == "error":
                raise TemplateCompilerError(f"Required media slot is missing: {slot.slot_id}.")
            missing_optional_slots.add(slot.slot_id)
            continue
        try:
            metadata = media_lookup(media_id)
        except (KeyError, ValueError) as error:
            raise TemplateCompilerError(f"Slot {slot.slot_id} references unavailable media {media_id}.") from error
        kind = _media_value(metadata, "kind")
        if kind not in slot.allowed_media_kinds:
            raise TemplateCompilerError(
                f"Media type {kind!r} is not allowed for slot {slot.slot_id}; "
                f"expected one of {', '.join(slot.allowed_media_kinds)}."
            )
        if slot.reuse_policy == "unique_asset":
            other_slot = unique_assets.get(media_id)
            if other_slot is not None:
                raise TemplateCompilerError(
                    f"Media {media_id} is bound to both {other_slot} and {slot.slot_id}; unique_asset policy forbids reuse."
                )
            unique_assets[media_id] = slot.slot_id
        resolved[slot.slot_id] = metadata
        media_for_slot[slot.slot_id] = media_id

    if template.asset_dependencies:
        dependencies = ", ".join(f"{item.kind}:{item.asset_id}" for item in template.asset_dependencies)
        raise TemplateCompilerError(f"Asset preprocessing/dependency resolution is not implemented: {dependencies}.")

    from mediastudio.video_editor.media_selection import resolve_template_asset
    for event in template.events:
        for layer in event.layers:
            if layer.asset_reference is None:
                continue
            try:
                resolve_template_asset(template.template_id, template.version, layer.asset_reference)
            except (OSError, ValueError) as error:
                raise TemplateCompilerError(
                    f"Template asset for layer {layer.layer_id} is unavailable: {error}"
                ) from error

    project_key = project_id or uuid4().hex
    if len(project_key) != 32 or any(character not in "0123456789abcdef" for character in project_key):
        raise TemplateCompilerError("project_id must be a lowercase 32-character hexadecimal ID.")

    lane_kinds: dict[int, str] = {}
    clips_by_order: dict[int, list[TimelineClipV2]] = defaultdict(list)
    for event in template.events:
        skip_event = any(
            layer.slot_id in missing_optional_slots
            for layer in event.layers
            if layer.slot_id is not None
        )
        if skip_event:
            skipped_slots = sorted({
                layer.slot_id for layer in event.layers
                if layer.slot_id in missing_optional_slots
            })
            warnings.append(
                f"Event {event.event_id} was skipped because optional slot(s) "
                f"{', '.join(skipped_slots)} are empty."
            )
            continue
        for layer in event.layers:
            _reject_unsupported_layer_features(event.event_id, layer)
            lane_kind = "text" if layer.kind == "text" else "audio" if layer.kind == "audio" else "visual"
            lane_kinds[layer.layer_order] = lane_kind
            media_id: str | None = None
            source_start_ticks = layer.source_time_mapping.source_start_ticks
            if layer.slot_id is not None:
                metadata = resolved.get(layer.slot_id)
                if metadata is None:
                    raise TemplateCompilerError(f"Slot {layer.slot_id} did not resolve to imported media.")
                media_id = media_for_slot[layer.slot_id]
                media_kind = _media_value(metadata, "kind")
                if media_kind != layer.kind:
                    raise TemplateCompilerError(
                        f"Layer {layer.layer_id} requires {layer.kind}, but bound media is {media_kind}."
                    )
                if layer.source_time_mapping.rate_numerator != layer.source_time_mapping.rate_denominator:
                    raise TemplateCompilerError(
                        f"Layer {layer.layer_id} uses source speed mapping; only 1:1 source timing is supported."
                    )
                if media_kind == "image" and source_start_ticks != 0:
                    raise TemplateCompilerError(f"Image layer {layer.layer_id} must start at source tick zero.")
                duration_ms = _media_value(metadata, "duration_ms")
                if media_kind in {"video", "audio"}:
                    if not isinstance(duration_ms, int) or duration_ms <= 0:
                        raise TemplateCompilerError(f"Cannot read source duration for {layer.layer_id}.")
                    if source_start_ticks + event.duration_ticks > duration_ms * 90:
                        raise TemplateCompilerError(f"Layer {layer.layer_id} exceeds its source media duration.")

            clip_id = uuid5(
                NAMESPACE_URL,
                f"mediastudio:{project_key}:{template.template_id}:{template.version}:{event.event_id}:{layer.layer_id}",
            ).hex
            props = _layer_properties(layer, event, clip_id, media_id, source_start_ticks)
            if layer.asset_reference is not None:
                props["templateAssetReference"] = layer.asset_reference
                props["templateAssetId"] = template.template_id
                props["templateAssetDefinitionVersion"] = template.version
            clip_template_metadata = {
                "templateId": template.template_id,
                "templateDefinitionVersion": template.version,
                "eventId": event.event_id,
                "layerId": layer.layer_id,
                "slotId": layer.slot_id,
            }
            if event.event_classification != "UNKNOWN":
                clip_template_metadata["eventClassification"] = event.event_classification
            if event.source_evidence:
                clip_template_metadata["sourceEvidence"] = event.source_evidence
            if layer.motion_classification != "UNVERIFIED":
                clip_template_metadata["motionClassification"] = layer.motion_classification
            clips_by_order[layer.layer_order].append(TimelineClipV2(
                clip_id=clip_id,
                track_id=_track_id(project_key, layer.layer_order),
                clip_kind=layer.kind,
                timeline_start_ticks=event.timeline_start_ticks,
                source_start_ticks=source_start_ticks if lane_kind != "text" else 0,
                duration_ticks=event.duration_ticks,
                media_id=media_id,
                properties=props,
                template_metadata=clip_template_metadata,
            ))

    if not clips_by_order:
        raise TemplateCompilerError("No renderable events remain after applying optional-slot policies.")
    if len(clips_by_order) > 100:
        raise TemplateCompilerError("Project V2 supports at most 100 tracks; template has more layer orders.")

    tracks = [
        TimelineTrackV2(
            track_id=_track_id(project_key, layer_order),
            kind=lane_kinds[layer_order],
            layer_order=layer_order,
            display_name=f"Template layer {layer_order}",
            clips=sorted(clips, key=lambda clip: (clip.timeline_start_ticks, clip.clip_id)),
        )
        for layer_order, clips in sorted(clips_by_order.items())
    ]
    project = VideoProjectV2(
        schema_version=2,
        project_id=project_key,
        template_id=template.template_id,
        title=(title or template.name)[:160],
        width=template.width,
        height=template.height,
        frame_rate_numerator=template.frame_rate_numerator,
        frame_rate_denominator=template.frame_rate_denominator,
        timebase=TIMEBASE,
        tracks=tracks,
        template_metadata={
            "templateId": template.template_id,
            "templateDefinitionVersion": template.version,
            "templateCompilerVersion": "1.0.0",
            "templateDurationTicks": template.duration_ticks,
            "templateSupportedCapabilities": list(template.supported_capabilities),
            "templateBindings": dict(sorted(media_for_slot.items())),
            **({"definitionMetadata": template.metadata} if template.metadata else {}),
        },
    )
    try:
        graph = build_composition_graph(project, media_lookup)
    except (ValueError, KeyError) as error:
        raise TemplateCompilerError(f"Project V2 could not form a Composition Graph: {error}") from error
    if graph.duration_ticks < template.duration_ticks:
        warnings.append(
            f"Compiled duration is {graph.duration_ticks} ticks; optional-event policy shortened the "
            f"template duration from {template.duration_ticks} ticks."
        )
    return CompiledTemplate(project=project, composition_graph=graph.to_dict(), warnings=warnings)


def _reject_unsupported_layer_features(event_id: str, layer: TemplateLayer) -> None:
    unsupported: list[str] = []
    if layer.keyframes and layer.kind not in {"image", "video"}:
        unsupported.append("keyframes on non-visual layer")
    text_style_requested = (layer.text_box or layer.text_box_opacity > 0 or layer.text_box_border_width > 0
                            or layer.text_box_color.upper() != "#000000"
                            or layer.text_box_border_color.upper() != "#FFFFFF"
                            or layer.shadow_color is not None or layer.shadow_x != 0 or layer.shadow_y != 0)
    if text_style_requested and layer.kind != "text":
        unsupported.append("text graphic style on a non-text layer")
    if layer.mask_reference:
        unsupported.append("mask")
    if layer.cutout_reference:
        unsupported.append("foreground cutout")
    if layer.sticker_reference:
        unsupported.append("sticker asset")
    if layer.transition not in (None, "cut") or (layer.transition is not None and layer.kind not in {"image", "video"}):
        unsupported.append(f"{layer.transition} transition")
    if layer.kind == "text":
        if (layer.source_time_mapping.source_start_ticks != 0
                or layer.source_time_mapping.rate_numerator != layer.source_time_mapping.rate_denominator):
            unsupported.append("source time mapping on text")
        if (layer.fit_mode != "cover" or layer.position_x != 0 or layer.position_y != 0
                or layer.scale != 1 or layer.rotation != 0 or layer.effect != "none"
                or layer.audio_volume != 1 or layer.volume != 1 or layer.fade_in_ms != 0
                or layer.fade_out_ms != 0):
            unsupported.append("visual/audio properties on text")
    elif layer.kind == "audio":
        if layer.text is not None:
            unsupported.append("text content on audio")
        if (layer.fit_mode != "cover" or layer.position_x != 0 or layer.position_y != 0
                or layer.scale != 1 or layer.rotation != 0 or layer.effect != "none"
                or layer.opacity != 1 or layer.audio_volume != 1 or layer.text_x != 0.5
                or layer.text_y != 0.5 or layer.font_size != 52 or layer.color.upper() != "#FFFFFF"
                or layer.font_family != "Arial"):
            unsupported.append("visual properties on audio")
    else:
        if layer.text is not None:
            unsupported.append("text content on a media layer")
        if (layer.text_x != 0.5 or layer.text_y != 0.5 or layer.font_size != 52
                or layer.color.upper() != "#FFFFFF" or layer.font_family != "Arial"
                or layer.volume != 1 or layer.fade_in_ms != 0 or layer.fade_out_ms != 0):
            unsupported.append("text/audio properties on a visual layer")
        if layer.kind == "image" and layer.audio_volume != 1:
            unsupported.append("embedded audio gain on an image")
    if unsupported:
        raise TemplateCompilerError(
            f"Event {event_id}, layer {layer.layer_id} requests unsupported features: {', '.join(unsupported)}."
        )


def _layer_properties(
    layer: TemplateLayer,
    event: TemplateTimelineEvent,
    clip_id: str,
    media_id: str | None,
    source_start_ticks: int,
) -> dict[str, Any]:
    source_start_ms = source_start_ticks // 90
    duration_ms = max(1, event.duration_ticks // 90)
    if layer.kind == "text":
        properties = {
            "layerId": clip_id,
            "text": layer.text,
            "startMs": event.timeline_start_ticks // 90,
            "durationMs": duration_ms,
            "x": layer.text_x,
            "y": layer.text_y,
            "fontSize": layer.font_size,
            "color": layer.color.upper(),
            "fontFamily": layer.font_family,
            "opacity": layer.opacity,
        }
        if layer.text_box or layer.text_box_opacity or layer.text_box_border_width:
            properties.update({
                "textBox": layer.text_box,
                "textBoxColor": layer.text_box_color.upper(),
                "textBoxOpacity": layer.text_box_opacity,
                "textBoxBorderWidth": layer.text_box_border_width,
                "textBoxBorderColor": layer.text_box_border_color.upper(),
            })
        if layer.shadow_color:
            properties.update({"shadowColor": layer.shadow_color.upper(),
                               "shadowX": layer.shadow_x, "shadowY": layer.shadow_y})
        return properties
    if layer.kind == "audio":
        return {
            "trackId": clip_id,
            "mediaId": media_id,
            "timelineStartMs": event.timeline_start_ticks // 90,
            "sourceStartMs": source_start_ms,
            "durationMs": duration_ms,
            "volume": layer.volume,
            "fadeInMs": layer.fade_in_ms,
            "fadeOutMs": layer.fade_out_ms,
        }
    properties = {
        "name": layer.layer_id,
        "clipId": clip_id,
        "mediaId": media_id,
        "sourceStartMs": source_start_ms,
        "durationMs": duration_ms,
        "fitMode": layer.fit_mode,
        "positionX": layer.position_x,
        "positionY": layer.position_y,
        "scale": layer.scale,
        "rotation": layer.rotation,
        "effect": layer.effect,
        "opacity": layer.opacity,
        "audioVolume": layer.audio_volume,
        "transition": "cut",
        "transitionDurationMs": 0,
    }
    if layer.remove_background:
        properties["removeBackground"] = True
    if layer.trim_transparent_bounds:
        properties["trimTransparentBounds"] = True
    if layer.subject_centered:
        properties["subjectCentered"] = True
    if layer.entrance_effect is not None:
        properties["entranceEffect"] = layer.entrance_effect
    if layer.keyframes:
        properties["keyframes"] = [key.model_dump(mode="json", by_alias=True) for key in layer.keyframes]
    return properties


def _track_id(project_id: str, layer_order: int) -> str:
    return uuid5(NAMESPACE_URL, f"mediastudio:{project_id}:template-layer:{layer_order}").hex


def _media_value(media: Any, snake_name: str) -> Any:
    if isinstance(media, Mapping):
        camel_name = snake_name.split("_")[0] + "".join(part.capitalize() for part in snake_name.split("_")[1:])
        return media.get(snake_name, media.get(camel_name))
    return getattr(media, snake_name, None)
