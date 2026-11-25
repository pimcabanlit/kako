// "The Villanuevas' story": the synthetic household every page anchors to, in the order it
// happened (docs/data-model.md, "Worked example" and "Demo dataset"). Every amount is the engine's.

import type { DocPage } from "../types.ts";

export const STORY: DocPage = {
  slug: "story",
  title: "The Villanuevas' story",
  lead: "A synthetic household, followed from August to December, that every page of these docs points back to.",
  sections: [
    {
      id: "household",
      title: "The household",
      blocks: [
        {
          kind: "p",
          text: "Mara (34) and Jun (36) live in the Philippines with their daughter Lia (5). They plan in pesos, with 13th-month pay, SSS and Pag-IBIG as part of ordinary life. Nothing about them is real: every person, amount and statement is made up for the demo.",
        },
        {
          kind: "table",
          head: ["On Sep 15, 2026", "Amount"],
          rows: [
            ["Take-home pay a month (Mara ₱52,000, Jun ₱48,000)", "₱100,000"],
            ["Spending a month, of which essential ₱70,000", "₱76,000"],
            ["Minimum payments (credit card ₱2,550, car loan ₱12,400)", "₱14,950"],
            ["Left a month after spending and minimum payments", "₱9,050"],
            ["Credit card, at 3% a month", "₱85,000"],
            ["Car loan, at 9% a year", "₱420,000"],
            ["Emergency fund, 2.1 months of essential spending", "₱150,000"],
          ],
        },
      ],
    },
    {
      id: "timeline",
      title: "What happened",
      blocks: [
        {
          kind: "timeline",
          items: [
            {
              when: "Aug 15",
              title: "Session 1: a bigger buffer",
              text: "Jun is asked whether to pay the car loan early or keep a bigger buffer. \"We'd rather have a bigger cash buffer.\"",
            },
            {
              when: "Sep 15",
              title: "Session 2: the debt question",
              text: "Mara asks how hard to pay down the card. Option A puts all ₱9,050 on it (paid off in 9 months, ₱12,460.10 of interest); option B splits it, ₱4,000 on the card and ₱5,050 to the emergency fund (17 months, ₱24,303.62). Mara chooses B: \"Lia starts school and we want cash on hand.\" That is plan v2.",
            },
            {
              when: "Oct 18",
              title: "Session 3: the trip",
              text: "Jun keeps the bonus as cash for the family trip rather than putting it all on the card.",
            },
            {
              when: "Oct 20",
              title: "Dreaming finds a pattern",
              text: "Three choices for cash on hand across three sessions: dreaming proposes a preference for flexibility. Mara approves it, Jun confirms sharing it, and every agent can now find it.",
            },
            {
              when: "Nov 16",
              title: "The November statements",
              text: "The card is down to ₱76,880.00, the car loan to ₱401,430.63, and the emergency fund up to ₱160,100. Each balance replaces the last; none is overwritten.",
            },
            {
              when: "Nov 20",
              title: "Session 4: Mara's new job",
              text: "Mara starts a new job on Dec 1 at ₱68,000 take-home and approves the change. Jun asks what it changes. Kako replans as of Dec 1 against the Oct 18 decision, lists the three earlier decisions to revisit because each rested on Mara's old salary, and its debt specialist cites the preference for flexibility.",
            },
            {
              when: "Dec 1",
              title: "Plan v3",
              text: "Take-home ₱116,000, ₱25,050 left a month. ₱10,000 on the card (paid off in 7 months), ₱10,000 to the emergency fund (its 3-month target in 5 months, not 12), and ₱5,050 a month to a new house fund. Putting all ₱25,050 on the card would clear it in 3 months; it was set aside as against the household's preference.",
              planned: true,
            },
          ],
        },
      ],
    },
    {
      id: "what-it-shows",
      title: "What the story shows",
      blocks: [
        {
          kind: "list",
          items: [
            "**Nothing is overwritten.** Mara's old salary is closed on Nov 30, not edited, so \"why is this different from before?\" has an answer.",
            "**The engine calculates.** Every amount above comes from code, checked to the centavo in a test; the agents explain and propose.",
            "**The household decides.** Each change, decision, preference and sharing waited for an adult's yes.",
            "**Context carries over.** A choice made in August shapes the advice in November, through Meko.",
          ],
        },
        {
          kind: "placeholder",
          text: "Plan v3 is in the story as approved facts on Dec 1, without a session of its own: the step from Mara's new job to the new split isn't shown yet.",
        },
        {
          kind: "see",
          links: [
            { href: "/timeline", label: "Timeline" },
            { href: "/decisions", label: "Decisions" },
            { href: "/money", label: "Money" },
          ],
        },
      ],
    },
  ],
};
