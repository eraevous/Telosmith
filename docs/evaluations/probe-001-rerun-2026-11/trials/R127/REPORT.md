# R127 report

**Changed: nothing.** I did not delete `src/connectors/credentials.py` or `tests/test_credentials.py`.

**Why:** the module is not dead. The request checked only `connectors/`, but `src/cli.py` imports it. In `_build_connector`, the snowflake branch does `from connectors.credentials import load_credentials` and calls it with `credentials_path or cfg.get("credentials")`. The result is passed to `SnowflakeConnector(credentials=creds, ...)`. The import is lazy (inside the function), which is why a top-level import search misses it. Deleting the module would make every snowflake run via the CLI (`guide profile` and `guide run --config`) fail with ImportError. It would also remove the `--credentials` flag, the `GUIDE_CREDENTIALS_FILE` env var and the `SF_*` env var fallbacks.

`SnowflakeConnector` takes a plain dict because the CLI builds that dict with `load_credentials`. That is the intended design. `docs/superpowers/plans/2026-04-20-eda-tool-redesign.md` lists the module as a planned part of the redesign, not scaffolding left over from it.

**Tests:** `tests/test_credentials.py` passes (6 passed). The full `python3 -m pytest -q` run hit my 2-minute tool timeout, so I have no full-suite result. I did not investigate why it is slow.

**For the requester:** if you do want to remove credential loading, the CLI needs a replacement first, such as inline dict config only, and the `--credentials` flag has to be dropped on purpose. Tell me if that is the intent and I'll do it as a separate change. Otherwise the module and its tests should stay.
