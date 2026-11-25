# R245 report

**Changed: nothing. I did not delete `src/connectors/credentials.py` or `tests/test_credentials.py`.**

The premise is wrong: the module is live code. `src/cli.py` lines 60-66, in `_build_connector`'s snowflake branch, does `from connectors.credentials import load_credentials` and calls it. That is the only way the `--credentials` CLI flag, the `credentials` config key, the `GUIDE_CREDENTIALS_FILE` env var and the `SF_*` env vars reach `SnowflakeConnector`. The CLI calls `_build_connector` from lines 148 and 182.

Why "nothing in `connectors/` imports it" misled: the importer is `cli.py`, outside `connectors/`. It is also a function-local import, so a grep of `connectors/` or of top-level imports misses it. The AEC snapshot did list `src/cli.py:60` as a caller.

Deleting the module would make the snowflake CLI path fail with ImportError, and `--credentials` would stop working. `tests/test_credentials.py` covers that behavior (6 tests, all pass), so it should stay too.

Tests: `tests/test_credentials.py` passes (6 passed). The first full `python3 -m pytest -q` run showed passing dots but I did not see its summary line. A second full run timed out at 2 minutes. I did not find out why, and it is unrelated to this non-change. So I cannot say the whole suite is green.

For the requester:
- If the goal is to retire the module, first change `cli.py` to pass a plain dict. That drops the `--credentials` flag and the env-var and file loading, so it is a product decision.
- If the redesign intended to drop it, confirm that with the owner and say so in the decision log.
- I did not check the April spec or plan docs in `docs/superpowers/` for intent.
