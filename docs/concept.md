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

### The household

A synthetic Philippine family, explained in plain terms for judges anywhere.
Amounts are in pesos. Local items such as 13th-month pay, SSS and Pag-IBIG
appear as knowledge-base documents. No real person's data is used.

### Four capabilities

| Capability | What it does |
| --- | --- |
| **Financial Dreaming** | After each session, a background job reviews what was said, extracts what was decided, reconciles it with what is already known, marks what has been superseded, and proposes what should become shared household knowledge. A person approves each promotion. |
| **Decision memory** | Each important decision is stored with its reasoning, the options rejected, the assumptions behind it, and later its outcome and any revision. |
| **Life-event replanning** | When something changes (a new job, a baby, a move), Kako works out which facts and plans are affected, recalculates, asks the specialists to reassess, and explains what changed and why. This is the centre of the live demo. |
| **Specialists that reconcile** | An orchestrator calls the budget, debt, savings and goals specialists as tools and stays accountable for reconciling them. When the debt specialist wants aggressive repayment and the savings specialist wants to keep cash on hand, the conflict and its resolution are visible. |

### Example

Over three sessions the household keeps choosing flexibility over paying debt
down fast. Dreaming notices the pattern and proposes it as a durable household
preference; the household approves. In the next session the debt specialist
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
| Learning | Dreaming reconciles memories and proposes promotions to shared knowledge |
| Knowledge base | Synthetic statements, budgets, planning rules, local reference documents |
| Artifacts | Generated plans and reports, stored next to the session that made them |
| Decision traces | Why each recommendation was made, one trace per conversation |
| Postgres in the datapack (AMP) | The household's structured data; what-ifs as copy-on-write branches, if the Phase 1 test passes |
| Context Gaps | Weak searches turned into questions for the household |

### What Meko already does, and what Kako adds

From reading Meko's docs and source (November 2026):

- Meko extracts facts from the user's messages and adds them. It does not
  update, merge or retire memories, and it drops near-duplicates. Kako adds the
  reconcile and supersede step: which value is current, what it replaced, and
  which plans depended on it.
- Meko's promotion moves a memory into shared knowledge. Kako decides what to
  propose for promotion and asks the household first.
- Meko records every call as a span in a conversation's trace. Kako links each
  recommendation to its trace instead of building its own audit log.
- AMP gives a Postgres database inside the datapack with branches. Kako uses a
  branch for each what-if, so scenarios start from the same household picture.

## Scope

| Tier | What |
| --- | --- |
| Must | Synthetic household with 3+ past sessions; calculation engine; orchestrator and 4 specialists on one Meko context; decision records with reasons and rejected options; life-event replan; trace-backed explanations; dreaming v1 (reconcile, supersede, propose promotions) |
| Should | What-if as an AMP branch; specialist conflict shown on screen; Context Gaps turned into questions for the household |
| Could | Counterfactual from a past fork; per-person privacy; behaviour drift from stated goals |
| Won't | Tax calculations, bank connections, real data, investment product picks |

## The name

Kako is short and unused by other finance apps. In Japanese, 過去 (*kako*)
means "the past"; in casual Tagalog, *kako* is roughly "I said". Both fit a
planner that remembers what you said and why you decided it. (Check both
meanings before using them in the video.)
