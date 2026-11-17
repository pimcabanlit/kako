# Meko setup and spikes

How Kako reaches Meko, and the answers to the Phase 1 spikes (docs/build-plan.md, Phase 1, task 6),
each with what was run. Keep it current when Meko changes or a fallback is chosen. No secrets here.

## Where Kako talks to Meko

| Where | Meko | URL | Key |
| --- | --- | --- | --- |
| Development, tests, CI | Local Meko 1.20261116.0 | `http://127.0.0.1:7777/mcp` | `meko token`, or none |
| The demo and the video | Meko Cloud, the demo datapack only | `https://mcp.mekodata.ai/mcp` | A `mko_tkn_` API key in `MEKO_API_KEY` |

- One package talks to Meko: `backend/src/kako/meko/` (REVIEW.md rule 9). Each session counts its tool
  calls and refuses any past its `max_tool_calls` ceiling, 0 by default.
- Every request names the client in `User-Agent` (`kako/<version>`): Meko Cloud asks for it, and its
  firewall has refused clients without one (Meko release notes, installer transports).
- Plain `http://` is accepted only for this machine (`127.0.0.1`, `localhost`, `::1`). Any other host
  must use `https://`, so an API key never travels in clear text.
- Every tool call takes a `conversation_id`: create the conversation first. `agent_id` is
  `kako:<role>` (for example `kako:orchestrator`).

## The spikes

Status: **in progress**. Local Meko and Meko's docs answer part of each question; the rest runs on
Meko Cloud in a separate spike datapack (`kako-spike`, Pim's choice, Nov 17), deleted afterwards.
Budget for the whole spike: about 10 conversations, 10 searches and a few memories, out of the
account's lifetime allowances (docs/contextcon-2026.md).

### 1. Traces: `plan` and `reasoning` per turn, and a link to the trace

**Local Meko (verified Nov 17):** `conversation_add_message` takes `input`, `output`, `plan` (2 to 4
steps), `reasoning` and `metadata` (a JSON object as a string). `conversation_get` with
`include_messages: true` returns each turn with all five, plus `message_id` and `created_at`:

```
"input": "Our rent is 18,000 pesos a month.",
"output": "Noted: rent of 18,000 pesos a month, a fixed cost.",
"reasoning": "Rent is a fixed cost, so it goes in the budget as is.",
"plan": ["Read the stated rent", "Record it as a fixed monthly cost"],
"metadata": {"kako_turn": 1}
```

So Kako can keep each turn's plan and reasoning in Meko and read them back to show "how we got here".

**Meko Cloud:** to check: the same fields, and whether a turn or conversation has a portal URL Kako can
link to (the portal shows decision and execution traces per conversation).

### 2. Meko Cloud from the backend with an API key

**Docs:** a server process sends `Authorization: Bearer mko_tkn_...` and a `User-Agent` to
`https://mcp.mekodata.ai/mcp`, and names the datapack with `datapack_id` on each call. There is no
Python SDK; MCP is the way in. Keys are made under Settings > API Keys and shown once.

**Meko Cloud:** to check: Kako's own client (`MekoMcpSession`) completes the handshake and a tool call
with a key from a server process.

### 3. Self-learning tools on Free

**Docs:** four tools (`selflearning_status`, `selflearning_query_log`, `selflearning_shortfalls`,
`selflearning_verify`), registered only where the deployment turns self-learning on; Meko Cloud does.
They need the datapack's owner or a maintainer, and `selflearning_verify` counts as a search. Local
Meko 1.20261116.0 does not list them.

**Meko Cloud:** to check: are they listed for a Free account, and does `selflearning_verify` report
`improved` after a missing fact is added?

### 4. Meko Cloud's own extraction

**Docs:** Meko Cloud extracts memories from saved turns in the background, from the user's own
messages, best-effort ("can occasionally miss an individual fact"). The public docs name no switch to
turn it off for a Cloud datapack; `datapack_update` only has `conversation_search_opt_out`. Local Meko
extracts only when `meko memory-extractor` is on.

**Meko Cloud:** to check: is there an opt-out, how many seconds after a turn the memories appear, and
what `source` and metadata they carry. Kako treats them as candidates either way: dreaming reconciles
them and the household approves (docs/architecture.md).

### 5. AMP on our account

**Docs:** AMP is a Postgres database in a datapack. To reach it from outside Meko, its writer endpoint
must be created public (`ingress_external`) with an allow list of addresses no broader than a `/24`;
the choice can't be changed later. The password is shown once. Each tier has a compute budget.

**Meko Cloud:** to check from the laptop: create a database, connect, time a snapshot query and a
branch, read the vCPU cap. A cloud session's outgoing address is not fixed, so tests and CI keep using
local Postgres either way.

## Verification log

| Date | Where | What |
| --- | --- | --- |
| Nov 17, 2026 | Cloud session, local Meko 1.20261116.0 | One conversation with one turn: `plan`, `reasoning` and `metadata` read back with `conversation_get`; conversation deleted |
