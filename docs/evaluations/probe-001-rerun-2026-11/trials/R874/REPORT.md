# Report R874

## Changed: nothing
I did not delete `src/connectors/credentials.py` or `tests/test_credentials.py`.

## Why
The module is not dead code. The premise ("nothing in `connectors/` imports it") is true but misleading, because the importer is outside `connectors/`:
- `src/cli.py:60` imports `load_credentials` inside the snowflake branch of `_build_connector`. It calls it at line 62 to build the `creds` dict that it passes to `SnowflakeConnector`.
- `SnowflakeConnector` only takes a plain dict because the CLI resolves credentials first. The module supplies the `--credentials` flag, the `GUIDE_CREDENTIALS_FILE` env var, the `SF_*` env var fallback, and validation of required fields.
- The import is local to the function, so a quick grep for top-level imports can miss it. It is also easy to miss if you only search inside `connectors/`.
- Deleting the module would make `data-guide ... --connector snowflake` fail with ImportError. Deleting `tests/test_credentials.py` would remove the only tests for that path.
- Baseline `python3 -m pytest -q` passes, so no test breaks now. I did not delete anything, so I did not re-run it afterwards.

## For the requester
- The AEC snapshot caveat applies in both directions. Here it shows a real caller (`src.cli._build_connector`).
- If the real goal is to remove credential-file handling, the work is bigger. Remove the `--credentials` option and the `cfg["credentials"]` use in `cli.py`, decide how Snowflake credentials are supplied instead, and then delete the module and its tests together.
- I'm happy to do that if you confirm the intended design.
