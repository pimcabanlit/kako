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
  Meko's own docs (playbook Stage 5), and the answers are written in below. Phase 1: CI against local
  Meko, the backend and web skeletons are merged (#8 to #11); Azure AI Foundry is set up and
  `check-models` passes from a cloud session and the laptop (docs/azure-setup.md); the Meko spikes
  are answered (docs/meko-setup.md). Phase 2: the schema (#15), the fact store (#16), the engine and
  the plan diff (#17), the demo household and the Meko adapter are built and tested, each in its own
  PR. Phase 3 is next.

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
   Built Nov 24: `kako test-set` scores 22 questions; each run's results are kept in
   `data/test-set/results/`, which the metrics page (Phase 5, task 4) reads.
8. **Single-agent baseline.** The same test set against one all-in-one agent with the same tools.
   Done when: both scores and call counts are written up; if the specialists don't score better, the
   architecture doc says so.
9. **Demo mode.** One command: local Meko, a local database with the demo household, recorded responses.
   Done when: a fresh clone runs session 4 in demo mode with no Azure settings.
   Built Nov 24 with session 2 and the agent test set (`kako demo run`). Session 4 joined with the
   life-event replan (Phase 4, task 2), and the fresh-clone check was run again with it.

### Phase 4: Memory over time (Mon Dec 28 to Sun Jan 3)

1. **Proposals and approvals.** The API and the rules (V-08, V-09), with idempotency keys.
   Done when: approving a proposal twice changes nothing the second time.
   Built Nov 24: `db/proposal_store.py` (propose with V-09 and the idempotency key; approve one or
   several together, exactly once; reject), the payloads of every kind, the facts a decision rests
   on, the guard in migration 0005, `/api/v1/proposals` and `kako proposals`.
2. **Life-event replan.** In-session proposals, approval, what the event touches, the new plan, the diff
   and the decisions to revisit.
   Done when: the worked example's session 4 runs end to end on local Meko and shows the three-part
   answer (new plan, what changed, why).
   Built Nov 24: `propose_change` (`agents/proposing.py`) holds the household's stated change as
   pending proposals, checked in code (the quote, V-09, the entity and attribute, the value it
   replaces); once a person approves, the session's next turns replan as of the change's date against
   the decision last made (`agents/replan.py`, `agents/replan_store.py`: F-DIFF-1 and the decisions to
   revisit), and the answer has three parts. Session 4 is recorded on Foundry (tuning log entry 9) and
   plays in `kako demo run`: Mara's news, her approval at its time in the story (which writes
   changes.csv rows 10 and 11), and Jun's question answered as the replan.
3. **Dreaming.** The job, extraction, Meko's extracted memories and Learnings as candidates, the checks
   in code and the classification.
   Done when: the labelled set of scripted sessions scores at least 90% of expected proposals found and
   no proposal with a number that is not in its quote; and every extracted memory ends linked or deleted
   (V-14).
   Built Nov 24 (first part): ending a session (`POST /api/v1/sessions/{id}/end`, `kako dream end`)
   queues a `dream_run`; `kako dream run` reads the session's turns from its Meko conversation, makes
   one structured extraction call (`dreaming/extract.py`, `submit_claims`, no other tools), then checks
   every claim in code (`dreaming/claims.py`, `dreaming/classify.py`: the quote is in the turn, V-09,
   the entity and attribute, new, replace, retract, correction, same, conflict) and holds what is new as
   pending proposals with their quotes. A change the session already proposed is reported, not proposed
   again. The labelled set (`data/dreaming/labelled.toml`, 13 sessions, 15 expected proposals) scores
   100% with a careful scripted extraction and no unquoted number; the real Foundry run and its
   recording come next.
   Built Nov 24 (second part): the memories Meko extracted from the session (its Learnings, memories
   waiting to be kept or promoted) are read as candidates, shown to extraction as noted memories, and
   each settles to linked or deleted (`dreaming/candidates.py`, `dreaming/memories.py`,
   `kako dream settle`); `kako dream check` is V-14, and passes on local Meko after approval and after
   rejection.
   On Foundry (tuning log entries 10 and 11): 13 of 15 found on the first run, then 15 of 15 (100%),
   none wrong or unquoted, after the prompt said a change of mind isn't a correction.
4. **Patterns and promotion.** Option tags, the preference pattern, and promotion with a second
   confirmation: a preference to collective memory, a decision record to shared knowledge.
   Done when: after sessions 1 to 3 (Mara in some, Jun in others) dreaming proposes the flexibility
   preference; after approval and promotion the debt specialist cites it in session 4 without being
   told.
   Built Nov 24: `dreaming/patterns.py` counts the household's decisions by the tags of the option
   chosen, and each dreaming run (steps 4 and 5, `dreaming/promotion.py`) proposes a new pattern as a
   `preference_pattern`, citing each decision in the household's words, once for the decisions
   behind it. An approved preference from a pattern, and a decision two sessions have held, are
   offered for sharing once ever, also right after an approval. A `promote` proposal names its row by
   id; approving it needs its second confirmation (`confirm_promotion`, `--confirm-promotion`). Meko
   upkeep then promotes the preference's sentence to collective memory, or uploads the decision
   record, linked in `meko_link`, and V-13 checks both. The brief marks a preference promoted once
   its sharing was approved by the brief's `known_at`. Tested on Postgres with the demo household's
   three decisions (`tests/integration/test_promotion.py`), and on local Meko in a datapack of its own.
   **Done-when met Nov 24** (tuning log entry 12). The demo story holds Jun's decisions in Sessions 1
   and 3 beside Mara's in Session 2 (`decisions.toml`), and demo mode plays what dreaming learns
   (`learning.toml`): before session 4 it dreams over Session 3, Mara approves the preference, Jun
   confirms its sharing, and upkeep shares it in Meko. In session 4's replan, recorded on Foundry,
   the debt specialist cites `fact:preference.debt_vs_flexibility` though neither the household nor
   the session mentions it; with an ask from the orchestrator that doesn't name it either, it cited
   it in 3 of 3 runs. Session 4's replan now compares against the latest decision (Session 3's) and
   lists all three to revisit (Pim, Nov 24).
5. **Meko upkeep.** Add, rewrite in the past tense, delete on retraction, promote, and `meko_link`.
   Done when: after the four sessions, memory search for "Mara's salary" returns the current value and
   the old one in the past tense, and the validation suite's link check passes.
   Built Nov 24 (promotion with task 4): Meko upkeep (`kako/upkeep/`) keeps one
   memory in Kako's words for every fact, seed facts included, as `kako:upkeep`; a replaced fact's
   memory is rewritten in the past tense (and a memory Meko extracted for it deleted), a retracted
   one's deleted, each linked in `meko_link` with who wrote it and the text written (migration
   0006). It runs after each approval, at the end of `kako demo run` and with `kako meko sync`, and
   `kako meko check` is the link check (V-13). After `kako demo run`, a memory search for "Mara's
   salary" finds "from Dec 1, 2026, … is ₱68,000.00" and "from Mar 1, 2026 until Nov 30, 2026, … was
   ₱52,000.00", and the check passes (`tests/integration/test_demo_mode.py`).
6. **Context Gaps** (a Must if the Phase 1 spike found the tools). Shortfalls become `context_gap` rows
   and questions for the household; an approved answer is followed by `selflearning_verify`.
   Done when: one weak search in the demo household goes from Mid or Low to `improved`, with both scores
   stored.
   Built Nov 24, and the done-when met on Meko Cloud the same day in a throwaway datapack: "Who looks
   after Lia after school?" went from `low` 0.297 to `improved` 0.578, both scores stored
   (docs/meko-setup.md, spike 3). `kako/gaps/` keeps each shortfall of coverage in Meko's search log
   (`selflearning_query_log`, low and mid bands) as an open `context_gap` with a question written by
   code (`kako gaps sync`, `POST /api/v1/gaps/sync`). An adult ties the proposal that answers it, one
   that writes a fact (`kako gaps answer`), or dismisses it. Once that proposal is approved and Meko
   upkeep has written the fact's memory, the search is replayed (`selflearning_verify`, after each
   approval's upkeep and with `kako gaps verify`, at most 5 a run) and the outcome and the score
   after are stored; `improved` makes the gap verified. Tested on Postgres with Meko's search log in
   memory: a search that found nothing goes from low (0.000) to `improved` (0.800) once Mara's note
   is approved through the API (`tests/integration/test_gaps.py`); on local Meko the commands say
   the tools aren't there and nothing changes. Asking a gap in a session (`asked`, the brief's "Kako
   would like to know") is Phase 5.

### Phase 5: Screens and demo (Mon Jan 4 to Sun Jan 10, feature freeze)

1. **Session screen** with approval cards inline, and the **agents' steps** for each turn: every
   specialist's tool calls, the what-ifs it tried, and what was rejected and why.
   Built Nov 25, laid out like ChatGPT, Claude and Gemini (sessions on the left, the conversation,
   the composer at the bottom), in the look-and-feel tokens, dark and light: each turn kept as shown
   (`session_turn`, migration 0007), `GET /household`, `GET /sessions`, `GET /sessions/{id}/turns`
   with the running turn's steps, and the screen with its loading, empty and error states. Checked
   on the demo household through session 4 (Mara's news, her approval, Jun's replan) in both themes
   and at phone width.
2. **Plan screen** with "why" on each recommendation (figures with their formula and facts, memories,
   decisions, documents, the Meko trace) and "what changed" against the last plan.
   Built Nov 25: `GET /plans` and `GET /plans/{id}` (`db/plan_read.py`, the words in
   `planning/why.py`), the screen at `/plans` and `/plans/{id}` with a version picker, linked from
   the sidebar and from each answer that made a plan. Each option's why goes down to the facts:
   every cited figure with its formula in words, the figures and facts it was built from, each fact
   with where it came from and who approved it, the decisions, Meko's memories and documents, the
   household's words, and what the number check matched; the turn's Meko calls and trace link.
   What changed is F-DIFF-1 against the previous version, or for a first plan the last decision as
   known then, with the decisions to revisit. Checked on the demo story (plan v1 from Session 2,
   v2 from Session 4) in both themes, at phone width, and in its loading, empty, error and missing
   states.
   Follow-up, noted Nov 25 (its own PR, High tier since it touches the number check): the check
   keeps the first source a number matches, and it looks at the snapshot's facts before the
   what-ifs' allocations, so in session 4's option A "₱10,000" is recorded as matching the "School
   and transport" fact rather than the option's ₱10,000 for the card. Pass and fail don't change;
   the plan screen shows the match as recorded. Fix: in `pool_of` (`agents/numbers.py`), add the
   what-ifs' allocations before the facts, with a test that option A's ₱10,000 matches
   `allocation:<what-if>:debt:credit-card`.
3. **Timeline and decisions.** Facts over time with their windows, replaced and retracted values, life
   events; decisions with rejected options and "to revisit".
   Built Nov 25: `GET /timeline` and `GET /decisions` (`db/history_read.py`; the words in
   `planning/timeline.py` and `decisions/revisit.py`, both pure; each fact's source in
   `db/provenance.py`, now shared with the plan screen), and the screens at `/timeline` (what
   happened, newest first, with what is ahead of the household's date apart; each thing's values
   over time with their windows and states) and `/decisions` (each decision's chosen option, the
   options not chosen and why, the facts it rests on, and what to revisit), linked from the sidebar.
   Checked on the demo story through Dec 1 and on a household loaded through Nov 20 (the new job
   ahead, her ₱52,000 current and ₱68,000 coming, the three decisions already to revisit), in both
   themes, at phone width, and in loading, empty and error states.
4. **Metrics page.** Meko `datapack_metrics`, tokens, cost and seconds per turn (average and worst
   case), brief size against the whole context, number-check pass rate, dreaming score, agent test-set
   score against the single-agent baseline, the session-4 answer scored with and without the promoted
   preference, and Context Gaps before and after scores.
   Built Nov 25: `GET /api/v1/metrics` works every figure out in code from stored rows and saved
   results (`metrics/turns.py`, pure; `db/metrics_read.py`; `evals/results.py`): each turn's model
   calls, tokens, cost and seconds (average and worst case, the worst one named) for the household's
   sessions and for the agent test set's by architecture, its brief's size against its budget, the
   number check, the test set against the single-agent baseline, the learned preference's effect,
   dreaming's labelled set and its runs, Context Gaps' scores before and after, and the Meko calls
   each Free-tier allowance has left. `GET /api/v1/metrics/meko` reads Meko's own `datapack_metrics`
   live (context size, how much `context_search` saves sending, relevance) and sets the brief
   against the whole context. The preference's effect is measured on the four test-set questions
   whose answer should cite it (q10, q12, q16, q21): the household without what dreaming learned
   (`kako demo run --without-learning`), recorded on Foundry once (`kako test-set
   --without-preference`, US$0.26, tuning log entry 13), against the same questions with it: 81.4%
   with, 59.3% without, and 81.3% against 72.9% leaving out the check that names the preference. The
   screen at `/metrics` (sidebar, "Metrics") shows each part with its own empty and error states, and
   Meko's part fails on its own. Measured on the demo story through Dec 1, replayed: a household
   turn 26.7 seconds on average and 40.6 at worst, 51,028 tokens and US$0.0452; the brief 2,430
   tokens, 6.5% of the datapack's 37,458; every number checked passed; specialists 93.3% against
   one agent's 90.7%; dreaming 15 of 15. Context Gaps need Meko Cloud, so locally the section says
   none yet. Checked in both themes, at phone width, and loading, empty and error.
5. **Demo datapack on Meko Cloud.** Seed sessions 1 to 3 through the real flow once; rehearse session 4.
   Done when: a full rehearsal runs on Meko Cloud and the call counter shows the allowance left.
6. **Shoulds, if time:** a what-if kept as an AMP branch; the specialist conflict drawn on screen.
Done when (for 1 to 4): each screen has empty, loading and error states and works on the seeded
household without demo-only code paths.

#### Phase 5a: Interface refinements (Pim's feedback, from Nov 25)

Pim's changes to the screens built in tasks 1 to 4, made before the demo datapack (task 5) and the
video, so the rehearsal and the recording use the screens as they will ship. Each item is one of
Pim's requests; more are added here as they come. They change how a screen shows what it already
reads, never what Kako works out.

1. **Timeline (Nov 25).** The title placed like a page heading (Claude's Artifacts page), with
   "What happened" and "Each thing" as chips under it (like "Yours" and "Templates"). What happened
   as a clean list in the style of Claude's Plugins list: each event a headline ("Mara got a new
   job") with a short line under it (the date, what kind of event, who approved or decided it), and
   its details (the facts it changed, where they came from, the plan, session or decision it opens)
   only when it is opened. Each thing as overview cards in the style of Claude's Scheduled tasks:
   each card its name, what it holds now and when it last changed, with its full history only when
   it is opened.
   Done when: both views show one line or one card per item, everything the screen showed before is
   one click away, the details open and close by keyboard and pointer, and the screen still has its
   loading, empty and error states, in both themes and at phone width.
   Built Nov 25: `PageHeader` and `ViewChips` (`components/page-header.tsx`, the title and the view
   chips, arrow keys between them) and `DetailSheet` (`components/detail-sheet.tsx`, a native modal
   dialog) are shared, so the other screens can take the same shape. Each event now names who
   approved it or decided (`by` on `GET /timeline`). Checked on the demo story through Dec 1 and on
   a household loaded through Nov 20 (the new job ahead, Mara's salary "Changes Dec 1, 2026"), in
   both themes, at phone width, by keyboard, and loading, empty and error.
2. **Meko not reachable (Nov 25).** On the metrics screen, a Meko that can't be reached reads as a
   plain note ("Meko isn't running here"), not a red error; a real error from Meko stays red.
   Done when: the metrics screen with Meko stopped shows the note, and with Meko failing shows the
   error.
   Built Nov 25: the Meko client tells "nothing answered" (`MekoUnreachable`) from an error, and
   `GET /metrics/meko` answers it with 503 and "Meko isn't running here, so its own figures can't
   be shown".
3. **Decisions as books (Nov 25).** Each decision is a book on a shelf, after the two bookshelf
   pages Pim shared. The cover carries the question as its title ("Should the bonus go to the card
   or the family trip?"), who decided as its author ("by Jun") and where and when as its publication
   line ("Session 3 · Oct 18, 2026"), with its standing (in force, revised, reversed) and a gold
   ribbon when it is to be revisited. A book opens on three bookmarks:
   - **The decision:** what was chosen then and the household's reasoning in their words, with
     each option not chosen and why.
   - **To revisit:** what has changed since among the facts it rests on, each change before and
     after; when nothing has, it says so.
   - **Rests on N facts:** the facts it was made on, each with its value then and whether it has
     moved.
   It keeps the screen pattern of item 1 (the title and view chips at the top left) and the look and
   feel's colours (gold only for "to revisit", emerald for in force), and reads only what
   `GET /decisions` returns.
   Done when: Pim has approved a mockup, and the screen built from it shows every decision as a
   book, each bookmark one click away, by keyboard too, in both themes, at phone width, and in its
   loading, empty and error states.
   Approved Nov 25, with Pim's changes to the mockup: the three bookmarks sit on one row, never
   wrapping ("The decision", "To revisit · 1", "Rests on 21 facts"); no option letters ("B") and no
   "Chosen" mark (the bookmark and "What Jun chose" already say it); options turned down shown plain
   and greyed, with no colour and no "Not chosen" (this replaces "rose for options turned down").
   Built Nov 25: the shelf (`components/decisions-view.tsx`, chips All, To revisit, In force and
   Revised with their counts; covers whose colour and pattern stand for the session, decoration
   only; a pattern "across the shelf" counted in code from each chosen option's tags), and the open
   book (the cover on the left, or on top on a phone, the bookmarks as tabs hanging from the page,
   arrow keys between them). The book and bookmark open are in the address
   (`/decisions?book=<id>&mark=revisit`), so the timeline's decision opens its book, the browser's
   back button returns to the shelf and an older `#decision-<id>` link still opens the book. On a
   phone the bookmarks keep one row with short names ("Decision", "Revisit · 1", "21 facts"). For
   the third bookmark each fact `GET /decisions` returns now says what it is about (`thing`, `kind`,
   `words`), so the facts are grouped by kind like the mockup. The pure parts are `lib/shelf.ts`.
   Checked on the demo story through Dec 1, in both themes, at phone width, by keyboard, from the
   timeline, and loading, empty, error and an unknown book.
   Later, not built (they need new backend work, Meko or the models, and Pim's yes): the mockup's
   "Then and now" totals (the household's take-home pay when it decided and now, worked out in
   code), and its "Keep the decision as it is" and "Talk it over in a new session" buttons on the
   "To revisit" bookmark.
4. **Money tracker (Nov 25).** A screen where the household sees where its money stands at a
   glance, after the tabs of Pim's own budget spreadsheet (its structure only, never its numbers):
   the overview, the month's plan line by line, each debt's amortization, the big moments ahead and
   net worth. First in the sidebar, as `/money` with the pattern of item 1 (the title and view
   chips: Overview, Monthly plan, Debts, Big moments, Net worth).
   Done when: Pim has approved a mockup, and the screen built from it shows every view from
   `GET /money`, every number worked out in code (docs/data-model.md, "The money screen"), in both
   themes, at phone width, by keyboard, and in its loading and error states.
   Approved Nov 25, with Pim's six changes to the mockup: the tiles show only their label and value
   (no line under them), named "Total salary" and "Free after expenses"; where each peso goes is a
   donut, not a bar; the monthly plan has no kind column; no "before" split bar; and each debt is
   an amortization table in the monthly plan's style (month, payment, interest, principal, balance
   left), with no line chart, keeping the debt's facts (interest, paying a month, paid off, interest
   still to pay).
   Built Nov 25: `engine/money.py` (M-1 to M-6, pure; F-DEBT-2 also keeps each debt's scheduled
   payment, no figure changes), `planning/money.py` (in words), `db/money_read.py` and
   `GET /api/v1/money`; `components/money-view.tsx` with `lib/money.ts` (the view in the address,
   `?view=debts`; the donut's arcs, checked in tests) and the chart palette (docs/look-and-feel.md,
   "Charts"). The rollover month is marked in the car loan's table ("+₱12,550.00 from the Credit
   card", Aug 2027); a schedule shows a year until "Show all". On a phone the tables scroll sideways
   with their first column kept in place. Checked on the demo story through Dec 1, in both themes,
   at desktop and phone width, by keyboard, and loading and error.
   Later, not built: year-end projections of net worth, a one-off what-if such as a bonus, paydays
   (which pay covers which bills), and a card's use against its limit.
5. **Before and after each option (Nov 25).** When Kako answers with options, the household sees
   what each one changes instead of only reading it ("Card paid off in 9 months" is abstract): each
   option's card shows its before → after against today's plan, a table below the options sets
   today's plan and every option side by side, and each option opens its months one by one in the
   money screen's amortization style, so option B's full schedule is there to see.
   Done when: Pim has approved a mockup, and the session and plan screens built from it show, for
   every turn with options, each option against today's plan with every number and every change
   worked out in code (docs/data-model.md, "Before and after an option"), in both themes, at phone
   width, by keyboard, and in its loading and error states.
   Approved Nov 25, with Pim's choices on the mockup: keep both the per-card "Before → after" and
   the "Compare the options" table; a change that is worse for the household is rose with its
   words, better is emerald, the same is plain; the same pieces on the plan screen.
   Built Nov 25: `engine/compare.py` (C-1 to C-3, pure), `planning/compare.py` (in words, every
   change written by code), `db/compare_read.py` and `GET /api/v1/plans/{id}/compare`. Today's plan
   is the turn's own run: its snapshot taken again, checked against the stored hash, and each option
   is that snapshot with its allocations as overrides, the what-if the agents ran; nothing is stored,
   so every turn kept before this has its comparison too. `components/compare-view.tsx` with
   `lib/compare.ts`, used by the session screen's answer and the plan screen. Agents see none of
   it, so the recordings and the number check are unchanged. Checked on the demo story's sessions 2
   and 4 (session 2 to the centavo against the worked example: option A pays the card off Jun 15,
   2027, 38 months sooner, with ₱119,627.44 less interest on both debts, and its ₱11,600.00 rolls
   into the car loan in Jul 2027; option B reaches the emergency fund's ₱210,000.00 on Sep 15,
   2027), in both themes, at desktop and phone width, by keyboard, and loading and error.
   Later, not built: a what-if the household sets itself beside the options (an amount of its own).
6. **Kako with Meko off, to try it on the laptop (Nov 25).** Pim wants to try Kako in the app with
   their own questions, to feel how it answers, without touching the demo. Local Meko doesn't run
   on Windows and Meko Cloud is kept for the demo datapack, so the app gets a switch to run without
   Meko (`KAKO_MEKO_OFF=true`), chosen by Pim over a terminal-only try.
   Done when: with Meko off, the API makes no Meko call, a new session is kept in Kako only, a turn
   runs (no Meko search) and its plan and comparison show, an approval writes with no Meko upkeep,
   the health check says Meko is off, Meko's own screens say so as a note, and a session kept in
   Meko is refused a turn with a plain reason.
   Built Nov 25: the setting (`settings.py`), the real services opening no Meko when it is set
   (`api/sessions.py`), the Meko probe (`meko/health.py`) and the 503s of `GET /metrics/meko` and
   `POST /gaps/sync`. Every route already went on without Meko (tests run that way); this only lets
   a real run choose it. `tests/integration/test_meko_off.py` runs session 4 through the API with
   it, with Meko's address a closed port and not one row in `meko_call`.
   The try itself, on the laptop: a database of its own (`kako_sandbox`) with the demo household
   loaded through Dec 1, the backend on port 8001 with Meko off and live Foundry models (about
   US$0.03 a question, under the US$3 daily cap), and the web app on port 3001. The demo's database,
   its recordings and Meko Cloud are untouched; live mode never writes a recording.
   The first question on the laptop (Nov 25) ran 49 seconds on live models (6 calls, US$0.06) and
   was kept, but the screen said HTTP 500: Next.js's pass-through gives up after 30 seconds. The web
   app now waits up to 5 minutes, and a request that ends with no answer reads the session again
   before calling the turn failed (docs/architecture.md, "The session screen").
   What looked off while trying it (Nov 25), to fix or decide on:
   - Plan v3 (Dec 1: ₱10,000 on the card, ₱10,000 to the emergency fund, ₱5,050 to a new house
     fund) has no session or decision behind it: it is loaded as approved facts labelled
     `session-5:plan-v3`, so the step from Mara's new job to the new split is invisible, and a
     plan's "What changed" compares against the Oct 18 decision instead. Either session 4's replan
     proposes plan v3 and Jun accepts it on Dec 1, or plan v3 gets its own decision in
     `decisions.toml`.
   - Two cited figures read oddly to a household: the house fund's "on track" shown as "0 (nothing
     allocated to it)" and the emergency fund's months to target as "none". They should read as
     words ("not on track", "no money going in").
   - The sidebar's turn count stayed at 0 after the long turn's error (it is read again once the
     turn ends, which the fix above now reaches).
   - In Session 2's recording the orchestrator corrected two slips of its own (citing the wrong
     what-if, guessing a figure's name), each costing an extra call; a sharper tool message would
     avoid them.
   - A what-if can't yet try a one-off amount (the ₱48,000 13th-month pay), a spending change or an
     income change, so "what if I lose my job?" can only be answered in words (item 8 stops it
     being filed as a real change). Next: income, spending and one-off what-ifs in the engine and
     `run_what_if`, shown before and after like the options.
   - Dreaming runs only when someone runs it, and a session nobody ends stays open.

7. **Documentation inside the app (Nov 25).** The sidebar's footer (the household's name and date)
   opens a menu with System check and a new Documentation, in the style of Meko's own docs: how
   Kako uses every part of Meko's context (conversations, memory, learning, knowledge, artifacts,
   decision tracing, Postgres in the datapack, sharing and collaboration), anchored to the
   Villanuevas' story, with a placeholder for each part not built yet, and "Under the hood" pages
   on the engine, the agents, dreaming and the guardrails. It answers the judging's "Use of Meko"
   in the app itself.
   Done when: Pim has approved a mockup, and the screen built from it shows every page and section
   with its status, every internal link opens a page, section or screen that exists, every figure is
   one the demo's files or the engine give, "Copy page as Markdown" copies the page, in both themes,
   at phone width and by keyboard.
   Approved Nov 25 (the mockup, then the four Under the hood drafts). Built Nov 25: the pages as
   data (`web/src/lib/docs/`, one module per page, with `docs.test.ts`: unique ids, the menu, every
   link, the statuses, the Markdown), `components/docs-view.tsx` and `/docs/[slug]`, and the
   household menu in `components/sidebar.tsx` (closes on Escape or a click outside). The first page
   says live whether Meko is reachable here, off or unreachable. Artifacts and Postgres in the
   datapack are placeholders (planned); sharing is in part (promotion is built, per-person
   datapacks need Meko Pro). The approved mockup and drafts stay in `docs/mockups/` as the record.
   Checked on the demo story through Dec 1, in both themes, at desktop and phone width (no sideways
   scroll), with no console errors.

8. **Kako follows the chat and its writer (Nov 25).** Pim's chats on the laptop, as Jun: "what if
   my salary goes to 200000 per month." was met with "whose salary, Jun's or Mara's?"; "Jun",
   answering that question, with "what would you like to look at today?"; "no, just give me the
   simulation" with the current plan, the job-loss question forgotten; and "what if i lose my
   job" was filed as a real pending job loss. Each turn's brief held the household's state and one
   Meko search on the new message, but never who wrote it or the session's earlier turns.
   Done when: the brief names who wrote the message; from the second turn on it shows the
   session's last turns, read from Postgres (so Meko off too), within the budget; a what-if is
   never filed as a change; the household's earlier words in the session count as said; tested
   with a scripted two-turn session on Postgres; and sessions 2 and 4 recorded again on Foundry.
   Built Nov 25: "Who is writing" and "This session so far" in `agents/brief.py`, read by
   `agents/brief_store.py` (`session_turn`, this household's sessions only), dropped oldest first
   before the facts list; `propose_change` refuses words that ask a what-if (`agents/proposing.py`,
   English and Filipino); the number check takes the household's earlier messages in the session
   as said, and lets a specialist's summary name the brief's own refs (`D1`). No prompt file or
   tool definition changed, so the test set's recordings stand. Recorded: docs/tuning-log.md
   entry 14.

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
   only pile up don't know what's current. On screen: Meko on its own returns both ₱52,000 and ₱68,000
   for Mara's take-home pay; then Kako answers "₱68,000 since Dec 1, replaced ₱52,000" (the worked
   example in data-model.md). "Meko remembers what
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
