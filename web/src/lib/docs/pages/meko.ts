// "How Kako uses Meko": each part of Meko's context in Meko's own order, what Kako does with it,
// how far it is built, and where the Villanueva household meets it (Pim approved the mockup, Nov 25).
// Keep it to what is built: a part that isn't says so, with what it will be
// (docs/architecture.md, "How Kako uses each part of Meko").

import type { DocPage } from "../types.ts";

export const MEKO: DocPage = {
  slug: "meko",
  title: "How Kako uses Meko",
  lead: "Every part of Meko's context, followed through one household: the Villanuevas, from August to December 2026.",
  external: { href: "https://docs.mekodata.ai/concepts/datapacks/", label: "Meko's own docs" },
  live: "meko",
  intro: [
    {
      kind: "p",
      text: "Kako is a planner for a household's money. Mara and Jun talk to it in planning sessions; an orchestrator and four specialists answer; an engine works out every peso. **Meko is where Kako keeps the household's context**: what was said, what was learned, what every agent can find, and the trace of how each answer was reached. Postgres keeps the exact numbers. This page shows how each part of Meko's context is used, with the moment in the Villanuevas' story where you can see it.",
    },
  ],
  sections: [
    {
      id: "datapack",
      title: "The household's datapack",
      status: "built",
      blocks: [
        {
          kind: "p",
          text: "The Villanuevas have one datapack. Every call Kako makes names it with `datapack_id`, and every agent speaks as itself: `kako:orchestrator`, `kako:debt`, `kako:savings`, `kako:dreaming`, `kako:upkeep`. It holds:",
        },
        {
          kind: "pack",
          label: "The Villanuevas' datapack",
          parts: [
            { title: "Conversations", status: "built", text: "Sessions 2 and 4, every turn with its plan and reasoning." },
            { title: "Memories", status: "built", text: "One sentence per approved fact, decision and preference." },
            { title: "Collective memory", status: "built", text: "The preference for flexibility, shared with every agent." },
            {
              title: "Knowledge base",
              status: "built",
              text: "Statements, planning rules, reference documents, a decision record.",
            },
            { title: "Traces", status: "built", text: "Every Meko call of every session, under its conversation." },
            { title: "Search log", status: "built", text: "Weak searches turned into questions (Meko Cloud)." },
            { title: "Artifacts", status: "planned", text: "Each plan's report, kept whole." },
            { title: "Postgres (AMP)", status: "planned", text: "The household's facts inside the datapack." },
          ],
        },
      ],
      children: [
        {
          id: "isolation",
          title: "Isolation",
          blocks: [
            {
              kind: "list",
              items: [
                "**One household, one datapack.** Nothing from another household can reach the Villanuevas' answers, and every call carries their `datapack_id`.",
                "**Local first.** Development and tests use local Meko on `127.0.0.1`. Meko Cloud is reached only for the demo, and a call counter stops each Free-tier tool at a ceiling, so rehearsals can't use up the account's lifetime allowances (1,000 conversations, 1,000 of each search).",
                "**Agents by name.** Each agent changes and deletes only the memories it wrote, which Meko enforces.",
              ],
            },
          ],
        },
      ],
    },
    {
      id: "conversations",
      title: "Conversations",
      status: "built",
      blocks: [
        {
          kind: "p",
          text: "Each planning session is one Meko conversation. When Kako answers a turn, it adds the household's words, Kako's reply, the **plan** (the steps taken: the brief, the specialists asked, the reconciliation, the options) and the **reasoning** (the specialists' summaries and how a conflict was resolved), with metadata naming the plan, run and recommendation. Code writes both from what the agents handed in, so Meko and Kako say the same thing. After the session, dreaming reads the turns back from Meko.",
        },
        {
          kind: "story",
          when: "Session 2, Sep 15",
          text: "Mara asks how hard to pay down the card; Jun thinks ₱4,000 extra a month is enough and the rest can go to the emergency fund. The turn kept in Meko carries both specialists' proposals, the conflict between them, and options A and B. That same conversation is what dreaming reads later.",
        },
        { kind: "see", links: [{ href: "/", label: "a session" }] },
      ],
    },
    {
      id: "traces",
      title: "Decision traces",
      status: "built",
      blocks: [
        {
          kind: "p",
          text: "The conversation id is the trace. Every Meko call in a session (the brief's search, a specialist's extra search, the turn being kept) is a step under it. The plan screen and \"Show the working\" link to the turn's trace: Meko Cloud's Observe for the demo, or local Meko's call log, read back by `GET /api/v1/sessions/{id}/trace`. Kako also counts every call in its own table (`meko_call`), so the trace and Kako's records agree.",
        },
        {
          kind: "story",
          when: "Session 4, Nov 20",
          text: "Jun's \"what does it change?\" is answered as a replan. Its trace shows the one search the brief made, what came back, and the turn kept with what changed and why.",
        },
        {
          kind: "see",
          links: [
            { href: "/plans", label: "Plan" },
            { href: "/metrics", label: "Metrics" },
          ],
        },
      ],
    },
    {
      id: "memory",
      title: "Memory",
      status: "built",
      blocks: [
        {
          kind: "p",
          text: "Kako writes one sentence to Meko for each fact, decision and preference a person approved (`memory_add`), naming people and things in full because Meko's search favours named things, with its dates in its words. When a fact is replaced, its sentence is rewritten in the past tense (`memory_update`); when one is withdrawn, its memories are deleted. Meko also extracts memories from the household's words on its own. Kako treats those as **candidates**: each ends linked to a fact a person approved, or deleted.",
        },
        {
          kind: "story",
          when: "Nov 20 → Dec 1",
          text: "After Mara approves her new job, \"In the Villanueva household, from Mar 1, 2026, Mara's salary (take-home pay a month) is ₱52,000.00\" becomes \"… from Mar 1, 2026 until Nov 30, 2026, Mara's salary (take-home pay a month) was ₱52,000.00\", and a new memory says ₱68,000.00 from Dec 1. Meko keeps both; Kako's ledger says which one is true today.",
        },
        { kind: "see", links: [{ href: "/timeline", label: "Timeline" }] },
      ],
    },
    {
      id: "learning",
      title: "Learning and promotion",
      status: "built",
      blocks: [
        { kind: "p", text: "Meko's path from conversations to shared knowledge, and Kako's version of each step:" },
        {
          kind: "flow",
          nodes: [
            { title: "Conversation", text: "raw turns", tone: "meko" },
            { title: "Memories", text: "Meko's candidates", tone: "meko" },
            { title: "Dreaming", text: "Kako's code: quotes, numbers, patterns", tone: "kako" },
            { title: "Approvals", text: "a person says yes", tone: "person" },
            { title: "Collective memory · shared knowledge", text: "every agent finds it", tone: "shared" },
          ],
          arrows: ["extract", "check", "propose", "promote"],
        },
        {
          kind: "p",
          text: "Dreaming runs once after a session ends. It reads the turns and Meko's candidate memories, checks every claim in code (the quote is real, every number is in the quote), and puts proposals in front of the household. Across sessions, code counts the options the household chose: three the same way across at least two sessions make a pattern. Promotion is asked twice, because it can't be undone: a preference goes to collective memory (`memory_promote`), a decision to the knowledge base as a decision record.",
        },
        {
          kind: "story",
          when: "Oct 20",
          text: "Sessions 1, 2 and 3 (Aug, Sep, Oct) each chose the option that keeps cash on hand. Dreaming proposes the preference for flexibility; **Mara approves** it, **Jun confirms** sharing it and Session 1's decision record. In Session 4 the debt specialist cites the preference though nobody mentions it.",
        },
        {
          kind: "see",
          links: [
            { href: "/decisions", label: "Decisions" },
            { href: "/docs/dreaming", label: "Dreaming" },
          ],
        },
      ],
    },
    {
      id: "knowledge",
      title: "Knowledge base",
      status: "built",
      blocks: [
        {
          kind: "p",
          text: "The household's documents go to the datapack's knowledge base: the monthly statements for the card, the car loan, the emergency fund and savings; Kako's planning rules; and Philippine reference documents on 13th-month pay, SSS, Pag-IBIG and emergency funds. Tax is reference only: Kako never calculates it. A decision record promoted from dreaming lands here too. Each turn's brief makes **one** `context_search`, which covers memories, the knowledge base and past conversations together, and cited passages show in the plan's why.",
        },
        {
          kind: "story",
          when: "Session 4, Nov 20",
          text: "When Jun asks what Mara's new job changes, the one search can bring back the November statements, the 13th-month pay reference and Session 1's decision record (\"keep a bigger buffer\"), shared as knowledge on Oct 20.",
        },
      ],
    },
    {
      id: "self-learning",
      title: "Self-learning",
      status: "built",
      blocks: [
        {
          kind: "p",
          text: "Meko logs every `context_search` with how well it scored. Kako turns weak searches (best score under 0.75) into plain questions for the household (\"Kako would like to know…\"). Once an answer is approved and its memory is in Meko, Kako replays the search (`selflearning_verify`) and keeps the score before and after for the Metrics page. Meko Cloud only: local Meko has no self-learning tools.",
        },
        {
          kind: "placeholder",
          label: "Placeholder",
          text: "The demo datapack's first real gap and its score before and after go here once the sessions run on Meko Cloud.",
        },
      ],
    },
    {
      id: "artifacts",
      title: "Artifacts",
      status: "planned",
      blocks: [
        {
          kind: "p",
          text: "Each plan's report will be kept whole as a Meko artifact (`artifact_put`), its hash stored with the plan, so the report the household accepted can be fetched later exactly as it was, and downloaded from the Plan screen.",
        },
        {
          kind: "placeholder",
          label: "Placeholder · not built yet",
          text: "Plan v2 (Sep 15, option B: ₱4,000 on the card, ₱5,050 to the emergency fund) as the first artifact.",
        },
      ],
    },
    {
      id: "postgres",
      title: "Postgres in the datapack",
      status: "planned",
      blocks: [
        {
          kind: "p",
          text: "The household's facts (dated, never overwritten) live in plain Postgres today. The plan is to keep them in the datapack's own Postgres (AMP), next to the rest of the context. A Phase 1 test ran Kako's migrations and health check against AMP from the laptop; what-ifs stay in the engine, in memory, because a Free account's compute (0.5 vCPU) can't query a branch.",
        },
        {
          kind: "placeholder",
          label: "Placeholder · not in use yet",
          text: "The Villanuevas' ledger, with Mara's old salary closed on Nov 30 and the new one opened on Dec 1, inside the datapack.",
        },
      ],
    },
    {
      id: "sharing",
      title: "Sharing and collaboration",
      status: "in-part",
      blocks: [
        {
          kind: "p",
          text: "Mara and Jun share one household datapack. Either can speak in a session, and either can approve the other's changes: every fact, decision, preference and promotion waits for an adult's yes. Promotion is how something one session learned becomes context every agent shares.",
        },
        {
          kind: "story",
          text: "Mara chooses the split in Session 2; Jun accepts plan v3 on Dec 1; Mara approves the preference and Jun confirms sharing it.",
        },
        {
          kind: "placeholder",
          label: "Not pursued",
          text: "Each adult's private memories next to shared household knowledge needs Meko's roles (Viewer, Contributor, Maintainer) on a paid plan. Documented as the production path.",
        },
      ],
    },
    {
      id: "metrics",
      title: "Metrics",
      status: "built",
      blocks: [
        {
          kind: "p",
          text: "The Metrics page reads Meko's `datapack_metrics`: how big the household's whole context is, how much one search saves sending, and how relevant results were. Next to it, Kako's own figures: each turn's brief against the whole context, its model calls, tokens and cost.",
        },
        { kind: "see", links: [{ href: "/metrics", label: "Metrics" }] },
      ],
    },
    {
      id: "where",
      title: "Where Kako keeps what",
      blocks: [
        {
          kind: "table",
          head: ["Kept in", "What", "The Villanuevas' example"],
          rows: [
            ["Postgres", "Exact, dated facts; decisions with every option; plans; approvals", "Mara's salary ₱52,000 until Nov 30, then ₱68,000"],
            ["Meko memory", "One sentence per approved fact, decision, preference", "Mara's old salary, in the past tense"],
            ["Collective memory", "What the household shared with every agent", "The preference for keeping cash on hand"],
            ["Knowledge base", "Documents agents search inside", "The November card statement; 13th-month pay"],
            ["Conversations", "Every turn, with its plan and reasoning", "Session 4: the new job and the replan"],
            ["Artifacts (planned)", "Whole files, fetched by hash", "Plan v2's report"],
          ],
        },
        {
          kind: "p",
          text: "The rule of thumb: **Postgres knows what is true; Meko knows what was said, what was learned, and how each answer was reached.** Meko can hold ₱52,000 and ₱68,000 side by side; Kako decides which one is current and which decisions rested on the old one.",
        },
      ],
      children: [
        {
          id: "story-through-meko",
          title: "The story through Meko",
          blocks: [
            {
              kind: "timeline",
              items: [
                { when: "Aug 15", title: "Session 1", text: "Jun keeps a bigger buffer. A decision record, later shared as knowledge." },
                {
                  when: "Sep 15",
                  title: "Session 2",
                  text: "Mara picks the split (plan v2). A conversation, a trace, memories of the new allocations.",
                },
                { when: "Oct 18", title: "Session 3", text: "Jun keeps the bonus for the trip. The third choice for flexibility." },
                {
                  when: "Oct 20",
                  title: "Dreaming",
                  text: "The pattern becomes a preference; Mara approves, Jun shares it. Collective memory.",
                },
                {
                  when: "Nov 20",
                  title: "Session 4",
                  text: "Mara's new job; Jun's replan. Memory rewritten in the past tense; three decisions to revisit.",
                },
                {
                  when: "Dec 1",
                  title: "Plan v3",
                  text: "₱10,000 on the card, ₱10,000 to the emergency fund, ₱5,050 to the house fund. Placeholder: today it's in the story as approved facts, with no session of its own.",
                  planned: true,
                },
              ],
            },
          ],
        },
      ],
    },
  ],
  next: [
    { href: "/docs/story", label: "The Villanuevas' story", text: "session by session." },
    { href: "/docs/dreaming", label: "Dreaming", text: "how a session becomes proposals." },
    { href: "https://docs.mekodata.ai/concepts/datapacks/", label: "Meko's datapacks", text: "the concepts this page follows." },
  ],
};
