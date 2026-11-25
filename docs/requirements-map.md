# Requirements map

Every ContextCon 2026 rule, Challenge 05 objective, judging criterion and prize that applies to Kako,
against what is built. **Update a row when its status changes**, in the same PR as the change.

Source: the ContextCon overview, Challenge 05 brief and FAQ at
https://www.hackerearth.com/lp/challenges/contextcon, summarised in
[contextcon-2026.md](contextcon-2026.md) (checked Nov 17, 2026). The official page is the authority.
Full terms and conditions are not published yet.

| Status | Meaning |
| --- | --- |
| **Not started** | Planned, no work yet |
| **In progress** | Work started, not yet shown working end to end |
| **Implemented** | Works on the demo household (or, for submission items, done) |
| **Not planned** | Deliberately out of scope |

Phases refer to [build-plan.md](build-plan.md).

## Key dates

| Milestone | Pacific | Manila |
| --- | --- | --- |
| Registration opens, build begins | Nov 7, 2026 | Nov 7, 2026 |
| **Submissions due** | **Sun Jan 17, 2027, 11:59 PM** | **Mon Jan 18, 2027, 3:59 PM** |
| Our feature freeze | | Sun Jan 10, 2027 |
| Our submission | | Sat Jan 16, 2027 |
| Judging | Jan 18 to 24, 2027 | |
| Winners | February 2027 | |

## Eligibility and basics

| Requirement | Status | How Kako meets it | Phase |
| --- | --- | --- | --- |
| Aged 18 or older; solo or a team of up to 4 | Implemented | Solo entry by Pim | — |
| Uses Meko as its context layer | In progress | Every session is a Meko conversation; memories, shared knowledge, knowledge base, artifacts and traces carry the household's context. The toolkit is set up (PRs #3 and #4); the Phase 1 spikes confirmed Meko Cloud from the backend, traces with plan and reasoning, self-learning on Free and AMP from the laptop (docs/meko-setup.md); the adapter is Phase 2 | 1–4 |
| Any model, any MCP client | Implemented | Azure AI Foundry (OpenAI model deployments, `gpt-5.4` and `gpt-5-mini`) through one model manager, checked by `kako check-models` (docs/azure-setup.md); Meko through its MCP server | — |
| Entrants keep ownership | Implemented | All rights reserved; viewing and evaluation only, including by the judges ([LICENSE](../LICENSE)) | — |

## Challenge 05 objectives

| Objective | Status | How Kako meets it | Phase |
| --- | --- | --- | --- |
| **Remember the person:** goals, preferences, constraints and life events as long-term memory | In progress | Goals, preferences, constraints and life events are facts with a validity window and a replacement chain in Postgres, and memories in Meko; durable preferences are promoted to shared knowledge ([data-model.md](data-model.md#facts)). Built so far: the fact store, with replace, retract, snapshots on a date and as known at a time, and a database guard that allows nothing else (Phase 2) | 2, 4 |
| **Plan across areas:** specialist agents (budget, debt, savings, goals) share one financial context | In progress | One orchestrator calls four specialists as tools; all start from the same brief and the same engine run, and conflicts between them are found in code and resolved in the open ([architecture.md](architecture.md#agents)). Built: the brief, the agents' tools, the four specialists and the orchestrator, tested on the worked example's session 2 with a scripted model (Phase 3, tasks 2 and 3); the reconciliation rules and the what-if loop (task 4) catch session 2's over-allocation and record how it was resolved | 3 |
| **Adapt over time:** the plan updates when a life event happens | In progress | Life-event replan: the old fact closed and replaced, the decisions that rested on it marked to revisit, a new plan, and a diff that says what changed and why ([architecture.md](architecture.md#how-a-life-event-replans)). Built: replace and retract (Phase 2, task 2), the diff with the decisions to revisit (task 4), and the replan (Phase 4, task 2): the household states the change in a session, approves it, and the next turn answers with the new plan, what changed and why; session 4 shows it on the demo household. Built (Phase 5, task 3): the timeline shows the new job with Mara's old salary closed and replaced, ahead of the household's date until Dec 1, and the decisions screen marks the three decisions that rested on it to revisit | 4, 5 |
| **Explain the advice:** every recommendation traces to the memories and data behind it | Implemented | Each recommendation stores its figures, facts, decisions, memories and documents, and its Meko turn; the number check blocks any figure the engine did not produce. Built (Phase 5, task 2): the plan screen's "why" on each option goes down to the facts (each figure's formula in words, the figures and facts it was built from, where each fact came from and who approved it, Meko's memories and documents, the household's words, what the number check matched) and lists the turn's Meko calls with the trace link on Meko Cloud. Built (task 3): the timeline shows every value each thing has held, with where it came from and who approved it | 3, 5 |

## Meko at the core (from the brief)

| Meko feature | Status | Kako's use | Phase |
| --- | --- | --- | --- |
| Memory: goals, risk profile and past decisions, across sessions | In progress | One memory per approved fact, decision and preference, with Kako's ids in its metadata; replaced facts rewritten in the past tense. Built (Phase 4, task 5): Meko upkeep keeps one memory in Kako's words for every fact, seed facts included, after each approval and with `kako meko sync`; a replaced fact's memory is rewritten in the past tense and a retracted one's deleted, each linked in `meko_link`; `kako meko check` is V-13. After demo mode's sessions, a memory search for "Mara's salary" finds her new pay and her old pay in the past tense. Built (task 4): a preference approved from a pattern and a decision two sessions have held are offered for sharing; with a second confirmation, upkeep promotes the preference to collective memory or uploads the decision record, and V-13 checks both | 4 |
| Knowledge base: statements, budgets and planning rules (synthetic) | In progress | Synthetic statements (CSV), planning rules and Philippine reference documents (Markdown) for the demo household. Written in `data/demo-household/`; `kako demo upload` puts them in Meko's knowledge base (tested on local Meko); the demo datapack on Meko Cloud is seeded in Phase 5 | 2 |
| Artifacts: generated plans and reports in the datapack | Not started | Each plan report kept with `artifact_put`; its hash stored on the plan | 4 |
| Conversations: planning sessions over time | In progress | One conversation per session, turns with `plan` and `reasoning`; dreaming reads them. Built: `POST /api/v1/sessions` starts the conversation and each turn (`POST /api/v1/sessions/{id}/turns`, or `kako ask`) is kept in it with the steps taken, the specialists' reasons and the ids of the plan, recommendations, conflicts and what-if runs. Ending a session queues dreaming, which reads the conversation's turns and proposes what the household stated (Phase 4, task 3, first part) | 3–4 |
| Traces: why each recommendation was made | In progress | The session's conversation id is its trace id; every Meko call in a turn is a span; recommendations store their turn. Built: `GET /api/v1/sessions/{id}/trace` gives the session's Meko calls as spans from local Meko's call log (each search with its parts), or the Observe hub link on Meko Cloud; the turn's Meko metadata names the plan and recommendation ids, and each recommendation its turn seed. Built (Phase 5, task 2): the plan screen shows why each option was proposed, down to the facts, with the turn's Meko calls and its trace link. Left: the link checked on Meko Cloud with the demo datapack | 3 |

## Expected outcomes

| Outcome | Status | How | Phase |
| --- | --- | --- | --- |
| A synthetic household or small-business financial profile | In progress | The Villanueva household: two adults, one child, pesos, statements and reference documents ([data-model.md](data-model.md#demo-dataset)). Its seed and 18 approved changes load through the fact store (`kako demo load`), pass every validation rule, and give the worked example's figures; the session scripts come with the sessions | 2 |
| A planning agent system connected to Meko | In progress | Orchestrator, four specialists and dreaming, through one Meko adapter. Built: the orchestrator and specialists, with the brief's one `context_search` and one extra search per specialist (Phase 3, tasks 2 and 3); dreaming's job, extraction and checks in code, and Meko's extracted memories as candidates, each linked to what a person approves or deleted (V-14) (Phase 4, task 3) | 3–4 |
| 3 or more sessions showing memory carrying over and the plan adapting to a life event | In progress | Sessions in August, September and October, then the new job in session 4. Built: sessions 2 and 4, recorded and replayed by `kako demo run`; session 4 is the life event and the replan. Sessions 1 and 3 come with dreaming | 4–5 |
| Trace-backed explanations for the key recommendations | In progress | The "why" view and the Meko trace for every recommendation. Built (Phase 5, task 2): the plan screen's why on each option, and the turn's Meko calls with the Observe hub link when it ran on Meko Cloud. Left: checked on Meko Cloud with the demo datapack | 3, 5 |
| Encouraged: a what-if scenario planner | In progress | What-ifs in the engine (Must for the engine, screen is a Should); a kept scenario as an AMP branch (Should). The engine takes hypothetical values (`Override`) in place of facts and cites them (Phase 2, task 3) | 3, 5 |

## Judging criteria

| Criterion | Weight | Status | What Kako shows | Phase |
| --- | --- | --- | --- | --- |
| Use of Meko | 30% | Not started | Every part of the context has a visible job (rows below) | 2–5 |
| Impact and usefulness | 25% | In progress | A household's real question, "what should we do now, and why is that different from before?", answered with figures it can check; plain language for families anywhere. Built (Phase 5a, item 4): the money screen shows where the household stands at a glance, the way a family keeps its own budget sheet: the pay and what is free after expenses, where each peso goes, the month line by line, each debt month by month to the day it is paid off, the big moments ahead and net worth, every number from the engine | 4–5 |
| Technical execution | 20% | In progress | A working demo judges can run themselves (demo mode, no Azure account); a pure, tested engine; facts that are never overwritten; CI against local Meko; docs as the source of truth. Built: `kako demo run` (Phase 3, task 9) loads the household, uploads its documents to local Meko and replays session 2 and the agent test set from recordings, tested in CI on a fresh database | 1–5 |
| Innovation | 15% | Not started | Memory with history (valid time and record time, replace versus retract); dreaming that proposes and a person who approves; specialists that build on a preference another session taught them | 4 |
| Presentation | 10% | Not started | A video under 5 minutes, a README with setup and measured metrics, these docs | 6 |

### Use of Meko, part by part

| What the judges look for | Status | Kako | Phase |
| --- | --- | --- | --- |
| Conversations | Not started | Sessions as conversations | 3 |
| Memory | Not started | Facts, decisions and preferences as memories that stay current | 4 |
| Learning | In progress | Built (Phase 4, task 4): dreaming counts the household's decisions by option tags and proposes a preference pattern, then offers it and held decisions for promotion; a second confirmation, then Meko upkeep shares them. Task 4's done-when met on Foundry (Nov 24, [tuning-log.md](tuning-log.md) entry 12): in demo mode, dreaming over Session 3 finds the preference in Jun's and Mara's three decisions, Mara approves it, Jun confirms its sharing, and in session 4's replan the debt specialist cites it though nobody in the session mentions it (also 3 of 3 runs with an ask from the orchestrator that never names it). Built (task 6): Meko's own self-learning: each weak search in Meko's log becomes a Context Gap with a question for the household; once the answer is approved and in Meko, `selflearning_verify` replays the search and its before and after scores are kept (tested with Meko's log in memory, and run on Meko Cloud on Nov 24: a weak search went from low 0.297 to improved 0.578). Dreaming reads Meko's extracted memories and Learnings, proposes promotions; the household approves; a preference goes to collective memory, a decision record to shared knowledge | 1, 4 |
| Knowledge | Not started | Statements, rules, reference documents; promoted memories | 2, 4 |
| Artifacts | Not started | Plan reports | 4 |
| Decision tracing | In progress | Turns with `plan` and `reasoning`; spans for every Meko call; linked from each recommendation. Built in the backend (Phase 3, task 6). Built (Phase 5, task 1): each answer on the session screen shows its steps and links its Meko trace. Built (task 2): the plan screen traces each recommendation to its figures, facts, decisions and Meko calls | 3 |
| Blending data infrastructure: Postgres inside the context | Not started | The household's facts in AMP, Postgres in the datapack, if the Phase 1 test passes; a scenario as an AMP branch (Should) | 1, 5 |
| Sharing context and collaborating to improve it | In progress | Six agents on one datapack; both adults taking part across sessions (one reports the job, the other approves the promotion); the debt specialist acting on a preference the household approved; Context Gaps answered by the household. Built (Phase 4): Mara approves the learned preference and Jun confirms its promotion; session 4's debt specialist cites it (tuning log entry 12); Context Gaps from Meko's search log | 4–5 |

## Prizes

| Prize | Status | Kako's case |
| --- | --- | --- |
| Grand prize: collective memory in action, agents that learn, share and improve over time | In progress | Dreaming and promotion make the specialists better each session, **measured** on the metrics page (Phase 5, task 4, Nov 25): the four test-set questions whose answer should cite the promoted preference, recorded on Foundry with the household that learned it and without (`kako demo run --without-learning`, `kako test-set --without-preference`): 81.4% with, 59.3% without, and 81.3% against 72.9% leaving out the check that names it. Context Gaps' before and after scores are on the same page; they need Meko Cloud, so they are measured with the demo datapack (Phase 5, task 5) |
| Best use of shared memory: agents that build on each other's learning, with a clear decision-trace story | In progress | The flexibility preference: learned by dreaming from three decisions, approved, promoted, then used by the debt specialist, all traceable. Built (Phase 4, task 4): demo mode plays it end to end, and session 4's recording shows the debt specialist citing it. Built (Phase 5, task 2): the plan screen shows the preference on option A's why as "Learned by dreaming from Session 3, approved by Mara on Oct 20, 2026", shared with every agent in Meko |
| Runner-up places | — | Same entry |
| People's choice | Not started | The video and a short post |

## Submission requirements

| Requirement | Status | How | Phase |
| --- | --- | --- | --- |
| Demo video under 5 minutes, linked | Not started | Storyboard in [build-plan.md](build-plan.md#video-storyboard) | 6 |
| Public (or open-source) GitHub repository with setup instructions | In progress | The repository is public; setup instructions come with the code | 1–6 |
| Documentation (optional): architecture, how Kako uses Meko, measured token or relevance metrics | In progress | These docs; the metrics page (built Nov 25: tokens, cost and seconds per turn, the brief against Meko's whole context from `datapack_metrics`, relevance) and its numbers in the README | 1, 5–6 |
| Repository licence checked against the full terms | Not started | Check when the terms are published; switch to Apache-2.0 only if they require open source | 6 |
| Demo datapack and artifacts available through judging | Not started | Seeded on Meko Cloud; touched before judging (Free-tier artifacts expire after 30 days unused) | 5–6 |

## Beyond the brief

| Feature | Status | Why it matters |
| --- | --- | --- |
| Two kinds of time: when something was true and when Kako learned it | In progress | Explains an old plan exactly as it was made, and tells a change in life from a corrected mistake. Built (Phase 5, task 3): the timeline lists a correction apart from a change, on the day it was corrected, with what was wrong, what is back and why, and marks each value current, coming, past or corrected on the household's date |
| Decisions keep their rejected options and their assumptions | In progress | When an assumption is replaced, the decision is flagged to revisit. Built: a decision is written on approval with every option (the rejected ones with their reasons and tags) and the facts it rested on (income, costs, rates and preferences, not balances), and none of them can change afterwards (Phase 4, task 1); "to revisit" is F-DIFF-1, shown with the replan (task 2, built: session 4 lists the September decision to revisit because it rested on Mara's old salary). Built (Phase 5, task 3): the decisions screen shows every decision with its options not chosen and why, what each leans to, the facts it rests on, and what has moved under it since |
| The number check | Done | No figure reaches the household unless the engine produced it. Every number in the reply, the options, the resolution's reason and the specialists' summaries is matched to a figure, fact, what-if allocation or the household's own words (V-10, `agents/numbers.py`); a miss is sent back once, then flagged; every check is a `number_check` row (Phase 3, task 5) |
| Reconciliation rules in code | In progress | Specialist conflicts are found by arithmetic, not by hoping a model notices. Built: over-allocation, opposite moves and missed goal dates over the specialists' proposals together (`planning/reconcile.py`), up to 3 splits checked by the same rules, and the resolution with the option rejected (Phase 3, task 4); stored in `reconciliation` with the plan (task 6) |
| A call counter for Meko's Free-tier allowances | In progress | The demo can't run out of searches. Every Meko call is counted in `meko_call` before it is sent, and Meko Cloud's capped tools stop at `KAKO_MEKO_CLOUD_CEILING`; the metrics page shows what each allowance has left (built Nov 25); the demo datapack's rehearsal on Meko Cloud is Phase 5, task 5 |
| The agents' steps on screen and the what-if loop | In progress | Judges see the agents work: each tool call, each split tried through the engine, and what was rejected. Built: every split is an `agent_step` (`rejected` when the rules refuse it) and `kako ask` prints the conflict, the splits, the choice and the rejected option. Built (Phase 5, task 1): the session screen's "Show the working" under each answer lists every tool call, each specialist's steps under its ask, each split with what was rejected or sent back and why, what each specialist proposed, and the turn's cost; a running turn's steps appear as they are logged |
| Published evidence: agent test set, dreaming's labelled set, single-agent baseline | In progress | Scores with run dates in the README show it isn't one hand-held demo path. Built: the agent test set (22 questions from Sep 15 to Dec 1, each expected number held to the engine in tests, scored in code by `kako test-set`) and the single-agent baseline, recorded on Foundry Nov 24, 2026: specialists 98.1%, single agent 93.9%; recorded again the same day with the longer demo story (tuning log entry 12): specialists 93.3%, single agent 90.7%, with calls, tokens and cost in `data/test-set/results/` and [architecture.md](architecture.md#agents) (Phase 3, tasks 7 and 8). Dreaming's labelled set: 13 sessions, 15 expected proposals, recorded on Foundry Nov 24, 2026: 15 of 15 found (100%), none wrong or unquoted (`kako dream eval`, tuning log entry 11); all three are on the metrics page with their run dates (Phase 5, task 4, Nov 25); the README is Phase 6 |

## Gaps to close

| Gap | Plan |
| --- | --- |
| AMP availability and connectivity on our account | Phase 1 spike; Neon as the fallback |
| Context Gaps (self-learning tools) may not be available on Free | Phase 1 spike: available on Free on Meko Cloud (not on local Meko). Built in Phase 4, task 6; shown on the demo datapack |
| Meko Cloud extracts memories before the household approves them | It can't be turned off (Phase 1 spike). Built: dreaming reads each session's extracted memories as candidates; each is linked to what a person approves or deleted, and `kako dream check` holds V-14 (Phase 4, task 3) |
| Judges may not have an Azure account | Built: `kako demo run` (Phase 3, task 9) needs local Postgres and local Meko only, and replays sessions 2 and 4 and the agent test set from `data/recorded/`. Sessions 1 and 3 join it as each is recorded |
| "Why four specialists, not one agent?" | Built: the single-agent baseline on the agent test set (Phase 3, task 8). Specialists 93.3%, single agent 90.7% (98.1% and 93.9% on the first run), at 109 against 41 model calls and US$0.62 against US$0.49; a small margin from one run each, written up as it is in [architecture.md](architecture.md#agents) |
| Full terms not published | Check before submission |
