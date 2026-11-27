# R159 report

**Changed nothing.** I did not delete `src/connectors/credentials.py` or `tests/test_credentials.py`, because the module is not dead.

- `src/cli.py` line 60 imports `load_credentials` from `connectors.credentials`, inside the snowflake branch of `_build_connector`. The import is inside the function, so a search for top-level imports misses it. Line 62 calls it, and the result is passed to `SnowflakeConnector(credentials=creds, ...)`.
- That call is the only thing that fills the plain dict `SnowflakeConnector` takes. It resolves the `--credentials` flag, the `GUIDE_CREDENTIALS_FILE` env var and the `SF_*` env vars, and it validates required fields.
- Deleting the module would break `guide` on any Snowflake source with an `ImportError` at runtime. `tests/test_credentials.py` is the only coverage of this logic.
- Nothing inside `connectors/` imports the module, as the requester said. The caller is `cli.py`, one level up. The AEC listing was for `understanding.annotations.load`, which is unrelated to this module, and it says itself that unresolved calls can hide callers.

**For the requester:**
- If the aim is to drop the credentials layer, `cli.py` first needs a replacement that builds the dict directly. Then the module and its tests can go. That is a behaviour change (the `--credentials` flag and `GUIDE_CREDENTIALS_FILE` support), so it should be decided on purpose.
- If you only want it tidier, moving the module out of `connectors/` or adding a comment about its caller would be safe.
- The full pytest run timed out after 2 minutes in my environment (cause not investigated), so I have no test baseline. Since I changed no files, none was needed.
