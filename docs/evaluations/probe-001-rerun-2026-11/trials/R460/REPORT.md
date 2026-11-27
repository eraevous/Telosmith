# R460 report

Changed:
- `src/understanding/workflow.py`: `understand()` now returns the artifact dict (the same object `dumps()` writes to guide-profile.json). Files are written exactly as before. The old body moved into new `understand_with_paths()`, which returns `(artifact, {format: path})`. `understand()` is a thin wrapper that returns the first item.
- `src/cli.py`: the `understand` and `demo` commands use `understand_with_paths`, so their output (`json: path`, ...) is unchanged. A plain return-type change would have broken both, because they iterate `paths.items()`.

Tests: `tests/test_understanding.py` passes (59). The full `pytest -q` run timed out at my 2-minute limit, so I did not complete it. I did not add a test for the new return value.

Note for the requester:
- This is a breaking change for any other caller that used the returned paths. I found none in the repo besides the CLI. `docs/prototype/acceptance_fertility.py` ignores the return value.
- The AEC caller list covered `CredentialsValidationError`, which is unrelated to this change. I did not use it, and it says nothing about `understand()` callers. I found the callers by grep.
- The artifact is a plain dict. The caller gets the in-memory object, not a JSON round-trip, so values like numpy types or tuples may differ from what `json.loads` of the file returns.
