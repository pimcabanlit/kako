// "Dreaming": the background job after a session (backend/src/kako/dreaming/,
// docs/architecture.md "How dreaming works").

import type { DocPage } from "../types.ts";

export const DREAMING: DocPage = {
  slug: "dreaming",
  title: "Dreaming",
  lead: "After a session ends, Kako rereads it and proposes what the household said that Kako doesn't hold yet, and the patterns in their decisions. Nothing is learned until a person says yes.",
  sections: [
    {
      id: "when",
      title: "When it runs",
      blocks: [
        {
          kind: "p",
          text: "A session ends when someone ends it (the **End session** button, the API or `kako dream end`); there is no timer. Ending it refuses more turns and queues one dreaming run, once. `kako dream run` works through the queue, oldest first, and runs a failed run again. Demo mode runs it for you.",
        },
      ],
    },
    {
      id: "steps",
      title: "What it does",
      blocks: [
        {
          kind: "steps",
          items: [
            {
              title: "Read",
              text: "The session's turns from Meko, the household's facts and life events, and the memories Meko extracted from those turns on its own, which Kako treats as candidates.",
            },
            {
              title: "Extract",
              text: "One model call, one tool (`submit_claims`): each thing the household said, its exact quote, the day it takes effect. The model copies; it never calculates, and reads only the household's words.",
            },
            {
              title: "Check, in code",
              text: "The quote must be in the session word for word; every number in a claim must be in its quote. A claim that fails is refused, with why.",
            },
            {
              title: "Compare",
              text: "With what Kako holds on that day: the same (dropped), new, a replacement, a correction, or a conflict (nothing proposed; Kako asks).",
            },
            {
              title: "Patterns",
              text: "Code counts the household's decisions by what the chosen option leans to. Three the same way, across at least two sessions, with none the other way, make a preference to propose.",
            },
            {
              title: "Promotion",
              text: "An approved preference, or a decision still in force two sessions later, is offered for sharing with every agent, once, and asked twice because it can't be undone.",
            },
            { title: "Propose", text: "Everything goes to the household with its evidence: the quote, the turn, who said it." },
            { title: "Settle Meko's candidates", text: "Each ends linked to a fact a person approved, or deleted." },
          ],
        },
        {
          kind: "story",
          when: "Oct 20",
          text: "Session 1 (keep a bigger buffer), Session 2 (the split) and Session 3 (keep the bonus for the trip) each chose the option that keeps cash on hand. Dreaming proposes the preference for flexibility; **Mara approves** it; **Jun confirms** sharing it, and Session 1's decision record. In Session 4 the debt specialist cites it though nobody mentions it.",
        },
        {
          kind: "story",
          when: "Nov 20",
          text: "Mara's new job is proposed during Session 4 itself. When dreaming reads that session, it finds the same words and reports them as already proposed: never twice.",
        },
        {
          kind: "see",
          links: [
            { href: "/decisions", label: "Decisions" },
            { href: "/timeline", label: "Timeline" },
          ],
        },
      ],
    },
    {
      id: "tested",
      title: "How it's tested",
      blocks: [
        {
          kind: "p",
          text: "A labelled set of scripted sessions, with the proposals a person would expect, scored in code for what dreaming found, missed and wrongly proposed. It passes at 90% found, with no number that isn't in its quote.",
        },
      ],
    },
    {
      id: "not-yet",
      title: "Not yet",
      status: "planned",
      blocks: [
        {
          kind: "placeholder",
          label: "Planned",
          text: "Nothing runs the queue in the background, and a session nobody ends stays open: a small worker, and a gentle \"end this session?\" after a quiet spell.",
        },
      ],
    },
  ],
  next: [
    { href: "/docs/meko#learning", label: "Learning and promotion", text: "where dreaming meets Meko." },
    { href: "/docs/guardrails", label: "Guardrails", text: "why nothing is learned without a yes." },
  ],
};
