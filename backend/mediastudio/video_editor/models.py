from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

import re

from pydantic import BaseModel, ConfigDict, Field


def new_id() -> str:
    return uuid4().hex


def _to_camel(name: str) -> str:
    return re.sub(r"_([a-z])", lambda match: match.group(1).upper(), name)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", alias_generator=_to_camel, populate_by_name=True)


class VideoClip(StrictModel):
    clip_id: str = Field(default_factory=new_id, pattern=r"^[a-f0-9]{32}$")
    name: str = Field(min_length=1, max_length=120)
    media_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    source_start_ms: int = Field(default=0, ge=0, le=86_400_000)
    # Template frames can be as short as one video frame (0.1 s bridges, 0.2 s cuts).
    duration_ms: int = Field(default=3000, ge=30, le=600_000)
    fit_mode: Literal["cover", "contain"] = "cover"
    position_x: float = Field(default=0.0, ge=-2.0, le=2.0)
    position_y: float = Field(default=0.0, ge=-2.0, le=2.0)
    scale: float = Field(default=1.0, ge=0.1, le=5.0)
    rotation: float = Field(default=0.0, ge=-180.0, le=180.0)
    effect: Literal["none", "warm", "mono", "vivid"] = "none"
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    audio_volume: float = Field(default=1.0, ge=0.0, le=2.0)
    transition: Literal["cut", "fade"] = "cut"
    transition_duration_ms: int = Field(default=300, ge=0, le=3000)


class TextLayer(StrictModel):
    layer_id: str = Field(default_factory=new_id, pattern=r"^[a-f0-9]{32}$")
    text: str = Field(min_length=1, max_length=500)
    start_ms: int = Field(default=0, ge=0, le=86_400_000)
    duration_ms: int = Field(default=3000, ge=100, le=1_800_000)
    x: float = Field(default=0.5, ge=0.0, le=1.0)
    y: float = Field(default=0.5, ge=0.0, le=1.0)
    font_size: int = Field(default=52, ge=8, le=300)
    color: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    font_family: str = Field(default="Arial", min_length=1, max_length=80)
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)


class AudioTrack(StrictModel):
    track_id: str = Field(default_factory=new_id, pattern=r"^[a-f0-9]{32}$")
    media_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    timeline_start_ms: int = Field(default=0, ge=0, le=86_400_000)
    source_start_ms: int = Field(default=0, ge=0, le=86_400_000)
    duration_ms: int = Field(ge=100, le=3_600_000)
    volume: float = Field(default=1.0, ge=0.0, le=2.0)
    fade_in_ms: int = Field(default=0, ge=0, le=30_000)
    fade_out_ms: int = Field(default=0, ge=0, le=30_000)


class VideoProject(StrictModel):
    project_id: str = Field(default_factory=new_id, pattern=r"^[a-f0-9]{32}$")
    template_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=160)
    width: int = Field(default=1080, ge=64, le=3840, multiple_of=2)
    height: int = Field(default=1920, ge=64, le=3840, multiple_of=2)
    fps: int = Field(default=30, ge=1, le=60)
    # Empty main video tracks are valid editor states after deleting all clips.
    clips: list[VideoClip] = Field(max_length=300)
    text_layers: list[TextLayer] = Field(default_factory=list, max_length=100)
    audio_tracks: list[AudioTrack] = Field(default_factory=list, max_length=20)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    revision: int = Field(default=1, ge=1)

    @property
    def duration_ms(self) -> int:
        video_duration = sum(clip.duration_ms for clip in self.clips)
        audio_end = max(
            (track.timeline_start_ms + track.duration_ms for track in self.audio_tracks),
            default=0,
        )
        return max(video_duration, audio_end)


class CreateProjectRequest(StrictModel):
    template_id: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, max_length=160)


class CreateBlankProjectRequest(StrictModel):
    title: str = Field(default="Dự án trống", min_length=1, max_length=160)
    width: int = Field(default=1080, ge=64, le=3840, multiple_of=2)
    height: int = Field(default=1920, ge=64, le=3840, multiple_of=2)
    frame_rate_numerator: int = Field(default=30, ge=1, le=240_000)
    frame_rate_denominator: int = Field(default=1, ge=1, le=100_000)


class RenderRequest(StrictModel):
    quality: Literal["draft", "standard", "high"] = "standard"
    video_codec: Literal["h264"] = "h264"


class VideoCreatorExportRequest(StrictModel):
    request_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    draft_revision: int = Field(ge=1)
    template_id: str = Field(min_length=1, max_length=120)
    template_version: str = Field(min_length=1, max_length=80)
    composition_fingerprint: str = Field(min_length=16, max_length=128)
    media_bindings: dict[str, str] = Field(default_factory=dict)
    quality: Literal["standard", "high"] = "standard"
    output_directory: str = Field(min_length=1, max_length=2048)
    file_name: str = Field(min_length=1, max_length=160)
    overwrite: bool = False


class MediaMetadata(StrictModel):
    asset_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    file_name: str
    kind: Literal["image", "video", "audio"]
    content_type: str
    byte_size: int = Field(ge=1)
    duration_ms: int | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    video_codec: str | None = None
    audio_codec: str | None = None
    thumbnail_available: bool = False


class VideoJobSnapshot(StrictModel):
    job_id: str
    project_id: str
    state: Literal["queued", "processing", "succeeded", "failed", "cancelled"]
    progress: int = Field(ge=0, le=100)
    stage: str
    output_file_name: str | None = None
    error: str | None = None

