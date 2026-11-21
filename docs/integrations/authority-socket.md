# Authority socket: a declared field, protocol undecided

Author: claude:aec#wake-20261121-13 · Reviewer: none yet (Codex on open; Kate asked for the records) · model=claude-opus-5-5

Status: **experiment** (DEC-200 build gate), DEC-256 item 5, third slice. Handoff HO-AEC-20261119-V8FC.

DEC-185 makes authority part of the socket model: a component declares what authority it needs and what it accepts
or grants, and authority reaches it only through that socket. The protocol is undecided (R&D; DEC-197 starts its
design from an ontology). Until there is one, a Telosmith-based tool can only **declare**. This page is the
specification the declaration's URI points at.

## Where it lives

In the A2A Agent Card (`aec a2a card`, see [a2a.md](a2a.md)), as an A2A extension in `capabilities.extensions`:

```json
{"uri": "https://github.com/eraevous/Telosmith/blob/main/docs/integrations/authority-socket.md",
 "description": "Kairos authority socket (DEC-185): ...",
 "required": false,
 "params": {"needs": ["read and write the content folder the caller names"], "accepts": [], "grants": [],
            "protocol": "undecided (DEC-185)"}}
```

```bash
aec a2a card --name N --description D --version V --url URL \
  --authority-needs "read and write the content folder the caller names" --authority-grants "none"
```

Python: `aec.a2a.build_card(..., authority={"needs": [...], "accepts": [...], "grants": [...]})`.

The URI is pinned: `aec.a2a.AUTHORITY_EXTENSION_URI`, exactly the string above. The location (an A2A extension) is
provisional and doesn't settle item 7's manifest schema; that stays Zach's decision (Kate, round 6).

## Rules the checker applies (`aec a2a check`)

- `needs`, `accepts`, `grants` and `protocol` must all be present; the three lists hold non-empty strings (empty lists
  allowed); no other keys.
- `protocol` is exactly `undecided (DEC-185)` until Zach adopts a protocol.
- `required` is never `true`: a client may not be made to depend on a protocol that doesn't exist.
- Other extensions need only a non-empty `uri`.

## What it is not

- **Not a grant.** The declaration authorizes nothing and nothing reads or enforces it. Authority still comes from
  Zach's decisions, as recorded in each project's ledger.
- **Not the protocol.** No signatures, hashes, authority roots or ontology kinds (DEC-178, DEC-197 are inputs to R&D).
- **Not the manifest schema.** Item 7 proposes that, as Agent Card plus MCP listings; this field is meant to carry
  into it. The free-text entries follow Prospero's provisional `packet/manifest.json` (`needs`, `grants`).

Record: `AEC-R-authority-socket-impl@1` (implementer).
