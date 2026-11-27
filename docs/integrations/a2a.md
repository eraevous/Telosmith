# An A2A Agent Card for a Telosmith-based project

DEC-256 item 5 asks that anything built on Telosmith can connect to anything else built on it. An
[A2A](https://a2a-protocol.org/) Agent Card is how an agent tells another agent what it is, where to
reach it and which skills it offers. `aec a2a` builds that card the same way for every project and
checks one you already have. This is the second slice of item 5 (the first is the MCP server, #95),
and an experiment under DEC-200: it is not yet proved compatible with anything. The Lydian
compatibility test (item 6) is what will prove it.

## Build a card

```bash
aec a2a card --name my-tool --description "What my tool does." --version 0.3.0 \
  --url https://my-tool.example/a2a \
  --skill "records=Records|Read this project's records.|records,read-only" \
  --provider "My Org=https://my-org.example" \
  -o .well-known/agent-card.json
```

- `--skill ID=NAME|DESCRIPTION|tag1,tag2` repeats, one per skill. Tags must not be empty.
- `--binding` is the protocol binding of the endpoint: `JSONRPC` (default), `GRPC` or `HTTP+JSON`.
- `-o` never overwrites an existing file. Without `-o` the card goes to standard output.
- From Python: `aec.a2a.build_card(...)` returns the card as a dict and raises `CardError` naming
  every problem; `aec.a2a.skill(...)` builds one skill.

## Check a card

```bash
aec a2a check .well-known/agent-card.json   # exit 0, or 1 with one line per problem
```

`aec.a2a.validate_card(card)` returns the same problems as a list and never raises.

## What the card follows

A2A protocol version 1.0. The fields checked as required:

| Object | Required fields |
|---|---|
| AgentCard | `name`, `description`, `supportedInterfaces`, `version`, `capabilities`, `defaultInputModes`, `defaultOutputModes`, `skills` |
| AgentInterface (each `supportedInterfaces` entry) | `url` (absolute http or https for `JSONRPC` and `HTTP+JSON`; `host:port` or a URL for `GRPC`; any non-empty string for other bindings), `protocolBinding`, `protocolVersion` |
| AgentSkill | `id` (unique in the card), `name`, `description`, `tags` (non-empty) |
| AgentProvider (optional) | `organization`, `url` |

In 1.0 the endpoint URL and protocol version are per interface; the 0.3 top-level `url`,
`preferredTransport` and `protocolVersion` are not written. `.well-known/agent-card.json` is the
conventional place to serve the card from.

**Source and verification:** the field list was read from the A2A 1.0 protobuf reference
(`lf.a2a.v1`) and the a2a-go v2 types on 2026-11-20, partly through a summary; the well-known path is
from the earlier spec and was not re-checked. The checker enforces only the fields above. It does not
check `securitySchemes` or `signatures`; of extensions it checks only that each has a `uri`, plus the authority socket's
own rules ([authority-socket.md](authority-socket.md)). It does not prove a client accepts the card.

## Not covered

Serving the card over HTTP, signing it, security schemes, the extended card and A2A task handling. The
authority socket is declared in the card ([authority-socket.md](authority-socket.md)); the Agent Skills folder is
[agent-skills.md](agent-skills.md). The card describes the project; it grants no authority.
