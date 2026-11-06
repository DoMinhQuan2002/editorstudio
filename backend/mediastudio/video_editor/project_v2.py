from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, model_validator

from mediastudio.video_editor.models import AudioTrack, StrictModel, TextLayer, VideoClip, VideoProject


TIMEBASE = 90_000
MAX_TIME_TICKS = 30 * 60 * TIMEBASE
INT64_MAX = (1 << 63) - 1
TRACK_KINDS = ("visual", "text", "audio")


def _stable_id(project_id: str, role: str, lane: int = 0) -> str:
    return uuid5(NAMESPACE_URL, f"mediastudio:{project_id}:track:{role}:{lane}").hex


class TrackStateV2(StrictModel):
    visible: bool = True
    locked: bool = False
    muted: bool = False
    solo: bool = False


class TimelineClipV2(StrictModel):
    clip_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    track_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    clip_kind: Literal["visual", "image", "video", "text", "audio"]
    timeline_start_ticks: int = Field(ge=0, le=MAX_TIME_TICKS)
    source_start_ticks: int = Field(default=0, ge=0, le=INT64_MAX)
    duration_ticks: int = Field(gt=0, le=MAX_TIME_TICKS)
    media_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    properties: dict[str, Any] = Field(default_factory=dict)
    template_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_end(self) -> "TimelineClipV2":
        if self.timeline_start_ticks + self.duration_ticks > MAX_TIME_TICKS:
            raise ValueError("Clip vượt giới hạn timeline 30 phút.")
        if self.source_start_ticks + self.duration_ticks > INT64_MAX:
            raise ValueError("Source range vượt giới hạn số nguyên 64-bit.")
        return self

    @property
    def end_ticks(self) -> int:
        return self.timeline_start_ticks + self.duration_ticks


class TimelineTrackV2(StrictModel):
    track_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    kind: Literal["visual", "text", "audio"]
    layer_order: int = Field(ge=0, le=10_000)
    display_name: str = Field(min_length=1, max_length=120)
    state: TrackStateV2 = Field(default_factory=TrackStateV2)
    clips: list[TimelineClipV2] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def clip_ownership(self) -> "TimelineTrackV2":
        if any(clip.track_id != self.track_id for clip in self.clips):
            raise ValueError("Track chứa clip có trackId không khớp.")
        return self


class VideoProjectV2(StrictModel):
    schema_version: Literal[2]
    project_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    template_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=160)
    width: int = Field(default=1080, ge=64, le=3840, multiple_of=2)
    height: int = Field(default=1920, ge=64, le=3840, multiple_of=2)
    frame_rate_numerator: int = Field(default=30, ge=1, le=240_000)
    frame_rate_denominator: int = Field(default=1, ge=1, le=100_000)
    timebase: int = Field(default=TIMEBASE, ge=1)
    tracks: list[TimelineTrackV2] = Field(max_length=100)
    template_metadata: dict[str, Any] = Field(default_factory=dict)
    extensions: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    revision: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_project(self) -> "VideoProjectV2":
        if self.timebase != TIMEBASE:
            raise ValueError(f"Timebase không được hỗ trợ: {self.timebase}.")
        if self.timebase * self.frame_rate_denominator % self.frame_rate_numerator:
            raise ValueError("Frame rate không biểu diễn chính xác được bằng timebase của project.")
        track_ids = [track.track_id for track in self.tracks]
        if len(track_ids) != len(set(track_ids)):
            raise ValueError("Track ID bị trùng.")
        clip_ids = [clip.clip_id for track in self.tracks for clip in track.clips]
        if len(clip_ids) != len(set(clip_ids)):
            raise ValueError("Clip ID bị trùng trong project.")
        if len({track.layer_order for track in self.tracks}) != len(self.tracks):
            raise ValueError("Layer order phải duy nhất trong project.")
        return self

    @property
    def fps(self) -> int:
        return round(self.frame_rate_numerator / self.frame_rate_denominator)

    @property
    def duration_ticks(self) -> int:
        return max((clip.end_ticks for track in self.tracks for clip in track.clips), default=0)

    @property
    def duration_ms(self) -> int:
        return (self.duration_ticks + 89) // 90

    @classmethod
    def blank(cls, title: str, width: int = 1080, height: int = 1920,
              fps_num: int = 30, fps_den: int = 1) -> "VideoProjectV2":
        return cls(schema_version=2,
                   project_id=uuid5(NAMESPACE_URL, f"mediastudio:blank:{title}:{datetime.now(timezone.utc).isoformat()}").hex,
                   template_id="free-editor", title=title[:160], width=width, height=height,
                   frame_rate_numerator=fps_num, frame_rate_denominator=fps_den, tracks=[])


def migrate_v1_project(project: VideoProject) -> VideoProjectV2:
    """Build V2 in memory; the store owns backup and atomic persistence."""
    tracks: list[TimelineTrackV2] = []
    visual_id = _stable_id(project.project_id, "visual")
    visual_clips: list[TimelineClipV2] = []
    start = 0
    for clip in project.clips:
        visual_clips.append(TimelineClipV2(
            clip_id=clip.clip_id, track_id=visual_id, clip_kind="visual",
            timeline_start_ticks=start * 90, source_start_ticks=clip.source_start_ms * 90,
            duration_ticks=clip.duration_ms * 90, media_id=clip.media_id,
            properties=clip.model_dump(mode="json", by_alias=True),
            template_metadata={"placeholder": clip.media_id is None},
        ))
        start += clip.duration_ms
    if visual_clips or project.template_id == "free-editor":
        tracks.append(TimelineTrackV2(track_id=visual_id, kind="visual", layer_order=0,
                                      display_name="Video 1", clips=visual_clips))

    if project.text_layers:
        text_id = _stable_id(project.project_id, "text")
        text_clips = [TimelineClipV2(
            clip_id=layer.layer_id, track_id=text_id, clip_kind="text",
            timeline_start_ticks=layer.start_ms * 90, source_start_ticks=0,
            duration_ticks=layer.duration_ms * 90,
            properties=layer.model_dump(mode="json", by_alias=True),
            template_metadata={"legacyRenderOrder": index},
        ) for index, layer in enumerate(project.text_layers)]
        tracks.append(TimelineTrackV2(track_id=text_id, kind="text", layer_order=1,
                                      display_name="Văn bản 1", clips=text_clips))

    # Preserve the legacy first-fit lane assignment once, then persist lane IDs.
    lanes: list[tuple[str, int]] = []
    for item in sorted(project.audio_tracks, key=lambda audio: (audio.timeline_start_ms, audio.track_id)):
        lane = next((index for index, (_, end_ms) in enumerate(lanes) if end_ms <= item.timeline_start_ms), None)
        if lane is None:
            lane = len(lanes)
            lanes.append((_stable_id(project.project_id, "audio", lane), 0))
        track_id, _ = lanes[lane]
        lanes[lane] = (track_id, item.timeline_start_ms + item.duration_ms)
        track = next((candidate for candidate in tracks if candidate.track_id == track_id), None)
        if track is None:
            track = TimelineTrackV2(track_id=track_id, kind="audio", layer_order=2 + lane,
                                    display_name=f"Âm thanh {lane + 1}")
            tracks.append(track)
        track.clips.append(TimelineClipV2(
            clip_id=item.track_id, track_id=track_id, clip_kind="audio",
            timeline_start_ticks=item.timeline_start_ms * 90,
            source_start_ticks=item.source_start_ms * 90, duration_ticks=item.duration_ms * 90,
            media_id=item.media_id, properties=item.model_dump(mode="json", by_alias=True),
        ))

    # Normalize stable layer ordering while preserving visual/text order.
    for order, track in enumerate(sorted(tracks, key=lambda candidate: candidate.layer_order)):
        track.layer_order = order
    return VideoProjectV2(
        schema_version=2, project_id=project.project_id, template_id=project.template_id, title=project.title,
        width=project.width, height=project.height, frame_rate_numerator=project.fps,
        frame_rate_denominator=1, tracks=tracks, created_at=project.created_at,
        updated_at=project.updated_at, revision=project.revision,
        template_metadata={"templateId": project.template_id},
    )


def to_legacy_project(project: VideoProjectV2) -> VideoProject:
    """Explicit compatibility adapter for the current single-lane renderer."""
    def legacy_properties(properties: dict[str, Any], *, visual: bool = False) -> dict[str, Any]:
        result = deepcopy(properties)
        if visual:
            # The legacy VideoClip model has no keyframe semantics. The
            # canonical V2 track remains lossless; this compatibility view is
            # deliberately static and exists for old UI/API consumers only.
            for key in ("keyframes", "removeBackground", "trimTransparentBounds", "subjectCentered",
                        "userScale", "userOffsetX", "userOffsetY", "entranceEffect",
                        "templateAssetReference", "templateAssetId",
                        "templateAssetDefinitionVersion"):
                result.pop(key, None)
        else:
            # Text graphics are rendered by the V2 composition renderer. The
            # older TextLayer contract has only the base font/color/position.
            for key in ("textBox", "textBoxColor", "textBoxOpacity", "textBoxBorderWidth",
                        "textBoxBorderColor", "shadowColor", "shadowX", "shadowY", "keyframes"):
                result.pop(key, None)
        return result

    visual = sorted((clip for track in project.tracks if track.kind == "visual" for clip in track.clips),
                    key=lambda clip: (clip.timeline_start_ticks, clip.clip_id))
    text = [clip for track in sorted((track for track in project.tracks if track.kind == "text"),
                                     key=lambda item: item.layer_order)
            for index, clip in sorted(enumerate(track.clips), key=lambda pair: (
                pair[1].template_metadata.get("legacyRenderOrder", pair[0]), pair[0]))]
    audio = sorted((clip for track in project.tracks if track.kind == "audio" for clip in track.clips),
                   key=lambda clip: (clip.timeline_start_ticks, clip.clip_id))
    return VideoProject(
        project_id=project.project_id, template_id=project.template_id, title=project.title,
        width=project.width, height=project.height, fps=project.fps,
        clips=[VideoClip.model_validate(legacy_properties(clip.properties, visual=True) | {
            "clipId": clip.clip_id, "mediaId": clip.media_id,
            "sourceStartMs": clip.source_start_ticks // 90,
            "durationMs": clip.duration_ticks // 90,
        }) for clip in visual],
        text_layers=[TextLayer.model_validate(legacy_properties(clip.properties) | {
            "layerId": clip.clip_id, "startMs": clip.timeline_start_ticks // 90,
            "durationMs": clip.duration_ticks // 90,
        }) for clip in text],
        audio_tracks=[AudioTrack.model_validate(deepcopy(clip.properties) | {
            "trackId": clip.clip_id, "mediaId": clip.media_id,
            "timelineStartMs": clip.timeline_start_ticks // 90,
            "sourceStartMs": clip.source_start_ticks // 90,
            "durationMs": clip.duration_ticks // 90,
        }) for clip in audio],
        created_at=project.created_at, updated_at=project.updated_at, revision=project.revision,
    )


def project_api_payload(project: VideoProjectV2) -> dict[str, Any]:
    """Expose legacy editor collections as projections while tracks remain persisted canonically."""
    payload = project.model_dump(mode="json", by_alias=True)
    legacy = to_legacy_project(project)
    clips_by_id = {clip.clip_id: clip for track in project.tracks for clip in track.clips}
    payload["clips"] = []
    for item in legacy.clips:
        canonical = clips_by_id[item.clip_id]
        row = item.model_dump(mode="json", by_alias=True)
        row["trackId"] = canonical.track_id
        row["timelineStartTicks"] = canonical.timeline_start_ticks
        row["sourceStartTicks"] = canonical.source_start_ticks
        row["durationTicks"] = canonical.duration_ticks
        row["clipKind"] = canonical.clip_kind
        payload["clips"].append(row)
    payload["textLayers"] = []
    for item in legacy.text_layers:
        canonical = clips_by_id[item.layer_id]
        row = item.model_dump(mode="json", by_alias=True)
        row["trackId"] = canonical.track_id
        row["timelineStartTicks"] = canonical.timeline_start_ticks
        row["durationTicks"] = canonical.duration_ticks
        payload["textLayers"].append(row)
    payload["audioTracks"] = []
    for item in legacy.audio_tracks:
        canonical = clips_by_id[item.track_id]
        row = item.model_dump(mode="json", by_alias=True)
        row["clipId"] = canonical.clip_id
        row["laneTrackId"] = canonical.track_id
        row["timelineStartTicks"] = canonical.timeline_start_ticks
        row["sourceStartTicks"] = canonical.source_start_ticks
        row["durationTicks"] = canonical.duration_ticks
        payload["audioTracks"].append(row)
    payload["fps"] = project.fps
    return payload


def apply_api_compatibility_projection(payload: dict[str, Any]) -> VideoProjectV2:
    """Reconcile WPF compatibility views against the canonical V2 timeline.

    The WPF arrays are projections for older inspectors, not a place to infer placement.
    Every clip must already exist in ``tracks`` and retain an explicit owner and tick range.
    This prevents a stale or partial projection from erasing canonical clips and metadata.
    """
    if payload.get("schemaVersion", payload.get("schema_version")) != 2 or "tracks" not in payload:
        raise ValueError("Từ chối ghi payload không có schemaVersion 2 và persistent tracks.")
    core = {key: value for key, value in payload.items()
            if key not in {"clips", "textLayers", "audioTracks", "fps"}}
    project = VideoProjectV2.model_validate(core)
    supplied_fps = payload.get("fps")
    if isinstance(supplied_fps, int) and supplied_fps > 0 \
            and supplied_fps != round(project.frame_rate_numerator / project.frame_rate_denominator):
        project.frame_rate_numerator = supplied_fps
        project.frame_rate_denominator = 1
        project = VideoProjectV2.model_validate(project.model_dump())
    # Old project projections must be explicit in a V2 save; silently ignoring them would
    # permit a WPF edit to appear saved while the canonical clips stayed stale.
    if not all(key in payload for key in ("clips", "textLayers", "audioTracks")):
        raise ValueError("Thiếu projection clips/textLayers/audioTracks trong payload Save V2.")

    tracks = {track.track_id: track for track in project.tracks}
    clips = {clip.clip_id: (track, clip) for track in project.tracks for clip in track.clips}
    expected = {
        "visual": {clip_id for clip_id, (track, _) in clips.items() if track.kind == "visual"},
        "text": {clip_id for clip_id, (track, _) in clips.items() if track.kind == "text"},
        "audio": {clip_id for clip_id, (track, _) in clips.items() if track.kind == "audio"},
    }
    seen: dict[str, set[str]] = {kind: set() for kind in expected}

    def reconcile(kind: Literal["visual", "text", "audio"], clip_id: str,
                  track_id: str, start_ticks: Any, source_ticks: Any,
                  duration_ticks: Any, media_id: str | None,
                  properties: dict[str, Any], clip_kind: str,
                  template_metadata: dict[str, Any] | None = None) -> None:
        if not clip_id or clip_id in seen[kind]:
            raise ValueError("Projection WPF chứa Clip ID rỗng hoặc trùng.")
        seen[kind].add(clip_id)
        found = clips.get(clip_id)
        if found is None:
            raise ValueError(f"Projection WPF có clip {clip_id} nhưng canonical V2 không có entity này.")
        owner, canonical = found
        if track_id not in tracks or tracks[track_id].kind != kind:
            raise ValueError("Projection WPF tham chiếu Track ID không tồn tại hoặc sai loại.")
        if canonical.track_id != track_id or owner.track_id != track_id:
            raise ValueError(f"Track ID của clip {clip_id} không khớp canonical V2.")
        if canonical.clip_kind != clip_kind:
            raise ValueError(f"Loại clip {clip_id} không khớp canonical V2.")
        if start_ticks is None or duration_ticks is None or (kind != "text" and source_ticks is None):
            raise ValueError(f"Projection WPF thiếu timestamp ticks bắt buộc cho clip {clip_id}.")
        canonical.timeline_start_ticks = int(start_ticks)
        canonical.duration_ticks = int(duration_ticks)
        if source_ticks is not None:
            canonical.source_start_ticks = int(source_ticks)
        canonical.media_id = media_id
        merged = deepcopy(canonical.properties)
        merged.update(properties)
        canonical.properties = merged
        if template_metadata is not None:
            canonical.template_metadata = deepcopy(template_metadata)

    for raw in payload["clips"]:
        row = dict(raw)
        track_id = row.pop("trackId", None)
        start_ticks = row.pop("timelineStartTicks", None)
        source_ticks = row.pop("sourceStartTicks", None)
        duration_ticks = row.pop("durationTicks", None)
        clip_kind = row.pop("clipKind", "visual")
        item = VideoClip.model_validate(row)
        found = clips.get(item.clip_id)
        metadata = found[1].template_metadata if found is not None else None
        reconcile("visual", item.clip_id, track_id, start_ticks, source_ticks,
                  duration_ticks, item.media_id, item.model_dump(mode="json", by_alias=True),
                  clip_kind, metadata)

    for raw in payload["textLayers"]:
        row = dict(raw)
        track_id = row.pop("trackId", None)
        start_ticks = row.pop("timelineStartTicks", None)
        duration_ticks = row.pop("durationTicks", None)
        item = TextLayer.model_validate(row)
        found = clips.get(item.layer_id)
        metadata = found[1].template_metadata if found is not None else None
        reconcile("text", item.layer_id, track_id, start_ticks, None, duration_ticks,
                  None, item.model_dump(mode="json", by_alias=True), "text", metadata)

    for raw in payload["audioTracks"]:
        row = dict(raw)
        clip_id = row.pop("clipId", None)
        lane_id = row.pop("laneTrackId", None)
        start_ticks = row.pop("timelineStartTicks", None)
        source_ticks = row.pop("sourceStartTicks", None)
        duration_ticks = row.pop("durationTicks", None)
        row.pop("trackId", None)
        item = AudioTrack.model_validate(row)
        reconcile("audio", clip_id or "", lane_id, start_ticks, source_ticks,
                  duration_ticks, item.media_id, item.model_dump(mode="json", by_alias=True), "audio")

    for kind, expected_ids in expected.items():
        if seen[kind] != expected_ids:
            missing = sorted(expected_ids - seen[kind])
            extra = sorted(seen[kind] - expected_ids)
            raise ValueError(f"Projection WPF {kind} không đầy đủ; thiếu={missing}, thừa={extra}.")
    return VideoProjectV2.model_validate(project.model_dump())


def render_capability(project: VideoProjectV2) -> tuple[bool, str | None]:
    populated_tracks = [track for track in project.tracks if track.clips]
    if any(not track.state.visible or track.state.muted or track.state.solo for track in populated_tracks):
        return False, "Renderer hiện tại chưa áp dụng đầy đủ trạng thái visible/muted/solo của track."
    visual_tracks = [track for track in populated_tracks if track.kind == "visual"]
    if len(visual_tracks) > 1:
        return False, "Multi-track visual compositing chưa được hỗ trợ; project được giữ nguyên."
    if sum(track.kind == "text" for track in populated_tracks) > 1:
        return False, "Nhiều text track chưa có quy tắc compositing đã xác minh; project được giữ nguyên."
    populated_audio_tracks = [track for track in populated_tracks if track.kind == "audio"]
    if len(populated_audio_tracks) > 1:
        return False, "Trộn nhiều audio track chưa được xác minh; project được giữ nguyên."
    if populated_audio_tracks:
        audio_clips = sorted(populated_audio_tracks[0].clips,
                             key=lambda clip: (clip.timeline_start_ticks, clip.clip_id))
        if any(current.timeline_start_ticks < previous.end_ticks
               for previous, current in zip(audio_clips, audio_clips[1:])):
            return False, "Audio overlap trong cùng track chưa được xác minh; project được giữ nguyên."
    text_tracks = [track for track in populated_tracks if track.kind == "text"]
    if visual_tracks and text_tracks and visual_tracks[0].layer_order > text_tracks[0].layer_order:
        return False, "Thứ tự lớp này chưa được renderer tuyến tính hỗ trợ; project được giữ nguyên."
    clips = sorted((clip for track in visual_tracks for clip in track.clips),
                   key=lambda clip: (clip.timeline_start_ticks, clip.clip_id))
    cursor = 0
    for clip in clips:
        if clip.timeline_start_ticks != cursor:
            return False, "Renderer hiện tại chỉ hỗ trợ visual timeline tuyến tính, không gap/overlap."
        cursor = clip.end_ticks
    if any(value % 90 for track in project.tracks for clip in track.clips
           for value in (clip.timeline_start_ticks, clip.source_start_ticks, clip.duration_ticks)):
        return False, "Renderer hiện tại chỉ nhận timestamp millisecond-aligned; dữ liệu ticks chính xác được giữ nguyên."
    if project.frame_rate_numerator % project.frame_rate_denominator:
        return False, "Renderer hiện tại chưa xác minh được frame rate phân số của Project V2."
    return True, None


class TimelineEditError(ValueError):
    pass


class TimelineEngineV2:
    """Small domain engine: operations retain IDs; callers can persist snapshots."""

    def __init__(self, project: VideoProjectV2) -> None:
        self.project = VideoProjectV2.model_validate(project.model_dump())
        self._undo: list[dict[str, Any]] = []
        self._redo: list[dict[str, Any]] = []

    def _commit(self) -> None:
        self._undo.append(self.project.model_dump(mode="json", by_alias=True))
        self._redo.clear()

    def create_track(self, kind: Literal["visual", "text", "audio"], display_name: str) -> TimelineTrackV2:
        self._commit()
        order = max((track.layer_order for track in self.project.tracks), default=-1) + 1
        track = TimelineTrackV2(track_id=uuid5(NAMESPACE_URL,
            f"mediastudio:{self.project.project_id}:track:{kind}:{order}:{len(self.project.tracks)}").hex,
            kind=kind, layer_order=order, display_name=display_name)
        self.project.tracks.append(track)
        return track

    def remove_empty_track(self, track_id: str) -> None:
        track = self._track(track_id)
        if track.clips:
            raise TimelineEditError("Chỉ có thể xóa track rỗng.")
        self._commit()
        self.project.tracks.remove(track)

    def reorder_track(self, track_id: str, layer_order: int) -> None:
        track = self._track(track_id)
        if not 0 <= layer_order < len(self.project.tracks):
            raise TimelineEditError("Layer order nằm ngoài phạm vi.")
        self._commit()
        ordered = sorted(self.project.tracks, key=lambda item: item.layer_order)
        ordered.remove(track)
        ordered.insert(layer_order, track)
        for index, item in enumerate(ordered):
            item.layer_order = index

    def add_clip(self, track_id: str, clip: TimelineClipV2) -> None:
        track = self._track(track_id)
        if clip.track_id != track_id or clip.clip_id in self._clip_ids():
            raise TimelineEditError("Clip ID đã tồn tại hoặc trackId không khớp.")
        status = self.validate_clip_placement(track_id, clip)
        if status["status"] != "VALID":
            raise TimelineEditError(str(status["reason"]))
        self._commit()
        track.clips.append(clip)

    def remove_clip(self, clip_id: str) -> None:
        track, clip = self._find_clip(clip_id)
        self._commit()
        track.clips.remove(clip)

    def move_clip(self, clip_id: str, timeline_start_ticks: int) -> None:
        track, clip = self._find_clip(clip_id)
        updated = clip.model_copy(update={"timeline_start_ticks": timeline_start_ticks})
        # Revalidate end bound before committing the state mutation.
        TimelineClipV2.model_validate(updated.model_dump())
        status = self.validate_clip_placement(track.track_id, updated, exclude_clip_id=clip_id)
        if status["status"] != "VALID":
            raise TimelineEditError(str(status["reason"]))
        self._commit()
        clip.timeline_start_ticks = timeline_start_ticks

    def set_timeline_start(self, clip_id: str, timeline_start_ticks: int) -> None:
        self.move_clip(clip_id, timeline_start_ticks)

    def move_clip_to_track(self, clip_id: str, target_track_id: str,
                           timeline_start_ticks: int | None = None) -> None:
        source_track, clip = self._find_clip(clip_id)
        target = self._track(target_track_id)
        expected_kind = {"visual": {"visual", "image", "video"}, "text": {"text"}, "audio": {"audio"}}
        if clip.clip_kind not in expected_kind[target.kind]:
            raise TimelineEditError("Loại clip không phù hợp với track đích.")
        start = clip.timeline_start_ticks if timeline_start_ticks is None else timeline_start_ticks
        replacement = clip.model_copy(update={"track_id": target.track_id, "timeline_start_ticks": start})
        TimelineClipV2.model_validate(replacement.model_dump())
        status = self.validate_clip_placement(target.track_id, replacement, exclude_clip_id=clip_id)
        if status["status"] != "VALID":
            raise TimelineEditError(str(status["reason"]))
        self._commit()
        source_track.clips.remove(clip)
        target.clips.append(replacement)

    def trim_source(self, clip_id: str, source_start_ticks: int, duration_ticks: int) -> None:
        track, clip = self._find_clip(clip_id)
        candidate = clip.model_copy(update={"source_start_ticks": source_start_ticks,
                                           "duration_ticks": duration_ticks})
        TimelineClipV2.model_validate(candidate.model_dump())
        status = self.validate_clip_placement(track.track_id, candidate, exclude_clip_id=clip_id)
        if status["status"] != "VALID":
            raise TimelineEditError(str(status["reason"]))
        self._commit()
        clip.source_start_ticks = source_start_ticks
        clip.duration_ticks = duration_ticks

    def trim_source_in(self, clip_id: str, source_start_ticks: int, duration_ticks: int) -> None:
        self.trim_source(clip_id, source_start_ticks, duration_ticks)

    def trim_source_out(self, clip_id: str, duration_ticks: int) -> None:
        _, clip = self._find_clip(clip_id)
        self.trim_source(clip_id, clip.source_start_ticks, duration_ticks)

    def split_clip(self, clip_id: str, split_at_ticks: int, second_clip_id: str) -> tuple[TimelineClipV2, TimelineClipV2]:
        track, clip = self._find_clip(clip_id)
        offset = split_at_ticks - clip.timeline_start_ticks
        if not 0 < offset < clip.duration_ticks:
            raise TimelineEditError("Điểm split phải nằm bên trong clip.")
        first = clip.model_copy(update={"duration_ticks": offset})
        second = clip.model_copy(update={"clip_id": second_clip_id,
            "timeline_start_ticks": split_at_ticks,
            "source_start_ticks": clip.source_start_ticks + offset,
            "duration_ticks": clip.duration_ticks - offset})
        TimelineClipV2.model_validate(first.model_dump())
        TimelineClipV2.model_validate(second.model_dump())
        if second_clip_id in self._clip_ids():
            raise TimelineEditError("Clip ID của đoạn mới đã tồn tại.")
        self._commit()
        track.clips.remove(clip)
        track.clips.extend((first, second))
        return first, second

    def update_track_state(self, track_id: str, state: TrackStateV2) -> None:
        track = self._track(track_id)
        self._commit()
        track.state = state

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.project.model_dump(mode="json", by_alias=True))
        self.project = VideoProjectV2.model_validate(self._undo.pop())
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.project.model_dump(mode="json", by_alias=True))
        self.project = VideoProjectV2.model_validate(self._redo.pop())
        return True

    def read_track_state(self, track_id: str) -> TrackStateV2:
        return self._track(track_id).state

    def validate_clip_placement(self, track_id: str, clip: TimelineClipV2,
                                exclude_clip_id: str | None = None) -> dict[str, str | bool]:
        track = self._track(track_id)
        expected_kind = {"visual": {"visual", "image", "video"}, "text": {"text"}, "audio": {"audio"}}
        if clip.track_id != track_id or clip.clip_kind not in expected_kind[track.kind]:
            return {"allowed": False, "status": "INVALID_TRACK_KIND", "reason": "Loại clip không phù hợp với track."}
        for current in track.clips:
            if current.clip_id == exclude_clip_id:
                continue
            if clip.timeline_start_ticks < current.end_ticks and current.timeline_start_ticks < clip.end_ticks:
                return {"allowed": False, "status": "REFERENCE_PENDING",
                        "reason": "Overlap trong cùng track đang chờ xác minh quy tắc tham chiếu; không tự ripple hoặc replace."}
        return {"allowed": True, "status": "VALID", "reason": "Vị trí hợp lệ."}

    def _track(self, track_id: str) -> TimelineTrackV2:
        track = next((item for item in self.project.tracks if item.track_id == track_id), None)
        if track is None:
            raise TimelineEditError("Không tìm thấy track.")
        return track

    def _find_clip(self, clip_id: str) -> tuple[TimelineTrackV2, TimelineClipV2]:
        for track in self.project.tracks:
            for clip in track.clips:
                if clip.clip_id == clip_id:
                    return track, clip
        raise TimelineEditError("Không tìm thấy clip.")

    def _clip_ids(self) -> set[str]:
        return {clip.clip_id for track in self.project.tracks for clip in track.clips}
