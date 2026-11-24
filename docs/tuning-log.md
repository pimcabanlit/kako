# Tuning log

A short record of each real model run that changes a prompt, a tool or a bound: what we expected,
what happened, and why. **The prediction is written before the run**, so a surprise is visible as a
surprise and not explained after the fact. Scripted-model tests don't go here; real Foundry runs do.

Each entry: the date (Manila time), the change being tested, the prediction, the run (command,
deployments, tokens, cost from `llm_call`), the result, the root cause of any miss, and the change
it led to.

## Entries

### 1. Session 2 on Foundry, first real run (Nov 24, 2026, 3:20 PM)

- **Change tested:** the first prompts and tools (Phase 3, task 3), on the worked example's
  session-2 question: "Mara here. How hard should we pay down the credit card? Jun thinks ₱4,000
  extra a month is enough and the rest can go to the emergency fund, but I'd rather clear the card
  fast.", as of Sep 15, 2026, before plan v2. Local Meko with the demo's 15 documents.
- **Prediction (written before the run):**
  - The orchestrator asks the debt and savings specialists in one reply, and maybe budget.
  - Each specialist runs one or two what-ifs. Debt tries the whole surplus on the card; at least
    one specialist tries `said:4000` with `rest` to the emergency fund.
  - The answer has two options matching the worked example: A, 9 months and ₱12,460.10; B,
    17 months and ₱24,303.62, with the fund's target in 12 months. `recommended` is empty, because
    no preference or decision existed yet on Sep 15.
  - Most likely misses: a citation refused once (a figure ref without its what-if prefix), then fixed;
    a specialist using a number instead of a spec (refused, then fixed).
  - Cost: about US$0.10 to US$0.25 for the turn; under 60,000 tokens.
- **Run:** `KAKO_MODEL_MODE=record uv run kako ask "…" --on 2026-09-15 --title "Session 2" --seed
  s2:t1`, gpt-5.4 and gpt-5-mini, reasoning effort low. 7 model calls, 30,592 tokens in (11,904
  cached), 2,804 out, **US$0.0359**. 8 agent steps, no refusals. Recording:
  `data/recorded/session-2-run1.json`.
- **Result:**
  - Right: debt and savings asked together; debt ran the split (`said:4000`, `rest`) and all on
    the card (`rest` with the fund at `none`), savings the split. Options A and B carry the worked
    example's figures, all cited from their what-ifs: A ₱12,460.10 of interest (paid off Jun 15,
    2027); B ₱24,303.62, paid off Feb 15, 2028, the fund's target in 12 months. No refused call.
  - Miss 1: **A was recommended**, because "Mara said she would rather clear the card fast" and the
    avalanche strategy. But Mara and Jun disagree in the same message, so the choice is theirs.
  - Miss 2: the debt specialist's summary was long, spoke to the household ("Which do you
    prefer?"), put refs inside its prose, and cited a knowledge-base document (`doc:K4`) for the
    household's own 3-month target, which is a fact (`fact:household.emergency_months_target`).
  - Cost was a third of the low estimate: the prompts are about 4,000 tokens, and the cache served
    the shared prefix from each agent's second call.
- **Root cause:**
  - Miss 1: the orchestrator's rule ("recommend when … the household's own words support it") says
    nothing about two people in the household wanting different things.
  - Miss 2: the specialist prompts don't say who reads the summary, or that the household's own
    settings are facts while documents are general reference.
- **Change made:** see entry 2.

### 2. Session 2 after tuning: disagreement and specialist summaries (Nov 24, 2026)

- **Change tested:**
  - The orchestrator: when people in the household want different things, leave `recommended`
    empty and say what each option does for each of them.
  - Every specialist: the summary is for the orchestrator, two to four sentences, with no questions
    and no refs in the text.
  - The shared rules: the household's own settings are facts, and documents are general reference.
- **Prediction (written before the run):**
  - The same two options with the same figures (A ₱12,460.10, B ₱24,303.62 and 12 months to the
    fund's target), and `recommended` empty.
  - The reply names both Mara's and Jun's view.
  - The debt summary is shorter (under 600 characters), asks no question, and cites
    `fact:household.emergency_months_target` rather than a document, if it cites the target at all.
  - About the same cost as run 1 (US$0.03 to US$0.05).
- **Run:** the same command, recorded to `data/recorded/session-2.json`. 7 model calls, 31,437
  tokens in (11,136 cached), 2,707 out, **US$0.0352**. 9 agent steps, no refusals. Replayed
  strictly afterwards with `KAKO_MODEL_MODE=replay`: the same answer, US$0.
- **Result:**
  - As predicted: the same two options and figures (A 9 months and ₱12,460.10; B 17 months and
    the fund's target in 12 months), `recommended` empty, and the reply names Mara's wish and
    Jun's. B cites `fact:household.emergency_months_target`, not a document. No questions in the
    summaries.
  - Off the prediction: the debt summary was about 720 characters, not under 600, because it
    compared both moves with all four figures (and proposed A). That is fine for the orchestrator,
    which read it and still left the choice to the household.
  - Both specialists now ran both moves (4 what-ifs, against 3 in run 1).
- **Root cause of the miss:** none needed; the length limit is guidance, and code caps a summary
  at 1,500 characters.
- **Change made:** none. Spend so far: US$0.071 of the US$1 Pim approved. Next real runs come with
  task 4 (reconciliation) and the agent test set.
