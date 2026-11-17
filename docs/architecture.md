# Architecture

How Kako is built: the parts, how one planning turn and one life event flow through them, how Kako uses
each part of Meko, the controls that keep numbers and memory honest, where it runs and what it costs.
**Code follows this document.** If code and this document disagree, raise it, and update this document
in the same change once agreed.

Tables and formulas are in [data-model.md](data-model.md). The order of work is in
[build-plan.md](build-plan.md). Meko facts here were checked on Nov 17, 2026 against local Meko
1.20261116.0 (its MCP tools, by calling them) and Meko's agent skills plugin v2.6.1 (its tool
references); limits change, so check again before relying on one.

## In one paragraph

Kako is a **Next.js** web app in front of a **FastAPI** backend. The household talks to Kako in
planning sessions; each session is a **Meko conversation**, so every turn and every Meko call is traced.
The household's structured data lives in **Postgres** as facts with a validity window and a replacement
chain, and a **deterministic engine** computes every peso, month and date from a snapshot of those
facts. An **orchestrator** agent answers each turn by calling four **specialists** (budget, debt,
savings, goals) as tools; they read the engine's figures and a context brief built from Meko's memory,
knowledge base and past conversations, and propose moves. Code checks the proposals against the surplus
and against each other; the orchestrator resolves conflicts in the open, and a **number check** blocks
any figure the engine did not produce. After each session a **dreaming** job reviews the conversation,
reconciles what it heard with what is known, marks what has been replaced, spots patterns, and puts
proposals in front of the household. Approved facts become Meko memories; approved preferences and
decisions can be promoted to the datapack's **shared knowledge**, where every specialist finds them.

## Diagram

```mermaid
flowchart LR
  subgraph Web["Next.js (web/)"]
    UI[Session, plan and why,<br/>timeline, decisions,<br/>approvals, what-if, metrics]
  end

  subgraph API["FastAPI backend (backend/)"]
    R[Routes /api/v1]
    ORC[Orchestrator]
    SP[Specialists<br/>budget, debt, savings, goals]
    BR[Brief builder]
    NC[Number check]
    REC[Reconciliation rules]
    ENG[Engine<br/>pure, centavos]
    FS[Fact store<br/>snapshots, replace, retract]
    DR[Dreaming worker]
    MM[Model manager]
    MA[Meko adapter]
  end

  PG[(Postgres<br/>local, then AMP or Neon)]
  CL[Claude<br/>Anthropic API]

  subgraph Meko["Meko datapack (local for dev, Meko Cloud for the demo)"]
    CONV[Conversations<br/>and traces]
    MEM[Memories]
    SK[Shared knowledge<br/>promoted memories]
    KB[Knowledge base<br/>statements, rules, reference]
    ART[Artifacts<br/>plan reports]
    SL[Self-learning<br/>weak searches]
  end

  UI --> R
  R --> ORC
  ORC --> SP
  ORC --> BR
  SP --> BR
  BR --> FS
  BR --> ENG
  BR --> MA
  ORC --> REC
  REC --> ENG
  ORC --> NC
  ENG --> FS
  FS --> PG
  R --> FS
  DR --> FS
  DR --> MA
  ORC --> MM
  SP --> MM
  DR --> MM
  MM --> CL
  MA --> CONV
  MA --> MEM
  MA --> SK
  MA --> KB
  MA --> ART
  MA --> SL
```

## How one planning turn flows

1. **The household writes** in the session screen. The API appends the turn to the session's Meko
   conversation when the answer is ready (step 8), with a stable seed so a retry stores it once.
2. **Snapshot and figures.** The fact store builds the snapshot for the household's date. If its hash
   differs from the last calculation run, the engine computes a new run; otherwise the last run is
   reused. The engine is pure: same snapshot in, same figures out.
3. **The brief.** Code builds a context brief within a size budget (about 3,000 tokens): the key
   figures, the active decisions with their reasons, approved preferences and constraints, pending
   proposals, and the results of **one** `context_search` on the household's message (memories, shared
   knowledge and documents, past conversations). Specialists start from this brief instead of searching
   on their own, which keeps the answer grounded and the Meko call count low.
4. **The orchestrator** reads the brief and calls the specialists it needs as tools, in parallel. It can
   also propose a fact or a life event the household just stated (see the next section).
5. **Each specialist** is a short, bounded loop (at most 4 tool calls) over read-only tools:
   `get_figures`, `get_facts`, `get_decisions`, `search_memory` (one extra Meko search at most) and
   `run_what_if` (the engine with hypothetical allocations). It returns a structured proposal: the
   allocation it wants, its recommendation text, and the sources it cites.
6. **Reconciliation in code.** The engine runs once more with all proposed allocations together. Rules
   find over-allocation (the asks add up to more than the surplus), opposite moves, and goals that miss
   their date. Each conflict goes back to the orchestrator with the figures, and its resolution and the
   option it rejected are recorded and shown.
7. **The number check.** Every number in the reply, the recommendations and the resolutions must match a
   figure of the run or a fact in the snapshot (rule V-10). A failure is regenerated once with the
   mismatch named; if it fails again, the reply is shown with the unmatched numbers flagged, never
   silently.
8. **Recorded.** The reply goes to the household with a "why" link on each recommendation. The turn goes
   to Meko with the orchestrator's `plan` (its steps) and `reasoning`, and metadata naming the plan,
   run and recommendation ids, so the Meko trace and Kako's own sources say the same thing. The plan is
   `proposed` until the household accepts it; accepting writes the `plan.allocation` facts.

## How a life event replans

This is the centre of the live demo.

1. Mara says she has a new job from Dec 1 at ₱68,000 take-home. The orchestrator calls
   `propose_life_event` and `propose_fact_change`; the backend creates **pending proposals** with the
   quoted words as evidence, and the session shows an approval card at once. (Dreaming would find the
   same thing after the session; proposals have an idempotency key, so it can't be proposed twice.)
2. The household approves. The fact store inserts the new fact, closes the old one (`valid_to` = Dec 1,
   `status` = `replaced`, `replaced_by` = the new one) and records the life event. The Meko adapter adds
   the new memory and rewrites the old one in the past tense.
3. The fact store lists what the event touches: the facts it changed, the calculation inputs that read
   them, and the **decisions whose assumptions** included a replaced fact ("to revisit").
4. The engine computes a new run. The orchestrator asks every specialist whose figures moved to reassess,
   with the decisions to revisit and the preferences in the brief.
5. Kako answers in three parts: **the new plan**; **what changed** (the diff between the last accepted
   plan's run and the new run, each change labelled replaced, retracted, new or allocation, rule
   F-DIFF-1); and **why**, citing the facts, the promoted preference, the earlier decision and the
   session it came from. The plan report is kept as a Meko artifact.

## How dreaming works

A background job queued when a session ends (`dream_run`, one per session, so a rerun does nothing).

1. **Read** the session's turns from Meko (`conversation_get`), the snapshot, the active decisions and
   the pending proposals.
2. **Extract** candidate claims with the model, as structured output: the entity, the attribute, the
   value **as quoted**, when it takes effect, and the quote. The model copies; it does not calculate.
3. **Check in code.** Every number in a candidate must appear in its quote (V-09). The candidate is
   matched to an entity and attribute in the catalog, and compared with the snapshot: **same** (dropped),
   **new**, **replace** (a later value for the same thing), **retract** (the household said an earlier
   value was wrong) or **conflict** (two values for the same day; asked as a question).
4. **Patterns.** Code counts the household's decisions by the tag of the option they chose (such as
   `favours_flexibility`). Three choices the same way across at least two sessions, with none the other
   way, produce a `preference_pattern` proposal, citing each decision and session.
5. **Promotion candidates.** An approved preference or decision that has held for two sessions is
   proposed for promotion to shared knowledge, with the plain warning that promotion can't be undone.
6. **Propose.** Everything lands in the approvals inbox with an explanation and its evidence. Nothing
   becomes household knowledge until a person says yes.
7. **On approval**, the fact store writes the rows and the Meko adapter brings Meko in line: add the new
   memory, rewrite a replaced one, delete a retracted one, promote what was approved for sharing.

Dreaming is tested against a labelled set: scripted sessions with the facts, replacements and patterns
a person would expect, scored for what it found, missed and wrongly proposed.

## How Kako uses each part of Meko

| Meko part | Kako's use | Where it shows |
| --- | --- | --- |
| Conversations | One per planning session, turns stored with `plan` and `reasoning` | Session history; dreaming's input |
| Decision traces | The conversation id is the trace id; every Meko call in the session is a span under it | "Open trace" on each recommendation (Meko Cloud's Observe for the demo) |
| Memory | One sentence per approved fact, decision and preference, with Kako's ids in its metadata; replaced facts rewritten in the past tense | Specialists' context; the timeline |
| Learning (promotion) | Dreaming proposes, the household approves, Kako promotes to shared knowledge | "Learned on Oct 18 from the October session" in the why panel |
| Knowledge base | Synthetic statements (CSV), planning rules and Philippine reference documents (Markdown) | Cited excerpts in the why panel |
| Artifacts | Each plan report | Download on the plan screen |
| Postgres in the datapack (AMP) | The household's structured data, if the Phase 1 test passes; a scenario kept as an AMP branch (Should) | Architecture slide; what-if screen |
| Context Gaps (self-learning) | Weak searches turned into questions for the household (Should), if the tools are available to us | "Kako would like to know" card |
| Metrics | `datapack_metrics` (context size, efficiency, relevance) next to Kako's own token and number-check counts | The metrics page |

What Meko does not do, and Kako adds (see [concept.md](concept.md#what-meko-already-does-and-what-kako-adds)):
Meko keeps both "₱100,000" and "₱120,000" as memories and returns both (tested); Kako decides which is
current, what it replaced and which plans and decisions depended on it.

## Components

| Component | Where | What it does |
| --- | --- | --- |
| Web app | `web/` | Next.js App Router, TypeScript strict, Tailwind and shadcn/ui. Rewrites `/api/v1/*` to the backend. Never sees database rows, only response schemas |
| API | `backend/src/kako/api/` | FastAPI routes under `/api/v1`: sessions and turns, plans, why, diff, facts timeline, decisions, proposals and approvals, what-ifs, metrics |
| Engine | `backend/src/kako/engine/` | Pure functions from a snapshot (and optional hypothetical allocations or overrides) to figures. No database, network, clock or randomness; a lint rule enforces it |
| Fact store | `backend/src/kako/facts/` | The attribute catalog, snapshots (`on`, `known_at`), replace and retract, what an event touches |
| Planning | `backend/src/kako/planning/` | Plans, recommendations and sources, reconciliation rules, diff, what-ifs |
| Decisions | `backend/src/kako/decisions/` | Decision records, options, assumptions, "to revisit" |
| Agents | `backend/src/kako/agents/` | `model_manager.py` (the only module that imports the Anthropic SDK), orchestrator, the four specialists, brief builder, tools, number check, prompts |
| Dreaming | `backend/src/kako/dreaming/` | The job, extraction, classification, patterns, proposals |
| Meko adapter | `backend/src/kako/meko/` | One interface for every Meko call, an MCP client implementation, an in-memory fake for unit tests, the call counter and quota guard |
| Database | `backend/src/kako/db/` | SQLAlchemy 2 async models, repositories, Alembic migrations |
| Settings | `backend/src/kako/settings.py` | `pydantic-settings`: database URL, Meko URL and key, model names, budgets |
| Demo data | `data/demo-household/` | The synthetic household, statements, documents and session scripts |

The backend is organised by domain, with `core → domain → infrastructure`: the engine and fact rules
never import the database, Meko or the model SDK.

## Agents

| Agent | Job | Tools | Writes |
| --- | --- | --- | --- |
| Orchestrator | Reads the brief, decides which specialists to ask, resolves conflicts, writes the answer, proposes facts and events the household stated | The four specialists, `get_figures`, `get_facts`, `get_decisions`, `propose_fact_change`, `propose_life_event`, `propose_decision` | Pending proposals only |
| Budget | Spending against income; where the surplus comes from | Read tools, `run_what_if` | Nothing |
| Debt | Payoff order and extra payments, respecting preferences | Read tools, `run_what_if` | Nothing |
| Savings | Emergency runway and target | Read tools, `run_what_if` | Nothing |
| Goals | Goal dates, required contributions, trade-offs | Read tools, `run_what_if` | Nothing |
| Dreaming | Extracts claims from a finished session | None (structured output only) | Pending proposals, through code |

Bounds: at most 4 specialist calls per turn, at most 4 tool calls per specialist, one extra Meko search
per specialist, a token budget per turn, and a daily spend cap in settings. Model names live in
settings only; the orchestrator and dreaming use the stronger model and the specialists a faster one,
confirmed in Phase 3 by the agent test set.

**Prompts and context.** Each prompt is short and sectioned: the role, the one rule (the engine
calculates, agents explain and propose, the household decides), a glossary of figure keys, the tool
contract and one worked example. Stable parts come first so prompt caching applies. Conversation text,
memories and documents are wrapped as data, never as instructions.

## Where data lives

| | Development and tests | Demo |
| --- | --- | --- |
| Meko | Local Meko (`MEKO_MCP_URL=http://127.0.0.1:7777/mcp`); in CI, the same release installed from GitHub | Meko Cloud, one datapack for the demo household |
| Postgres | Local Postgres (Docker; on Windows inside WSL), a fresh database per test run | AMP in the demo datapack if the Phase 1 test passes; otherwise a free managed Postgres (Neon) |
| Model | The Anthropic API with a small dev budget; unit tests use a recorded fake | The Anthropic API |
| Backend and web | `uvicorn` and `next dev` on the laptop | The laptop too: the video is recorded locally against Meko Cloud. No hosted app (Pim, Nov 17) |

**AMP constraints** (from Meko's AMP reference): a database is reached from outside Meko only through
an `ingress_external` endpoint with an allow-list of `/32` source addresses chosen at create time, so the
laptop's public IP goes on the allow-list (and is checked again before recording); creating a branch or compute can block for up to 5 minutes; only the
datapack owner can create them; compute counts against a per-account vCPU cap. So what-ifs run in the
engine in memory, always, and keeping one as an AMP branch is an optional step done ahead of time, never
on the click path.

## Controls

| Control | How |
| --- | --- |
| No numbers from a model | The engine computes; agents read figures; the number check (V-10) blocks the rest; dreaming copies quoted numbers only (V-09) |
| No silent overwrite | Facts are insert-only apart from the status transitions in the data model; a database trigger rejects other updates and deletes |
| A person decides | Every fact, event, decision, preference and promotion starts as a proposal; promotion asks twice because it can't be undone |
| Traceable advice | Every recommendation has a figure source and a non-figure source (V-11), and its Meko turn |
| Prompt injection | Session text, memories and documents are passed as data; agents have read tools and `propose_*` tools only; nothing an agent says can write without approval |
| Spend and quota | Token budget per turn and a daily cap; a Meko call counter with a ceiling per environment, so rehearsals can't use up the Free tier's lifetime allowances |
| Not financial advice | Synthetic household only; the app and README say so; no product picks, no tax calculations |
| Secrets | Environment variables only; `.env` is gitignored and `.env.example` lists the names |

## Cost plan

| Item | Plan | Recurring cost |
| --- | --- | --- |
| Meko | Free tier; local Meko for development | None. The lifetime allowances below are the real limit |
| Postgres | Local; AMP (Free) or Neon (free) for the demo | None expected |
| Anthropic API | Pay as you go, with a per-turn budget and a daily cap; prompt caching; tests use a recorded fake | Usage only. The cap is set before Phase 3 and reported on the metrics page |
| Hosting | None: the demo runs on the laptop for the video | None |
| CI | GitHub Actions on a public repository | None |

**Meko Free-tier lifetime allowances** (account-wide, from Meko's tool reference, Nov 2026): 1,000
each of `memory_search`, `knowledgebase_search`, `context_search` and `conversation_add_message`; 10,000
`memory_add`; 1,000 conversations. A demo session of about 8 turns uses about 8 conversation turns, 8
to 16 searches and a few memory writes, so seeding sessions 1 to 3 once and rehearsing session 4 about
ten times stays well under every limit. The call counter enforces it.

## Production path (documented, not built)

Per-person privacy (each adult's private memories, shared household knowledge) needs Meko's shared
datapacks and roles, which are Pro only. Real households would also need bank-statement import with
consent, encryption of personal data at rest, and deletion on request. None of this is in the MVP.
