# REVIEW.md: instructions for the AI reviewer

Kako is a household financial planner for ContextCon 2026, Challenge 05. A deterministic engine
computes every peso figure from a history of household facts that is never overwritten; an
orchestrator and four specialist agents (budget, debt, savings, goals) explain and propose; the
household approves. Meko holds the conversations, memories, shared knowledge, documents and traces;
Postgres holds the household and its fact history. Read `CLAUDE.md` (decisions already made),
`docs/concept.md`, `docs/architecture.md` and `docs/data-model.md` first. Review the diff against
them. Be short and specific.

Judges watch the video and read this public repository: the README, the setup steps and the code.
Every figure on screen has to be traceable to code, and nothing in the repo may be real household
data. Many rules below exist for that reason.

## Report as Important

These are the failures that matter here. Any instance is **Important**, never a nit.

1. **Secrets.** `MEKO_API_KEY`, `KAKO_ANTHROPIC_API_KEY`, an Azure client secret, Foundry key or access token, a database URL
   with a password, a Meko token or any other key in code, config, tests, demo data, docs, screenshots or workflow files;
   `.gitignore` loosened for `.env*`; a secret, a full request header or a Meko token written to a
   log.
2. **A model produces a number.** A peso amount, rate, month count, date or share that comes from
   model output instead of the engine or a stored fact; maths done in a prompt or by an agent; a
   model call inside `engine/`; the number check (V-10) bypassed, weakened or skipped for any text
   shown to the household; dreaming writing a number that is not in its quoted evidence (V-09); an
   engine test deleted or its expected figure loosened.
3. **A fact is overwritten or deleted.** An `UPDATE` to a fact's value, or a `DELETE` of a fact,
   decision, life event or proposal; a change stored as an edit instead of a replacement; a mistake
   deleted instead of retracted; the trigger that blocks updates and deletes dropped or weakened;
   `valid_from`, `valid_to`, `replaced_by` or `recorded_at` left unset; a code path that breaks rules
   V-01 to V-08.
4. **Knowledge without a yes.** A fact, life event, decision, preference or Meko promotion that
   becomes active, shared or promoted without an approved proposal; an agent tool that writes
   anything other than a pending proposal; promotion without its second confirmation; approval
   applied to a different proposal or value from the one approved.
5. **Untrusted text steers an agent.** Session text, memories, knowledge-base documents, statements
   and dreaming input are written by people or by models. Report a path where that text is placed
   in a prompt as instructions rather than wrapped as data, where a tool's inputs come from model
   output without server-side validation, or where an agent gains a tool that writes.
6. **Wrong or non-deterministic money.** Money as a float anywhere (it is `BIGINT` centavos); rates
   not stored as fractions; rounding done before the last step or in more than one place; engine
   output that can change between runs on the same snapshot (the system clock, unseeded randomness,
   results that depend on row order without `ORDER BY`); household dates read from the system clock
   instead of `household.as_of_date`; timestamps not in UTC.
7. **Untraceable advice.** A recommendation without a figure source and a non-figure source (V-11);
   a figure stored without its calculation run, formula and the facts it read; a "why" or "what
   changed" view that shows a value it can't trace to stored rows.
8. **Postgres integrity.** A schema change outside Alembic, an edit to a merged migration, or a
   destructive migration (drop, narrowing type, rename) without a stated way back; a missing foreign
   key, unique key or check constraint the data model lists; SQL built from strings (f-strings,
   `+`, `%` formatting) instead of bound parameters; a multi-step write that can leave half-written
   state without a transaction.
9. **Meko misuse and quota.** A Meko call outside the `meko/` adapter; a call that skips the call
   counter or the quota guard; tests, CI or development pointed at Meko Cloud instead of local Meko;
   a loop or retry that can call Meko without a bound. Meko Free-tier allowances (1,000
   conversations and 1,000 of each search) are lifetime and account-wide: using them up loses the
   demo.
10. **Model spend.** A provider SDK (Anthropic, OpenAI, Azure AI or Azure identity for models) imported
    anywhere except `agents/model_manager.py`; a model or deployment name written outside settings;
    key-based auth to Foundry instead of Entra ID; Claude's key read from anything but
    `KAKO_ANTHROPIC_API_KEY`, or the SDK left to find a key or base URL in the environment; a model call with no token budget, in an unbounded loop, or with an
    uncapped retry; the per-turn budget or daily cap removed or raised without saying so; a unit test
    that calls the real API instead of the recorded fake.
11. **Real or unsafe data.** A real person, bank, employer, account number or statement in demo data,
    tests, docs or screenshots; amounts sampled from someone's real finances; investment product
    picks or tax calculations (tax is knowledge-base reference only); the README, or a money, plan,
    timeline, decisions, metrics or system check screen, that drops the "synthetic data, not
    financial advice" line (the chat screens leave it out: Pim, Nov 25).
12. **Demo-only code paths.** A household, person or entity ID, a name like "Mara", a peso amount or a
    date written into logic instead of read from data or settings; code that branches on the demo
    household; a screen that works only with the seeded data. Seed data itself is fine, inside
    `data/demo-household/`.
13. **Docs that lie.** `CLAUDE.md`, `README.md`, `REVIEW.md` or a doc in `docs/` stating commands,
    modules, tables, columns, formulas, rules, decisions or checklist items that the diff makes
    untrue; a schema change without the matching `docs/data-model.md` change; a requirements-map row
    whose status the diff changes but doesn't update.
14. **Dependencies and license.** Changes to `pyproject.toml`, `uv.lock`, `package.json` or a lockfile
    not asked for in the PR; a new framework, agent framework, external service, model provider or
    paid plan not flagged; code copied in from elsewhere (including from Pim's other projects), or a
    license file added or changed (the repo is all rights reserved: viewing and evaluation only).
15. **Swallowed errors.** A bare `except`, `except Exception: pass`, or a `.catch()` that drops an
    error without showing it or logging it. A plan computed from partial data looks like good advice.
    A deliberate ignore needs a comment saying why.

## How to report

- Every finding gives `file:line` evidence and one sentence on the input or sequence that makes it
  fail. Don't infer a bug from a name.
- At most **3 nits** per review. Skip formatting and style that `ruff` or ESLint already enforce.
- Never repeat a finding already posted on this PR. A mistake made in several places is **one**
  finding listing every location.
- A bug that exists on the base branch and is not made worse by the diff is labelled
  **Pre-existing**. Report it, but it does not block the PR.
- Agent behaviour and anything that needs Meko Cloud can't be fully tested in CI. If the diff changes
  a prompt, an agent's tools, dreaming, or the Meko adapter, check the PR says it was run on local
  Meko (and the agent test set, once it exists), with the score. If not, that is Important.
- Don't restate what the diff does; the author knows.

## Skip

Lock and generated files (`uv.lock`, `package-lock.json`, `node_modules/`, `.next/`, `.venv/`,
`dist/`, `build/`, `coverage/`) and recorded model fakes. Read demo data only to check it for
secrets and real data (rules 1 and 11) and for IDs or values that logic depends on (rule 12).

## Risk tiers

The tier is set by what the change touches, not by who wrote it. The **highest tier touched wins**.
When unsure, go **one tier up**. Every PR states its tier and the file that set it. Some paths below
don't exist yet; the tier follows what the code does, wherever it lands.

| Tier | What the change touches | Pim before merging |
|---|---|---|
| **High** | The engine and its tests; the fact store (replace, retract, snapshots); Alembic migrations and database models; the number check; agent prompts, tools and `model_manager.py`; dreaming and approvals; the Meko adapter and quota guard; settings that hold budgets or caps; `pyproject.toml`, `package.json` and lockfiles; `.github/workflows/`; `.claude/`, `.mcp.json`; `.gitignore`, `.env.example`, `LICENSE` | Read the whole diff and the pasted evidence, and run `/security-review`. A prompt, tool, dreaming or adapter change also needs a run on local Meko, with the result in the PR. |
| **Medium** | `CLAUDE.md`, `REVIEW.md`, `README.md`, `docs/` (including the data model), other API routes, read-only views, the web app, demo data, tests | Read the summary, the evidence and the review findings. A screen change needs a screenshot. |
| **Low** | Wording-only doc fixes (typos, links), comments, new tests that touch no code under test | Merge on green CI. |

`CLAUDE.md` and `REVIEW.md` are never below Medium. Deleting an engine test or loosening its expected
figure is High.

## Summary

Start the summary with the risk tier, the file that set it and the count, for example
`High (backend/src/kako/engine/debt.py) · 2 Important, 1 nit`, then the findings. If there are none,
write exactly `No issues found.` after the tier.
If the PR states a lower tier than the table gives, say so first, with the file that sets it.
