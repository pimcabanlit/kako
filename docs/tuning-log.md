# Tuning log

A short record of each real model run that changes a prompt, a tool or a bound: what we expected,
what happened, and why. **The prediction is written before the run**, so a surprise is visible as a
surprise and not explained after the fact. Scripted-model tests don't go here; real Foundry runs do.

Each entry: the date (Manila time), the change being tested, the prediction, the run (command,
deployments, tokens, cost from `llm_call`), the result, the root cause of any miss, and the change
it led to.

## Entries

### 1. Session 2 on Foundry, first real run (not yet run)

- **Change tested:** the first prompts and tools (Phase 3, task 3), on the worked example's
  session-2 question: "How hard should we pay down the credit card? Jun thinks ₱4,000 extra a month is
  enough…", as of Sep 15, 2026, before plan v2.
- **Prediction:**
  - The orchestrator asks the debt and savings specialists in one reply, and maybe budget.
  - Each specialist runs one or two what-ifs. Debt tries the whole surplus on the card; at least
    one specialist tries `said:4000` with `rest` to the emergency fund.
  - The answer has two options matching the worked example: A, 9 months and ₱12,460.10; B,
    17 months and ₱24,303.62, with the fund's target in 12 months. `recommended` is empty, because
    no preference or decision existed yet on Sep 15.
  - Most likely misses: a citation refused once (a figure ref without its what-if prefix), then fixed;
    a specialist using a number instead of a spec (refused, then fixed).
  - Cost: about US$0.10 to US$0.25 for the turn; under 60,000 tokens.
- **Run:** _to fill in._
- **Result:** _to fill in._
- **Root cause of any miss:** _to fill in._
- **Change made:** _to fill in._
