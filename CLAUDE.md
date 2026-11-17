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
