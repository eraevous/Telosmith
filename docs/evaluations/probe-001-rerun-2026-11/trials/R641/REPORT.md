# R641 report

## Changed
- src/data_profiler.py: `profile_dataset()` no longer calls `profile_columns()`. It now sets only `metadata` and `column_types` (plus bivariate if requested). The `__main__` demo now calls `profile_columns()` explicitly so its report is still complete.
- src/profilers/univariate.py: this caller relied on the implicit call (its comment said so). With the change alone, analyses=["dataset","columns"] would have lost all column stats. Now `dataset` and `columns` run independently with two `if`s.
- codex_++/purpose_files/data_profiler.purpose.md: updated the contract line.

## Verified
Manual smoke test: `profile_dataset()` returns only `metadata` and `column_types`. After `profile_columns()` the column keys and plots are present.

## Caveats
- `python3 -m pytest -q` timed out at 2 minutes, so I did not get a result. I did not investigate whether this is pre-existing. No test references `profile_dataset` or `profile_columns`.
- Behaviour change: any external caller that relied on `profile_dataset()` to fill column profiles must now call `profile_columns()`. `generate_report()` after `profile_dataset()` alone now produces a report without column sections or the missing-value matrix. The "Call profile_dataset() first" error message is now slightly misleading.
- `ast_deps.csv` mentions a `run_profiler.profile_folder` caller that calls both methods, but that file is not in the repo. The AEC caller list is incomplete (849 of 1578 calls unresolved), so unseen callers may exist.
- The `ast_dependency_cli.__init__` structural context is unrelated to this change and I did not touch it.
