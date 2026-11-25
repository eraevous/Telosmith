# R655 report

Changed `DataProfiler.profile_dataset()` (src/data_profiler.py) so it no longer calls `profile_columns()`. It now computes only the metadata and column types, plus bivariate if asked.

The one known caller relied on the old behaviour, so I also changed:
- src/profilers/univariate.py: `profile()` defaulted to analyses `["dataset","columns"]` and used `profile_dataset()` to run the column profiling. I changed `elif "columns"` to `if "columns"`. Without this, the default call would silently return empty `column_stats`. Behaviour is unchanged for the default and for `["dataset"]`. `["dataset"]` alone now gets no column stats, and that is the speedup you asked for.
- src/data_profiler.py `__main__` demo: it calls `profile_columns()` before `generate_report`.
- codex_++/purpose_files/data_profiler.purpose.md: updated the description of `profile_dataset`.

Things to know:
- This is a breaking change for anyone calling `profile_dataset()` and expecting column profiles. `generate_report()` will then show no column sections or plots unless `profile_columns()` has run. The AEC caller list is incomplete (849 of 1578 calls were unresolved), so check for external callers. I found none in the repo besides docs/superpowers/plans/2026-04-20-eda-tool-redesign.md, an old plan that I left alone.
- The `generate_report` error message still says "Call profile_dataset() before generating a report". I didn't reword it.
- Tests: each test file passes when run separately (cli 8, connectors 7, credentials 6, models 5, static_report 4, understanding 59). The full `pytest -q` run in one go exceeds the 2-minute timeout, so I ran the files individually. I added no test that checks `profile_dataset()` skips column profiling.
