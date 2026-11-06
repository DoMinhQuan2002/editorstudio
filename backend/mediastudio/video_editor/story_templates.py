"""Photo story templates: a fixed set of still pages built from the user's photos.

Unlike the video templates, a story template outputs images, one per page, for
posting as a multi-image story/carousel. A template is pure data (a JSON file in
``definitions/stories``): the output canvas, where the page sits on it, and for
each page the photo cells, captions and stickers, all in fractions of the page.

``november-dump`` reproduces the reference "october dump" carousel measured
frame by frame from its preview (720 px wide recording):

* page 4:5 (720x900 in the recording -> 1080x1350), centred on a 1080x1920
  canvas with the reference's near-black #110E12 bars above and below
* 7 pages, 13 photos: 2x2 cover, then single / top-bottom pairs alternating,
  every cell an exact half or quarter of the page, photos centre-cropped
* captions: cream, rounded semibold sans, two centred lines with an emoji
* the title sticker replaces "october" at the same height and centre
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

STORY_DEFINITION_DIRECTORY = Path(__file__).resolve().parent / "definitions" / "stories"


class StoryTemplateError(ValueError):
    """Raised for an invalid story definition or unusable input."""


@dataclass(frozen=True, slots=True)
class StoryTemplate:
    template_id: str
    name: str
    root: Path
    data: dict

    @property
    def canvas_size(self) -> tuple[int, int]:
        width, height = self.data["canvas"]["width"], self.data["canvas"]["height"]
        return int(width), int(height)

    @property
    def pages(self) -> list[dict]:
        return self.data["pages"]

    @property
    def photo_count(self) -> int:
        return sum(len(page["cells"]) for page in self.pages)

    def asset(self, reference: str) -> Path:
        path = (self.root / reference).resolve()
        if self.root.resolve() not in path.parents:
            raise StoryTemplateError(f"Asset {reference!r} nằm ngoài thư mục mẫu.")
        if not path.is_file():
            raise StoryTemplateError(f"Thiếu asset {reference!r} của mẫu {self.template_id}.")
        return path


def list_story_templates() -> list[StoryTemplate]:
    if not STORY_DEFINITION_DIRECTORY.is_dir():
        return []
    return [get_story_template(path.parent.name)
            for path in sorted(STORY_DEFINITION_DIRECTORY.glob("*/template.json"))]


@lru_cache(maxsize=16)
def get_story_template(template_id: str) -> StoryTemplate:
    root = STORY_DEFINITION_DIRECTORY / template_id
    path = root / "template.json"
    if not path.is_file():
        raise StoryTemplateError(f"Không có mẫu ảnh {template_id!r}.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("templateId") != template_id:
        raise StoryTemplateError(f"templateId trong {path} không khớp thư mục.")
    template = StoryTemplate(template_id, data.get("name", template_id), root, data)
    _validate(template)
    return template


def _validate(template: StoryTemplate) -> None:
    for index, page in enumerate(template.pages, start=1):
        for cell in page["cells"]:
            x, y, w, h = cell["rect"]
            if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > 1.0001 or y + h > 1.0001:
                raise StoryTemplateError(f"Trang {index} có ô ảnh ngoài trang.")
        for sticker in page.get("stickers", []):
            template.asset(sticker["asset"])
    for font in template.data.get("fonts", {}).values():
        template.asset(font)


# ------------------------------------------------------------------ drawing

def _page_box(template: StoryTemplate) -> tuple[int, int, int, int]:
    page = template.data["page"]
    canvas_w, canvas_h = template.canvas_size
    width = int(round(page["width"]))
    height = int(round(page["height"]))
    left = (canvas_w - width) // 2
    top = (canvas_h - height) // 2
    return left, top, width, height


def _hex(value: str, alpha: int = 255) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha


def _open_photo(path: Path) -> Image.Image:
    stat = path.stat()
    return _open_photo_cached(str(path), stat.st_mtime_ns, stat.st_size).copy()


@lru_cache(maxsize=24)
def _open_photo_cached(path: str, mtime_ns: int, size: int) -> Image.Image:
    del mtime_ns, size  # cache key only
    with Image.open(path) as opened:
        # Cells are at most one page (1080x1350); a 2160 px bound keeps full
        # quality for cropping while avoiding decoding 12 MP photos every time.
        opened.draft("RGB", (2160, 2160))
        image = ImageOps.exif_transpose(opened).convert("RGB")
    image.thumbnail((2160, 2160), Image.Resampling.LANCZOS)
    return image


def _fill_cell(photo: Image.Image, size: tuple[int, int], focus: tuple[float, float]) -> Image.Image:
    """Scale to cover the cell and crop around ``focus`` (fractions of the photo)."""
    return ImageOps.fit(photo, size, method=Image.Resampling.LANCZOS, centering=focus)


@lru_cache(maxsize=32)
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


@lru_cache(maxsize=64)
def _emoji(path: str) -> Image.Image:
    with Image.open(path) as opened:
        return opened.convert("RGBA")


def _draw_caption(page: Image.Image, template: StoryTemplate, caption: dict) -> None:
    style = {**template.data.get("captionStyle", {}), **caption.get("style", {})}
    font = _font(str(template.asset(template.data["fonts"][style.get("font", "caption")])),
                 int(style["fontSize"]))
    line_height = int(style["lineHeight"])
    color = _hex(style.get("color", "#FFFFFF"))
    emoji_scale = float(style.get("emojiScale", 1.0))
    emoji_gap = int(style.get("emojiGap", 8))

    # A line is a list of runs: text, or {"emoji": "<asset>"}.
    rendered_lines: list[Image.Image] = []
    for line in caption["lines"]:
        runs = line if isinstance(line, list) else [line]
        pieces: list[Image.Image] = []
        for run in runs:
            if isinstance(run, str):
                right = int(round(font.getlength(run)))
                piece = Image.new("RGBA", (max(1, right), line_height), (0, 0, 0, 0))
                ImageDraw.Draw(piece).text((0, line_height / 2), run, font=font, fill=color, anchor="lm")
                pieces.append(piece)
            else:
                glyph = _emoji(str(template.asset(run["emoji"])))
                target_h = max(1, int(round(font.size * emoji_scale)))
                target_w = max(1, int(round(glyph.width * target_h / glyph.height)))
                icon = glyph.resize((target_w, target_h), Image.Resampling.LANCZOS)
                piece = Image.new("RGBA", (target_w + emoji_gap, line_height), (0, 0, 0, 0))
                piece.alpha_composite(icon, (emoji_gap, (line_height - target_h) // 2))
                pieces.append(piece)
        width = sum(piece.width for piece in pieces)
        line_image = Image.new("RGBA", (max(1, width), line_height), (0, 0, 0, 0))
        x = 0
        for piece in pieces:
            line_image.alpha_composite(piece, (x, 0))
            x += piece.width
        rendered_lines.append(line_image)

    block_w = max(line.width for line in rendered_lines)
    block_h = line_height * len(rendered_lines)
    block = Image.new("RGBA", (block_w, block_h), (0, 0, 0, 0))
    for index, line in enumerate(rendered_lines):
        block.alpha_composite(line, ((block_w - line.width) // 2, index * line_height))

    centre_x = caption["center"][0] * page.width
    centre_y = caption["center"][1] * page.height
    origin = (int(round(centre_x - block_w / 2)), int(round(centre_y - block_h / 2)))

    shadow = style.get("shadow")
    if shadow:
        alpha = block.getchannel("A").point(lambda v: int(v * float(shadow.get("opacity", 0.35))))
        shade = Image.new("RGBA", block.size, _hex(shadow.get("color", "#000000")))
        shade.putalpha(alpha)
        blur = float(shadow.get("blur", 3))
        pad = int(blur * 3) + 2
        padded = Image.new("RGBA", (block_w + 2 * pad, block_h + 2 * pad), (0, 0, 0, 0))
        padded.alpha_composite(shade, (pad, pad))
        padded = padded.filter(ImageFilter.GaussianBlur(blur))
        page.alpha_composite(padded, (origin[0] - pad + int(shadow.get("x", 0)),
                                      origin[1] - pad + int(shadow.get("y", 1))))
    page.alpha_composite(block, origin)


def _draw_sticker(page: Image.Image, template: StoryTemplate, sticker: dict) -> None:
    with Image.open(template.asset(sticker["asset"])) as opened:
        art = opened.convert("RGBA")
    # Measure the sticker by its visible pixels so transparent margins in the
    # source file do not change its placed size.
    box = art.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if box is not None:
        art = art.crop(box)
    target_h = max(1, int(round(sticker["height"] * page.height)))
    target_w = max(1, int(round(art.width * target_h / art.height)))
    art = art.resize((target_w, target_h), Image.Resampling.LANCZOS)
    centre_x = sticker["center"][0] * page.width
    centre_y = sticker["center"][1] * page.height
    page.alpha_composite(art, (int(round(centre_x - target_w / 2)), int(round(centre_y - target_h / 2))))


def _render_page(template: StoryTemplate, index: int, spec: dict, photos: Sequence[Path | None],
                 captions: list | None = None, placeholder_numbers: Sequence[int] | None = None) -> Image.Image:
    """One page on its full canvas; ``None`` photos become numbered placeholders."""
    canvas_w, canvas_h = template.canvas_size
    left, top, page_w, page_h = _page_box(template)
    page = Image.new("RGBA", (page_w, page_h), (0, 0, 0, 255))
    for cell_index, cell in enumerate(spec["cells"]):
        x, y, w, h = cell["rect"]
        box = (int(round(x * page_w)), int(round(y * page_h)),
               int(round((x + w) * page_w)), int(round((y + h) * page_h)))
        size = (box[2] - box[0], box[3] - box[1])
        photo_path = photos[cell_index] if cell_index < len(photos) else None
        if photo_path is None:
            number = placeholder_numbers[cell_index] if placeholder_numbers else cell_index + 1
            page.paste(_placeholder(size, number), box[:2])
        else:
            photo = _open_photo(Path(photo_path))
            page.paste(_fill_cell(photo, size, tuple(cell.get("focus", (0.5, 0.5)))), box[:2])
    for sticker in spec.get("stickers", []):
        _draw_sticker(page, template, sticker)
    for caption_index, caption in enumerate(spec.get("captions", [])):
        if captions is not None and caption_index < len(captions):
            caption = {**caption, "lines": captions[caption_index]}
        _draw_caption(page, template, caption)
    canvas = Image.new("RGBA", (canvas_w, canvas_h), _hex(template.data["canvas"].get("background", "#000000")))
    canvas.alpha_composite(page, (left, top))
    return canvas.convert("RGB")


def _placeholder(size: tuple[int, int], number: int) -> Image.Image:
    """Empty photo cell: grey with a dashed frame and the selection number it waits for."""
    tile = Image.new("RGBA", size, (58, 56, 66, 255))
    draw = ImageDraw.Draw(tile)
    inset = max(6, min(size) // 40)
    dash = max(10, min(size) // 25)
    color = (150, 146, 170, 255)
    x0, y0, x1, y1 = inset, inset, size[0] - inset - 1, size[1] - inset - 1
    for x in range(x0, x1, dash * 2):
        draw.line([(x, y0), (min(x + dash, x1), y0)], fill=color, width=3)
        draw.line([(x, y1), (min(x + dash, x1), y1)], fill=color, width=3)
    for y in range(y0, y1, dash * 2):
        draw.line([(x0, y), (x0, min(y + dash, y1))], fill=color, width=3)
        draw.line([(x1, y), (x1, min(y + dash, y1))], fill=color, width=3)
    font_size = max(24, min(size) // 4)
    try:
        font = ImageFont.load_default(size=font_size)
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()
    draw.text((size[0] / 2, size[1] / 2), str(number), font=font, fill=(205, 200, 225, 255), anchor="mm")
    return tile


def render_story(template: StoryTemplate, photo_paths: Sequence[Path],
                 captions: dict[int, list] | None = None) -> list[Image.Image]:
    """Render every page; ``photo_paths`` are consumed in page/cell order."""
    if len(photo_paths) != template.photo_count:
        raise StoryTemplateError(
            f"Mẫu {template.name} cần đúng {template.photo_count} ảnh, nhận {len(photo_paths)}.")
    pages: list[Image.Image] = []
    cursor = 0
    for index, spec in enumerate(template.pages, start=1):
        count = len(spec["cells"])
        pages.append(_render_page(template, index, spec, list(photo_paths[cursor:cursor + count]),
                                  (captions or {}).get(index)))
        cursor += count
    return pages


def render_page_preview(template: StoryTemplate, page_index: int, photos_by_order: Sequence[Path | None],
                        width: int = 540) -> Image.Image:
    """Preview one page while photos are still being chosen.

    ``photos_by_order`` lists the photo for every slot in template order, with
    ``None`` for slots not chosen yet; those show as numbered placeholders so
    the user sees which selection number lands where.
    """
    if not 1 <= page_index <= len(template.pages):
        raise StoryTemplateError(f"Mẫu {template.name} không có trang {page_index}.")
    start = sum(len(page["cells"]) for page in template.pages[:page_index - 1])
    spec = template.pages[page_index - 1]
    count = len(spec["cells"])
    photos = [photos_by_order[start + i] if start + i < len(photos_by_order) else None for i in range(count)]
    image = _render_page(template, page_index, spec, photos,
                         placeholder_numbers=[start + i + 1 for i in range(count)])
    if width and width < image.width:
        image = image.resize((width, round(image.height * width / image.width)), Image.Resampling.LANCZOS)
    return image


def export_story(template: StoryTemplate, photo_paths: Sequence[Path], output_directory: Path,
                 *, image_format: str = "png", stem: str | None = None) -> list[Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    stem = stem or template.template_id
    extension = "jpg" if image_format.lower() in {"jpg", "jpeg"} else "png"
    written: list[Path] = []
    for index, image in enumerate(render_story(template, photo_paths), start=1):
        path = output_directory / f"{stem}_{index:02d}.{extension}"
        if extension == "jpg":
            image.save(path, format="JPEG", quality=95, subsampling=0, optimize=True)
        else:
            image.save(path, format="PNG", optimize=True)
        written.append(path)
    return written


def export_story_page(template: StoryTemplate, photo_paths: Sequence[Path], output_directory: Path,
                      page_index: int, *, image_format: str = "png", stem: str | None = None) -> Path:
    """Render and save one page, so a caller can report progress page by page."""
    if len(photo_paths) != template.photo_count:
        raise StoryTemplateError(
            f"Mẫu {template.name} cần đúng {template.photo_count} ảnh, nhận {len(photo_paths)}.")
    if not 1 <= page_index <= len(template.pages):
        raise StoryTemplateError(f"Mẫu {template.name} không có trang {page_index}.")
    start = sum(len(page["cells"]) for page in template.pages[:page_index - 1])
    spec = template.pages[page_index - 1]
    image = _render_page(template, page_index, spec, list(photo_paths[start:start + len(spec["cells"])]))
    output_directory.mkdir(parents=True, exist_ok=True)
    extension = "jpg" if image_format.lower() in {"jpg", "jpeg"} else "png"
    path = output_directory / f"{stem or template.template_id}_{page_index:02d}.{extension}"
    if extension == "jpg":
        image.save(path, format="JPEG", quality=95, subsampling=0, optimize=True)
    else:
        image.save(path, format="PNG", optimize=True)
    return path


def public_dict(template: StoryTemplate) -> dict[str, object]:
    canvas_w, canvas_h = template.canvas_size
    return {
        "templateId": template.template_id,
        "name": template.name,
        "description": template.data.get("description", ""),
        "outputKind": "image-set",
        "width": canvas_w,
        "height": canvas_h,
        "pageCount": len(template.pages),
        "requiredPhotos": template.photo_count,
        "pages": [{"index": index, "photoSlots": len(page["cells"]),
                   "captions": [caption["lines"] for caption in page.get("captions", [])]}
                  for index, page in enumerate(template.pages, start=1)],
    }


def iter_photo_slots(template: StoryTemplate) -> Iterable[tuple[int, int]]:
    for page_index, page in enumerate(template.pages, start=1):
        for cell_index, _ in enumerate(page["cells"], start=1):
            yield page_index, cell_index
