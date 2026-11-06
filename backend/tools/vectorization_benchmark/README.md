# MediaStudio raster-to-SVG benchmark (Task 08A)

The benchmark compares the production Smart Reconstruction V2 API route with the experimental Contour-Preserving API route. It does not change either vectorization engine or the default engine selection.

Run commands from `backend/` with the project virtual environment:

```powershell
..\.venv\Scripts\python.exe -m tools.vectorization_benchmark init
..\.venv\Scripts\python.exe -m tools.vectorization_benchmark validate
..\.venv\Scripts\python.exe -m tools.vectorization_benchmark run --scope smoke
..\.venv\Scripts\python.exe -m tools.vectorization_benchmark run --scope all --resume
..\.venv\Scripts\python.exe -m tools.vectorization_benchmark report
```

To add a user-provided image, run this from `backend/` after checking its source family and rights:

```powershell
..\.venv\Scripts\python.exe -c "from pathlib import Path; from tools.vectorization_benchmark.dataset import add_image; add_image(Path(r'C:\\images\\sample.png'), image_id='sample-logo-01', source_family_id='sample-logo-family', category='flat_logos_icons', source_description='User-provided flat logo fixture', author='unknown', license_status='user_provided_unknown', usage_permission='local benchmark only')"
```

`category` is one of the dataset groups. If one design is relevant to several groups, add the additional category labels to that manifest item while preserving its single source family ID. Review the updated manifest, then explicitly relock with:

```powershell
..\.venv\Scripts\python.exe -m tools.vectorization_benchmark lock-split --confirm-review
```

Source files are referenced in place and are not copied into the public/source tree. `--resume` reuses only successful rows when run identity, source SHA, SVG SHA and render existence still match. Per-image jobs use a separate worker process and the backend JobManager remains serial. The default per-engine timeout is 900 seconds and can be overridden with `--timeout`.

Artifacts are written to `backend/artifacts/contour_preserving/task_08a/`. The Edge/Chromium render is the primary metric renderer; Svg.Skia is used as a secondary consistency check when the repository's existing `VectorDiagnostics` binary is available. Opaque images without trustworthy foreground references receive raster-reference color metrics; silhouette geometry is reported unavailable rather than treating the full canvas as a foreground mask. Human-review sheets are pending until a reviewer fills in scores.

Synthetic fixtures and their analytic alpha/semantic sidecars remain explicitly labeled as synthetic. They are evidence for measurement validation and not real-world dataset coverage.
