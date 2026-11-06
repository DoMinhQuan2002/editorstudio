"""Direct Phase A entry point. Does not dispatch or change the app's SVG API."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from mediastudio.image_tools.vectorization_v2 import run_phase_a


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", type=Path, default=ROOT / "backend/tests/fixtures/active_fox.jpg")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scale", type=int, choices=(1, 3, 4), default=3)
    args = parser.parse_args()
    output = args.output or ROOT / "backend/tests/artifacts/vectorization_v2" / args.image.stem / "phase_a"
    fixture = ROOT / "backend/tests/fixtures/active_fox.jpg"
    matches_fixture = hashlib.sha256(args.image.read_bytes()).digest() == hashlib.sha256(fixture.read_bytes()).digest()
    legacy = ROOT / "backend/tests/baselines/vectorization/legacy_foreground.png" if matches_fixture else None
    result = run_phase_a(args.image, processing_scale=args.scale, debug_directory=output,
                         legacy_foreground=legacy)
    print(json.dumps(result.metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
