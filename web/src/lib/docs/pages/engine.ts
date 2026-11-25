// "The engine": the deterministic code behind every figure (backend/src/kako/engine/,
// docs/data-model.md "Calculations"). Figures checked against `kako figures` and the worked example.

import type { DocPage } from "../types.ts";

export const ENGINE: DocPage = {
  slug: "engine",
  title: "The engine",
  lead: "Every peso, month and date in Kako is worked out here, in code. The agents read its figures; they never calculate.",
  sections: [
    {
      id: "what-it-is",
      title: "What it is",
      blocks: [
        {
          kind: "list",
          items: [
            "**Pure.** Functions from a snapshot of the household's facts to figures. No database, network, clock or randomness: a test (`tests/test_purity.py`) fails the build if one creeps in. The same facts in always give the same figures out.",
            "**Exact.** Money is whole centavos, rates are decimals, and rounding is half up, once, where the formula says.",
            "**Traceable.** Each figure names the facts and other figures it was built from, so the plan's why can go all the way down.",
          ],
        },
      ],
    },
    {
      id: "snapshot",
      title: "The snapshot: two kinds of time",
      blocks: [
        {
          kind: "p",
          text: "A snapshot is the household's facts **true on a date**, **as Kako knew them at a moment**. Facts are never overwritten, so both questions have an answer: what was true then, and what Kako knew then.",
        },
        {
          kind: "story",
          when: "Oct 18",
          text: "The snapshot for Oct 18, 2026, as known at the end of that day, holds 27 facts: Mara's ₱52,000.00 and Jun's ₱48,000.00 take-home, the four expenses, both debts, both savings accounts and the household's rules. The preference for flexibility is dated Oct 18 but was only approved on Oct 20, so it isn't in that snapshot. Asked about Oct 18 with what Kako knows today, it is: that is the difference between when something was true and when Kako learned it.",
        },
      ],
    },
    {
      id: "figures",
      title: "The figures",
      blocks: [
        { kind: "p", text: "About 37 kinds, in five areas:" },
        {
          kind: "table",
          head: ["Area", "Figures"],
          rows: [
            [
              "Cash flow",
              "income, spending, essential spending, minimum payments, surplus a month, savings rate, debt-payment share, 13th-month pay",
            ],
            ["Debts", "balance, rate, months to pay off, payoff date, total interest, order (avalanche or snowball)"],
            ["Savings", "emergency target, months of cover (runway), months to target"],
            ["Goals", "required a month, projected date, months to target, on track"],
            ["Plan", "each allocation a month, what is left unallocated"],
          ],
        },
        {
          kind: "story",
          when: "Dec 1, 2026",
          text: "Income ₱116,000.00; surplus ₱25,050.00, all of it planned. Credit card paid off Jul 1, 2027 (7 months), ₱9,358.80 of interest still to pay; car loan Oct 1, 2028 (22 months), ₱38,914.35. Emergency fund: 2.3 months of essential spending, its ₱210,000.00 target in 5 months. House fund: ₱300,000.00 by Dec 1, 2031, on track.",
        },
        { kind: "see", links: [{ href: "/money", label: "Money" }] },
      ],
    },
    {
      id: "debts",
      title: "Paying debts off",
      blocks: [
        {
          kind: "p",
          text: "Each month, for each open debt in the household's order, interest is added (rounded half up), then the payment comes off. The order is the household's rule: **avalanche**, the highest rate first. When a debt is paid off, its whole payment rolls to the next debt from the following month.",
        },
        {
          kind: "story",
          text: "The card (3% a month) goes first. When it is gone in Jul 2027, its ₱12,550.00 rolls onto the car loan: from Aug 2027 the car loan gets ₱24,950.00 a month instead of ₱12,400.00, which is why it ends on Oct 1, 2028. The Money screen's amortization tables show every month.",
        },
      ],
    },
    {
      id: "what-ifs",
      title: "What-ifs",
      blocks: [
        {
          kind: "p",
          text: "A what-if runs the engine on the same snapshot with different monthly allocations, in memory, and is never written as a fact. An agent names each amount as a spec, never a number it worked out: `none`, `rest` (the rest of the surplus, worked out in code), `figure:<ref>`, `fact:<ref>` or `said:<amount>` (an amount the household typed). Code refuses a what-if that spends more than the surplus.",
        },
        {
          kind: "story",
          when: "Session 2, Sep 15",
          text: "Paying only the minimums, the card is paid off on Aug 15, 2030, with ₱111,635.47 of interest. Option A (all ₱9,050.00 on the card): Jun 15, 2027, ₱12,460.10. Option B (₱4,000.00 on the card, ₱5,050.00 to the emergency fund): Feb 15, 2028, ₱24,303.62, and the fund reaches its target in 12 months.",
        },
      ],
    },
    {
      id: "runs",
      title: "Runs and what changed",
      blocks: [
        {
          kind: "p",
          text: "A run is the engine's figures for one snapshot, stored with the snapshot's hash; if nothing changed, the last run is reused. Comparing two runs (F-DIFF-1) gives what moved, the facts behind it, and the decisions whose facts were replaced or withdrawn: **to revisit**.",
        },
        {
          kind: "story",
          when: "Session 4, Nov 20",
          text: "Against the run of Oct 18: take-home ₱100,000.00 → ₱116,000.00; surplus ₱9,050.00 → ₱25,050.00; the car loan 31 months → 22. All three decisions rested on Mara's old salary, so all three are to revisit.",
        },
        { kind: "see", links: [{ href: "/plans", label: "Plan" }, { href: "/decisions", label: "Decisions" }] },
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
          text: "What-ifs change how the monthly surplus is split. They can't yet try a one-off amount (the ₱48,000.00 13th-month pay), a change in spending or a change in income without recording it first.",
        },
      ],
    },
  ],
  next: [
    { href: "/docs/agents", label: "The agents", text: "who reads these figures, and how." },
    { href: "/docs/guardrails", label: "Guardrails", text: "the number check that holds them to it." },
  ],
};
