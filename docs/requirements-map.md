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
| Uses Meko as its context layer | In progress | Every session is a Meko conversation; memories, shared knowledge, knowledge base, artifacts and traces carry the household's context. The toolkit is set up (PRs #3 and #4); the adapter is Phase 2 | 1–4 |
| Any model, any MCP client | Implemented | Azure AI Foundry (OpenAI model deployments) through one model manager; Meko through its MCP server | — |
| Entrants keep ownership | Implemented | All rights reserved; viewing and evaluation only, including by the judges ([LICENSE](../LICENSE)) | — |

## Challenge 05 objectives

| Objective | Status | How Kako meets it | Phase |
| --- | --- | --- | --- |
| **Remember the person:** goals, preferences, constraints and life events as long-term memory | Not started | Goals, preferences, constraints and life events are facts with a validity window and a replacement chain in Postgres, and memories in Meko; durable preferences are promoted to shared knowledge ([data-model.md](data-model.md#facts)) | 2, 4 |
| **Plan across areas:** specialist agents (budget, debt, savings, goals) share one financial context | Not started | One orchestrator calls four specialists as tools; all start from the same brief and the same engine run, and conflicts between them are found in code and resolved in the open ([architecture.md](architecture.md#agents)) | 3 |
| **Adapt over time:** the plan updates when a life event happens | Not started | Life-event replan: the old fact closed and replaced, the decisions that rested on it marked to revisit, a new plan, and a diff that says what changed and why ([architecture.md](architecture.md#how-a-life-event-replans)) | 4 |
| **Explain the advice:** every recommendation traces to the memories and data behind it | Not started | Each recommendation stores its figures, facts, decisions, memories and documents, and its Meko turn; the "why" view shows them and links the Meko trace. The number check blocks any figure the engine did not produce | 3, 5 |

## Meko at the core (from the brief)

| Meko feature | Status | Kako's use | Phase |
| --- | --- | --- | --- |
| Memory: goals, risk profile and past decisions, across sessions | Not started | One memory per approved fact, decision and preference, with Kako's ids in its metadata; replaced facts rewritten in the past tense | 4 |
| Knowledge base: statements, budgets and planning rules (synthetic) | Not started | Synthetic statements (CSV), planning rules and Philippine reference documents (Markdown) for the demo household | 2 |
| Artifacts: generated plans and reports in the datapack | Not started | Each plan report kept with `artifact_put`; its hash stored on the plan | 4 |
| Conversations: planning sessions over time | Not started | One conversation per session, turns with `plan` and `reasoning`; dreaming reads them | 3 |
| Traces: why each recommendation was made | Not started | The session's conversation id is its trace id; every Meko call in a turn is a span; recommendations store their turn | 3 |

## Expected outcomes

| Outcome | Status | How | Phase |
| --- | --- | --- | --- |
| A synthetic household or small-business financial profile | Not started | The Villanueva household: two adults, one child, pesos, statements and reference documents ([data-model.md](data-model.md#demo-dataset)) | 2 |
| A planning agent system connected to Meko | Not started | Orchestrator, four specialists and dreaming, through one Meko adapter | 3–4 |
| 3 or more sessions showing memory carrying over and the plan adapting to a life event | Not started | Sessions in August, September and October, then the new job in session 4 | 4–5 |
| Trace-backed explanations for the key recommendations | Not started | The "why" view and the Meko trace for every recommendation | 3, 5 |
| Encouraged: a what-if scenario planner | Not started | What-ifs in the engine (Must for the engine, screen is a Should); a kept scenario as an AMP branch (Should) | 3, 5 |

## Judging criteria

| Criterion | Weight | Status | What Kako shows | Phase |
| --- | --- | --- | --- | --- |
| Use of Meko | 30% | Not started | Every part of the context has a visible job (rows below) | 2–5 |
| Impact and usefulness | 25% | Not started | A household's real question, "what should we do now, and why is that different from before?", answered with figures it can check; plain language for families anywhere | 4–5 |
| Technical execution | 20% | Not started | A working demo judges can run themselves (demo mode, no Azure account); a pure, tested engine; facts that are never overwritten; CI against local Meko; docs as the source of truth | 1–5 |
| Innovation | 15% | Not started | Memory with history (valid time and record time, replace versus retract); dreaming that proposes and a person who approves; specialists that build on a preference another session taught them | 4 |
| Presentation | 10% | Not started | A video under 5 minutes, a README with setup and measured metrics, these docs | 6 |

### Use of Meko, part by part

| What the judges look for | Status | Kako | Phase |
| --- | --- | --- | --- |
| Conversations | Not started | Sessions as conversations | 3 |
| Memory | Not started | Facts, decisions and preferences as memories that stay current | 4 |
| Learning | Not started | Meko's own self-learning: weak searches become questions, and `selflearning_verify` shows the search improved (a Must if the tools are available). Dreaming reads Meko's extracted memories and Learnings, proposes promotions; the household approves; a preference goes to collective memory, a decision record to shared knowledge | 1, 4 |
| Knowledge | Not started | Statements, rules, reference documents; promoted memories | 2, 4 |
| Artifacts | Not started | Plan reports | 4 |
| Decision tracing | Not started | Turns with `plan` and `reasoning`; spans for every Meko call; linked from each recommendation | 3 |
| Blending data infrastructure: Postgres inside the context | Not started | The household's facts in AMP, Postgres in the datapack, if the Phase 1 test passes; a scenario as an AMP branch (Should) | 1, 5 |
| Sharing context and collaborating to improve it | Not started | Six agents on one datapack; both adults taking part across sessions (one reports the job, the other approves the promotion); the debt specialist acting on a preference the household approved; Context Gaps answered by the household | 4–5 |

## Prizes

| Prize | Status | Kako's case |
| --- | --- | --- |
| Grand prize: collective memory in action, agents that learn, share and improve over time | Not started | Dreaming and promotion make the specialists better each session, **measured**: the session-4 answer scored with and without the promoted preference, and Context Gaps before and after scores, on the metrics page |
| Best use of shared memory: agents that build on each other's learning, with a clear decision-trace story | Not started | The flexibility preference: learned by dreaming from three decisions, approved, promoted, then used by the debt specialist, all traceable |
| Runner-up places | — | Same entry |
| People's choice | Not started | The video and a short post |

## Submission requirements

| Requirement | Status | How | Phase |
| --- | --- | --- | --- |
| Demo video under 5 minutes, linked | Not started | Storyboard in [build-plan.md](build-plan.md#video-storyboard) | 6 |
| Public (or open-source) GitHub repository with setup instructions | In progress | The repository is public; setup instructions come with the code | 1–6 |
| Documentation (optional): architecture, how Kako uses Meko, measured token or relevance metrics | In progress | These docs; the metrics page and its numbers in the README | 1, 5–6 |
| Repository licence checked against the full terms | Not started | Check when the terms are published; switch to Apache-2.0 only if they require open source | 6 |
| Demo datapack and artifacts available through judging | Not started | Seeded on Meko Cloud; touched before judging (Free-tier artifacts expire after 30 days unused) | 5–6 |

## Beyond the brief

| Feature | Status | Why it matters |
| --- | --- | --- |
| Two kinds of time: when something was true and when Kako learned it | Not started | Explains an old plan exactly as it was made, and tells a change in life from a corrected mistake |
| Decisions keep their rejected options and their assumptions | Not started | When an assumption is replaced, the decision is flagged to revisit |
| The number check | Not started | No figure reaches the household unless the engine produced it |
| Reconciliation rules in code | Not started | Specialist conflicts are found by arithmetic, not by hoping a model notices |
| A call counter for Meko's Free-tier allowances | Not started | The demo can't run out of searches |
| The agents' steps on screen and the what-if loop | Not started | Judges see the agents work: each tool call, each split tried through the engine, and what was rejected |
| Published evidence: agent test set, dreaming's labelled set, single-agent baseline | Not started | Scores with run dates in the README show it isn't one hand-held demo path |

## Gaps to close

| Gap | Plan |
| --- | --- |
| AMP availability and connectivity on our account | Phase 1 spike; Neon as the fallback |
| Context Gaps (self-learning tools) may not be available on Free | Phase 1 spike; a Must if available, otherwise documented as the production path |
| Meko Cloud extracts memories before the household approves them | Phase 1 spike (can it be turned off?); dreaming treats extracted memories as candidates either way (V-14) |
| Judges may not have an Azure account | Demo mode with recorded responses (Phase 3) |
| "Why four specialists, not one agent?" | Single-agent baseline on the agent test set (Phase 3), both scores published |
| Full terms not published | Check before submission |
