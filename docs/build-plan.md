# Build plan

How Kako gets from docs to a ContextCon 2026 submission: what is already decided, the order of work
with a test for when each task is done, the risks and their fallbacks, the demo video and the
submission checklist.

- **Submission deadline:** Sun **Jan 17, 2027, 11:59 PM Pacific** (Mon Jan 18, 3:59 PM Manila).
  **Feature freeze Jan 10; submit Sat Jan 16** (Manila).
- **Judging:** Jan 18 to 24, 2027. The demo datapack and its artifacts must still be there.
- **Shared time:** Qorren (Codegeist) comes first until its submission on Dec 21, so Kako runs light
  until then: docs, CI, the engine. Full time from Dec 22.
- **Where it stands (Nov 17):** the base files, concept, ContextCon summary, Meko toolkit, these docs
  and `REVIEW.md` are merged (PRs #1 to #6). The plan was questioned against the brief, the judging and
  Meko's own docs (playbook Stage 5), and the answers are written in below. Phase 1 is next.

What Kako does is in [concept.md](concept.md). How it is built is in [architecture.md](architecture.md).
Every table and formula is in [data-model.md](data-model.md). How each ContextCon criterion is met is in
[requirements-map.md](requirements-map.md). Dates and rules are in [contextcon-2026.md](contextcon-2026.md).

## Decisions already made

| Topic | Decision |
| --- | --- |
| Name | **Kako**. "Myrqen", "Sank" and "Plankeeper" in older notes are the same app |
| Challenge | Challenge 05, The Planner That Remembers. Target prizes: Grand prize and Best use of shared memory |
| The one rule | The engine calculates, the agents explain and propose, the household decides |
| Household | One synthetic Philippine family (the Villanuevas), in pesos, explained in plain terms. No real data |
| Areas | Budget, debt, savings, goals. Tax is knowledge-base reference only, never calculated |
| Stack | FastAPI on Python 3.12 (uv, Pydantic v2, SQLAlchemy 2 async, Alembic, ruff, mypy, pytest); Next.js App Router with TypeScript strict, Tailwind and shadcn/ui |
| Model | **Azure AI Foundry** (OpenAI model deployments), signed in with Entra ID, from one model-manager module; Kako's own resource group and budget. Deployment names live in settings only (Pim, Nov 17) |
| The honest line | "Kako's agents investigate, try what-ifs and propose. The engine checks every figure. The household decides." The orchestrator and specialists are agentic; dreaming is a fixed workflow with one model step |
| Meko's own extraction | Meko Cloud extracts memories from what the household says. Dreaming treats them as candidates; each ends linked to an approved fact or deleted |
| The laptop | Runs only the backend and web app, natively on Windows, for the video. No Docker or WSL; development and tests run in cloud sessions and CI |
| Demo mode | One command, local Meko, recorded model responses: judges can run the scripted sessions with no Azure account. Live mode needs a Foundry deployment |
| Pro access | Not pursued (Pim, Nov 17). Designed for Free; per-person privacy stays a stretch goal |
| Agents | One orchestrator calls four specialists as tools and reconciles them in the open. No other agent framework |
| History | Every fact carries `valid_from`, `valid_to` and `replaced_by`; changes replace, mistakes are retracted, nothing is deleted ([data-model.md](data-model.md)) |
| Store of record | Postgres holds the household and its fact history; Meko holds conversations, memories, shared knowledge, documents, artifacts and traces, linked by `meko_link` |
| Dreaming | A background job after each session proposes; a person approves. In-session, the orchestrator can propose what the household just said, so a life event replans at once |
| What-ifs | Computed by the engine in memory. Keeping one as an AMP branch is a Should, made ahead of time |
| Meko environments | Local Meko for development, tests and CI; Meko Cloud for the demo datapack only |
| Demo (Pim, Nov 17) | **Video recorded from the laptop** against the Meko Cloud demo datapack. No hosted app: the rules don't say judges run it, and a hosted backend would need a fixed outgoing IP for AMP and could add cost. Judges get the video, the README and the metrics |
| Licence | All rights reserved: viewing and evaluation only, including by the ContextCon 2026 judges |

## Phases

Each task has a **Done when** line: the check that proves it. A phase is done when every task in it is.

### Phase 1: Foundations (Tue Nov 17 to Sun Nov 29, alongside Qorren)

1. **Docs and decisions.** These four docs, reviewed and merged.
   Done when: the docs PR is merged and `CLAUDE.md` lists them as the source of truth.
2. **CI against local Meko.** A GitHub Actions workflow that installs the pinned Meko release from
   GitHub, starts it, runs a Postgres service, and runs lint, type check and tests. It never touches
   Meko Cloud.
   Done when: a pull request shows the check green, including a smoke test that creates a conversation,
   adds a memory and finds it.
3. **Backend skeleton.** `backend/` with uv, FastAPI, settings, the Alembic baseline, and
   `/api/v1/health` reporting Postgres and Meko.
   Done when: `uv run pytest` passes and the health route shows both reachable locally.
4. **Web skeleton.** `web/` with Next.js, the `/api/v1` rewrite and a page that shows the health route.
   Done when: `npm run build` passes in CI and the page shows "Postgres ok, Meko ok" locally.
5. **Azure AI Foundry.** Kako's own resource group, a Foundry project with a stronger and a faster
   pay-per-token deployment, Entra ID sign-in (no keys), a monthly budget with alerts, and a
   `check-models` command that makes one tiny call per deployment. Recorded in the setup log.
   Done when: `check-models` passes from a cloud session and from the laptop.
6. **Spikes.** Answer each in a setup log, `docs/meko-setup.md`, with what was run:
   - **AMP on our account:** create a database with an `ingress_external` endpoint, connect from the
     laptop, time a snapshot query, time a branch, read the vCPU cap.
   - **Meko Cloud from the backend:** does the MCP endpoint accept an API key from a server process?
   - **Self-learning tools** (Context Gaps): are they available to a Free account on Meko Cloud? Does
     `selflearning_verify` report `improved` after a missing fact is added?
   - **Meko Cloud's own extraction:** can it be turned off on a Cloud datapack? How soon after a turn do
     extracted memories appear, and with what `source` and metadata?
   - **Traces:** can Kako link straight to a session's trace, and does `conversation_get` return each
     turn's `plan` and `reasoning`?
   Done when: each question has an answer, or a fallback chosen, in the setup log.

### Phase 2: Facts and engine (Mon Nov 30 to Sun Dec 13, alongside Qorren)

1. **Schema.** Alembic migrations for every table in the data model.
   Done when: a fresh database migrates, a second run changes nothing, and the schema test compares the
   tables and columns with [data-model.md](data-model.md).
2. **Fact store.** The attribute catalog, replace and retract, the trigger that rejects other updates,
   and snapshots `on` a date and `known_at` a time.
   Done when: tests cover each status transition and rules V-01 to V-08.
3. **Engine.** Every formula in the data model, pure, in centavos.
   Done when: a test reproduces every figure of the worked example exactly, and property tests hold
   (for example, payments made equal the starting balance plus interest).
4. **Plan diff.** F-DIFF-1 between two runs, with each change labelled.
   Done when: the worked example's diff (plan v2 to v3) comes out as written.
5. **Demo household.** `data/demo-household/` and the import that loads it.
   Done when: the import loads it into an empty database, the validation suite passes, and the figures
   match the worked example.
6. **Meko adapter.** The interface, the MCP implementation, an in-memory fake, the call counter, and
   the knowledge-base upload of the demo documents.
   Done when: the adapter's integration tests pass against local Meko in CI.

### Phase 3: Agents (Mon Dec 14 to Sun Dec 27; full time from Dec 22)

1. **Model manager.** The only module that imports a model SDK (OpenAI against Azure AI Foundry, Entra
   ID): retries, the per-turn budget and daily cap, `llm_call` logging with cost, `agent_step` logging,
   and recorded responses for tests and demo mode.
   Done when: a lint check fails if any other module imports the SDK, and recorded responses replay a
   turn with no network.
2. **Brief builder.** The brief within its token budget, with one `context_search`.
   Done when: a test shows the brief for the worked example under budget and containing the promoted
   preference.
3. **Specialists and orchestrator.** Prompts, tools and structured proposals.
   Done when: the session-2 question ("how hard should we pay down the card?") produces options A and B
   with the worked example's figures, cited.
4. **Reconciliation and the what-if loop.** The rules, up to 3 splits tried through the engine, and the
   recorded resolution.
   Done when: an over-allocation on the worked example is caught, at least one split is tried and logged
   as an `agent_step`, and the resolution is shown with the rejected option.
5. **Number check.** V-10 over every text, with one regeneration.
   Done when: a test with a planted wrong number is caught, regenerated, and logged in `number_check`.
6. **A turn end to end.** The session API, the Meko turn with `plan`, `reasoning` and ids.
   Done when: one turn on local Meko leaves a conversation turn, a plan, recommendations with sources,
   and a trace with the session's Meko calls as spans.
7. **Agent test set.** About 20 household questions with the figures and sources a good answer must use,
   kept in the repository with how each answer is scored.
   Done when: the set runs in one command and reports a score, kept on the metrics page.
8. **Single-agent baseline.** The same test set against one all-in-one agent with the same tools.
   Done when: both scores and call counts are written up; if the specialists don't score better, the
   architecture doc says so.
9. **Demo mode.** One command: local Meko, a local database with the demo household, recorded responses.
   Done when: a fresh clone runs session 4 in demo mode with no Azure settings.

### Phase 4: Memory over time (Mon Dec 28 to Sun Jan 3)

1. **Proposals and approvals.** The API and the rules (V-08, V-09), with idempotency keys.
   Done when: approving a proposal twice changes nothing the second time.
2. **Life-event replan.** In-session proposals, approval, what the event touches, the new plan, the diff
   and the decisions to revisit.
   Done when: the worked example's session 4 runs end to end on local Meko and shows the three-part
   answer (new plan, what changed, why).
3. **Dreaming.** The job, extraction, Meko's extracted memories and Learnings as candidates, the checks
   in code and the classification.
   Done when: the labelled set of scripted sessions scores at least 90% of expected proposals found and
   no proposal with a number that is not in its quote; and every extracted memory ends linked or deleted
   (V-14).
4. **Patterns and promotion.** Option tags, the preference pattern, and promotion with a second
   confirmation: a preference to collective memory, a decision record to shared knowledge.
   Done when: after sessions 1 to 3 (Mara in some, Jun in others) dreaming proposes the flexibility
   preference; after approval and promotion the debt specialist cites it in session 4 without being
   told.
5. **Meko upkeep.** Add, rewrite in the past tense, delete on retraction, promote, and `meko_link`.
   Done when: after the four sessions, memory search for "Mara's salary" returns the current value and
   the old one in the past tense, and the validation suite's link check passes.
6. **Context Gaps** (a Must if the Phase 1 spike found the tools). Shortfalls become `context_gap` rows
   and questions for the household; an approved answer is followed by `selflearning_verify`.
   Done when: one weak search in the demo household goes from Mid or Low to `improved`, with both scores
   stored.

### Phase 5: Screens and demo (Mon Jan 4 to Sun Jan 10, feature freeze)

1. **Session screen** with approval cards inline, and the **agents' steps** for each turn: every
   specialist's tool calls, the what-ifs it tried, and what was rejected and why.
2. **Plan screen** with "why" on each recommendation (figures with their formula and facts, memories,
   decisions, documents, the Meko trace) and "what changed" against the last plan.
3. **Timeline and decisions.** Facts over time with their windows, replaced and retracted values, life
   events; decisions with rejected options and "to revisit".
4. **Metrics page.** Meko `datapack_metrics`, tokens, cost and seconds per turn (average and worst
   case), brief size against the whole context, number-check pass rate, dreaming score, agent test-set
   score against the single-agent baseline, the session-4 answer scored with and without the promoted
   preference, and Context Gaps before and after scores.
5. **Demo datapack on Meko Cloud.** Seed sessions 1 to 3 through the real flow once; rehearse session 4.
   Done when: a full rehearsal runs on Meko Cloud and the call counter shows the allowance left.
6. **Shoulds, if time:** a what-if kept as an AMP branch; the specialist conflict drawn on screen.
Done when (for 1 to 4): each screen has empty, loading and error states and works on the seeded
household without demo-only code paths.

### Phase 6: Video and submission (Mon Jan 11 to Sat Jan 16)

1. **Video** under 5 minutes, following the storyboard.
2. **README** with setup instructions for demo mode (no Azure account; scripted sessions only) and live
   mode (a Foundry deployment), architecture, how Kako uses Meko, the measured metrics, the test sets'
   scores with their run dates, and a plain privacy note: one shared household datapack today,
   per-person privacy as the production path (needs Meko Pro).
3. **Final checks** against the submission checklist in [contextcon-2026.md](contextcon-2026.md), and
   the full terms once published (licence, open-source requirement).
   Done when: submitted on Jan 16, with the confirmation saved.

## Stretch goals

Only after the Must and Should items work end to end.

- **Counterfactual from a past fork:** "what if we had chosen option A in September?", replayed from a
  `known_at` snapshot.
- **Per-person privacy:** each adult's private memories and shared household knowledge (needs Meko Pro).
- **Behaviour drift:** spending that drifts from a stated goal, noticed by dreaming.

## Risks

| Risk | Effect | Fallback |
| --- | --- | --- |
| Qorren overlaps until Dec 21 | Less time for Kako's agents | Engine and facts first, which need no model; agents from Dec 22 |
| Meko Free-tier lifetime allowances | Rehearsals use up searches on Meko Cloud | Local Meko for everything but the demo; the call counter's ceiling; one seeding run |
| AMP unavailable, slow, or the laptop's home IP changes | The structured data can't live in the datapack, or the allow-list breaks before recording | Neon (free Postgres); AMP named as the next step in the docs. Check the allow-list on the day of recording |
| Meko Cloud MCP needs OAuth for a server | The backend can't reach the demo datapack | Ask on Discord; run the demo backend on the laptop with the user's sign-in |
| Dreaming proposes wrong facts | Trust in the memory story | Code checks quotes and numbers; everything needs approval; the labelled set measures it |
| Model spend | Cost | Per-turn budget, daily cap, prompt caching, recorded fakes in tests |
| Meko releases change behaviour | Tests or the demo break | Pin the tested release in CI and the cloud setup; upgrade on purpose |
| Developing on Windows | Local Meko runs on Linux and macOS only | Develop and test in cloud sessions and CI; the laptop only runs the backend and web app for the video, natively |
| Meko Cloud extracts memories before approval | Unapproved or stale facts in the demo datapack | Dreaming treats them as candidates (V-14); the Phase 1 spike checks whether extraction can be turned off |
| Self-learning tools off on our account | Context Gaps can't be shown | The Phase 1 spike decides; if off, it drops back to the production path and the docs say so |
| Azure spend | Cost | Kako's own resource group with a monthly budget and alerts; pay-per-token deployments only; recorded responses in tests and demo mode |
| Demo artifacts expire after 30 days unused | Judges find a missing plan report | Touch the demo datapack before judging; keep the reports in the repo too |

## Video storyboard

Under 5 minutes. Not financial advice, synthetic data, said on the first screen.

1. **The problem (0:00 to 0:30).** Planning is a long relationship; assistants forget, and memories that
   only pile up don't know what's current. On screen: Meko on its own returns both ₱100,000 and ₱120,000
   for Mara's salary; then Kako answers "₱120,000 since Dec 1, replaced ₱100,000". "Meko remembers what
   you said. Kako works out which of it is still true, and asks you."
2. **The household (0:30 to 1:00).** The Villanuevas, three past sessions, the timeline.
3. **Memory that carries over (1:00 to 1:50).** The September decision with the option they rejected;
   October; dreaming proposes "they value flexibility", the household approves and promotes it.
4. **The life event (1:50 to 3:30).** Mara's new job: the approval card, the old salary closed and
   replaced, the new plan, what changed, and why: the debt specialist citing the promoted preference it
   was never told about, and the conflict with the savings specialist resolved in the open.
5. **Trace and numbers (3:30 to 4:20).** The agents' steps for the turn (the what-ifs tried and the one
   rejected); "why" on one recommendation down to the facts and the Meko trace; the number check; the
   metrics page.
6. **Close (4:20 to 4:50).** How Kako uses each part of Meko, in one slide.

## Submission checklist

The checklist in [contextcon-2026.md](contextcon-2026.md#submission-checklist) is the authority. Kako adds:

- [ ] Demo datapack seeded on Meko Cloud, artifacts touched within 30 days of judging
- [ ] Metrics page numbers copied into the README with the date measured
- [ ] Requirements map updated, every row's status true
- [ ] No secrets, real names or real data in the repository

## Open questions

| Question | Who | By |
| --- | --- | --- |
| Can Meko Cloud's extraction be turned off on a datapack? | Phase 1 spike | Phase 1 |
| AMP on Free: limits and connectivity | Phase 1 spike | Phase 1 |
| Full terms: licence or open-source requirement | ContextCon page | Before submission |
| Final Demo Day date (likely US hours) | ContextCon page | January |
