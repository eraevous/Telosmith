# R753 report

**Changed: nothing.** I did not delete `src/connectors/credentials.py` or `tests/test_credentials.py`.

Why: the module is live code, not scaffolding. `src/cli.py` (lines 60-66, in `_build_connector`, the `snowflake` branch) lazily imports `connectors.credentials.load_credentials`. It calls it to resolve credentials and passes the result to `SnowflakeConnector(credentials=creds, ...)`. The teammate saw no import because the caller is `src/cli.py`, outside `connectors/`, and the import sits inside a function. `SnowflakeConnector` takes a plain dict because the CLI builds that dict with this module.

Deleting the module would make `guide ... --connector snowflake` fail with ImportError. It would also remove the only handling of the `--credentials` flag, the `GUIDE_CREDENTIALS_FILE` env var and the `SF_*` env vars. The deleted tests would be the only coverage of that logic.

Notes for the requester:
- The AEC structural context was about `understanding.annotations.load`, which is unrelated to this request. It says nothing about `credentials.py`.
- A plain grep for `credentials` found the `cli.py` caller straight away.
- I ran `python3 -m pytest -q` once, and it timed out after 2 minutes. I did not investigate, since no files changed. The suite may hang or be slow in this environment.
- If you want to retire the module, first decide how the CLI should get Snowflake credentials. Then change `cli.py` and move or replace the tests.
