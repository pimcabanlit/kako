# Kako: notes for Claude

Kako is a household financial planner built for ContextCon 2026, Challenge 05.
Working dates (Manila time): feature freeze Jan 10, 2027, submit Jan 16, deadline
Jan 18, 3:59 PM. Check the official ContextCon rules before any decision that
touches eligibility or submission. See README.md for the concept.

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

Kako is built on Meko, the context and memory platform behind ContextCon. Use
these sources for any Meko fact before writing code against it:

| Need | Use |
| --- | --- |
| Memory, datapack and knowledge-base calls (`memory_search`, `datapack_search`, `knowledgebase_search`, AMP Postgres) | **Meko MCP server**: local Meko for dev and tests (`meko agent connect claude` registers it), Meko Cloud at `https://mcp.mekodata.ai/mcp` for the demo only |
| How to use the MCP tools, picking a datapack | Meko's agent skills (`meko-mcp-tools`, `meko-select-datapack`) from [yugabyte/meko-skills](https://github.com/yugabyte/meko-skills), plugin `meko-agent-skills` |
| The `meko` and `meko-cli` commands, local server, REST API | [yugabyte/meko](https://github.com/yugabyte/meko) README and `src/meko/docs/` |
| Product docs, MCP reference, limits | [docs.mekodata.ai](https://docs.mekodata.ai/) (MCP server: `/reference/mcp-server/`), [pricing](https://mekodata.ai/pricing/) |
| Questions to the Meko team | [Meko Discord](https://mekodata.ai/discord/) |

Rules:

- If the Meko MCP server or skills are not loaded in a session, say so before writing
  Meko code instead of guessing.
- Free tier: 1,000 conversations account-wide. Every session, test run and evaluation
  uses one, so never point tests or experiments at Meko Cloud.
- Meko auth comes from `meko cloud-link` or a Meko Cloud API key in the environment.
  Never ask for, print or commit tokens.
- The plugin and MCP wiring (`.claude/settings.json`, `.mcp.json`) arrive in the toolkit
  PR; update this section then with the exact install steps.

## Conventions

- Two-space indentation, LF line endings.
- Never commit secrets, API tokens, or `.env` files.
- Ship in small PRs, base files first, then the toolkit, then CI.

Commands and code layout are added here as the code arrives.
