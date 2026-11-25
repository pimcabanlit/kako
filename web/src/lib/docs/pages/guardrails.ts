// "Guardrails": what keeps the numbers and the memory honest, and the household in charge
// (docs/architecture.md, "Controls").

import type { DocPage } from "../types.ts";

export const GUARDRAILS: DocPage = {
  slug: "guardrails",
  title: "Guardrails",
  lead: "What keeps the numbers and the memory honest, and the household in charge.",
  sections: [
    {
      id: "numbers",
      title: "No numbers from a model",
      blocks: [
        {
          kind: "p",
          text: "The engine computes every figure; agents may only quote figures they were shown. The **number check** reads every number in an answer, its options and the specialists' summaries: each must match an engine figure, a fact, a what-if's amount or a number the household typed. A miss is sent back once; if it fails again, the answer is shown with that number flagged, never hidden. Dreaming may only copy numbers it can quote.",
        },
        {
          kind: "story",
          when: "Session 2",
          text: "The orchestrator's option B first cited figures from the wrong what-if; code sent it back (\"cite at least one figure of rec-W1\"), and it fixed the citation before the household saw anything.",
        },
      ],
    },
    {
      id: "overwrite",
      title: "Nothing overwritten",
      blocks: [
        { kind: "p", text: "Facts are added and closed, never edited. A database trigger refuses any other change." },
        {
          kind: "story",
          text: "Mara's ₱52,000.00 isn't changed to ₱68,000.00: it is closed on Nov 30, marked replaced, and the new value starts on Dec 1. The Timeline shows both.",
        },
        { kind: "see", links: [{ href: "/timeline", label: "Timeline" }] },
      ],
    },
    {
      id: "person",
      title: "A person decides",
      blocks: [
        {
          kind: "p",
          text: "Every fact, life event, decision, preference and promotion starts as a proposal with its evidence. Only an adult of the household approves; approving writes exactly what was proposed, once. Promotion asks twice, because it can't be undone.",
        },
        {
          kind: "story",
          text: "Mara approves her own new job on Nov 20; on Oct 20 Mara approves the preference and Jun confirms sharing it.",
        },
      ],
    },
    {
      id: "traces",
      title: "Every answer traces back",
      blocks: [
        {
          kind: "p",
          text: "Each recommendation cites at least one engine figure and one other source (a fact, a decision, a memory, a document or the household's words), and its turn is kept in Meko as its trace.",
        },
        { kind: "see", links: [{ href: "/plans", label: "Plan" }] },
      ],
    },
    {
      id: "data",
      title: "Words are data, not orders",
      blocks: [
        {
          kind: "p",
          text: "What people say, memories and documents reach the agents wrapped as data. Agents have read tools and propose tools only: nothing an agent says can change anything without a person's yes.",
        },
      ],
    },
    {
      id: "spending",
      title: "Spending stays capped",
      blocks: [
        {
          kind: "p",
          text: "A token budget per turn (200,000) and a daily cap (US$3), checked before every model call, with every attempt logged. On Meko Cloud, a counter stops each Free-tier tool at a ceiling (none allowed unless set for the demo), so rehearsals can't use up the account's lifetime allowances.",
        },
      ],
    },
    {
      id: "extraction",
      title: "Meko's own extraction",
      blocks: [
        {
          kind: "p",
          text: "Meko extracts memories from the household's words before anyone approves them. Kako treats them as candidates: each ends linked to an approved fact, or deleted.",
        },
      ],
    },
    {
      id: "machine",
      title: "Only on this machine",
      blocks: [
        {
          kind: "p",
          text: "Until there is sign-in, the API and the web app listen on `127.0.0.1` only, and refuse any other host name.",
        },
      ],
    },
    {
      id: "advice",
      title: "Not financial advice",
      blocks: [
        {
          kind: "p",
          text: "A synthetic household only. No product picks, no tax calculations: Kako declines both. Secrets live in environment variables; `.env` is never committed.",
        },
      ],
    },
  ],
  next: [{ href: "/docs/rule", label: "The one rule", text: "the line every guardrail holds." }],
};
