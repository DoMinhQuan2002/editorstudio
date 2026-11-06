"""Local foreground cutout for template overlay images."""
from __future__ import annotations

import os
from pathlib import Path
from threading import RLock

from PIL import Image, ImageOps


# Background removal model. Two earlier choices were wrong for this template:
# ``u2netp`` is rembg's portable U^2-Net at roughly 4.7 MB, resized to 320x320
# internally, which cannot resolve whiskers or loose hair; ``isnet-general-use``
# fixed that but is a salient-object detector, so on a photo holding an object it
# keeps the one dominant subject and drops the rest - a mug survives while the
# hand, sleeve and legs around it are erased. BiRefNet performs dichotomous
# segmentation of the whole foreground instead, which is what a held-object photo
# needs. It is markedly slower on CPU and downloads a large ONNX file on first
# use; cutouts are cached per asset, so that cost is paid once per image.
#
# MEDIASTUDIO_CUTOUT_MODEL overrides this, but note that the backend is launched
# by the desktop host rather than from a shell, so exporting that variable in a
# terminal does not reach it. Set it machine-wide, or edit the default here.
DEFAULT_MODEL_NAME = "birefnet-general"
MODEL_NAME = os.environ.get("MEDIASTUDIO_CUTOUT_MODEL", "").strip() or DEFAULT_MODEL_NAME

# Written into the cutout filename so that changing the model or the parameters
# below invalidates cutouts produced by an earlier configuration.
# Salient-object models (BiRefNet included) decide what "the subject" is: on a
# photo of a mug held in a hand they keep the mug and erase the hand and sleeve;
# on a first-person photo they drop the arm. A person-segmentation model finds
# exactly those parts, so its mask is merged into the object mask. Only person
# regions that touch the object are kept, so a stranger in the background is
# not pulled in. MEDIASTUDIO_CUTOUT_PERSON_MODEL="" disables the merge.
DEFAULT_PERSON_MODEL_NAME = "u2net_human_seg"
PERSON_MODEL_NAME = os.environ.get("MEDIASTUDIO_CUTOUT_PERSON_MODEL", DEFAULT_PERSON_MODEL_NAME).strip()
# Person regions within this fraction of the long edge of the object count as
# touching it.
PERSON_TOUCH_FRACTION = 0.02

CUTOUT_PIPELINE_REVISION = "v5"


def _tag(name: str) -> str:
    return name.replace("-", "_").replace(".", "_")


CUTOUT_CACHE_TAG = (
    f"{_tag(MODEL_NAME)}{'+' + _tag(PERSON_MODEL_NAME) if PERSON_MODEL_NAME else ''}"
    f"_{CUTOUT_PIPELINE_REVISION}"
)

# Inference and alpha matting both scale with pixel count, so the mask is solved
# on a bounded copy of the source. The resulting alpha is resampled back onto the
# untouched source, which keeps the saved cutout at the source's own resolution.
INFERENCE_MAX_EDGE = 1600

# Alpha matting converts the model's near-binary mask into sub-pixel coverage at
# fur and hair boundaries; without it every edge is hard and backlit fur renders
# as a comb. A small erode size keeps thin structures inside the trimap instead
# of eroding them away.
ALPHA_MATTING_FOREGROUND_THRESHOLD = 240
ALPHA_MATTING_BACKGROUND_THRESHOLD = 20
ALPHA_MATTING_ERODE_SIZE = 2

# An input counts as an existing cutout only when a real share of it is fully
# transparent. A handful of stray semi-transparent pixels, which compression and
# earlier processing both produce, is not evidence of a removed background.
EXISTING_CUTOUT_MIN_TRANSPARENT_RATIO = 0.02

_LOCK = RLock()
_SESSIONS: dict[tuple[Path, str], object] = {}

# Set once when alpha matting is unavailable, so the degraded path is reported
# instead of silently producing hard edges forever.
alpha_matting_unavailable_reason: str | None = None


class BackgroundRemovalError(RuntimeError):
    """Raised when an image cannot be converted to a transparent foreground."""


def _transparent_ratio(image: Image.Image) -> float:
    """Fraction of fully transparent pixels in an RGBA image."""
    pixel_count = image.width * image.height
    if pixel_count <= 0:
        return 0.0
    return image.getchannel("A").histogram()[0] / float(pixel_count)


def _session(model_home: Path, name: str) -> object:
    from rembg import new_session

    key = (model_home.resolve(), name)
    session = _SESSIONS.get(key)
    if session is None:
        try:
            session = new_session(name)
        except Exception as error:
            # A model name this rembg build does not ship fails here, and the
            # bare message does not say which names are valid.
            available = ""
            try:
                from rembg.sessions import sessions_names

                available = f" Mô hình khả dụng: {', '.join(sorted(sessions_names))}."
            except Exception:  # noqa: BLE001 - the hint is best-effort
                pass
            raise BackgroundRemovalError(
                f"Không tạo được phiên rembg cho mô hình {name!r}: {error}.{available}"
            ) from error
        _SESSIONS[key] = session
    return session


def _mask(image: Image.Image, session: object) -> Image.Image:
    from rembg import remove

    mask = remove(image, session=session, only_mask=True, post_process_mask=False)
    if not isinstance(mask, Image.Image):
        mask = Image.open(mask)
    mask = mask.convert("L")
    if mask.size != image.size:
        mask = mask.resize(image.size, Image.Resampling.LANCZOS)
    return mask


def _merge_touching_person(object_mask: Image.Image, person_mask: Image.Image) -> Image.Image:
    """Union of the object mask with the person parts that belong to it.

    The person model also fires on non-people: on a cat photo it marked the cat
    and a hanging plant above it as "person", so a raw union pasted a slab of
    plant and wall into the cut-out. What the merge is for is the photographer's
    or subject's own body - a hand holding a cup, an arm, a sweater, legs - and
    those enter the frame from the bottom or side edges. So a person region the
    object mask does not already cover is added only when it touches the object
    and reaches the bottom edge or a side edge in the lower half. Small detached
    regions are no longer let through: on the cat photo they were patches of the
    hanging plant behind the leaf, which showed as a dark fringe around it.
    """
    import numpy as np
    from scipy import ndimage

    obj = np.asarray(object_mask, dtype=np.uint8)
    per = np.asarray(person_mask, dtype=np.uint8)
    solid_object = obj > 127
    if not solid_object.any():
        # Nothing salient was found; the person is then the subject.
        return Image.fromarray(np.maximum(obj, per))
    height, width = obj.shape
    reach = max(1, round(PERSON_TOUCH_FRACTION * max(height, width)))
    grown = ndimage.binary_dilation(solid_object, iterations=reach)
    added = (per > 127) & ~solid_object
    labels, count = ndimage.label(added)
    if count == 0:
        return object_mask
    edge = max(2, round(0.01 * max(height, width)))
    lower_sides = np.zeros_like(added)
    lower_sides[height // 2:, :edge] = True
    lower_sides[height // 2:, -edge:] = True
    lower_sides[-edge:, :] = True
    keep_ids = []
    for index, region in enumerate(ndimage.find_objects(labels), start=1):
        component = labels[region] == index
        if not (component & grown[region]).any():
            continue
        if (component & lower_sides[region]).any():
            keep_ids.append(index)
    if not keep_ids:
        return object_mask
    keep = np.isin(labels, keep_ids) | solid_object
    keep = ndimage.binary_dilation(keep, iterations=reach)
    return Image.fromarray(np.maximum(obj, np.where(keep, per, 0).astype(np.uint8)))


def _matte(image: Image.Image, mask: Image.Image) -> Image.Image:
    """Alpha-matte the mask into soft edges, falling back to the plain mask.

    rembg's own ``post_process_mask`` stays off everywhere: its morphological
    cleanup removes small connected components, and whiskers are exactly that.
    """
    global alpha_matting_unavailable_reason
    if alpha_matting_unavailable_reason is None:
        try:
            from rembg.bg import alpha_matting_cutout

            matted = alpha_matting_cutout(
                image.convert("RGB"), mask,
                ALPHA_MATTING_FOREGROUND_THRESHOLD,
                ALPHA_MATTING_BACKGROUND_THRESHOLD,
                ALPHA_MATTING_ERODE_SIZE,
            )
            return matted.convert("RGBA").getchannel("A")
        except ImportError as error:
            # pymatting is an optional dependency of rembg; without it matting
            # cannot run, but a hard-edged cutout still beats no cutout.
            alpha_matting_unavailable_reason = str(error)
        except Exception as error:  # noqa: BLE001 - surfaced through the message below
            alpha_matting_unavailable_reason = f"{type(error).__name__}: {error}"
    return mask


def _foreground_alpha(image: Image.Image, model_home: Path) -> Image.Image:
    """Object mask, merged with touching person regions, then matted."""
    mask = _mask(image, _session(model_home, MODEL_NAME))
    if PERSON_MODEL_NAME:
        person = _mask(image, _session(model_home, PERSON_MODEL_NAME))
        mask = _merge_touching_person(mask, person)
    return _matte(image, mask)


def ensure_background_removed_image(
    source_path: Path,
    destination_path: Path,
    model_home: Path,
    *,
    crop_transparent_bounds: bool = False,
) -> Path:
    """Create and cache a cutout PNG, optionally trimming its transparent canvas."""
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.is_file() and destination_path.stat().st_size > 0:
        return destination_path

    with _LOCK:
        if destination_path.is_file() and destination_path.stat().st_size > 0:
            return destination_path
        model_home.mkdir(parents=True, exist_ok=True)
        os.environ["REMBG_HOME"] = str(model_home)
        os.environ["U2NET_HOME"] = str(model_home)
        try:
            with Image.open(source_path) as opened:
                source = ImageOps.exif_transpose(opened).convert("RGBA")

            if source.width <= 0 or source.height <= 0:
                raise BackgroundRemovalError("Ảnh nguồn rỗng.")

            if _transparent_ratio(source) >= EXISTING_CUTOUT_MIN_TRANSPARENT_RATIO:
                # Already a cutout; re-running segmentation would only degrade it.
                result = source
            else:
                bounded = source.copy()
                bounded.thumbnail((INFERENCE_MAX_EDGE, INFERENCE_MAX_EDGE), Image.Resampling.LANCZOS)
                mask = _foreground_alpha(bounded, model_home)
                if mask.size != source.size:
                    mask = mask.resize(source.size, Image.Resampling.LANCZOS)
                result = source.copy()
                result.putalpha(mask)

            if result.width <= 0 or result.height <= 0:
                raise BackgroundRemovalError("Mô hình tách nền trả về ảnh rỗng.")

            if crop_transparent_bounds:
                visible = result.getchannel("A").point(lambda value: 255 if value > 8 else 0)
                bounds = visible.getbbox()
                if bounds is not None:
                    left, top, right, bottom = bounds
                    padding_x = max(8, round((right - left) * 0.04))
                    padding_y = max(8, round((bottom - top) * 0.04))
                    result = result.crop((
                        max(0, left - padding_x),
                        max(0, top - padding_y),
                        min(result.width, right + padding_x),
                        min(result.height, bottom + padding_y),
                    ))

            temporary_path = destination_path.with_name(f".{destination_path.stem}.tmp.png")
            try:
                result.save(temporary_path, format="PNG", optimize=True)
                temporary_path.replace(destination_path)
            finally:
                temporary_path.unlink(missing_ok=True)
            return destination_path
        except BackgroundRemovalError:
            raise
        except Exception as error:
            raise BackgroundRemovalError(
                f"Không thể tách nền ảnh phủ bằng mô hình {MODEL_NAME}. Kiểm tra gói rembg "
                "và kết nối mạng lần đầu để tải mô hình."
            ) from error
