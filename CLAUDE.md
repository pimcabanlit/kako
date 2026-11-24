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
- `docs/tuning-log.md`: each real model run that tunes a prompt or a tool, with its prediction
  written before the run.
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
uv run kako api                           # /api/v1 on 127.0.0.1:8000 (loopback only: no sign-in yet); /api/v1/health, /api/v1/sessions (turns, trace), docs at /api/v1/docs
uv run kako check-models                  # Foundry settings, Entra ID sign-in, one tiny call per deployment; exit 1 on a FAIL
uv run kako demo load --through 2026-12-01T12:00+08:00   # the demo household: its seed, then each approved change up to then
uv run kako validate                      # V-01 to V-08 and V-16 over the household's facts; exit 1 on any (--household)
uv run kako proposals list                # what waits for the household (--status pending|approved|rejected|expired|all, --household)
uv run kako proposals approve <id>… --by Mara   # approve together and write what each names, offer what is now ready to share, then Meko upkeep (--no-meko; --confirm-promotion: a promotion's second yes); again changes nothing (reject: the same)
uv run kako figures --on 2026-09-15 --known-at 2026-09-15T18:00Z   # the engine's figures then (--household, --save)
uv run kako demo upload                   # the demo's statements and reference documents into Meko's knowledge base (counted in meko_call)
uv run kako ask "How hard should we pay down the card?" --on 2026-09-15 --seed s2:t1   # one planning turn (--title, --known-at, --household, --no-meko, --by Mara: who says it)
KAKO_MODEL_MODE=replay KAKO_RECORDED_RESPONSES=../data/recorded/session-2.json uv run kako ask …   # the same turn from a recording, no Foundry
uv run kako demo run                      # demo mode: migrate, load the whole story, upload the documents, replay the scripted sessions (local Meko, no Azure)
uv run kako demo run --test-set           # … and replay the agent test set for each recorded architecture (--strict: refuse a request that differs from its recording)
KAKO_MODEL_MODE=record uv run kako demo record session-4   # record one scripted session on Foundry, on an empty database (spends; log a prediction in docs/tuning-log.md first)
uv run kako test-set                      # the agent test set's score, replayed from data/recorded/test-set-specialists.json (needs the household loaded through Dec 1)
uv run kako test-set --architecture single --only q01,q07   # the single-agent baseline, some questions (--household, --save: data/test-set/results/)
KAKO_MODEL_MODE=record uv run kako test-set   # the only way it calls Foundry: records a new run (spends; log a prediction in docs/tuning-log.md first)
uv run kako dream end <session>           # end a session (once) and queue its dreaming run (--at; the API: POST /api/v1/sessions/{id}/end)
uv run kako dream run                     # run the queued or failed dreaming runs: read the session, one extraction, checks in code, pending proposals (--session, --at)
uv run kako dream settle                  # carry out each memory Meko extracted from a dreamed session: linked to what a person approved, or deleted (--at)
uv run kako dream check                   # V-14 against Meko: each extracted memory linked, waiting on a pending proposal, or gone; exit 1 if not (--household)
uv run kako meko sync                     # Meko upkeep: a memory per fact, a replaced one rewritten in the past tense, a retracted one's deleted, what was approved for sharing promoted or uploaded (--household, --at; also after each approval)
uv run kako meko check                    # V-13: every link to a memory, promoted memory or document points to one Meko holds, and no upkeep is owed; exit 1 if not (--household)
uv run kako gaps sync                     # Context Gaps: each new weak search in Meko's log as an open gap (Meko Cloud only; local Meko says it has no self-learning tools) (--household)
uv run kako gaps list                     # the gaps, their questions and outcomes (--status open|answered|verified|dismissed|all, --household)
uv run kako gaps answer <gap> <proposal>  # tie a gap to the proposal that answers it (one that writes a fact); `dismiss <gap> --by Jun` closes one
uv run kako gaps verify                   # replay each answered search once its answer is approved and in Meko (selflearning_verify; also after each approval's upkeep) (--gap)
uv run kako dream eval                    # dreaming's labelled set, replayed from data/recorded/dreaming.json; exit 1 under 90% found or on any unquoted number (--only, --household, --save)
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
  `api/app.py` the app and `/api/v1/health` (it answers only to a loopback Host); `api/sessions.py` the session API (start a session, a
  turn in it, one at a time, and its trace); `api/proposals.py` the approvals API (list, approve,
  reject; JSON only; `describe` writes a proposal in plain words); `db/` the engine, the declarative base, the table
  models (`db/models/`, one module per layer of `docs/data-model.md`), every enumerated column's
  values (`db/enums.py`, held as check constraints) and Alembic (`db/migrations/`, append-only once
  merged; `0002_tables.py` creates every table, `0003_fact_guard.py` the trigger that allows only
  the fact status transitions, a non-seed fact only with its approved proposal, and refuses deletes;
  `0004_recommendation_option.py` each recommendation's option and a plan's recommended one;
  `0005_approval_guard.py` the triggers that keep a decided proposal from changing, refuse a decision
  or life event without its approved proposal, and keep decisions, options and assumptions as recorded);
  `db/proposal_store.py` proposals and approvals: `propose` (pending, with evidence, V-09, once per
  idempotency key), `approve` (one or several in one transaction, each exactly its payload, once; again
  changes nothing), `reject` and `list_proposals`;
  `db/fact_store.py` records, replaces and retracts facts and reads snapshots, one transaction per
  write, each exactly what its proposal's payload names (only the seed loader calls
  `record_seed_fact`); `facts/` the pure fact rules (`attributes.py` the attribute catalog, `values.py`
  a value against its attribute, `proposals.py` proposal payloads of every kind, their
  idempotency keys and the check that a write is the one approved, `evidence.py` V-09 (every number a
  proposal writes is in its quotes), `reading.py` numbers read out of text, shared with the number check
  and the test set's scoring, `snapshot.py` snapshots `on` a date and `known_at` a time, `rules.py` V-01 to V-08 and
  V-16); `engine/` the deterministic engine, pure like `facts/` (`engine.py` `compute`: a snapshot,
  the entities and a what-if's overrides in, every figure of docs/data-model.md "Calculations" out,
  each citing what it read; `debts.py` the payoff with the rollover; `arith.py` centavos, half-up
  rounding and ratios; `dates.py` calendar months and the 100-year horizon; `inputs.py` what it
  reads; `figures.py` the figure and the run; `diff.py` F-DIFF-1, what changed between two runs and
  why, and the decisions to revisit); `decisions/`, pure too (`tags.py` the fixed option tags, V-15;
  `assumptions.py` the facts a decision rests on: not balances, savings or allocations). `db/calc_store.py` stores a run with the facts it read and its
  figures, and reads it back; `db/plan_store.py` keeps a turn's what-ifs (a scenario, its overrides,
  its run, and the `agent_step` rows that ran it then name it; the tools write nothing) and the plan
  it proposes (recommendations per option with their sources, reconciliation), in one transaction; `demo/` the demo household (`files.py` reads and checks
  `data/demo-household/`, `load.py` loads it through the fact store, each change as an approved
  proposal and then its write). `planning/reconcile.py` holds the reconciliation rules: the
  specialists' asks together through the engine, over-allocation, opposite moves and missed goal
  dates, and the same rules on one split. `facts/`, `engine/` and `planning/` use no database,
  clock or randomness, which `tests/test_purity.py` checks; `meko/` the only package that talks to Meko
  (`client.py`, a small MCP client over Streamable HTTP whose sessions count tool calls and refuse
  any past their `max_tool_calls` ceiling, 0 by default; `adapter.py`, the one interface for every
  Meko call Kako makes; `mcp.py`, that interface over MCP (`open_meko`); `fake.py`, the same in memory
  for unit tests; `quota.py`, the call counter and quota guard every call goes through;
  `health.py`, the handshake probe; `trace.py`, a session's spans from local Meko's call log).
  `db/meko_log.py` counts the calls in `meko_call` (bound to the session once it exists), and
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
  then only its final tool, every tool call an `agent_step`, and a note from code between rounds),
  `present.py` (what agents see: stable
  refs such as `debt:credit-card`, figures and facts written out as ₱9,050.00, 12 months, Feb 15,
  2028), `brief.py` (`render_brief`, pure: the brief within `KAKO_BRIEF_TOKEN_BUDGET`, people's and
  Meko's words wrapped in `<data>` blocks, and what it drops first when over budget) and
  `brief_store.py` (`gather_brief`: Postgres, then one `context_search`); `answers.py` (what agents
  hand back: allocations with their amount specs, citations, proposals, options), `tools.py`
  (`TurnState` and the agents' tools: `get_figures`, `get_facts`, `get_decisions`, one extra
  `search_memory`, `run_what_if`; amount specs and citations resolved and checked in code),
  `specialists.py` (the four specialists and `submit_proposal`), `orchestrator.py` (`answer_turn`:
  the `ask_*` tools, at most 4 a turn, and `submit_answer`), `reconciling.py` (the orchestrator's
  side of reconciliation: the rules' note on the proposals together, at most 3 splits each checked
  by the rules, and the resolution with the option rejected), `numbers.py` (the number check, V-10:
  every number in a text read out and matched to a figure, fact, what-if allocation or the
  household's words; used by `submit_answer` and `submit_proposal`, one regeneration, then
  flagged) with `checks.py` (what it finds and logs), `ask.py` (a session and its turns, for `kako ask`
  and the API: the session's conversation, the brief, the turn's run stored, the answer, its plan
  and checks stored, the changes the household stated kept as pending proposals, the turn kept in
  Meko with its steps, reasons and ids, and what it cost), `proposing.py` (`propose_change`: a life
  event and the facts it changes, from the household's words, checked in code and held for a yes),
  `replan.py` (pure: a replan's figures before and now, the facts behind them and the decisions to
  revisit, as the agents and the household read them) with `replan_store.py` (the changes a person
  approved from this session's turns, and the run the household last decided on) and
  `prompts/` (the shared rules, then one file per role; every system prompt is the shared rules,
  the brief, then the role), and `single.py` (`answer_alone`, the single-agent baseline: one agent on
  the strong deployment with every read tool, its own what-ifs and search, and the same
  `submit_answer`, prompt `prompts/single.md`). Tool output lists figures in the engine's key order,
  then the debts' payoff order, never by database id (`in_order`), so a recording replays on any
  database. Recorded real runs live in `data/recorded/`, and each is logged in `docs/tuning-log.md`.
  `evals/` the agent test set: `questions.py` reads and checks `data/test-set/questions.toml`,
  `scoring.py` scores one answer against what its question expects (each check named, a failed turn
  0), and `runner.py` runs the set through `ask` for either architecture and reports the score, model
  calls, tokens, cost and Meko calls; `evals/dreaming.py` dreaming's labelled set
  (`data/dreaming/labelled.toml`): each case's expected, maybe and forbidden proposals, the score
  and the cases run through extraction and classification. `dreaming/` the background job after a
  session: `claims.py` (pure: the claims `submit_claims` hands in, checked for shape), `classify.py`
  (pure: each claim against what Kako holds, the quote in its turn, V-09, new, replace, retract,
  correction, same, conflict, refused or deferred, and the proposals it makes), `candidates.py`
  (pure: which memories Meko extracted are candidates, and each one's fate: waiting or
  delete), `extract.py` (the brief and the one structured model call, prompt `prompts/dreaming.md`),
  `job.py` (`end_session` queues a `dream_run`; `run_dream` reads the session's turns from its Meko
  conversation as the agent that wrote them and its extracted memories (`search_memories`),
  extracts, classifies and proposes in one transaction, and marks the run done or failed with why)
  and `memories.py` (`settle_memories` links or deletes each candidate, `check_extracted` is V-14,
  `forgotten` marks one upkeep deleted); `patterns.py` (pure: three choices the same way by option
  tag, across two sessions, none the other way) and `promotion.py` (steps 4 and 5 at the end of each
  run, and promotions also after each approval: `preference_pattern` proposals, and `promote` ones
  for an approved preference or a decision two sessions have held, once ever). `upkeep/` is Meko upkeep: `sentences.py` (a fact as one
  sentence, the past tense once replaced) and `plan.py` (the steps owed: add, rewrite, delete), both
  pure; `sync.py` (`keep_up`: the steps as `kako:upkeep`, each memory changed as the agent that wrote
  it, links in `meko_link` with the text written, at most 60 steps a run, one run per household at a
  time; after each approval, at the end of `kako demo run`, `kako meko sync`), `promote.py` (what was
  approved for sharing: a preference's sentence added and promoted, never twice, or a decision
  record uploaded, each linked), `records.py` (pure: the decision record's Markdown) and `check.py`
  (V-13, promoted memories and documents included). `gaps/` is Context Gaps: `questions.py` (pure:
  which weak searches are a shortfall of coverage, and the question, written by code) and `store.py`
  (`collect_gaps` from Meko's search log, `answer_gap`, `dismiss_gap`, and `verify_gaps`, which
  replays an answered search once its proposal is approved and upkeep has written its facts'
  memories, at most 5 a run, after each approval's upkeep too); the adapter's `logged_searches` and
  `replay_search` raise `SelfLearningUnavailable` on a Meko without the tools (local Meko);
  `api/gaps.py` is `/api/v1/gaps`. `demo/sessions.py` reads the scripted sessions
  (`data/demo-household/sessions/`) and `demo/mode.py` is `kako demo run`: local Meko only, the
  household with its whole story, the documents uploaded once, each session replayed by call key
  (a request that differs from its recording, as when another machine's Meko ranks the brief's
  search results differently, is replayed and reported; `--strict` refuses it), a turn's `approve`
  step approved at its time in the story, and the `changes.csv` rows a session `writes` left out of
  the load and checked after it (`kako demo record` records a session the same way).
  `db/llm_log.py`, `db/agent_steps.py` and `db/number_checks.py` write those three tables, each row
  committed on its own.
- `backend/tests/`: unit tests need nothing running; `tests/integration/` runs only when
  `KAKO_TEST_DATABASE_URL` or `KAKO_TEST_MEKO_URL` is set, and refuses a Meko URL that isn't local.
  `tests/support/data_model.py` reads the tables out of `docs/data-model.md`: `test_schema_doc.py`
  holds the models to it and `tests/integration/test_schema.py` the migrated database (a fresh
  database per test, migrated twice), with the checks the database must refuse.
  `test_reconcile.py` tests the reconciliation rules on the worked example (the asks together,
  over-allocation, opposite moves, missed goal dates, one split), and `test_agents_reconcile.py`
  the what-if loop with a scripted model: session 2's over-allocation caught, splits tried and
  logged, the resolution checked in code and shown with the rejected option. `test_numbers.py`
  tests the number check on session 2's figures (what matches, what fails, rounding,
  multipliers, dates in any common form, spelled-out numbers with a unit, refs, names),
  and `test_agents_numbers.py` in a scripted turn (sent back once, then flagged; every text; the
  specialists'; an answer kept when the model stops). `test_agents_session.py` checks the turn Meko
  keeps (steps, reasons, ids) and which row each final check names; `test_meko_trace.py` reads a
  mocked call log; `test_api_sessions.py` the routes' refusals with no database; and
  `tests/integration/test_session_api.py` is task 6's done-when: a turn through the API on Postgres
  and local Meko leaves the conversation's turn, a plan, recommendations with sources and the
  session's Meko calls as spans.
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
  `test_facts_evidence.py` V-09 on the household's many ways of writing a number, and
  `test_decisions.py` what plan v2 rests on; `tests/integration/test_proposal_store.py` is Phase 4
  task 1's done-when (approving twice changes nothing), with the refusals, a life event and its fact
  approved together, a batch undone by one refused write, decisions that revise and accept plans, and
  migration 0005's guard; `tests/integration/test_proposals_api.py` the API and `kako proposals`.
  `tests/integration/test_meko_smoke.py` creates a conversation, adds a memory, finds it and
  cleans up (at most 6 tool calls).
  `test_model_calls.py` (budgets, the cap, retries, cost and the log), `test_tool_loop.py` (the
  loop's bounds and steps), `test_recorded.py` (a two-agent turn recorded, then replayed with every
  socket refused) and `test_model_sdk_imports.py` (Ruff refuses a model SDK anywhere but the model
  manager) use the scripted model in `tests/support/models.py`, never Foundry;
  `tests/integration/test_agent_logs.py` writes and reads `llm_call` and `agent_step`.
  `test_agent_tools.py` tests the tools on the worked example (amount specs, the rest, refusals,
  citations, one search, proposals), and `test_agents_turn.py` runs session 2 with a scripted model:
  options A and B with the worked example's figures, cited, what each agent was sent, and the
  parallel turn recorded and replayed strictly; `tests/integration/test_agents_turn.py` runs the same
  turn on the demo household in Postgres and local Meko (the brief's search and a specialist's), and
  `tests/integration/test_ask.py` records a turn through `ask` and replays it with `kako ask`, with
  every text's `number_check` row against the stored run, and a planted wrong number regenerated and
  logged.
  `test_evals.py` holds every expected number in the test set to the engine and scores session 2's
  scripted turn and the single agent's; `test_dreaming_classify.py` tests the classification on the
  worked example (each outcome, V-09, corrections, repeats within a session) and
  `test_evals_dreaming.py` the labelled set: a careful extraction (`tests/support/dreaming.py`) finds
  every case exactly, the scoring, broken files, the brief, and the one structured call with a wrong
  shape sent back once; `tests/integration/test_dreaming.py` ends a session and dreams over it on
  Postgres and local Meko (proposed once with its quote and speaker, approved with source `dreaming`,
  what the session proposed already reported, a failed run run again, the labelled set, the CLI from
  a recording, the API); `test_dreaming_candidates.py` which memories are candidates and each
  fate, and `tests/integration/test_dreaming_memories.py` the candidates on local Meko: shown to
  extraction, one linked after approval, one deleted after rejection, the rest deleted, Kako's own
  untouched, Meko's words never a quote for V-09, and `kako dream settle` and `check`;
  `test_upkeep.py` the sentences and the plan, and `tests/integration/test_upkeep.py` upkeep on the
  demo household in a throwaway datapack (every fact kept, Mara's old salary in the past tense after
  her new job, a retraction, Meko's words deleted once replaced, `kako meko sync` and `check`);
  `test_gaps.py` which searches are asked about and the question, the fake's search log and replay,
  and `McpMeko` reading Meko's self-learning answers (nested or flat, refused when unreadable, a
  missing tool said plainly); `tests/integration/test_gaps.py` a search that found nothing going
  from low to `improved` with both scores stored once its answer is approved through the API, a
  replay waiting for upkeep and for indexing, at most 5 a run, the refusals, a Meko with no
  self-learning, and `kako gaps` on local Meko;
  `test_promotion.py` patterns, promote payloads, decision records and the fake's promotion, and
  `tests/integration/test_promotion.py` the demo household's three decisions: the pattern proposed
  once, the offers, a no that is final, the second confirmation through the API and the command
  line, upkeep sharing on the fake and on local Meko in a datapack of its own (never twice after a
  stopped run), V-13, and the brief's promoted marker as known at a time; `test_demo_sessions.py` the session files and each mistake;
  `tests/integration/test_demo_mode.py` runs `kako demo run --test-set` on a fresh database and local
  Meko with no Azure settings, then again (session 4 isn't replayed twice), and its refusals, session 4
  recorded from the scripted model with its approval and the rows it writes, and `kako demo record`'s
  refusals; `test_agents_proposing.py` tests `propose_change` on the worked example (held, and each
  refusal a model could cause), and `tests/integration/test_replan.py` runs session 4 with a scripted
  model on Postgres, through `run_turn` and through the API: the new job proposed, approved, then the
  replan in three parts with the September decision to revisit; `test_agent_tools.py` also checks that
  tool output doesn't change when the entities' ids sort the other way.
  `test_brief.py` builds the worked example's brief in memory (under budget, with the approved
  preference; Meko results wrapped; trimming in order), and `tests/integration/test_brief_store.py`
  gathers it from the demo household in Postgres and local Meko, with its one search counted.
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
