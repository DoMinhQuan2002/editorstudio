"""Prompt building for Fashion Studio tasks (Qwen-Image-Edit, multi-image input).

Image order matters for Qwen-Image-Edit-2509/2511: prompts refer to inputs as
"image 1", "image 2". Image 1 is always the person (model photo).
"""
from __future__ import annotations

from dataclasses import dataclass

TASKS = ("try_on", "scene", "recolor", "new_view")

SCENE_PRESETS: dict[str, str] = {
    "studio": "a clean professional photo studio with a seamless light grey backdrop and soft key light",
    "street": "a sunny city street with stylish shop fronts, shallow depth of field",
    "cafe": "a cozy modern cafe with warm ambient light and wooden furniture",
    "beach": "a bright tropical beach at golden hour with gentle waves",
    "autumn_park": "an autumn park path covered with orange maple leaves, soft afternoon light",
    "runway": "a fashion runway with dramatic spotlights and a blurred audience",
}

VIEW_PRESETS: dict[str, str] = {
    "full_body": "a full-body front view, standing naturally, head to toe in frame",
    "side": "a three-quarter side view turned to the left",
    "back": "a back view showing the back of the outfit",
    "close_up": "a waist-up close-up that shows fabric texture and details",
}

KEEP = ("Keep the person's face, identity, hairstyle, body shape and skin tone exactly the same. "
        "Photorealistic fashion photography, natural lighting, sharp details, no text, no watermark.")


@dataclass(frozen=True, slots=True)
class FashionRequest:
    task: str
    has_garment: bool = False
    scene_preset: str | None = None
    scene_text: str | None = None
    color: str | None = None
    view_preset: str | None = None
    extra: str | None = None


def build_prompt(request: FashionRequest) -> str:
    extra = f" {request.extra.strip()}" if request.extra and request.extra.strip() else ""
    if request.task == "try_on":
        if not request.has_garment:
            raise ValueError("Thử đồ cần ảnh trang phục.")
        return ("Dress the person in image 1 with the exact garment shown in image 2. "
                "Reproduce the garment's color, pattern, fabric, cut and details faithfully and fit it naturally to "
                "the body with realistic folds. Keep the original pose and background. " + KEEP + extra)
    if request.task == "scene":
        scene = (request.scene_text or "").strip() or SCENE_PRESETS.get(request.scene_preset or "", "")
        if not scene:
            raise ValueError("Hãy chọn hoặc mô tả bối cảnh.")
        return (f"Place the person from image 1 into {scene}. Keep the outfit exactly the same "
                "(color, pattern, fabric and fit) and keep the pose. Match lighting and shadows to the new scene. "
                + KEEP + extra)
    if request.task == "recolor":
        color = (request.color or "").strip()
        if not color:
            raise ValueError("Hãy nhập màu mới cho trang phục.")
        return (f"Change the color of the main outfit worn by the person in image 1 to {color}. "
                "Keep the garment's cut, fabric texture, pattern layout and fit, and keep the background and pose. "
                + KEEP + extra)
    if request.task == "new_view":
        view = VIEW_PRESETS.get(request.view_preset or "", VIEW_PRESETS["full_body"])
        return (f"Show the same person from image 1 wearing the same outfit in {view}. "
                "Keep every detail of the outfit and the same background style. " + KEEP + extra)
    raise ValueError(f"Chức năng không hợp lệ: {request.task}")


NEGATIVE_PROMPT = ("blurry, lowres, deformed hands, extra fingers, distorted face, duplicated person, "
                   "text, watermark, logo, cartoon, oversaturated")
