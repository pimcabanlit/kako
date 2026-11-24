# Kako: notes for Claude

Kako is a household financial planner built for ContextCon 2026, Challenge 05.
Working dates (Manila time): feature freeze Jan 10, 2027, submit Jan 16, deadline
Jan 18, 3:59 PM. Check the official ContextCon rules before any decision that
touches eligibility or submission.

## Key documents (read before changing behaviour)

The docs in `docs/` are the source of truth, and code follows them. If code and a doc
disagree, raise it, and update the doc in the same change once agreed.

- `docs/concept.md`: the problem, what Kako does, principles, how it uses Meko, scope.
- `docs/contextcon-2026.md`: dates, Challenge 05 brief, judging, prizes, submission
  checklist, Meko Free-tier limits, open questions.
- `docs/build-plan.md`: decisions already made, phases with a "Done when" test for each
  task, stretch goals, risks, video storyboard, open questions.
- `docs/architecture.md`: components, how a planning turn, a life event and dreaming flow,
  how Kako uses each part of Meko, agents, where data lives, controls, cost plan.
- `docs/data-model.md`: the data contract. Every Postgres table, the fact history rules
  (valid from, valid to, replaced by; replace versus retract), what Kako keeps in Meko,
  the calculations, validation rules and a worked example. A schema change updates it
  in the same PR.
- `docs/requirements-map.md`: every ContextCon rule, Challenge 05 objective, judging
  criterion and prize against what is built. Update a row when its status changes.
- `docs/meko-setup.md`: how Kako reaches local Meko and Meko Cloud, and the Phase 1 spike answers
  (traces, API keys, self-learning, extraction, AMP), each with what was run.
- `docs/azure-setup.md`: Kako's Azure side (resource group, budget, Foundry deployments, app
  registration, role, settings), how to check it with `check-models`, and lessons learned. No secrets.
- `REVIEW.md`: what the AI reviewer reports as Important, and the risk tier of each
  kind of change. Every PR states its tier and the file that set it.

## The one rule

The engine calculates, the agents explain and propose, the household decides.
Every peso figure comes from deterministic code; agents never do the maths.

## Decisions already made

- The product and repo name is **Kako**. "Myrqen", "Sank" and "Plankeeper" in
  older notes mean the same app.
- Nothing is silently overwritten. Every fact keeps its source, the date it took
  effect, and what replaced it, so "why is this different from before?" can be answered.
- Dreaming proposes, a person approves. Nothing becomes shared household knowledge
  without a yes.
- Four areas: budget, debt, savings, goals. Tax is knowledge-base reference only,
  never calculated.
- One orchestrator calls four specialists as tools and reconciles them. Dreaming runs
  as a background job after each session. Models come from **Azure AI Foundry** (OpenAI
  model deployments), signed in with Entra ID, through one model-manager module in the
  FastAPI backend; Next.js frontend. Kako has its own Azure resource group and budget.
- The honest line: Kako's agents investigate, try what-ifs and propose; the engine
  checks every figure; the household decides. Never say the agents "negotiate" or
  "learn" on their own.
- Meko Cloud extracts memories from what the user says. Kako treats those as candidates:
  dreaming reconciles them and the household approves, like any other proposal.
- The laptop runs only the backend and web app, natively on Windows, for the video.
  Development and tests run in cloud sessions and CI against local Meko; no Docker or
  WSL on the laptop.
- Meko Cloud holds the demo only; development and tests run against local Meko.
  Household data goes in AMP (Postgres in the datapack) if the Phase 1 test passes,
  otherwise plain Postgres.
- The demo household is a synthetic Philippine family, explained in plain terms:
  pesos, with 13th-month pay, SSS and Pag-IBIG as knowledge-base documents. No real data.
- One shared household datapack first. Per-person privacy is a stretch goal (needs Meko
  Pro; entrant Pro access is not being pursued).
- Out of scope: tax calculations, bank connections, real data, investment product picks.
- The repo is public and all rights reserved (no open source license). Switch to
  Apache-2.0 only if the full ContextCon terms require open source.

## Meko toolkit (use it, don't work from memory)

Kako is built on Meko, the context and memory platform behind ContextCon. This repo
loads Meko's own Claude Code toolkit, so every session starts with it:

- **`.claude/settings.json`** adds Meko's marketplace (`yugabyte/meko-skills`) and turns on
  the `meko-agent-skills` plugin: the `meko-mcp-tools` and `meko-select-datapack` skills,
  plus hooks that capture each session as a Meko conversation (SessionStart, PreCompact,
  SessionEnd).
- **`.mcp.json`** adds the `meko` MCP server at `MEKO_MCP_URL` (default: local Meko,
  `http://127.0.0.1:7777/mcp`) with `MEKO_API_KEY` as its bearer token. The plugin's hooks
  read the same two variables, so build sessions are captured to local Meko, not Meko Cloud.

| Need | Use |
| --- | --- |
| Memory, conversations, knowledge base, datapacks, artifacts, traces, AMP Postgres | The `meko` MCP server (`context_search` first, then `memory_search` or `knowledgebase_search`) |
| How to call the tools, ids, datapack routing | The `meko-mcp-tools` and `meko-select-datapack` skills (and their `references/`) |
| The `meko` and `meko-cli` commands, local server, REST API | [yugabyte/meko](https://github.com/yugabyte/meko) README and `src/meko/docs/` |
| Product docs, MCP reference, limits | [docs.mekodata.ai](https://docs.mekodata.ai/) (MCP server: `/reference/mcp-server/`), [pricing](https://mekodata.ai/pricing/) |
| Meko in Claude outside this repo | Meko's [Claude page](https://mekodata.ai/claude/): the claude.ai connector from [the directory](https://claude.ai/directory/connectors/meko), or `npx @yugabytedb/meko-mcp --client claude-code` for Claude Code elsewhere. One path per client, never both; sign in with the same identity as the Meko account |
| Questions to the Meko team | [Meko Discord](https://mekodata.ai/discord/) |

Setup on a new machine (Linux or Apple Silicon macOS):

```
curl -fsSL https://mekodata.ai/install.sh | sh   # local Meko, no sudo
meko start
export MEKO_MCP_URL=http://127.0.0.1:7777/mcp
export MEKO_API_KEY="$(meko token)"
claude                                          # trust the folder; accept the meko-skills marketplace and plugin
```

Check with `/mcp` (the `meko` server is connected) and `/plugin` (meko-agent-skills is on).

Local Meko runs on Linux (x64, arm64) and Apple Silicon macOS only. On Windows use WSL or a
cloud session. If `mekodata.ai` is blocked (as in cloud sessions), install the same release
from GitHub: Meko's `install.sh` with `--version <X.Y.Z>`, from
`github.com/yugabyte/meko/releases/download/meko-v<X.Y.Z>/install.sh`.

Cloud sessions that hold several repos start in the folder above them, so they don't read
`kako/.claude/settings.json` or `kako/.mcp.json`. The cloud environment ("First TEst") does the
same setup at user scope instead. Its setup script runs the block below, and two environment
variables go with it: `MEKO_MCP_URL=http://127.0.0.1:7777/mcp` (points the capture hooks at
local Meko; cloud installs need no token from this machine) and `MCP_TIMEOUT=60000` (gives the
first connect time to wait for Meko).

The setup script can still be running when Claude Code reads its config, so the block registers
`meko` first, as a command that waits for the `meko` binary, starts Meko, then bridges to its
HTTP endpoint with `mcp-remote`. That also restarts Meko in a resumed container, which doesn't
run the setup script again. The command is built in three lines because the environment's setup
script allows at most 200 characters a line; it registers exactly the same command. Keep the
version in step with the one tested below.

```
# Kako: local Meko + Meko's Claude Code plugin, at user scope (sessions start above the repos).
# Registers the meko server FIRST, so it is in Claude Code's config before Claude Code reads it.
# The server command waits for the meko binary, starts Meko, then bridges stdio to HTTP,
# so every session start and resume starts Meko.
if [ -d kako ]; then
  claude mcp remove --scope user meko || true
  MEKO_CMD='for i in $(seq 40); do [ -x "$HOME/.local/bin/meko" ] && break; sleep 1; done; '
  MEKO_CMD="$MEKO_CMD"'"$HOME/.local/bin/meko" start >/dev/null 2>&1; '
  MEKO_CMD="$MEKO_CMD"'exec npx -y mcp-remote@0.16.6 http://127.0.0.1:7777/mcp --allow-http'
  claude mcp add --scope user meko -- sh -c "$MEKO_CMD" || true
  curl -fsSL https://github.com/yugabyte/meko/releases/download/meko-v1.20261116.0/install.sh \
    | sh -s -- --version 1.20261116.0 --no-service --non-interactive || true
  ~/.local/bin/meko start || true
  claude plugin marketplace add yugabyte/meko-skills || true
  claude plugin install meko-agent-skills@meko-agent-skills --scope user || true
fi
```

Tested Nov 17, 2026 with Meko 1.20261116.0. In this repo: the `meko` server listed 40 tools,
the plugin's skills loaded as `meko-agent-skills:meko-mcp-tools` and
`meko-agent-skills:meko-select-datapack`, and the SessionStart hook captured the session into
local Meko (agent id `claude_code:kako`), not Meko Cloud. In a fresh "First TEst" session with
the block above: `meko` connected from the first turn with all 40 tools, both skills loaded,
and the session was captured to local Meko 2 seconds after Meko started. The plugin's own
Meko Cloud server fails to connect there (the network blocks `mcp.mekodata.ai`); that is
expected and keeps build sessions off Meko Cloud. The environment's script was updated to this
block on Nov 17, 2026; with Meko stopped by hand, opening the `meko` server started it again in
about 3 seconds.

Rules:

- If the `meko` MCP server or the Meko skills are not loaded in a session, say so before
  writing Meko code instead of guessing.
- Free tier: 1,000 conversations account-wide, and every captured session, test run and
  evaluation uses one. Dev, tests and build sessions use local Meko; point `MEKO_MCP_URL`
  at Meko Cloud only for the demo datapack.
- The plugin also declares a Meko Cloud MCP server (`https://mcp.mekodata.ai/mcp`, OAuth).
  Leave it unauthenticated unless you are working on the demo datapack.
- Never ask for, print or commit tokens. `MEKO_API_KEY` lives in the shell or a gitignored
  `.env`; `.env.example` lists the names.

## Conventions

- Two-space indentation (four for Python), LF line endings. See `.editorconfig`.
- Never commit secrets, API tokens, or `.env` files.
- Ship in small PRs: base files, docs, toolkit, the doc set, `REVIEW.md`, then CI.
- Every PR states its risk tier from `REVIEW.md` and the file that set it.

## Commands

Run from `backend/`. Keep this list current as commands are added.

```
uv sync                                   # install exact versions from uv.lock (Python 3.12)
uv run ruff check . && uv run ruff format --check .
uv run mypy                               # strict, src/kako
uv run pytest                             # unit tests; integration tests skip unless the two variables below are set
KAKO_TEST_DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:5432/kako_test \
KAKO_TEST_MEKO_URL=http://127.0.0.1:7777/mcp uv run pytest   # also against local Postgres and local Meko (never Meko Cloud)
uv run kako migrate                       # Alembic upgrade to the latest schema (KAKO_DATABASE_URL)
uv run kako api                           # /api/v1 on 127.0.0.1:8000; /api/v1/health, docs at /api/v1/docs
uv run kako check-models                  # Foundry settings, Entra ID sign-in, one tiny call per deployment; exit 1 on a FAIL
uv run kako demo load --through 2026-12-01T12:00+08:00   # the demo household: its seed, then each approved change up to then
uv run kako validate                      # V-01 to V-08 and V-16 over the household's facts; exit 1 on any (--household)
uv run kako figures --on 2026-09-15 --known-at 2026-09-15T18:00Z   # the engine's figures then (--household, --save)
uv run kako demo upload                   # the demo's statements and reference documents into Meko's knowledge base (counted in meko_call)
```

The web app, from `web/` (Node.js 24, see `web/.nvmrc`; the backend must be running):

```
npm ci              # install exact versions from package-lock.json
npm run dev         # http://localhost:3000; /api/v1/* is passed to the backend (KAKO_API_URL, default http://127.0.0.1:8000)
npm run lint        # ESLint (Next.js rules)
npm run typecheck   # route types, then tsc (strict)
npm run build       # production build
npm run check       # all three, as CI runs them
```

In a cloud session, start the local services first: `meko start` and `service postgresql start`.

CI (`.github/workflows/ci.yml`) runs the same lint, type check and tests on every pull request,
against a Postgres service and local Meko installed from its GitHub release at the version pinned
there (keep it in step with the setup block above). It sets `KAKO_REQUIRE_INTEGRATION=1`, so a
missing test variable fails instead of skipping. It never touches Meko Cloud and uses no secrets.

## Code layout

- `backend/`: the FastAPI backend (uv project `kako`, Python 3.12). `src/kako/settings.py` holds every
  setting (`KAKO_*`, plus `MEKO_MCP_URL` and `MEKO_API_KEY`); `cli.py` is the `kako` command;
  `health.py` the health report and `safe_error` (no secret reaches a response or a log);
  `api/app.py` the app and `/api/v1/health`; `db/` the engine, the declarative base, the table
  models (`db/models/`, one module per layer of `docs/data-model.md`), every enumerated column's
  values (`db/enums.py`, held as check constraints) and Alembic (`db/migrations/`, append-only once
  merged; `0002_tables.py` creates every table, `0003_fact_guard.py` the trigger that allows only
  the fact status transitions, a non-seed fact only with its approved proposal, and refuses deletes);
  `db/fact_store.py` records, replaces and retracts facts and reads snapshots, one transaction per
  write, each exactly what its proposal's payload names (only the seed loader calls
  `record_seed_fact`); `facts/` the pure fact rules (`attributes.py` the attribute catalog, `values.py`
  a value against its attribute, `proposals.py` proposal payloads and the check that a write is the
  one approved, `snapshot.py` snapshots `on` a date and `known_at` a time, `rules.py` V-01 to V-08 and
  V-16); `engine/` the deterministic engine, pure like `facts/` (`engine.py` `compute`: a snapshot,
  the entities and a what-if's overrides in, every figure of docs/data-model.md "Calculations" out,
  each citing what it read; `debts.py` the payoff with the rollover; `arith.py` centavos, half-up
  rounding and ratios; `dates.py` calendar months and the 100-year horizon; `inputs.py` what it
  reads; `figures.py` the figure and the run; `diff.py` F-DIFF-1, what changed between two runs and
  why, and the decisions to revisit). `db/calc_store.py` stores a run with the facts it read and its
  figures, and reads it back; `demo/` the demo household (`files.py` reads and checks
  `data/demo-household/`, `load.py` loads it through the fact store, each change as an approved
  proposal and then its write). `facts/` and `engine/` use no database, clock or
  randomness, which `tests/test_purity.py` checks; `meko/` the only package that talks to Meko
  (`client.py`, a small MCP client over Streamable HTTP whose sessions count tool calls and refuse
  any past their `max_tool_calls` ceiling, 0 by default; `adapter.py`, the one interface for every
  Meko call Kako makes; `mcp.py`, that interface over MCP (`open_meko`); `fake.py`, the same in memory
  for unit tests; `quota.py`, the call counter and quota guard every call goes through;
  `health.py`, the handshake probe). `db/meko_log.py` counts the calls in `meko_call`, and
  `demo/kb.py` uploads the demo's documents to the knowledge base. `agents/` the agents' plumbing:
  `chat.py` (a model call's request and reply as plain values, the request digest, the token
  estimate), `model_manager.py` (the only module that imports a model SDK: `check_models`, the
  live Foundry backend `FoundryChat`, and `ModelManager.chat`, which picks the tier's deployment,
  refuses a call past the turn's token budget or the daily spend cap, retries at most
  `KAKO_MODEL_MAX_RETRIES` times and logs every attempt with its cost), `recorded.py` (recorded
  responses: `RecordingBackend` saves replies by call key, `ReplayBackend` answers from the file
  with no network; `KAKO_MODEL_MODE`), `spend.py` (cost from the per-token prices, the `llm_call`
  log protocol), `turn.py` (a turn's token budget and step numbers, the `agent_step` log protocol)
  and `tool_loop.py` (`run_agent`: one agent's bounded loop, at most 4 counted tool calls and
  then only its final tool, every tool call an `agent_step`). `db/llm_log.py` and
  `db/agent_steps.py` write those two tables, each row committed on its own.
- `backend/tests/`: unit tests need nothing running; `tests/integration/` runs only when
  `KAKO_TEST_DATABASE_URL` or `KAKO_TEST_MEKO_URL` is set, and refuses a Meko URL that isn't local.
  `tests/support/data_model.py` reads the tables out of `docs/data-model.md`: `test_schema_doc.py`
  holds the models to it and `tests/integration/test_schema.py` the migrated database (a fresh
  database per test, migrated twice), with the checks the database must refuse.
  `test_facts_*.py` test the fact rules on rows in memory (`tests/support/facts.py` builds them);
  `test_engine_worked_example.py` checks every worked-example figure to the centavo
  (`tests/support/villanueva.py` builds that household's history in memory from the demo files), `test_engine_rules.py` the flags,
  rollover, goals, what-ifs and what each figure cites, and `test_engine_properties.py` seeded
  property tests (payments equal balance plus interest, order independence, identities), and
  `test_engine_diff.py` the worked example's diff from plan v2 to v3 and each label;
  `test_demo_files.py` the demo files and each mistake they can hold;
  `tests/integration/test_demo_load.py` the demo loaded into Postgres: every rule passes, its figures
  there are the worked example's (also as known at an earlier time), a run's round trip and the commands;
  `tests/integration/test_fact_store.py` each status transition, the rules on each write and the
  database guard behind them.
  `tests/integration/test_meko_smoke.py` creates a conversation, adds a memory, finds it and
  cleans up (at most 6 tool calls).
  `test_model_calls.py` (budgets, the cap, retries, cost and the log), `test_tool_loop.py` (the
  loop's bounds and steps), `test_recorded.py` (a two-agent turn recorded, then replayed with every
  socket refused) and `test_model_sdk_imports.py` (Ruff refuses a model SDK anywhere but the model
  manager) use the scripted model in `tests/support/models.py`, never Foundry;
  `tests/integration/test_agent_logs.py` writes and reads `llm_call` and `agent_step`.
  `test_meko_quota.py` and `test_meko_adapter.py` test the counter, the guard, `McpMeko` against a
  scripted server, `FakeMeko` and the demo upload; `tests/integration/test_meko_adapter.py` runs the
  adapter on local Meko with every call counted in Postgres (documents go to a throwaway datapack),
  the ceiling, two callers racing for the last call, and `kako demo upload`.
- `web/`: Next.js 16 App Router, TypeScript strict, Tailwind 4, Lucide icons. `next.config.ts`
  passes `/api/v1/*` to the backend; `src/app/` the pages (the layout carries the "synthetic data,
  not financial advice" line); `src/components/health-panel.tsx` the system check with its loading
  and error states; `src/lib/health.ts` the health report's types (kept in step with the backend's
  `health.py`). `web/AGENTS.md` is written by `next dev`: this Next.js differs from older versions,
  so read `web/node_modules/next/dist/docs/` before writing Next.js code. shadcn/ui is added when
  its registry (`ui.shadcn.com`) is reachable from the session; it is blocked today.
- Ruff bans model SDK imports (`openai`, `azure.identity`, `azure.ai`) everywhere except
  `src/kako/agents/model_manager.py` (REVIEW.md rule 10).
