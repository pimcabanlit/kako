# Kako concept

Kako is the household financial planner that learns why. It is our entry for
ContextCon 2026, Challenge 05: "The Planner That Remembers".

## The problem

Financial planning is a long relationship, but most AI assistants forget
everything when the session ends. A household has to re-explain its income,
debts, goals and life events every time, and the advice ignores what was decided
before.

Remembering facts is not enough. Facts change: income goes up, a family moves,
a target is revised. A memory that holds "income ₱100,000" and "income
₱120,000" side by side does not know which one is current, which plan was built
on the old figure, or why a recommendation was later reversed.

Planning also spans several areas (budget, debt, savings, goals) that should
work from the same picture. Specialists that each give sensible advice on their
own can contradict each other. And money advice has to be explainable.

## What Kako does

Kako's question is not "what should you do with your money?" It is:

> Given everything we've learned about you, what should you do now, and why is
> that different from before?

The honest one-line description, used in the video and the README:

> Kako's agents investigate, try what-ifs and propose. The engine checks every
> figure. The household decides.

And the line that sets Kako apart from Meko on its own:

> Meko remembers what you said. Kako works out which of it is still true, and
> asks you.

### The household

A synthetic Philippine family, explained in plain terms for judges anywhere.
Amounts are in pesos. Local items such as 13th-month pay, SSS and Pag-IBIG
appear as knowledge-base documents. No real person's data is used.

### Four capabilities

| Capability | What it does |
| --- | --- |
| **Financial Dreaming** | After each session, a background job reviews what was said (including the memories Meko extracted on its own), picks out what was decided, reconciles it with what is already known, marks what has been superseded, and proposes what should become shared household knowledge. Patterns are counted in code, not judged by a model. A person approves each promotion. |
| **Decision memory** | Each important decision is stored with its reasoning, the options rejected, the assumptions behind it, and later its outcome and any revision. |
| **Life-event replanning** | When something changes (a new job, a baby, a move), Kako works out which facts and plans are affected, recalculates, asks the specialists to reassess, and explains what changed and why. This is the centre of the live demo. |
| **Specialists that reconcile** | An orchestrator calls the budget, debt, savings and goals specialists as tools and stays accountable for reconciling them. Code finds the conflict (the debt specialist wants aggressive repayment, the savings specialist wants to keep cash on hand); the orchestrator tries other splits through the engine, picks one with the household's preferences, and shows the option it rejected. Each specialist's steps are visible. |

### What the AI does, and what code does

| The AI (agents) | Code (engine and rules) |
| --- | --- |
| Understands what the household says and proposes fact changes and life events | Checks every number in a proposal against the household's own words |
| Chooses which specialists to ask and which what-ifs are worth trying | Computes every figure for every what-if |
| Weighs options that all fit, using past decisions, their reasons, preferences and planning rules | Finds conflicts: over-allocation, opposite moves, missed goal dates |
| Explains in plain words why the plan differs from the last one | Blocks any number the engine did not produce (the number check) |
| Picks claims out of a finished session for dreaming | Counts choices to find a preference pattern; decides what is current |

The orchestrator and specialists are agentic: they choose their own tool calls within bounds. Dreaming
is a fixed workflow with one model step (extraction). Kako never claims more than that.

### Example

Over three sessions the household (Mara in some sessions, Jun in others) keeps
choosing flexibility over paying debt down fast. Dreaming counts those choices,
finds the pattern and proposes it as a durable household preference; the
household approves. In the next session the debt specialist
retrieves that preference and adjusts its advice, although nobody told it to.
Then the household reports a new job. Kako records the new income without
erasing the old one, recalculates, and answers: here is the new plan, here is
what changed from the last one, and here are the memories and figures behind it.

## Principles

1. **The engine calculates, the agents explain and propose, the household
   decides.** Every peso figure (cash flow, debt payoff, savings runway, goal
   dates) comes from deterministic code. Agents never do the maths.
2. **Nothing is silently overwritten.** Every fact keeps its source, the date it
   took effect, and what replaced it.
3. **Dreaming proposes, a person approves.** Nothing becomes shared household
   knowledge without a yes.
4. **Every recommendation traces back** to the memories, documents and
   calculations behind it.
5. **Not financial advice.** Synthetic data only, and the app says so.

## Built on Meko

Every ContextCon project uses Meko as its context layer, and "Use of Meko" is
30% of the score. Kako gives each part of Meko a visible job:

| Meko part | Kako's use |
| --- | --- |
| Conversations | Planning sessions over time, the raw material for dreaming |
| Memory | Goals, preferences, constraints, life events and past decisions |
| Learning | Dreaming reconciles Meko's extracted memories and Meko's own Learnings with what is known, and proposes promotions: a preference to collective memory, a decision record to shared knowledge |
| Knowledge base | Synthetic statements, budgets, planning rules, local reference documents |
| Artifacts | Generated plans and reports, stored next to the session that made them |
| Decision traces | Why each recommendation was made, one trace per conversation |
| Postgres in the datapack (AMP) | The household's structured data; what-ifs as copy-on-write branches, if the Phase 1 test passes |
| Self-learning (Context Gaps) | A weak search becomes a question for the household; once answered, Meko's replay shows the search improved |

### What Meko already does, and what Kako adds

From reading Meko's docs and source (November 2026):

- Meko extracts facts from the user's messages and adds them. It does not
  update, merge or retire memories, and it drops near-duplicates. Local Meko
  returns both "₱100,000" and "₱120,000" for the same salary (tested). Kako adds
  the reconcile and supersede step: which value is current, what it replaced,
  and which plans depended on it. On Meko Cloud, extraction runs on its own, so
  Kako treats extracted memories as candidates the household approves.
- Meko's promotion moves a memory into shared knowledge. Kako decides what to
  propose for promotion and asks the household first.
- Meko records every call as a span in a conversation's trace. Kako links each
  recommendation to its trace instead of building its own audit log.
- AMP gives a Postgres database inside the datapack with branches. Kako uses a
  branch for each what-if, so scenarios start from the same household picture.

## Scope

| Tier | What |
| --- | --- |
| Must | Synthetic household with 3+ past sessions, both adults taking part; calculation engine; orchestrator and 4 specialists on one Meko context; the what-if loop on conflicts; the agents' steps on screen; decision records with reasons and rejected options; life-event replan; trace-backed explanations; dreaming v1 (reconcile, supersede, propose promotions); Context Gaps turned into questions, if Meko's self-learning tools are available to us; a demo mode that runs without an Azure account |
| Should | What-if as an AMP branch; specialist conflict drawn on screen |
| Could | Counterfactual from a past fork; per-person privacy; behaviour drift from stated goals |
| Won't | Tax calculations, bank connections, real data, investment product picks |

## The name

Kako is short and unused by other finance apps. In Japanese, 過去 (*kako*)
means "the past"; in casual Tagalog, *kako* is roughly "I said". Both fit a
planner that remembers what you said and why you decided it. (Check both
meanings before using them in the video.)
