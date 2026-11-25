# R174 report

**Changed** (request done as asked):
- `src/data_profiler.py`: `profile_dataset()` no longer calls `profile_columns()`. It now returns only `metadata` and `column_types` (plus bivariate if requested). Added a docstring. The `__main__` demo now calls `profile_columns()` explicitly so its report is still full.
- `src/profilers/univariate.py`: `profile()` relied on the old hidden behavior (default `analyses=["dataset","columns"]` skipped the explicit call). It now calls `profile_dataset()` and `profile_columns()` independently, so the default output is unchanged. `analyses=["dataset"]` alone is now fast and returns empty `column_stats`, which is the intent.
- `codex_++/purpose_files/data_profiler.purpose.md`: updated the one line describing `profile_dataset`.

**Tests:** `python3 -m pytest -q` gives 89 passed (about 65s). No test covers `profile_dataset` directly, and I added none.

**Be aware:**
- This is a behavior change for any external caller that used `profile_dataset()` and expected column profiles. In this repo the only callers were the two above.
- `generate_report()` after `profile_dataset()` alone works but has no column sections or missing-value matrix. The matrix plot is made in `profile_columns()`, so it is skipped as well.
- `ast_deps.csv` and `docs/superpowers/plans/...md` are generated or historical, so I left them alone.
- AGENTS.md's Run/Drift rules are about a different (Predictions) project; this was a Run-type task.
