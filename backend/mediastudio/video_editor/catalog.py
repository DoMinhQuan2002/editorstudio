from __future__ import annotations

from dataclasses import dataclass
from math import gcd
from pathlib import Path

from mediastudio.video_editor.models import TextLayer, VideoClip, new_id
from mediastudio.video_editor.project_v2 import TimelineClipV2, TimelineEngineV2, VideoProjectV2


@dataclass(frozen=True, slots=True)
class TemplateScene:
    name: str
    duration_ms: int


@dataclass(frozen=True, slots=True)
class TemplateMediaSlotRequirement:
    slot_id: str
    allowed_media_kinds: tuple[str, ...]
    required: bool = True
    reuse_policy: str = "allow"
    missing_slot_policy: str = "error"

    def public_dict(self) -> dict[str, object]:
        return {
            "slotId": self.slot_id,
            "allowedMediaKinds": list(self.allowed_media_kinds),
            "required": self.required,
            "reusePolicy": self.reuse_policy,
            "missingSlotPolicy": self.missing_slot_policy,
        }


@dataclass(frozen=True, slots=True)
class VideoTemplate:
    template_id: str
    name: str
    description: str
    category: str
    duration_ms: int
    width: int
    height: int
    scenes: tuple[TemplateScene, ...]
    text: str | None = None
    availability_status: str = "REFERENCE_ONLY"
    template_definition_version: str | None = None
    poster_source: str | None = None
    demo_source: str | None = None
    render_capabilities: tuple[str, ...] = ()
    media_slot_requirements: tuple[TemplateMediaSlotRequirement, ...] = ()
    # "video" renders through the composition pipeline; "image-set" is a photo
    # story template (story_templates.py) that outputs one image per page.
    output_kind: str = "video"

    def public_dict(self) -> dict[str, object]:
        from mediastudio.video_editor.media_selection import (
            get_template_definition,
            slot_requirements,
            template_definition_version,
        )
        verified_slots = slot_requirements(self.template_id)
        definition = get_template_definition(self.template_id)
        width = definition.width if definition is not None else self.width
        height = definition.height if definition is not None else self.height
        duration_ms = definition.duration_ticks // 90 if definition is not None else self.duration_ms
        selection_policy = definition.metadata.get("selectionPolicy", {}) if definition is not None else {}
        dynamic_minimum = 1 if selection_policy.get("mode") == "background-batches-of-nine" else None
        text_layers = []
        if definition is not None:
            for event in definition.events:
                for layer in event.layers:
                    if layer.kind == "text" and layer.text is not None:
                        text_layers.append({
                            "text": layer.text,
                            "startMs": event.timeline_start_ticks // 90,
                            "durationMs": event.duration_ticks // 90,
                        })
        elif self.text:
            text_layers = [{"text": self.text, "startMs": 0,
                            "durationMs": min(6000, self.duration_ms)}]
        return {
            "templateId": self.template_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "durationMs": duration_ms,
            "durationSeconds": round(duration_ms / 1000, 2),
            "width": width,
            "height": height,
            "aspectRatio": f"{width // gcd(width, height)}:{height // gcd(width, height)}",
            "sceneCount": len(self.scenes),
            "requiredMediaSlots": dynamic_minimum if dynamic_minimum is not None else (
                len(verified_slots) if verified_slots else sum(1 for slot in self.media_slot_requirements if slot.required)
            ),
            "previewAvailable": self.demo_source is not None,
            "posterPath": self.poster_source,
            "previewSource": self.demo_source,
            "availabilityStatus": "PILOT_RENDERABLE" if verified_slots else self.availability_status,
            "templateDefinitionVersion": (template_definition_version(self.template_id)
                                            if verified_slots else self.template_definition_version),
            "posterSource": self.poster_source,
            "demoSource": self.demo_source,
            "mediaSlotRequirements": verified_slots or [slot.public_dict() for slot in self.media_slot_requirements],
            "renderCapabilities": (list(definition.supported_capabilities)
                                   if definition is not None else list(self.render_capabilities)),
            "scenes": [{"name": scene.name, "durationMs": scene.duration_ms} for scene in self.scenes],
            "textLayers": text_layers,
            "outputKind": self.output_kind,
        }

    def create_project(self, title: str | None = None) -> VideoProjectV2:
        from mediastudio.video_editor.media_selection import get_template_definition
        definition = get_template_definition(self.template_id)
        project = VideoProjectV2(
            schema_version=2,
            project_id=new_id(),
            template_id=self.template_id,
            title=(title or self.name)[:160],
            width=definition.width if definition is not None else self.width,
            height=definition.height if definition is not None else self.height,
            frame_rate_numerator=30,
            frame_rate_denominator=1,
            tracks=[],
            template_metadata={"templateId": self.template_id},
        )
        engine = TimelineEngineV2(project)
        visual_track = engine.create_track("visual", "Video 1")
        start_ticks = 0
        for index, scene in enumerate(self.scenes):
            clip = VideoClip(name=scene.name, duration_ms=scene.duration_ms)
            engine.add_clip(visual_track.track_id, TimelineClipV2(
                clip_id=clip.clip_id,
                track_id=visual_track.track_id,
                clip_kind="visual",
                timeline_start_ticks=start_ticks,
                source_start_ticks=clip.source_start_ms * 90,
                duration_ticks=clip.duration_ms * 90,
                media_id=None,
                properties=clip.model_dump(mode="json", by_alias=True),
                template_metadata={"templateId": self.template_id, "sceneIndex": index,
                                   "sceneName": scene.name, "placeholder": True},
            ))
            start_ticks += scene.duration_ms * 90
        if self.text:
            text_track = engine.create_track("text", "Văn bản 1")
            layer = TextLayer(text=self.text, duration_ms=min(6000, self.duration_ms), y=0.28,
                              font_size=76, color="#FFFFFF")
            engine.add_clip(text_track.track_id, TimelineClipV2(
                clip_id=layer.layer_id, track_id=text_track.track_id, clip_kind="text",
                timeline_start_ticks=layer.start_ms * 90, duration_ticks=layer.duration_ms * 90,
                properties=layer.model_dump(mode="json", by_alias=True),
                template_metadata={"legacyRenderOrder": 0, "templateId": self.template_id},
            ))
        return engine.project


_PORTRAIT = (1080, 1920)
# Demo videos and posters shipped with the backend. The desktop app plays them
# from a local path, so they are given as absolute paths to the package files.
_PREVIEW_DIRECTORY = Path(__file__).resolve().parent / "definitions" / "assets" / "previews"


def _bundled_preview(name: str) -> str | None:
    path = _PREVIEW_DIRECTORY / name
    return str(path) if path.is_file() else None

TEMPLATES: tuple[VideoTemplate, ...] = (
    # Only templates that really render are listed. The earlier placeholder cards
    # (Denim Story, Travel Reel, Product Intro, Minimal Fashion, Food Story,
    # Collage Memories, Cut Out Pop) had no template definition and were removed.
    VideoTemplate("fall-diary", "Fall Diary", "Chọn 1–36 media theo thứ tự: mỗi nhóm 9 có 1 nền ảnh/video và tối đa 8 ảnh phủ được tách nền, cắt gọn và đặt lớn quanh giữa khung hình. Nền đầu dài 5,2 giây; mỗi nền tiếp theo dài 4 giây. Logo FALL DIARY chỉ hiện trong 1,2 giây đầu.", "Story", 17200,
                  *_PORTRAIT,
                  tuple(TemplateScene(f"Nhóm nền {index + 1}", 5200 if index == 0 else 4000) for index in range(4)),
                  availability_status="PILOT_RENDERABLE",
                  template_definition_version="0.9.0-reference-overlays",
                  # Rendered by this app from the 0.9 definition (2026-10-29).
                  poster_source=_bundled_preview("fall_diary_poster.jpg"),
                  demo_source=_bundled_preview("fall_diary_demo.mp4"),
                  render_capabilities=("full_frame_image", "hard_cut", "multi_layer_collage",
                                       "safe_area_contain_cards", "event_classification_evidence",
                                       "independent_visual_event_timing_90khz", "static_template_image_asset",
                                       "preview_export_shared_renderer", "image_slot_reuse",
                                       "automatic_foreground_cutout", "dynamic_background_batches_of_nine",
                                       "video_backgrounds")),
    VideoTemplate("autumn-love-40", "Autumn Love · 40 khung",
                  "Mẫu dọc 9:16 gồm đúng 40 media theo thứ tự. Phần lớn khung dài 0,2 giây; một số cảnh kéo dài hơn, có ảnh chân dung tách nền chồng lên video và dòng chữ ‘where we fell in love’.",
                  "Story", 11000, *_PORTRAIT,
                  (
                      TemplateScene("Mở đầu · nhịp cắt nhanh", 3700),
                      TemplateScene("Cảnh nền và chân dung phủ", 2400),
                      TemplateScene("Coffee & portrait collage", 1600),
                      TemplateScene("Phần kết mùa thu", 3300),
                  ),
                  availability_status="PILOT_RENDERABLE",
                  template_definition_version="1.0.0-reference-sequence",
                  poster_source=_bundled_preview("autumn_love_40_poster.jpg"),
                  render_capabilities=("full_frame_image", "hard_cut", "multi_layer_collage",
                                       "automatic_foreground_cutout", "preview_export_shared_renderer",
                                       "video_backgrounds")),
    VideoTemplate("november-dump", "November Dump",
                  "Story ảnh 7 trang từ đúng 13 ảnh, chọn THEO THỨ TỰ: 4 ảnh bìa (trái trên, phải trên, "
                  "trái dưới, phải dưới) có chữ November, rồi 2 ảnh (trên/dưới), 1 ảnh, 2 ảnh, 1 ảnh, 2 ảnh, 1 ảnh. "
                  "Mỗi trang có sẵn chú thích tiếng Anh. Xuất ra 7 ảnh 1080×1920.",
                  "Story", 0, *_PORTRAIT,
                  tuple(TemplateScene(f"Trang {index + 1}", 0) for index in range(7)),
                  availability_status="PILOT_RENDERABLE",
                  template_definition_version="1.0.0",
                  render_capabilities=("image_set_output", "photo_story_pages", "fixed_captions",
                                       "title_sticker"),
                  output_kind="image-set"),
)

_BY_ID = {template.template_id: template for template in TEMPLATES}
if len(_BY_ID) != len(TEMPLATES):
    raise RuntimeError("Video template catalog contains duplicate template IDs.")


def list_templates() -> list[dict[str, object]]:
    return [template.public_dict() for template in TEMPLATES]


def get_template(template_id: str) -> VideoTemplate | None:
    return _BY_ID.get(template_id)
