"""So sánh các mô hình tách nền của rembg trên ảnh thật, ngoài ứng dụng.

Chạy từ venv của backend:

    cd "C:\\Users\\Quan\\Documents\\ChatGPT\\Unkown app\\backend"
    .venv\\Scripts\\python.exe tools\\compare_cutout_models.py ^
        "D:\\anh\\meo.png" "D:\\anh\\co-gai-la.jpg" "D:\\anh\\chan-jeans.jpg"

Mỗi mô hình tải file ONNX về lần đầu; `birefnet-general` khoảng 900 MB nên cần
mạng và thời gian. Mô hình nào tải hỏng sẽ được báo và bỏ qua, các mô hình còn
lại vẫn chạy.

Kết quả ghi vào .\\cutout_comparison\\ :
  <ảnh>__<mô hình>.png            cutout nền trong suốt
  <ảnh>__<mô hình>__on_grey.png   ghép trên nền xám để nhìn rõ phần bị mất
  summary.csv                     bảng số liệu
"""
from __future__ import annotations

import csv
import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

MODELS = [
    "u2netp",
    "u2net",
    "isnet-general-use",
    "birefnet-general-lite",
    "birefnet-general",
]

INFERENCE_MAX_EDGE = 1600
MATTING = dict(
    alpha_matting=True,
    alpha_matting_foreground_threshold=240,
    alpha_matting_background_threshold=20,
    alpha_matting_erode_size=2,
)


def measure(image: Image.Image) -> dict[str, float | int]:
    """Số liệu để so sánh khách quan thay vì cảm nhận."""
    rgba = image.convert("RGBA")
    alpha = np.asarray(rgba)[:, :, 3]
    total = alpha.size
    solid = alpha > 127
    # Pixel biên: pixel đục có ít nhất một hàng xóm không đục.
    padded = np.pad(solid, 1, mode="constant", constant_values=False)
    neighbours = (
        padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    )
    edge = solid & ~neighbours
    partial = int(((alpha > 0) & (alpha < 255)).sum())
    return {
        "alpha_levels": int(len(np.unique(alpha))),
        "kept_pct": round(float(solid.sum()) / total * 100, 2),
        "partial_px": partial,
        "edge_px": int(edge.sum()),
        # < 1.0 nghĩa là biên cứng, không có chuyển tiếp mềm.
        "soft_edge_ratio": round(partial / max(int(edge.sum()), 1), 3),
    }


def run_model(name: str, source: Image.Image, model_home: Path):
    from rembg import new_session, remove

    session = new_session(name)
    bounded = source.copy()
    bounded.thumbnail((INFERENCE_MAX_EDGE, INFERENCE_MAX_EDGE), Image.Resampling.LANCZOS)

    started = time.perf_counter()
    try:
        removed = remove(bounded, session=session, post_process_mask=False, **MATTING)
        matting = "yes"
    except ImportError as error:
        print(f"    (alpha matting không khả dụng: {error}; chạy không matting)")
        removed = remove(bounded, session=session, alpha_matting=False, post_process_mask=False)
        matting = "no"
    elapsed = time.perf_counter() - started

    mask = removed.convert("RGBA").getchannel("A")
    if mask.size != source.size:
        mask = mask.resize(source.size, Image.Resampling.LANCZOS)
    result = source.copy()
    result.putalpha(mask)
    return result, elapsed, matting


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    out_dir = Path("cutout_comparison").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    model_home = out_dir / "models"
    model_home.mkdir(parents=True, exist_ok=True)
    os.environ["REMBG_HOME"] = str(model_home)
    os.environ["U2NET_HOME"] = str(model_home)

    rows: list[dict[str, object]] = []
    for raw in argv[1:]:
        path = Path(raw)
        if not path.is_file():
            print(f"BỎ QUA (không thấy tệp): {path}")
            continue
        with Image.open(path) as opened:
            source = ImageOps.exif_transpose(opened).convert("RGBA")
        print(f"\n=== {path.name}  ({source.width}x{source.height}) ===")

        for name in MODELS:
            try:
                result, elapsed, matting = run_model(name, source, model_home)
            except Exception as error:  # noqa: BLE001 - báo rồi đi tiếp
                print(f"  {name:24s} LỖI: {type(error).__name__}: {error}")
                rows.append({"image": path.name, "model": name, "error": f"{type(error).__name__}: {error}"})
                continue

            stem = f"{path.stem}__{name}"
            result.save(out_dir / f"{stem}.png")
            grey = Image.new("RGBA", result.size, (128, 128, 128, 255))
            Image.alpha_composite(grey, result).convert("RGB").save(out_dir / f"{stem}__on_grey.png")

            stats = measure(result)
            rows.append({"image": path.name, "model": name, "seconds": round(elapsed, 2),
                         "matting": matting, **stats})
            print(f"  {name:24s} {elapsed:6.2f}s  giữ={stats['kept_pct']:5.1f}%  "
                  f"mức_alpha={stats['alpha_levels']:3d}  biên_mềm={stats['soft_edge_ratio']:.2f}")

    if rows:
        fields: list[str] = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
        with (out_dir / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nĐã ghi: {out_dir}")
        print("Mở các tệp *__on_grey.png và phóng to vùng chi tiết mảnh để so bằng mắt.")
        print("Số liệu chỉ để sàng lọc; quyết định cuối cùng vẫn phải nhìn.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
