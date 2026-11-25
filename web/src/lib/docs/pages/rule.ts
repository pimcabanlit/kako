// "The one rule": the engine calculates, the agents explain and propose, the household decides
// (CLAUDE.md, "The one rule"; docs/concept.md).

import type { DocPage } from "../types.ts";

export const RULE: DocPage = {
  slug: "rule",
  title: "The one rule",
  lead: "The engine calculates, the agents explain and propose, the household decides.",
  sections: [
    {
      id: "three-parts",
      title: "Three parts, three jobs",
      blocks: [
        {
          kind: "table",
          head: ["Who", "Does", "Never"],
          rows: [
            ["The engine", "Works out every peso, month and date from the household's facts", "Guesses or rounds twice"],
            ["The agents", "Read the figures, try what-ifs, explain options and propose changes", "Produce a number of their own, or change anything"],
            ["The household", "Approves facts, decisions, preferences and what to share", "Finds its knowledge changed without a yes"],
          ],
        },
        {
          kind: "story",
          when: "Nov 20",
          text: "Mara says she has a new job at ₱68,000 a month. An agent proposes it with her words as evidence; she approves it; the engine works out that ₱25,050 is now left each month; the agents explain what that could do, and the household picks.",
        },
      ],
    },
    {
      id: "honest-line",
      title: "The honest line",
      blocks: [
        {
          kind: "p",
          text: "Kako's agents investigate, try what-ifs and propose; the engine checks every figure; the household decides. The agents don't negotiate with each other, and they don't learn on their own: dreaming proposes what a session showed, and a person says yes.",
        },
      ],
    },
  ],
  next: [
    { href: "/docs/engine", label: "The engine", text: "how every figure is worked out." },
    { href: "/docs/guardrails", label: "Guardrails", text: "how the rule is held." },
  ],
};
