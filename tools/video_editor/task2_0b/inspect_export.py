#!/usr/bin/env python3
"""Read-only FFprobe/FFmpeg validation for a WPF-exported MP4."""

from __future__ import annotations

import argparse
import array
import json
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any


def parse_times(value: str) -> list[float]:
    if not value.strip():
        return []
    return [float(part.strip()) for part in value.split(",") if part.strip()]


def run_rms(ffmpeg: str, media: Path, seek_seconds: float, duration: float) -> float | None:
    if seek_seconds < 0:
        return None
    command = [
        ffmpeg, "-hide_banner", "-v", "error", "-ss", f"{seek_seconds:.4f}",
        "-i", str(media), "-t", f"{duration:.4f}", "-map", "0:a:0",
        "-vn", "-ac", "1", "-ar", "48000", "-f", "s16le", "pipe:1",
    ]
    process = subprocess.run(command, capture_output=True, check=False)
    if process.returncode != 0 or len(process.stdout) < 2:
        return None
    samples = array.array("h")
    samples.frombytes(process.stdout[:len(process.stdout) // 2 * 2])
    if not samples:
        return None
    mean_square = sum(float(sample) * sample for sample in samples) / len(samples)
    return math.sqrt(mean_square) / 32768.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--marker-times", default="0.5,2.5,5.0", help="WAV marker pulse starts in seconds")
    parser.add_argument("--gap-times", default="1.5,3.5", help="Expected quiet WAV positions in seconds")
    parser.add_argument("--timeline-offset-seconds", type=float, default=0.0)
    parser.add_argument("--sample-window-seconds", type=float, default=0.12)
    parser.add_argument("--out", type=Path, help="Optional JSON summary path")
    args = parser.parse_args()
    if not args.file.is_file():
        parser.error(f"Export file not found: {args.file}")
    ffprobe = shutil.which(args.ffprobe)
    ffmpeg = shutil.which(args.ffmpeg)
    if not ffprobe or not ffmpeg:
        parser.error("ffprobe and ffmpeg must be on PATH or passed with --ffprobe/--ffmpeg")

    probe_command = [
        ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(args.file)
    ]
    probe_run = subprocess.run(probe_command, capture_output=True, text=True, check=False)
    if probe_run.returncode != 0:
        parser.error(f"ffprobe failed: {probe_run.stderr[-1000:]}")
    probe = json.loads(probe_run.stdout)
    format_data = probe.get("format", {})
    streams = []
    for stream in probe.get("streams", []):
        streams.append({
            "index": stream.get("index"),
            "codecType": stream.get("codec_type"),
            "codecName": stream.get("codec_name"),
            "width": stream.get("width"),
            "height": stream.get("height"),
            "sampleRate": stream.get("sample_rate"),
            "channels": stream.get("channels"),
            "durationSeconds": stream.get("duration"),
        })

    decode = subprocess.run(
        [ffmpeg, "-hide_banner", "-v", "error", "-i", str(args.file), "-f", "null", "-"],
        capture_output=True, text=True, check=False,
    )
    markers = []
    window = max(0.02, min(args.sample_window_seconds, 1.0))
    for marker_start in parse_times(args.marker_times):
        center = args.timeline_offset_seconds + marker_start + 0.10
        seek = max(0.0, center - window / 2)
        markers.append({
            "expectedPulseStartSeconds": args.timeline_offset_seconds + marker_start,
            "sampleStartSeconds": seek,
            "sampleWindowSeconds": window,
            "rms": run_rms(ffmpeg, args.file, seek, window),
        })
    gaps = []
    for quiet_time in parse_times(args.gap_times):
        center = args.timeline_offset_seconds + quiet_time
        seek = max(0.0, center - window / 2)
        gaps.append({
            "expectedQuietCenterSeconds": center,
            "sampleStartSeconds": seek,
            "sampleWindowSeconds": window,
            "rms": run_rms(ffmpeg, args.file, seek, window),
        })
    has_video = any(item["codecType"] == "video" for item in streams)
    has_audio = any(item["codecType"] == "audio" for item in streams)
    summary: dict[str, Any] = {
        "file": str(args.file),
        "fileSizeBytes": args.file.stat().st_size,
        "formatName": format_data.get("format_name"),
        "durationSeconds": format_data.get("duration"),
        "streams": streams,
        "hasVideo": has_video,
        "hasAudio": has_audio,
        "fullDecodeExitCode": decode.returncode,
        "fullDecodeStderr": decode.stderr[-1000:],
        "audioMarkerSamples": markers,
        "audioGapSamples": gaps,
        "audioMarkerRmsIsDiagnosticOnly": True,
        "sourceFileWasNotModified": True,
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if decode.returncode == 0 and has_video else 2


if __name__ == "__main__":
    raise SystemExit(main())
