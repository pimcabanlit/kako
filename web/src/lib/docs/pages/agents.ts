// "The agents": the orchestrator and four specialists, the brief, one turn, the bounds, and why
// four specialists rather than one agent (docs/architecture.md, "Agents" and "How one planning
// turn flows"; the test-set scores are tuning log entry 12).

import type { DocPage } from "../types.ts";

export const AGENTS: DocPage = {
  slug: "agents",
  title: "The agents",
  lead: "An orchestrator answers any money question, and asks four specialists when the household needs a plan. They explain and propose; the engine calculates; the household decides.",
  sections: [
    {
      id: "who",
      title: "Who does what",
      blocks: [
        {
          kind: "table",
          head: ["Agent", "Job", "Tools", "Can write"],
          rows: [
            [
              "Orchestrator",
              "Reads the brief, picks the kind of answer, answers it (asking the specialists only for a plan), settles conflicts, proposes facts and life events the household stated",
              "The four specialists, read tools, `get_history`, `get_figures_on`, `read_document`, `calculate`, `run_what_if` (with changes and new items), `propose_change`",
              "Proposals only",
            ],
            ["Budget", "Spending against income; where the surplus comes from", "Read tools, `run_what_if`", "Nothing"],
            ["Debt", "Payoff order and extra payments, respecting the household's preferences", "Read tools, `run_what_if`", "Nothing"],
            ["Savings", "The emergency fund, its runway and target", "Read tools, `run_what_if`", "Nothing"],
            ["Goals", "Goal dates, contributions, trade-offs", "Read tools, `run_what_if`", "Nothing"],
          ],
        },
        {
          kind: "p",
          text: "The orchestrator and dreaming use the stronger model deployment; the specialists a faster one, both on Azure AI Foundry. Every model call goes through one door, the model manager, which checks the turn's budget and the day's cap first.",
        },
      ],
    },
    {
      id: "brief",
      title: "The brief",
      blocks: [
        {
          kind: "p",
          text: "Before any agent runs, code writes one brief of about 3,000 tokens: the key figures, the decisions in force with their reasons, approved preferences, pending proposals, recent life events, in a replan what changed, this session's state, recaps of the household's earlier sessions, and the results of **one** Meko search on what the conversation is about. Every agent starts from it, so answers stay grounded and Meko calls stay few. Agents see stable refs (`debt:credit-card`, `M1`), never database ids.",
        },
      ],
    },
    {
      id: "conversation",
      title: "The conversation",
      blocks: [
        {
          kind: "p",
          text: "A household writes the way people chat: \"Jun\", \"go with B\", \"just give me the simulation\". Each only makes sense with the turns before it, so the orchestrator reads the session's earlier turns as a real conversation before the brief and the new message. **Code compacts it, never a model:** turns stay word for word within a budget (about 12,000 tokens, the last 8 always), older ones become one line each, and the oldest can be read again in full with `read_turns`. Nothing a person said is reworded by a model.",
        },
        {
          kind: "p",
          text: "The brief's session state, kept by code, holds the thread of a long conversation: who wrote this message (so \"I\" and \"my\" have an owner and Kako never asks \"whose?\"), who else wrote, what the conversation is about, the question Kako last asked (so a short reply answers it), the options on the table with the moves behind each (so \"go with B\" can run B again), and the changes filed for a yes. The specialists get this state and a question that stands on its own, never the transcript. Once a session ends, a recap written by code is kept in Meko, so a later session can find it.",
        },
      ],
    },
    {
      id: "any-question",
      title: "Any question",
      blocks: [
        {
          kind: "p",
          text: "A household asks more than where the money should go. Kako answers any money question on one rule: **reading, explaining, working out and trying change nothing; only news an adult approves writes data; every answer shows what it rests on.** It never answers with a flat \"can't\": it declines only real limits (a tax amount, picking an investment product, live prices), says why, and gives what it can.",
        },
        {
          kind: "table",
          head: ["Asked like", "Kind", "How Kako answers"],
          rows: [
            ["\"What's an emergency fund?\"", "General information", "In plain words, citing Kako's guidance documents"],
            ["\"Why is our surplus lower than in October?\"", "Explain", "Today's figures beside another date's, or each value over time"],
            ["\"How much interest did we pay last month?\"", "Look up", "The household's statements and records (`read_document`, `get_history`)"],
            ["\"How much is ₱6,000 a month over a year?\"", "Compute", "`calculate`: the formula worked out in code, with its working shown"],
            ["\"What if my salary goes up by ₱20,000?\"", "Simulate", "`run_what_if` with the fact changed for the run: before and after, nothing saved"],
            ["\"Should we get a cashback card?\"", "Advise", "Pros and cons against their own figures; never a product"],
            ["\"How hard should we pay down the card?\"", "Plan", "The specialists, then 2 to 4 options"],
            ["\"Mara got a new job at ₱72,000.\"", "Record", "`propose_change`, held for an adult's yes"],
          ],
        },
        {
          kind: "p",
          text: "Under each answer, code shows its labels (**General information**, **Scenario, nothing saved**, **Calculated**, **From your documents**), a card for any what-if with what it changed, what Kako assumed and the figures before and after, a card for any sum with its formula and inputs, and the sources it rests on. A value the household never wrote is refused, or used as Kako's assumption and shown as one.",
        },
      ],
    },
    {
      id: "turn",
      title: "One turn",
      blocks: [
        {
          kind: "steps",
          items: [
            { title: "Figures", text: "Code takes the snapshot and the engine's figures." },
            { title: "Brief", text: "Code writes the brief." },
            { title: "Specialists", text: "The orchestrator asks the specialists it needs, side by side." },
            {
              title: "Proposals",
              text: "Each specialist runs a short loop (at most 4 tool calls) and proposes a move resting on one of its own what-ifs, citing a figure and another source.",
            },
            {
              title: "Reconciliation",
              text: "Code puts the proposals together; if they spend more than the surplus or pull in opposite directions, the orchestrator may try up to 3 splits, and only code can say a split fits.",
            },
            { title: "Number check", text: "Every number in the answer is matched to the engine, a fact or the household's words." },
            {
              title: "Kept",
              text: "The answer, its options and every source are saved; the turn goes to Meko with its plan and reasoning.",
            },
          ],
        },
        {
          kind: "story",
          when: "Session 2, Sep 15",
          text: "Mara wants the card cleared fast; Jun wants ₱4,000.00 on it and the rest saved. The debt and savings specialists each propose a move; together they ask for more than the ₱9,050.00 surplus. Kako shows options A and B and recommends neither: Mara and Jun want different things, so the choice is theirs.",
        },
        {
          kind: "note",
          label: "On the laptop",
          text: "One live question in the sandbox (Dec 1, \"how fast can we clear the credit card?\") took 6 model calls (3 by the orchestrator, 3 by the debt specialist) and cost US$0.06. Kako offered three options and recommended B, citing Session 1's decision and the preference for flexibility.",
        },
        { kind: "see", links: [{ href: "/", label: "a session's \"Show the working\"" }] },
      ],
    },
    {
      id: "bounds",
      title: "Bounds",
      blocks: [
        {
          kind: "p",
          text: "At most 4 specialists asked a turn, 4 tool calls each, 1 extra Meko search each, and 3 splits a conflict; a token budget of 200,000 a turn and a daily cap of US$3, both checked before every call, with every attempt logged.",
        },
      ],
    },
    {
      id: "why-four",
      title: "Why four specialists, not one agent",
      blocks: [
        {
          kind: "p",
          text: "Kako's test set (22 household questions, scored in code) ran both ways on Nov 24, 2026, with the same tools and checks:",
        },
        {
          kind: "table",
          head: ["", "Orchestrator and four specialists", "One agent"],
          rows: [
            ["Score", "93.3% (95 of 102 checks)", "90.7% (90 of 102)"],
            ["Model calls", "109", "41"],
            ["Cost of the run", "US$0.62", "US$0.49"],
          ],
        },
        {
          kind: "p",
          text: "The margin is small, so both are reported. Kako keeps the specialists because every \"what if we put ₱X in\" question becomes a traceable option, and each area's rules stay in its own prompt.",
        },
        { kind: "see", links: [{ href: "/metrics", label: "Metrics" }] },
      ],
    },
    {
      id: "prompts",
      title: "Prompts",
      blocks: [
        {
          kind: "p",
          text: "Every prompt starts with the same shared rules and the turn's brief (so the provider's cache serves them to every agent), then the agent's role. The one rule comes first: the engine calculates, the agents explain and propose, the household decides. What people said, memories and documents arrive wrapped as data, never as instructions.",
        },
      ],
    },
    {
      id: "replays",
      title: "The demo replays",
      blocks: [
        {
          kind: "p",
          text: "Demo mode replays recorded model replies, keyed by turn and agent, so judges need no Azure account; a strict replay refuses a reply whose prompt has changed since it was recorded. Asking new questions needs live models.",
        },
      ],
    },
  ],
  next: [
    { href: "/docs/engine", label: "The engine", text: "where the figures come from." },
    { href: "/docs/guardrails", label: "Guardrails", text: "what the agents can't do." },
  ],
};
