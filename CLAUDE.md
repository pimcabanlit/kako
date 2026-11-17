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

## Conventions

- Two-space indentation, LF line endings.
- Never commit secrets, API tokens, or `.env` files.
- Ship in small PRs, base files first, then the toolkit, then CI.

Commands and code layout are added here as the code arrives.
