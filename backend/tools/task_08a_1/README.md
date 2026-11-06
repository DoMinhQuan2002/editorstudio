# Task 08A.1 benchmark tooling

All outputs stay under `backend/artifacts/contour_preserving/task_08a_1/`. This package does not edit production vectorization or WPF code.

## Commands (from `backend/`)

```powershell
.\.venv\Scripts\python.exe -m tools.task_08a_1.dataset init
.\.venv\Scripts\python.exe -m tools.task_08a_1.dataset validate
.\.venv\Scripts\python.exe -m tools.task_08a_1.dataset import --source C:\path\image.png --category flat_logos_icons --source-family-id studio-logo-01 --license-status CC0 --provenance-url https://example.org/source --author "Author"
.\.venv\Scripts\python.exe -m tools.task_08a_1.runner run --timeout 900
.\.venv\Scripts\python.exe -m tools.task_08a_1.runner finalize
.\.venv\Scripts\python.exe -m tools.task_08a_1.review validate C:\path\completed-review.csv
.\.venv\Scripts\python.exe -m tools.task_08a_1.review import C:\path\completed-review.csv
```

`runner run` reuses Task 08A ACTIVE FOX records only after checking their source and saved SVG/render hashes. New source-family samples run through the existing API worker. Resume skips only a PASS record whose source, both engines, SVG files and rendered PNG hashes still match the run identity.

The static blind page does not write user scores. `human_review_results.csv` is created only by the explicit `review import` command after score-schema validation. Blind engine mapping is in a separate coordinator file; do not open it before review is finished.

Current sources are nine scikit-image documented samples plus the existing user-supplied ACTIVE FOX family. Source family assignment, Task 08A-compatible 64-bit DCT perceptual hash, provenance, license, exact duplicate and near duplicate checks are recorded. Near-duplicate results are review candidates, not automatic merges.
