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
