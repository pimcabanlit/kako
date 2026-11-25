# Guardrails

What keeps the numbers and the memory honest, and the household in charge.

## No numbers from a model

The engine computes every figure. Agents may only quote figures they were shown. The **number check** reads every number in an answer, its options and the specialists' summaries: each must match an engine figure, a fact, a what-if's amount or a number the household typed. A miss is sent back once; if it fails again, the answer is shown with that number flagged, never hidden. Dreaming may only copy numbers it can quote.

> **In the story · Session 2.** The orchestrator's option B first cited figures from the wrong what-if; code sent it back ("cite at least one figure of rec-W1"), and it fixed the citation before the household saw anything.

## Nothing overwritten

Facts are added and closed, never edited. A database trigger refuses any other change.

> **In the story.** Mara's ₱52,000.00 isn't changed to ₱68,000.00: it's closed on Dec 1, marked replaced, and the new value starts. The Timeline shows both.

## A person decides

Every fact, life event, decision, preference and promotion starts as a proposal with its evidence. Only an adult of the household approves; approving writes exactly what was proposed, once. Promotion asks twice, because it can't be undone.

> **In the story.** Mara approves her own new job on Nov 20; Mara approves the preference and Jun confirms sharing it on Oct 20.

## Every answer traces back

Each recommendation cites at least one engine figure and one other source (a fact, a decision, a memory, a document or the household's words), and its Meko trace.

## Words are data, not orders

What people say, memories and documents reach the agents wrapped as data. Agents have read tools and propose tools only: nothing an agent says can change anything without a person's yes.

## Spending stays capped

A token budget per turn (200,000) and a daily cap (US$3), checked before every model call, with every attempt logged. On Meko Cloud, a counter stops each Free-tier tool at a ceiling (0 unless set for the demo), so rehearsals can't use up the account's lifetime allowances.

## Meko's own extraction

Meko extracts memories from the household's words before anyone approves them. Kako treats them as candidates: each ends linked to an approved fact, or deleted.

## Only on this machine

Until there is sign-in, the API and the web app listen on 127.0.0.1 only, and refuse any other host name.

## Not financial advice

A synthetic household only. No product picks, no tax calculations: Kako declines both. Secrets live in environment variables; `.env` is never committed.
