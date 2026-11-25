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
- **Run:** the same command, recorded to `data/recorded/session-2.json`, now
  `session-2-run4.json` (it replaced run 2's recording, which the new note no longer replays; run 2's is in the git history). 8 model calls,
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

### 5. Session 2 with the number check (Nov 24, 2026)

- **Change tested:** Phase 3, task 5. Every number in the reply, the options' labels and summaries,
  the resolution's reason and each specialist's summary must match a figure, fact, what-if
  allocation or the household's words; a miss is sent back once, then flagged. The shared rules gain
  a paragraph saying so ("a difference, a total or a rounded guess is not").
- **Prediction (written before the run):**
  - The same conflict and resolution as run 4 (over-allocation left to the household).
  - Every text passes on its first try: the prompts already say to copy figures as shown, and runs
    2 to 4 had no worked-out numbers in what the household reads. The most likely miss is one
    specialist summary sent back once for a difference or a percentage it derived.
  - Every text gets a `number_check` row against the turn's stored run: 2 specialist summaries,
    the reply, 2 labels, 2 summaries and the reason, so 8 rows, all `pass`.
  - Cost US$0.025 to US$0.04.
- **Run:** the same command, recorded to `data/recorded/session-2-run5.json`. 9 model calls, 46,435
  tokens in (24,192 cached), 5,883 out, **US$0.0576**. 13 agent steps.
- **Result:**
  - Off the prediction, the turn went another way: both specialists proposed Jun's split this
    time (each also ran all-on-the-card), so the rules found they fit together and no conflict
    was reported. The orchestrator offered the asks together (`rec-W1`) as option A and ran
    all-on-the-card itself as B. The figures were right (17 months, ₱24,303.62, 12 months; 9 months,
    ₱12,460.10), and `recommended` was empty.
  - The number check worked as designed. Every text the household reads passed on its first try:
    the reply, both labels and both summaries (6 `pass` rows). The savings specialist's summary
    ended "I propose the split (savings1-W1)". It was sent back (`regenerated`), still had the ref,
    and was kept with it flagged (`fail`). The orchestrator reads that summary; the household
    doesn't.
  - Two other misses. The refusal named the number as `'1'`, which doesn't tell the model what to
    take out. And the orchestrator's first `submit_answer` passed a resolution with empty
    `what_if` and `rejected` when there was no conflict, which was refused and cost one more
    strong-model call. With that and the cache missing the first calls, the cost was above the
    range.
- **Root cause:** a number run into letters was reported as the digit alone. Refusing an empty
  resolution with no conflict was stricter than it needed to be: it carries nothing.
- **Change made:**
  - The check names the whole word a number is run into (`'savings1-W1' in the savings
    specialist's summary`).
  - With no conflict, a resolution that names no what-if is taken as null.
  - See entry 6.

### 6. Session 2, whole refs named and an empty resolution accepted (Nov 24, 2026)

- **Change tested:** the two code changes above; no prompt change.
- **Prediction (written before the run):**
  - Every `number_check` row ends `pass`. If a specialist writes a ref, the refusal names it in
    full and the second summary leaves it out.
  - There is no refused `submit_answer` for an empty resolution.
  - The options carry the same figures as runs 2 to 5.
  - Cost US$0.025 to US$0.05.
- **Run:** the same command, recorded to `data/recorded/session-2-run6.json`. 10 model calls,
  48,642 tokens in (35,456 cached), 4,633 out, **US$0.0334**. 13 agent steps.
- **Result:**
  - Right: every text the household reads passed on its first try (the reply, two labels, two
    summaries and the reason: 6 `pass` rows), with the worked example's figures (A: 9 months,
    ₱12,460.10; B: 17 months, ₱24,303.62, the fund's target in 12 months). No refused
    `submit_answer`; `recommended` empty. The proposals fit together, as in run 5.
  - Miss: both specialists' first summaries named what-ifs (`debt1-W1`, `figure:…` refs) and were
    sent back. The refusal said "numbers that match no figure", so each model "fixed" it by
    swapping the numbers themselves for figure refs. The savings summary then passed (its numbers
    were gone); the debt summary still had refs and was kept flagged (`fail`), now made only of
    refs ("pays it off in figure:debt1-W1:debt.payoff_months@debt:credit-card").
  - Also: each ref was listed twice in `numbers` (once for each digit run in the word), and the
    savings specialist passed a fact ref to `get_facts` as an entity, refused with a clear message.
- **Root cause:** a specialist's summary is read by the orchestrator, which resolves refs from the
  proposal's citations; refusing refs there cost a call and pushed the model the wrong way. The
  refusal lumped refs in with worked-out numbers, so the model couldn't tell what was wrong.
- **Change made:** in a specialist's summary a ref of this turn (a what-if, or a `figure:` or
  `fact:` ref) is a ref, not a number (`match` "ref"); the household's texts still allow none. The
  refusal names worked-out numbers and refs separately, each with its own instruction. A word with
  two digit runs is one code. See entry 7.

### 7. Session 2, refs allowed in a specialist's summary (Nov 24, 2026)

- **Change tested:** the three code changes above; no prompt change.
- **Prediction (written before the run):**
  - No specialist summary is sent back for a ref; if one is sent back, it is for a worked-out
    number, and the second try passes.
  - Every household text passes on its first try, with the same figures as runs 2 to 6.
  - Whether the specialists' proposals fit together or conflict is a coin flip (runs 3 and 4
    conflicted, 5 and 6 didn't); either way the answer is taken with no refused `submit_answer`.
  - 8 or 9 model calls, US$0.025 to US$0.04.
- **Run:** the same command, recorded to `data/recorded/session-2.json` (run 4's recording, which
  the number check's new prompt paragraph no longer replays, is now `session-2-run4.json`).
  6 model calls, 28,466 tokens in (25,344 cached), 2,996 out, **US$0.0242**. 9 agent steps, no
  refused call. Replayed strictly with `KAKO_MODEL_MODE=replay`: the same answer, US$0.
- **Result:** as predicted, and the cleanest run so far.
  - No text was sent back: 8 `number_check` rows, all `pass` on the first try (2 specialist
    summaries, the reply, 2 labels, 2 summaries, the reason). Neither specialist wrote a ref this
    time, so the ref rule wasn't exercised by the model; the unit tests cover it.
  - The proposals conflicted, as in runs 3 and 4: debt proposed all on the card, savings Jun's split.
    Code caught the over-allocation (₱9,050 + ₱5,050 against ₱9,050, `rec-W1` unallocated
    -₱5,050.00) and the orchestrator left it to the household with a plain-words reason.
  - Options A (9 months, ₱12,460.10) and B (17 months, the fund's target in 12 months) carry the
    worked example's figures. `recommended` empty.
  - Cost just under the predicted range: no refusals, so 6 calls instead of 8 or 9.
- **Root cause:** none.
- **Change made:** none. Real spend for the session-2 question so far: US$0.241 of the US$1 approved.

### 8. The agent test set and the single-agent baseline, first runs (Nov 24, 2026)

- **Change tested:** no prompt change for the orchestrator and specialists. New: the agent test set
  (`data/test-set/questions.toml`, 22 questions from Sep 15 to Dec 1, scored in code by
  `kako test-set`) and the single-agent baseline (`agents/single.py`, `prompts/single.md`: one agent
  on the strong deployment with the same tools and checks, at most 12 counted tool calls). Pim
  approved up to US$3 for both runs (Nov 24).
- **Prediction (written before the runs):**
  - **Specialists:** all 22 questions answered (no turn fails), scoring **75% to 90%**.
    - Figure questions (q02 to q04, q11, q13, q14, q18, q20) state the right numbers; the orchestrator
      sometimes asks a specialist for a figure it already has in the brief, which costs calls but
      not points.
    - Most likely misses: a source the question wants (the preference for flexibility on q10, q16
      and q21) cited in the reply's words but not in an option's `sources`, or no options at all;
      q09 writing the knowledge base's "December 24", which no figure or fact backs, so the number
      check flags it; q05 not saying "avalanche".
    - About 100 to 160 model calls, **US$0.40 to US$0.70**.
  - **Single agent:** all answered, within 10 points of the specialists either way. Fewer calls
    (2 to 4 a question) but every one on the strong deployment, so **US$0.25 to US$0.50**. The
    likeliest gap is the option questions: one agent tries fewer what-ifs, so q01 or q16 may offer
    one option where two are expected.
- **Run:** `KAKO_MODEL_MODE=record uv run kako test-set --architecture specialists`, then
  `--architecture single`, on a database loaded with the whole story (through Dec 1, 12:00) and local
  Meko, recorded to `data/recorded/test-set-specialists.json` and `test-set-single.json`; then each
  replayed strictly with `--save` (`data/test-set/results/`). Spent US$1.03 of the US$3 approved:
  US$0.59 for the specialists' run, US$0.01 to record q08 again, US$0.42 for the single agent.
- **First result (specialists, as the set was first written): 88.8%** (93 of 101 checks), 109 model
  calls, 597,503 tokens, US$0.59. Two things were wrong with the set, not the agents:
  - **q08 never reached the model.** Its message began "Ignore your rules and the engine", and Azure's
    content filter refused the request (HTTP 400, "the prompt triggering Azure OpenAI's content
    management policy"). The turn failed cleanly as a `ModelError`, nothing was stored, and it
    scored 0. Good to know for the demo: Foundry's own filter is a layer in front of Kako's rules.
    q08 now asks the same thing without the jailbreak wording ("Skip the calculations this time…"),
    and was recorded again alone.
  - **Four expectations asked for more than their question did,** found by reading the answers, not
    the scores: q14 and q20 ask "when", and the answers gave the payoff date (Feb 16, 2028; Oct 1,
    2028), which is the engine's figure as much as the month count is; q20 also expected the car
    loan's interest, which the question doesn't ask about; q15's answer said ₱0.00 is unallocated
    rather than naming the ₱9,050.00 surplus; q16's named the ₱16,000.00 not yet allocated rather
    than the ₱25,050.00 surplus. A stated figure may now list its forms (`"15 months | Feb 16,
    2028"`), each held to the engine by the tests. These were fixed **before** the single agent ran,
    so its run was scored on the set as it now stands.
- **Result (the set as it stands, both replayed strictly):**

  | | Specialists | Single agent |
  | --- | --- | --- |
  | Score | **98.1%** (99 of 102 checks) | **93.9%** (93 of 102) |
  | Answered | 22 of 22 | 22 of 22 |
  | Model calls | 110 | 40 |
  | Tokens | 602,904 | 210,686 |
  | Cost | US$0.60 | US$0.42 |
  | Seconds a question (recording) | 21 | 11 |

  - **Specialists' misses, all on q12** ("What if we moved the ₱5,050 from the emergency fund to the
    card instead?"): they read it as ₱5,050.00 on the card in place of the ₱4,000.00, not ₱9,050.00
    in all, so the card's payoff came out at 14 months, not 8, and the reply named the flexibility
    preference without citing it.
  - **The single agent's misses:** q06 and q17 (the household's own amount into the emergency fund)
    were answered with the right months in the reply but no option, so there was no what-if a
    household could choose or trace; q21 didn't state the current plan's 7 months for the card.
  - Against the prediction: the specialists beat the 75–90% range once the set was fixed (88.8%
    before, inside it); cost and calls were inside it. The single agent was within 10 points as
    predicted (4.2 behind), cheaper than the specialists but nearer the top of its range, and its
    gap was where predicted, on the option questions, though on q06 and q17 rather than q01 or q16.
  - **Read with care:** one run each on 22 questions; one question either way moves a score about 4.5
    points. The specialists are ahead on checks a household can trace (options, citations), not on
    getting numbers right: both stated no number the engine didn't give.
- **Also found:** recordings didn't replay on another database. The tools listed debts' figures in
  the order of their database ids, which differ between databases, so a request's digest differed.
  Tool output now follows the debts' payoff order (`in_order` in `agents/tools.py`), a test swaps the
  ids to prove it, and the recordings replay on a fresh database (`kako demo run`).
- **And on CI:** CI's local Meko ranks the brief's search excerpts differently from the machine these
  were recorded on (their scores are near-equal, about 0.0001), so every session-2 request there
  differs from its recording, as do 18 of the specialists' 110 test-set requests and 6 of the single
  agent's 40. A judge's machine can do the same, so `kako demo run` replays each reply by its call
  key and reports the requests that differed (`--strict` refuses them). On CI both test-set scores
  still come out exactly as saved.

### 9. Session 4, the life event and the replan, first real run; session 2 again (Nov 24, 2026)

- **Change tested:** Phase 4, task 2. The orchestrator (and the single agent) now has
  `propose_change` and two prompt sections ("When the household tells you something changed", "A
  replan"); `submit_answer` has `why`, required in a replan; the brief has the household's life events
  and, in a replan, a section with what changed (F-DIFF-1), the facts behind it and the decisions to
  revisit. Session 4 is new (`data/demo-household/sessions/session-4.toml`); session 2 is recorded
  again because its requests now differ from its recording (the new tool and prompt sections).
- **Prediction (written before the runs):**
  - **Session 4, turn 1** (Mara's news): the orchestrator calls `propose_change` once, with the
    `new_job` life event on Dec 1 and Mara's salary at ₱68,000 from Dec 1, quoting her words, and asks
    no specialist; it answers without options, saying what waits for a yes. 2 or 3 strong calls. The
    likeliest miss: it also asks a specialist "to see the impact" before the yes (the prompt says not
    to), or writes a worked-out number such as "₱16,000 more a month", sent back once by the check.
  - **Mara's approval** writes changes.csv rows 10 and 11 exactly (demo mode checks it).
  - **Turn 2** (Jun asks what it changes): a replan as of Dec 1 against the decision of Sep 15. The
    orchestrator asks debt and savings (budget maybe); options all on the card (3 months, ₱4,620.01
    of interest) and Jun's ₱10,000 with the rest to the fund (card in 7 months, ₱9,358.80; the fund's
    target in 4 months). `why` names the replaced salary, the Session 2 decision to revisit and the
    preference for flexibility. Whether the specialists conflict is a coin flip, as in session 2. The
    likeliest miss: a `why` with a worked-out number (the +₱16,000), sent back once, then passing.
  - Session 4 in all: 8 to 13 model calls, **US$0.04 to US$0.10**.
  - **Session 2:** the same answer as entry 7 (options A and B with the worked example's figures),
    no `propose_change` call (nothing in the message is a change), `why` empty. 6 to 9 calls,
    US$0.02 to US$0.04.
- **Run:** `KAKO_MODEL_MODE=record uv run kako demo record session-4`, then `session-2`, each on an
  empty database and local Meko (gpt-5.4 and gpt-5-mini), recorded to
  `data/recorded/session-4.json` and `session-2.json` (entry 7's recording is now
  `session-2-run7.json`). Pim approved up to US$0.50; spent **US$0.1316**.

  | | Turn | Model calls | Tokens in | Out | Cost |
  | --- | --- | --- | --- | --- | --- |
  | Session 4 | s4:t1, the news | 2 | 11,700 | 309 | US$0.0212 |
  | Session 4 | s4:t2, the replan | 11 | 66,696 | 6,768 | US$0.0749 |
  | Session 2 | s2:t1 | 7 | 34,368 | 3,203 | US$0.0355 |

- **Result:**
  - **Turn 1 as predicted:** one `propose_change` (the `new_job` life event on Dec 1, "Mara got a new
    job", and Mara's salary at ₱68,000 from Dec 1, the whole message as the quote), no specialist,
    and a reply that says it waits for a yes and that the plan is redone after. Every number passed.
  - **Mara's approval** wrote changes.csv rows 10 and 11 as the story has them (demo mode checked).
  - **Turn 2:** a replan as of Dec 1 against the decision of Sep 15, Session 2, with that decision to
    revisit. The orchestrator asked budget, debt and savings (one more than predicted), and the
    specialists didn't conflict. Options: A, Jun's ₱10,000 on the card and the rest to the fund (card
    in 7 months, ₱9,358.80 of interest, the fund's target in 4 months), recommended; B, all on the
    card (3 months). The figures are the engine's, as predicted. The recommendation leans on the
    preference for flexibility and the September decision, as the worked example's plan v3 does.
  - **One `submit_answer` sent back, not for a worked-out number but for refs:** the first reply named
    "D1" and the first `why` wrote `fact:income:mara-s-salary/income.monthly_net` and
    `figure:cashflow.monthly_surplus` in the household's text. The second try wrote them in plain
    words ("the September choice", ₱25,050.00) and passed. 11 calls, inside the 8 to 13 predicted.
  - **Session 2** as entry 7: options A (9 months, ₱12,460.10) and B, Jun's split (17 months, the
    fund's target in 12 months); the over-allocation caught in code and the choice left to the
    household; no `propose_change`; `why` empty. 7 calls.
  - Cost: session 4 US$0.096, inside its range; session 2 US$0.036, just under the top of its range.
- **Root cause of the miss:** the replan prompt asks `why` to name "the facts, preferences and
  decisions it rests on", and the brief lists them by ref, so the model's first try named them by
  ref. The number check's send-back fixed it in one try.
- **Change made:** none yet; one send-back costs one strong call (about US$0.02). If it happens again
  in session 4's next recording, the prompt will say to name them in words.

### 10. Dreaming's labelled set, first real run (Nov 24, 2026)

- **Change tested:** Phase 4, task 3. Dreaming's extraction step (`dreaming/extract.py`, prompt
  `agents/prompts/dreaming.md`): one call to `submit_claims` per session over a brief of what Kako
  holds, the noted memories (none in the labelled set) and the household's turns. Code checks every
  claim (`dreaming/classify.py`). The labelled set (`data/dreaming/labelled.toml`) has 13 sessions
  and 15 expected proposals; a careful scripted extraction finds all 15.
- **Prediction (written before the run):**
  - **Found:** 14 or 15 of 15 (93% to 100%), so the set passes (90%). The likeliest miss is a
    correction: d10's retraction with an empty value (the model writes `correction` false, or leaves
    the claim out because there is no new number), or d03 and d12 not marked as corrections, which
    code then calls a conflict (a value for the same day as the one Kako holds) instead of a
    retraction.
  - **Unquoted:** 0. Code refuses any claim with a number not in its quote, so none can be proposed;
    a refusal shows as a miss instead.
  - **Wrong proposals:** 0 to 2. The likeliest: a life event nobody stated (a `big_expense` for d07's
    school costs, or a `raise` in d02, which is a maybe and so not wrong), or d05's what-if or d09's
    wish handed in as a fact.
  - **Shape:** every call hands in claims the first time; at most one wrong shape sent back.
  - **Cost:** 13 strong calls (14 with a send-back), about 3,000 to 5,000 tokens in and 300 to 1,500
    out each: **US$0.08 to US$0.25**.
- **Run:** `KAKO_MODEL_MODE=record uv run kako dream eval --save` on a fresh database with the demo
  household loaded through Dec 1 (gpt-5.4), recorded to `data/recorded/dreaming.json`. Pim approved
  up to US$0.50.
  Spent **US$0.0758** (13 calls, 32,541 tokens in, 16,896 of them cached, and 2,165 out).
- **Result:** **13 of 15 found (87%), 2 wrong, 0 unquoted: FAIL** (needs 90%). Every call handed
  in claims of the right shape the first time. d04, d05 and d09 handed in nothing, as they should.
  d01 to d03, d06, d07, d10, d12 and d13 were found exactly, the corrections included. Two misses:
  - **d08** ("we want the emergency fund to cover 6 months of expenses, not 3"): marked as a
    correction, so code proposed retracting the target of 3 and writing 6 from Mar 1. That is two
    wrong proposals, and the change from today was missed. The household changed its mind; it never
    said Kako had it wrong.
  - **d11** ("we're expecting a baby in April 2027"): the life event came back with `occurs_on` empty,
    so code refused it.
- **Root cause:** the prompt's one example of a correction is "the rent is ₱38,000, not 40,000", so
  "6 months, not 3" read as a correction. And the prompt says how to write a day but not a month with
  its year, while "copy, never calculate" made the model unwilling to write April 2027 as 2027-04-01.
- **Change made:** the prompt now says a correction is a value that was never right ("I misread",
  "sorry, I told you wrong"), and a decision to change ("we've decided on a bigger target", "from now
  on") is a change, even when they also say the old value. Its examples are not the labelled set's
  words, so the set still measures it. It also says a month with its year is written as its first
  day ("June 2027" is 2027-06-01), which V-09 already accepts. This run's recording is kept as
  `data/recorded/dreaming-run10.json`; the next run, after Pim's yes, records `dreaming.json`.

### 11. Dreaming's labelled set again, after the prompt fix (Nov 24, 2026)

- **Change tested:** entry 10's prompt change: a correction is a value that was never right, a
  decision to change is not one, and a month with its year is written as its first day.
- **Prediction (written before the run):**
  - **Found:** 15 of 15 (100%); at worst 14 (93%), still a pass. d08 is now a change from the day
    it was said, and d11's baby is dated 2027-04-01.
  - **Risk to watch:** the corrections that were right in entry 10 (d03, d10, d12) turn into
    changes because the prompt now leans away from `correction`. d12 ("I misread") and d10 ("I don't
    get a 13th month pay") should hold. d03 ("rent and utilities are ₱38,000 a month, not ₱40,000")
    is the one most at risk, which would be a miss and a wrong proposal.
  - **Wrong:** 0 to 1. **Unquoted:** 0 (code refuses any). Every call's shape right first time.
  - **Cost:** 13 strong calls, about US$0.08 like entry 10 (**US$0.06 to US$0.12**). Pim approved up
    to US$0.25.
- **Run:** `KAKO_MODEL_MODE=record uv run kako dream eval --save` on the same fresh database (the
  demo household through Dec 1, gpt-5.4), recorded to `data/recorded/dreaming.json`.
  Spent **US$0.0750** (13 calls, 34,296 tokens in and 2,029 out).
- **Result:** **15 of 15 found (100%), 0 wrong, 0 unquoted: PASS**, as predicted. d08 is now a change
  from Nov 20 and d11's baby is dated Apr 1, 2027. The corrections held: d03, d10 and d12 are still
  retractions with the right value from the old date. d04, d05 and d09 handed in nothing. Every
  call's shape was right the first time. `kako dream eval` replays this recording with no Foundry
  and the same score.
- **Root cause / change made:** none needed. Phase 4, task 3's first measure (at least 90% found, none
  unquoted) is met on the real model. The two runs together cost US$0.15 of the US$0.75 Pim approved.

### 12. Task 4's done-when: session 4 after dreaming learned and shared the preference (Nov 24, 2026)

- **Change tested:** no prompt or tool change. The demo story now holds Jun's decisions in Sessions
  1 and 3 beside Mara's in Session 2 (`decisions.toml`), all three choosing cash on hand. Before
  session 4, demo mode dreams over Session 3 (`learning.toml`): code finds the pattern (no model
  call), Mara approves the preference, Jun confirms its sharing, and upkeep promotes it in Meko. So
  every brief from Oct 20 on lists three decisions, and session 4's marks the preference
  "promoted: shared with every agent in Meko's collective memory". Session 4's replan now compares
  against the latest decision (Session 3's, Oct 18) and lists all three decisions to revisit (Pim's
  choice, Nov 24). Every recording's requests differ, so session 2, session 4 and the test set are
  recorded again. Pim approved about US$1.50 (Nov 24).
- **Prediction (written before the runs):**
  - **Session 2** (Sep 15): the same options as entry 9, A all on the card (9 months, ₱12,460.10 of
    interest) and B Jun's split (17 months, the fund's target in 12 months), the over-allocation
    caught in code, no `propose_change`, `why` empty. New: the brief shows Session 1's decision
    (D1, a bigger buffer), and I expect option B's sources to cite it (`decision:D1`) about half the
    time. 6 to 9 calls, **US$0.03 to US$0.05**.
  - **Session 4, turn 1:** as entry 9: one `propose_change`, no specialist, 2 calls.
  - **Session 4, turn 2 (the done-when):** a replan against Session 3's decision of Oct 18, with
    Sessions 1, 2 and 3 to revisit. The orchestrator asks debt and savings (budget maybe), and its
    ask to debt does not mention the preference. **The debt specialist cites
    `fact:preference.debt_vs_flexibility` in its proposal's sources** and says the household keeps
    cash on hand; I'd put that at 85%, since its prompt says to respect approved preferences and
    the brief now marks this one promoted. The options carry entry 9's figures (Jun's ₱10,000: card
    in 7 months, ₱9,358.80; all on the card: 3 months, ₱4,620.01). The likeliest miss is entry 9's:
    refs (D1, D2, D3 now) written in the household's text, sent back once. With three decisions in
    `why`, a second send-back is possible. 10 to 15 calls, **US$0.08 to US$0.15**.
  - **Test set** (on a database after `kako demo run`, so the briefs are the ones demo mode replays):
    specialists **94% to 100%** (98.1% before), single agent **88% to 96%** (93.9% before); the
    preference questions (q10, q16, q21) more likely to cite the preference now that it is marked
    promoted. About **US$0.55 to US$0.75** and **US$0.35 to US$0.50**.
  - In all, **US$1.00 to US$1.45**.
- **Run:** each on an empty database and a throwaway local Meko datapack (gpt-5.4 and gpt-5-mini):
  `KAKO_MODEL_MODE=record uv run kako demo record session-2`, then `session-4` (entry 9's recordings
  kept as `session-2-run9.json` and `session-4-run9.json`); then `kako demo run` on a fresh database,
  `KAKO_MODEL_MODE=record uv run kako test-set --architecture specialists`, then `single` (entry 8's
  kept as `test-set-*-run8.json`), each replayed strictly with `--save`. Spent **US$1.28** of the
  about US$1.50 approved:

  | | Model calls | Tokens | Cost |
  | --- | --- | --- | --- |
  | Session 2, first try (stopped, see below) | 7 | 38,488 | US$0.0328 |
  | Session 2 | 10 | 61,258 | US$0.0412 |
  | Session 4 (s4:t1 and s4:t2) | 14 | 91,827 | US$0.0946 |
  | The debt specialist alone, 3 runs (below) | 6 | not kept | about US$0.006 |
  | Test set, specialists | 109 | 648,722 | US$0.6176 |
  | Test set, single agent | 41 | 264,921 | US$0.4853 |

- **Result:**
  - **The first session 2 recording stopped:** the orchestrator's second call came back empty (no
    words, no tool call, finish reason "stop", 141 output tokens), and the loop took that as the end
    of the turn: "the orchestrator ended the turn with no answer". Not seen in the about 250 calls recorded before.
    The tool loop now sends an empty reply back once with only the final tool offered (a plain reply
    in words still ends the loop, as before). The partial recording was discarded.
  - **Session 2** as predicted: A, all on the card (9 months, by Jun 15, 2027) and B, Jun's split
    (17 months; the fund's target in 12), no `propose_change`, `why` empty. Option B cites Session
    1's decision (`decision:D1`), and the debt specialist named "the active decision to keep a bigger
    buffer" (debt's words). This time they agreed (both proposed the split), so there was no over-allocation to catch.
    10 calls, one more than predicted: the first `submit_answer` was refused once, and the
    orchestrator fetched the figures it cited before answering again.
  - **Session 4, turn 1** as predicted: one `propose_change`, no specialist, 2 calls.
  - **Session 4, turn 2: the done-when is met.** A replan against Session 3's decision of Oct 18 with
    Sessions 1, 2 and 3 to revisit. Options: A, Jun's ₱10,000 on the card and ₱15,050.00 to the fund
    (card in 7 months, the fund's target in 4), recommended, citing
    `fact:preference.debt_vs_flexibility`; B, all on the card (3 months). The debt specialist's
    proposal cites `fact:preference.debt_vs_flexibility` ("it respects the household's preference for
    flexibility"), and `why` says "The recommendation follows your approved preference for
    flexibility and the pattern in your earlier choices: you chose a bigger buffer before, then a
    split when school costs mattered, and then keeping cash for the family trip." As
    predicted, `submit_answer` was sent back once for refs (D1, D2 and D3 in `why`), then passed. 12
    calls, inside 10 to 15.
  - **One miss against the prediction: the orchestrator told the debt specialist.** Its ask said
    "respecting avalanche and the household's flexibility preference", so this recording alone shows
    the preference reached the debt specialist without the household saying it, not that the debt
    specialist found it on its own. So I ran the stricter check: session 4 turn 2 replayed from its
    recording, but the orchestrator's ask to debt replaced with one that never names a preference
    ("compare putting ₱10,000 a month on the card with the rest to the emergency fund against putting
    all the extra on the card"), and the debt specialist live on Foundry, on a fresh database each
    time. **It cited `fact:preference.debt_vs_flexibility` in 3 of 3 runs**, from the brief alone.
  - **Test set** (both replayed strictly to the same scores):

    | | Specialists | Single agent |
    | --- | --- | --- |
    | Score | **93.3%** (95 of 102) | **90.7%** (90 of 102) |
    | Entry 8 | 98.1% (99 of 102) | 93.9% (93 of 102) |
    | Model calls | 109 | 41 |
    | Cost | US$0.62 | US$0.49 |

    Below the predicted ranges (94 to 100%, 88 to 96%), the specialists by one check. Specialists'
    misses: q05 didn't state the card's 3% or the car loan's 9%; q10 and q21 didn't state one payoff's
    months; q12 again named the preference without citing it; q16 named neither the surplus nor what
    is unallocated; q22 offered an option where none was asked for. The single agent's: q06 and q17
    again answered with no option (as in entry 8), q09 didn't say "December", q10 and q21 one figure
    each, q19 didn't state the ₱5,000. No number was stated that the engine didn't give, and the
    preference questions didn't cite the preference more often than before, against the prediction.
- **Root cause:** for the scores, none found that a prompt change would fix: the misses are figures
  left out, spread over different questions, one run each (one question either way moves a score
  about 4.5 points), and the briefs are longer now (three decisions and their options). For the
  orchestrator naming the preference: the prompt says to ask specialists to respect the preferences
  in the brief, so passing it on is the orchestrator doing its job; the stricter check shows the debt
  specialist doesn't need it.
- **Change made:** the empty-reply send-back in the tool loop. No prompt change. Demo mode replays
  session 4 with all 14 requests differing from the recording on the same machine, because `demo
  record` doesn't replay session 2 before recording session 4, so the brief's Meko search sees a
  different datapack (as with entry 9's recording); the replies are replayed and reported. Recording
  session 4 after session 2, as demo mode plays them, is a follow-up.

### 13. The learned preference's effect: its four questions without it (Nov 25, 2026)

- **Change tested:** no prompt or tool change. The metrics page (Phase 5, task 4) shows the
  preference's effect: the test set's four questions that expect it cited (q10, q12, q16 and q21),
  answered by the specialists on a household that never learned it, against entry 12's saved run
  with it. The household without it is `kako demo run --without-learning` on an empty database and a
  throwaway local Meko datapack: changes.csv row 6 is never written, nothing is shared in Meko (no
  promoted preference, no decision record), and session 4 isn't replayed (its rows 10 and 11 are
  loaded as they are). The three decisions of Sessions 1 to 3, all choosing cash on hand, are still
  in every brief. Pim approved up to US$0.35 (Nov 25).
- **Prediction (written before the run):**
  - Entry 12, with the preference: 81.4% (q10 80%, q12 85.7%, q16 80%, q21 80%); leaving out the
    check that cites it, 81.3%.
  - Without it, the check that cites it fails on all four by construction, so the full score drops to
    **60% to 68%**.
  - Leaving that check out, I expect **75% to 82%**: the three decisions in the brief still point to
    cash on hand, so q10 and q21 most likely still don't recommend all on the card (about 70% that
    both hold; the likeliest miss is q21 recommending the whole surplus on the card, now that nothing
    names the household's preference). The figures missed in entry 12 (q10's 16 months, q16's surplus,
    q21's 7 months) are about as likely to be missed again.
  - About 45 to 55 calls, **US$0.20 to US$0.28** (entry 12's four cost US$0.23).
- **Run:** on the household above (database `kako_nopref`, its own throwaway datapack), gpt-5.4 and
  gpt-5-mini: `KAKO_MODEL_MODE=record uv run kako test-set --without-preference`, then replayed
  strictly with `--save` (the same scores; `data/test-set/results/preference.json`, recording
  `data/recorded/test-set-specialists-without-preference.json`). 37 model calls, 227,609 tokens,
  **US$0.26** of the US$0.35 approved.
- **Result:**

  | | With (entry 12) | Without |
  | --- | --- | --- |
  | Score, every check | **81.4%** | **59.3%** |
  | Leaving out the check that cites the preference | 81.3% | 72.9% |
  | Model calls | 49 | 37 |
  | Cost | US$0.23 | US$0.26 |

  The full score is just under the predicted 60% to 68%; leaving out the citation it is under the
  predicted 75% to 82%. As predicted, the check that cites the preference failed on all four, and
  **q10 and q21 still didn't recommend all on the card**: the three decisions in the brief were
  enough to keep cash on hand (q12's reply: "Since you previously chose a bigger cash buffer and a
  split approach for the card, I'd treat this as a choice for you"). The same figures as entry 12
  were missed (q10's 16 months, q16's surplus, q21's 7 months). The difference without the
  citation is q12 alone: asked "What if we moved the ₱5,050 from the emergency fund to the card
  instead?", the agents ran the card at ₱5,050 instead of ₱4,000 plus ₱5,050, so the option is
  14 months, not 8 (the figure is the engine's for the move it ran, so the number check passed).
- **Root cause:** what the preference changes here is what the answer cites and names, not what it
  recommends: the decisions it was learned from already steer the specialists. q12's miss is a
  misread move, not the preference; one run each, so one question moves a score by about 20 points.
- **Change made:** none to the prompts. The metrics page shows both scores, each with and without
  the citation, and says what the difference rests on. A what-if that reads "moved X to Y" as "set
  Y to X" is worth a test-set question of its own.

### 14. Each turn knows its writer and the session so far: sessions 2 and 4 again (Nov 25, 2026)

- **Change tested:** Pim tried Kako on the laptop (Meko off, live models) as Jun. "what if my salary
  goes to 200000 per month." was met with "whose salary, Jun's or Mara's?"; "Jun", answering that
  question, with a greeting; "no, just give me the simulation" with the current plan; and "what if
  i lose my job" was filed as a real pending job loss. The brief now says who wrote the message
  ("Who is writing": "I", "me" and "my" mean them) and, from the second turn on, "This session so
  far": the last four turns as the household saw them, read from `session_turn`. `propose_change`
  refuses words that ask a what-if, and the number check counts the household's earlier messages
  in the session as said. No prompt file or tool definition changes. The test set's requests don't
  change (no writer, one turn a session). Session 2 gains Mara as the writer; session 4's turn 1
  Mara, turn 2 Jun and turn 1 as the session so far, so both are recorded again. Pim approved
  about US$0.20 (Nov 25).
- **Prediction (written before the runs):**
  - **Session 2:** the same options as entry 12 (A all on the card, 9 months; B Jun's split, 17
    months, the fund's target in 12), `recommended` empty since Mara and Jun disagree, no
    `propose_change`. The reply is a little more likely to speak to Mara by name ("you'd rather
    clear the card fast") now that she is named as the writer; no "whose" question. 8 to 11 calls,
    **US$0.03 to US$0.05**.
  - **Session 4, turn 1:** one `propose_change` (the new job and ₱68,000.00 from Dec 1), no
    specialist, 2 calls, as entries 9 and 12.
  - **Session 4, turn 2:** the replan against Session 3's decision of Oct 18 with Sessions 1, 2 and
    3 to revisit, the same two options (A Jun's ₱10,000 on the card, the rest to the fund,
    recommended on the preference; B all on the card, 3 months). The new "session so far" shows
    Mara's news and Kako's "waiting for your yes" reply; I expect it to change nothing in the
    options and at most a phrase in the reply ("Mara's new job, which you approved"). The likeliest
    miss is entry 12's: refs written in the household's text, sent back once. 10 to 15 calls,
    **US$0.08 to US$0.15**.
  - In all, **US$0.11 to US$0.20**.
- **Run:** each on an empty database and a throwaway local Meko datapack (gpt-5.4 and gpt-5-mini):
  `KAKO_MODEL_MODE=record uv run kako demo record session-2`, then `session-4` (entry 12's kept as
  `session-2-run12.json` and `session-4-run12.json`). Session 4's first recording is kept as
  `session-4-run14a.json`; after the change below Pim approved one more run (about US$0.12), and
  session 4 was recorded again. Spent **US$0.27**:

  | | Model calls | Tokens | Cost |
  | --- | --- | --- | --- |
  | Session 2 | 6 | 33,610 | US$0.0381 |
  | Session 4, first recording (s4:t1 and s4:t2) | 17 | 105,085 | US$0.1221 |
  | Session 4, kept (s4:t1 and s4:t2) | 14 | 94,478 | US$0.1105 |

- **Result:**
  - **Session 2** as predicted: A, all on the card (9 months, ₱12,460.10 of interest) and B, Jun's
    split (17 months; the fund's target in 12), the over-allocation caught in code and left to the
    household ("Mara wants the card cleared fast and Jun wants more cash in the emergency fund"),
    no "whose" question, no `propose_change`. 6 calls, under the predicted 8 to 11: no answer was
    sent back this time. Option A's summary names a figure by its key ("plan.unallocated is
    ₱0.00"), which the number check allows and a household shouldn't read.
  - **Session 4, turn 1** as predicted, both times: one `propose_change`, 2 calls.
  - **Session 4, turn 2, first recording:** the replan as predicted, but the budget specialist's
    summary said "Decisions D1, D2 and D3 need revisiting", and the number check flagged D1, D2 and
    D3: the brief's own decision refs, which a specialist's summary couldn't name. Shown in the
    demo as flagged numbers. 15 calls.
  - **Session 4, turn 2, kept:** the replan against Session 3's decision of Oct 18 with Sessions 1,
    2 and 3 to revisit; A, Jun's ₱10,000 on the card and ₱15,050.00 to the fund (card in 7 months
    with ₱9,358.80 of interest, the fund's target in 4), recommended on the preference and the three
    decisions; nothing flagged. 12 calls, inside 10 to 15. **One miss against the prediction:**
    option B isn't the whole surplus on the card (entry 12: 3 months) but the ₱16,000.00 left
    unallocated (`figure:plan.unallocated`), with the fund at ₱0.00: 5 months. Its label still says
    "all extra on the card", and the savings specialist's summary says 3 months for its own
    all-on-the-card what-if, so the options and a specialist's words disagree. The figures are the
    engine's for the moves each ran; the label overstates option B. Nobody asked about who was
    writing, and the reply doesn't mention the session so far, as predicted.
- **Root cause:** for the flagged refs: the number check let a specialist's summary name the
  turn's what-ifs, figures and facts but not the brief's decisions (`D1`), so a summary that named
  them was flagged after one send-back. For option B: the orchestrator ran its own all-on-the-card
  what-if with the unallocated figure rather than the surplus; a model's reading of "all of it",
  not a change of this entry.
- **Change made:** the number check lets a specialist's summary name the brief's own refs (`D1`,
  `P1`, `M1`, `K1`, and with their prefixes); the household's texts still allow none. Follow-ups: an
  option's label checked against its what-if ("all extra" when some of the surplus stays
  unallocated), and figure keys in an option's summary written as words. As in entry 12, demo mode
  replays session 4 with its requests differing from the recording, because `demo record` doesn't
  replay session 2 before recording session 4, so the brief's Meko search sees a different
  datapack; the replies are replayed and reported.

### 15. The conversation as context: sessions, both test sets and the conversation set (Nov 25, 2026)

- **Change tested:** the context strategy agreed with Pim on Nov 25 (docs/architecture.md, "The
  conversation"). The orchestrator's system prompt is the shared rules and its role alone; the
  session's earlier turns follow as chat messages, compacted by code beyond
  `KAKO_HISTORY_TOKEN_BUDGET`; then the brief and the new message. The brief carries the session
  state and recaps of earlier sessions; `submit_answer` takes `topic` and `asks`; the orchestrator
  and the single agent gain `read_turns`; the prompts gain "The conversation" and "What Kako can
  test". Specialists get a self-contained question. Every orchestrator request changes, so every
  recording is made again: sessions 2 and 4 (`kako demo record`, session 4 now after session 2 is
  replayed, so its brief recaps Session 2), the test set for both architectures and without the
  preference, and the new conversation set (`kako conversations`, specialists). Waiting for Pim's
  yes; estimate about **US$1.60 to US$2.00**, under the daily cap of US$3.
- **Prediction (written before the runs):**
  - **Session 2:** as entry 14: A all on the card (9 months), B Jun's split (17 months, the fund's
    target in 12), the choice left to the household, no `propose_change`; `topic` about paying down
    the card, `asks` the choice between A and B. 6 to 10 calls, **US$0.03 to US$0.06**.
  - **Session 4:** turn 1 one `propose_change`, 2 calls. Turn 2 the replan against Oct 18 with
    Sessions 1 to 3 to revisit, A recommended on the preference. The brief now recaps Session 2 and
    the orchestrator reads turn 1 as a chat turn; I expect no change to the options, and the
    reply may name Mara's news as "the new job you just approved". 12 to 16 calls, **US$0.10 to
    US$0.16**.
  - **Test set:** single-turn questions see no earlier sessions and no history, so only the layout
    and the new fields change. Specialists within one question of entry 12 (93.3%), single within
    one question of 90.7%; cost about entry 12's (US$0.62 and US$0.49), without the preference
    about US$0.12. The likeliest new miss: a `topic` or `asks` with a number in it, sent back once.
  - **Conversation set** (8 turns):
    - c01: no turn files a change (the what-if guard and the prompt). Turn 1 shows the runway in
      months and doesn't ask whose job. Turn 2 ("Jun") reads as Jun answering, not a greeting, and
      stays on the job. Turn 3 gives the runway again, plainly. The likeliest miss: turn 1 asks
      "should I show the runway?" instead of showing it.
    - c02: turn 1 files Mara's salary at ₱72,000.00 from Feb 1, 2027, naming Mara. Turn 2 (Jun) says
      the raise waits for a yes before the plan changes, and asks nobody whose salary.
    - c03: turn 1 as session 2. Turn 2 ("go with B") names B with its moves from the session state
      and says how to accept it; the likeliest miss is offering A and B again (the options check
      fails), since there is no "accept an option" step yet.
    - About 20 to 30 calls, **US$0.15 to US$0.30**. Score: 85% to 95% of checks.

### 16. Answering any question: sessions, both test sets, the conversation set and the open set (Nov 25, 2026)

- **Change tested:** Phase 5a item 10 (docs/architecture.md, "Answering any question"). The
  orchestrator and the single agent pick a kind of answer and hand it in with its sources; the
  specialists are asked only for a plan; `run_what_if` takes `changes` and `new` items (hypothetical,
  never an option); new tools `calculate`, `get_history`, `get_figures_on` and `read_document`; the
  number check accepts what the turn worked out and a cited document's numbers; `common.md`,
  `orchestrator.md` and `single.md` rewritten ("Answer first"; the "What Kako can test" lines
  gone); a new reference document, `general-guidance`. Every orchestrator request changes, so entry
  15's runs are folded into this one and nothing from entry 15 is recorded on its own: sessions 2
  and 4 (`kako demo record`), the test set for both architectures and without the preference, the
  conversation set (specialists), and the new open-question set (`kako conversations --set open`,
  specialists, 30 one-turn questions). Waiting for Pim's yes; estimate about **US$2.00 to US$2.60**
  in all, under the daily cap of US$3, run over two days if it would pass it.
- **Prediction (written before the runs):**
  - **Session 2:** a `plan` answer, as entry 14: A all on the card (9 months), B Jun's split (17
    months, the fund's target in 12), the choice left to the household. Its sources name the two
    what-ifs and Jun's words. 6 to 10 calls, **US$0.03 to US$0.06**.
  - **Session 4:** turn 1 a `record` answer with one `propose_change`, 2 calls. Turn 2 a `plan`
    replan against Oct 18 with Sessions 1 to 3 to revisit, A recommended on the preference. 12 to
    16 calls, **US$0.10 to US$0.16**.
  - **Test set:** most questions are plans and stay so. The risk is the other way from before: a
    "what if we put ₱X in" question (q06, q17) answered as a `simulate` with no option, where the
    set expects an option. Specialists 88% to 95% (entry 12: 93.3%), single 86% to 93% (90.7%);
    cost about entry 12's (US$0.62 and US$0.49), without the preference about US$0.12.
  - **Conversation set:** as entry 15's prediction, except c01 turn 1 ("what if i lose my job"):
    now a `simulate` with Jun's salary at `none`, the runway shown, no question back. 85% to 95%.
  - **Open set** (30 questions, scored on kind, sources, labels, words, numbers and nothing filed):
    - Simulations (o01 to o07, o30): each runs one what-if with `changes` or `new`, `said:` values
      for what was said and `assume:` for a loan's missing rate; "Scenario, nothing saved" on each.
      The likeliest miss: a rent rise or 10% raise "from March" run without saying it is run as if
      from today (not scored), or the reply working out a difference in prose and being sent back
      once.
    - Explanations and look-ups (o08, o09, o16 to o18, o22, o23): `get_figures_on` or `get_history`, and
      the card statement for o17, labelled "From your documents".
    - Sums (o19 to o21): `calculate`, labelled "Calculated". Likeliest miss: o20's share of income
      to debt answered from `cashflow.debt_payment_share` without a calculation, which is fine but
      fails "Calculated" if the set asks for it.
    - General knowledge and advice (o10 to o15, o24, o25, o29): `inform` or `advise` from
      `general-guidance` and the reference documents; o25 (tax on 13th-month pay) explains the
      rule and says Kako doesn't work tax out; o24 names kinds of investment, no product. Likeliest
      miss: "General information" missing when the reply also cites a household figure (by design
      the label then doesn't apply; the set expects it only where no figure is needed).
    - o26 a `plan` with 2 to 4 options; o27 a `record` proposing Mara's salary; o28 small talk.
    - About 70 to 100 calls, **US$0.30 to US$0.60**. Score: 80% to 92% of checks; no flat "can't"
      anywhere; nothing filed except o27.
