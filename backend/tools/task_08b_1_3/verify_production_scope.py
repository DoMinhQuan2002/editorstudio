from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[2]
ARTIFACTS = BACKEND / "artifacts" / "contour_preserving" / "task_08b_1_3"
PRESERVED_PHASE_E_SHA256 = "AF3539CB7A56959450293A48C2EBFAAC2BAB4A2FFA67F0547BA639B6A3938B43"
SCOPE = (
    "mediastudio/image_tools/vectorization_v2",
    "mediastudio/image_tools/vectorization_contour",
    "mediastudio/image_tools/contour_backend.py",
    "mediastudio/image_tools/contour_svg_composer.py",
    "mediastudio/image_tools/vectorize.py",
    "mediastudio/api.py",
)


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            value.update(chunk)
    return value.hexdigest().upper()


def current_hashes() -> dict[str, str]:
    files: list[Path] = []
    for item in SCOPE:
        path = BACKEND / item
        if path.is_dir():
            files.extend(path.rglob("*.py"))
        elif path.is_file():
            files.append(path)
    return {path.relative_to(BACKEND).as_posix(): sha256(path)
            for path in sorted(files) if path.is_file()}


def main() -> dict[str, Any]:
    before_json = json.loads((ARTIFACTS / "production_scope_before.json").read_text(encoding="utf-8-sig"))
    before = {row["path"].replace("\\", "/"): row["sha256"].upper() for row in before_json["scope"]}
    after = current_hashes()
    changed = sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))
    phase_e = after.get("mediastudio/image_tools/vectorization_v2/phase_e.py")
    result = {
        "task": "08B.1.3",
        "productionFilesBefore": len(before),
        "productionFilesAfter": len(after),
        "scopeFilesChanged": changed,
        "productionScopeUnchanged": not changed and len(before) == len(after),
        "phaseE1_2AcceptedSha256": PRESERVED_PHASE_E_SHA256,
        "phaseECurrentSha256": phase_e,
        "task08b1_2RadialFixPreserved": phase_e == PRESERVED_PHASE_E_SHA256,
        "diagnosticProductionFilesTouched": [],
        "scope": list(SCOPE),
        "note": "SHA-256 before/after verification; repository status is not used as the source-of-truth for this check.",
        "afterManifest": [{"path": path, "sha256": digest} for path, digest in sorted(after.items())],
    }
    (ARTIFACTS / "production_scope_after.json").write_text(
        json.dumps({"capturedAt": __import__("datetime").datetime.now().astimezone().isoformat(),
                    "scope": result["afterManifest"]}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (ARTIFACTS / "production_changes.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "productionFilesBefore", "productionFilesAfter", "scopeFilesChanged",
        "productionScopeUnchanged", "task08b1_2RadialFixPreserved")}, indent=2))
    return result


if __name__ == "__main__":
    main()
