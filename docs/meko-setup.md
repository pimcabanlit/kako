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

**Meko Cloud (verified Nov 17, Meko MCP 3.2.4):** the same: `conversation_get` with
`include_messages: true` returned the turn's `input`, `output`, `reasoning`, `plan` and `metadata`
exactly as saved. No response carries a portal URL for the conversation or its trace (link: to check
in the portal).

### 2. Meko Cloud from the backend with an API key

**Docs:** a server process sends `Authorization: Bearer mko_tkn_...` and a `User-Agent` to
`https://mcp.mekodata.ai/mcp`, and names the datapack with `datapack_id` on each call. There is no
Python SDK; MCP is the way in. Keys are made under Settings > API Keys and shown once.

**Meko Cloud (verified Nov 17): yes.** Kako's own client (`MekoMcpSession`, with `User-Agent:
kako/<version>`) completed the handshake (server "Meko MCP" 3.2.4, protocol 2025-06-18) and every tool
call below with a `mko_tkn_` key from a server process. Two differences from local Meko:

- Every call needs a `conversation_id`, as locally; `datapack_create` and `datapack_delete` refuse an
  `agent_id` argument.
- Meko Cloud lists more tools: the four self-learning tools, 14 `amp_*` tools and `track_token_usage`
  (57 in all, against 40 locally).

### 3. Self-learning tools on Free

**Docs:** four tools (`selflearning_status`, `selflearning_query_log`, `selflearning_shortfalls`,
`selflearning_verify`), registered only where the deployment turns self-learning on; Meko Cloud does.
They need the datapack's owner or a maintainer, and `selflearning_verify` counts as a search. Local
Meko 1.20261116.0 does not list them.

**Meko Cloud (verified Nov 17): yes, on Free.** In the spike datapack:

1. `context_search` "How much is the household's monthly electricity bill?" returned only the rent
   memory (best score 0.50), `match_quality: low`, and the hint "Weak or no match: do not guess".
2. `selflearning_query_log` listed it at once: band `low`, reason `weak_match`, category `coverage`,
   to-do `add_context`.
3. `memory_add` "The household's electricity bill is about 3,200 pesos a month."
4. `selflearning_verify` with that `log_id`, 10 seconds later: `outcome: improved`, band `low` to
   `high`, best score 0.50 to 0.76, `indexing: false`.

So the "Context Gaps" story works on Free: a weak search, the missing fact added (after the household
approves it), and a replay that proves the fix. Each replay counts as one search.

### 4. Meko Cloud's own extraction

**Docs:** Meko Cloud extracts memories from saved turns in the background, from the user's own
messages, best-effort ("can occasionally miss an individual fact"). The public docs name no switch to
turn it off for a Cloud datapack; `datapack_update` only has `conversation_search_opt_out`. Local Meko
extracts only when `meko memory-extractor` is on.

**Meko Cloud (verified Nov 17):**

- **No opt-out.** Neither `datapack_update` nor `datapack_describe` has an extraction setting; the only
  switch is `conversation_search_opt_out`. Every saved turn is extracted.
- **About 17 seconds.** The turn was saved at 10:53:07 and its two memories were created at 10:53:24.
- **What they look like.** One memory per fact, reworded with an added interpretation: "User's
  household pays 18,000 pesos in rent each month, a recurring housing expense that affects their
  monthly budget." Metadata holds only `meko_datapack_id`; `run_id` is the conversation id, and
  `attributed_to: "user"`. There is no `source` field and no link to the turn's `message_id`.
- **Kako's own memories** (`memory_add`) keep the metadata Kako passes (`{"kako_source":
  "approved_fact", "fact_id": ...}`) and carry `role: "user"` instead of `attributed_to`.

**Decision for Kako:** extraction can't be turned off, so every memory without Kako's `kako_source`
metadata is a candidate, never a fact. Dreaming reads them (by `run_id`, the conversation), proposes
facts, and the household approves; approved facts are written with `memory_add` and `kako_source`.
The engine never reads memories for figures; figures come from the fact store in Postgres.

### 5. AMP on our account

**Docs:** AMP is a Postgres database in a datapack. To reach it from outside Meko, its writer endpoint
must be created public (`ingress_external`) with an allow list of addresses no broader than a `/24`;
the choice can't be changed later. The password is shown once. Each tier has a compute budget.

**Meko Cloud (Nov 17):**

- **vCPU cap on Free: 0.5 across the whole account** (`amp_core_budget`). One database with its
  default writer (0.5 vCPU, 4 GiB, Postgres 18) uses all of it.
- **Create:** `amp_cluster_create` with a writer, `ingress_external` and the laptop's address as a `/32`
  took 19 seconds. The endpoint is `ep-<id>.db.mekodata.ai:<port>`, user `admin`. The password is
  shown once (Kako passed its own).
- **Branch:** `amp_branch_create` (zero-copy) took under 3 seconds, handshake included. But a branch
  needs its own endpoint to be queried, and `amp_compute_create` on it was refused with
  `FREE_TIER_CORE_LIMIT`. So on Free, branches can't serve what-ifs next to the main database.
- **Laptop:** to check: connect, migrate, time it.

## Verification log

| Date | Where | What |
| --- | --- | --- |
| Nov 17, 2026 | Cloud session, local Meko 1.20261116.0 | One conversation with one turn: `plan`, `reasoning` and `metadata` read back with `conversation_get`; conversation deleted |
| Nov 17, 2026 | Cloud session, Meko Cloud (MCP 3.2.4), datapack `kako-spike` | 2 conversations, 1 turn, 1 `memory_add`, 2 searches (1 `context_search`, 1 `selflearning_verify`); AMP database, branch, refused branch endpoint |
