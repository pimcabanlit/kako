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
  as a background job after each session. Claude via the Anthropic API from FastAPI;
  Next.js frontend.
- Meko Cloud holds the demo only; development and tests run against local Meko.
  Household data goes in AMP (Postgres in the datapack) if the Phase 1 test passes,
  otherwise plain Postgres.
- The demo household is a synthetic Philippine family, explained in plain terms:
  pesos, with 13th-month pay, SSS and Pag-IBIG as knowledge-base documents. No real data.
- One shared household datapack first. Per-person privacy is a stretch goal.
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
HTTP endpoint with `mcp-remote`. That also restarts Meko in a resumed container. Keep the
version in step with the one tested below.

```
# Kako: local Meko + Meko's Claude Code plugin, at user scope (sessions start above the repos).
# Registers the meko server FIRST, so it is in Claude Code's config before Claude Code reads it.
# The server command waits for the meko binary, starts Meko, then bridges stdio to HTTP.
if [ -d kako ]; then
  claude mcp remove --scope user meko || true
  claude mcp add --scope user meko -- sh -c 'for i in $(seq 40); do [ -x "$HOME/.local/bin/meko" ] && break; sleep 1; done; "$HOME/.local/bin/meko" start >/dev/null 2>&1; exec npx -y mcp-remote@0.16.6 http://127.0.0.1:7777/mcp --allow-http' || true
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
expected and keeps build sessions off Meko Cloud.

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
- Ship in small PRs: base files, docs, toolkit, then the doc set and CI.

Commands and code layout are added here as the code arrives.
