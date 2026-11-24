# Meko setup and spikes

How Kako reaches Meko, and the answers to the Phase 1 spikes (docs/build-plan.md, Phase 1, task 6),
each with what was run. Keep it current when Meko changes or a fallback is chosen. No secrets here.

## Where Kako talks to Meko

| Where | Meko | URL | Key |
| --- | --- | --- | --- |
| Development, tests, CI | Local Meko 1.20261116.0 | `http://127.0.0.1:7777/mcp` | `meko token`, or none |
| The demo and the video | Meko Cloud, the demo datapack only | `https://mcp.mekodata.ai/mcp` | A `mko_tkn_` API key in `MEKO_API_KEY` |

- One package talks to Meko: `backend/src/kako/meko/` (REVIEW.md rule 9). Kako calls it through one
  interface (`adapter.py`): `McpMeko` over MCP, or `FakeMeko` in memory for unit tests. Each adapter
  session refuses calls past `KAKO_MEKO_SESSION_MAX_CALLS` (50 by default).
- Every call is counted in `meko_call` before it is sent. On Meko Cloud, each Free-tier-capped tool stops
  at `KAKO_MEKO_CLOUD_CEILING` calls (0 by default, so nothing reaches Meko Cloud until it is set for the
  demo); local Meko has no ceiling.
- `KAKO_MEKO_DATAPACK_ID` names the datapack every call uses (unset: the default one), and
  `KAKO_MEKO_LANGFUSE_PROJECT_ID` gives the "See the trace" link on Meko Cloud.
- Knowledge-base files go up with `knowledgebase_upload_document` and a POST to the one-time link it
  returns, which works on local Meko and Meko Cloud alike (`knowledgebase_upload_file` reads a path on
  Meko's own machine, so it can't reach Meko Cloud). The link carries its own authorisation: the API key
  is never sent with it. Meko knows a file by its content, so uploading it again sends nothing. The
  document status names no document id (search hits do), so tests that upload files use a throwaway
  datapack and delete it.
- Every request names the client in `User-Agent` (`kako/<version>`): Meko Cloud asks for it, and its
  firewall has refused clients without one (Meko release notes, installer transports).
- Plain `http://` is accepted only for this machine (`127.0.0.1`, `localhost`, `::1`). Any other host
  must use `https://`, so an API key never travels in clear text.
- Every tool call takes a `conversation_id`: create the conversation first. `agent_id` is
  `kako:<role>` (for example `kako:orchestrator`).

## The spikes

Status: **answered** (Nov 17). Local Meko and Meko's docs answered part of each question; the rest
ran on Meko Cloud in a separate spike datapack (`kako-spike`, Pim's choice), deleted afterwards with
its AMP database and both conversations. It used 2 conversations, 1 saved turn, 1 `memory_add` and 2
searches, out of the account's lifetime allowances (docs/contextcon-2026.md), and 1 of the account's
10 lifetime datapacks.

| Question | Answer | What Kako does |
| --- | --- | --- |
| Traces | Yes: each turn keeps `plan`, `reasoning` and `metadata`, and the portal has a link per conversation | Saves every turn with its plan and reasoning; "See the trace" links to the portal |
| Meko Cloud from the backend | Yes, with a `mko_tkn_` key and a `User-Agent` | The demo backend uses `MEKO_API_KEY` and `https://mcp.mekodata.ai/mcp` |
| Self-learning on Free | Yes; `selflearning_verify` reported `improved` | Context Gaps screen: a weak search, the household approves the missing fact, the replay proves it |
| Extraction | Always on, about 17 s after a turn, no source tag | Memories without Kako's `kako_source` are candidates for dreaming, never facts |
| AMP | Works from the laptop; 0.5 vCPU per account on Free; branches can't be queried | Household data in AMP for the demo, few queries per turn; what-ifs stay in the engine |

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
exactly as saved.

**The link (checked in the portal by Pim):** each conversation is a session in the portal's Observe
page, which embeds Langfuse traces:

```
https://cloud.mekodata.ai/observe-hub?project=<langfuse_project_id>&session=<conversation_id>
```

`langfuse_project_id` is one value per account (Meko returns it in `memory_get_all`); Kako keeps it
in a setting, added with the Meko adapter (Phase 2). The page shows each tool call as a span with its latency, the session's tokens and cost,
and its tags (`agent:<agent_id>`). It needs the account's sign-in, so the link is for Pim and the
video, not for judges without the account.

**Local Meko's trace (verified Nov 24, Meko 1.20261116.0):** local Meko keeps a call log, one row
per MCP tool call with its conversation id, latency, outcome and parts (a `context_search` lists its
`conversation_search`, `memory_search` and `knowledge_base_search` with their times and result
counts). It serves the log at `GET /api/v1/calls` (newest first, `before=<id>` for the next page; the
web UI's Calls page reads the same), with no token from this machine. That is the local equivalent of
the Observe hub's spans: `GET /api/v1/sessions/{id}/trace` reads it for one session's conversation
(`meko/trace.py`, local Meko only, at most 20 pages and 15 seconds back to the session's start; a
read cut short by either comes back with `truncated: true`). It is a read of
Meko's own log, not a tool call, so no allowance is spent and it isn't counted in `meko_call`.

**Each turn Kako keeps** (Phase 3, task 6): `input` the household's message, `output` the reply,
`plan` the steps taken (2 to 4), `reasoning` the specialists' summaries and the resolution's reason,
and `metadata` the turn seed, session, household and date, the turn's run, each what-if's run, and
the plan, recommendation and reconciliation ids, and `kako_flagged` (the numbers the check could not
match, by text) when there are any, since Meko keeps the texts as shown. `conversation_get` with `include_messages: true`
reads them back (`Meko.read_turns`, counted like any call). Meko makes a turn's `message_id` from its
`seed` alone (the same seed in two conversations gave the same id, verified Nov 24), so Kako's seed
for Meko is `<session id>:<turn seed>`.

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
- **Laptop (Pim's Windows laptop, Nov 17): works.** With `KAKO_DATABASE_URL` pointing at the endpoint
  (`?ssl=require`), `kako migrate` ran and `/api/v1/health` reported "PostgreSQL 18.2, schema 0001".
  The first health check took 4.7 s (connection, TLS); once connected, 1.4 s for the probe's two
  queries plus the pool's ping. From Manila each round trip to the database costs a few hundred
  milliseconds, so a planning turn must keep its queries few and batched.
- **This cloud session** can't reach it: the allow list holds only the laptop's address, and a cloud
  session's outgoing address is not fixed. Tests and CI keep using local Postgres.

## Verification log

| Date | Where | What |
| --- | --- | --- |
| Nov 17, 2026 | Cloud session, local Meko 1.20261116.0 | One conversation with one turn: `plan`, `reasoning` and `metadata` read back with `conversation_get`; conversation deleted |
| Nov 17, 2026 | Cloud session, Meko Cloud (MCP 3.2.4), datapack `kako-spike` | 2 conversations, 1 turn, 1 `memory_add`, 2 searches (1 `context_search`, 1 `selflearning_verify`); AMP database, branch, refused branch endpoint |
| Nov 17, 2026 | Pim's laptop | `kako migrate` and `/api/v1/health` against the AMP endpoint; the portal's trace page for the spike conversation |
| Nov 17, 2026 | Cloud session, local Meko 1.20261116.0 | The adapter (Phase 2, task 6): every demo document uploaded and indexed in seconds; a second upload finds each one already there; a search for 13th-month pay finds its document |
| Nov 17, 2026 | Cloud session, Meko Cloud | Clean-up: AMP database deleted (vCPU back to 0 of 0.5), both conversations and the `kako-spike` datapack deleted |
| Nov 24, 2026 | Cloud session, local Meko 1.20261116.0 | A turn through the session API (session 2, recorded model): the conversation's turn read back with its plan, reasoning and Kako's ids; the session's 3 Meko calls read from the call log as spans, the same 3 counted in `meko_call`. Found: a turn's message id comes from its seed alone |
