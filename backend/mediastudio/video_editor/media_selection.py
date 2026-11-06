"""Versioned template binding validation with a legacy compatibility subset."""
from functools import lru_cache
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Mapping

from pydantic import Field
from mediastudio.video_editor.models import StrictModel
from mediastudio.video_editor.project_v2 import MAX_TIME_TICKS
from mediastudio.video_editor.template_compiler import TemplateDefinition, compile_template

# Explicit placeholder mapping reviewed against VideoTemplate.create_project.
# Not a general scene -> slot inference. Other catalog entries remain disabled.
LEGACY_PLACEHOLDERS = {
    "denim-story": (("denim-close-up", 3000), ("lookbook", 3000), ("fabric-detail", 3000),
                    ("everyday-wear", 3000), ("final-look", 3000)),
    "travel-reel": (("travel-1", 4000), ("travel-2", 4000), ("travel-3", 4000),
                    ("travel-4", 4000), ("travel-5", 4000)),
    "product-intro": (("product-1", 3000), ("product-2", 3000), ("product-3", 3000),
                      ("product-4", 3000), ("product-5", 3000), ("product-6", 3000)),
}
VERSION = "1.0.0-legacy"
MAX_TEMPLATE_MEDIA = 40
DEFINITION_FILES = {
    "fall-diary": {
        "0.1.0-pilot": Path(__file__).with_name("definitions") / "fall-diary-0.1.0-pilot.json",
        "0.2.0-motion-pilot": Path(__file__).with_name("definitions") / "fall-diary-0.2.0-motion-pilot.json",
        "0.3.0-reference-pilot": Path(__file__).with_name("definitions") / "fall-diary-0.3.0-reference-pilot.json",
        "0.4.0-editorial-motion-pilot": Path(__file__).with_name("definitions") / "fall-diary-0.4.0-editorial-motion-pilot.json",
        "0.5.0-layer-structure-pilot": Path(__file__).with_name("definitions") / "fall-diary-0.5.0-layer-structure-pilot.json",
        "0.6.0-dynamic-batches": Path(__file__).with_name("definitions") / "fall-diary-0.6.0-dynamic-batches.json",
        "0.7.0-reference-timing": Path(__file__).with_name("definitions") / "fall-diary-0.7.0-reference-timing.json",
        "0.8.0-intro-title": Path(__file__).with_name("definitions") / "fall-diary-0.8.0-intro-title.json",
        "0.9.0-reference-overlays": Path(__file__).with_name("definitions") / "fall-diary-0.9.0-reference-overlays.json",
    },
    "autumn-love-40": {
        "1.0.0-reference-sequence": Path(__file__).with_name("definitions") / "autumn-love-40-1.0.0-reference-sequence.json",
    },
}
LATEST_DEFINITION_VERSIONS = {
    "fall-diary": "0.9.0-reference-overlays",
    "autumn-love-40": "1.0.0-reference-sequence",
}
FALL_DIARY_MAX_MEDIA = 36
FALL_DIARY_GROUP_SIZE = 9
FALL_DIARY_FIRST_BACKGROUND_DURATION_MS = 5_200
FALL_DIARY_SUBSEQUENT_BACKGROUND_DURATION_MS = 4_000
FALL_DIARY_FIRST_BACKGROUND_TITLE_OVERLAP_MS = 1_200
FALL_DIARY_TITLE_DURATION_MS = 1_200
FALL_DIARY_REFERENCE_TIMING_VERSIONS = frozenset((
    "0.7.0-reference-timing", "0.8.0-intro-title", "0.9.0-reference-overlays",
))
# Versions that show the title only as a short intro. 0.9 is deliberately absent:
# frames sampled every 0.5s across the reference recording show FALL DIARY present
# from 0.5s through 7.0s, including after the background group changes, so its
# title spans the whole template rather than the first 1.2 seconds.
FALL_DIARY_INTRO_TITLE_VERSIONS = frozenset(("0.8.0-intro-title",))
# Versions whose overlays accumulate: each cut-out stays on screen once it
# appears and is covered by the next one, until its background group ends. The
# reference clears the stack only when the next background starts.
FALL_DIARY_ACCUMULATING_OVERLAY_VERSIONS = frozenset(("0.9.0-reference-overlays",))
# Accumulated overlays coexist in time, so each needs its own layerOrder: layers
# sharing an order share a track, and a track rejects visual clips that overlap.
# Appearance order doubles as stacking order, so a later cut-out covers earlier
# ones. Background holds 0 and the title holds 20, leaving 1..8 for a group of
# at most eight overlays.
FALL_DIARY_FIRST_OVERLAY_LAYER_ORDER = 1
# How an overlay is framed inside the canvas.
#   "subject-centered" - what the reference actually does, measured by registering
#                        its frames against the source photos: the whole photo
#                        is kept at 1.35x canvas height and slid so the visible
#                        subject sits at (0.50, 0.60) of the canvas, never letting
#                        a photo edge enter more than 6 percent. The placement is
#                        computed at render time from the cut-out (framing.py).
#   "trimmed-contain"  - crop to the cut-out's visible alpha bounds, then fit that
#                        box at FALL_DIARY_OVERLAY_SCALE. A subject that occupies
#                        only part of its photo still reads large, which is what
#                        the reference does: in its mug shot the cup spans about
#                        three quarters of the width, and trimming reproduces that.
#   "full-frame-cover" - place the whole photo at native framing. Every 9:16 photo
#                        then fills the canvas, but a subject sitting in part of a
#                        squarer photo reads small - the same mug lands near 45
#                        percent of the width.
# Trimming was switched off at one point because apparent size then varied about
# threefold with subject shape. That disparity came from isnet's fragmentary
# masks: a dropped hand left a mug-sized box and a sliced trouser leg left a
# narrow strip. BiRefNet returns the whole subject group, so the trimmed box now
# tracks the real subject and the original framing is the better match again.
FALL_DIARY_OVERLAY_FRAMING = "subject-centered"
FALL_DIARY_OVERLAY_SCALE = 0.74
# Entrance effect for every cut-out (effects.ENTRANCE_EFFECTS); "" disables.
FALL_DIARY_OVERLAY_ENTRANCE_EFFECT = "zoom-settle"
FALL_DIARY_OVERLAY_POSITION_Y = 0.06


def resolve_template_asset(template_id: str, version: str, asset_reference: str) -> Path:
    """Resolve a bundled template image while keeping references inside its definition folder."""
    versions = DEFINITION_FILES.get(template_id)
    definition_path = versions.get(version) if versions is not None else None
    if definition_path is None:
        raise ValueError(f"Template definition {template_id}@{version} is unavailable.")
    relative = PurePosixPath(asset_reference)
    if (not asset_reference or "\\" in asset_reference or ":" in asset_reference
            or PureWindowsPath(asset_reference).is_absolute() or relative.is_absolute()
            or any(part in {"", ".", ".."} for part in relative.parts)):
        raise ValueError("Template asset path must be relative and cannot escape its definition folder.")
    root = definition_path.parent.resolve()
    path = root.joinpath(*relative.parts).resolve()
    if path == root or root not in path.parents:
        raise ValueError("Template asset path escapes its definition folder.")
    if not path.is_file():
        raise FileNotFoundError(f"Template asset does not exist: {asset_reference}.")
    return path


@lru_cache(maxsize=32)
def get_template_definition(template_id: str, version: str | None = None) -> TemplateDefinition | None:
    versions = DEFINITION_FILES.get(template_id)
    if versions is None:
        return None
    requested_version = version or LATEST_DEFINITION_VERSIONS.get(template_id)
    path = versions.get(requested_version)
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return TemplateDefinition.model_validate(payload)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"Template definition {template_id} không hợp lệ: {error}") from error


def _story_template(template_id: str):
    """Photo story template (image output) with this id, or None."""
    from mediastudio.video_editor.story_templates import StoryTemplateError, get_story_template
    try:
        return get_story_template(template_id)
    except StoryTemplateError:
        return None


def story_slot_ids(story) -> list[str]:
    from mediastudio.video_editor.story_templates import iter_photo_slots
    return [f"page-{page:02d}-photo-{cell:02d}" for page, cell in iter_photo_slots(story)]


def template_definition_version(template_id: str) -> str | None:
    story = _story_template(template_id)
    if story is not None:
        return str(story.data.get("version", "1.0.0"))
    definition = get_template_definition(template_id)
    if definition is not None:
        return definition.version
    return VERSION if template_id in LEGACY_PLACEHOLDERS else None


def slot_requirements(template_id):
    story = _story_template(template_id)
    if story is not None:
        return [dict(slotId=slot_id, allowedMediaKinds=["image"], required=True,
                     reusePolicy="allow", missingSlotPolicy="error")
                for slot_id in story_slot_ids(story)]
    definition = get_template_definition(template_id)
    if definition is not None:
        policy = definition.metadata.get("selectionPolicy", {})
        if policy.get("mode") == "background-batches-of-nine":
            result = []
            for index in range(FALL_DIARY_MAX_MEDIA):
                group_number, position = divmod(index, FALL_DIARY_GROUP_SIZE)
                group_id = f"group-{group_number + 1:02d}"
                is_background = position == 0
                result.append(dict(
                    slotId=f"{group_id}-background" if is_background else f"{group_id}-overlay-{position:02d}",
                    allowedMediaKinds=["image", "video"] if is_background else ["image"],
                    required=index == 0,
                    reusePolicy="allow",
                    missingSlotPolicy="error" if index == 0 else "skip_event",
                ))
            return result
        if policy.get("mode") == "ordered-40-frame-sequence":
            durations = policy.get("mediaDurationsMs", [])
            return [
                {**slot.public_dict(), "durationMs": int(durations[index])}
                for index, slot in enumerate(definition.slots)
            ]
        return [slot.public_dict() for slot in definition.slots]
    return [dict(slotId=slot, allowedMediaKinds=["image", "video"], required=True,
                 reusePolicy="allow", missingSlotPolicy="error", durationMs=duration)
            for slot, duration in LEGACY_PLACEHOLDERS.get(template_id, ())]


class SelectionPayloadRequest(StrictModel):
    template_id: str = Field(min_length=1, max_length=64)
    template_definition_version: str
    bindings: dict[str, str] = Field(max_length=MAX_TEMPLATE_MEDIA)


class TemplateProcessingRequest(StrictModel):
    template_id: str = Field(min_length=1, max_length=64)
    template_definition_version: str = Field(min_length=1, max_length=40)
    selection_session_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    bindings: dict[str, str] = Field(min_length=1, max_length=MAX_TEMPLATE_MEDIA)


def prepare_payload(request: SelectionPayloadRequest, media_lookup):
    from mediastudio.video_editor.catalog import get_template
    template = get_template(request.template_id)
    story = _story_template(request.template_id)
    if story is not None:
        return prepare_story_payload(story, request, media_lookup)
    # Selection sessions are pinned to the definition version displayed by the
    # caller. This keeps older verified definitions usable for rollback while
    # the catalog's unversioned lookup continues to advertise the latest.
    definition = get_template_definition(request.template_id, request.template_definition_version)
    if definition is not None:
        slot_ids = {slot.slot_id for slot in definition.slots}
        if template is None or request.template_definition_version != definition.version:
            raise ValueError("Template definition unavailable or version changed.")
        if definition.metadata.get("selectionPolicy", {}).get("mode") == "background-batches-of-nine":
            dynamic_definition = _build_fall_diary_selection_definition(
                definition, request.bindings, media_lookup, title=template.name,
            )
            try:
                compile_template(
                    dynamic_definition,
                    request.bindings,
                    media_lookup,
                    project_id="0" * 32,
                    title=template.name,
                )
            except ValueError as error:
                raise ValueError(str(error)) from error
            return dict(
                templateId=template.template_id,
                templateDefinitionVersion=definition.version,
                definition=dynamic_definition.model_dump(mode="json", by_alias=True),
                bindings=request.bindings,
            )
        if definition.metadata.get("selectionPolicy", {}).get("mode") == "ordered-40-frame-sequence":
            dynamic_definition = _build_autumn_love_40_selection_definition(
                definition, request.bindings, media_lookup,
            )
            try:
                compile_template(
                    dynamic_definition,
                    request.bindings,
                    media_lookup,
                    project_id="0" * 32,
                    title=template.name,
                )
            except ValueError as error:
                raise ValueError(str(error)) from error
            return dict(
                templateId=template.template_id,
                templateDefinitionVersion=definition.version,
                definition=dynamic_definition.model_dump(mode="json", by_alias=True),
                bindings=request.bindings,
            )
        if set(request.bindings) != slot_ids:
            raise ValueError("Bindings must contain exactly the required slot IDs.")
        try:
            # Compile once in memory during binding validation. This has no
            # persistence or render side effects and catches media-kind,
            # source-bound, reuse-policy, and unsupported-feature errors before
            # a processing job is created.
            compile_template(
                definition,
                request.bindings,
                media_lookup,
                project_id="0" * 32,
                title=template.name,
            )
        except ValueError as error:
            raise ValueError(str(error)) from error
        return dict(
            templateId=template.template_id,
            templateDefinitionVersion=definition.version,
            definition=definition.model_dump(mode="json", by_alias=True),
            bindings=request.bindings,
        )

    mapping = LEGACY_PLACEHOLDERS.get(request.template_id)
    if template is None or not mapping or request.template_definition_version != VERSION:
        raise ValueError("Template definition unavailable or version changed.")
    if set(request.bindings) != {slot for slot, _ in mapping}:
        raise ValueError("Bindings must contain exactly the required slot IDs.")
    events = []
    start = 0
    for slot, duration in mapping:
        media = media_lookup(request.bindings[slot])
        if media.kind not in ("image", "video"):
            raise ValueError(f"Unsupported media kind for {slot}.")
        if media.kind == "video" and (media.duration_ms or 0) < duration:
            raise ValueError(f"Video for {slot} must be at least {duration} ms.")
        events.append(dict(eventId=slot, timelineStartTicks=start, durationTicks=duration * 90,
                           layers=[dict(layerId=slot, kind=media.kind, layerOrder=0, slotId=slot)]))
        start += duration * 90
    if template.text:
        events.append(dict(eventId="title", timelineStartTicks=0,
                           durationTicks=min(6000, template.duration_ms) * 90,
                           layers=[dict(layerId="title", kind="text", layerOrder=1,
                                        text=template.text, textY=0.28, fontSize=76)]))
    # Resolve the polymorphic legacy visual placeholder to an existing compiler
    # image/video layer. The compiler schema itself is unchanged.
    definition = TemplateDefinition.model_validate(dict(
        templateId=template.template_id, version=VERSION, name=template.name,
        width=template.width, height=template.height, frameRateNumerator=30,
        frameRateDenominator=1, durationTicks=template.duration_ms * 90,
        slots=[{key: value for key, value in slot.items() if key != "durationMs"}
               for slot in slot_requirements(template.template_id)], events=events))
    return dict(templateId=template.template_id, templateDefinitionVersion=VERSION,
                definition=definition.model_dump(mode="json", by_alias=True), bindings=request.bindings)


def _build_fall_diary_selection_definition(base: TemplateDefinition, bindings, media_lookup, *, title: str):
    """Compile the selected prefix into batches of one background plus up to eight image overlays."""
    from copy import deepcopy

    requirements = slot_requirements(base.template_id)
    ordered_slot_ids = [str(slot["slotId"]) for slot in requirements]
    media_count = len(bindings)
    if not 1 <= media_count <= FALL_DIARY_MAX_MEDIA:
        raise ValueError(f"Fall Diary cần từ 1 đến {FALL_DIARY_MAX_MEDIA} media đã chọn.")
    expected_ids = ordered_slot_ids[:media_count]
    if set(bindings) != set(expected_ids):
        raise ValueError("Fall Diary media cần được gán theo thứ tự liên tục từ vị trí đầu tiên.")

    active_slots = []
    resolved = {}
    for rule in requirements[:media_count]:
        slot_id = str(rule["slotId"])
        metadata = media_lookup(bindings[slot_id])
        kind = getattr(metadata, "kind", None)
        if kind is None and isinstance(metadata, Mapping):
            kind = metadata.get("kind", metadata.get("mediaKind"))
        if kind not in rule["allowedMediaKinds"]:
            role = "ảnh hoặc video nền" if slot_id.endswith("background") else "ảnh phủ"
            raise ValueError(f"Vị trí {len(active_slots) + 1} cần {role}; không thể dùng media loại {kind!r}.")
        if slot_id.endswith("background") and kind == "video":
            source_duration_ms = getattr(metadata, "duration_ms", None)
            if source_duration_ms is None and isinstance(metadata, Mapping):
                source_duration_ms = metadata.get("duration_ms", metadata.get("durationMs"))
            if not isinstance(source_duration_ms, int) or source_duration_ms <= 0:
                raise ValueError(f"Không đọc được thời lượng nền video tại vị trí {len(active_slots) + 1}.")
            if base.version in FALL_DIARY_REFERENCE_TIMING_VERSIONS:
                group_number = len(active_slots) // FALL_DIARY_GROUP_SIZE
                target_duration_ms = (FALL_DIARY_FIRST_BACKGROUND_DURATION_MS if group_number == 0
                                      else FALL_DIARY_SUBSEQUENT_BACKGROUND_DURATION_MS)
                if source_duration_ms < target_duration_ms:
                    raise ValueError(
                        f"Video nền tại vị trí {len(active_slots) + 1} cần dài ít nhất "
                        f"{target_duration_ms / 1000:g} giây theo nhịp của mẫu."
                    )
        resolved[slot_id] = (metadata, kind)
        active_slots.append({**rule, "required": True, "missingSlotPolicy": "error"})

    events = []
    timeline_start = 0
    group_durations = []
    for group_start in range(0, media_count, FALL_DIARY_GROUP_SIZE):
        group_slots = active_slots[group_start:group_start + FALL_DIARY_GROUP_SIZE]
        background_slot = group_slots[0]
        background_id = background_slot["slotId"]
        background_metadata, background_kind = resolved[background_id]
        if base.version in FALL_DIARY_REFERENCE_TIMING_VERSIONS:
            background_duration_ms = (FALL_DIARY_FIRST_BACKGROUND_DURATION_MS if not group_durations
                                      else FALL_DIARY_SUBSEQUENT_BACKGROUND_DURATION_MS)
        elif background_kind == "image":
            background_duration_ms = 17_000
        else:
            background_duration_ms = getattr(background_metadata, "duration_ms", None)
            if background_duration_ms is None and isinstance(background_metadata, Mapping):
                background_duration_ms = background_metadata.get("duration_ms", background_metadata.get("durationMs"))
        if not isinstance(background_duration_ms, int) or background_duration_ms <= 0:
            raise ValueError(f"Không đọc được thời lượng nền {background_id}.")
        duration_ticks = background_duration_ms * 90
        if duration_ticks > MAX_TIME_TICKS:
            raise ValueError(f"Thời lượng nền {background_id} vượt giới hạn timeline.")
        group_end = timeline_start + duration_ticks
        if group_end > MAX_TIME_TICKS:
            raise ValueError("Tổng thời lượng các nhóm media vượt giới hạn timeline.")

        events.append(dict(
            eventId=f"{background_id}-event",
            timelineStartTicks=timeline_start,
            durationTicks=duration_ticks,
            eventClassification="BACKGROUND_CUT",
            sourceEvidence=(
                "Nền đầu dài 5,2 giây; mỗi nền tiếp theo dài 4 giây. Video nền được cắt theo nhịp mẫu."
                if base.version in FALL_DIARY_REFERENCE_TIMING_VERSIONS
                else "Media đầu nhóm làm nền; ảnh nền mặc định 17 giây, video nền dùng thời lượng nguồn."
            ),
            layers=[dict(
                layerId=background_id,
                kind=background_kind,
                layerOrder=0,
                slotId=background_id,
                fitMode="cover",
                positionX=0.0,
                positionY=0.0,
                scale=1.0,
            )],
        ))

        overlay_slots = group_slots[1:]
        overlay_count = len(overlay_slots)
        overlay_sequence_start = timeline_start
        overlay_sequence_duration = duration_ticks
        if base.version == "0.9.0-reference-overlays" and not group_durations:
            intro_overlap_ticks = min(FALL_DIARY_FIRST_BACKGROUND_TITLE_OVERLAP_MS * 90, duration_ticks)
            overlay_sequence_start += intro_overlap_ticks
            overlay_sequence_duration -= intro_overlap_ticks
        for overlay_index, overlay_slot in enumerate(overlay_slots):
            slot_id = overlay_slot["slotId"]
            offset_start = overlay_sequence_duration * overlay_index // overlay_count
            offset_end = overlay_sequence_duration * (overlay_index + 1) // overlay_count
            if offset_end <= offset_start:
                raise ValueError(f"Nền nhóm quá ngắn để hiển thị tuần tự {overlay_count} ảnh phủ.")
            large_centered = base.version == "0.9.0-reference-overlays"
            trimmed_framing = FALL_DIARY_OVERLAY_FRAMING == "trimmed-contain"
            subject_framing = FALL_DIARY_OVERLAY_FRAMING == "subject-centered"
            accumulating = base.version in FALL_DIARY_ACCUMULATING_OVERLAY_VERSIONS
            if accumulating:
                # Stay on screen from this slot's turn until the group ends, so
                # later cut-outs pile on top instead of replacing this one.
                overlay_duration = overlay_sequence_duration - offset_start
                overlay_layer_order = FALL_DIARY_FIRST_OVERLAY_LAYER_ORDER + overlay_index
            else:
                overlay_duration = offset_end - offset_start
                overlay_layer_order = 1
            events.append(dict(
                eventId=f"{slot_id}-event",
                timelineStartTicks=overlay_sequence_start + offset_start,
                durationTicks=overlay_duration,
                eventClassification="OVERLAY_APPEAR",
                sourceEvidence=("Ảnh được tách nền tự động, xuất hiện lần lượt rồi chồng tích luỹ "
                                "lên nhau cho tới hết nền của nhóm."
                                if accumulating else
                                "Ảnh được tách nền tự động rồi lần lượt phủ lên nền của nhóm."),
                layers=[dict(
                    layerId=slot_id,
                    kind="image",
                    layerOrder=overlay_layer_order,
                    slotId=slot_id,
                    # See FALL_DIARY_OVERLAY_FRAMING for why trimming is on.
                    fitMode=("contain" if trimmed_framing or subject_framing else "cover")
                    if large_centered else "contain",
                    positionX=0.0 if large_centered else 0.28,
                    positionY=(FALL_DIARY_OVERLAY_POSITION_Y if trimmed_framing else 0.0)
                    if large_centered else 0.3,
                    scale=(FALL_DIARY_OVERLAY_SCALE if trimmed_framing else 1.0) if large_centered else 0.18,
                    removeBackground=True,
                    **({"trimTransparentBounds": True} if large_centered and trimmed_framing else {}),
                    **({"subjectCentered": True} if large_centered and subject_framing else {}),
                    # Measured on the reference: each cut-out pops in at 1.195x
                    # and settles to its size in about half a second.
                    **({"entranceEffect": FALL_DIARY_OVERLAY_ENTRANCE_EFFECT}
                       if large_centered and FALL_DIARY_OVERLAY_ENTRANCE_EFFECT else {}),
                )],
            ))
        timeline_start = group_end
        group_durations.append(background_duration_ms)

    title_event = next((event for event in base.events if event.event_id == "title-graphic"), None)
    if title_event is None:
        raise ValueError("Fall Diary không có lớp tiêu đề SVG.")
    title_duration_ticks = timeline_start
    if base.version in FALL_DIARY_INTRO_TITLE_VERSIONS:
        title_duration_ticks = min(FALL_DIARY_TITLE_DURATION_MS * 90, timeline_start)
    title_event = title_event.model_copy(update={"timeline_start_ticks": 0, "duration_ticks": title_duration_ticks})
    events.append(title_event.model_dump(mode="json", by_alias=True))

    payload = base.model_dump(mode="json", by_alias=True)
    payload.update({
        "durationTicks": timeline_start,
        "slots": active_slots,
        "events": events,
        "metadata": {
            **base.metadata,
            "selectionPlan": {
                "selectedMediaCount": media_count,
                "groupCount": len(group_durations),
                "backgroundDurationsMs": group_durations,
                "timelineDurationMs": timeline_start // 90,
                "firstBackgroundTitleOverlapMs": (FALL_DIARY_FIRST_BACKGROUND_TITLE_OVERLAP_MS
                                                   if base.version in FALL_DIARY_REFERENCE_TIMING_VERSIONS else None),
                "titleDurationMs": (FALL_DIARY_TITLE_DURATION_MS
                                    if base.version in FALL_DIARY_INTRO_TITLE_VERSIONS else None),
            },
        },
    })
    return TemplateDefinition.model_validate(payload)


BRIDGE_MS = 100


def _build_autumn_love_40_selection_definition(base: TemplateDefinition, bindings, media_lookup):
    """Bind the reference's 40 ordered media frames and their displayed durations."""
    policy = base.metadata.get("selectionPolicy", {})
    durations = policy.get("mediaDurationsMs", [])
    if len(base.slots) != 40 or len(durations) != 40:
        raise ValueError("Autumn Love 40 cần đúng 40 vị trí và 40 thời lượng mẫu.")
    slot_ids = [slot.slot_id for slot in base.slots]
    if set(bindings) != set(slot_ids):
        raise ValueError("Autumn Love 40 cần gán đủ 40 media theo đúng thứ tự.")

    resolved = {}
    for index, slot in enumerate(base.slots):
        metadata = media_lookup(bindings[slot.slot_id])
        kind = getattr(metadata, "kind", None)
        if kind is None and isinstance(metadata, Mapping):
            kind = metadata.get("kind", metadata.get("mediaKind"))
        if kind not in ("image", "video"):
            raise ValueError(f"Vị trí {index + 1} chỉ nhận ảnh hoặc video.")
        if kind == "video":
            source_duration_ms = getattr(metadata, "duration_ms", None)
            if source_duration_ms is None and isinstance(metadata, Mapping):
                source_duration_ms = metadata.get("duration_ms", metadata.get("durationMs"))
            minimum_source_duration_ms = int(durations[index])
            if index == 12:
                minimum_source_duration_ms = 1_400
            elif index == 14:
                minimum_source_duration_ms = 1_000
            if not isinstance(source_duration_ms, int) or source_duration_ms < minimum_source_duration_ms:
                raise ValueError(
                    f"Video ở vị trí {index + 1} cần dài ít nhất {minimum_source_duration_ms / 1000:g} giây."
                )
        resolved[slot.slot_id] = (metadata, kind)

    events = []
    timeline_start = 0
    frame_starts = [0] * len(base.slots)

    def add_frame_event(index: int, start_ticks: int, duration_ms: int, *, hold_background: bool = False):
        slot = base.slots[index]
        _, kind = resolved[slot.slot_id]
        events.append(dict(
            eventId=f"{slot.slot_id}-event",
            timelineStartTicks=start_ticks,
            durationTicks=duration_ms * 90,
            eventClassification="BACKGROUND_CUT",
            sourceEvidence=(
                f"Khung {index + 1}/40; thời lượng theo strip mẫu: "
                f"{int(durations[index]) / 1000:g} giây."
                + (" Cảnh nền được giữ dưới lớp cut-out." if hold_background else "")
            ),
            layers=[dict(
                layerId=slot.slot_id,
                kind=kind,
                layerOrder=0,
                slotId=slot.slot_id,
                fitMode="cover",
                **({"audioVolume": 0.0} if kind == "video" else {}),
            )],
        ))

    def add_cutout_event(index: int, start_ticks: int, duration_ms: int, layer_order: int):
        slot = base.slots[index]
        _, kind = resolved[slot.slot_id]
        if kind != "image":
            # Video in a portrait slot: show it full-frame on top for its window
            # (cut-out needs a still image); the background keeps running below.
            events.append(dict(
                eventId=f"{slot.slot_id}-video-overlay",
                timelineStartTicks=start_ticks,
                durationTicks=duration_ms * 90,
                eventClassification="OVERLAY_APPEAR",
                sourceEvidence="Video ở vị trí chân dung được phát toàn khung phía trên cảnh nền.",
                layers=[dict(
                    layerId=f"{slot.slot_id}-video",
                    kind="video",
                    layerOrder=layer_order,
                    slotId=slot.slot_id,
                    fitMode="cover",
                    audioVolume=0.0,
                )],
            ))
            return
        events.append(dict(
            eventId=f"{slot.slot_id}-cutout-overlay",
            timelineStartTicks=start_ticks,
            durationTicks=duration_ms * 90,
            eventClassification="OVERLAY_APPEAR",
            sourceEvidence="Ảnh chân dung được tách nền và chồng lên cảnh nền theo bố cục quan sát được.",
            layers=[dict(
                layerId=f"{slot.slot_id}-cutout",
                kind="image",
                layerOrder=layer_order,
                slotId=slot.slot_id,
                fitMode="cover",
                positionX=0.0,
                positionY=0.0,
                scale=1.0,
                removeBackground=True,
            )],
        ))

    index = 0
    while index < len(base.slots):
        slot_start = timeline_start
        frame_starts[index] = slot_start

        # Cards 13/14 and 15/16 overlap in the sample: the portrait enters as a
        # cut-out while the preceding video continues underneath it.
        if index == 12:
            add_frame_event(index, slot_start, 1_400, hold_background=True)
            frame_starts[index + 1] = slot_start + 500 * 90
            add_cutout_event(index + 1, frame_starts[index + 1], 900, 1)
            timeline_start += 1_400 * 90
            index += 2
            continue
        if index == 14:
            add_frame_event(index, slot_start, 1_000, hold_background=True)
            frame_starts[index + 1] = slot_start + 100 * 90
            add_cutout_event(index + 1, frame_starts[index + 1], 900, 1)
            timeline_start += 1_000 * 90
            index += 2
            continue

        duration_ms = int(durations[index])
        add_frame_event(index, slot_start, duration_ms)
        timeline_start += duration_ms * 90
        index += 1

    # Subject bridge (seen on every cut of the reference): during the last
    # ~0.1 s of each frame, the NEXT media's subject is cut out and shown in its
    # own position over the current scene; then the next frame appears in full.
    pair_overlays = {13, 15}          # slots 14 and 16 already overlap their backgrounds
    for index in range(1, len(base.slots)):
        if index in pair_overlays or index - 1 in pair_overlays:
            continue
        slot = base.slots[index]
        if resolved[slot.slot_id][1] != "image":
            continue                  # cut-out needs a still image
        previous_ms = int(durations[index - 1]) if index - 1 != 12 else 1_400
        bridge_ms = min(BRIDGE_MS, previous_ms // 2)
        start = frame_starts[index] - bridge_ms * 90
        if start < frame_starts[index - 1]:
            continue
        add_cutout_event(index, start, bridge_ms, 2)

    caption = next((
        layer for event in base.events for layer in event.layers
        if layer.kind == "text" and layer.text is not None
    ), None)
    if caption is not None:
        caption = caption.model_copy(update={"layer_order": 10})
        events.append(dict(
            eventId="caption-where-we-fell-in-love",
            timelineStartTicks=0,
            durationTicks=timeline_start,
            eventClassification="OVERLAY_APPEAR",
            sourceEvidence="Dòng chữ ở giữa khung hình được giữ xuyên suốt clip mẫu.",
            layers=[caption.model_dump(mode="json", by_alias=True)],
        ))

    payload = base.model_dump(mode="json", by_alias=True)
    payload.update({
        "durationTicks": timeline_start,
        "events": events,
        "metadata": {
            **base.metadata,
            "selectionPlan": {
                "selectedMediaCount": len(base.slots),
                "mediaDurationsMs": list(durations),
                "timelineDurationMs": timeline_start // 90,
                "sequence": "ordered-40-frame-sequence",
            },
        },
    })
    return TemplateDefinition.model_validate(payload)


def prepare_story_payload(story, request: SelectionPayloadRequest, media_lookup) -> dict:
    """Validate bindings for a photo story template: one image per photo slot."""
    version = str(story.data.get("version", "1.0.0"))
    if request.template_definition_version != version:
        raise ValueError("Template definition unavailable or version changed.")
    slot_ids = story_slot_ids(story)
    if set(request.bindings) != set(slot_ids):
        raise ValueError(f"Mẫu {story.name} cần đúng {len(slot_ids)} ảnh, mỗi ô một ảnh.")
    for slot_id in slot_ids:
        media = media_lookup(request.bindings[slot_id])
        if media.kind != "image":
            raise ValueError(f"Ô {slot_id} chỉ nhận ảnh.")
    return dict(templateId=story.template_id, templateDefinitionVersion=version,
                outputKind="image-set", bindings=request.bindings,
                photoOrder=[request.bindings[slot_id] for slot_id in slot_ids])
