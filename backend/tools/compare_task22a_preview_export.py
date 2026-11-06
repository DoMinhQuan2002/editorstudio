from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image


def run(command: list[str]) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(command, capture_output=True, check=False, timeout=90)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace")[-2000:])
    return result


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python compare_task22a_preview_export.py <Denim-validation-directory>")
    root = Path(sys.argv[1]).resolve()
    source = root / "denim-regression-summary.json"
    candidate = root / "denim_task22a_api_composition.mp4"
    output = root / "preview-export-parity.json"
    if not source.is_file() or not candidate.is_file():
        raise FileNotFoundError("Validation summary or candidate composition export is missing.")
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite an existing parity report: {output}")
    summary = json.loads(source.read_text(encoding="utf-8"))
    ffmpeg = summary["ffmpegCapabilities"]["ffmpegPath"]
    samples = []
    for preview in summary["previewSamples"]:
        seconds = float(preview["seconds"])
        frame_index = round(seconds * 30)
        frame = run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(candidate), "-vf",
                     f"select=eq(n\\,{frame_index})", "-frames:v", "1", "-f", "image2pipe",
                     "-vcodec", "png", "pipe:1"])
        with Image.open(root / preview["file"]) as left_source, Image.open(BytesIO(frame.stdout)) as right_source:
            left = left_source.convert("RGB")
            right = right_source.convert("RGB")
            if left.size != right.size:
                raise RuntimeError(f"Frame size mismatch at {seconds}s: {left.size} != {right.size}")
            mae = sum(abs(a - b) for a, b in zip(left.tobytes(), right.tobytes())) / (
                left.width * left.height * 3
            )
        samples.append({
            "timeSeconds": seconds,
            "frameIndex": frame_index,
            "previewRenderer": preview["renderer"],
            "rgbMae": mae,
            "threshold": 18.0,
            "status": "PASS" if mae <= 18.0 else "FAIL",
        })
    report = {
        "task": "TASK 2.2A API preview/export frame parity",
        "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "candidate": str(candidate),
        "method": "Compare API preview PNG against decoded H.264 frame at the same 30fps frame index; RGB MAE threshold 18.0.",
        "samples": samples,
        "allPassed": all(sample["status"] == "PASS" for sample in samples),
    }
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["allPassed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
