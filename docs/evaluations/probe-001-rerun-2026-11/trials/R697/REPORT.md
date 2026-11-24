<!-- recovered from the agent's final message; it could not write this file itself -->
R697 report (also in /home/claude/probe/trials/R697/REPORT.md)

Changed:
- src/data_profiler.py: profile_dataset() no longer calls profile_columns(). It fills only metadata and column_types, and still runs bivariate profiling when asked. The __main__ demo now calls profile_columns() too.
- src/profilers/univariate.py: this was the one in-repo caller relying on the old behaviour. It now calls profile_dataset() if "dataset" is in analyses, and profile_columns() if "columns" is. The default analyses give the same results as before.

Verified:
- Direct check: profile_dataset() returns only metadata and column_types. profile_columns() afterwards adds the per-column profiles and plots.
- test_models, test_static_report, test_understanding and test_credentials: 74 passed.
- The full pytest run timed out at 2 minutes, so test_cli and test_connectors were not run to completion. No test references profile_dataset or profile_columns.

Notes:
- This is a public behaviour change. External callers that call profile_dataset() then generate_report() will get no per-column sections or missing-value matrix until they also call profile_columns().
- I did not update codex_++/purpose_files/data_profiler.purpose.md (line 64) or the docs plan. The purpose file should be updated.
- ast_deps.csv mentions a run_profiler.profile_folder that calls both methods, but that file is not in the repo, so check external scripts.
- The AEC note about ASTDependencyExtractor.__init__ is unrelated to this change. Its caller list is incomplete (849 of 1578 calls unresolved), so I grepped the source for callers instead.
