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

### 3. Session 2 with the reconciliation rules (Nov 24, 2026)

- **Change tested:** Phase 3, task 4. Once two or more specialists propose a move, code puts their
  proposals together (`rec-W1`) and tells the orchestrator what the rules found, in a note between
  its rounds; while a conflict is open its `run_what_if` calls are splits (at most 3), and
  `submit_answer` needs a `resolution`. The orchestrator's prompt has a new "Conflicts" section.
  Same question, date and command as entries 1 and 2.
- **Prediction (written before the run):**
  - Debt and savings are asked together, as in run 2. If debt proposes all on the card and savings
    the split, the rules find an over-allocation: ₱9,050 on the card and ₱5,050 to the fund,
    ₱5,050 a month over the surplus. If both propose the split, they fit together and no conflict
    is reported.
  - With the conflict, the orchestrator tries no split or one (the split already exists as a
    specialist's what-if), and resolves with `what_if` and `rejected` both "", because Mara and Jun
    disagree; `recommended` stays empty. Options A and B carry the same figures as run 2.
  - Most likely miss: one refused `submit_answer` (a missing or inconsistent resolution, such as a
    chosen split without recommending it), then fixed on the next call.
  - Cost: US$0.04 to US$0.06 (one or two more orchestrator calls than run 2).
- **Run:** the same command, recorded to `data/recorded/session-2-run3.json`. 6 model calls, 27,520
  tokens in (22,680 cached), 2,538 out, **US$0.0244**. 8 agent steps, no refusals.
- **Result:**
  - As predicted: debt proposed all on the card (its second what-if, `debt1-W2`) and savings the
    split, so the rules found the over-allocation (₱9,050 and ₱5,050 together, ₱5,050 a month over),
    and the orchestrator left the choice to the household: no split tried, `what_if` and
    `rejected` both "", `recommended` empty. The two options carry run 2's figures (17 months and
    12 months to the fund's target; 9 months and ₱12,460.10).
  - No refused call, so the predicted miss didn't happen. Cost was below the range: one fewer
    model call than run 2 (each specialist called once fewer) and more of the prefix cached.
  - Off the prediction: the resolution's reason ends with "Sources: figure:cashflow.monthly_surplus,
    said, fact:preference.debt_strategy". The household reads that text, and refs mean nothing to it.
- **Root cause:** the new "Conflicts" section says what the reason must name, not how it is written;
  the rule against refs in text was only in the specialists' prompts.
- **Change made:** the orchestrator's prompt says the household reads the reason: plain words,
  figures as the tools write them, no refs. See entry 4.

### 4. Session 2, the resolution's reason in plain words (Nov 24, 2026)

- **Change tested:** the sentence on the reason above; nothing else changed.
- **Prediction (written before the run):** the same conflict and the same resolution (left to the
  household, `recommended` empty, 0 or 1 splits); the reason has no `figure:`, `fact:` or `said`
  ref in it. Cost US$0.02 to US$0.04.
- **Run:** the same command, recorded to `data/recorded/session-2.json` (it replaces run 2's
  recording, which the new note no longer replays; run 2's is in the git history). 8 model calls,
  36,857 tokens in (30,720 cached), 3,292 out, **US$0.0308**. 9 agent steps. Replayed strictly
  afterwards with `KAKO_MODEL_MODE=replay`: the same answer, US$0.
- **Result:**
  - As predicted: the same over-allocation, left to the household with `recommended` empty and no
    split tried; the reason is plain words with no refs ("Both split choices fit the ₱9,050.00
    monthly surplus. Mara asked to clear the credit card fast, while Jun wants ₱4,000.00 extra on
    the card and the rest to the emergency fund, so the choice is yours."). The reply now says which
    option suits whose priority.
  - Off the prediction: the debt specialist's `submit_proposal` was refused twice before it passed,
    once for citing `said:` with the whole message after it and once for `memory:K4` (a document,
    `doc:K4`). Code's refusals named the fix each time. This is the fast model's variance, not the
    orchestrator change; it cost two small calls (US$0.002).
- **Root cause of the miss:** the shared rules list `said` among the citations without saying it
  stands alone; nothing in this change touched it.
- **Change made:** none now. The agent test set (task 7) will show whether the citation refusals
  are frequent enough to tune. Spend so far: US$0.126 of the US$1 Pim approved.
