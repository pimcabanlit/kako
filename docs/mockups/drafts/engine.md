# The engine

Every peso, month and date in Kako is worked out here, in code. The agents read its figures; they never calculate.

## What it is

- **Pure.** Functions from a snapshot of the household's facts to figures. No database, network, clock or randomness: a test (`tests/test_purity.py`) fails the build if one creeps in. The same facts in always give the same figures out.
- **Exact.** Money is integer centavos, rates are decimals. Nothing is rounded until a figure is shown.
- **Traceable.** Each figure names the facts and other figures it was built from, so the plan's "why" can go all the way down.

## The snapshot: two kinds of time

A snapshot is the household's facts **true on a date**, **as Kako knew them at a moment**.

> **In the story.** The snapshot for Oct 18, 2026, as known at the end of that day, holds 27 facts: Mara's ₱52,000.00 and Jun's ₱48,000.00 take-home, the four expenses, both debts, both savings accounts and the house rules. The preference for flexibility is dated Oct 18 but was only approved on Oct 20, so it isn't in that snapshot. Asked about Oct 18 with what Kako knows today, it is: that's the difference between when something was true and when Kako learned it.

## The figures

About 37 kinds, in five areas:

| Area | Figures |
| --- | --- |
| Cash flow | income, spending, essential spending, minimum payments, surplus a month, savings rate, debt-payment share, 13th-month pay |
| Debts | balance, rate, months to pay off, payoff date, total interest, order (avalanche or snowball) |
| Savings | emergency target, months of cover (runway), months to target |
| Goals | required a month, projected date, months to target, on track |
| Plan | each allocation a month, what is left unallocated |

> **In the story · Dec 1, 2026.** Income ₱116,000.00; surplus ₱25,050.00, all of it planned. Credit card paid off Jul 1, 2027 (7 months), ₱9,358.80 interest still to pay; car loan Oct 1, 2028 (22 months), ₱38,914.35. Emergency fund: 2.3 months of essentials, target ₱210,000.00 in 5 months. House fund: ₱300,000.00 by Dec 1, 2031, on track.

## Paying debts off

Each month, for each open debt in the household's order: interest is added (rounded half up), then the payment comes off. The order is the household's rule: **avalanche**, the highest rate first. When a debt is paid off, its whole payment rolls to the next debt from the following month.

> **In the story.** The card (3% a month) goes first. When it's gone in Jul 2027, its ₱12,550.00 rolls onto the car loan: from Aug 2027 the car loan gets ₱24,950.00 a month instead of ₱12,400.00, which is why it ends Oct 1, 2028.

The month-by-month schedule behind these figures is what the Money tab's amortization tables show.

## What-ifs

A what-if runs the engine on the same snapshot with different monthly allocations, in memory, and is never written as a fact. An agent names each amount as a spec, never a number it worked out: `none`, `rest` (the rest of the surplus, worked out in code), `figure:<ref>`, `fact:<ref>` or `said:<amount>` (an amount the household typed). Code refuses a what-if that spends more than the surplus.

> **In the story · Session 2, Sep 15.** Today's plan pays only the minimums: card paid off Aug 15, 2030, ₱111,635.47 interest. Option A (all ₱9,050.00 on the card): Jun 15, 2027, ₱12,460.10. Option B (₱4,000.00 on the card, ₱5,050.00 to the emergency fund): Feb 15, 2028, ₱24,303.62, and the fund reaches its target in 12 months.

## Runs and what changed

A run is the engine's figures for one snapshot, stored with the snapshot's hash; if nothing changed, the last run is reused. Comparing two runs (F-DIFF-1) gives what moved, the facts behind it, and the decisions whose facts were replaced or withdrawn: **to revisit**.

> **In the story · Session 4.** Against the run of Oct 18: take-home ₱100,000.00 → ₱116,000.00; surplus ₱9,050.00 → ₱25,050.00; car loan 31 → 22 months. All three decisions rested on Mara's old salary, so all three are to revisit.

## Not yet

What-ifs change how the monthly surplus is split. They can't yet try a one-off amount (Jun's ₱48,000.00 bonus), a change in spending or a change in income without recording it first. *Planned.*
