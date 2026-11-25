# Kako data model v0.19

The data contract for Kako: every table the backend keeps in Postgres, what Kako keeps in Meko and how
the two link, the calculations the engine makes, the rules that guard them, and a worked example.
**Code follows this document.** If code and this document disagree, raise it, and update this document
in the same change once agreed.

- **Database:** Postgres. Local Postgres for development and tests; AMP (Postgres in the Meko datapack)
  for the demo if the Phase 1 test passes, otherwise a free managed Postgres. See
  [architecture.md](architecture.md#where-data-lives).
- **Scope:** the hackathon MVP: one synthetic household, four planning areas (budget, debt, savings,
  goals), sessions, dreaming, decisions and plans. Tax is never calculated.
- **Version:** v0.6 (Nov 17, 2026). v0.1 was the first draft. v0.2 closed eight gaps found in the
  Stage 5 review: `account.purpose` and `preference.debt_strategy` facts, `decision_option.tags`, an
  amount on each recommendation, `session_participant` and the speaker on evidence, `agent_step`,
  `context_gap`, and the deployment and cost on `llm_call`. It also handles Meko's own extracted
  memories and sends decision records to shared knowledge. v0.3 is the schema as migrated (Phase 2,
  task 1): every table has a column list, `figure.flag` says why a figure has no value, the system
  tables have their columns, and each table names its keys and checks. v0.4 is the fact store (task 2):
  the status transitions, proposal payloads (a proposal writes exactly the fact it names, once), and
  a seed fact has no proposal and replaces nothing. v0.5 is the engine (task 3): each formula's
  edge cases, the debt rollover, the calendar, and the worked example's car loan, so every figure in
  it can be checked; plan v2's emergency-fund wait is 12 months, not 10. The plan diff (task 4) adds
  the `ended` label and says which facts count as a change. v0.6 is the demo household (task 5): its
  files and how they load, the car loan's Oct and Nov statements, and how a run is stored. The Meko
  adapter (task 6) says how `meko_call` counts and refuses calls, and how documents are uploaded.
  v0.7 (Nov 24) is proposals and approvals (Phase 4, task 1): the payloads of a life event and a
  decision, the idempotency key's shape, what V-09 counts as the same number, the facts a decision
  rests on, and the guard on decided proposals, decisions and life events (migration 0005). v0.8
  (Nov 24) is the life-event replan (task 2): the demo's `decisions.toml`, the session files'
  `writes`, a turn's own `known_at` and `approve`, and what the number check (V-10) also matches in a
  turn that proposed something or replans. v0.9 (Nov 24) is dreaming (task 3): ending a session,
  what `dream_run` keeps, the speaker on a Meko turn (`kako_said_by`), a correction's `fact`
  evidence, and dreaming's labelled set. v0.10 (Nov 24) is task 3's second part: Meko's extracted
  memories as candidates, each one's fate in `dream_run.counts`, `extracted_memory` evidence kept out
  of V-09's quotes, and how V-14 is checked. v0.11 (Nov 24) is Meko upkeep (task 5): one memory
  in Kako's words for every fact, seed facts included, kept in step by `kako meko sync`; who wrote
  each linked memory and the text Kako last gave it (`meko_link.agent_id`, `meko_link.text`,
  migration 0006); and V-13 with `kako meko check`. v0.12 (Nov 24) is patterns and promotion
  (task 4): the `promote` payload and its second confirmation, a preference promoted to collective
  memory and a decision record uploaded to the knowledge base by Meko upkeep, their `meko_link`
  rows, and V-13 over both. v0.13 (Nov 24) is Context Gaps (task 6): how a gap is collected from
  Meko's search log, answered by a proposal that writes a fact, replayed once that fact is in Meko,
  and dismissed; no schema change. v0.14 (Nov 24) is task 4's done-when: the demo story's decisions
  of Sessions 1 and 3 (a decision in `decisions.toml` may have no `after`), the preference pattern
  from Oct 18 (`changes.csv` row 6), `learning.toml` (what dreaming learns in the story between
  sessions), and session 4's replan against the latest decision with all three to revisit; no
  schema change. v0.15 (Nov 25) is the session screen (Phase 5, task 1): `session_turn` keeps each
  turn as the household saw it, so a past session reopens like a chat, and its writer joins
  `session_participant` (migration 0007). v0.16 (Nov 25) is the metrics page (task 4): a kept turn's
  cost also names its brief's size and budget; no schema change. v0.17 (Nov 25) is the money screen
(Phase 5a, item 4): formulas M-1 to M-6 under "The money screen", worked out from a run and its
snapshot without changing any figure; F-DEBT-2's months also keep each debt's scheduled payment, so
a schedule can show the month a freed payment rolls in; no schema change. v0.18 (Nov 25) is before
and after an option (Phase 5a, item 5): formulas C-1 to C-3 under "Before and after an option",
each option worked out again from its turn's own snapshot and set beside today's plan; no schema
change, nothing stored. v0.19 (Nov 25) is prompt versions: each model call logs the prompts its system
message was built from (`llm_call.prompts`, migration 0008), and each Meko turn names them
(`kako_prompts`).

How the tables are used at run time is in [architecture.md](architecture.md); the order of work is in
[build-plan.md](build-plan.md).

## Design principles

| Principle | What it means in the schema |
| --- | --- |
| Nothing is silently overwritten | A fact's value is never updated. A change is a new fact that **replaces** the old one; a mistake is **retracted**, not deleted. Every fact keeps `valid_from`, `valid_to` and `replaced_by` |
| Two kinds of time | *Valid time* is when something was true in the household's life (`valid_from`, `valid_to`). *Record time* is when Kako learned or retracted it (`recorded_at`, `retracted_at`). "Mara's salary changed on Dec 1" and "Kako was told on Nov 20" are different dates, and both are kept |
| Change is not correction | A new job **replaces** the old salary: the old value was true until the change. A typo is **retracted**: it was never true. The plan diff explains the two differently |
| Every figure comes from code | Pesos, months, rates and dates are computed by the deterministic engine and stored as figures of a calculation run. Agents read figures; they never compute them |
| Every figure is traceable | A figure records its calculation run, its formula and the facts it read. A recommendation records the figures, facts, memories, documents and decisions it cites |
| Proposals before knowledge | Anything an agent or dreaming wants to add to what the household knows starts as a **proposal**. A person approves it before it becomes an active fact, a decision or shared knowledge |
| Postgres is the record, Meko is the context | Postgres holds the structured household and the history of every fact. Meko holds conversations, memories, shared knowledge, documents, artifacts and traces, which agents search. A link table ties the two together |
| Relationships are enforced | Postgres foreign keys, unique keys and check constraints guard every table. Rules that span rows (no overlapping validity, a replacement chain without gaps) are checked in code before a write and by the validation suite |

## Conventions

| Convention | Standard |
| --- | --- |
| Primary keys | `UUID`, generated by the backend |
| Money | `BIGINT` **centavos** (₱1.00 = 100). Never a float. Displayed as pesos with two decimals |
| Rates | `NUMERIC(9,6)` as a fraction: 0.03 is 3%. A column ending `_monthly_rate` is per month; `_annual_rate` is per year |
| Shares and ratios | Computed, never stored as input. Stored as figures with `NUMERIC(12,6)`; shown to one decimal |
| Calendar dates | `DATE`. Valid time is a date because household events happen on a day |
| Points in time | `TIMESTAMPTZ`, stored in UTC. The household time zone (`Asia/Manila`) is for display |
| Validity windows | Half-open: a fact is valid on day *d* when `valid_from <= d` and (`valid_to` is null or `d < valid_to`). A null `valid_to` means "still true" |
| The demo clock | The household's "today" is `household.as_of_date`, so the demo can move through Aug to Nov 2026 on purpose. Code never reads the system clock for household dates |
| Enumerations | Lowercase text with a check constraint, so a new value is a migration |
| Nulls | A column is `NOT NULL` unless its type says `null` |
| Schema changes | Alembic migrations only; append-only once merged. A test compares every table and column below with the migrated database, so this document and the schema can't drift |

## Layers and tables

| Layer | Tables | Written by |
| --- | --- | --- |
| Household | `household`, `person`, `entity` | Seed import; approved proposals |
| Facts | `fact`, `life_event` | Seed import; approved proposals |
| Sessions | `session`, `session_participant`, `session_turn` | The API when a planning session starts and ends; a turn once it is kept (`agents/ask.py`, `db/turn_store.py`) |
| Engine | `calc_run`, `calc_input`, `figure` | The engine only |
| Planning | `plan`, `recommendation`, `recommendation_source`, `reconciliation`, `scenario`, `scenario_override`, `agent_step` | The orchestrator, through the backend; `agent_step` by the agents' tool loop (`agents/tool_loop.py`) |
| Decisions | `decision`, `decision_option`, `decision_assumption` | Approved proposals |
| Dreaming | `dream_run`, `proposal`, `proposal_evidence` | The dreaming job; the household's approvals |
| Self-learning | `context_gap` | The Meko adapter (from Meko's self-learning tools); the household's answers |
| Meko links | `meko_link` | The Meko adapter |
| System | `llm_call`, `meko_call`, `number_check` | The model manager, the Meko adapter and the number check |

## Household

### `household`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `name` | TEXT | "Villanueva household" in the demo |
| `currency` | TEXT | `PHP`. One currency per household |
| `timezone` | TEXT | IANA name, `Asia/Manila` |
| `as_of_date` | DATE | The household's "today" (the demo clock) |
| `meko_datapack_id` | TEXT, null | The household's datapack; null until one is chosen (local Meko uses its default) |
| `created_at` | TIMESTAMPTZ | |

Checks: `currency` is three capital letters.

### `person`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `household_id` | UUID FK | |
| `display_name` | TEXT | Fictional first name |
| `role` | TEXT | `adult` or `child` |
| `birth_year` | INT, null | Only for age-based goals (school) |

### `entity`

The things a household has: an income source, an expense category, a debt, a savings account, a goal.
An entity holds **identity only**. Every value that can change (an amount, a rate, a target) is a fact
about the entity, so every value has the same history rules.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `household_id` | UUID FK | |
| `kind` | TEXT | `income`, `expense`, `debt`, `account`, `goal` |
| `name` | TEXT | "Mara's salary", "Credit card", "Emergency fund", "House down payment" |
| `owner_person_id` | UUID FK, null | Null for household-wide entities |
| `opened_on` | DATE, null | When it started in the household's life |
| `closed_on` | DATE, null | A paid-off debt or a reached goal is closed, never deleted |

Unique on (`household_id`, `kind`, `name`), so the import and the household can name an entity
plainly. Checks: `closed_on` is not before `opened_on`.

The household itself is also a subject of facts (preferences, constraints), with `entity_id` null.

## Facts

### `fact`

One row per value per period. The heart of "nothing is silently overwritten".

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `household_id` | UUID FK | |
| `entity_id` | UUID FK, null | Null for a household-wide fact |
| `attribute` | TEXT | A key from the attribute catalog below, such as `income.monthly_net` |
| `value_money` | BIGINT, null | Centavos |
| `value_rate` | NUMERIC(9,6), null | |
| `value_int` | INT, null | |
| `value_date` | DATE, null | |
| `value_text` | TEXT, null | Preferences, constraints and enums |
| `valid_from` | DATE | When it became true in the household's life |
| `valid_to` | DATE, null | Exclusive. Null while still true |
| `replaces` | UUID FK, null | The fact this one replaced |
| `replaced_by` | UUID FK, null | The fact that replaced this one. Set once, when the replacement is approved |
| `status` | TEXT | `active` (true now or in its window), `replaced`, `retracted` |
| `recorded_at` | TIMESTAMPTZ | When Kako recorded it |
| `retracted_at` | TIMESTAMPTZ, null | When it was found to be wrong |
| `retraction_reason` | TEXT, null | Required when retracted |
| `source_kind` | TEXT | `seed`, `session`, `statement`, `household_entry`, `dreaming` |
| `source_ref` | TEXT | A Meko conversation id and turn seed, a knowledge-base document id, or a form submission id |
| `proposal_id` | UUID FK, null | The approved proposal that created it (null for the seed). Unique: a proposal writes one fact at most |
| `life_event_id` | UUID FK, null | The life event that caused it, if any |

Checks in the database: exactly one `value_*` column is set; money is not negative and a rate is
between 0 and 1 (V-07); `valid_to` is after `valid_from`; a fact doesn't replace itself; a `replaced`
fact has `valid_to` and `replaced_by`; a `retracted` fact, and only a retracted one, has
`retracted_at` and a reason; a seed fact, and only a seed fact, has no `proposal_id`, and a seed fact
replaces nothing (`ck_fact_seed`). `replaced_by` is unique (one fact replaces another at most once), and
so is `proposal_id`. An index
on (`household_id`, `entity_id`, `attribute`, `valid_from`) serves the snapshot.

Exactly one `value_*` column is set, the one the attribute's type names. Only `valid_to`, `replaced_by`,
`status`, `retracted_at` and `retraction_reason` ever change after insert, and only in the transitions
below; a database trigger rejects any other update, and deletes.

**Status transitions**

| From | To | When | What changes |
| --- | --- | --- | --- |
| (new) | `active` | A proposal is approved, or the seed is loaded | Insert, always as `active` with no replacement or retraction |
| `active` | `replaced` | An approved new fact for the same entity and attribute takes effect | `valid_to` = the new fact's `valid_from`; `replaced_by` = the new fact. Only an open fact (no `valid_to`) can be replaced, by one that starts later; the new fact is inserted first, in the same transaction |
| `active` | `retracted` | The household says it was wrong | `retracted_at`, `retraction_reason` |
| `replaced` | `active` | The fact that replaced it is retracted | `replaced_by` cleared and `valid_to` back to null, in the same transaction as the retraction: the old value was true all along |

A fact that has already been replaced can't be retracted: its replacement is retracted first (Pim, Nov
17). This keeps every chain repairable without changing a fact's `replaces`, which never changes. The
proposals that may write: `new_fact` or `preference_pattern` records a fact; `replace_fact` or
`preference_pattern` replaces one; `retract_fact` retracts one. Each writes exactly what its payload
names, once (see "Proposal payloads"). Seed facts have no proposal: only the seed loader records them,
and a seed fact never replaces another.

The store (`kako/db/fact_store.py`) checks each write first and says why it refuses, and locks the
household's row so two writes can't interleave. Behind it, migration 0003's guard refuses the same
things in the database: an insert that isn't `active`, a non-seed insert without an approved proposal
of its household and of a kind that may make it, any other update (a value, a start, a source or
what a fact replaces never changes), and, at commit, a replacement whose old fact doesn't end where it
starts and name it back (V-03, V-04). Facts, decisions, life events and proposals are never deleted or
truncated.

### Attribute catalog

Defined in code (`kako/facts/attributes.py`) and listed here. A new attribute is added to both in the
same change.

| Attribute | Entity kind | Type | Meaning |
| --- | --- | --- | --- |
| `income.monthly_net` | income | money | Take-home pay per month, after the deductions on the payslip (withholding tax, SSS, PhilHealth, Pag-IBIG). Kako reads the net figure; it never computes the deductions |
| `income.thirteenth_month` | income | money | The 13th-month pay amount, received in December |
| `income.pay_day` | income | int | Day of the month, 1 to 31 |
| `expense.monthly_amount` | expense | money | Budgeted amount per month |
| `expense.essential` | expense | text | `yes` or `no`. Essential expenses count toward the emergency-fund runway |
| `debt.balance` | debt | money | Balance on `valid_from`, from a statement or the household |
| `debt.monthly_rate` | debt | rate | Interest per month (credit cards in the Philippines quote a monthly rate) |
| `debt.annual_rate` | debt | rate | Interest per year (loans). A debt has one of the two |
| `debt.minimum_payment` | debt | money | The required monthly payment (a fixed amount in the MVP) |
| `account.balance` | account | money | Balance on `valid_from` |
| `account.liquid` | account | text | `yes` if it can be used in an emergency |
| `account.purpose` | account | text | `emergency` (the emergency fund) or `general`. At most one active `emergency` account per household. Formulas find the emergency fund by this fact, never by name |
| `goal.target_amount` | goal | money | |
| `goal.target_date` | goal | date | |
| `goal.saved_amount` | goal | money | Already set aside, on `valid_from` |
| `goal.priority` | goal | int | 1 is highest |
| `plan.allocation` | debt, account, goal | money | How much of the monthly surplus the household agreed to put here (extra debt payment or a contribution) |
| `household.emergency_months_target` | (household) | int | The household's own target, such as 3 months (1 to 24) |
| `preference.debt_vs_flexibility` | (household) | text | `speed`, `balanced` or `flexibility` |
| `preference.debt_strategy` | (household) | text | `avalanche` (highest rate first) or `snowball` (smallest balance first). Required once the household has two open debts; the engine reports a missing strategy instead of assuming one |
| `preference.note` | (household) | text | Any other stated preference, in the household's words |
| `constraint.note` | (household) | text | A limit the plan must respect, such as "₱5,000 a month goes to Jun's parents" |

### `life_event`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `household_id` | UUID FK | |
| `kind` | TEXT | `new_job`, `job_loss`, `raise`, `baby`, `move`, `big_expense`, `other` |
| `description` | TEXT | In the household's words |
| `occurs_on` | DATE | When it takes effect (can be in the future) |
| `recorded_at` | TIMESTAMPTZ | |
| `source_ref` | TEXT | The session turn that reported it |
| `proposal_id` | UUID FK | The approved proposal (every life event has one, V-08). Unique: a proposal writes one life event at most |

Facts caused by the event point to it with `life_event_id`, so the replan can say "these four values
changed because of the new job". A life event is written only with an approved `life_event` proposal of
its household, and never changes (migration 0005). Its id is chosen when it is proposed, so the fact
proposals it causes can name it; they are approved with it, the event first.

### Reading facts: the snapshot

The engine never reads `fact` directly. It reads a **snapshot**: the household as it stood on one date.

- `snapshot(household, on=d)`: every fact with `status` in (`active`, `replaced`) whose validity window
  contains *d*. This is "what was true on *d*" and is what calculations use.
- `snapshot(household, on=d, known_at=t)`: the same, but only facts recorded at or before *t* and not
  retracted at or before *t*, each with the window it had at *t*. This is "what Kako believed at *t*",
  which explains an old plan exactly as it was made. A replacement recorded after *t* hadn't closed the
  old fact yet: on Sep 15, Mara's ₱52,000 was still open, so a snapshot on Dec 1 known at Sep 15 holds
  ₱52,000. The window at *t* comes from the chain (a fact ends where its replacement starts, if that
  replacement was recorded and not retracted by *t*), so no extra history columns are needed.

A snapshot has a stable hash (the sorted fact ids), stored on every calculation run.

## Sessions

### `session`

A planning session is one Meko conversation.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `household_id` | UUID FK | |
| `meko_conversation_id` | TEXT | Also the session's trace id in Meko. Unique. A session run with Meko off has `local-<hex>` here instead |
| `title` | TEXT | |
| `household_date` | DATE | The demo clock when the session ran |
| `started_at` | TIMESTAMPTZ | |
| `ended_at` | TIMESTAMPTZ, null | Null while the session is open. Ending a session (`POST /api/v1/sessions/{id}/end`, `kako dream end`) refuses any more turns and queues its dreaming run, once |

### `session_participant`

Who took part in a session. Each household turn sent to Meko carries the speaker's `person_id` in its
metadata (`kako_said_by`, with the turn's seed in `kako_turn` and the session in `kako_session_id`), so
a quote can be attributed ("Mara: I got the job"), and dreaming names them on what it proposes. The demo has both adults taking part
across the four sessions. A person joins when a turn they wrote is kept (`session_turn.said_by`).

| Column | Type | Notes |
| --- | --- | --- |
| `session_id` | UUID PK, FK | |
| `person_id` | UUID PK, FK | |

### `session_turn`

One turn of a session as the household saw it: the session screen reads it to reopen a past session.
`shown` is the session API's turn answer (`agents/shown.py`, `TurnOut`), built by code once the turn
is kept: the reply and every text as number-checked, the options with their allocations and sources,
how a conflict ended, the numbers the check flagged, the changes waiting for a yes (their proposal
ids; their status is read from `proposal`), a replan's other two parts, the plan's ids and what the
turn cost, with the brief every agent was sent (`brief_tokens`, estimated high) and its budget then
(`brief_budget`), both absent on a turn kept before Nov 25. Every figure in it came from the engine; the ids in it point to the rows behind it. A turn
that fails leaves no row (its `agent_step` and `llm_call` rows stay). Written once, never updated.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `session_id` | UUID FK | |
| `meko_turn_seed` | TEXT | The turn's seed in the session, as on `agent_step` and `llm_call` |
| `said_by` | UUID FK, null | The person who wrote the message (`person.id`); null when no one was named |
| `message` | TEXT | The household's words |
| `shown` | JSONB | The answer as shown (see above) |
| `created_at` | TIMESTAMPTZ | When the turn was kept |

Unique on (`session_id`, `meko_turn_seed`).

## Engine

### `calc_run`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `household_id` | UUID FK | |
| `as_of_date` | DATE | The snapshot date |
| `known_at` | TIMESTAMPTZ | The record time of the snapshot; a run computed without one used everything Kako knew at `created_at`, and is stored with that |
| `snapshot_hash` | TEXT | |
| `scenario_id` | UUID FK, null | Set for a what-if. A run whose figures read a what-if's hypothetical values is stored only with its scenario |
| `engine_version` | TEXT | Equals the backend package version |
| `created_at` | TIMESTAMPTZ | |

### `calc_input`

The facts a run read.

| Column | Type | Notes |
| --- | --- | --- |
| `calc_run_id` | UUID PK, FK | |
| `fact_id` | UUID PK, FK | |

### `figure`

Every number the engine produces, addressable by a key.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `calc_run_id` | UUID FK | |
| `key` | TEXT | Such as `cashflow.monthly_surplus` or `debt.payoff_months` |
| `entity_id` | UUID FK, null | The debt, account or goal it is about |
| `unit` | TEXT | `centavos`, `months`, `ratio`, `date`, `count` |
| `value_numeric` | NUMERIC(20,6), null | |
| `value_date` | DATE, null | |
| `flag` | TEXT, null | Why the value is missing or needs attention: `never_pays_off`, `no_allocation`, `no_emergency_account`, `strategy_missing`, `past_due`, `negative` (shown, not hidden), `no_income` or `no_essential_expenses` (nothing to divide by), `missing_input` (a fact the formula needs isn't there; the engine never assumes one) |
| `formula` | TEXT | The formula id from [Calculations](#calculations) |
| `input_fact_ids` | UUID[] | The facts this figure read |
| `input_figure_ids` | UUID[] | The figures it was built from |

Unique on (`calc_run_id`, `key`, `entity_id`), with a null `entity_id` counted as one value. Checks: at
most one of `value_numeric` and `value_date` is set, and a figure with neither has a `flag`.

## Planning

### `plan`

A plan is a version: the household's recommended moves as of one date. Each turn that offers options or finds a conflict proposes one (`db/plan_store.py`); it stays `proposed` until the household accepts one of its options.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `household_id` | UUID FK | |
| `version` | INT | 1, 2, 3 … per household |
| `session_id` | UUID FK | |
| `calc_run_id` | UUID FK | |
| `status` | TEXT | `proposed`, `accepted`, `replaced` |
| `replaces` | UUID FK, null | The plan before it |
| `replaced_by` | UUID FK, null | |
| `summary` | TEXT | The orchestrator's checked summary |
| `meko_artifact_hash` | TEXT, null | The plan report kept as a Meko artifact |
| `created_at` | TIMESTAMPTZ | |
| `recommended_option` | TEXT, null | The label of the option the orchestrator recommends; null when the choice is the household's |

Unique on (`household_id`, `version`).

### `recommendation`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `plan_id` | UUID FK | |
| `area` | TEXT | `budget`, `debt`, `savings`, `goals` |
| `specialist` | TEXT | The specialist that proposed it: `budget`, `debt`, `savings` or `goals`. The area's own specialist when the option draws on it, else the first specialist the option draws on |
| `text` | TEXT | The option's summary, which passed the number check |
| `entity_id` | UUID FK, null | The debt, account or goal the move is about |
| `allocation` | BIGINT, null | Centavos per month the recommendation puts on that entity, not negative. Accepting the plan writes these as `plan.allocation` facts |
| `meko_turn_seed` | TEXT | The session turn whose trace holds the reasoning |
| `option` | TEXT | The label of the option it belongs to ("A: all extra on the card"). An option is one what-if; each of its allocations is one recommendation |

Unique on (`plan_id`, `option`, `entity_id`).

### `recommendation_source`

What a recommendation stands on. One row per source.

| Column | Type | Notes |
| --- | --- | --- |
| `recommendation_id` | UUID PK, FK | |
| `source_kind` | TEXT PK | `figure`, `fact`, `decision`, `memory`, `knowledge`, `conversation` |
| `source_id` | TEXT PK | A Kako id, or a Meko memory id, document id or conversation id |
| `quote` | TEXT, null | The excerpt used, for memories and documents (the words Meko gave, never the ref); a document Meko gave no id can't be cited; for `conversation` (the household's own words in the turn, `source_id` the session's conversation id), the message. At most 500 characters |

### `reconciliation`

A conflict between specialists, found in code, and how the orchestrator resolved it.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `plan_id` | UUID FK | |
| `kind` | TEXT | `over_allocation` (together the asks leave `plan.unallocated` below zero), `opposite_moves` (one specialist raises an entity's monthly allocation above what it is now and another lowers it), `target_missed` (a goal on track in the turn's run is off track together, or a goal an ask raises is still off track). Together, each entity takes the amount from the specialist whose area it is (debt, savings for an account, goals), else the last ask that named it, else its current allocation |
| `specialists` | TEXT[] | |
| `figure_ids` | UUID[] | The figures that show the conflict: the turn's surplus and the asks-together run's `plan.unallocated`, each side's what-if figure for an opposite move, a missed goal's `goal.on_track`, `goal.projected_date` and `goal.required_monthly` |
| `resolution` | TEXT | The orchestrator's choice and reason, checked like any other text. A choice is a split the rules pass, offered as an option and recommended |
| `rejected` | TEXT, null | The option it did not take: another what-if of the turn, with its allocations. Null when the orchestrator left the choice to the household (nothing supports one split, or no split fitted) and the household was shown the conflict |
| `attempts` | INT | Splits the orchestrator tried through the engine (0 to 3 a turn) once the conflict was found; each is an `agent_step` with its what-if run, `rejected` when the rules refuse it |

### `scenario`

A what-if: the snapshot plus hypothetical facts (`scenario_override`) that are never written to `fact`.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `household_id` | UUID FK | |
| `name` | TEXT | "If Jun takes the Cebu job"; a turn's what-if is named by its ref and allocations ("debt1-W1: debt:credit-card ₱9,050.00 a month"), kept with the turn (never by an agent's tool), and then the `agent_step` rows that ran it name its run |
| `base_as_of` | DATE | |
| `amp_branch_id` | TEXT, null | Set when the scenario is kept as an AMP branch (a Should, see the build plan) |

### `scenario_override`

One hypothetical value, in the same shape as a fact, with the same checks on its value columns.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `scenario_id` | UUID FK | |
| `entity_id` | UUID FK, null | |
| `attribute` | TEXT | From the attribute catalog |
| `value_money` | BIGINT, null | |
| `value_rate` | NUMERIC(9,6), null | |
| `value_int` | INT, null | |
| `value_date` | DATE, null | |
| `value_text` | TEXT, null | |
| `valid_from` | DATE | |

### `agent_step`

One tool call by one agent: what the "agents' steps" view shows. Meko's trace holds the same calls as
spans; this table is Kako's own copy, shaped for the screen and for the metrics.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `session_id` | UUID FK | |
| `meko_turn_seed` | TEXT | The turn it belongs to |
| `agent` | TEXT | `orchestrator`, `budget`, `debt`, `savings`, `goals`, `dreaming` |
| `seq` | INT | Order within the turn |
| `tool` | TEXT | Such as `get_figures`, `run_what_if`, `search_memory` |
| `input_summary` | TEXT | Short, for display (never a full prompt) |
| `result_summary` | TEXT | Short, for display; a what-if's result names its figures |
| `calc_run_id` | UUID FK, null | The what-if run, when the tool ran the engine. Set when the turn is kept: the tools write nothing, so a turn that fails leaves the step with no run and no scenario |
| `outcome` | TEXT | `ok`, `rejected` (a split the rules refused), `error` |
| `created_at` | TIMESTAMPTZ | |

Unique on (`session_id`, `meko_turn_seed`, `seq`).

## Decisions

### `decision`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `household_id` | UUID FK | |
| `session_id` | UUID FK | Where it was made |
| `question` | TEXT | "How hard should we pay down the credit card?" |
| `chosen_option_id` | UUID FK | Checked at commit, so a decision and its options are written in one transaction |
| `reasoning` | TEXT | In the household's words where possible |
| `valid_from` | DATE | |
| `valid_to` | DATE, null | |
| `status` | TEXT | `active`, `revised`, `reversed` |
| `replaced_by` | UUID FK, null | The decision that revised or reversed it |
| `outcome` | TEXT, null | Filled in later: what happened |
| `proposal_id` | UUID FK | The approved proposal (V-08). Unique: a proposal writes one decision at most |

A decision is written only with an approved `decision` proposal of its household, with its options and
assumptions in the same transaction. Afterwards it changes only by being revised or reversed once
(`status`, `valid_to` and `replaced_by` together, when a later decision names it in `revises`) or by
its `outcome` being written once; options and assumptions never change and are never deleted
(migration 0005). A decision that accepts a plan (`plan_id` in its payload) marks the plan `accepted`
and the household's earlier accepted plan `replaced`.

### `decision_option`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `decision_id` | UUID FK | |
| `label` | TEXT | "A: all extra on the card" |
| `calc_run_id` | UUID FK, null | The figures that described the option |
| `rejected_reason` | TEXT, null | Null for the chosen option |
| `tags` | TEXT[] | Empty by default. From a fixed list in `kako/decisions/tags.py`: `favours_flexibility`, `favours_speed` (the two sides of `preference.debt_vs_flexibility`). The orchestrator tags an option when it proposes it; code rejects a tag that is not on the list, and a database check holds the same list (V-15). Dreaming counts chosen options by tag. A new tag is added to all three in the same change |

### `decision_assumption`

The facts a decision rested on. When one of these facts is replaced, the replan lists the decision as
**to revisit**.

Which facts (`kako/decisions/assumptions.py`): every fact in the snapshot on the decision's date, as
known when it was made, except those that move as the plan works: `debt.balance`, `account.balance`,
`goal.saved_amount` and `plan.allocation` (the decision itself). So a new statement doesn't send a
decision back to the household, and a new job does.

| Column | Type | Notes |
| --- | --- | --- |
| `decision_id` | UUID PK, FK | |
| `fact_id` | UUID PK, FK | |

## Dreaming

### `dream_run`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `session_id` | UUID FK | Unique: one run per session, so running it twice does nothing |
| `status` | TEXT | `queued`, `running`, `done`, `failed`. A done run never runs again; a failed one may, and what it proposed the first time is found under its keys |
| `started_at` | TIMESTAMPTZ, null | Null while queued |
| `finished_at` | TIMESTAMPTZ, null | |
| `counts` | JSONB | Empty by default. A done run: `claims` (what extraction handed in), `model_calls`, `proposals` (made, by kind), `outcomes` (by outcome: `new`, `replace`, `retract`, `same`, `conflict`, `refused`, `deferred`, `already`) `findings` (up to 40: the claim, the turn, the outcome, what it is and why) and `memories` (each memory Meko extracted from the session: its ref, id, the agent that wrote it, its words, its fate `waiting` or `delete`, why, the proposals it waits on (each showing its words), and its `state` as settling carries it out: `linked` with its `links`, `deleted`, or `undeletable` when an agent that isn't Kako's wrote it). A failed run: `error` |

### `proposal`

Everything dreaming or an agent wants to add to household knowledge waits here for a person.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `household_id` | UUID FK | |
| `dream_run_id` | UUID FK, null | |
| `kind` | TEXT | `new_fact`, `replace_fact`, `retract_fact`, `life_event`, `decision`, `preference_pattern`, `promote` |
| `payload` | JSONB | The fact, event, decision or memory ids, in the shape of the target table |
| `explanation` | TEXT | Why, in plain words |
| `status` | TEXT | `pending`, `approved`, `rejected`, `expired` |
| `decided_by_person_id` | UUID FK, null | |
| `decided_at` | TIMESTAMPTZ, null | |
| `idempotency_key` | TEXT | Unique. `<source>\|<kind>\|<target>`: the source turn (`<session id>:<turn seed>`), the kind (`fact` for the three kinds that write a fact, so one value can't be proposed as two kinds) and the target (`<entity id or household>/<attribute>/<valid_from>` for a fact, `fact/<id>` for a retraction, `<kind>/<occurs_on>` for a life event, `plan/<id>` for a decision on a plan), so a rerun of the turn, or dreaming over it, can't propose it twice. The same key with a different payload is refused |
| `created_at` | TIMESTAMPTZ | |

Checks: a `pending` proposal has no decision yet; an `approved` one names the person who approved it and
when; a `rejected` or `expired` one has `decided_at`. Only an adult of the household decides. A proposal
is decided once: its status moves from `pending` to `approved`, `rejected` or `expired` and never again,
and what it proposes (household, kind, payload, explanation, key, run, creation time) never changes; a
database trigger refuses any other update (migration 0005). Approving an approved proposal again
changes nothing. Several proposals can be approved together, in one transaction (a life event before
its facts, a retraction before the facts, the facts before a decision); if any write is refused, none
is made. The store is `kako/db/proposal_store.py`; the API is `/api/v1/proposals`.

**Proposal payloads.** A proposal that writes a fact carries the write itself, and the fact store writes
only that, once (V-08; REVIEW.md rule 4). A write that differs in any field is refused, and so is a
second write with the same proposal.

| Kind | Payload |
| --- | --- |
| `new_fact` | `entity_id` (null for a household-wide fact), `attribute`, `value`, `valid_from`, `valid_to` (null unless the period has already ended), `life_event_id` (null if none) |
| `replace_fact` | The same, plus `replaces`: the open fact it replaces. `valid_to` is null |
| `preference_pattern` | Either of the two above |
| `retract_fact` | `fact_id`, `reason` |
| `life_event` | `id` (chosen when proposed, so its facts can name it), `kind`, `description` (in the household's words), `occurs_on`, `source_ref` (the turn that reported it) |
| `decision` | `id`, `session_id`, `question`, `reasoning`, `valid_from`, `chosen` (the chosen option's label), `options` (each `id`, `label`, `calc_run_id` or null, `rejected_reason`, null only for the chosen one, and `tags` from the fixed list), `assumptions` (fact ids), `plan_id` (the plan it accepts, or null), `revises` (the active decision it revises, or null) |
| `promote` | `fact_id` (an active, open `preference.*` fact) or `decision_id` (an active decision): what it shares, by id only, so nothing in it is a number. The words shared are written by code from rows that never change (`upkeep/sentences.py`, `upkeep/records.py`). Approving one needs its second confirmation (`confirm_promotion` in the API, `--confirm-promotion` on the command line), because it can't be undone, and checks again that what it shares still holds. It writes no row: Meko upkeep shares it |

Values are JSON: money and whole numbers as integers (money in centavos), a rate as a decimal string
such as `"0.035"` (never a float), a date as `"YYYY-MM-DD"`, ids as UUID strings. Every row a payload
names must be the household's. A fact written on approval takes its source from the proposal: `dreaming`
when dreaming made it, otherwise `session`, with the turn it was said in as `source_ref`, and it is
recorded at the approval's time.

### `proposal_evidence`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `proposal_id` | UUID FK | |
| `kind` | TEXT | `turn`, `memory`, `extracted_memory` (one Meko extracted on its own, shown with what dreaming proposed; its words never hold a number for V-09), `learning` (one of Meko's Learnings; never a quote for V-09 either), `fact` (such as the fact a correction takes the place of, from its start date), `decision` |
| `ref` | TEXT | Turn seed, memory id, or Kako id |
| `person_id` | UUID FK, null | Who said it, for a turn |
| `quote` | TEXT | The words the proposal rests on |

A number in a proposal must appear in its quoted evidence (see [Validation rules](#validation-rules)):
dreaming copies what the household said; it never works a number out. The check
(`kako/facts/evidence.py`) runs before a proposal is stored. The numbers are a fact's value (money,
rate, whole number or date), its `valid_from` and `valid_to`, a life event's `occurs_on`, and every
number in the free text it writes (a text value, a description, a retraction's reason, a decision's
reasoning). They are read the way the number check reads text (`kako/facts/reading.py`), and match
when they are the same amount (₱68,000, 68,000 pesos, 68000, and in the household's words 68k or 68
thousand), the same rate (3.5% or 0.035), the same whole number (or months for years), or the same day
in any form; a day with no year (Dec 1) counts within a year of the household's date, a month with its
year (December 2026) counts for its first day, and a start date may be the household's date itself
(a statement of how things are now). A decision's options come from a stored plan whose texts passed
the number check (V-10); its reasoning is checked here.

## Self-learning

### `context_gap`

A weak search, from Meko's self-learning tools, and what happened to it (`kako/gaps/`).
Self-learning is served by Meko Cloud only; on local Meko every step below refuses and nothing changes.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `household_id` | UUID FK | |
| `meko_log_id` | TEXT | The search in Meko's query log; unique, so a search is kept once, for one household |
| `query` | TEXT | What was searched |
| `band_before` | TEXT | `mid` or `low` |
| `score_before` | NUMERIC(4,3) | Best score, 0 to 1, rounded to 3 places; 0 when nothing came back |
| `reason` | TEXT | Meko's reason, such as `weak_match` |
| `question` | TEXT, null | The plain question for the household, written by code, never a model, with the search's words (at most 500 characters) |
| `asked_in_session_id` | UUID FK, null | Not set yet: asking in a session (the brief's "Kako would like to know") is Phase 5 |
| `proposal_id` | UUID FK, null | The answer: one of the household's proposals that writes a fact (`new_fact`, `replace_fact`, `preference_pattern`), pending or approved when tied |
| `verify_outcome` | TEXT, null | From `selflearning_verify`: `improved`, `no_change`, `worse`, `no_baseline` |
| `score_after` | NUMERIC(4,3), null | |
| `status` | TEXT | `open`, `asked`, `answered`, `verified`, `dismissed` |

Checks: both scores are between 0 and 1.

How a gap moves (`kako gaps`, `/api/v1/gaps`):

- **Collected** (`open`): Meko's search log (`selflearning_query_log`, the low and the mid band, the
  newest 10 of each from the last 7 days) on the household's datapack. Only a shortfall of coverage is
  kept: Meko's category `coverage`, or with no category a reason of `weak_match`, `partial_match`,
  `nothing_matched` or `below_floor` (or none). A vague prompt or a failed or out-of-date source
  isn't the household's to answer.
- **Answered**: tied to its answer's proposal. Tying it again replaces the answer and clears any
  outcome. A dismissed or verified gap can't be answered.
- **Replayed** (`selflearning_verify`) once the answer is approved and every fact it wrote has Kako's
  own memory in Meko (a `meko_link` with its text): after each approval's upkeep, and with
  `kako gaps verify`. At most 5 a run; one Meko is still indexing waits for the next run. Meko's
  outcome and best score after are stored; `improved` makes the gap `verified`, any other outcome
  leaves it `answered` with that outcome (`kako gaps verify --gap` replays it again).
- **Dismissed** by an adult of the household, at any point before it is verified.

## Meko links

### `meko_link`

Ties a Kako row to what Meko holds about it.

| Column | Type | Notes |
| --- | --- | --- |
| `kako_table` | TEXT PK | `fact`, `decision`, `plan`, `life_event`, `proposal`, `context_gap` |
| `kako_id` | UUID PK | The row in `kako_table` (checked by the validation suite, as it can point at several tables) |
| `meko_kind` | TEXT PK | `memory`, `promoted_memory`, `document`, `artifact`, `conversation` |
| `meko_id` | TEXT PK | Memory id (a promoted memory keeps its id), a document's upload key, artifact content hash, or conversation id |
| `created_at` | TIMESTAMPTZ | |
| `agent_id` | TEXT, null | The agent that wrote the memory (`kako:upkeep` for Kako's own memory of a fact; the turn's agent for one Meko extracted): only it can rewrite or delete the memory |
| `text` | TEXT, null | The sentence Kako last wrote to the memory (or shared, for a promoted one); null for one in Meko's own words and for a document. Meko upkeep compares it with the fact's sentence now to know when to rewrite it |

This table exists because Meko keeps a
memory's own metadata while it is a memory but drops it on promotion (a promoted hit carries only its
`memory_id`, `agent_id` and `source`; tested on local Meko 1.20261116.0, Nov 17, 2026).

The brief marks a memory found by `context_search` approved only when `meko_link` ties it to one
of the household's facts (not retracted) or decisions. Meko's own metadata never decides that: any
client of the datapack can write it, and promotion drops it.

## System

Written by the model manager, the Meko adapter and the number check. Never edited.

### `llm_call`

Every model call attempt, made or refused. For the metrics page (cost and seconds per turn, average
and worst case) and the spend cap. A retried call is one row per attempt; a failed attempt costs 0;
a call refused before sending (the turn's token budget or the daily cap) is `budget_exceeded` with
0 tokens. A replayed call keeps the cost its recorded tokens would have had, for the metrics, and the
daily cap sums real calls only (`recorded_replay` false, `created_at` since midnight UTC).

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `session_id` | UUID FK, null | Null outside a session (such as `check-models`) |
| `meko_turn_seed` | TEXT, null | The turn it served |
| `agent` | TEXT | `orchestrator`, `budget`, `debt`, `savings`, `goals`, `dreaming`, `system` |
| `deployment` | TEXT | The Foundry deployment name, from settings |
| `input_tokens` | INT | |
| `output_tokens` | INT | |
| `cached_tokens` | INT | |
| `latency_ms` | INT | |
| `cost_usd` | NUMERIC(12,6) | From the per-token prices in settings at the time of the call |
| `outcome` | TEXT | `ok`, `error`, `budget_exceeded` |
| `recorded_replay` | BOOLEAN | A recorded response replayed (tests, demo mode), not a real call |
| `created_at` | TIMESTAMPTZ | |
| `prompts` | JSONB | The prompts the call's system message was built from, by name, each with its `source` (`repo`) and the `sha256` of its text as loaded: `{"common": {...}, "debt": {...}}`. Empty for a call with no agent prompt (`check-models`) and rows from before migration 0008. See [architecture.md](architecture.md#prompt-versions) |

Checks: token counts, latency and cost are not negative.

### `meko_call`

Every Meko tool call, made or refused. The Free tier caps some tools for the account's lifetime, so the
adapter counts them here and refuses calls past the ceiling in settings (`KAKO_MEKO_CLOUD_CEILING`, 0 by
default, never above the Free tier's own allowance). A call is written before it is sent, under a lock per
allowance so two callers can't both take the last one, and then gets its outcome; a call that failed still
counts, since it may have used the allowance. The ceiling applies on Meko Cloud only, to the capped tools:
`context_search` (with `selflearning_verify`, a replayed search), `memory_search`, `knowledgebase_search`,
`conversation_add_message`, `conversation_create` and `memory_add`. The count is this database's, not the
account's.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `session_id` | UUID FK, null | |
| `target` | TEXT | `local` or `cloud`, from the Meko URL |
| `tool` | TEXT | Such as `context_search` |
| `agent_id` | TEXT | Such as `kako:orchestrator` |
| `latency_ms` | INT, null | Null when the call was refused before it was sent |
| `result_count` | INT, null | Results returned, for searches |
| `outcome` | TEXT | `ok`, `error`, `refused` (the ceiling was reached) |
| `created_at` | TIMESTAMPTZ | |

An index on (`target`, `tool`) serves the counter.

### `number_check`

Every text checked against the figures and facts (V-10). A text that fails is sent back to its agent
once, with the unmatched numbers named: that check is a `regenerated` row. The text finally shown is a
`pass` row, or a `fail` row when it failed again, and its unmatched numbers are flagged where it is
shown. Each write commits on its own (`db/number_checks.py`).

| Column | Type | Notes |
| --- | --- | --- |
| `id` | UUID PK | |
| `session_id` | UUID FK, null | |
| `calc_run_id` | UUID FK | The turn's run: its figures and snapshot, with the turn's what-ifs (runs of the same snapshot) |
| `subject` | TEXT | `reply`; `recommendation` (an option's label or summary, or a specialist's summary); `summary` (a plan's summary, when it isn't the reply); `reconciliation` (a resolution's reason) |
| `subject_id` | UUID, null | The recommendation, plan or reconciliation, once stored; null for a check made before the row exists and for a specialist's summary |
| `checked_text` | TEXT | |
| `numbers` | JSONB | Each number found, as `{text, kind, match}`: `kind` is `money`, `months`, `percent`, `date`, `month`, `number`, `code` (a number run into letters, such as a ref) or `scaled` (a number with a multiplier); `match` is what it matched (`figure:<ref>`, `figure:<what-if>:<ref>`, `fact:<ref>`, `allocation:<what-if>:<entity>`, `said`, `date:today`), `ref` for a ref of the turn in a specialist's summary (only the orchestrator reads it, and resolves it from the proposal's citations; the household's texts allow none), or null. A word with two numbers in it (`debt1-W1`) is one `code` |
| `result` | TEXT | `pass`, `fail`, `regenerated` |
| `created_at` | TIMESTAMPTZ | |

## What Kako keeps in Meko

Meko is where agents find context. Postgres stays the record. The mapping:

| Kako thing | In Meko | How it is written | Notes |
| --- | --- | --- | --- |
| A planning session | A **conversation** (one per session) | `conversation_create`, then `conversation_add_message` per turn with `plan` and `reasoning` | The conversation id is the trace id; every Meko call made with it becomes a span. Kako stores the turn seed on each recommendation. Each turn's metadata names Kako's ids and the prompt versions its agents ran with (`kako_prompts`: by name, `{source, sha256}`, as on `llm_call.prompts`) |
| A fact (approved, or the seed) | A **memory** in Kako's words, one sentence, written by `kako:upkeep` with metadata `{kako_source: "fact", fact_id, attribute, valid_from}`, linked in `meko_link` with the text written | `memory_add` by Meko upkeep (`kako/upkeep/`): after every approval, at the end of `kako demo run`, and with `kako meko sync` | A plain sentence naming the household and the thing, because Meko's search boosts named entities: "In the Villanueva household, from Dec 1, 2026, Mara's salary (take-home pay a month) is ₱68,000.00." Upkeep compares each fact's sentence now with the link's `text`, so a run does only what is owed, at most 60 steps (the rest waits for the next run), one run per household at a time. Memories are never the source of a number: agents read numbers from figures. A memory Meko extracted stays linked as well while its fact holds |
| What the household said, extracted by Meko | A **memory** Meko added on its own (`source` = `extract`; Meko Cloud runs this automatically) | Not written by Kako | A **candidate** for dreaming, never knowledge by itself (any memory without Kako's `kako_` metadata). Each ends linked to the facts and life events its claim wrote (`meko_link`), once a person has approved every proposal that showed its words, or deleted as the agent that wrote it: when the household turns any of them down, or when no new proposal shows it (V-14) |
| A replaced fact | Kako's memory, **rewritten in the past tense**; a memory Meko extracted for it is deleted | `memory_update` and `memory_delete_by_id`, each as the agent that wrote the memory (`meko_link.agent_id`; Meko allows no other) | Meko keeps a memory's metadata on update but cannot change it, so the text carries the dates: "In the Villanueva household, from Mar 1, 2026 until Nov 30, 2026, Mara's salary (take-home pay a month) was ₱52,000.00." Meko's own words told of the old value as current; its dreaming run's entry becomes `deleted`, so V-14 still holds. A fact back in force (its replacement retracted) is rewritten in the present tense |
| A retracted fact | Every memory linked to it is **deleted**, and its links with it | `memory_delete_by_id` | The fact row keeps the history; a wrong memory must not be found again. Deleting a memory removes every link to it, so V-13 holds |
| A household preference the household approves for sharing | A **promoted memory** (collective memory): the preference's sentence while in force, written by `kako:upkeep` ("In the Villanueva household, from Oct 18, 2026, the household's preference between paying debt off faster (speed) and keeping cash on hand (flexibility) is flexibility."), linked as `promoted_memory` with the words shared | Meko upkeep, after an approval with its second confirmation: `memory_add`, then `memory_promote`. Before adding, it reads `memory_get_all` with `promoted` (Meko lists the newest 20): a memory `kako:upkeep` already promoted with the same words (a run stopped before its link) is linked, never promoted twice. A memory Meko didn't promote is deleted again | One-way: a promoted memory can't be edited or deleted through MCP, memory search no longer finds it, and promotion drops its metadata (`meko_link` keeps what it is). So Kako promotes only preferences, and a later change is shared as a new promoted memory with its own date. A preference replaced before upkeep gets to it isn't shared. Agents find it through `context_search` and `knowledgebase_search`; the brief marks the preference promoted once its sharing was approved by the brief's `known_at` |
| A decision the household approves for sharing | A **decision record** in the knowledge base (`kako-decision-<id>.md`), linked as `document` by its upload key | Meko upkeep, after an approval with its second confirmation: `knowledgebase_upload_document` (`upkeep/records.py` writes the Markdown) | The question, who approved it and when, the option chosen with the household's reasoning, the options turned down with their reasons, the facts it rests on (as they were), and the decision it revises. The same decision always gives the same record, and Meko takes the same content once. A decision revised before upkeep gets to it isn't shared |
| Statements, budgets, planning rules, local reference | **Knowledge-base** documents | `knowledgebase_upload_document`, then a POST of the file to the one-time link it returns (`kako demo upload`); the same on local Meko and Meko Cloud, and a file Meko already holds isn't sent again | Synthetic statements as CSV; rules and reference as Markdown. Reference documents explain 13th-month pay, SSS and Pag-IBIG in plain words and are never used to calculate |
| A plan report | An **artifact** | `artifact_put` | Markdown; its content hash is stored on `plan` |
| Weak searches | **Self-learning** shortfalls (Context Gaps) | Read with `selflearning_query_log` (`kako gaps sync`; the self-learning tools take no `agent_id`); replayed with `selflearning_verify`, counted as a `context_search`. Meko Cloud only: local Meko has no self-learning tools | Each shortfall of coverage becomes a `context_gap` with a question for the household; once its answer is approved and in Meko, the replay's outcome and score after are kept |
| Meko's Learnings | Memories waiting to be kept or promoted (`datapack_describe` counts them; local Meko 1.20261116.0 lists no other view) | Read by dreaming, session by session, as the extracted memories above | Candidates: linked once kept as an approved fact, or deleted. Promotion candidates are Kako's own: a preference approved from a pattern, or a decision two sessions have held (dreaming steps 4 and 5) |

Agent ids: `kako:orchestrator`, `kako:budget`, `kako:debt`, `kako:savings`, `kako:goals`,
`kako:dreaming`, and `kako:seed` for the demo's documents. They attribute writes and traces; Meko does not filter reads by agent id, so every agent
sees the whole household context.

## Calculations

Computed in `kako/engine`, pure Python with integer centavos and `Decimal` for rates, never by a model.
Rounding is **half up to the centavo** at each monthly step; months are whole; ratios are kept to six
decimals and shown to one.

The rules every formula follows:

- **Open entities.** A formula reads the entities open on the as-of date: `opened_on` is null or on or
  before it, and `closed_on` is null or after it.
- **No guessing.** A formula that needs a fact the snapshot doesn't have gives no value and the flag
  `missing_input`, and so does every figure built from it. Two facts are optional because their absence
  has a meaning: no `plan.allocation` is ₱0 a month, and no `income.thirteenth_month` is no 13th-month
  pay. Input that contradicts itself (a debt with both rates, two emergency funds) is refused.
- **The calendar.** Month *k* falls *k* months after the as-of date, on the same day, or on the month's
  last day when it has no such day (Jan 31 + 1 month is Feb 28). A date *N* months away is as-of + *N*
  months.
- **The horizon** is 100 years (1,200 months). A debt still owed then never pays off; an allocation too
  small to reach a goal or the emergency target within it counts as none (`no_allocation`).
- **Traceable.** Each figure records the facts (and a what-if's overrides) it read and the figures it
  was built from. A what-if's override takes the place of the fact for the same entity and attribute
  from its `valid_from`.

| Formula id | Figure key | Definition |
| --- | --- | --- |
| `F-INC-1` | `cashflow.monthly_income` | Sum of `income.monthly_net` over open income entities. 13th-month pay is shown separately as `cashflow.thirteenth_month`, only when the as-of date is in December |
| `F-EXP-1` | `cashflow.monthly_expenses` | Sum of `expense.monthly_amount` |
| `F-EXP-2` | `cashflow.essential_expenses` | The same, for expenses marked essential (each open expense needs `expense.essential`) |
| `F-DEBT-1` | `cashflow.minimum_payments` | Sum of `debt.minimum_payment` over open debts: open debt entities whose `debt.balance` is above zero |
| `F-CF-1` | `cashflow.monthly_surplus` | income − expenses − minimum payments. May be negative; a negative surplus is flagged, not hidden |
| `F-CF-2` | `cashflow.debt_payment_share` | minimum payments ÷ income |
| `F-CF-3` | `cashflow.savings_rate` | (sum of `plan.allocation` to accounts and goals) ÷ income |
| `F-SAV-1` | `savings.emergency_runway_months` | liquid balance ÷ essential expenses. The liquid balance is the sum of `account.balance` over open accounts with `account.liquid` = `yes` (each open account needs `account.liquid`) |
| `F-SAV-2` | `savings.emergency_target` | `household.emergency_months_target` × essential expenses |
| `F-SAV-3` | `savings.months_to_target` | ceil((target − liquid balance) ÷ monthly allocation to the emergency fund, the account with `account.purpose` = `emergency`); 0 once the target is reached; otherwise null with `no_allocation` if the allocation is zero, or `no_emergency_account` if no account has that purpose (each open account needs `account.purpose`) |
| `F-DEBT-2` | `debt.payoff_months`, `debt.total_interest`, `debt.payoff_date` | The open debts are paid off together, month by month, in strategy order. For each: interest = round(balance × monthly rate); balance += interest; payment = min(its payment, balance); repeat until the balance is zero. The balance fact is the balance on the as-of date. A debt with an annual rate uses annual ÷ 12, rounded once with the interest. A debt's payment starts as its minimum plus its extra allocation; when a debt is paid off, its whole payment (with anything rolled into it) rolls to the first debt still open in strategy order, from the next month (Pim, Nov 17). Once a month passes in which no open debt's balance goes down, the debts still open never pay off (for one debt: the payment does not exceed the first month's interest), and the figures say so. The payoff date is as-of + months. Each figure reads every open debt's facts, since any of them can roll a payment over |
| `F-DEBT-3` | `debt.strategy_order` | Each open debt's place (1 is first) in the order freed payments roll, from `preference.debt_strategy`: `avalanche` (highest monthly rate first, an annual rate counted as annual ÷ 12; ties go to the smaller balance) or `snowball` (smallest balance first; ties go to the higher rate), then by name. One open debt is first with no strategy needed. With two or more open debts and no strategy fact, the figure (and every F-DEBT-2 figure) says the strategy is missing |
| `F-GOAL-1` | `goal.months_to_target`, `goal.projected_date` | ceil((target − saved) ÷ monthly allocation), 0 once reached; null with `no_allocation` when nothing is allocated; projected date = as-of + months. No interest in the MVP |
| `F-GOAL-2` | `goal.required_monthly` | ceil((target − saved) ÷ months until `goal.target_date`), to the centavo; 0 once reached. The months are the monthly steps from the as-of date that land on or before the target date; with none left, the figure is `past_due` |
| `F-GOAL-3` | `goal.on_track` | 1 when the projected date ≤ the target date, else 0 (unit `count`). A goal with no allocation is 0, flagged `no_allocation` |
| `F-ALLOC-1` | `plan.unallocated` | surplus − sum of allocations to open debts, accounts and goals. Must be ≥ 0 (a reconciliation rule); a negative result is flagged `negative` |
| `F-DIFF-1` | (diff) | Two runs compared figure by figure: each changed figure (value or flag, or in one run only), its old and new value, and the facts behind the change: the facts it was built from, directly or through other figures, that differ between the runs. Each is labelled `replaced` (life changed: a newer fact in the chain took its place), `retracted` (a mistake was fixed; the fact it had replaced is back), `allocation` (the household chose differently: `plan.allocation`, replaced or new), `new` (it started, or Kako learned it, after the old run) or `ended` (its window closed with nothing in its place). A fact already true and known at the old run is not a change, even when only the new run reads it. A decision whose assumption (`decision_assumption`) has been replaced or retracted by the new run's date is listed **to revisit** |

### The money screen

`GET /api/v1/money` lays out where the household's money stands on its date
(`kako/engine/money.py`, pure, then `kako/planning/money.py` writes it in words). These are not
figures: nothing is stored, no figure's value changes and no agent sees them. Each is worked out
from the same snapshot and run as the figures, with the same rules (no guessing, open entities,
half up to the centavo). A value the snapshot doesn't have stays unknown, and so does every number
built from it.

| Id | What | Definition |
| --- | --- | --- |
| `M-1` | The month's plan, line by line | Take-home pay first (each `income.monthly_net`, by name), then each expense (essential first, largest first), each debt's minimum in strategy order, each extra `plan.allocation` to a debt in the same order, then the allocations to accounts and to goals (only those above ₱0). Each line keeps what is left after it: the pay so far less every line so far. What is left after the last line is F-ALLOC-1, `plan.unallocated` |
| `M-2` | Where each peso goes | The lines of M-1 in four parts: needs (essential expenses), wants (the other expenses), debt (minimums and extras), savings (allocations to accounts and goals), and what isn't planned yet (`plan.unallocated` when above zero). A plan that goes over the pay has no unplanned part and says by how much. Each part's share of the pay is rounded half up to a whole percent |
| `M-3` | Each debt's schedule | F-DEBT-2's months for each open debt, one row each: the month (as-of + *k* months), what was owed, the interest, the payment, the principal (payment − interest) and what is left. The month a paid-off debt's payment rolls in shows the amount rolled in (the payment less its own scheduled payment) and the debt it came from. The totals are the payments, the interest (F-DEBT-2's `debt.total_interest`) and the principal. A debt that never pays off keeps its first 12 months, to show why |
| `M-4` | Where the household stands | What it owns: each open account's `account.balance` and each open goal's `goal.saved_amount`. What it owes: each open debt's `debt.balance`. Net worth is owned − owed, each with the date its fact took effect |
| `M-5` | The milestones ahead | The emergency fund at its target (F-SAV-3), each debt paid off (F-DEBT-2) and each goal reached (F-GOAL-1, with F-GOAL-3's on track), each with its date and the months until then, soonest first. One already reached, or with no date, is left out |
| `M-6` | The plan before its last change | The latest `valid_from` among the facts M-1 reads (pay, expenses, minimums, allocations) on or before the as-of date. When any such fact took effect before it, M-1 is also worked out the day before, and each line of today's plan says what it was then (`was ₱52,000.00`) or that it is `new` |

The screen also shows the household's four headline numbers (F-INC-1, F-CF-1, F-SAV-1 and M-4's net
worth), 13th-month pay (`income.thirteenth_month`, in December of the as-of year), the facts that
take effect after the as-of date, and the decisions in force with how many of their assumptions are
to revisit.

### Before and after an option

`GET /api/v1/plans/{id}/compare` sets each of a plan's options beside today's plan, so the
household sees what an option changes instead of reading it (`kako/engine/compare.py`, pure, then
`kako/planning/compare.py` writes it in words; `kako/db/compare_read.py` reads it). Like the money
screen, these are not figures: nothing is stored and no agent sees them.

**Today's plan** is the turn's own run: the snapshot the turn read (its `calc_run.as_of_date` and
`known_at`), taken again. Facts are never overwritten, so it is the same snapshot; its hash must be
the stored run's `snapshot_hash`, or the options are not compared (409) rather than compared on
other facts. **Each option** is that snapshot with the option's allocations (each
`recommendation.allocation` with its entity) as `plan.allocation` overrides from the as-of date,
exactly the what-if the agents ran; any allocation the option doesn't name stays as today's plan
has it. For a replan, today's plan is the plan as it stands after the change the household
approved, so each option is set beside what happens if nothing else changes.

| Id | What | Definition |
| --- | --- | --- |
| `C-1` | What each run reaches | Read from the run's figures, in a fixed order: each open debt in strategy order, paid off (F-DEBT-2's months and `debt.payoff_date`) then its interest (`debt.total_interest`); with more than one debt, the interest on every debt (their sum, unknown when any one is); the emergency fund at its target (F-SAV-3, its date the as-of date + its months); each goal reached (F-GOAL-1), by name; and what is left unplanned (F-ALLOC-1). A payoff or target with no months is **never** reached when its flag is `never_pays_off` or `no_allocation`, and **unknown** for any other reason (a missing fact) |
| `C-2` | What the option changes | Each outcome of C-1 against the same outcome in today's plan. A payoff or target: today's months − the option's, **sooner** when above 0 and **later** when below (better and worse), **reached** where today's plan never gets there (better), **never** where today's plan does (worse), **the same** when equal or both never. Interest: today's − the option's, **less** (better) or **more** (worse). Unknown on either side: nothing to compare. What is left unplanned changes but is neither better nor worse: it is the household's to plan |
| `C-3` | Month by month | Each open debt's schedule with the option (M-3), each month beside its balance in today's plan that month (0 once today's plan has paid it off; none past the first 12 months of a debt today's plan never pays off), and what today's plan still owes in the option's last month. The emergency fund's climb with the option: for each month *k* to F-SAV-3's months (at most 120), the liquid balance (F-SAV-1's) + *k* × the fund's allocation, and what is still short of the target; none when the option puts nothing into the fund, the fund is already there, or there is not exactly one emergency fund |

The session screen shows each option's dates and the interest on every debt (a single debt's own
interest when there is one debt) on its card; a row no run can tell (every value unknown) stays off
the card and in the table.

## Validation rules

Checked by code before a write, and as a suite over the whole database in CI.

| Rule | Check |
| --- | --- |
| V-01 | Exactly one `value_*` column is set on a fact, and it matches the attribute's type |
| V-02 | For one entity and attribute, the validity windows of `active` and `replaced` facts never overlap |
| V-03 | A replacement chain has no gaps: `replaced_by.valid_from` equals the old fact's `valid_to` |
| V-04 | `replaced_by` and `replaces` agree in both directions |
| V-05 | A retracted fact has `retracted_at` and a reason, and no snapshot after `retracted_at` includes it |
| V-06 | `valid_from` is on or after the entity's `opened_on`, and before its `closed_on` |
| V-07 | Money facts are never negative (a debt is a positive balance). Rates are between 0 and 1 |
| V-08 | Every non-seed fact, decision and life event has an approved proposal; a fact is exactly the write its proposal names, and a proposal writes one fact at most. A seed fact has no proposal and replaces nothing |
| V-09 | Every number in a proposal appears in its quoted evidence (checked before a proposal is stored; what counts as the same number is under `proposal_evidence`) |
| V-10 | Every number in a reply, recommendation, summary or reconciliation text matches a figure of the plan's run or of one of its turn's what-ifs, a fact in its snapshot, a what-if's allocation, or a number the household wrote in the turn (the number check, `agents/numbers.py`). Dates (in any common form, each read as one date), months, years, percentages, counts and spelled-out numbers with a unit ("nine months") are checked too; a value written at a lower precision is the figure rounded half up to it, and a negative figure matches its amount. Other spelled-out numbers aren't checked. Never a match: a number run into letters, one with a multiplier (`150k`, `₱2M`, "12 thousand") or more than 6 decimals. A bare number from the household's message is a count, and an amount only from ₱100. A fact matches by its value and by the date it took effect. In a turn that proposed a change (`propose_change`), its values and dates match too: they are the household's words, checked. In a replan, so do the figures of the run the household last decided on and the old and new facts of each change and decision to revisit. A specialist's summary (read by the orchestrator, and shown in the agents' steps) may name the turn's own refs exactly; the reply, the options and the reason may not |
| V-11 | Every recommendation has at least one `figure` source and one non-figure source (a fact, memory, decision or document) |
| V-12 | `plan.unallocated` is not negative |
| V-13 | Each `meko_link` to a memory points to a memory that exists, and one Kako wrote says what Kako wrote; each to a promoted memory is among the promoted memories Meko lists (its newest 20; one beyond them isn't checked) with the words shared; each to a document is uploaded and hasn't failed to index (`kako meko check`, against Meko, not on every write; it also reports upkeep still owed, an approved promotion not yet shared included) |
| V-14 | Every memory Meko extracted from a session that dreaming has run on is either linked to an approved fact in `meko_link` or deleted; one still waiting on a pending proposal is not yet a failure (`kako dream check`, against Meko, not on every write; it also finds a memory extracted after the run) |
| V-15 | Every `decision_option.tags` value is on the fixed tag list |
| V-16 | At most one active `account.purpose` = `emergency` fact per household on any date |

## Worked example: a new job

The Villanueva household, synthetic: Mara (34), Jun (36) and Lia (5). Every figure below is computed
by the engine's formulas; the build checks these numbers in a test.

**Before: plan v2, Sep 15, 2026.** Take-home pay ₱100,000 a month (Mara ₱52,000, Jun ₱48,000).
Expenses ₱76,000, of which ₱70,000 essential. The emergency fund is the account with `account.purpose` =
`emergency`; the household's `preference.debt_strategy` is `avalanche`. Minimum payments ₱14,950 (credit card ₱2,550, car loan
₱12,400). Surplus **₱9,050**. Credit card ₱85,000 at 3% a month; car loan ₱420,000 at 9% a year, so the
card is first in avalanche order. Emergency fund ₱150,000, a runway of **2.1 months** against a 3-month
target, reached in **12 months** at ₱5,050 a month.

The debt question had two options:

| Option | Extra on the card | To the emergency fund | Card paid off in | Interest |
| --- | --- | --- | --- | --- |
| A: all extra on the card | ₱9,050 | ₱0 | 9 months | ₱12,460.10 |
| B: split (chosen) | ₱4,000 | ₱5,050 | 17 months | ₱24,303.62 |
| Minimum only | ₱0 | | 47 months: ₱2,550 only covers the interest, so the balance stands still until the car loan is paid off in month 40 and its ₱12,400 rolls over | ₱111,635.47 |

The household chose B: "Lia starts school and we want cash on hand." Option A is kept with its reason
for rejection. They had already kept a larger cash buffer in August, and in October they chose
flexibility a third time (keeping cash for a family trip). After that session dreaming proposed the
pattern as a preference (`preference.debt_vs_flexibility` = `flexibility`); they approved it, and it was
promoted to collective memory.

**The event: Nov 20, 2026.** Mara (the speaker on the evidence) reports a new job from Dec 1 at ₱68,000 take-home. Dreaming proposes a
`life_event` (`new_job`, Dec 1) and a `replace_fact`. On approval:

| Fact | `valid_from` | `valid_to` | `status` | `replaced_by` |
| --- | --- | --- | --- | --- |
| Mara's salary, `income.monthly_net` = ₱52,000 | 2026-03-01 | 2026-12-01 | `replaced` | the new fact |
| Mara's salary, `income.monthly_net` = ₱68,000 | 2026-12-01 | null | `active` | null |

The Nov statements set the card at ₱76,880.00, the car loan at ₱401,430.63 and the emergency fund at
₱160,100 (new `debt.balance` and `account.balance` facts, each replacing the last; the Oct statements
did the same).

**After: plan v3, as of Dec 1, 2026.** Income ₱116,000; surplus **₱25,050**. The debt specialist reads
the promoted preference and does not put everything on the card; the orchestrator records the option it
rejected:

| Option | Card extra | Emergency fund | House fund | Card paid off in | Interest |
| --- | --- | --- | --- | --- | --- |
| All extra on the card (rejected: against the household's preference for flexibility) | ₱25,050 | ₱0 | ₱0 | 3 months | ₱4,620.01 |
| Plan v3 | ₱10,000 | ₱10,000 | ₱5,050 | 7 months | ₱9,358.80 |

Runway is **2.3 months** (₱160,100 ÷ ₱70,000), and the 3-month target (₱210,000) is reached in
**5 months**, against 12 in plan v2 at ₱5,050 a month. With the card paid off in month 7, its ₱12,550
rolls to the car loan, which is paid off in 22 months (₱38,914.35 of interest), against 32 months
(₱58,333.22) in plan v2.

**The diff Kako explains (F-DIFF-1):** income +₱16,000 because one fact was *replaced* by the new job;
surplus ₱9,050 → ₱25,050; card extra ₱4,000 → ₱10,000; emergency target in 5 months, not 12; a new
₱5,050 a month for the house. The three decisions of Sessions 1 to 3 (the bigger buffer, "split the
surplus" and the trip) each rested on Mara's old salary, so all three are listed **to revisit**, and
plan v3 explains why it still leans toward flexibility, citing the promoted preference and the October
session where it was learned. (Session 4's replan, on Nov 20, compares against the latest decision,
Session 3's of Oct 18: the decision the household last made.)

## Demo dataset

`data/demo-household/` holds the synthetic household as files. `kako demo load` loads them through the
same fact store a real household uses (`backend/src/kako/demo/`), in one transaction, into a database
that doesn't hold the household yet:

- `household.csv`, `people.csv`, `entities.csv`: who the household is and what it has. An entity is
  named by a short key (`card`, `mara_salary`) that the other files use.
- `facts.csv`: the seed, the household before session 1, with `valid_from` dates from March 2026. Seed
  facts have `source_kind` `seed` and no proposal, and are recorded at midnight UTC on the household's
  `as_of_date` (Aug 1, 2026).
- `changes.csv`: what happened after, in order of `recorded_at` (with its time zone). Each row is one
  proposal an adult approved (`decided_by`): a new or replaced fact, a preference pattern, or a life
  event, with the explanation the household saw. Loading writes the approved proposal, then exactly
  the fact it names (V-08); a fact may name the life event it belongs to. `--through` stops the replay
  at a point in the story (without it, only the seed is loaded). The 18 changes are the worked example:
  plan v2 (Sep 15), the Oct and Nov statements, the October preference pattern (row 6, from Oct 18,
  Session 3's day), the new job (Nov 20) and plan v3 (Dec 1). Rows 10 and 11, the new job, are the
  ones session 4 writes: their `source_ref` is its turn (`s4:t1`).
- `decisions.toml`: the decisions of the story, each written right after the change it follows
  (`after`, a seq, at the same `recorded_at`) or, with no `after`, in its own moment, in time order
  with the changes (it may not share a change's `recorded_at`): its session's title and date, who
  decided (an adult),
  the question, the reasoning and quote in the household's words, the chosen option's label, the date
  it takes effect, and every option with its tags (from `decision_option.tags`' fixed list) and, for
  each rejected one, the reason. Loading writes a session row, then a `decision` proposal approved by
  that person at that moment, with the facts it rests on as known then. Three decisions, each
  choosing cash on hand: Jun's "B: bigger buffer" in Session 1 (Aug 15), Mara's "B: split" in
  Session 2 (Sep 15) and Jun's "B: keep it for the trip" in Session 3 (Oct 18). Session 4's replan
  lists all three to revisit.
- `learning.toml`: what dreaming learns in the story between sessions, for demo mode (`kako demo
  run`): the session it dreams over (Session 3) and when, the `changes.csv` row its pattern must be
  (row 6, which demo mode leaves out of the load and lets dreaming propose; its `decided_by` approves
  it at its `recorded_at`), and who confirms the sharing and when (`promote`, Jun at 9:30 PM on Oct
  20). Demo mode plays it before the first session after that time: the dreaming run (code finds the
  pattern; no model call), the approval, each `promote` it offers approved with its second
  confirmation, and each shared in Meko. Checked against the story when read.
- `statements/*.csv` (synthetic monthly bank, card and loan statements, cited by each statement fact's
  `source_ref`, and uploaded to the knowledge base),
- `kb/*.md` (planning rules and plain-language reference: 13th-month pay, SSS, Pag-IBIG, emergency funds).

Money is written in pesos with two decimals and read as exact centavos; a rate is a decimal fraction.
Every file is checked before anything is written, and an error names the file and line.

- `sessions/*.toml`: the scripted sessions demo mode replays (`backend/src/kako/demo/sessions.py`). Each
  names its title, the household's date (`on`), what Kako knew then (`known_at`, with its time zone, so
  a database holding the whole story answers as it would have then), its recording (a file name in
  `data/recorded/`) and its turns, each with the speaker (a key in `people.csv`), a seed unique across
  the sessions, and the message. A turn may also name its own `known_at` (never before what the
  session knew already), and an `approve` step after it: `{ by = <an adult's key>, at = <time with its
  zone> }`, the adult approving everything the turn proposed, at that moment in the story. A session
  whose approvals write rows of `changes.csv` lists them in `writes` (their seq): each is a fact or a
  life event recorded at one of its approvals, a life event's facts go with it, and no two sessions
  write the same row. Demo mode loads the story without them, and after the session checks that its
  own approved proposals wrote each one as the row has it (kind, entity, attribute, value, date). On a
  database that holds them already, the session isn't replayed again. Sessions 2 and 4 are written;
  sessions 1 and 3 join with dreaming, both adults taking part, and dreaming is tested on them too.

`data/recorded/` (beside the demo folder) holds model responses recorded on Foundry, keyed by turn seed,
agent and call number, and checked against each request's digest when replayed: `session-2.json` and
`session-4.json` for sessions 2 and 4 (`kako demo record <session>` records one on Foundry), and `test-set-specialists.json` and `test-set-single.json` for the agent test set. Each
recording is logged in `docs/tuning-log.md`. `data/test-set/questions.toml` is the agent test set:
each question's date, `known_at`, message, why it is in the set and what a good answer must hold
(`backend/src/kako/evals/`); `data/test-set/results/` keeps each architecture's last full run.
`data/dreaming/labelled.toml` is dreaming's labelled set: scripted sessions on the demo household, each
with its date, `known_at`, the turns (who said what) and the proposals dreaming must make (`expect`), may
make (`maybe`) or must not make. `kako dream eval` scores it (`backend/src/kako/evals/dreaming.py`) from
the recording `data/recorded/dreaming.json`, or on Foundry with `KAKO_MODEL_MODE=record`; `--save` keeps
the last run in `data/dreaming/results.json`.

No real person, bank, employer or account. Names are fictional; amounts are plausible, not sampled.
