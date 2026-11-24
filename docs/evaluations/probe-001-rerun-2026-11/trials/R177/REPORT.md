# R177 report

Changed:
- `src/data_profiler.py`: `profile_dataset()` no longer calls `profile_columns()`. It now only sets `results["metadata"]` and `results["column_types"]`, and still runs bivariate if `include_bivariate=True`. The `__main__` demo now calls `profile_columns()` explicitly, so its markdown report keeps the column sections.
- `src/profilers/univariate.py`: this caller relied on the old coupling (`if "dataset" ... elif "columns"`). I changed `elif` to `if`, so the default `analyses=["dataset","columns"]` still produces both. `analyses=["dataset"]` now yields no column stats or plots, as requested.
- `codex_++/purpose_files/data_profiler.purpose.md`: updated the one-line description of `profile_dataset`.

Tests: `python3 -m pytest -q` gives 89 passed. The suite takes about 75s. I added no new tests, and none of the existing ones covered this behaviour.

Things to know:
- This is a breaking behaviour change for any external caller that uses `profile_dataset()` and then reads `numeric_profiles`, `string_profiles` and similar keys. I found no other callers in the repo.
- `generate_report()` after only `profile_dataset()` still works. It prints metadata and column types, and the per-column sections are simply empty. I did not check whether the report handles the missing keys cleanly beyond the code path being reachable.
- `profile_columns()` always writes the `missing_value_matrix` plot, even when called alone. That is unchanged.
- The `docs/superpowers/plans` file mentions the old behaviour in a historical plan. I left it alone.
- `.claude`/AEC drift checks (`tools/drift_check.py`) were not run, because they are not part of the requested test command.
