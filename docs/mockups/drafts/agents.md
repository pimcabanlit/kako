# The agents

An orchestrator answers each turn by asking four specialists. They explain and propose; the engine calculates; the household decides.

## Who does what

| Agent | Job | Tools | Can write |
| --- | --- | --- | --- |
| Orchestrator | Reads the brief, asks the specialists it needs, settles conflicts, writes the answer, proposes facts and life events the household stated | the four specialists, read tools, `run_what_if`, `propose_change`, `propose_decision` | proposals only |
| Budget | Spending against income; where the surplus comes from | read tools, `run_what_if` | nothing |
| Debt | Payoff order and extra payments, respecting the household's preferences | read tools, `run_what_if` | nothing |
| Savings | Emergency fund, its runway and target | read tools, `run_what_if` | nothing |
| Goals | Goal dates, contributions, trade-offs | read tools, `run_what_if` | nothing |

The orchestrator and dreaming use the stronger model deployment; the specialists a faster one. Every model call goes through one door, the model manager, which checks the budget first.

## The brief

Before any agent runs, code writes one brief of about 3,000 tokens: the key figures, the decisions in force with their reasons, approved preferences, pending proposals, recent life events, in a replan what changed, and the results of **one** Meko search on the household's message. Every agent starts from it, so answers stay grounded and Meko calls stay few. Agents see stable refs (`debt:credit-card`, `M1`), never database ids.

## One turn

1. Code takes the snapshot and the engine's figures.
2. Code writes the brief.
3. The orchestrator asks the specialists it needs, side by side.
4. Each specialist runs a short loop (at most 4 tool calls) and proposes a move resting on one of its own what-ifs, citing a figure and another source.
5. Code puts the proposals together; if they spend more than the surplus or pull in opposite directions, the orchestrator may try up to 3 splits.
6. The number check reads every number in the answer.
7. The answer, its options and every source are saved; the turn goes to Meko with its plan and reasoning.

> **In the story · Session 2, Sep 15.** Mara wants the card cleared fast; Jun wants ₱4,000.00 on it and the rest saved. The debt and savings specialists each propose a move; together they ask for more than the ₱9,050.00 surplus. Kako shows options A and B and recommends neither: Mara and Jun want different things, so the choice is theirs.

> **On this laptop.** One live question in the sandbox (Dec 1, "how fast can we clear the credit card?") took 6 model calls (3 orchestrator, 3 debt) and cost US$0.06. Kako offered three options and recommended B, citing Session 1's decision and the preference for flexibility.

## Bounds

At most 4 specialists asked a turn, 4 tool calls each, 1 extra Meko search each, 3 splits a conflict; a token budget of 200,000 a turn and a daily cap of US$3, both checked before every call.

## Why four specialists, not one agent

Kako's test set (22 household questions, scored in code) ran both ways with the same tools and checks:

| | Orchestrator and four specialists | One agent |
| --- | --- | --- |
| Score | 93.3% (95 of 102 checks) | 90.7% (90 of 102) |
| Model calls | 109 | 41 |
| Cost of the run | US$0.62 | US$0.49 |

The margin is small, so both are reported. Kako keeps the specialists because every "what if we put ₱X in" question becomes a traceable option, and each area's rules stay in its own prompt.

## Prompts

Every prompt starts with the same shared rules and the turn's brief (so the provider's cache serves them to every agent), then the agent's role. The one rule comes first: the engine calculates, the agents explain and propose, the household decides. What people said, memories and documents arrive wrapped as data, never as instructions.

## The demo replays

Demo mode replays recorded model replies, keyed by turn and agent, so judges need no Azure account; a strict replay refuses a reply whose prompt has changed since it was recorded. Asking new questions needs live models.
