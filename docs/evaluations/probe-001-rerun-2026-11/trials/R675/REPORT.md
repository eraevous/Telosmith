# R675 report

Changed `understand()` in `repo/src/understanding/workflow.py` to return the artifact dict, the same content it writes to guide-profile.json. It still writes the files exactly as before.

The change has three parts:
- **Path-returning variant:** The old body became `understand_with_paths()`, which returns `(artifact, paths)`.
- **`understand()`:** This is now a thin wrapper that returns only the artifact.
- **`src/cli.py`:** The `understand` and `demo` commands call `understand_with_paths`, because they print `kind: path` lines from the old return value. Switching them kept the CLI output unchanged.

I made the split because the `src.cli` callers used the returned path dict, so changing the return type alone would have broken both commands.

The other caller, `docs/prototype/acceptance_fertility.py`, ignores the return value, so it is unaffected.

Tests: `tests/test_understanding.py` passes (59 passed). The full `pytest -q` run timed out at 2 minutes, so I didn't run the rest of the suite.

For the requester:
- This is a breaking change for any caller that expects the path dict. I found none in the repo, but the caller list was static analysis with many unresolved calls. Notebooks and external code that use the old dict need `understand_with_paths`.
- Nothing tests the new return value directly. I did not add a test.
- If `formats` leaves out "json", the artifact is still returned, but guide-profile.json is not written.
