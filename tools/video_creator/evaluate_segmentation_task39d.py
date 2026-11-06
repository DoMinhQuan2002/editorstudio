from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image, ImageDraw, ImageOps


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resize_shape(height: int, width: int, ref_size: int = 512) -> tuple[int, int]:
    if max(height, width) < ref_size or min(height, width) > ref_size:
        if width >= height:
            resized_height = ref_size
            resized_width = int(width / height * ref_size)
        else:
            resized_width = ref_size
            resized_height = int(height / width * ref_size)
    else:
        resized_height, resized_width = height, width
    resized_width -= resized_width % 32
    resized_height -= resized_height % 32
    return max(32, resized_height), max(32, resized_width)


def run_one(session: ort.InferenceSession, source: Path, out_dir: Path) -> dict[str, object]:
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    rgb = np.asarray(image)
    source_height, source_width = rgb.shape[:2]
    input_height, input_width = resize_shape(source_height, source_width)

    normalized = (rgb.astype(np.float32) - 127.5) / 127.5
    normalized = cv2.resize(normalized, (input_width, input_height), interpolation=cv2.INTER_AREA)
    model_input = np.transpose(normalized, (2, 0, 1))[None].astype(np.float32, copy=False)
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name
    started = time.perf_counter()
    raw = session.run([output_name], {input_name: model_input})[0]
    elapsed_ms = (time.perf_counter() - started) * 1000

    matte = np.squeeze(raw).astype(np.float32)
    matte = cv2.resize(matte, (source_width, source_height), interpolation=cv2.INTER_AREA)
    matte = np.clip(matte, 0.0, 1.0)
    alpha = np.rint(matte * 255.0).astype(np.uint8)

    safe_name = source.stem.replace(" ", "_")
    alpha_path = out_dir / f"{safe_name}_alpha.png"
    rgba_path = out_dir / f"{safe_name}_rgba.png"
    Image.fromarray(alpha, mode="L").save(alpha_path)
    rgba = np.dstack((rgb, alpha))
    Image.fromarray(rgba, mode="RGBA").save(rgba_path)

    nonzero_ratio = float(np.mean(matte > 0.05))
    confident_foreground_ratio = float(np.mean(matte >= 0.95))
    uncertain_edge_ratio = float(np.mean((matte > 0.05) & (matte < 0.95)))
    diagnostics = {
        "source": str(source),
        "sourceSha256": sha256(source),
        "sourceWidth": source_width,
        "sourceHeight": source_height,
        "modelInputWidth": input_width,
        "modelInputHeight": input_height,
        "inferenceMilliseconds": round(elapsed_ms, 2),
        "matteMin": float(matte.min()),
        "matteMax": float(matte.max()),
        "foregroundCoverageAbove0_05": round(nonzero_ratio, 6),
        "confidentForegroundCoverageAt0_95": round(confident_foreground_ratio, 6),
        "softEdgeCoverage": round(uncertain_edge_ratio, 6),
        "matteUniqueLevels": int(np.unique(alpha).size),
        "alphaPath": str(alpha_path),
        "rgbaPath": str(rgba_path),
    }

    display_width = 280
    display_height = 380
    source_thumb = ImageOps.fit(image, (display_width, display_height))
    alpha_thumb = ImageOps.fit(Image.fromarray(alpha, mode="L"), (display_width, display_height)).convert("RGB")
    fitted_rgb = np.asarray(source_thumb).astype(np.float32)
    fitted_alpha = np.asarray(ImageOps.fit(Image.fromarray(alpha, mode="L"), (display_width, display_height))).astype(np.float32)[..., None] / 255
    background = np.empty((display_height, display_width, 3), dtype=np.float32)
    background[:] = (52, 64, 76)
    composite = np.clip(fitted_rgb * fitted_alpha + background * (1 - fitted_alpha), 0, 255).astype(np.uint8)

    tile = Image.new("RGB", (3 * display_width, display_height + 54), "white")
    tile.paste(source_thumb, (0, 0))
    tile.paste(alpha_thumb, (display_width, 0))
    tile.paste(Image.fromarray(composite), (2 * display_width, 0))
    draw = ImageDraw.Draw(tile)
    draw.text((8, display_height + 8), f"Source: {source.name}", fill="black")
    draw.text((display_width + 8, display_height + 8), f"MODNet alpha · {diagnostics['softEdgeCoverage']:.2%} soft", fill="black")
    draw.text((2 * display_width + 8, display_height + 8), "RGBA on neutral background", fill="black")
    tile.save(out_dir / f"{safe_name}_qa.jpg", quality=92)
    return diagnostics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("images", nargs="+", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session = ort.InferenceSession(str(args.model), sess_options=options, providers=["CPUExecutionProvider"])
    results = [run_one(session, source, args.output) for source in args.images]
    payload = {
        "model": "Xenova/modnet",
        "modelRevision": "fa2fa546052fba4c08921230a26cc69a333fca12",
        "modelSha256": sha256(args.model),
        "runtime": ort.__version__,
        "providers": session.get_providers(),
        "results": results,
    }
    (args.output / "evaluation.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
